# Design: incidents-web

## Context

El frontend ya tiene la ruta `/incidents` registrada en el shell (`route-registry.ts:155-167`), con su `href`, su `navigationGroup: "work"`, su `order: 3` y sus claves i18n en `locales/{es,en}/navigation.json` (`routes.incidents.title`/`.description`), pero la página renderiza `RoutePlaceholder routeId="incidents"`. El cliente HTTP tipado del frontend ya conoce los once endpoints de `/api/v1/incidents` (`openapi.d.ts:310-377`); no hay que regenerar nada ni negociar contrato. La sesión autenticada viene de `frontend-auth-session` archivado, y la frontera de paginación `{items, total, page, per_page}` de `IncidentPageResponse` (`openapi.d.ts:1709-1715`) es **distinta** de la del dashboard (`{data, page, per_page, total, total_pages}`) — vale la pena nombrarlo en D3.

El backend ya tiene `maintenance` archivado (2026-08-15), y la spec del backend (`specs/maintenance.md`) fija el contrato que este change consume tal cual, sin renegociar formas. La sesión autenticada y el cliente tipado están al día.

## Decisions

### D1 — Sin seam `IncidentsDataSource`: el factory exporta directamente `HttpIncidentsSource`

**Chosen:** `frontend/features/incidents/data/index.ts` exporta `getIncidentsDataSource()` que devuelve un singleton `HttpIncidentsSource` (no una interfaz), construido contra el `ApiClient` autenticado, igual que el composition point de `reservations-web` (`features/reservations/data/index.ts:23-29`).

**Why:** El precedent de `reservations-web` D1 lo discute y descarta para este caso: *"aquí no hay mock previo que sustituir ni UI previa que respetar: se va directo a HTTP contra `lib/api`, sin la indirección `Mock*Source` que allí existía sólo porque la UI se adelantó al backend"*. Mantener la indirección cuando no hay mock que preservar solo añadiría una capa sin el problema que la justificaba. Las pruebas unitarias del source usan `vi.fn().mockResolvedValue(...)` contra `ApiClient`, igual que `http-reservations-source.test.ts`, sin necesidad de un mock por encima.

**Rejected:**
- *Interfaz `IncidentsDataSource` + `HttpIncidentsSource` + `MockIncidentsSource`* — es el patrón de `dashboard-web`, pero no hay UI preexistente que dependa de la interfaz; añadirla solo mueve la frontera sin beneficiario.
- *Llamar `ApiClient.request` directamente desde los hooks* — pierde el composition point único (los tests del source son la única forma de fijar el contrato HTTP sin levantar la suite del navegador, y necesitan un `ApiClient` que poder mockear a nivel de método).

### D2 — Un único fichero de locale nuevo: `incidents.json`

**Chosen:** Crear `frontend/locales/{es,en}/incidents.json` con cinco secciones: `status` (nueve etiquetas de `IncidentStatus`), `severity` (cuatro de `IncidentSeverity`), `category` (trece de `IncidentCategory`), `source` (seis de `IncidentSource`) y `fields` (etiquetas de columnas y campos del detalle). Reutilizar `frontend/locales/{es,en}/states.json` para los textos comunes de carga/error/vacío que ya existen.

**Why:** Las cinco secciones son específicas de esta capacidad — no las reutiliza otra feature — y mezclarlas en `states.json` o en `dashboard.json` haría que un futuro cambio de etiquetas aquí obligara a tocar un fichero que también mira el resto del workspace. `dashboard.json` ya contiene `card.incidents` con un sentido distinto (es el contador de la card del dashboard, no las etiquetas del listado) y no es razonable ampliarlo. Los textos de carga/error/vacío **no** se duplican: `states.json` ya provee `loading.label`, `error.title`, `error.description`, `error.retry`, `empty.title`, `empty.description`, y eso es exactamente lo que R2.4 y R3 piden.

**Rejected:**
- *Reutilizar `dashboard.json`* — sus claves son del dashboard agregado (`propertyCode`, `operationalState`), no de la pantalla de incidencias. Mezclar dominios invita a renombrados al cruzar.
- *Un fichero por enumeración (`status.json`, `severity.json`, etc.)* — cuatro ficheros para una entrada `size: S` es ceremonia.
- *Un fichero por requisito (lista/detail/status/fields)* — cinco ficheros para una entrada `size: S` es ceremonia.

### D3 — DTOs `camelCase` con un mapper snake_case → camelCase, sin genérico de sobre

