# Design: blocked-transitions-web

## Context

`GET /api/v1/blocked-transitions` ya existe desde `cleaning-stall-blocks-next-stay` (archivado
2026-08-24) y está cubierta por `sdd/specs/celery-jobs.md` §«Desajustes entre el calendario y el
estado»: envelope paginado de PRD §23, permiso `READ_PROPERTIES`, ordenado por `due_since`
ascendente, cada entrada con `property_id`, `property_code`, `reservation_id`, `trigger`,
`blocking_state` y `due_since` — los dos últimos como literales canónicos sin prosa.

`dashboard-api` ya entrega las cards en `frontend/features/dashboard/components/property-card.tsx`,
con su orden de regiones por §9.1 (`property-state-badge`, incidencias abiertas, próxima acción,
reserva, limpieza, último evento). Las mutaciones ya viven: `POST /api/v1/cleaning-tasks/{id}/cancel`
(`sdd/specs/cleaning.md` §«La salida de excepción») y `POST /api/v1/incidents/{id}/resolve`
(`sdd/specs/maintenance.md` §R4). El espejo de permisos del frontend está en
`frontend/lib/auth/permissions.ts` con sólo `MANAGE_CLEANING_TASKS` y `MANAGE_PRICE_RECOMMENDATIONS`;
`EXECUTE_INCIDENTS` no está todavía. Los catálogos ES/EN están en `frontend/locales/{es,en}/*.json`,
registrados en `frontend/lib/i18n/resources.ts` y protegidos por paridad en
`frontend/lib/i18n/catalog-parity.test.ts`.

Este change es el consumidor del endpoint que su change antecesor dejó sin pintar: hacer llegar el
dato a la persona, en `locales/es` **y** `locales/en`, y darle una salida cuando su rol lo permita.

## Decisions

### D1 — Un único fetch de stalls en el dashboard, slice por `property_id` en el render

**Chosen:** Una sola query TanStack Query
`['tenant', tenantId, 'blocked-transitions', page]` montada en `DashboardView` consume la primera
página del endpoint, y `PropertyCard` recibe su lista filtrada por `property_id` desde el slice en
memoria del `useBlockedTransitions`. Sin N+1, sin parámetro nuevo en el endpoint.

Rejected: una query por card (`useBlockedTransitions(propertyId)` invocada dentro de
`PropertyCard`). El endpoint actual `list_blocked_transitions_api_v1_blocked_transitions_get`
sólo conoce `page`/`per_page`, así que añadir `property_id` exige un cambio de contrato
(`backend/app/properties/api/router.py`) y un caso de prueba de aislamiento por tenant para esa
clave; pagar eso para evitar un `data.filter(...)` en cliente con dos viviendas y dos o tres
stalls sería estirar el contrato sin motivo. Además: si más adelante la pantalla crece en
paginación, la única que necesita saber de páginas es la query global.

Rejected: integrar los stalls en el `HttpDashboardSource.getDashboardCards` (un envelope
monolítico por vivienda). Mezcla dos responsabilidades —lista de cards y desajustes— y obliga a
paginarlas a la vez: la card ya tiene `page`/`per_page` propios.

### D2 — DTO fiel al contrato OpenAPI; ningún campo inventado

**Chosen:** `BlockedTransitionSummary` re-exporta los seis campos del esquema generado
(`property_id`, `property_code`, `reservation_id`, `trigger`, `blocking_state`, `due_since`),
importados de `components["schemas"]["BlockedTransitionResponse"]` en
`frontend/lib/api/generated/openapi.d.ts:970`. Sin campos derivados — ni `severity`, ni
`housekeeping_kind`, ni fechas re-formateadas—: la pantalla formatea `due_since` con `Intl` y el
resto pasa como literal canónico (R4.2).

Rejected: reescribir el DTO con nombres `camelCase` y un campo `humanKey`. El backend ya entrega
los literales canónicos por una razón que `cleaning-stall-blocks-next-stay` R2.2 declara: el
traductor no puede saber la prosa de un literal que ya era "lo que el backend emite"; añadir un
`humanKey` en el cliente sería el catálogo paralelo que R4.3 prohíbe.

### D3 — Mapping `trigger × blocking_state → ActionKind` declarado en un solo sitio, exhaustivo

