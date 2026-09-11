# Design: pms-sync-schedule

## Context

El calendario de beat vive en `backend/app/scheduler/schedule.py` (`CADENCES`, `DAILY_JOBS`,
`MONTHLY_JOBS`, `ON_DEMAND_TASKS`) y se despliega vía `backend/app/scheduler/tasks.py`, donde
cada job periódico se envuelve con `_guarded(name, cadence, work)` — que toma el candado de
`scheduler/locks.py` y llama a `run_for_every_tenant(name, work)`, que a su vez abre una
sesión marcada por tenant vía `run_in_marked_session` y nunca la re-marca. Los seis jobs
existentes (`check_checkin_windows`, `process_checkouts`, `mark_occupied_estimated`,
`check_sla_breaches`, `dispatch_notifications`, `provision_access_records`,
`classify_incidents`, `classify_reviews`) siguen exactamente esta forma; `test_schedule.py`
transcribe el calendario contra PRD §8.3 y sus divergencias declaradas.

El caso de uso que este job necesita ya existe: `SyncReservationsFromPmsUseCase.execute(tenant_id,
since, now, providers=None, actor_type=SYSTEM, source=PMS_SOURCE)`
(`backend/app/integrations/application/use_cases.py`) — agrupa las propiedades del tenant por
proveedor, resuelve un adapter por grupo vía `PMSAdapterFactory`, y ya se niega en voz alta
(`_sync_one_provider`, líneas ~229-246) a servir un proveedor con credenciales `PROPERTY`-scoped
en un sync agrupado. Lo usan hoy el CLI `python -m app.integrations.cli.pms_sync` (con
`source=PMS_SOURCE`) y el drenaje de webhooks (`source=WEBHOOK_SOURCE`). `celery-jobs` design
D16 decidió explícitamente NO programarlo porque su coste no estaba medido y su adapter no
existía; las dos premisas cerraron con `docs/beds24-adapter.md` y `pms-beds24-adapter`
respectivamente, y el propio docstring de `pms_sync.py` ya lo dice: "Whoever schedules this owns
the cadence decision on its own merits."

## Decisions

### D1 — Cadencia fija de 6 h en `CADENCES`, no en `Settings`

**Chosen:** `sync_pms_reservations` entra en `CADENCES` como un `timedelta(hours=6)` literal,
exactamente como los otros ocho jobs periódicos. 6 h es la cadencia que Beds24 mismo
recomienda para sincronización completa (nota del roadmap), y ninguna otra entrada del
calendario deriva su cadencia de `Settings` — `CADENCES` es un `dict` module-level que
`test_schedule.py` transcribe literalmente contra el PRD y sus divergencias declaradas.

Rejected: cadencia como `Settings` (la nota del roadmap lo sugería) — habría exigido que
`CADENCES` dejara de ser un dict de literales para leer `settings` al importar el módulo, la
única entrada así de las nueve, y `test_schedule.py` tendría que dejar de transcribir un valor
fijo. El beneficio (poder bajar la cadencia sin desplegar código) no compensa romper la
única propiedad que hace el calendario auditable de un vistazo.

### D2 — La ventana (`since`) sí es un `Settings`, `window_days` no lo es

**Chosen:** `pms_sync_window_days: int = 2` en `Settings` (patrón `notification_batch_size`,
`beds24_max_pages`: `<dominio>_<cosa>: int = <default>`). 2 días da margen sobre la cadencia de
6 h para tolerar un ciclo perdido sin re-pedir el mes entero que usa el CLI manual
(`DEFAULT_WINDOW_DAYS = 30`, que no cambia). A diferencia de la cadencia, la ventana no
determina la FORMA del calendario — no la transcribe `test_schedule.py` — así que hacerla
configurable no compromete esa propiedad y sí permite ajustar el coste de crédito sin
desplegar, que es exactamente el margen que D16 pedía medir.

Rejected: ventana fija en código como la cadencia — pierde el único grado de libertad
operativo que la nota del roadmap pedía sin ningún coste de legibilidad a cambio, porque el
valor no participa en `beat_schedule()`.

### D3 — Todos los tenants `ACTIVE`, incluidos los `MOCK`-only

