# Design: revenue-statements

## Context

El módulo `statements` lleva desde `domain-foundation-financial` (archivado 2026-07-31) con `OwnerStatement` y `Expense` como dataclass planos, dos modelos SQLAlchemy, sus tests de entidad/repositorio/modelo, y **un único puerto de lectura** — `ExpenseReader.summary_for_property` (`backend/app/statements/domain/repositories.py:41-58`) — implementado por `SqlAlchemyExpenseReader` (`backend/app/statements/infrastructure/repositories.py:21-45`). Hoy se consume desde `dashboard-api` R2: `PropertyFinancialSummary` (pendientes = `statement_id IS NULL`).

El `OwnerStatement` carece de invariantes y de máquina de estados (los 11 importes y los 3 `status` son columnas planas, dataclass sin métodos); `Expense` igual. Lo que entra en este change son las capas `application/` y `api/` (casos de uso + adaptadores + router), los métodos de transición en la entidad, el puerto + adaptador de lectura/escritura para las dos tablas, dos exportadores (CSV, PDF-stream), la tarea mensual del scheduler, los permisos/RBAC, las acciones de `AuditLog`, las traducciones ES/EN y los tests de cada capa.

Las decisiones se ciñen a los archivos declarados como inalterados por el proposal: ninguna entidad nueva, ningún enum nuevo, ninguna columna nueva, ninguna migración Alembic nueva. La suma `TenantConfig.owner_approval_threshold_eur` (PRD §7.2) es el único campo que se lee y se enforza fuera del dominio propio — y su existencia precede al change.

## Decisions

### D1 — Domain layer: invariantes en `OwnerStatement`, no en el caso de uso

**Chosen:** `OwnerStatement` gana un `ClassVar[frozenset]` con la tabla legal de transiciones, más los métodos `update_notes(notes, now)`, `mark_ready(now)`, `mark_sent(now)` y un helper `_check_transition(operation) → OwnerStatementStatus` análogo a `Incident._transition` (`backend/app/maintenance/domain/entities.py:330-333`). R4.2 y R4.4 se hacen cumplir por construcción: dos llamadas erróneas a `mark_ready` (sobre `READY` y sobre `SENT`) levantan `OwnerStatementInvalidTransitionError` con mensajes distintos, y la entidad rechaza un `update_notes` con `notes` None o vacío.

Rejected: tabla legal en el caso de uso — la regla "qué movimientos son legales" se dispersa entre router y caso de uso, y un `mark_sent` que olvide la guarda tiene que descubrirla cada revisión (mismo razonamiento que `Incident._TRANSITIONS` en `backend/app/maintenance/domain/entities.py:197-202`).

R5.1-R5.6 sobre Expense no son invariantes de entidad — son reglas de validación de entrada y de borrado — así que viven en `CreateExpenseUseCase` y `DeleteExpenseUseCase`, en `backend/app/statements/application/use_cases.py`. La entidad sigue siendo un dataclass plano (`backend/app/statements/domain/entities.py:35-49`).

### D2 — Puertos de repositorio y adaptadores SQLAlchemy

**Chosen:** dos nuevos protocolos en `domain/repositories.py` junto al `ExpenseReader` existente — `OwnerStatementRepository` y `ExpenseRepository` —, con seis métodos cada uno: `get`, `list_paginated` (filtros: `property_id`, `period_start_from`, `period_start_to`, `status`; tamaño 20 fijo; cursor `(page, per_page)`), `add`, `save`, `list_for_period(tenant_id, property_id, period_start, period_end)`, `bulk_associate_to_statement(ids, statement_id)`. Adaptador único por puerto: `SqlAlchemyOwnerStatementRepository` y `SqlAlchemyExpenseRepository` en `infrastructure/repositories.py`. Cada método toma `tenant_id` explícito además del `id` o filtro — mismo dibujo que `cleaning`, `pricing` y `maintenance` (regla 1 de `steering/security.md`: el filtro global de `app/core/db.py` es la red; el `tenant_id` en cada query es la regla).

Rejected: reutilizar `ExpenseReader` como puerto de lectura/escritura — su docstring (`backend/app/statements/domain/repositories.py:1-13`) dice literalmente *"**No `add`, no `save**. The signature is where that boundary lives"*, y la firma es la razón. Esa promesa sigue vigente: el lector queda intacto y el nuevo adaptador convive con él.

### D3 — Multi-moneda (resuelve OQ1)

**Chosen:** la generación declara una **moneda implícita** = `EUR` (sin columna nueva, sin enum nuevo). El `OwnerStatement` no expone `currency` (PRD §7.22 y la tabla del censo ya lo niegan). El cálculo suma importes de `Expense.currency == "EUR"` y de `Reservation.currency == "EUR"` para el período. **Si cualquier fila computable del período tiene `currency != "EUR"`, la generación se aborta para ese `(tenant, property, period_start, period_end)` entero** — no se emite un statement parcial. El job o `POST /generate` cuentan el caso como `currency_mismatch` con la lista de `(row_id, currency, table)` y siguen con el siguiente `(tenant, property, period)`. Ninguna conversión FX. El dashboard sigue mostrando `pending_expenses` por moneda (R2.3 de `dashboard-api`); el manager ve la fila no-EUR y decide (corregirla o quitarla).

Rejected:
- *Generar parcialmente omitiendo las filas no-EUR y contarlas aparte* — rechaza la integridad del snapshot: un statement con las 11 columnas calculadas sobre un subconjunto de filas induce al propietario a firmar una liquidación que no refleja la evidencia. La omisión por fila es la primera redacción de este D3 y se descarta por este motivo.
- *Fijar moneda por tenant en `tenant_configs`* — implica migración Alembic; queda fuera del scope aprobado.
- *Convertir a EUR con tabla de tipos* — implica una tabla nueva (`exchange_rates`); mismo motivo, queda fuera.

La estrategia se decide con los **datos del modelo canónico** (`Reservation.currency`, `Expense.currency`) y el reporte lo hace explícito: el manager sabe qué `(tenant, property, period)` quedó abortado y por qué, sin que la liquidación quede firmada a medias.