**Chosen:** Una tabla `Record<ClockTrigger, Record<PropertyOperationalState, ActionKind | null>>`
en `frontend/features/dashboard/stalls/lib/action-map.ts`, con la unión cerrada de los tres
triggers del reloj (`CHECKIN_WINDOW_OPENED`, `CHECKIN_TIME_REACHED`, `CHECKOUT_TIME_REACHED`) y
los once estados operacionales. Tipo
`Record<ClockTrigger, Record<PropertyOperationalState, ActionKind>>` con default `null` en
tiempo de ejecución; el tipo se cierra con `Exclude<…, …>` a `never` para que añadir un trigger o
un estado sea error de compilación, igual que la guarda de exhaustividad de `TIMELINE_EVENT_TYPES`
(`dashboard-web-frontend.md` §Timeline). Las dos entradas activas son:

| `trigger` \ `blocking_state` | `AWAITING_CLEANING`, `CLEANING_IN_PROGRESS`, `CLEANING_SCHEDULED` | `MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT` | resto |
|---|---|---|---|
| `CHECKIN_WINDOW_OPENED`, `CHECKIN_TIME_REACHED` | `cancel-cleaning` | `resolve-incident` | `null` |
| `CHECKOUT_TIME_REACHED` | `null` | `resolve-incident` | `null` |

`cancel-cleaning` exige `MANAGE_CLEANING_TASKS`; `resolve-incident` exige `EXECUTE_INCIDENTS`. El
resto de combinaciones son `null` — informativo sin acción— y eso lo cubren los tests de la tabla
sin más estructura.

Rejected: `if (state === 'AWAITING_CLEANING' || state === 'CLEANING_IN_PROGRESS' || …)` repartido
por el componente. R1.5 lo prohíbe expresamente y es además el modo de divergencia que la guarda
de exhaustividad de D3 cierra.

Rejected: importar la matriz desde el backend y derivar el mapping. La matriz
`PropertyStateMachine.source_states_for` describe qué transiciones son legales; **no** describe
qué botón pintamos. La primera es del motor de estados; el segundo es del catálogo de
capacidades que esta entrada estrena, y se queda en el frontend como cualquier otro mapeo de UI
que vive del lado del cliente.

### D4 — `EXECUTE_INCIDENTS` se añade al espejo parcial de permisos

**Chosen:** `Permission` union gana `EXECUTE_INCIDENTS`; `ROLE_UI_PERMISSIONS` declara
`PROPERTY_MANAGER: [..., "EXECUTE_INCIDENTS"]` y deja el resto sin cambios. `TENANT_OWNER` no lo
lleva — `backend/app/auth/domain/policy.py:286` lo confirma: la propietaria está en `_INCIDENT_READ`
sólo, no en `_INCIDENT_EXECUTE`. Esto cumple R2.4 (nunca pintar un botón que responderá 403).

Rejected: añadir un `useHasPermission("MANAGE_INCIDENTS")` paralelo. `MANAGE_INCIDENTS` cubre
asignar y clasificar (`policy.py:208`), que son del manager pero no son la acción del card; el
card resuelve, y resuelve es `EXECUTE_INCIDENTS`. Copiar el primero y leer el segundo sería el
mismo error que `frontend.md` §Authentication integration boundary declara sobre el espejo: «una
entrada equivocada esconde un control que el backend permite, y ningún test fuera del espejo lo
pilla».

### D5 — Mutaciones vía hooks dedicados con invalidación cruzada

**Chosen:** Dos hooks `useCancelCleaningTask()` y `useResolveIncident()` en
`frontend/features/dashboard/stalls/hooks/`, ambos `retry: false` (una escritura rechazada no se
reintenta — mismo razonamiento que `useAssignCleaningTask`), y `onSettled` invalida **tres**
claves: `dashboardKeys.blockedTransitions(tenantId)` (R3.2), la lista de tasks/incidents del
tenant y el detalle de la propiedad afectada. La invalidación es por prefijo, así que `cleaning`
e `incidents` invalidan sus listas paginadas sin enumerar páginas.

