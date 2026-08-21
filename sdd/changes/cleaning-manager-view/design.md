# Design: cleaning-manager-view

## Context

`/cleaning` es hoy `app/(workspace)/cleaning/page.tsx` renderizando `RoutePlaceholder`. La única
superficie funcional comparable del workspace es el dashboard: `frontend/features/dashboard/`
establece el patrón completo —`data/dto.ts` (DTOs de presentación), `data/<x>-source.ts`
(interfaz), `data/http/http-dashboard-source.ts` (implementación sobre `lib/api`),
`data/index.ts` (punto de composición), `hooks/query-keys.ts` + `hooks/use-dashboard-data.ts`
(TanStack Query con clave `tenantScopedKey`), `lib/` (mapeos puros) y `components/`— y
`features/guest-portal/hooks/use-checkin.ts` establece el de mutación (`useMutation`,
`retry: false`).

El backend está entero y no se toca. Los cuatro endpoints y sus formas están en
`frontend/lib/api/generated/openapi.d.ts`: `GET /api/v1/cleaning-tasks`
(`page`/`per_page`/`property_id`/`status` → `CleaningTaskPageResponse`), `PATCH
/api/v1/cleaning-tasks/{task_id}` (`AssignCleaningTaskRequest` = solo `assigned_cleaner_id` →
`CleaningTaskResponse`), `GET /api/v1/users` (`role`/`status`) y `GET /api/v1/properties`.
`CleaningTaskResponse` trae `property_id` y `assigned_cleaner_id` como UUID desnudos: los
nombres hay que resolverlos en el cliente. El orden lo fija
`backend/app/cleaning/infrastructure/repositories.py::_ordered_tasks` — `created_at` descendente
con `id` de desempate—, y `per_page` está topado a **100** en los tres listados
(`MAX_PER_PAGE` en `cleaning/`, `properties/` y `auth/domain/repositories.py`).

El mapa rol→permiso vive en `backend/app/auth/domain/policy.py`: `TENANT_OWNER` tiene
`READ_CLEANING_TASKS`, `READ_PROPERTIES` y `READ_USERS` (vía `_USER_MANAGE`) pero **no**
`MANAGE_CLEANING_TASKS`; `PROPERTY_MANAGER` tiene los cuatro. En el frontend **no existe hoy
ninguna noción de permiso**: `CurrentUserResponse` solo trae `role`, y ningún componente lo
mira.

## Decisions

### D1 — Feature nueva `frontend/features/cleaning/`, con el layering del dashboard y sin mock

**Chosen:** módulo propio `features/cleaning/` con `data/` (dto + interfaz + `http/` + punto de
composición), `hooks/`, `lib/`, `components/` y `state/`, copiando la estructura de
`features/dashboard/`. **Sin `data/mock/`**: el backend existe desde el change `cleaning`, así
que no hay nada que suplantar. Se mantiene la interfaz + punto de composición aunque no haya
segunda implementación, porque es lo que permite que los tests de componentes inyecten un doble
sin tocar `lib/api`.

Rejected: colgarlo de `features/dashboard/` — es otra capability y otro dominio de backend;
`dashboard-api` es de solo lectura y agregado, esto es operación sobre `cleaning`.
Rejected: `fetch` ad-hoc en la página — rompe la convención de frontera que el repo ya prueba
(`features/dashboard/data/boundary.test.ts`) y deja el contrato repetido en el componente.
Rejected: replicar `data/mock/` y su test de frontera — protege un swap que aquí no existe;
un test que vigila una regla vacía es ruido.

### D2 — Tres consultas independientes, ninguna composición en backend y ninguna por fila

**Chosen:** `useCleaningTasks(filters, page)` (la lista, con sus parámetros en la petición),
`useCleanerDirectory()` y `usePropertyDirectory()` (los dos catálogos). Las tres son
`useQuery` con clave `tenantScopedKey`, así que TanStack Query las cachea y las comparte entre
filas y entre cambios de página: los catálogos **no** se vuelven a pedir al paginar ni al
filtrar (R2.5).