**Chosen:** ningún filtro nuevo — `run_for_every_tenant` ya recorre todo tenant `ACTIVE`, que
es exactamente la recomendación de la nota del roadmap ("que el mock siga siendo idempotente,
que es lo que prueba que el job no rompe nada"). `MockPMSAdapter.list_reservations` es
idempotente sobre el seed (`ingest.py:218-228`: `skipped`, no `updated`), así que un tenant de
demo no genera ruido en cada ciclo.

Rejected: filtrar por `pms_provider != MOCK` — añadiría una consulta y una excepción sin
beneficio: el propio caso de uso ya reporta `skipped` cuando no hay nada que cambiar.

### D4 — Tercer `source`, `actor_type` sin cambios

**Chosen:** un tercer valor de módulo en `use_cases.py`, `SCHEDULED_SOURCE = "pms_scheduled"`,
junto a `PMS_SOURCE`/`CSV_SOURCE`/`WEBHOOK_SOURCE` — mismo patrón, mismo comentario de por qué
no reutilizar `PMS_SOURCE` ("la pregunta que alguien le hace al timeline es *por qué cambió
esto ahora*"). `actor_type` se deja en su default, `SYSTEM`: el propio docstring de la clase ya
lo declara como la decisión (design D15) — "a command or, later, Celery beat runs this, and
there is no person to attribute it to" — escrito antes de que este change existiera.

Rejected: `TimelineActorType.SCHEDULER`, que sí usan `pricing`/`reviews`/`statements` para
trabajo disparado por el reloj. D15 ya fijó `SYSTEM` para esta clase específica citando el
propio job de beat que este change añade; cambiarlo ahora reabriría una decisión que el código
ya tomó, sin que la nota del roadmap ni la propuesta pidan revisarla.

### D5 — `make pms-sync` invoca el CLI, no una lógica nueva

**Chosen:** target de Makefile que llama `python -m app.integrations.cli.pms_sync` dentro del
contenedor `backend`, mismo patrón que `sim-advance` (`$(COMPOSE) exec -T backend python -m
app.cli.sim_advance ...`). El disparo manual del sync programado y el disparo manual "clásico"
son la misma operación con la misma ventana por defecto (30 días) — no hay razón para que
`make pms-sync` compile a otra ruta de código.

Rejected: un nuevo comando CLI dedicado al job de beat — duplicaría `pms_sync.py` sin ganar
nada, porque `run_for_every_tenant` ya generaliza "para cada tenant" y el CLI ya generaliza
"para un tenant"; el job de beat es la única pieza nueva de verdad.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Scheduler — calendario | `backend/app/scheduler/schedule.py` | Nueva entrada en `CADENCES`: `"sync_pms_reservations": timedelta(hours=6)`, con su comentario de docstring como las demás. |
| Scheduler — tarea | `backend/app/scheduler/tasks.py` | Nueva `async def _sync_pms_reservations(session, tenant_id, now)` (construye `SyncReservationsFromPmsUseCase` con las mismas dependencias que `pms_sync.py`, `since=now - timedelta(days=settings.pms_sync_window_days)`, `source=SCHEDULED_SOURCE`) y `@celery_app.task(name="sync_pms_reservations") def sync_pms_reservations() -> dict`, envuelta en `_guarded` como los demás. |
| Integraciones — atribución | `backend/app/integrations/application/use_cases.py` | `SCHEDULED_SOURCE = "pms_scheduled"` junto a los otros tres `*_SOURCE`, mismo comentario de intención. Sin cambios en `execute()` ni en su firma. |
| Config | `backend/app/core/config.py`, `.env.example` | `pms_sync_window_days: int = 2` en `Settings`, junto a los demás enteros de dominio; línea comentada `# PMS_SYNC_WINDOW_DAYS=2` en `.env.example`. |
| Operación manual | `Makefile` | Target `pms-sync:` junto a `sim-advance:`, invocando el CLI con `TENANT`/`WINDOW`/`PROVIDER` opcionales; añadir a `.PHONY`. |
| Tests | `backend/tests/scheduler/test_schedule.py`, `backend/tests/scheduler/test_tasks.py` (o el fichero que ya cubra los demás jobs) | Añadir `sync_pms_reservations` a la tabla transcrita (`BEYOND_PRD_8_3` o una nueva, con su comentario de divergencia) y un test de aislamiento entre dos tenants `MOCK`, replicando el patrón que ya prueban los demás jobs de reloj. |
| Specs (al archivar, no en este change) | `sdd/specs/celery-jobs.md`, `sdd/specs/reservations.md` | Los `SHALL` y correcciones que lista `proposal.md` en Affected specs. |

## Data & interfaces

Ninguna migración. Un `Settings` nuevo (`pms_sync_window_days`, entero, default 2). Un valor de
módulo nuevo (`SCHEDULED_SOURCE`) sin cambio de interfaz — el parámetro `source: str` de
`execute()` ya existía. Ninguna ruta HTTP nueva (R4 es explícitamente el CLI, no un endpoint —
ver Out of scope de la propuesta).

## Risks & mitigations

- **Coste de crédito Beds24**: 6 h es la cadencia recomendada por el proveedor, pero el uso de
  crédito real no está instrumentado todavía (`beds24-webhook-cutover-measurement` lo hará). Si
  un ciclo agota la cuota, `_sync_one_provider` ya captura el `PmsUnavailableError` del 429 sin
  abortar el tenant ni los demás — el ciclo reporta `provider_failures` y el siguiente ciclo,
  6 h después, vuelve a intentarlo. No se añade backoff ni alerta nueva: ningún otro job del
  calendario tiene una, y añadir una solo para este job sería inconsistente sin una razón que la
  propuesta no pide.
- **Doble trabajo con `process_webhook_events`**: ambos pueden re-leer la misma reserva en la
  misma ventana. `SyncReservationsFromPmsUseCase.execute` ya es idempotente sobre lo ya
  importado (`created`/`updated`/`skipped`), así que el peor caso es una lectura de más, no una
  duplicación — el mismo riesgo que ya acepta el CLI manual solapado con webhooks hoy.
- **`test_schedule.py` es el candado que impide que el job quede sin tabla**: si se olvida
  añadirlo a la transcripción, el test falla en rojo — no hay mitigación adicional que escribir
  porque el propio test es la mitigación.

## Open questions

Ninguna: las cuatro decisiones que la nota del roadmap dejaba abiertas (qué tenants, créditos,
credenciales por propiedad, gap de `TimelineEvent`) quedan resueltas en D2-D4 y en "Out of
scope" de la propuesta con una recomendación que ninguna alternativa de steering o del propio
código contradice.