Rejected: invalidar sólo `blockedTransitions`. La acción cambia la task/incidencia de la que sale
el desajuste, pero también el `cleaningStatus` y `openIncidentsCount` de la card; sin refrescar
las otras dos, el dashboard queda medio nuevo.

Rejected: actualizar la cache optimistamente. La sección §La salida de excepción de
`sdd/specs/cleaning.md` admite que la cancelación puede mover la vivienda a `OCCUPIED_ESTIMATED`
o `AWAITING_CLEANING` con tarea de reemplazo — el resultado lo cuenta `PropertyStateMachine`, no
el cliente; un patch optimista mentiría.

### D6 — `trigger`/`blocking_state` se pintan como literales canónicos, sin prosa

**Chosen:** El componente renderiza los dos campos como texto literal (`CHECKIN_TIME_REACHED`,
`AWAITING_CLEANING`) en un `<code>` con tipografía monoespaciada, sin traducirlos. El color, si
lo hay, sale del mismo `STATE_COLOR_GROUP` que `PropertyStateBadge`
(`frontend/components/property-state-badge.tsx:45`) aplicaría a `blocking_state` —
`MAINTENANCE_REQUIRED` → ámbar, `CRITICAL_INCIDENT` → rojo, `AWAITING_CLEANING` → ámbar. Eso
cumple R4.2 sin meter un catálogo paralelo.

Rejected: traducir los literales con un `Object.fromEntries` en `locales/dashboard.json`. R4.3 lo
prohíbe: «no SHALL introducir un catálogo paralelo de traducciones de los literales». El backend
los emite sin prosa por diseño.

### D7 — Motivo obligatorio en la cancelación, opcional en la resolución, ambos como input tipado

**Chosen:** `useCancelCleaningTask({ taskId, reason })` exige `reason: string` no vacío (acotado
a 500 caracteres en el backend, `cleaning.md`); `useResolveIncident({ incidentId, finalCost })`
exige `finalCost: number | string` (un decimal en string o un número — el esquema Pydantic acepta
ambos, `ResolveIncidentRequest` en `openapi.d.ts:3266`). El motivo de la limpieza se pide en un
mini-formulario antes del `mutationFn`; el `final_cost` de la incidencia se pide en el mismo
formulario porque la acción sin él es un 422. `materials` se omite del formulario — es opcional y
no es la palanca del card: se documenta en `docs/properties.md` que el manager puede añadirlo
desde `/incidents/{id}` cuando lo necesite.

Rejected: pedir el motivo de la limpieza en un `window.prompt`. Ni el aviso tiene que sobrevivir
a un refresh ni el estilo del producto acepta `prompt` del navegador. El mini-formulario es un
modal con foco inicial en el textarea, `role="alert"` para el error, `aria-describedby` entre el
label y el input — el patrón es el mismo que la pantalla de `/cleaning` ya implementa.

### D8 — `docs/properties.md` declara el límite de la ventana operativa

**Chosen:** Una sección «Aviso de desajustes en la card del dashboard» en
`docs/properties.md`, debajo del bloque actual de limpieza. Copia: explica que la ventana es la
misma `candidate_window` del job (30 días atrás, 2 adelante), que un atasco de más de 30 días
**deja de aparecer** sin ser culpa de la pantalla, y que el color y el literal no prometen
exhaustividad. La card enlaza a la sección con un texto de una línea (R5.1) que sale del
namespace `dashboard` y no del `docs/`.

Rejected: documentarlo en `docs/celery-jobs.md` (donde vive la ventana original). R5.1 lo prohíbe
al nombrar «docs/properties.md» como la casa del aviso del lado de la propietaria/manager.

### D9 — Feature separada `features/dashboard/stalls/`, barrel por la feature padre

**Chosen:** La lógica nueva vive bajo `frontend/features/dashboard/stalls/` con un barrel
`index.ts` que exporta sólo lo que `dashboard-view.tsx` y `property-card.tsx` consumen (`useBlockedTransitions`,
`BlockedTransitionsSection`, `actionMapFor`). El resto del tree (otros features, el shell) sólo
ve la exportación de `features/dashboard` ya existente — `dashboard-view.tsx` la re-exporta.