**Chosen:** Modelar `IncidentSummaryDto` y `IncidentDetailDto` (camelCase) como tipos UI, y mapear los responses de la API con funciones explícitas — un `mapIncidentSummary`, un `mapIncidentDetail` — siguiendo el precedent de `http-reservations-source.ts:6-80`. `IncidentPageResponse` (sobre `{items, total, page, per_page}`) se tipifica con el DTO de summary dentro; el DTO de detalle **no** se mete en el sobre, sólo en el método del source que devuelve un único objeto.

**Why:** El codebase ya estandariza dos cosas: (a) los DTOs UI son camelCase y el resto del frontend los consume así; (b) los mappers son funciones nombradas en `http-*-source.ts` y no `pick`/`omit` dinámicos. El **sobre** del backend es deliberadamente distinto al del dashboard: `IncidentPageResponse` lleva `items` (no `data`) y devuelve `per_page`/`page`/`total` sin `total_pages`. Reutilizar el genérico `PaginatedResponse<T>` del dashboard es **mentira estructural**: habría que cambiar el nombre del campo (`items` vs `data`) en la frontera, y el mapper se vuelve menos trazable. Mejor un tipo local `IncidentList` que coincida con la forma del backend y un segundo tipo `IncidentSummary` que se entienda solo.

**Rejected:**
- *Devolver directamente los tipos `components["schemas"][...]`* — pierde la frontera de snake_case→camelCase; los componentes quedarían filtrándose capa a capa hasta los componentes de presentación, y un cambio de nombre del backend rompería la UI sin que `tsc` se enterara.
- *Un `PaginatedResponse<T>` genérico reutilizado del dashboard* — el sobre es distinto (`items` vs `data`, sin `total_pages`); mezclar el genérico es adaptar la fuente al consumidor equivocado.
- *Un mapper único para summary y detail* — los campos no coinciden: `IncidentResponse` tiene 22 campos, `IncidentSummary` tendría unos 12. Forzar un mapper único obliga a `pick` dinámicos o a sobre-tipar.

### D4 — Filtros v1: `status` (enum tipado), `severity` (enum tipado), sin `property_id`; la query key recibe el objeto de filtros normalizado

**Chosen:** La query del hook `useIncidents` admite en v1 `{ status?: IncidentStatus; severity?: IncidentSeverity; page?: number; perPage?: number }` en camelCase UI. **`propertyId` no se expone en v1**: añadir ese filtro exigiría un selector de propiedad (cuyas propiedades hay que listar desde `/api/v1/properties`, lo que o vuelve a la entrada `M`/`L` por el selector, o pide al usuario pegar un UUID a mano, que no es UI). El endpoint del backend sigue aceptando `property_id` —sólo no se le envía desde esta pantalla—. `IncidentStatus` e `IncidentSeverity` se mantienen como enums del `openapi.d.ts`, de modo que un valor no enumerado falle en `tsc` antes de llegar a runtime.

La query key del listado se construye como `incidentsKeys.list(tenantId, filters)` pasando el **objeto de filtros normalizado directamente** como último segmento (precedent: `reservationsKeys.list(tenantId, filters)` en `frontend/features/reservations/hooks/query-keys.ts:18-19` — recibe el objeto entero, no un `JSON.stringify`). El objeto se construye una sola vez por render con sus claves en un orden estable, así dos renders con los mismos filtros producen la misma key y TanStack Query no invalida.

**Why:** La razón para no exponer `property_id` en v1 no es técnica (el endpoint lo acepta), es de scope: el selector de propiedad abre un combo/async que duplica `usePropertiesList`, y eso vuelve a entrar en la decisión de «esta entrada es `size: S`». Cuando llegue el momento, una entrada propia con su design lo añade — el precedent de `reservations-web` D4 dejó la puerta abierta exactamente para esto. La query key como objeto directo evita dos trampas: (a) `JSON.stringify` no es estable frente al orden de claves de un objeto literal TS, así que dos renders con `filters` equivalentes pero construidos en orden distinto generarían keys distintas y duplicarían cache; (b) un comparador a mano duplica la lógica de igualdad que TanStack Query ya hace con `deepEqual` sobre la parte serializada. El `tenantScopedKey` del shell (`lib/query/query-keys.ts`) ya aísla la cache por tenant, así que el último segmento puede ser el objeto entero sin riesgo cross-tenant.

