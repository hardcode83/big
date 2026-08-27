# Proposal: blocked-transition-response-ids

## Why

`blocked-transitions-web` está pausado en la sección 5 (mutaciones: cancel cleaning task, resolve incident) porque sus dos hooks —`useCancelCleaningTask({ taskId })` y `useResolveIncident({ incidentId })`— quedan tipados contra campos que `BlockedTransitionResponse` aún no trae. El gate del 2026-08-24 aprobó extender el schema como camino A (no como nueva ruta) en `sdd/changes/blocked-transitions-web/design.md` §OQ1, y este change lo ejecuta: añade los dos ids como campos opcionales, los resuelve por tenant, regenera el `openapi.json` y deja la tarjeta del dashboard lista para llamar a las mutaciones cuando el PR del frontend retome su sección 5.

## What changes

`BlockedTransitionResponse` (Pydantic v2, `backend/app/properties/api/schemas.py`) gana dos campos opcionales: `cleaning_task_id: uuid.UUID | None = None` cuando `blocking_state ∈ {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}`, e `incident_id: uuid.UUID | None = None` en el resto de estados. La resolución del id se hace en la capa de aplicación a partir de `property_id` + `blocking_state`, siempre dentro del `tenant_id` del token verificado. `backend/openapi.json` se regenera para que `frontend/lib/api/generated/openapi.d.ts` incluya los dos campos antes de que `blocked-transitions-web` levante la pausa.

## Requirements

### R1 — Schema: dos ids opcionales en `BlockedTransitionResponse`

**As a** frontend del dashboard de MAGNO, **I want** que `BlockedTransitionResponse` lleve `cleaning_task_id` e `incident_id` además de los seis campos actuales, **so that** mis hooks de mutación puedan leer la fila del card y dirigirse al recurso correcto sin pedirlo de nuevo.

Acceptance criteria:

1. WHEN el schema `BlockedTransitionResponse` se declara, THE SYSTEM SHALL incluir `cleaning_task_id: uuid.UUID | None = None` e `incident_id: uuid.UUID | None = None` además de los seis campos actuales (`property_id`, `property_code`, `reservation_id`, `trigger`, `blocking_state`, `due_since`).
2. WHEN un cliente existente consume `GET /api/v1/blocked-transitions`, THE SYSTEM SHALL seguir respondiendo con los seis campos originales y los dos nuevos como `null` cuando no apliquen; el envelope paginado y el formato de fechas ISO 8601 UTC no cambian.
3. WHERE los dos campos nuevos no aplican al bloqueo concreto, THE SYSTEM SHALL devolver `null` (no cadena vacía, no la cadena `"null"`, no `0`).
4. THE SYSTEM SHALL no introducir campos nuevos en el **request** del endpoint; el schema de entrada queda intacto.

### R2 — Población: id correcto según `blocking_state`

**As a** gestor que ve una fila en el dashboard, **I want** que la respuesta lleve el id del recurso accionable, **so that** el botón «Cancelar limpieza» o «Resolver incidencia» apunte a la tarea o incidencia real y no a un UUID que no existe.

Acceptance criteria:

1. WHERE `blocking_state ∈ {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}`, THE SYSTEM SHALL poblar `cleaning_task_id` con el id de la tarea de limpieza **abierta** de la vivienda en cuestión y dejar `incident_id = null`.
2. WHERE `blocking_state` no es de limpieza, THE SYSTEM SHALL poblar `incident_id` con el id de la incidencia **abierta** de la vivienda en cuestión y dejar `cleaning_task_id = null`.
3. IF no hay tarea de limpieza abierta para una vivienda en estado de limpieza, THEN THE SYSTEM SHALL devolver `cleaning_task_id = null` (la fila sigue listándose — la ausencia de la tarea es un dato, no un error).
4. IF no hay incidencia abierta para una vivienda en estado de incidencia, THEN THE SYSTEM SHALL devolver `incident_id = null` por la misma razón.
5. WHERE una vivienda tiene a la vez una tarea de limpieza abierta **y** una incidencia abierta, THE SYSTEM SHALL poblar sólo el id correspondiente al `blocking_state` y dejar el otro en `null` (la regla 1 impide leer ambas tablas a la vez por la misma fila, así que la coherencia es por estado, no por «la primera que encontremos»).

### R3 — Aislamiento por tenant en los lookups (regla 1 de `steering/security.md`)

**As a** operador de un tenant, **I want** que el id que recibo corresponda a una entidad de mi tenant y sólo de mi tenant, **so that** una fila de mi dashboard nunca me deje pulsar un botón contra un recurso de otro tenant.

Acceptance criteria:

1. WHEN se resuelve `cleaning_task_id`, THE SYSTEM SHALL ejecutar la consulta **dentro** del `tenant_id` del token verificado (no del path, no del body, no de la fila del dashboard); cualquier coincidencia fuera de ese tenant se ignora y la fila devuelve `null`.
2. WHEN se resuelve `incident_id`, THE SYSTEM SHALL ejecutar la consulta dentro del mismo `tenant_id`; la misma regla aplica.
3. THE SYSTEM SHALL no aceptar `tenant_id` por ningún canal de entrada — `extra="forbid"` lo rechaza con `422` antes de llegar al lookup.
4. THE SYSTEM SHALL resolver cada id como máximo una vez por fila (sin `N+1` por listado paginado): un único batch por tenant que cubra todas las viviendas de la página.