Rejected: ensanchar `features/dashboard/components/property-card.tsx` directamente. La card ya
tiene cinco regiones y dos regiones más (stalls, action confirm) la hinchan y rompen el test de
orden de regiones de `property-card.test.tsx:74`. Un sub-componente mantiene la card bajo control.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Feature — stalls (nuevo) | `frontend/features/dashboard/stalls/index.ts` | Barrel: re-exporta `useBlockedTransitions`, `BlockedTransitionsSection`, `actionMapFor`, `ActionKind`. |
| Feature — stalls | `frontend/features/dashboard/stalls/lib/action-map.ts` | Tabla exhaustiva `trigger × blocking_state → ActionKind \| null` + tipos `ClockTrigger`, `ActionKind`, guardia `Exclude<…, never>`. |
| Feature — stalls | `frontend/features/dashboard/stalls/lib/action-map.test.ts` | Tests de la tabla: una entrada por combinación del producto cartesiano, sin `if`s solapados en el componente. |
| Feature — stalls | `frontend/features/dashboard/stalls/data/dto.ts` | `BlockedTransitionSummary` re-exportado del OpenAPI. |
| Feature — stalls | `frontend/features/dashboard/stalls/data/stalls-source.ts` | `StallsDataSource` interface (un método, `listBlockedTransitions(tenantId, page)`). |
| Feature — stalls | `frontend/features/dashboard/stalls/data/http/http-stalls-source.ts` | `HttpStallsSource` mapeando `snake_case` → DTO. |
| Feature — stalls | `frontend/features/dashboard/stalls/data/index.ts` | Composition point con `createAuthenticatedClients`. |
| Feature — stalls | `frontend/features/dashboard/stalls/data/mock/mock-stalls-source.ts` | Solo para tests (R3.2 cobertura). |
| Feature — stalls | `frontend/features/dashboard/stalls/hooks/query-keys.ts` | `stallsKeys.list(tenantId, page)` siguiendo `tenantScopedKey`. |
| Feature — stalls | `frontend/features/dashboard/stalls/hooks/use-blocked-transitions.ts` | Hook que entrega `{ data, byBy,` y `Map<propertyId, BlockedTransitionSummary[]>` ordenado por `due_since` ascendente. |
| Feature — stalls | `frontend/features/dashboard/stalls/hooks/use-cancel-cleaning-task.ts` | `useMutation` `retry: false`; invalida `dashboardKeys.blockedTransitions(tenantId, *)` + `cleaningKeys.tasksPrefix(tenantId)`. |
| Feature — stalls | `frontend/features/dashboard/stalls/hooks/use-resolve-incident.ts` | `useMutation` `retry: false`; invalida `dashboardKeys.blockedTransitions(tenantId, *)` + la query de incidents + `dashboardKeys.propertyDetail` y `dashboardKeys.cards`. |
| Feature — stalls | `frontend/features/dashboard/stalls/components/blocked-transitions-section.tsx` | Renderiza la lista de stalls en una `<section>` con `aria-labelledby`; por stall, `trigger`, `blocking_state`, `due_since` formateado, y un botón si el rol lo permite. |
| Feature — stalls | `frontend/features/dashboard/stalls/components/cancel-cleaning-dialog.tsx` | Modal con `reason` obligatorio (max 500 chars, contador visible). |
| Feature — stalls | `frontend/features/dashboard/stalls/components/resolve-incident-dialog.tsx` | Modal con `final_cost` obligatorio (decimal positivo). |
| Dashboard cards | `frontend/features/dashboard/components/property-card.tsx` | Acepta `stalls: BlockedTransitionSummary[]` opcional; renderiza `<BlockedTransitionsSection>` si la lista no está vacía. Mantiene el orden de regiones (R5.4 de `dashboard-web-frontend.md`). |
| Dashboard cards | `frontend/features/dashboard/components/dashboard-view.tsx` | Llama `useBlockedTransitions()`, indexa por `propertyId` y pasa el slice a cada `PropertyCard`. |
| Permisos | `frontend/lib/auth/permissions.ts` | `Permission` union añade `"EXECUTE_INCIDENTS"`; `PROPERTY_MANAGER: [..., "EXECUTE_INCIDENTS"]` (R2.4). |
| Permisos | `frontend/lib/auth/permissions.test.tsx` | Test que `PROPERTY_MANAGER` con `EXECUTE_INCIDENTS` y `MANAGE_CLEANING_TASKS`, `TENANT_OWNER` sin ninguno, `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` sin ninguno (R2.4). |
| i18n | `frontend/locales/es/dashboard.json` | Bloque `card.blocked` con título, descripción, formato `due_since`, `cancel.cleaning.{label, reason.label, reason.placeholder, confirm, sending, error.empty, error.generic}`, `resolve.incident.{…}`, `error.{fetch, forbidden, conflict, generic}`. |
| i18n | `frontend/locales/en/dashboard.json` | Mismo bloque en EN. |
| Docs | `docs/properties.md` | Sección «Aviso de desajustes en la card del dashboard»: ventana de 30 días, sin promesa de exhaustividad, enlace desde la card (R5.1-R5.3). |
| Tests | `frontend/features/dashboard/stalls/**/*.test.{ts,tsx}` | Cobertura de hooks, sección, dialogs, mapeo de errores. |

