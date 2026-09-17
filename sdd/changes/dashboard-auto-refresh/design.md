# Design: dashboard-auto-refresh

## Context

El dashboard consume las property cards desde `frontend/features/dashboard/hooks/use-dashboard-data.ts`
mediante `useDashboardCards`, con una clave construida por
`dashboardKeys.cards(tenantId, locale)`. La consulta usa el `DashboardDataSource` HTTP existente y
el cliente TanStack Query v5 configurado en `frontend/lib/query/query-client.ts`, cuyo
`staleTime` global es 60 segundos y cuyo `refetchOnWindowFocus` global es `false`.

El proyecto ya tiene un patrón de polling en
`frontend/features/notifications/hooks/use-unread-count.ts`: `refetchInterval` junto con
`refetchIntervalInBackground: false`. La continuidad de sesión ya se protege mediante
`purgeSessionCache()` en `frontend/lib/auth/session-cache-purge.ts`, que avanza la generación y
limpia el QueryClient cuando cambia la identidad.

`frontend/features/dashboard/components/dashboard-view.tsx` muestra el skeleton solo cuando
`cardsQuery.isPending` es verdadero. TanStack Query conserva `data` durante un refetch posterior,
por lo que una consulta con datos previos no vuelve al estado de carga inicial.

## Decisions

### D1 — Polling nominal de 30 segundos en `useDashboardCards`

**Chosen:** definir una constante local de intervalo MVP de 30.000 ms y pasarla como
`refetchInterval` en la configuración de `useDashboardCards`.

La cadencia pertenece a la consulta que representa el requisito §28.2 y no al cliente global:
detail, timeline y otras consultas del dashboard no deben empezar a hacer polling por herencia.
La constante será testeable y el contrato se describirá como cadencia nominal, no como garantía
de latencia o de *staleness*.

Rejected: cambiar el `staleTime` global — afectaría consultas no relacionadas y no configura
refetch periódico por sí mismo.

Rejected: añadir un timer o `setInterval` manual en `DashboardView` — duplicaría el scheduler de
TanStack Query y separaría el ciclo de polling del estado de la consulta.

### D2 — Suspensión determinista cuando la pestaña no está activa

**Chosen:** configurar `refetchIntervalInBackground: false` junto al intervalo de 30 segundos,
siguiendo el patrón ya usado por `useUnreadCount`.

Esto hace que no se ejecuten refetches basados en intervalo mientras la pestaña/dashboard está
oculta. Al volver a estar activa, TanStack Query reanuda el intervalo normal sin recargar la
página. No se introduce ni se presupone ningún refetch adicional por activación: la configuración
global existente mantiene `refetchOnWindowFocus: false`.

Rejected: añadir listeners propios de `visibilitychange` — duplicaría una capacidad ya ofrecida
por TanStack Query y ampliaría innecesariamente el change.

### D3 — Conservar datos durante el background refetch

**Chosen:** no cambiar el estado de renderizado de `DashboardView`; mantener la condición de
`cardsQuery.isPending` para distinguir solo la primera carga sin datos. La query conservará la
respuesta anterior mientras `isFetching`/el refetch periódico esté activo.

Un error posterior al primer éxito seguirá dejando `data` disponible y no activará el skeleton.
La pantalla mantendrá las cards y sus estados existentes; el manejo de error inicial y el botón de
retry permanecen sin cambios.

Rejected: añadir `placeholderData` o un estado de carga nuevo — no hace falta para conservar datos
reales y podría ocultar la diferencia entre primera carga y refetch.

### D4 — Aislamiento de tenant mediante la identidad y las claves existentes

**Chosen:** conservar `useTenantId()` como única fuente de `tenantId` y mantener
`dashboardKeys.cards(tenantId, locale)` como query key. No se añadirá estado local ni se aceptará
un tenant como parámetro.