### D4 — Threshold bypass via `OwnerApproval(related_type=OTHER)` (resuelve OQ2, sin acoplamiento)

**Chosen:** `CreateExpenseUseCase.execute()` calcula `tenant.config.owner_approval_threshold_eur` antes de construir la entidad. Si `amount > threshold`, en la **misma transacción**:
1. Construye el `Expense` con `approved_by=None` (lo que el modelo canónico ya admite, `backend/app/statements/infrastructure/models.py:86-88`).
2. Construye un `OwnerApproval(related_type=OTHER, related_id=expense.id, amount=expense.amount, reason=f"Expense #{expense.id}")` y lo persiste vía `OwnerApprovalRepository` (puerto existente en `backend/app/maintenance/domain/repositories.py`).
3. Devuelve `201` con el cuerpo del Expense y un campo `pending_owner_approval_id` (ver D13) para que la UI sepa que tiene que esperar.

**El módulo `maintenance.application` queda intacto.** `RespondToOwnerApprovalUseCase` no gana ningún parámetro nuevo ni conoce `Expense`. La interpretación de `related_type=OTHER` como "fila de `expenses`" se hace en `statements/`, no en `maintenance/`.

**La reacción a la respuesta del owner es un job de reconciliación desacoplado** en `statements/`, paralelo a `process_webhook_events` y `provision_access_records` (`backend/app/scheduler/tasks.py:307-345, 427-445`):
- Nuevo task `reconcile_owner_approvals_for_expenses` registrado en `CADENCES` con cadencia `timedelta(minutes=5)`.
- Toma el lock igual que los demás (`task_lock` + `_guarded`).
- **No hay cursor externo.** El job consulta directamente el trabajo todavía no materializado, que es la fuente de verdad: las propias guardas SQL hacen la operación idempotente, y una aprobación llegada durante una ejecución anterior no se pierde nunca porque la query de la siguiente ejecución la recoge por su estado en la fila, no por una ventana temporal.
- Query principal — **lo que está pendiente de materializar**:
  ```sql
  SELECT oa.id, oa.status, oa.responded_by, oa.related_id
    FROM owner_approvals oa
    JOIN expenses e
      ON e.id = oa.related_id
     AND e.tenant_id = oa.tenant_id
   WHERE oa.related_type = 'OTHER'
     AND oa.responded_at IS NOT NULL
     AND (
           (oa.status = 'APPROVED' AND e.approved_by IS NULL AND e.statement_id IS NULL)
        OR (oa.status = 'REJECTED' AND e.statement_id IS NULL)
     )
  ```
- Por cada fila devuelta:
  - Si `APPROVED`: `UPDATE expenses SET approved_by = :responded_by WHERE id = :related_id AND approved_by IS NULL AND statement_id IS NULL`. Idempotente por las guardas: si una ejecución posterior ve la misma fila, las dos condiciones fallan y el `UPDATE` es no-op (`rowcount=0`).
  - Si `REJECTED`: `DELETE FROM expenses WHERE id = :related_id AND statement_id IS NULL`. Idempotente: si la fila ya no existe, `rowcount=0` no falla; si por alguna razón está consolidada, no se borra porque ya forma parte de la liquidación.
- Query de **inconsistencias** — registrada aparte en el informe, **no** modifica filas:
  ```sql
  SELECT oa.id, oa.related_id
    FROM owner_approvals oa
    JOIN expenses e
      ON e.id = oa.related_id
     AND e.tenant_id = oa.tenant_id
   WHERE oa.related_type = 'OTHER'
     AND oa.status = 'REJECTED'
     AND e.statement_id IS NOT NULL
  ```
  Estas filas **no** se borran ni se interpretan como aprobadas: el sistema observa una aprobación rechazada apuntando a un gasto ya consolidado, lo cual es una anomalía de datos. Se reportan como `failed_reconciliation` en el informe del job (un array con `(approval_id, expense_id, property_id, period_start, period_end)`) y se loguean con `logger.error`. La auditoría de la anomalía queda en el log del worker hasta que un cambio posterior (con su propio scope) decida cómo cerrarla.
- Sin nuevas entidades, sin nuevos enums, sin migración. El puerto `OwnerApprovalRepository` ya está en `maintenance.domain.repositories` y se reusa. **Tampoco hay clave en Redis**: la query es función sólo del estado de las tablas.

**El cálculo del statement filtra por `approved_by IS NOT NULL OR amount <= threshold`**, igual que en la versión anterior. Una fila en `PENDING` queda fuera hasta que el job de reconciliación materialice la respuesta del owner — y R5.7 queda cerrado por construcción: el endpoint no es la fuente del `approved_by` (lo es la respuesta del owner, mediada por el job de reconciliación), y un `Expense` con `amount > threshold` y `approved_by = NULL` no se cuenta en la liquidación.

**Latencia esperada**: hasta 5 minutos entre la respuesta del owner y la materialización en `expenses` (`approved_by` o `DELETE`). El job de reconciliación se ejecuta cada 5 minutos; entre una respuesta y la siguiente, el campo `pending_owner_approval_id` del `ExpenseResponse` (D13) refleja el estado PENDING hasta el siguiente run. La latencia es **sin pérdida**: cualquier aprobación respondida se materializa en su siguiente barrido, sin importar cuánto tiempo haya pasado desde la respuesta.

Rejected:
- *Pasar `ExpenseRepository` a `RespondToOwnerApprovalUseCase`* — introduce el acoplamiento que esta D descarta. `maintenance.application` queda fuera del flujo de Expense por construcción.
- *Rechazar `POST /expenses` cuando `amount > threshold` y derivar al flujo de Incident* — R5.7 no obliga a esto; un amenities de €150 no necesita un Incident, y forzar ese rodeo rompe el flujo del manager.
- *Añadir un enum `EXPENSE` a `OwnerApprovalRelatedType`* — implica migración Alembic; fuera del scope aprobado.
- *Crear una nueva entidad `PendingExpenseApproval`* — mismo motivo. El `OwnerApproval` canónico con `OTHER` ya cubre exactamente el caso "approval sobre algo que no es Incident ni MaintenanceCost" (`backend/app/maintenance/domain/enums.py:55-62`).

