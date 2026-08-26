---
phases: [tasks]
---

# Design: demo-tenant-audit-retention

## Context

El `audit_logs` del tenant demo es la única tabla nightly-reset que no se reduce
(`backend/app/cli/demo_reset.py:113-117`, R3.6 de `demo-user`), y cada reset le añade
filas de convergencia por cuenta (`backend/app/cli/demo_reset.py:625-647`,
`AuditLogFactory.build` con `actor_user_id=None`). La estructura ya tiene el esqueleto
para una fase post-commit: `run()` (`backend/app/cli/demo_reset.py:1048-1077`) ejecuta
`storage-sweep` y `clear-lock` **fuera** de la transacción del reset y degradan con
`notes` en vez de abortar — el mismo patrón que sirve para `purge-audit`. El corte
por antigüedad puede apoyarse en `audit_logs.created_at`, ya indexado en
`ix_audit_logs_tenant_id_actor_user_id_created_at` (`backend/app/audit/infrastructure/models.py:41-45`),
cuyo prefijo izquierdo `(tenant_id)` cubre la parte selectiva de la consulta del purgado
(el `WHERE created_at < :cutoff` se evalúa sobre las filas así acotadas). La auditoría
del propio purgado tiene que pasar por `AuditLogFactory.build`, que valida `entity_type`
contra `actions.ENTITY_TYPES` (`backend/app/audit/domain/services.py:55-64`) — `AUDIT_LOG`
**no** está en el vocabulario cerrado, así que escribir la fila requiere ampliarlo.

## Decisions

### D1 — Constante `DEMO_AUDIT_RETENTION_DAYS = 7` al nivel del módulo

**Chosen:** constante de módulo en `backend/app/cli/demo_reset.py`, junto a
`DEMO_TENANT_NAME`, `PASSWORD_MIN_LENGTH` y compañía.

Why: el periodo es una decisión de ingeniería, no de despliegue — sigue el patrón
del fichero y no introduce ni `Settings` ni variable de entorno (R1.2 del proposal).
Rejected: `Settings`/env (R1.2 lo prohíbe explícitamente; "Settings" se reserva
para configuración del entorno, y el periodo de la demo no es eso).

### D2 — Fase `purge-audit` entre `storage-sweep` y `clear-lock`, fuera de la transacción

**Chosen:** nueva fase `purge-audit` insertada en `PHASES` (línea 134) entre
`storage-sweep` y `clear-lock`, ejecutada en `run()` (línea 1048) **después** del
cierre del `async with async_session_factory() as session:` y **antes** del
`async with _phase("clear-lock", ...)`.

Why: replica exactamente el contrato de `storage-sweep` y `clear-lock` (líneas
1061-1075): fuera de la transacción (Postgres y Redis/objetos no comparten
transacción, pero además la del reset ya está comprometida) y degradable con `notes`.
Rejected:
- **Dentro de la transacción** (entre `seed` y `clear-lock`): un fallo del `DELETE`
  revertiría el reset entero, contradice R3.4 ("ningún cambio parcial") y haría
  del purgado un motivo para abortar el comando que no lo justifica — el histórico
  que se purga es información de la que el sistema puede prescindir.
- **Antes de `prepare`**: el purgado previo al reset no aporta nada transaccional y
  desacopla la fase del resto del comando.

### D3 — Corte por `started_at` capturado en `prepare`, no por `NOW()`

**Chosen:** `prepare` lee `started_at = _now()` y lo expone vía `report.started_at`;
`purge-audit` calcula `cutoff = started_at - timedelta(days=DEMO_AUDIT_RETENTION_DAYS)`
y lo usa como único `WHERE created_at < :cutoff`.

Why:
- Determinista para tests: una `_now()` congelada produce un cutoff reproducible.
- Coherente con `_now()` (línea 708): el resto del comando usa una sola lectura de
  reloj por fase; el purgado hereda ese mismo reloj, no inventa otro.