**Rejected:**
- *Aceptar `status: string` libre* — pierde el guard de tipos del proposal R2.6 y abre la puerta a que un estado renombrado rompa en runtime.
- *Exponer `propertyId` en v1 con un selector* — multiplica la entrada por 2-3: fetch de propiedades, estado del selector, deep-linking de la selección. Rompe `size: S`.
- *Pedir al usuario pegar un UUID a mano* — no es UI; es depuración.
- *`JSON.stringify(filters)` para la query key* — `JSON.stringify({a:1,b:2}) !== JSON.stringify({b:2,a:1})` en algunas plataformas, y los filters se construyen desde varios sitios (URL, estado, defaults) donde el orden de claves puede divergir.

### D5 — Columnas mínimas de la lista; el resto va al detalle

**Chosen:** La tabla de `/incidents` muestra, y solo estas, en este orden: **severidad** (etiqueta localizada con color semántico), **estado** (etiqueta localizada del enum, R4), **título** (los primeros 60 caracteres), **propiedad** (mostrando la `propertyId` como referencia identificable, sin nombre —el endpoint de lista no devuelve nombre de propiedad, sólo el id—), **categoría** (etiqueta localizada), **fuente** (etiqueta localizada), **creada** (`createdAt` en formato YYYY-MM-DD HH:mm). El resto de campos del detalle —`description`, `ai_summary`, `assigned_technician_id`, `reservation_id`, `owner_approval_required`, `estimated_cost`, `approved_cost`, `final_cost`, `resolved_at`, `updated_at`— se reservan al detalle y **no** se renderizan en la tabla, ni como columna secundaria ni como expansión de fila.

**Why:** El endpoint de lista no devuelve nombre de propiedad; pintar la `propertyId` en la columna «propiedad» es la única información que la lista tiene, y fingir un nombre con un fetch extra por incidencia vuelve a la entrada `M`. La densidad de la tabla es lo que la hace útil en una pantalla de operaciones: si la tabla replica el detalle deja de ser tabla. El `description` es texto libre del huésped o de la limpiadora (regla 11 de `steering/security.md`, `incidents.title`/`description`); pintarlo en una tabla de operaciones abre dos preguntas — ancho (muchos caracteres) y exposición (todos los lectores ven lo que escribió un tercero)— que la densidad no cierra. En el detalle va con su wrapper de texto plano, fuera del ojo de tabla.

**Rejected:**
- *Mostrar las 22 columnas de `IncidentResponse`* — la lista deja de ser lista, se vuelve un detalle horizontal.
- *Hacer fetch de la propiedad por cada fila para sacar el nombre* — convierte la pantalla `size: S` en una que no entra en el change, y mete latencia de N peticiones por carga.
- *Expandir la fila al click para mostrar campos extra* — duplica la ruta `/incidents/[id]` sin ganar nada que el detalle no dé ya; el comportamiento canónico es navegar al detalle, que es deep-linkable.
- *Pintar `description` en la tabla* — texto libre de tercero en una celda de tabla, dense layout problem y riesgo de exposición.

### D6 — Ruta de detalle sin `href` ni `navigationGroup`, simétrica con `property-detail` y `reservation-detail`

**Chosen:** Añadir el descriptor de `incident-detail` en `route-registry.ts` con `pattern: "/incidents/[id]"`, `match: "exact"`, **sin** `href` y **sin** `navigationGroup` — replicando `property-detail` (`route-registry.ts:114-122`) y `reservation-detail` (`route-registry.ts:137-145`). Las claves `routes.incident-detail.{title,description}` se crean en los dos locales, y la lista `PRD_24_SURFACES` de `route-registry.test.ts` se **extiende** con `/incidents/[id]`, igual que ya contiene `/properties/[id]` y `/reservations/[id]`: la lista es de **superficies de navegación** con id, y la asimetría de excluir el hijo parametrizado sería una sorpresa para el siguiente descriptor detail.

**Why:** Replicar los dos precedents evita tres regresiones a la vez (las suites de `route-registry`, `route-metadata` y `breadcrumbs` cubren el contrato, y un descriptor mal formado las pone en rojo). El test "covers exactly the PRD §24 surfaces" compara `routeRegistry.map(r => r.pattern).sort()` con la lista, así que si el descriptor entra al registro y la lista no se actualiza, el test falla en rojo por construcción — no hay forma de saltarse la cobertura. Incluir el id en la lista mantiene la simetría con `properties/[id]` y `reservations/[id]`, que ya lo tienen, y deja al siguiente detail route con un precedent claro.