### D5 — Job mensual + excepción de regla 9 (resuelve OQ3)

**Chosen:** el job se registra en `MONTHLY_JOBS` con `MonthlySchedule(day_of_month=1, hour=2, lock_ttl=6h)` (definido en D11). **Cada** statement nuevo emite un `TimelineEvent OWNER_STATEMENT_GENERATED` con `metadata = {statement_id, property_id, period_start, period_end, source: "monthly_job"}` y actor `SCHEDULER` (análogo a `PRICE_RECOMMENDATION_CREATED`, `revenue-pricing` D7). **No** escribe `AuditLog`: la nueva excepción a regla 9 de `steering/security.md` se nombra como **sexta excepción** siguiendo el formato de las cinco existentes (mismo párrafo: "No hay actor (la generación la dispara `generate_owner_statements` el día 1 a las 02:00 UTC) **y** hay un sumidero hecho a medida — el `TimelineEvent OWNER_STATEMENT_GENERATED` por vivienda. Y no exime el camino manual: `POST /api/v1/owner-statements/generate` es llamado por una persona autenticada y escribe `OWNER_STATEMENT_GENERATED` con su actor siempre."). Esto añade la entrada de steering al archivo (modificación de `sdd/steering/security.md`).

Rejected:
- *Auditar siempre con `actor_user_id=NULL`* — funciona (PRD §7.25 admite nullable), pero serían ~12 filas/año/tenant con `actor=NULL`; bajo valor de auditoría porque el `TimelineEvent` ya dice lo mismo.
- *Eximir al actor de sistema sin sumidero* — inconsistente con el precedente de `PRICE_RECOMMENDATIONS_GENERATED`, que acompaña la exención con un evento de timeline.

### D6 — Consolidación de `Expense` y snapshot del `OwnerStatement` (resuelve OQ4)

Resuelve las cuatro caras de OQ4 sin migración de esquema:

**D6.1 — Momento exacto**: el `GenerateOwnerStatementUseCase` (manual + job) abre una transacción que, en este orden:
1. Comprueba si la `OwnerStatement` ya existe para la clave UNIQUE. Si existe, devuelve el existente con `idempotent_replay=True` (R2.3).
2. Comprueba mezcla de monedas (D3). Si **alguna** fila computable del período tiene `currency != "EUR"`, **aborta** la generación de ese `(tenant, property, period)` entero: registra `currency_mismatch` en el informe con la lista `(row_id, currency, table)` y sigue con el siguiente `(tenant, property, period)`. Sin statement parcial.
3. Calcula las 11 columnas monetarias leyendo `Expense` y `Reservation` del período en EUR, **con un solo lock de fila sobre la property** y `SERIALIZABLE` no requerido.
4. Persiste el `OwnerStatement` con `status=DRAFT`.
5. **Actualiza en bloque** `expenses SET statement_id = :new WHERE statement_id IS NULL AND property_id = :p AND date BETWEEN :start AND :end` (mismo `UPDATE … WHERE` que `price_recommendations` usa en D9). El conteo de filas tocadas entra como `consolidated_count` en el informe.

El `Expense.statement_id` queda fijado en el mismo instante en que se crea el statement, y **no vuelve a cambiar** (D6.2 y D6.4).

**D6.2 — Mutabilidad**: la consolidación cierra un subconjunto explícito de campos del `Expense`. La regla es **integridad entre evidencia y snapshot**, no conveniencia de edición.

**Campos inmutables tras `statement_id IS NOT NULL`** (cualquier intento de PATCH devuelve `409 ExpenseAlreadyConsolidatedError` con el nombre del campo; DELETE devuelve `409`):

- `amount` — aparece sumado en una de las 11 columnas monetarias del `OwnerStatement`; cambiarlo invalida la prueba del propietario.
- `currency` — si cambia a una moneda distinta de la implícita (EUR), invalida el cálculo de D3 que ya pasó.
- `category` — determina a cuál de los 7 buckets (`cleaning_costs`, `laundry_costs`, `amenities_costs`, `maintenance_costs`, `specialist_costs`, `platform_fee`, `other_costs`) se suma el `amount`; cambiar la categoría movería el importe entre buckets sin tocar el snapshot.
- `date` — determina la pertenencia al período `[period_start, period_end]`; cambiarla sacaría la fila del statement al que contribuyó o la metería en otro.
- `property_id` — el `statement_id` la ancla a esa vivienda; cambiar la propiedad sería una reasignación retroactiva que V1 no soporta.
- `statement_id` — el marcador de consolidación; moverlo entre statements es la regeneración que V1 prohíbe.
- `approved_by` — lo escribe la reconciliación de D4 al recibir `APPROVED`; cambiarlo a posteriori borra la trazabilidad de quién aprobó qué.
- `tenant_id`, `id`, `created_at` — invariantes de fila por construcción.

**Campos mutables tras `statement_id IS NOT NULL`** (PATCH permitido, no cambian nada contable):

- `description` — sumidero regla 11 (gestionado por la regla 11; el precedentede `incidents.title`/`description` del guest portal y de `owner_approvals.response_notes` admite edición tardía para notas aclaratorias, y la regla 11 ya declara el contrato).
- `receipt_storage_key` — puntero al justificante en `StorageAdapter`; la URL puede subirse tarde y el enlace actualizado no afecta a los importes.

**`Expense` con `statement_id IS NULL`** (antes de consolidar): CREATE / PATCH sobre cualquier campo permitido (R5.1-R5.3); DELETE permitido (R5.4, "sólo si `statement_id IS NULL").

**`Expense.approved_by`** cuando la fila aún no está consolidada pero su `OwnerApproval(OTHER)` está `PENDING`: la reconciliación de D4 lo setea a `responded_by` cuando llega `APPROVED`. Si entre tanto un PATCH intenta modificar `approved_by` directamente, el repositorio lo rechaza con `409` — `approved_by` sólo lo escribe la reconciliación.