Rejected: ampliar `CleaningTaskResponse` con nombres desnormalizados — es cambio de backend,
explícitamente fuera de alcance en el proposal.
Rejected: resolver cada fila con su `GET /users/{id}` / `GET /properties/{id}` — N+1 por
página, prohibido por R2.5.

### D3 — Los catálogos se piden en **una** página de `per_page=100` y se indexan en un `Map`

**Chosen:** `getCleaners()` y `getProperties()` piden `page=1&per_page=100` y el mapper
construye `Map<id, {name, internalCode}>`. Un id que no esté en el mapa cae en el indicador
degradado de R2.4. `per_page` está topado a 100 en el backend, así que "todo el catálogo" no es
una petición sino un bucle; con la escala del MVP (2 viviendas, un puñado de limpiadoras) ese
bucle nunca daría una segunda vuelta.

`ASSUMPTION` a declarar en el código: **un tenant con más de 100 propiedades o más de 100
limpiadoras verá identidades no disponibles a partir de la centésima**. No es un fallo silencioso
— es exactamente la degradación que R2.4 especifica, con el mismo indicador— pero deja de ser
correcto como cobertura y hay que rehacerlo antes de la fase SaaS.

Rejected: paginar hasta agotar `total_pages` — complejidad y ráfaga de peticiones por un caso
que no existe, y aun así haría falta R2.4 para la limpiadora desactivada.
Rejected: pedir el catálogo filtrado por los ids de la página visible — el endpoint no acepta
ese filtro, y hacerlo por fila es lo que D2 rechaza.

### D4 — Un solo catálogo de limpiadoras (`role=CLEANER`, sin filtro de estado) sirve para los dos usos

**Chosen:** una única consulta `GET /api/v1/users?role=CLEANER&per_page=100`, sin `status`. De
ella salen (a) la resolución de nombre de `assigned_cleaner_id` en cualquier fila y (b) las
candidatas del control de asignación, filtrando `status === "ACTIVE"` en el cliente.

El motivo de no mandar `status=ACTIVE`: una tarea antigua puede estar asignada a una limpiadora
ya desactivada, y con el catálogo filtrado su nombre **sí lo tenemos** pero no lo encontraríamos
— convertiríamos un dato disponible en el indicador de "identidad no disponible" de R2.4, que
existe para lo contrario. R4.2 se cumple igual: el filtro cliente acota las candidatas, y el
backend lo vuelve a exigir (`AssignCleaningTaskUseCase` responde `422` si la persona no es
`CLEANER` **y** `ACTIVE`).

Rejected: dos consultas (directorio + candidatas) — mismos datos, doble tráfico, dos cachés que
pueden discrepar.
Rejected: solo `status=ACTIVE` — rompe R2.2 para las asignaciones históricas.

### D5 — Tres renderizados distintos de identidad: **sin asignar**, **resolviendo**, **no disponible**

**Chosen:** la celda de limpiadora (y la de propiedad) distingue tres casos, no dos:

| Situación | Render |
|---|---|
| `assigned_cleaner_id === null` | etiqueta traducida «Sin asignar» (R2.3) |
| catálogo en vuelo (`isPending`) | marcador neutro de carga, sin texto de identidad |
| catálogo resuelto o en error y el id no está en el `Map` | etiqueta traducida «Identidad no disponible» (R2.4) |

R2.3 exige que «sin asignar» sea distinguible de «no se ha podido cargar», y con dos estados el
intervalo en el que el catálogo aún no ha llegado se pinta como uno de los dos y miente. El
error del catálogo **no** propaga a `ErrorState`: la lista se renderiza igual (R2.4).