Al cambiar la identidad, TanStack Query obtiene una clave distinta; la ausencia de
`placeholderData` entre claves evita presentar automáticamente la respuesta del tenant anterior.
El flujo existente de auth purga el QueryClient en transiciones de identidad, cancelando la
superficie de caché anterior. La query function seguirá recibiendo el tenant solo para respetar la
interfaz existente del data source; no se cambia el contrato HTTP.

Rejected: limpiar manualmente la caché desde el dashboard — duplicaría la responsabilidad de
`AuthProvider`/`purgeSessionCache()` y podría introducir una carrera entre superficies.

Rejected: capturar el tenant en un timer manual — haría que el polling pudiera sobrevivir a la
identidad que lo originó.

### D5 — Tests focales en la frontera de query y la vista existente

**Chosen:** cubrir la configuración y el comportamiento observable con tests frontend focales:

- un test de `useDashboardCards` con `QueryClientProvider`, reloj fake y data source controlado
  comprobará el intervalo nominal y que el refetch usa la misma clave tenant/locale;
- tests de `DashboardView` mantendrán una respuesta previa mientras la query está en refetch y
  tras un error posterior, comprobando que no aparece el skeleton completo;
- un test de hook/query hará switch de tenant y comprobará que la respuesta del tenant anterior no
  se renderiza bajo la nueva clave;
- el comportamiento de pestaña oculta se verificará sobre la opción
  `refetchIntervalInBackground: false`, sin introducir un listener propio.

Rejected: E2E o cambios backend — el requisito es de configuración y presentación frontend, y no
necesita infraestructura nueva ni un endpoint adicional.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dashboard query | `frontend/features/dashboard/hooks/use-dashboard-data.ts` | Añadir constante MVP de 30 s, `refetchInterval` y `refetchIntervalInBackground: false` únicamente a `useDashboardCards`. |
| Dashboard view | `frontend/features/dashboard/components/dashboard-view.tsx` | No se prevé cambio funcional; verificar que `isPending` conserva datos durante background refetch. Solo tocar si un test demuestra que el render actual no cumple R2. |
| Dashboard tests | `frontend/features/dashboard/...` tests focales existentes o un test de hook junto a `use-dashboard-data.ts` | Cubrir polling, datos durante refetch/error, tenant switch y suspensión en background. |
| Living spec | `sdd/specs/dashboard-web-frontend.md` | Documentar polling nominal de 30 s mientras está activo, suspensión en background y límite semántico de near-real-time. Se actualiza al archivar, no durante esta fase de diseño. |

## Data & interfaces

No hay cambios de esquema, migraciones, endpoints, OpenAPI, DTOs, query-key shape, permisos,
sesiones backend ni variables de entorno. El intervalo es una constante de frontend, no una
configuración del tenant ni un nuevo contrato público.

## Risks & mitigations

- **Carga de red:** 30 s añade una petición periódica por dashboard activo. Se limita a
  `useDashboardCards`, se detiene en background y reutiliza el ciclo de TanStack Query.
- **Latencia, errores o suspensión del navegador:** la cadencia de 30 s es nominal y no garantiza
  un máximo de *staleness*. La documentación y los tests no harán esa afirmación.
- **Parpadeo o pérdida de contexto:** `DashboardView` sigue comprobando `isPending`, no un estado
  genérico de fetching; los datos previos permanecen visibles durante el refetch.
- **Filtración entre tenants:** las claves incluyen `tenantId`, no se usa `placeholderData` entre
  tenants y el auth flow existente limpia el QueryClient durante el cambio de identidad. El test
  de switch cubrirá la garantía observable.
- **Interacción con `refetchOnWindowFocus: false`:** al volver a una pestaña activa no se
  presupone un comportamiento global nuevo; se conserva la configuración actual y se reanuda el
  intervalo conforme a TanStack Query. El test verificará únicamente las garantías explícitas de
  este change.

## Open questions

Ninguna. La cadencia MVP, la semántica de near-real-time y la suspensión en background están
decididas en la propuesta aprobada; no se requiere una decisión de arquitectura ni de producto.