**No hay reasignación retroactiva**: una fila consolidada que el manager descubre errónea **no** se mueve de statement; se anota vía `notes` del `OwnerStatement` y se deja que la siguiente liquidación corrija por diferencia. Esto es coherente con R1.3 y R2.3 (V1 no regenera, no reasocia).

**D6.3 — `Expense` con `date` en un período ya cerrado**: `POST /api/v1/expenses` rechaza con `422 NamedExpenseInClosedPeriodError` (mapea a `ErrorCode.VALIDATION_ERROR` en `app/core/error_codes.py`) si existe una `OwnerStatement` con `period_start ≤ date ≤ period_end` para esa `property_id`. La regla es de aplicación, no de esquema. El manager puede corregir la `date` o crear el Expense en el período abierto más cercano — el endpoint dice cuál en el cuerpo del error.

Rejected:
- *Permitir creación y asociar retroactivamente al statement existente* — contradice R1.3 (V1 no regenera, no reasocia) y abre el caso de "importe recalculado silenciosamente", que es exactamente la desalineación que D6.2 congela.
- *Permitir creación sin asociación (huérfano)* — la fila queda en `pending_expenses` para siempre (no hay regenerate en V1), y el manager ve un número que nunca entra en ninguna liquidación.

**D6.4 — Coherencia con V1**: la consolidación es **una operación irreversible y determinista por `(property_id, period_start, period_end)`**. No hay `UPDATE owner_statements` posterior — los importes se escriben una vez en la transacción D6.1 y nadie los toca. No hay `UPDATE expenses SET statement_id = NULL` — el campo pasa de NULL a un valor y se queda. Los once importes y el `consolidated_count` son la única verdad contable del período; cualquier divergencia posterior (un edit de `description` después de consolidar, por ejemplo) es visible por la diferencia entre `expenses` y `owner_statements`.

### D7 — AuditLog: nuevas entidades y acciones

**Chosen:** en `backend/app/audit/domain/actions.py`:
- `ENTITY_OWNER_STATEMENT = "OWNER_STATEMENT"` y `ENTITY_EXPENSE = "EXPENSE"` añadidos a `ENTITY_TYPES`.
- Acciones nuevas en `ACTIONS`: `OWNER_STATEMENT_GENERATED`, `OWNER_STATEMENT_STATUS_CHANGED`, `OWNER_STATEMENT_NOTES_UPDATED`, `EXPENSE_CREATED`, `EXPENSE_UPDATED`, `EXPENSE_DELETED`. La acción del job (`OWNER_STATEMENT_GENERATED` cuando la dispara el reloj) **no** se escribe — D5 cubre esa omisión por la sexta excepción de regla 9. El endpoint manual sí la escribe con actor.
- `AUDITABLE_FIELDS["OWNER_STATEMENT"] = {"status", "notes"}` — los once importes no son escribibles por API y por tanto no entran (criterio de la regla 9: lo que no se mueve no se audita).
- `AUDITABLE_FIELDS["EXPENSE"] = {"category", "amount", "currency", "date", "statement_id", "incident_id", "approved_by", "receipt_storage_key"}`. **`description` queda fuera** (sumidero regla 11, excepción 3): su valor va al `audit_logs.changes` sólo como `{"changed": true}` por `REDACT_ONLY_FIELDS["EXPENSE"] = {"description"}` (nueva entrada, mismo mecanismo que `PRICING_RULE` D13).

`_AuditWriter` en `app/statements/application/use_cases.py` rechaza cualquier `actor is None` salvo `OWNER_STATEMENT_GENERATED` cuando el llamante es el job — único path sin actor, mismo dibujo que `_AuditWriter` de `pricing/application/use_cases.py:119-167`.

Rejected: añadir `EXPENSE_DELETED_VIA_APPROVAL_REJECTED` como acción distinta — sería una acción para una operación que nadie ejecuta fuera del flujo de aprobación, y el vocabulario del módulo (`app/audit/domain/actions.py:1-15`) lo rechaza explícitamente.

### D8 — RBAC y permisos

**Chosen:** en `backend/app/auth/domain/policy.py`:
- `Permission.READ_OWNER_STATEMENTS` y `Permission.MANAGE_OWNER_STATEMENTS` añadidos al `Permission` enum.
- `_STATEMENTS_READ = frozenset({Permission.READ_OWNER_STATEMENTS})` y `_STATEMENTS_MANAGE = frozenset({Permission.READ_OWNER_STATEMENTS, Permission.MANAGE_OWNER_STATEMENTS})`.
- `TENANT_OWNER` recibe `_STATEMENTS_READ` (mismo dibujo que `_INCIDENT_READ`/`_ACCESS_READ`).
- `PROPERTY_MANAGER` recibe `_STATEMENTS_MANAGE` (mismo dibujo que `_INCIDENT_MANAGE`/`_ACCESS_MANAGE`).
- `CLEANER`, `TECHNICIAN`, `SUPER_ADMIN` no reciben ninguno (mismo razonamiento que el resto: no necesitan ver cifras financieras; `SUPER_ADMIN` queda fuera por el motivo genérico ya documentado).

`RESPOND_OWNER_APPROVALS` ya existe y sigue intacto: el owner usa ese permiso para responder las aprobaciones que D4 crea por encima del umbral.

### D9 — Endpoints, errores y formato

**Chosen:** router FastAPI bajo prefijo `/api/v1/owner-statements` y `/api/v1/expenses`. Sobre:

| Método | Ruta | Permiso | Errores |
|---|---|---|---|
| `GET` | `/api/v1/owner-statements` | `READ_OWNER_STATEMENTS` | `404` tenant vacío, `403` sin permiso |
| `GET` | `/api/v1/owner-statements/{id}` | `READ_OWNER_STATEMENTS` | `404` (id o tenant ajeno, cuerpo constante) |
| `POST` | `/api/v1/owner-statements/generate` | `MANAGE_OWNER_STATEMENTS` | `422` period inválido / mixed-period / property ajena / inactiva, `404` property inexistente (404 sólo en casos del resource path, no del body) |
| `PATCH` | `/api/v1/owner-statements/{id}` | `MANAGE_OWNER_STATEMENTS` | `409` transición ilegal / ya en `SENT`, `422` validación |
| `GET` | `/api/v1/owner-statements/{id}/export.csv` | `READ_OWNER_STATEMENTS` | `404` |
| `GET` | `/api/v1/owner-statements/{id}/export.pdf` | `READ_OWNER_STATEMENTS` | `404` |
| `GET` | `/api/v1/expenses` | `READ_OWNER_STATEMENTS` | `403` |
| `POST` | `/api/v1/expenses` | `MANAGE_OWNER_STATEMENTS` | `422` validación / period cerrado (D6.3); nunca `422` por umbral (D4 lo crea junto con `OwnerApproval`), `404` property ajena |
| `PATCH` | `/api/v1/expenses/{id}` | `MANAGE_OWNER_STATEMENTS` | `404`, `422` validación, `409` consolidado (D6.2) / field inmutable | `409` period cerrado |
| `DELETE` | `/api/v1/expenses/{id}` | `MANAGE_OWNER_STATEMENTS` | `404`, `409` consolidado |

Sobre el `RESPOND_OWNER_APPROVALS` y su `POST /api/v1/owner-approvals/{id}/respond` — el endpoint **no se toca**, y `RespondToOwnerApprovalUseCase` tampoco. La lógica D4 vive en `statements/application/reconciliation.py` y se ejecuta desde el job `reconcile_owner_approvals_for_expenses`.

### D10 — PDF y CSV

**Chosen:**
- **CSV** — `csv.writer` del stdlib. Cabecera: `date,category,description,amount,currency,receipt_storage_key`. Sin BOM. UTF-8 directo. Codepoints especiales no se escapan (la hoja de cálculo los soporta).
- **PDF** — `fpdf2` (`PyPI: fpdf2`, pure-Python, sin dependencias nativas; cabe en `python:3.12-slim`). Una sola clase `PdfStatementGenerator` en `app/statements/infrastructure/pdf.py` con un método `render(statement, reservations, expenses_by_category, tenant, property) -> bytes`. Layout: cabecera tenant, bloque property, bloque período, tabla de reservas, tabla de gastos por categoría con subtotal, fila de totales, caja de `notes`. Sin logo. Se sirve vía `StreamingResponse` con `Content-Type: application/pdf` y `Content-Disposition: attachment; filename="owner-statement-<period>.pdf"`.

Rejected:
- *`weasyprint` / `xhtml2pdf`* — ambos necesitan HTML→PDF; `weasyprint` requiere Cairo/Pango en la imagen Docker (alza ~80MB), `xhtml2pdf` es menos maduro. El formato no necesita HTML.
- *`reportlab`* — funciona pero su API es verbosa para un layout simple; `fpdf2` lo cubre con menos líneas.

### D11 — Scheduler: `MonthlySchedule` y TTL

**Chosen:** extiende `DailySchedule` a `Schedule(hour, lock_ttl)` y añade `MonthlySchedule(day_of_month, hour, lock_ttl)`. El nuevo job `generate_owner_statements` se registra en `MONTHLY_JOBS`:

```python
MONTHLY_JOBS: dict[str, MonthlySchedule] = {
    "generate_owner_statements": MonthlySchedule(
        day_of_month=1, hour=2, lock_ttl=timedelta(hours=6)
    ),
}
```

Lock TTL = 6 horas: una cartera con 100 propiedades tarda minutos en generación; 6h cubre un tenant lento sin wedgear la siguiente ventana mensual. `lock_ttl_for(MONTHLY_JOBS[...].lock_ttl)` se usa igual que `lock_ttl_for(CADENCES[...])` en `_locked`. Nueva función `_guarded_monthly(name, work)` paralela a `_guarded_daily` (`backend/app/scheduler/tasks.py:242-254`).

`beat_schedule()` (`backend/app/scheduler/schedule.py:97-115`) gana una tercera rama:

```python
schedule.update({
    f"{name}-monthly-{m.day_of_month:02d}{m.hour:02d}00-utc": {
        "task": name,
        "schedule": crontab(day_of_month=m.day_of_month, hour=m.hour, minute=0),
    }
    for name, m in MONTHLY_JOBS.items()
})
```

Rejected: reusar `crontab(month_of_year=...)` con `month_of_year='1'` y hacer crontab mensual — Celery lo soporta pero la legibilidad sufre, y `MonthlySchedule` es paralelo a `DailySchedule` en coste.

### D12 — Steering: sexta excepción de regla 9

**Chosen:** modifica `sdd/steering/security.md` para añadir una sexta excepción de regla 9, redactada en paralelo a la quinta (`PRICE_RECOMMENDATIONS_GENERATED`):

> **Sexta excepción nombrada, y acotada al actor y a una sola vía: la generación de `OwnerStatement` por el job mensual **no escribe `AuditLog`.** Decidida en `revenue-statements` (D5 del design, aprobada en el gate de `/sdd:design` 2026-08-XX); la entrada la escribe su tarea de archivado correspondiente al cambio del archivo.
>
> Se pide por dos propiedades a la vez. **No hay actor**, como en la cuarta excepción: la generación la dispara `generate_owner_statements` el día 1 a las 02:00 UTC, no hay persona detrás y `actor_ip` no tiene petición de la que salir. Y **hay un sumidero hecho a medida**, como en la primera: cada statement nuevo emite un `TimelineEvent OWNER_STATEMENT_GENERATED` con `metadata` cerrado (`{statement_id, property_id, period_start, period_end, source}`), y el informe del job devuelve `created`, `skipped`, `failed`, `consolidated_count` y `currency_mismatch`.
>
> El volumen es bajo — doce filas de timeline por tenant al año—, así que la consideración es de **simetría con el precedente** de `revenue-pricing` y no de presión sobre el índice.
>
> **Lo que esta excepción NO concede**, y aquí es simétrica a la quinta: no exime **`POST /api/v1/owner-statements/generate`**: esa la pide una persona autenticada con RBAC, y escribe `OWNER_STATEMENT_GENERATED` con su actor siempre. No exime **ninguna mutación del statement**: `OWNER_STATEMENT_STATUS_CHANGED` y `OWNER_STATEMENT_NOTES_UPDATED` llevan su actor siempre. No exime **ninguna mutación de `Expense`**: las tres acciones del vocabulario de Expense llevan su actor siempre.