Rejected: bloquear la lista hasta que los tres queries resuelvan — R1.2/R1.3 atan los estados de
carga y error a la consulta de tareas, y una caída del catálogo dejaría la vista inservible
cuando la información que importa (estado, fechas) ya está.

### D6 — Filtros y página en un store de Zustand; el reset a página 1 vive en los setters

**Chosen:** `features/cleaning/state/use-cleaning-filters-store.ts` con `propertyId`, `status` y
`page`, siguiendo `features/dashboard/state/use-timeline-filters-store.ts` (frontend.md: Zustand
solo para estado ligero de UI). **`setPropertyId` y `setStatus` ponen `page: 1` dentro del
propio setter**, de modo que R3.4 es un invariante del store y no una cortesía que cada llamante
recuerda; se prueba sin renderizar nada. Los tres valores entran en la clave de query
(`tenantScopedKey(tenantId, "cleaning-tasks", {propertyId, status, page})`), así que cada
combinación se cachea aparte.

**El store recuerda además de qué tenant son sus filtros** (`tenantId` + `adoptTenant`, añadidos
en `/sdd:run`, sección 8, a partir de un hallazgo del panel de seguridad). El store es un
singleton de módulo: sobrevive a la vista y sobrevive a la sesión, así que un `propertyId` elegido
por una sesión se reenviaba en la **primera** petición de la siguiente —el identificador opaco de
un tenant viajando en la petición de otro (`steering/security.md` regla 1, lado frontend)—. No
hay fuga de datos, porque el backend acota por tenant y las claves de query llevan `tenantId`,
pero el identificador no debe viajar.

Vive en el store por la misma razón que el reset a página 1: es un invariante de los filtros, no
una cortesía del llamante. Y **tenía** que vivir ahí: un `useRef` en `CleaningView` no lo detecta,
porque cerrar sesión desmonta la vista y el ref se reinicia con el tenant nuevo. `CleaningView`
sólo declara quién mira; además calcula `staleFilters` **durante el render**, porque un efecto
corre después de que la primera petición haya salido ya con el filtro viejo.

`tenantId` aquí es una **etiqueta de propiedad** copiada de `useAuth()`, no server state
duplicado, así que no choca con «No duplicar server state en stores».

Rejected: estado en la URL (`useSearchParams`) — mejor para compartir y para el botón atrás,
pero no hay precedente en el repo, obliga a un límite de Suspense en App Router y decide por el
producto algo que nadie ha pedido. Ver **OQ1**.
Rejected: `useState` en el componente — el mismo estado lo leen la barra de filtros, la
paginación y el hook; subirlo a un store evita pasarlo por props a tres niveles.

### D7 — `lib/auth/permissions.ts`: mapa rol→permiso **parcial y declarado como tal**

**Chosen:** módulo nuevo `frontend/lib/auth/permissions.ts` con un `Record<UserRole,
readonly Permission[]>` que declara **solo los permisos que el frontend usa para ocultar algo**
—hoy `MANAGE_CLEANING_TASKS` y nada más— y un hook `useHasPermission(permission)` que lo lee del
`role` de `useAuth()`. El módulo documenta en su cabecera que es una **pista de UX**: la
autoridad es el backend (`steering/frontend.md`: «RBAC del backend decide, el frontend solo
oculta»; `steering/security.md` regla 2), y por eso R4.4 exige que un `403` nunca se lea como
éxito.

Parcial a propósito: un espejo que se declara completo de `ROLE_PERMISSIONS` envejece en
silencio en cuanto el backend añade un permiso. Uno que dice qué cubre solo miente sobre lo que
enumera.

Rejected: `user.role === "PROPERTY_MANAGER"` en el componente — reparte literales de rol por la
UI y obliga a repetir la decisión en cada superficie nueva.
Rejected: añadir `permissions: string[]` a `CurrentUserResponse` — es la solución buena a medio
plazo y elimina el espejo entero, pero es cambio de backend y el proposal lo deja fuera. Ver
**OQ3**.