### R4 — Tests de aislamiento por tenant

**As a** mantenedor del cambio, **I want** tests que reproduzcan el escenario cross-tenant, **so that** un cambio futuro que meta el `tenant_id` a mano falle la suite antes de salir.

Acceptance criteria:

1. THE SYSTEM SHALL incluir un test donde, con dos tenants sembrados (cada uno con una vivienda en estado de limpieza y su tarea abierta), una petición con el token del tenant A reciba una fila cuyo `cleaning_task_id` es el id de la tarea del tenant A, no la del B.
2. THE SYSTEM SHALL incluir un test análogo para `incident_id`.
3. THE SYSTEM SHALL incluir un test donde una vivienda del tenant A aparece en `blocking_state` de limpieza pero la tarea que la desbloquearía pertenece al tenant B — `cleaning_task_id` SHALL ser `null` (no el id del otro tenant) y la fila SHALL seguir listándose.
4. THE SYSTEM SHALL incluir un test negativo donde `tenant_id` enviado por body o query string es ignorado y la respuesta se calcula sólo con el del token.

### R5 — Regeneración del contrato (frontend deriva tipos)

**As a** pipeline que mantiene `frontend/lib/api/generated/openapi.d.ts` actualizado, **I want** que el merge de este change traiga también el `openapi.json` regenerado, **so that** la siguiente build del frontend no rompa por tipos faltantes y `blocked-transitions-web` §5 pueda arrancar.

Acceptance criteria:

1. WHERE el cambio modifica `BlockedTransitionResponse`, THE SYSTEM SHALL regenerar `backend/openapi.json` antes del merge, y SHALL verificar —en CI— que `frontend/lib/api/generated/openapi.d.ts` lista `cleaning_task_id` e `incident_id` como campos opcionales (`string | null` o equivalente) tras correr `frontend/scripts/generate-api-types.mjs`.
2. IF la regeneración no incluye los dos campos en `openapi.d.ts`, THEN THE SYSTEM SHALL fallar la CI antes de permitir el merge.
3. THE SYSTEM SHALL no introducir breaking changes en `BlockedTransitionResponse`: los clientes que ya consumen los seis campos originales siguen recibiendo los mismos seis campos con el mismo formato.

## Out of scope

- **Los hooks de mutación del frontend** (`useCancelCleaningTask`, `useResolveIncident`, diálogos, action buttons) — viven en `sdd/changes/blocked-transitions-web/tasks.md` §5 y se implementan cuando este PR esté mergeado en `main`. Este change no toca `frontend/` salvo la regeneración mecánica de `openapi.d.ts`.
- **Los endpoints de mutación** (`POST /cleaning-tasks/{id}/cancel`, `POST /incidents/{id}/resolve`, etc.). Este change sólo añade ids de **lectura** al schema; las mutaciones ya existen o se entregan en cambios aparte.
- **Cambios en la máquina de estados** (`PropertyStateMachine`, `AdvancePropertyStatesUseCase`) — la detección de stalls no cambia, sólo se le añade un lookup del recurso accionable en la capa de aplicación.
- **Renombrar o reordenar los seis campos originales** de `BlockedTransitionResponse`. El shape público no rota: añadir es sumar, no reemplazar.
- **Persistencia de los ids en `BlockedTransition`** (el value object de dominio). Los ids son una **vista** sobre las tablas de `cleaning_tasks` e `incidents` ya existentes; meterlos en el dominio sería propagar presentación a una capa pura.

## Affected specs

- `sdd/specs/api-contract.md` — añadir a la sección de `BlockedTransitionResponse` los dos campos opcionales con su semántica (`blocking_state ∈ {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}` → `cleaning_task_id`, resto → `incident_id`) y la regla de tenant isolation en el lookup.
- `sdd/specs/celery-jobs.md` — el EARS del `GET /api/v1/blocked-transitions` (líneas 175-178) pasa a enunciar los ocho campos de la respuesta y a prohibir cross-tenant en la población; el cubo `blocked` del scheduler **no cambia** (sigue contando viviendas y emitiendo una línea por desajuste sin ids).
- `sdd/specs/dashboard-api.md` — si tiene un EARS del dashboard, reflejar la nueva forma; en cualquier caso, mantener la regla de `trigger`/`blocking_state` como literales canónicos sin prosa (mismo trato que `operational_state`).
- `sdd/specs/properties-crud.md` — comprobar si lista el schema; añadir los dos campos si lo hace.
- `docs/celery-jobs.md` — mencionar que la respuesta paginada del endpoint ahora incluye los ids (operativo, no normativo).

(specs marcadas como *(no existe aún)* — verificar al archivar; `dashboard-api.md` puede no tener un EARS dedicado a este endpoint y la edición podría ser nula)