- "Preservar las filas del último reset" sale gratis por la cuenta: las filas del
  reset previo tienen `created_at >= started_at - 1 day` (el reset corre diario),
  que es más nuevo que `started_at - 7 days`, así que la condición las conserva sin
  ningún discriminante explícito.

Rejected:
- `NOW()` en el SQL: no determinista, rompe el patrón de `_now()` del módulo.
- `started_at` capturado dentro de `purge-audit`: sería una segunda lectura del
  reloj y desplazaría el corte por minutos, suficiente para hacer fallar un test de
  borde a las 23:59:59.

### D4 — Vocabulario `ENTITY_AUDIT_LOG` + `ACTION_AUDIT_LOG_PURGED` + `AUDITABLE_FIELDS["AUDIT_LOG"]`

**Chosen:** añadir al vocabulario cerrado (R3.1 lo exige):

```python
# backend/app/audit/domain/actions.py
ENTITY_AUDIT_LOG = "AUDIT_LOG"
AUDIT_LOG_PURGED = "AUDIT_LOG_PURGED"
# y ambos en ENTITY_TYPES / ACTIONS, respectivamente
```

```python
# backend/app/audit/domain/value_objects.py
"AUDIT_LOG": frozenset({"deleted_count", "cutoff"}),
```

Why: `AuditLogFactory.build` (línea 60-64) rechaza un `entity_type` que no esté en
`ENTITY_TYPES`, y `ChangeSet` rechaza un campo fuera de `AUDITABLE_FIELDS`. La fila
de "se borraron N filas" es un evento real del sistema y necesita su propio
discriminante — no se puede reusar `ENTITY_USER` o `ENTITY_TENANT` porque la
semántica es otra.
Rejected:
- **No escribir la fila de auditoría** (incumplir R3.1): deja el purgado sin
  registro, contra el espíritu de la regla 11.
- **Reusar `ENTITY_TENANT`** (porque el purgado es del tenant): confunde dos
  cosas — `entity_id` es el recurso modificado, no el ámbito; además, el
  `ChangeSet` para `TENANT` no declararía `deleted_count` y `cutoff`.

### D5 — `DELETE` con SQL textual y bind params, sobre la sesión ya marcada

**Chosen:**

```python
async def purge_old_audit_logs(
    session: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime
) -> int:
    require_session_bound_to(session, tenant_id, write="the demo reset's purge-audit phase")
    result = await session.execute(
        text(
            "DELETE FROM audit_logs "
            "WHERE tenant_id = :tenant_id AND created_at < :cutoff"
        ),
        {"tenant_id": tenant_id, "cutoff": cutoff},
    )
    return result.rowcount
```

Why:
- La sesión ya está marcada al tenant demo (R1.3): `require_session_bound_to(session,
  tenant_id, write="the demo reset's purge-audit phase")` rechaza la operación si la
  sesión no está marcada al tenant demo o lo está a otro tenant — esa es la guarda
  **real** del scope del `DELETE` (R3 del security steering: la constante manda). El
  parámetro `:tenant_id` en el `WHERE` es redundancia explícita sobre esa guarda,
  redactada como defensa en profundidad visible: si el `require_session_bound_to`
  cambiara de contrato, el `WHERE` seguiría acotando el `DELETE` al tenant resuelto,
  y un test a nivel de SQL (`test_purge_old_audit_logs_refuses_a_session_bound_to_a_different_tenant`)
  pina ese comportamiento. **El listener de `app/core/db.py` no entra aquí** — su
  `do_orm_execute` solo cubre `select/update/delete` ORM, y el `text(...)` de este
  `DELETE` lo esquiva por construcción; mencionarlo como red sería atribuirle un
  alcance que su propio docstring (`backend/app/core/db.py:79-82`) excluye.
- Un solo statement atómico: la semántica es "borrar todo lo más viejo de N días",
  no "borrar uno a uno"; `rowcount` lo cuenta sin un `SELECT` adicional.
- SQL crudo en lugar del ORM (`delete(AuditLogModel).where(...)`): la consulta no
  usa el ORM para nada (no hay hidratación de filas a borrar), y el SQL directo es
  la forma explícita de "no se ejecuta nada fuera de este WHERE".