### D8 — Control de asignación: `<select>` nativo de candidatas + botón de confirmación explícito, por fila

**Chosen:** en cada fila, cuando `useHasPermission("MANAGE_CLEANING_TASKS")`, un `<select>` con
las candidatas de D4 y un botón que dispara la mutación. `<select>` nativo es lo que ya usa
`features/dashboard/components/detail/property-timeline.tsx`, no hay primitivo `Select` en
`components/ui/`, y trae teclado y rueda nativa de móvil gratis (R5.3).

El botón separado no es adorno: R4.1 habla de **confirmar**, y en un `<select>` navegado con
flechas el evento `change` se dispara en cada opción por la que pasas — autosubmit reasignaría
tareas a quien solo estaba mirando la lista.

**La identidad de D5 se pinta siempre, y el control se añade debajo — no la sustituye**
(corregido en `/sdd:run`, sección 8, a partir de un test propio y confirmado por el panel de
arquitectura). Una primera redacción de esta decisión decía «sin permiso, la misma celda es texto
de solo lectura», que se lee como un XOR: control **o** texto. Implementado así, la manager —la
única que ve el control— se quedaba sin poder leer **a quién está asignada la tarea ahora**, que
es justo lo que R2.2 le garantiza y lo que necesita para decidir a quién la mueve. Y peor: al
rechazar el backend una asignación, no quedaba en la celda ninguna afirmación verdadera que
sostuviera R4.4.

Así que las dos cosas conviven y son independientes: **el render de identidad de D5 va primero y
para todos los roles** —es la única afirmación de la fila sobre lo que el backend tiene por
bueno—, y el control, cuando lo hay, sólo **propone**. R4.3 se cumple igual: sin
`MANAGE_CLEANING_TASKS` no hay control y la celda es exactamente ese texto y nada más.

Consecuencia asumida: tras un fallo, el desplegable conserva la elección de la manager para que
pueda reintentar, mientras el texto sigue diciendo lo del servidor. Lo que R4.4 prohíbe es que la
fila **afirme** la asignación rechazada, y no lo hace.

Rejected: diálogo modal por fila — necesita un primitivo nuevo y tres pulsaciones para la acción
más frecuente de la vista.
Rejected: autosubmit en `change` — escritura accidental por teclado, descrito arriba.

### D9 — La mutación **invalida**; nunca escribe la caché de forma optimista

**Chosen:** `useAssignCleaningTask()` = `useMutation` con `retry: false` (igual que
`features/guest-portal/hooks/use-checkin.ts`) y, en `onSettled`, `invalidateQueries` sobre el
prefijo `['tenant', tenantId, 'cleaning-tasks']`. En éxito y en fallo — porque R4.5 pide
refrescar tras `404`/`409` para no dejar en pantalla una asignación que el servidor no aceptó.

Invalidar y no parchear es lo que hace posible R4.4/R4.5 sin trabajo extra: no hay ningún
instante en el que la fila muestre una asignación que el backend no confirmó. Además, la tarea
puede **salir del filtro activo** al asignarse (`CREATED` → `ASSIGNED` con el filtro en
`CREATED`), y solo una recarga de la página descrita por los parámetros actuales lo refleja
bien; la respuesta del `PATCH` es una tarea suelta y no sabe nada de la página.

Rejected: actualización optimista con rollback — más código, y el modo de fallo que introduce
(fila que muestra el resultado antes de que el servidor lo acepte) es justo el que R4.4 prohíbe.
Rejected: escribir a mano la `CleaningTaskResponse` devuelta en la caché — no resuelve la
salida de filtro ni `total`/`total_pages`.

### D10 — El texto de error se elige por `status` HTTP, nunca por el mensaje del backend

**Chosen:** un mapeo `ApiError.status → clave i18n` en `features/cleaning/lib/assign-error.ts`,
con entradas para `403`, `404`, `409`, `422` y un genérico por defecto. `ApiError.message` es
técnico y está en inglés (`lib/api/errors.ts`): no se pinta nunca (R5.1).