Y se amplía la fila del censo para `owner_statements.notes` (excepción 3) y `expenses.description` (excepción 3), con la tabla cerrada en `maintenance/domain/notifications.py`/`cleaning/domain/notifications.py` como precedente de forma.

### D13 — `pending_owner_approval_id` en `ExpenseResponse`, no en `OwnerStatementResponse`

**Chosen:** `ExpenseResponse` (devuelto por `POST /api/v1/expenses` y por `GET /api/v1/expenses/{id}`) lleva un campo opcional:

```python
class ExpenseResponse(BaseModel):
    # … los 11 campos canónicos de §7.23 …
    pending_owner_approval_id: UUID | None = None
```

**Cómo se rellena el campo**:
- En creación: `CreateExpenseUseCase` lo setea con el `id` del `OwnerApproval(OTHER)` recién creado cuando `amount > threshold`. Cuando `amount ≤ threshold`, queda `None`.
- En lectura: `GetExpenseUseCase` y `ListExpensesUseCase` consultan `owner_approvals WHERE related_type=OTHER AND related_id=expense.id AND status=PENDING LIMIT 1` y, si la hay, setean `pending_owner_approval_id` con su `id`. Si no hay (aprobada, rechazada, o nunca creada por umbral), queda `None`. La consulta es una sola fila por `Expense`; el coste es despreciable para el tamaño del listado (típicamente vacío tras la primera reconcilación de D4).

  **Cambio respecto a la redacción inicial**: `find_pending_owner_approval_for` lleva **`tenant_id` como parámetro obligatorio**, y el SQL filtra por `oa.tenant_id = :tenant_id`. La primera redacción omitía el `tenant_id`, lo que infringía regla 1 de `steering/security.md` (toda query debe scope por tenant). El panel de arquitectura de §3 lo señaló como `DESIGN-CONFLICT`; el steering gana y la firma cambia.

**`OwnerStatementResponse` no lleva este campo**, y eso es deliberado: un `OwnerStatement` se construye con `Expense.statement_id` ya fijado (D6.1), es decir, sólo sobre filas consolidadas — cuyo `OwnerApproval(OTHER)` está necesariamente `APPROVED` y por tanto no está `PENDING`. La consulta `pending_owner_approval_id` no aporta información para una respuesta de statement.

**Forma del campo**: `UUID | None`, igual que `statement_id` y `approved_by` en el modelo. Sin nuevo enum, sin nueva columna, sin lógica nueva en `maintenance.application`.

Rejected:
- *Eliminar el campo y exigir al cliente una segunda llamada a `/owner-approvals?related_type=OTHER&related_id=X`* — acopla al cliente al modelo de aprobación de `maintenance`, que no es su superficie. El campo en `ExpenseResponse` mantiene la consulta donde la hace el repositorio de `statements`.
- *Poner `pending_owner_approval_id` en `OwnerStatementResponse`* — confunde evidencia con snapshot: un statement no "tiene" aprobaciones pendientes, registra importes consolidados.

## Changes by area