**Rejected:**
- *Dejar `PRD_24_SURFACES` sin `/incidents/[id]`* — el test "covers exactly..." fallaría en rojo; el precedent de los otros dos detail routes es la postura simétrica.
- *Poner `navigationGroup` y `href` en la ruta de detalle* — la haría aparecer en la barra lateral, que no es lo que la spec pide ni lo que `property-detail`/`reservation-detail` hacen.

### D7 — `description` se renderiza una sola vez y como texto plano

**Chosen:** El detalle muestra `description` como un bloque de texto plano (`{value}` directo, sin `dangerouslySetInnerHTML`, sin `react-markdown`, sin `parseHtml`), con `whitespace-pre-wrap` para respetar saltos de línea del reporte y `max-w-prose` para limitar ancho en desktop. El bloque lleva una etiqueta accesible (`aria-label` localizado) y nunca se pinta dentro de la lista.

**Why:** `incidents.title` y `incidents.description` son sumideros de la regla 11 de `steering/security.md` —texto libre de tercero (huésped o limpiadora) que puede contener PII involuntaria, un `<script>` accidental, o nombres de personas que la manager no quiere leer en una tabla—. El precedent de `reservations-web` R3.3 lo fija para `internal_notes` y `special_requests`; este change lo aplica al mismo género de columna. Renderizarlo en la lista multiplica la superficie de exposición; renderizarlo en el detalle, en un bloque etiquetado y con ancho acotado, lo mantiene visible para quien necesita leer la incidencia pero no lo arrastra a la pantalla de operaciones.

**Rejected:**
- *Renderizar con un markdown seguro* — el precedente de `reservations-web` no lo hace y `domain-foundation-ops` no pidió markdown aquí; añadirlo es ampliar el contrato del campo sin un requisito del PRD.
- *Truncar `description` en la lista* — confunde la densidad (ocupa el doble de altura) y rompe la coherencia del flujo tabla→detalle.
- *Pintar `description` como `whitespace-pre-wrap` sin `max-w-prose`* — un reporte de 1000 caracteres ocupa toda la pantalla en desktop; el ancho acotado es lo que mantiene legible el bloque.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Shell | `frontend/features/shell/navigation/route-registry.ts` | Add `incident-detail` descriptor. |
| Locales (nav) | `frontend/locales/{es,en}/navigation.json` | Add `routes.incident-detail.{title,description}`. |
| Locales (feature) | `frontend/locales/{es,en}/incidents.json` | New file: `status` (9 keys) + `severity` (4 keys) + `category` (13 keys) + `source` (6 keys) + `fields` (column/detail labels). |
| Locales (registry) | `frontend/lib/i18n/resources.ts` | Register `esIncidents` / `enIncidents` namespaces. |
| Data | `frontend/features/incidents/data/index.ts` | New: composition point exporting `getIncidentsDataSource()`. |
| Data | `frontend/features/incidents/data/dto.ts` | New: `IncidentSummaryDto`, `IncidentDetailDto`, `IncidentList`, `IncidentStatus` / `IncidentSeverity` / `IncidentCategory` / `IncidentSource` (re-exports from openapi), `IncidentFilters`. |
| Data | `frontend/features/incidents/data/http/http-incidents-source.ts` | New: `HttpIncidentsSource` with `listIncidents` and `getIncident`, plus `mapIncidentSummary` and `mapIncidentDetail`. |
| Data | `frontend/features/incidents/data/http/http-incidents-source.test.ts` | New: unit tests for the two methods (mappers + paths + query params). |
| Lib | `frontend/features/incidents/lib/error-mapping.ts` | New: `mapIncidentsError<TData>` (discriminated union: `loading` / `forbidden` / `not-found` / `validation` / `error` / `ok`), precedent: `reservations/lib/error-mapping.ts`. |
| Hooks | `frontend/features/incidents/hooks/query-keys.ts` | New: `incidentsKeys` (list, detail) using `tenantScopedKey`. |
| Hooks | `frontend/features/incidents/hooks/use-incidents.ts` | New: `useIncidents(filters)` and `useIncident(id)` with `retry: retryPolicy` reused from `@/lib/api/retry-policy`. |
| Hooks | `frontend/features/incidents/hooks/use-incidents.test.tsx` | New: hook tests against a mocked `HttpIncidentsSource`. |
| Components | `frontend/features/incidents/components/list/incidents-view.tsx` | New: client view that consumes `useIncidents`, renders tabla con paginación y estado vacío/error. |
| Components | `frontend/features/incidents/components/list/incidents-view.test.tsx` | New: render tests (loading / loaded / empty / error). |
| Components | `frontend/features/incidents/components/list/incidents-filters.tsx` | New: filtros (`status`, `severity`) con control tipado. Sin `propertyId` en v1 (D4). |
| Components | `frontend/features/incidents/components/list/incidents-filters.test.tsx` | New: tests del comportamiento del filtro. |
| Components | `frontend/features/incidents/components/detail/incident-detail-view.tsx` | New: client view que consume `useIncident(id)`, renderiza todos los campos y trata `description` como texto plano (D7). |
| Components | `frontend/features/incidents/components/detail/incident-detail-view.test.tsx` | New: tests (loading / loaded / not-found / error / description as plain text). |
| Components | `frontend/features/incidents/components/detail/incident-detail-sections.tsx` | New: bloques reutilizables del detalle (cabecera, identifica, costes, descripción). |
| Components | `frontend/features/incidents/index.ts` | New: barrel export. |
| Pages | `frontend/app/(workspace)/incidents/page.tsx` | Replace placeholder with the list view. |
| Pages | `frontend/app/(workspace)/incidents/[id]/page.tsx` | New: detail page that calls `routeMetadata('incident-detail')` and renders `<IncidentDetailView incidentId={id} />`. |
| Tests | `frontend/features/shell/navigation/route-registry.test.ts` | Extend `PRD_24_SURFACES` with `/incidents/[id]` (D6). |