**`422` no está en R4.5 y hay que añadirlo**: `backend/app/cleaning/api/errors.py` mapea
`CleaningValidationError → 422`, y ese es el caso de «la limpiadora elegida ya no es una
`CLEANER` activa de este tenant» — perfectamente alcanzable cuando alguien la desactiva mientras
el catálogo cacheado sigue mostrándola. Sin su entrada caería en el genérico y le diríamos a la
manager «ha fallado» cuando lo cierto es «esa persona ya no está». Los tres estados que R4.5 sí
nombra salen del mismo fichero: `404` = `CleaningTaskNotFoundError`, `409` =
`InvalidCleaningTransitionError` (asignar una tarea ya `ACCEPTED`, que `CleaningTask.assign`
rechaza), `403` = falta de `MANAGE_CLEANING_TASKS`.

Rejected: mapear por `error.code` del envelope §23 — `NOT_FOUND`/`CONFLICT`/`VALIDATION_ERROR`
son más gruesos que el status y no distinguen mejor; el status ya es exacto aquí.

### D11 — Una región viva por vista, `role="status" aria-live="polite"`

**Chosen:** `CleaningView` posee una única región viva y escribe en ella la frase traducida del
resultado de la última asignación (éxito o fallo), cumpliendo R5.4 sin depender del color.

Rejected: una región por fila — el lector anuncia la región que cambia; N regiones son N puntos
de anuncio y nadie sabe cuál habló.
Rejected: `role="alert"` para el éxito — assertive interrumpe, y una asignación correcta no es
una urgencia. El error sí se marca `alert` dentro de la misma región (mismo patrón que
`features/guest-portal/components/guest-portal-view.tsx`).

### D12 — Etiqueta y color de estado: `Record` exhaustivo sobre `CleaningTaskStatus`

**Chosen:** `features/cleaning/lib/task-status.ts` con `Record<CleaningTaskStatus,
StatusColorGroup>` sobre los nueve valores, espejo de
`features/dashboard/lib/state-color.ts`. Al ser un `Record` sobre la unión generada, **un décimo
estado en el backend es un error de tipos** y no una fila gris silenciosa (R1.6). La etiqueta
sale del namespace i18n; el identificador crudo no se pinta nunca.

Agrupación propuesta, marcada `ASSUMPTION` porque **PRD §9.1 fija colores para el estado
operacional de la propiedad, no para el estado de una tarea de limpieza**:
`CREATED`/`ASSIGNED` → amber (pendiente de respuesta), `ACCEPTED`/`IN_PROGRESS` → blue (en
curso), `PENDING_REVIEW` → amber, `COMPLETED` → green, `REJECTED`/`FAILED` → red,
`CANCELLED` → gray.

El mapa de clases Tailwind por grupo se **copia** de `STATE_BADGE_CLASS`
(`features/dashboard/components/property-card.tsx`), con un comentario que apunta a su gemelo.
Rejected: extraerlo ya a un módulo compartido — toca una feature entregada sin cambiar su
comportamiento; la extracción se paga cuando aparezca el tercer consumidor.

### D13 — Paginación propia de la feature, prev/next + «página X de Y»

**Chosen:** `features/cleaning/components/cleaning-pagination.tsx`, presentacional, alimentado
por `page`/`total_pages`/`total` de la respuesta (R1.5), con los botones deshabilitados en los
extremos y etiquetas accesibles.

Rejected: lista numerada de páginas — más cromo del que un MVP de dos viviendas justifica.
Rejected: scroll infinito — pierde el «página X de Y» que R1.5 pide reflejar.
Rejected: componente compartido en `components/ui/` — primer consumidor; sube a compartido
cuando haya segundo.

### D14 — Namespace i18n nuevo `cleaning`