| Area | Files | Change |
|---|---|---|
| **statements/domain** | `backend/app/statements/domain/entities.py` | `OwnerStatement` gana `_TRANSITIONS` (ClassVar), `update_notes`, `mark_ready`, `mark_sent` y `_check_transition` (privado). `Expense` queda como está. |
| **statements/domain** | `backend/app/statements/domain/repositories.py` | `OwnerStatementRepository` y `ExpenseRepository` (nuevos Protocol); el `ExpenseReader` existente queda intacto. |
| **statements/domain** | `backend/app/statements/domain/exceptions.py` (nuevo) | `OwnerStatementInvalidTransitionError`, `OwnerStatementNotFoundError`, `ExpenseNotFoundError`, `ExpenseAlreadyConsolidatedError`, `NamedExpenseInClosedPeriodError`, `MixedCurrencyPeriodError` (ésta sólo se usa internamente — el rechazo de la generación devuelve `MixedCurrencyPeriodError` con la lista). |
| **statements/application** | `backend/app/statements/application/use_cases.py` (nuevo) | `CreateExpenseUseCase`, `UpdateExpenseUseCase`, `DeleteExpenseUseCase`, `ListExpensesUseCase`, `GetExpenseUseCase`, `ListOwnerStatementsUseCase`, `GetOwnerStatementUseCase`, `GenerateOwnerStatementUseCase`, `UpdateOwnerStatementNotesUseCase`, `TransitionOwnerStatementStatusUseCase`, `ExportOwnerStatementCsvUseCase`, `ExportOwnerStatementPdfUseCase`. `_AuditWriter` interno. |
| **statements/application** | `backend/app/statements/application/reconciliation.py` (nuevo) | `ReconcileOwnerApprovalsForExpensesUseCase` (D4): query de trabajo pendiente (JOIN con `expenses` por las guardas de D4 — sin cursor externo); `UPDATE expenses` para APPROVED, `DELETE expenses` para REJECTED, ambos idempotentes por sus guardas; query separada para REJECTED sobre Expense consolidado se reporta como `failed_reconciliation` sin tocar filas. |
| **statements/application** | `backend/app/statements/application/generation.py` (nuevo) | `Period` value object (start, end, duration = un mes natural), `MonetaryAggregator` (suma de `Reservation` + `Expense` por categoría, devuelve un `StatementBreakdown` con los 11 importes), `CurrencyFilter` (D3: aborta la generación si hay filas no-EUR). |
| **statements/infrastructure** | `backend/app/statements/infrastructure/repositories.py` | `SqlAlchemyOwnerStatementRepository` y `SqlAlchemyExpenseRepository`. `SqlAlchemyExpenseReader` queda intacto. |
| **statements/infrastructure** | `backend/app/statements/infrastructure/pdf.py` (nuevo) | `PdfStatementGenerator` con `fpdf2`. |
| **statements/infrastructure** | `backend/app/statements/infrastructure/csv_export.py` (nuevo) | `csv` stdlib envuelto en un caso de uso. |
| **statements/api** | `backend/app/statements/api/router.py` (nuevo) | Los once endpoints de D9. |
| **statements/api** | `backend/app/statements/api/schemas.py` (nuevo) | Pydantic v2 para los once DTOs. `ExpenseResponse` lleva `pending_owner_approval_id: UUID | None` (D13); `OwnerStatementResponse` **no** lleva ese campo. |
| **statements/api** | `backend/app/statements/api/dependencies.py` (nuevo) | Builders de los once casos de uso (mismo dibujo que `app/pricing/api/dependencies.py`). |
| **statements/api** | `backend/app/statements/api/errors.py` (nuevo) | Mapeo de excepciones a HTTP (mismo dibujo que `app/pricing/api/errors.py`). |
| **audit** | `backend/app/audit/domain/actions.py` | Nuevas entidades y acciones (D7); `AUDITABLE_FIELDS["OWNER_STATEMENT"]` y `["EXPENSE"]`; `REDACT_ONLY_FIELDS["EXPENSE"] = {"description"}`. |
| **audit** | `backend/app/audit/domain/value_objects.py` | Ningún cambio — `ChangeSet` cubre las nuevas entidades sin tocar el módulo. |
| **auth** | `backend/app/auth/domain/policy.py` | Dos `Permission` nuevos, dos `_STATEMENTS_*` bundles, dos líneas en `ROLE_PERMISSIONS` (D8). |
| **maintenance** | `backend/app/maintenance/application/use_cases.py` | **Sin cambios**. `RespondToOwnerApprovalUseCase` queda intacto por D4 (la reacción se desacopla al job de reconciliación en `statements/`). |
| **scheduler** | `backend/app/scheduler/schedule.py` | `MonthlySchedule` dataclass + `MONTHLY_JOBS`; `beat_schedule()` con la rama mensual. |
| **scheduler** | `backend/app/scheduler/tasks.py` | `_generate_owner_statements(session, tenant_id, now)` + `_guarded_monthly`; `@celery_app.task("generate_owner_statements")`. |
| **tenants** | `backend/app/tenants/infrastructure/repositories.py` | Sin cambios; el `TenantConfig.owner_approval_threshold_eur` ya está en el modelo. |
| **reservations** | `backend/app/reservations/infrastructure/models.py` | Sin cambios; las columnas `gross_amount`/`ota_commission`/`net_amount`/`currency` son las que se suman. |
| **properties** | `backend/app/properties/infrastructure/models.py` | Sin cambios; las columnas `name`/`internal_code`/`address_*` van al PDF. |
| **steering** | `sdd/steering/security.md` | Sexta excepción de regla 9 (D12); dos filas nuevas en la tabla de la regla 11. |
| **i18n** | `backend/app/core/i18n/` o equivalente (a localizar) | Dos claves ES/EN para los mensajes de error de las nuevas excepciones (ver D14). |
| **specs** | `sdd/specs/revenue-statements.md` (nuevo, al archivar) | Spec del módulo. |
| **specs** | `sdd/specs/api-contract.md` (modificado) | Once rutas nuevas. |
| **deps** | `backend/pyproject.toml` | `fpdf2` añadido (pure-Python, sin nativas). |
| **tests** | `backend/tests/statements/test_entities.py` | Transiciones de `OwnerStatement` (cubren D1). |
| **tests** | `backend/tests/statements/test_use_cases.py` | Las once casos de uso, con fakes de los puertos. |
| **tests** | `backend/tests/statements/test_repositories.py` | `bulk_associate_to_statement` (D6.1), el filtro `statement_id IS NULL`. |
| **tests** | `backend/tests/statements/test_models.py` | Sin cambios — schema no se mueve. |
| **tests** | `backend/tests/statements/test_generation.py` | `MonetaryAggregator` con datos reales del seed (D3 y D6). |
| **tests** | `backend/tests/statements/test_pdf.py` | Render del PDF: bytes comienzan con `%PDF-`, número de páginas esperado, contenido textual buscable. |
| **tests** | `backend/tests/statements/test_idempotency.py` | R1.3 + R2.3: dos generaciones sobre misma clave UNIQUE devuelven la misma fila. |
| **tests** | `backend/tests/statements/test_consolidation.py` | D6: generar y luego intentar `POST /expenses` con `date` en el período cerrado → `422`. Inmutabilidad D6.2: PATCH sobre un campo inmutable de un Expense consolidado → `409`. |
| **tests** | `backend/tests/statements/test_threshold.py` | `CreateExpenseUseCase` con `amount > threshold` crea `Expense` + `OwnerApproval(OTHER)` en la misma transacción; con `amount ≤ threshold` no crea approval. La respuesta lleva `pending_owner_approval_id` cuando aplica. |
| **tests** | `backend/tests/statements/test_reconciliation.py` | El job `reconcile_owner_approvals_for_expenses` aplica `UPDATE approved_by` cuando ve un `OwnerApproval(OTHER, APPROVED)` cuyo Expense sigue con `approved_by IS NULL AND statement_id IS NULL`; `DELETE` cuando ve un `OwnerApproval(OTHER, REJECTED)` cuyo Expense sigue existiendo con `statement_id IS NULL`. Idempotencia: la query no tiene ventana temporal — la misma fila devuelta dos veces es no-op por las guardas. La guarda `statement_id IS NULL` evita pisar gastos ya consolidados. Un `REJECTED` cuyo Expense ya está consolidado entra en `failed_reconciliation` sin tocar filas. |
| **tests** | `backend/tests/statements/test_api.py` | Tests de integración de los once endpoints. |

## Data & interfaces