## Data & interfaces

**Backend, sin cambios en el contrato actual.** El `BlockedTransitionResponse` que
`cleaning-stall-blocks-next-stay` publicó es lo que el frontend consume. La acción de los botones
necesita el id del recurso (`cleaning_task_id`, `incident_id`) y la respuesta actual **no lo
lleva** — `openapi.d.ts:970` enumera sólo seis campos. Sin el id, no hay forma de llamar a
`POST /api/v1/cleaning-tasks/{id}/cancel` ni a `POST /api/v1/incidents/{id}/resolve`.

Esto se resuelve en el backend (no en este change) y se declara como **OQ1**. La dirección
preferida es extender `BlockedTransitionResponse` con dos campos opcionales:

```python
class BlockedTransitionResponse(BaseModel):
    # …campos existentes…
    cleaning_task_id: uuid.UUID | None = None  # cuando blocking_state ∈ {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}
    incident_id: uuid.UUID | None = None       # cuando blocking_state ∈ {MAINTENANCE_REQUIRED, CRITICAL_INCIDENT}
```

`stalls.detect` (`backend/app/properties/domain/stalls.py`) ya tiene a mano la `property
 y la `reservation_id`; resolver el `cleaning_task_id` por
`(property_id, reservation_id, status IN {CREATED, ASSIGNED, ACCEPTED, IN_PROGRESS})` y el
`incident_id` por `(property_id, status NOT IN {RESOLVED, CANCELLED})` es una lectura acotada
sobre el mismo tenant. La regla 1 de `steering/security.md` obliga a probar el aislamiento de
esas dos lecturas en un test dedicado. La decisión es del change que la proponga, no de éste;
este change deja los hooks de mutación ya escritos y un test de D5 que se quedará rojo hasta que
el id exista, para que el gap no se cierre en silencio.

**Frontend, sin nuevos endpoints.** Las mutaciones se hacen por los endpoints ya existentes:

- `POST /api/v1/cleaning-tasks/{task_id}/cancel` — body `{ reason: string }`, requiere
  `MANAGE_CLEANING_TASKS`. `openapi.d.ts:1030` declara `CancelCleaningTaskRequest` con `reason`
  required y `CleaningTaskResponse` como `200`.
- `POST /api/v1/incidents/{incident_id}/resolve` — body `{ final_cost: number | string,
  materials?: string | null }`, requiere `EXECUTE_INCIDENTS`. `openapi.d.ts:3266` declara
  `ResolveIncidentRequest`; el manager del dashboard usa sólo `final_cost` (R3.1).

**Frontend, cambios en el espejo de permisos.** `Permission` union gana `EXECUTE_INCIDENTS`
(D4). `ROLE_UI_PERMISSIONS['PROPERTY_MANAGER']` lo declara; el resto de roles queda igual.

## Risks & mitigations

- **R1 — Riesgo de N+1 si el endpoint gana `property_id` y los componentes lo invocan por card.**
  Mitigación: la query vive en `DashboardView`, no en `PropertyCard` (D1). Si más adelante
  alguien intenta moverla por card, el test de query-key fija el `queryClient` y se ve rojo.

- **R2 — Catálogo de literales canónicos que se filtra al cliente.** El backend los emite sin
  prosa por una razón documentada en `cleaning-stall-blocks-next-stay` R2.2; el cliente los pinta
  como vienen. La mitigación contra el catálogo paralelo es D6 (literal canónico, color del
  mapping existente) más un test de `BlockedTransitionsSection` que verifique que ningún string
  traducido se renderiza para `trigger`/`blocking_state`.

- **R3 — Stale cache tras cancelar.** Una cancelación cambia la card (estado operacional +
  `cleaningStatus`) y los stalls, pero la cache de TanStack no se invalida sola. D5 fija la
  invalidación por prefijo en `onSettled` (también en error, R3.3): un 409 deja el aviso en
  pantalla pero refresca el cubo de stalls.

- **R4 — Botón que devuelve 403.** R2.4 lo prohíbe. D4 cierra la fuente del permiso en el espejo,
  con tests que afirman que `TENANT_OWNER` no tiene `MANAGE_CLEANING_TASKS` ni `EXECUTE_INCIDENTS`
  — exactamente lo que `backend/app/auth/domain/policy.py:286` declara. El test del componente
  afirma que el botón no aparece cuando el hook devuelve `false`.

- **R5 — Race entre mutación y refresh.** D5 invalida en `onSettled`, no `onSuccess`: si el
  backend rechaza la mutación, los stalls también se re-leen (puede que ya no exista la entrada
  porque otra persona lo arregló). Una mutación concurrente que sí tuvo éxito no provocará
  doble-pintura porque la query se resuelve y el `byPropertyId` se recalcula en cada render.

- **R6 — `openIncidentsCount` queda desfasado tras resolver.** El cubo de la card se actualiza al
  invalidar `dashboardKeys.cards(tenantId)` (D5). Misma query key, mismo `queryFn`, sin parche
  optimista.

- **R7 — Catálogo de i18n divergente entre ES y EN.** El `catalog-parity.test.ts:88` recorre
  `NAMESPACES` y exige paridad de claves — añade las claves nuevas en ambos ficheros a la vez y
  deja que el gate `npm test` se ponga rojo si una se queda atrás. Sin excepción nombrada.

## Open questions

### OQ1 — Camino del id: **A — Extender `BlockedTransitionResponse`** (aprobado en gate 2026-08-24)

Un change backend dedicado precede a este y añade a `BlockedTransitionResponse` dos campos
opcionales, `cleaning_task_id` y `incident_id`, con sus respectivas pruebas de aislamiento por
tenant (regla 1 de `steering/security.md`). Hasta que ese PR esté mergeado en `main`, este
change **no puede invocar las mutaciones**: `useCancelCleaningTask({ taskId })` y
`useResolveIncident({ incidentId })` quedan tipados contra campos que la respuesta aún no trae,
así que un test de D5 (`actionMapFor`) con una respuesta real se quedará rojo y se pone verde
sólo cuando el id exista en el contrato generado.

Si el PR backend no llega antes de `/sdd:tasks`, el flujo de tareas se parte: las tareas que no
tocan la mutación (D2, D3, D4, D6, D8, D9, la sección informativa de la card) se aprueban y
se ejecutan; las dos mutaciones se quedan en `BLOCKED.md` hasta que el id aterrice, con su
comando exacto de reanudación (`/sdd:tasks blocked-transitions-web`).

### OQ2 — Motivo de cancelación: **A — Modal accesible** (aprobado en gate 2026-08-24)

El modal es el de D7: `<dialog>` con foco automático, `<textarea>` de hasta 500 caracteres con
contador visible, `aria-describedby` entre label e input. La tarea 9.x de `/sdd:tasks` confirma
con el operador si el motivo es texto libre o un selector corto — el modal lleva texto libre
mientras tanto, sin cambio de tipo.

### OQ3 — `final_cost` en resolución: **A — Pedir en modal** (aprobado en gate 2026-08-24)

El modal pide `final_cost` como decimal positivo con validación cliente y `422` localizado si
el backend lo rechaza. La tarea 9.y de `/sdd:tasks` confirma con el operador el formato exacto
(decimales permitidos, separador) — el input es `<input type="number" inputMode="decimal" min="0"
step="0.01">` mientras tanto, sin cambio de tipo.