## Data & interfaces

**Sin cambios de schema, sin migraciones, sin variables de entorno.** Todo el contrato ya existe en `backend/openapi.json:9841-10974` y está tipado en `frontend/lib/api/generated/openapi.d.ts:1705-1836`.

**API consumida (read-only, ya tipada):**
- `GET /api/v1/incidents?page&per_page&property_id&status&severity` → `IncidentPageResponse` (sobre `{items, total, page, per_page}`, `IncidentResponse[]` dentro).
- `GET /api/v1/incidents/{incident_id}` → `IncidentResponse`.

**Enums que el FE localiza (de `openapi.d.ts:1705-1825`):**
- `IncidentStatus` (9): `OPEN`, `CLASSIFIED`, `AWAITING_OWNER_APPROVAL`, `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`, `RESOLVED`, `CANCELLED`.
- `IncidentSeverity` (4): `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `IncidentCategory` (13): `ACCESS`, `LOCK`, `WIFI`, `ELECTRICITY`, `WATER`, `PLUMBING`, `HVAC`, `APPLIANCE`, `NOISE`, `CLEANING`, `DAMAGE`, `SAFETY`, `OTHER`.
- `IncidentSource` (6): `GUEST`, `CLEANER`, `OWNER`, `SYSTEM`, `PMS`, `LOCK_ALERT`.

**DTOs UI (camelCase, exportados desde `features/incidents/data/dto.ts`):**
- `IncidentStatus` / `IncidentSeverity` / `IncidentCategory` / `IncidentSource` — re-exports de `openapi.d.ts`.
- `IncidentSummaryDto` — `{ id, propertyId, status, severity, category, source, title, createdAt }` (subset del detalle para la tabla; el detalle carga el resto).
- `IncidentDetailDto` — extiende summary con `description`, `aiSummary`, `reservationId`, `assignedTechnicianId`, `ownerApprovalRequired`, `estimatedCost`, `approvedCost`, `finalCost`, `resolvedAt`, `updatedAt`.
- `IncidentList` — `{ items: IncidentSummaryDto[]; total: number; page: number; perPage: number }` (sobre del backend, renombrado a camelCase en la frontera).
- `IncidentFilters` — `{ status?: IncidentStatus; severity?: IncidentSeverity; page?: number; perPage?: number }` (v1, sin `propertyId` por D4).

**Errores relevantes** (de `lib/api/errors.ts`): `ApiError` con `status` 401, 403, 404, 422, 5xx. Mapeo a UI ya está en R3.4 y R5.4 (discriminated union vía `mapIncidentsError`).

## Risks & mitigations

- **Riesgo: la PII del huésped o de la limpiadora en `description` se filtra a un log o a un componente que no la espera.** Mitigación: el mapper `mapIncidentDetail` enumera los campos explícitamente — un `IncidentResponse` que mañana gane un campo no se filtra automáticamente. El block de tests del mapper fija el sobre de salida.
- **Riesgo: la pantalla de detalle intenta mostrar `description` como HTML por accidente.** Mitigación: el componente `IncidentDetailSections` lo pinta con `whitespace-pre-wrap` y `{value}` (texto plano), nunca `dangerouslySetInnerHTML`. Los tests del componente verifican que el valor se renderiza como texto aunque contenga `<script>`, `\n` y PII.
- **Riesgo: la query key del listado no incluye los filtros, así que cambiar de página en la misma vista reusa la respuesta cacheada de otra página.** Mitigación: `incidentsKeys.list(tenantId, filters)` recibe el **objeto de filtros normalizado** directamente como parte de la key (D4; precedent: `reservationsKeys.list(tenantId, filters)` en `query-keys.ts:18-19`). El objeto se construye con sus claves en orden estable, no se serializa con `JSON.stringify`.
- **Riesgo: `status` o `severity` enviados como string libre pasan el typecheck pero la API devuelve 422.** Mitigación parcial por R2.6 (tipo `IncidentStatus`/`IncidentSeverity`); el resto se cubre con el test de mapper, que verifica que un valor enumerado se serializa al nombre exacto del enum del backend.
- **Riesgo: el `ApiError 404` del detalle entra por la rama genérica de error y oculta la distinción que pide R3.4.** Mitigación: `mapIncidentsError` distingue `404` por `instanceof ApiError && status === 404`; un test cubre el caso. La pantalla de detalle muestra "Incidencia no encontrada" localizado, distinto del error genérico.
- **Riesgo: regenerar `openapi.d.ts` en otro change futuro introduce un campo nuevo en `IncidentResponse` que no aparece en el mapper.** Mitigación: el mapper enumera campos explícitamente (D3), así que un campo nuevo es invisible al UI hasta que se mapee — exactamente el comportamiento que el precedent de `reservations-web` D3 y `properties-crud` demostró necesario. No es un riesgo nuevo ni específico de este change.
- **Riesgo: la pantalla muestra `assigned_technician_id` como un UUID pelado, que no identifica al técnico.** Mitigación: el detalle muestra el UUID con un tooltip localizado ("ID del técnico asignado"), botón "Copiar" para pegarlo en otra búsqueda. La resolución nombre↔UUID exigiría un `GET /api/v1/users` (no en `size: S`), y queda fuera de scope. Misma lógica que `reservations-web` deja el `propertyId` sin nombre en la lista.
- **Riesgo: la segunda puerta de aprobación (`final_cost` por encima del umbral) y `AWAITING_OWNER_APPROVAL` quedan como bloques informativos en el detalle, sin acción.** Mitigación: el detalle renderiza `owner_approval_required: true` con un bloque destacado y `status: "AWAITING_OWNER_APPROVAL"` con etiqueta localizada, pero **no** expone botones de respuesta. La aprobación (`POST /api/v1/owner-approvals/{id}/respond`) vive en la ruta `/approvals` (que sigue como `RoutePlaceholder`) y se cubre en una entrada propia.
- **Riesgo: `WORKTREE_PARALLEL_STACK` host-port collision (regla 1 de `sdd/steering/infra.md` no, esto es de `sdd/project.md` §Worktree bootstrap)**: este change no toca infra, pero el dev stack local puede chocarse al levantar la suite en el worktree. Mitigación: el shell `make up` ya levanta la suite del FE vía `npm test` con Vitest en el propio contenedor, sin necesidad de API real. Ver `frontend-foundation.md` §Testing: se verifica «type-check, lint, tests, and a production build without depending on a backend or fictitious business data».

## Open questions

*(Resueltas durante el gate de design, **2026-08-20**:*

- *Sobre del backend `IncidentPageResponse` vs `PaginatedResponse<T>` del dashboard → sobre local `IncidentList` con DTOs propios, D3. Sin genérico reutilizado.*
- *Enumeraciones a localizar → las 13 de `IncidentCategory`, las 6 de `IncidentSource`, las 4 de `IncidentSeverity` y las 9 de `IncidentStatus`: la lista la fija `openapi.d.ts`, no la spec de `maintenance.md`. D2 y el listado en §Data & interfaces.*
- *Exposición de `property_id` en v1 → no se expone, queda para una entrada propia con su design, D4. Misma forma que `reservations-web` D4*.
- *Renderizado de `description` → un único bloque en el detalle, texto plano, D7. Nunca en la lista.*
- *Acciones del manager (triage, classify, assign, …) → fuera de scope y fuera de la pantalla, R5 del proposal. La UI no expone botones de acción.*

*No queda ninguna abierta para `tasks.md`: la entrada puede pasar a tareas sin más gates.)*
