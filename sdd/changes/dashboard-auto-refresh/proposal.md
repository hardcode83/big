# Proposal: dashboard-auto-refresh

## Why

El dashboard ya muestra el estado operacional calculado por el backend, pero `useDashboardCards`
solo obtiene datos al montar, al reintentar o cuando una mutación invalida la consulta. El DoD del
MVP en PRD §28.2 exige que las property cards se actualicen en tiempo real; el hueco medido y
aceptado para este change se cerrará mediante refresco periódico automático (*near-real-time
polling*) con un intervalo MVP de 30 segundos, no mediante una nueva infraestructura de push.

Decisión de producto: para PRD §28.2, el MVP considera cumplimiento operativo de «tiempo real»
un dashboard que, mientras está activo, ejecuta polling automático con una cadencia nominal de 30
segundos. Esto no significa *true real-time*: no habrá push, WebSocket ni SSE.

El change se apoya exclusivamente en capacidades ya integradas en `main@b48fee86`: TanStack Query
v5, claves tenant-scoped, `useDashboardCards`, `purgeSessionCache()` y el patrón existente de
`refetchInterval` con `refetchIntervalInBackground: false` en notificaciones. La semántica será
explícitamente *near-real-time polling*; no se afirmará que existe *true real-time*.

## What changes

El dashboard existente refrescará periódicamente las cards mediante `useDashboardCards`, conservando
los datos previos mientras el refetch ocurre y sin mostrar de nuevo el skeleton completo. El refresco
seguirá ligado a la identidad tenant/session actual, no realizará polling cuando la pestaña esté en
background, y quedará cubierto por tests
focales de polling, refetch y cambio de tenant. No se añadirán endpoints, cambios backend ni
infraestructura WebSocket/SSE.

## Requirements

### R1 — Refresco periódico del estado operacional

**As a** propietaria o manager, **I want** que el dashboard consulte periódicamente las cards,
**so that** un cambio de estado operacional aparezca sin recargar manualmente la página.

Acceptance criteria:

1. WHEN `/dashboard` mantiene montada la consulta de cards, THE SYSTEM SHALL ejecutar refetches
   periódicos cada 30 segundos mediante las opciones existentes de TanStack Query y
   `useDashboardCards`.
2. WHEN un refetch periódico devuelve datos nuevos, THE SYSTEM SHALL actualizar las cards con la
   respuesta del servidor sin introducir un endpoint ni contrato nuevo.
3. THE SYSTEM SHALL describe este comportamiento como *near-real-time polling*, y SHALL NOT
   presentar WebSocket, SSE o push como parte de la solución.

### R2 — Continuidad visual durante background refetch

**As a** usuario del dashboard, **I want** conservar lo que ya estoy viendo mientras se consulta
una actualización, **so that** el refresco no provoque parpadeos ni pérdida de contexto.

Acceptance criteria:

1. WHILE una consulta de cards con datos previos está en background refetch, THE SYSTEM SHALL keep
   rendering those data and SHALL NOT replace them with the initial full-page skeleton.
2. IF el background refetch falla después de existir datos, THEN THE SYSTEM SHALL preserve the last
   successful cards and SHALL keep the existing error/retry semantics appropriate for stale data.
3. WHILE la primera carga no tenga datos, THE SYSTEM SHALL retain the existing loading, empty and
   page-level error states.

### R3 — Tenant y session isolation

**As a** usuario que puede cerrar sesión o cambiar de tenant, **I want** que el polling respete la
identidad actual, **so that** una respuesta antigua no aparezca en el dashboard del tenant siguiente.

Acceptance criteria:

1. WHEN the authenticated tenant changes, THE SYSTEM SHALL use the tenant-scoped dashboard query
   key and SHALL issue/refetch data for the new tenant without displaying cards belonging only to
   the previous tenant.
2. IF a request for the previous tenant resolves after the session or tenant changed, THEN THE
   SYSTEM SHALL NOT make that response visible under the new tenant.
3. WHEN the session cache is purged by the existing auth/session flow, THE SYSTEM SHALL NOT leave
   an active dashboard polling query serving the previous identity.

### R4 — Polling only while the application is active

**As a** usuario con una pestaña del dashboard abierta, **I want** que el navegador no haga
peticiones periódicas innecesarias cuando la pestaña está en background, **so that** el polling sea
proporcionado al uso real.

Acceptance criteria:

1. WHEN the dashboard tab is hidden, THE SYSTEM SHALL stop interval-based dashboard refetches while
   the tab/dashboard is not active.
2. WHEN the dashboard tab becomes active again, THE SYSTEM SHALL allow TanStack Query to refetch
   according to its configured normal stale/refetch behavior and SHALL resume interval-based
   refetches without requiring a new page load.

### R5 — Tests focales y compatibilidad de la superficie existente

**As a** maintainer, **I want** tests that exercise the polling and identity guarantees, **so that**
the §28.2 gap remains objectively verifiable without widening the change.

Acceptance criteria:

1. THE SYSTEM SHALL have focused frontend tests proving the configured periodic refetch behavior of
   `useDashboardCards`.
2. THE SYSTEM SHALL have a focused test proving that data remains visible during a background
   refetch and after a failed refetch when prior data exists.
3. THE SYSTEM SHALL have a focused tenant-switch/session test proving that a previous tenant's
   dashboard result is not rendered for the new tenant.
4. THE SYSTEM SHALL preserve the dashboard's existing responsive and accessible rendering and SHALL
   not alter activity feed, state-machine, API contract or backend behavior.

## Out of scope

- WebSockets, Server-Sent Events, backend push or cualquier infraestructura de tiempo real.
- Nuevos endpoints, cambios de contratos API/OpenAPI, state machine o backend.
- Rediseño del dashboard, activity feed u otras funcionalidades nuevas.
- Refactors no necesarios para añadir el polling y sus tests focales.
- Trabajo de CI, runners o gates.
- Afirmar *true real-time*: el resultado de este change es *near-real-time polling*.

## Affected specs

- `sdd/specs/dashboard-web-frontend.md` — documentar el refresco periódico, la conservación de
  datos durante background refetch y sus límites semánticos.
- `sdd/specs/frontend-auth-session.md` — consultar como contrato existente de purga de QueryClient
  y cambio de identidad; no se prevé modificarlo salvo que el design identifique una aclaración
  estrictamente necesaria.