**Chosen:** `locales/es/cleaning.json` + `locales/en/cleaning.json`, registrados en
`NAMESPACES` y `resources` de `lib/i18n/resources.ts`. `lib/i18n/catalog-parity.test.ts` cubre
la paridad es/en automáticamente al añadirlo.

Rejected: colgarlo de `dashboard` — es otra capability, y el namespace es la unidad por la que
se carga y se revisa la copia.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Ruta | `frontend/app/(workspace)/cleaning/page.tsx` | Deja de renderizar `RoutePlaceholder`; renderiza `<CleaningView />`. `generateMetadata` intacto. |
| Feature — data | `frontend/features/cleaning/data/dto.ts` | **Nuevo**. `CleaningTask`, `CleaningTaskStatus`, `CleanerSummary`, `PropertySummary`, `PaginatedResponse<T>`, `CleaningTaskFilters`. |
| | `frontend/features/cleaning/data/cleaning-source.ts` | **Nuevo**. Interfaz `CleaningDataSource`: `listTasks`, `listCleaners`, `listProperties`, `assignTask`. |
| | `frontend/features/cleaning/data/http/http-cleaning-source.ts` | **Nuevo**. Implementación sobre `ApiClient`, mapeando `components["schemas"]` → DTOs. |
| | `frontend/features/cleaning/data/index.ts` | **Nuevo**. Punto de composición (`createAuthenticatedClients` + `getCleaningDataSource`). |
| Feature — hooks | `frontend/features/cleaning/hooks/query-keys.ts` | **Nuevo**. `cleaningKeys.tasks/cleaners/properties` sobre `tenantScopedKey`. |
| | `frontend/features/cleaning/hooks/use-cleaning-data.ts` | **Nuevo**. `useCleaningTasks`, `useCleanerDirectory`, `usePropertyDirectory` (`retry: retryPolicy`). |
| | `frontend/features/cleaning/hooks/use-assign-cleaning-task.ts` | **Nuevo**. Mutación + invalidación (D9). |
| Feature — state | `frontend/features/cleaning/state/use-cleaning-filters-store.ts` | **Nuevo**. Zustand: `propertyId`, `status`, `page` y `tenantId`; setters con reset a 1 y `adoptTenant` (D6). |
| Feature — lib | `frontend/features/cleaning/lib/task-status.ts` | **Nuevo**. Grupo de color por estado + clases Tailwind (D12). |
| | `frontend/features/cleaning/lib/directory.ts` | **Nuevo**. `Map` de id→identidad y resolución con los tres casos de D5. |
| | `frontend/features/cleaning/lib/assign-error.ts` | **Nuevo**. `status` → clave i18n (D10). |
| Feature — components | `frontend/features/cleaning/components/cleaning-view.tsx` | **Nuevo**. `"use client"`; orquesta queries, estados, filtros, región viva. |
| | `frontend/features/cleaning/components/cleaning-filters.tsx` | **Nuevo**. Dos `<select>` + limpiar cada filtro (R3.5). |
| | `frontend/features/cleaning/components/cleaning-task-row.tsx` | **Nuevo**. Fila: propiedad, limpiadora, estado, fechas, control de asignación. |
| | `frontend/features/cleaning/components/assign-cleaner-control.tsx` | **Nuevo**. `<select>` + confirmar (D8). |
| | `frontend/features/cleaning/components/cleaning-pagination.tsx` | **Nuevo**. D13. |
| | `frontend/features/cleaning/index.ts` | **Nuevo**. Barrel: `CleaningView`. |
| Auth | `frontend/lib/auth/permissions.ts` | **Nuevo**. Mapa parcial rol→permiso + `useHasPermission` (D7). |
| | `frontend/lib/auth/index.ts` | Reexporta lo anterior. |
| i18n | `frontend/locales/{es,en}/cleaning.json` | **Nuevos**. Toda la copia de la vista. |
| | `frontend/lib/i18n/resources.ts` | Añade el namespace `cleaning`. |
| Tests existentes | `frontend/app/route-coverage.test.ts` | `REAL_PAGE_ROUTE_IDS` gana `"(workspace)/cleaning/page.tsx": "cleaning"`. Sin esto el test falla: la página deja de llevar `routeId=`. |
| | `frontend/app/route-wiring.test.tsx` | Caso nuevo: `/cleaning` monta `CleaningView`. |
| Tests nuevos | `frontend/features/cleaning/**/*.test.ts(x)` | Ver *Verification* abajo. |

