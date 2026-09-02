# Proposal: dashboard-operational-kpis

## Why

El dashboard rediseñado (`docs/design/2026-08-23-stitch-export/`) añade sobre las property
cards reales tres tarjetas de KPI a nivel de tenant — limpiezas de hoy, próximos check-ins,
incidencias abiertas con su desglose de urgentes — que hoy no sirve ninguna ruta. La decisión
D4 de `visual-restyle-workspace` (Jose, 2026-08-23) las excluyó explícitamente de ese restyle
por no tener backend (*"lo que no tiene backend no entra en un restyle"*) y las registró como
tres entradas de roadmap propias; esta es la primera de las tres. Las tres cuentan datos que
el sistema **ya tiene** y no expone agregados — limpiezas, check-ins, incidencias — así que
son lecturas nuevas sobre dominios ya entregados (`cleaning`, `reservations`, `maintenance`),
no capability nueva. Medido en `sdd/roadmap/visual-restyle-workspace.md` D4: de las 76 rutas de
`backend/openapi.json`, ninguna sirve un conteo de tenant.

Esta entrada es **solo el backend**: la mitad `[FE]` que consume estos conteos queda,
deliberadamente, para quien la implemente cuando la composición visual pueda verse contra
datos reales (D4 de `visual-restyle-workspace`).

## What changes

Un nuevo endpoint agregado a nivel de tenant en `app/dashboard/` que devuelve los tres
conteos operacionales — limpiezas de hoy, check-ins en los próximos 7 días, incidencias
abiertas totales y su desglose de urgentes — leyendo los repositorios de `cleaning`,
`reservations` y `maintenance` ya existentes, siguiendo el mismo patrón de composición sin
`infrastructure/` propia que ya usan `GetDashboardCardsUseCase`/`GetPropertyDashboardUseCase`
(decisión D1 de `dashboard-api`).

## Requirements

### R1 — Conteo de limpiezas de hoy