Rejected:
- ORM `delete(AuditLogModel)`: funciona, pero introduce una indirección sin
  beneficio — la consulta no materializa objetos, sólo cuenta.
- Borrar fila a fila con `SELECT … FOR UPDATE` seguido de `DELETE`: añadiría
  concurrencia sin motivo (no hay quien escriba `audit_logs` durante el purgado,
  el reset mantiene el aislamiento por la transacción ya comprometida) y
  bloquearía `audit_logs` entero.

### D6 — Fila de auditoría con `entity_id = uuid.uuid5(tenant_id, "demo-audit-purge")`, `actor_user_id=None`, `actor_ip=None`

**Chosen:**

```python
purge_audit_row = AuditLogFactory.build(
    tenant_id=tenant_id,
    action=actions.AUDIT_LOG_PURGED,
    entity_type=actions.ENTITY_AUDIT_LOG,
    entity_id=uuid.uuid5(tenant_id, "demo-audit-purge"),
    actor_user_id=None,
    actor_ip=None,
    changes=ChangeSet(actions.ENTITY_AUDIT_LOG).diff(
        "deleted_count", None, deleted_count
    ).diff("cutoff", None, cutoff.isoformat()),
    now=now,
)
await audit.add(tenant_id, purge_audit_row)
```

Why:
- `uuid.uuid5(tenant_id, "demo-audit-purge")` da un identificador estable por
  tenant — la fila del purgado de "este tenant" es siempre el mismo UUID, así que
  se puede filtrar/consultar sin ambigüedad.
- `actor_user_id=None` y `actor_ip=None` siguen el precedente de
  `converge_the_demo_passwords` (línea 642-643), `reset_password.py:103` y
  `seed_demo.py:1930, 2001`: un comando CLI no tiene identidad que registrar.
- `ChangeSet.diff()` exige pasar un valor previo (`None` aquí) y uno nuevo; para
  `deleted_count` y `cutoff` eso es coherente — son métricas que pasan de "no
  registradas" a "registradas con este valor".

Rejected:
- `entity_id = tenant_id`: la columna es el recurso modificado, no el ámbito del
  comando.
- `entity_id = uuid.uuid4()` aleatorio: pierde identidad — el purgado de "este
  tenant" dejaría de ser consultable como entidad.
- Synthetic actor `("system", "cli")`: requeriría cambios de esquema y un actor
  huérfano por todo el código que asume `actor_user_id` UUID.

### D7 — Degradación con `notes`, mismo contrato que `storage-sweep` y `clear-lock`

**Chosen:** envolver el cuerpo de `purge-audit` en un `try/except Exception` que
añade `f"purge-audit: failed with {type(exc).__name__} (detail withheld on purpose)"`
a `report.notes`. No relanza, no convierte en `PhaseError`.

Why:
- Mismo contrato que `clear_login_locks` (línea 661-705) — explícitamente "Never
  raises (D9.5)". La base está ya consistente por el compromiso previo; un fallo
  del purgado degradado es la verdad.
- `_phase("purge-audit", report)` no envolverá el cuerpo: cualquier `raise`
  dentro se convierte en `PhaseError` (línea 339-351), que es justo lo que NO
  queremos aquí. El bloque `try/except` vive **dentro** del `_phase`, igual que
  `clear_login_locks` está dentro de su `_phase`.

Rejected:
- Re-lanzar como `PhaseError`: cancelaría el run (exit 2) por un fallo no fatal,
  contradice R2.2 ("recoger el fallo como nota, no abortar la ejecución").
- Silenciar sin `notes`: perderíamos la huella del fallo, contraviene R2.3.

### D8 — Wire-up en `run()`

**Chosen:**

```python
# después de storage-sweep, antes de clear-lock
async with _phase("purge-audit", report):
    report.counts["audit_logs_purged"], note = await _safe_purge_old_audit_logs(
        report.tenant_id, report.started_at
    )
    if note is not None:
        report.notes.append(note)
```