**Backend: cero ficheros.** No se regenera `backend/openapi.json` ni
`frontend/lib/api/generated/openapi.d.ts` — no hay cambio de contrato, así que la regla de las
«dos mitades del puente» de `steering/documentation.md` no se dispara.

## Data & interfaces

Sin esquema, sin migración, sin variables de entorno, sin endpoints nuevos. Solo se **consumen**
tipos ya generados.

Interfaz de la feature (firmas, no implementación):

```ts
export interface CleaningDataSource {
  listTasks(tenantId: string, filters: CleaningTaskFilters, page: number):
    Promise<PaginatedResponse<CleaningTask>>;
  listCleaners(tenantId: string): Promise<CleanerSummary[]>;   // role=CLEANER, sin status (D4)
  listProperties(tenantId: string): Promise<PropertySummary[]>;
  assignTask(tenantId: string, taskId: string, cleanerId: string): Promise<CleaningTask>;
}

export interface CleaningTaskFilters {
  propertyId?: string;
  status?: CleaningTaskStatus;
}

export interface CleanerSummary { id: string; name: string; isActive: boolean }
export interface PropertySummary { id: string; name: string; internalCode: string }
```

`assignTask` manda **solo** `assigned_cleaner_id` (R4.6); `AssignCleaningTaskRequest` no admite
otra cosa, así que el tipo generado ya lo impone.

Claves de query (todas bajo `['tenant', tenantId, ...]`, `lib/query/query-keys.ts`):

- `['tenant', id, 'cleaning-tasks', { propertyId, status, page }]`
- `['tenant', id, 'cleaning-cleaners']`
- `['tenant', id, 'cleaning-properties']`

La invalidación de D9 usa el prefijo `['tenant', id, 'cleaning-tasks']`, que alcanza todas las
combinaciones de filtro/página sin enumerarlas.

## Verification

Frontend, Testing Library + vitest (`steering/testing.md`: «Testing Library para componentes con
lógica»). Lo que cada requisito exige probar:

- **R1**: la vista renderiza la página que devuelve la fuente y no el placeholder; `LoadingState`
  con `aria-busy` mientras la consulta de tareas está en vuelo; `ErrorState` con `role="alert"` y
  reintento que relanza; `EmptyState` con filtros activos y cero resultados; los nueve estados
  con etiqueta traducida (test parametrizado sobre la unión, que también prueba la
  exhaustividad de D12).
- **R2**: fila con propiedad y limpiadora por nombre; `assigned_cleaner_id === null` → «sin
  asignar»; id no resoluble → indicador degradado con el resto de la fila intacta; los tres
  renderizados de D5; **una** petición por catálogo con veinte filas en pantalla (contador sobre
  el doble de `CleaningDataSource`).
- **R3**: elegir propiedad/estado manda `property_id`/`status` en la petición (no filtra en
  cliente); ambos combinados viajan juntos; cambiar cualquier filtro estando en la página 3
  vuelve a la 1 (test directo del store, D6); limpiar cada filtro.
- **R4**: confirmar dispara `PATCH` con solo `assigned_cleaner_id` y la lista se refresca sin
  recarga; candidatas = solo `CLEANER` activas; sin `MANAGE_CLEANING_TASKS` no hay control y la
  asignación es texto; `403`/`404`/`409`/`422` → su mensaje traducido, invalidación, y **la fila
  nunca muestra la asignación rechazada**.