- **Esquema**: sin migración Alembic. Las tablas `owner_statements` y `expenses` no cambian. `tenant_configs.owner_approval_threshold_eur` ya existe. Los enums `owner_statement_status` y `expense_category` no cambian.
- **Contrato OpenAPI**: once rutas nuevas en `backend/openapi.json`, regeneradas con `make openapi`. `PricingPage<T>` y `OwnerStatementPage<T>` son tipos distintos para no romper la convención de `pricing-web` (`sdd/specs/revenue-pricing.md` §«El sobre de paginación de pricing no es el de los demás módulos»).
- **Eventos de timeline**: `OWNER_STATEMENT_GENERATED` (job y manual), `OWNER_STATEMENT_STATUS_CHANGED` (D4.2), `OWNER_STATEMENT_NOTES_UPDATED` (R4.5), `EXPENSE_CREATED`/`UPDATED`/`DELETED`. El job de `PRICE_RECOMMENDATION_CREATED` está en `TimelineEventType`; los nuevos se añaden ahí (un único enum compartido en `timeline/domain/enums.py`).
- **Config / env vars**: ninguno nuevo. `fpdf2` es puro Python y no requiere variables de entorno.
- **Permisos**: dos nuevos (`READ_OWNER_STATEMENTS`, `MANAGE_OWNER_STATEMENTS`).
- **AuditLog**: dos entidades nuevas (`OWNER_STATEMENT`, `EXPENSE`), seis acciones nuevas, dos entradas nuevas en `AUDITABLE_FIELDS`, una entrada nueva en `REDACT_ONLY_FIELDS`.

## Risks & mitigations

- **Riesgo: que una respuesta del owner llegue mientras el job está ejecutándose y se "pierda" entre dos barridos.** Mitigación: la query de D4 **no tiene ventana temporal** — es una JOIN sobre el estado de las filas, no sobre `responded_at > :cursor`. La fila con `OwnerApproval(OTHER, APPROVED)` y `Expense.approved_by IS NULL AND statement_id IS NULL` aparece en cada barrido subsiguiente hasta que las guardas la materialicen; la respuesta se aplica sin importar cuánto tiempo haya pasado. Sin Redis ni checkpoint externo. Latencia esperada: hasta 5 minutos entre la respuesta del owner y la materialización en `expenses`.
- **Riesgo: que aparezca un `OwnerApproval(OTHER, REJECTED)` apuntando a un Expense ya consolidado (`statement_id IS NOT NULL`).** Mitigación: la query de inconsistencias de D4 los detecta y los reporta como `failed_reconciliation` (array con `(approval_id, expense_id, property_id, period_start, period_end)` en el informe del job y `logger.error`). No se borra la fila (per tu instrucción: "no lo borres ni lo interpretes como aprobado"). La situación es un caso degenerado: V1 consolida tras la respuesta del owner, así que una aprobación `REJECTED` apuntando a un consolidado sólo ocurre si el sistema se ha saltado la materialización de un `APPROVED` previo o si la fila del Expense se modificó a mano. El reporte deja el rastro auditable sin tocar datos.
- **Riesgo: que el job `generate_owner_statements` aborte demasiados `(tenant, property, period)` por una sola fila no-EUR.** Mitigación: D3 aborta la generación **del (tenant, property, period) entero**, no del tenant entero. La lista de monedas encontradas se reporta en `currency_mismatch` para que el manager sepa qué corregir. Sin conversión FX ni omisión silenciosa.
- **Riesgo: que la inmutabilidad de D6.2 (campos contables/consolidables) sea demasiado estricta y bloquee correcciones legítimas.** Mitigación: `description` y `receipt_storage_key` siguen siendo editables tras consolidar (no alteran importes ni la pertenencia al período). El resto de campos financieros/contables son inmutables y devuelven `409 ExpenseAlreadyConsolidatedError`. La regla la fija el **repositorio** (`SqlAlchemyExpenseRepository.update`), no el caso de uso — un writer que llame `update` directamente la encuentra en la misma capa que la regla de `statement_id IS NOT NULL` que ya tiene.
- **Riesgo: que `fpdf2` no reproduzca exactamente el layout entre plataformas.** Mitigación: el layout es texto y celdas, sin fuentes externas. Test `test_pdf.py` hace `bytes[:4] == b"%PDF"` y `len(reader.pages) == expected` — invariantes suficientes para MVP. Si en el futuro se quiere tipografía exacta, el cambio es a `weasyprint` con migración de imagen Docker (no en scope).
- **Riesgo: que `Expense.statement_id IS NULL` después de consolidar tarde en reflejarse en `dashboard-api`.** Mitigación: la query `summary_for_property` ya filtra por `statement_id IS NULL`; cuando la generación corra, las filas pasan a tener `statement_id NOT NULL` y dejan de contar como pendientes. Cubierto por `tests/dashboard/test_dashboard.py::test_pending_expenses_drop_after_consolidation` (a añadir en `dashboard-api`'s tests si no existe, o aquí como `test_cross_feature_consolidation.py`).
- **Riesgo: que el `OwnerStatement.status = SENT` se use para disparar un envío real.** Mitigación: explícito en Out of scope (proposal). El handler nunca abre un canal de notificación; `notifications/` queda intacta.
- **Riesgo: que `update_notes` permita texto vacío o con `U+0000`.** Mitigación: `update_notes` rechaza con `OwnerStatementValidationError` si `notes` es vacío tras `strip()` o contiene `U+0000`; mismo guardián que `app/core/storable_text.py` ya aplica a `cleaning-tasks` y `incidents`.
- **Riesgo: el `INNER JOIN` `Expense ↔ OwnerApproval` para los gastos consolidados con umbral**. Mitigación: el cálculo filtra por `approved_by IS NOT NULL` en lugar de JOIN, así la query es un solo `SELECT` y no depende de que el `OwnerApproval` exista todavía (puede estar `PENDING`).

## Open questions

(Ninguna que pase a `/sdd:tasks`.)

D3 fija la postura de multi-moneda para V1: abortar `(tenant, property, period)` por moneda mixta, sin statement parcial, sin conversión FX. Si en el futuro el tenant opera multi-moneda real, la admisión de `tenant_configs.statement_currency` con migración Alembic queda como change posterior — fuera de scope aquí.

La sexta excepción de regla 9 (D12) queda como modificación de `sdd/steering/security.md` en scope del archivado del change — el texto se incluye en este design para revisión previa, y se commitea junto con el resto.