Where `_safe_purge_old_audit_logs` envuelve `purge_old_audit_logs` con el
`try/except` de D7 y devuelve `(deleted_count, note | None)`.

Why:
- El `count` va a `report.counts` y sale por stdout con el resto (línea 1131-1135),
  igual que `seed_*` counts.
- El `note` (si lo hay) sale por stderr (línea 1136-1137), igual que las
  degradaciones de `storage-sweep` y `clear-lock`.
- `report.started_at` lo rellena `prepare`; si `prepare` no llegó a ejecutarse
  (por ejemplo, una fase anterior falló con `PhaseError`), `purge-audit` no se
  invoca porque `run()` solo entra al post-commit si `apply_plan` terminó — el
  flujo actual ya lo garantiza (línea 1057-1058).

Rejected:
- Una sola tupla de retorno `(count, error_message)` con `error_message = ""`
  en éxito: hace al llamante revisar dos campos con la misma semántica; dos
  return values distintos lo hacen explícito.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Demo command | `backend/app/cli/demo_reset.py` | Añadir `DEMO_AUDIT_RETENTION_DAYS = 7` cerca de `PASSWORD_MAX_BYTES` (línea ~104); añadir `"purge-audit"` a `PHASES` (línea 134-145); capturar `started_at = _now()` en `prepare` y exponerlo en `report.started_at`; añadir `started_at: datetime \| None = None` y `purged_audit_count: int = 0` al dataclass `DemoResetReport` (línea 295-335); implementar `purge_old_audit_logs(session, tenant_id, cutoff)` y `_safe_purge_old_audit_logs(tenant_id, started_at)`; wire-up en `run()` entre `storage-sweep` y `clear-lock` (línea 1061-1075) |
| Audit vocabulary | `backend/app/audit/domain/actions.py` | Añadir `ENTITY_AUDIT_LOG = "AUDIT_LOG"` y `AUDIT_LOG_PURGED = "AUDIT_LOG_PURGED"`, registrar ambos en `ENTITY_TYPES` (línea 340) y `ACTIONS` (línea 363) |
| Audit fields | `backend/app/audit/domain/value_objects.py` | Añadir `"AUDIT_LOG": frozenset({"deleted_count", "cutoff"})` al `Mapping` `AUDITABLE_FIELDS` (línea 111) |
| Test coverage | `backend/tests/cli/test_demo_reset.py` | Actualizar la aserción de `PHASES` (línea 703) y `assert first.phases == list(demo_reset.PHASES)` (línea 2177); añadir test del purgado con corte explícito (mockeando `_now()` o `started_at`); añadir test de la degradación (DELETE falla → nota + run verde); añadir test que el reset NO crea la fila de auditoría si `prepare` no se ejecutó |
| Audit vocabulary test | `backend/tests/audit/test_audit_log_vocabulary.py` *(nuevo)* | Sigue el patrón de `test_incident_photo_vocabulary.py`: assert `ENTITY_AUDIT_LOG in ENTITY_TYPES`, `AUDIT_LOG_PURGED in ACTIONS`, `"AUDIT_LOG" in AUDITABLE_FIELDS`, y un test de smoke (`ChangeSet(actions.ENTITY_AUDIT_LOG).diff("deleted_count", None, 0)` no levanta) |
| Spec | `sdd/specs/demo-tenant.md` | Enmendar la sección «Qué borra y qué preserva» (línea 109-117) para que la preservación de `audit_logs` cite la retención; añadir un nuevo bloque EARS con la fase `purge-audit` como sección hermana |
| Docs | `docs/demo-tenant.md` | Nueva sección «Retención del audit_logs» indicando periodo (7 días), cuándo corre (durante el reset diario), qué se preserva (filas del último reset, por construcción del corte) y la única forma de ver el histórico (descarga directa de la fila antes del siguiente reset, **no** soportada por el producto) |

## Data & interfaces