- **R5**: paridad es/en la cubre `lib/i18n/catalog-parity.test.ts`; ninguna cadena literal en los
  componentes (el reviewer `sdd-review-i18n` lo verifica); etiqueta accesible en filtros y en el
  control; la región viva recibe el texto del resultado.

Suite completa: `cd frontend && npm test` y `npx tsc --noEmit`.

## Risks & mitigations

- **El espejo de permisos se desincroniza del backend.** Un cambio en `ROLE_PERMISSIONS` que
  quite `MANAGE_CLEANING_TASKS` al manager dejaría el control visible; el backend respondería
  `403` y R4.4 ya cubre que eso no se lea como éxito, así que el daño máximo es una acción que
  falla con mensaje claro, no una escritura indebida. *Mitigación real*: OQ3.
- **Más de 100 propiedades o limpiadoras** → identidades no disponibles a partir de la
  centésima (D3). Marcado `ASSUMPTION` en el código; sin impacto en el MVP y con degradación
  especificada, pero hay que rehacerlo antes de SaaS.
- **La lista y los catálogos pueden desfasarse.** Una limpiadora creada después de que se
  cacheara el catálogo no aparece hasta que la consulta se invalide o expire. Se acepta: la
  alternativa es refetch por interacción, y una asignación a alguien que el catálogo no conoce
  es imposible por construcción (solo se ofrece lo cacheado).
- **Duplicación del mapa de clases de badge** entre esta feature y `property-card.tsx` (D12).
  Aceptada y comentada; el coste de la extracción es tocar una feature entregada.
- **Se copia el layering completo del dashboard para un módulo más pequeño.** El riesgo es
  ceremonia; se acota no replicando `data/mock/` ni sus dos tests de frontera (D1).

## Open questions

Ninguna abierta: las tres se resolvieron en el gate de diseño del 2026-08-19 con Jose.

**OQ1 — ¿Filtros y página en Zustand o en la URL? → Zustand.** Consistencia con
`use-timeline-filters-store.ts`, el reset a página 1 como invariante testeable del setter, y no
estrenar un patrón (`useSearchParams` + límite de Suspense) por un beneficio —enlace
compartible, botón atrás— que nadie ha pedido. Es lo que D6 ya describe; queda confirmado, no
pendiente.

**OQ2 — ¿`/cleaning` abre sin filtrar? → Sin filtrar.** Lista completa, orden del backend
(`created_at` descendente, `id` de desempate), página 1, como describen R1.1 y R3.5. Se
descartó pre-filtrar a `CREATED` + `ASSIGNED`: esconde tareas por omisión y hace que R1.4
muestre un vacío que el usuario no ha pedido.

**OQ3 — ¿`permissions[]` en `CurrentUserResponse`? → Se anota como candidata de roadmap.**
No se hace aquí (es backend, fuera del alcance del proposal), pero la idea no se pierde.

### Encargo explícito a `/sdd:archive`

Al archivar este change, **añadir a los candidatos de `sdd/roadmap.md`** una entrada con este
contenido:

> **`auth-me-permissions`** — `GET /api/v1/auth/me` devuelve la lista de permisos efectivos del
> usuario además de su `role`, y el frontend deja de mantener el espejo parcial de
> `ROLE_PERMISSIONS` que `cleaning-manager-view` estrenó en
> `frontend/lib/auth/permissions.ts` (design D7). Motivo: hoy cada superficie que oculte algo
> por permiso añade una fila a un mapa que el backend puede cambiar sin que nada falle en rojo;
> el daño máximo es un control visible que responde `403`, pero crece con cada superficie
> nueva. Talla S. `needs: cleaning-manager-view`.

Se deja escrito aquí porque ningún gate del flujo SDD detecta un candidato de roadmap que se
decidió en design y nadie trasladó.