**As a** manager o propietaria autenticada, **I want** ver cuántas limpiezas hay programadas
para hoy en todo el tenant, **so that** entender de un vistazo la carga operativa del día sin
recorrer cada vivienda (principio 2 de `steering/product.md`: el dashboard responde "¿qué
pasa?" en <10s).

Acceptance criteria:

1. WHEN se solicita el endpoint de KPIs operacionales, THE SYSTEM SHALL contar las
   `CleaningTask` del tenant cuyo `scheduled_start` cae en la fecha de hoy (UTC, coherente con
   la convención de fechas ISO 8601 UTC de `steering/backend.md`) y cuyo `status` esté en
   `LIVE_STATUSES` (`CREATED, ASSIGNED, ACCEPTED, IN_PROGRESS`).
2. THE SYSTEM SHALL excluir del conteo las tareas en `COMPLETED`, `CANCELLED`, `REJECTED` o
   `FAILED`.
3. IF el tenant no tiene ninguna `CleaningTask` programada hoy, THEN THE SYSTEM SHALL devolver
   `0`, nunca `null`.

### R2 — Conteo de check-ins próximos

**As a** manager o propietaria autenticada, **I want** ver cuántos check-ins llegan en los
próximos días en todo el tenant, **so that** anticipar la preparación de accesos y limpiezas
antes de que lleguen los huéspedes.

Acceptance criteria:

1. WHEN se solicita el endpoint de KPIs operacionales, THE SYSTEM SHALL contar las
   `Reservation` del tenant cuyo `check_in_date` cae entre hoy (UTC, inclusive) y hoy + 7 días
   (inclusive).
2. THE SYSTEM SHALL excluir del conteo las reservas en `CANCELLED` o `NO_SHOW`.
3. IF el tenant no tiene ningún check-in en la ventana, THEN THE SYSTEM SHALL devolver `0`,
   nunca `null`.

`ASSUMPTION`: la ventana de 7 días no está en el PRD ni en la maqueta (que solo insinúa un
número de relleno, "18", desautorizado por D4 de `visual-restyle-workspace` como orden de
magnitud a diseñar) — decidida con Jose al escribir esta propuesta.

### R3 — Conteo de incidencias abiertas, con desglose de urgentes

**As a** manager o propietaria autenticada, **I want** ver cuántas incidencias siguen abiertas
en todo el tenant y cuántas de ellas son urgentes, **so that** priorizar sin tener que abrir el
listado completo de incidencias.

Acceptance criteria:

1. WHEN se solicita el endpoint de KPIs operacionales, THE SYSTEM SHALL contar los `Incident`
   del tenant cuyo `status` esté en `OPEN_INCIDENT_STATUSES`
   (`frozenset(IncidentStatus) - {RESOLVED, CANCELLED}`, ya definido en
   `backend/app/maintenance/domain/entities.py`).
2. THE SYSTEM SHALL desglosar, dentro de ese mismo conteo, cuántas de esas incidencias abiertas
   tienen `severity` en `{HIGH, CRITICAL}` como subconjunto "urgentes".
3. IF el tenant no tiene ninguna incidencia abierta, THEN THE SYSTEM SHALL devolver `0` en
   ambos campos (total y urgentes), nunca `null`.

`ASSUMPTION`: el umbral de "urgente" (`HIGH`+`CRITICAL` frente a solo `CRITICAL`) no está en el
PRD — decidido con Jose al escribir esta propuesta.

### R4 — Tenant scoping y redacción por permiso de origen

**As a** operador del sistema, **I want** que el endpoint de KPIs respete el aislamiento de
tenant y el permiso que protege cada dominio de origen, **so that** ningún rol vea agregados de
un dominio que no puede leer individualmente y ningún tenant vea datos de otro.

Acceptance criteria:

1. THE SYSTEM SHALL derivar el `tenant_id` del `RequestContext` autenticado (regla 1 de
   `steering/security.md`), nunca de un parámetro de la petición, y SHALL incluirlo en toda
   query contra `cleaning_tasks`, `reservations` e `incidents`.
2. THE SYSTEM SHALL declarar `require(Permission.READ_PROPERTIES)` en la ruta, siguiendo el
   patrón ya establecido en `sdd/specs/dashboard-api.md` ("Permisos: agregar no concede") para
   las otras rutas de `app/dashboard/`.
3. WHERE el rol que llama carece del permiso que protege el **origen** de un conteo —
   `READ_CLEANING_TASKS` para limpiezas de hoy, `READ_RESERVATIONS` para check-ins,
   `READ_INCIDENTS` para incidencias abiertas —, THE SYSTEM SHALL devolver ese campo como
   `null` en vez de `0`, distinguible de "no hay ninguno".
4. THE SYSTEM SHALL tener un test de aislamiento de tenant por conteo (regla 1 de
   `steering/security.md`) que demuestre que un tenant no ve los conteos de otro.

## Out of scope

- La mitad `[FE]` que consume y pinta estas tres tarjetas — queda para una entrada de roadmap
  propia, cuando la composición visual pueda verse contra datos reales (D4 de
  `visual-restyle-workspace`).
- La serie de ocupación semanal (`dashboard-occupancy-series`) y el feed de actividad
  cross-propiedad (`dashboard-activity-feed`) — son las otras dos entradas nacidas de la misma
  decisión D4, con su propio endpoint y su propio proposal.
- El buscador global de la maqueta — D4 lo descarta explícitamente por no ser un dato que el
  sistema ya tenga, sino una capability nueva de pleno derecho.
- Cambiar el comportamiento de `CleaningTaskStatus`, `ReservationStatus`, `IncidentStatus` o
  `IncidentSeverity` — este change solo lee esos enums, no los modifica.
- Configurabilidad de la ventana de 7 días o del umbral de severidad urgente (por tenant, por
  rol, etc.) — quedan fijos en el backend hasta que haya una necesidad de producto que lo pida.

## Affected specs

- `sdd/specs/dashboard-api.md` — se amplía con el nuevo endpoint de KPIs operacionales, su
  contrato, su regla de redacción por permiso y sus tests de aislamiento, siguiendo la
  estructura ya usada para `/dashboard/properties` y `/properties/{id}/dashboard`.