- **Schema**: sin cambios. `audit_logs.created_at` ya está indexado por
  `ix_audit_logs_tenant_id_actor_user_id_created_at`
  (`backend/app/audit/infrastructure/models.py:41-45`); el índice es
  `(tenant_id, actor_user_id, created_at DESC)`, y el prefijo izquierdo `(tenant_id)`
  basta para acotar la consulta del purgado — el `WHERE created_at < :cutoff` se
  evalúa sobre las filas así seleccionadas. Sin índice nuevo.
- **API REST**: sin cambios. No se exponen filas de auditoría hoy y este change no
  abre esa superficie.
- **Config / env**: sin cambios. `DEMO_AUDIT_RETENTION_DAYS` es constante del módulo
  por D1.
- **Eventos de timeline**: sin cambios. El purgado no genera `TimelineEvent` — la
  fila de `audit_logs` es suficiente.
- **Concurrencia con el cron de reset**: `demo-reset.yml` lleva `concurrency:
  deploy-dev` (R5.5 de demo-user) y el runner self-hosted no encola resets en
  paralelo, así que no hay solapamiento del purgado.

## Risks & mitigations

- **Ampliar `ENTITY_TYPES`/`ACTIONS`/`AUDITABLE_FIELDS` cambia un vocabulario
  cerrado.** Mitigación: la suite tiene patrón por entry
  (`backend/tests/audit/test_*_vocabulary.py`); tasks añade
  `test_audit_log_vocabulary.py` siguiendo `test_incident_photo_vocabulary.py`
  como plantilla.
- **Reordenar `PHASES` rompe `assert PHASES == (...)` y
  `assert first.phases == list(PHASES)`.** Mitigación: tasks actualiza esas dos
  líneas (703 y 2177) y añade cobertura de la nueva fase.
- **Fallo del purgado deja la BD parcialmente borrada.** Mitigación: el purgado
  es un único `DELETE`, atómico a nivel de statement; no hay estado intermedio
  que pueda quedar a medias. La degradación (D7) recoge el fallo sin abortar.
- **`started_at` capturado al inicio, purgado al final.** Mitigación: el reset
  corre en <20 min (R5.5 de demo-user) y el desfase entre `started_at` y el
  momento del purgado es del orden de minutos — irrelevante frente a 7 días. Si
  en el futuro el reset creciera a horas, el desfaje se mantendría proporcional
  al periodo y seguiría siendo válido.
- **Una futura ejecución podría purgar la fila de auditoría del purgado
  anterior.** Mitigación: la fila del purgado se escribe con
  `created_at = now` (≈ `started_at`) y el `DELETE` filtra
  `created_at < started_at - 7 days`, así que la fila es siempre más nueva que el
  corte y sobrevive. La fila del purgado de hace 8 días sí se borra — eso es
  exactamente la regla que estamos definiendo.
- **El `audit_log` que escribe el purgado queda con `entity_id` apuntando a un
  UUID que no existe en ninguna tabla.** Mitigación: ya pasa con cualquier
  `audit_log` cuyo `entity_id` polimórfico queda colgando tras el reset (D4bis
  punto 3 de demo-user); es el mismo problema, no uno nuevo, y la retención lo
  acota en vez de resolverlo.

## Open questions

Resueltas en el gate; las decisiones resultantes ya viven en D1-D8:

- **OQ1 — ¿Mismo módulo u otro?** Resuelto: `backend/app/cli/demo_reset.py`,
  junto a `clear_login_locks` y `sweep_storage`.
- **OQ2 — ¿Ejercitar `redacted("deleted_count")` en el test de vocabulario?**
  Resuelto: no — `deleted_count` no es un secreto y entra en
  `AUDITABLE_FIELDS`; `REDACT_ONLY_FIELDS` sería por simetría mal entendida.
- **OQ3 — Wording de la nota de degradación.** Resuelto: análogo a
  `clear_login_locks` — `"purge-audit: failed with <class> (detail withheld on
  purpose); the reset itself succeeded"`.
- **OQ4 — ¿Bloque EARS separado en la spec o sub-párrafo?** Resuelto: bloque
  EARS separado, mismo formato que el resto de la spec; la enmienda a R3.6 es
  de una línea.
