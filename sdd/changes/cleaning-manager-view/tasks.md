# Tasks: cleaning-manager-view

Todo el trabajo es de frontend (`frontend/**`). **Cero ficheros de backend**: no se regenera
`backend/openapi.json` ni `frontend/lib/api/generated/openapi.d.ts` (design, «Changes by area»).

Cada tarea incluye su test (`steering/testing.md`: «Cada tarea de implementación incluye su test»);
Testing Library + vitest para lo que tiene lógica, test puro para `lib/`, `state/` y `data/`.
Las secciones están ordenadas para que el árbol quede verde tras cada una: `/cleaning` sigue siendo
el placeholder hasta la sección 7, funciona en solo lectura al terminarla, y gana la asignación en la 8.

## 1. Fundamentos transversales (i18n y permisos de UI) <!-- panel: PASS 2026-08-19 -->

- [x] 1.1 Crear el namespace i18n `cleaning`: `frontend/locales/es/cleaning.json` y
  `frontend/locales/en/cleaning.json` con toda la copia de la vista (cabeceras de columna,
  los nueve estados de `CleaningTaskStatus`, etiquetas y «limpiar» de los dos filtros,
  título/descripción de vacío y de error, «sin asignar», «identidad no disponible»,
  textos del control de asignación, paginación «página X de Y», y los mensajes de
  `403`/`404`/`409`/`422`/genérico). Registrarlo en `NAMESPACES` y `resources` de
  `frontend/lib/i18n/resources.ts` (D14). La paridad es/en la verifica automáticamente
  `frontend/lib/i18n/catalog-parity.test.ts` al entrar el namespace — comprobar que pasa. [R5.1]
- [x] 1.2 Crear `frontend/lib/auth/permissions.ts` (D7): `Permission` con lo que el frontend usa
  para ocultar (hoy solo `MANAGE_CLEANING_TASKS`), `ROLE_UI_PERMISSIONS: Record<UserRole, readonly
  Permission[]>` sobre los cinco valores de `UserRole` del contrato generado, y
  `useHasPermission(permission)` leyendo `role` de `useAuth()`. La cabecera declara que es una
  **pista de UX parcial** y que la autoridad es el backend (`steering/frontend.md`,
  `steering/security.md` regla 2). Reexportar desde `frontend/lib/auth/index.ts`.
  Test (`frontend/lib/auth/permissions.test.tsx`): `PROPERTY_MANAGER` tiene
  `MANAGE_CLEANING_TASKS`, `TENANT_OWNER` no, y sin usuario autenticado `useHasPermission`
  devuelve `false`. [R4.3]

## 2. Capa de datos de `features/cleaning/` <!-- panel: PASS 2026-08-21 (secciones 2-5 juntas) -->

- [x] 2.1 Crear `frontend/features/cleaning/data/dto.ts` (D1): `CleaningTaskStatus` (alias del tipo
  generado, no una unión escrita a mano), `CleaningTask`, `CleanerSummary {id, name, isActive}`,
  `PropertySummary {id, name, internalCode}`, `PaginatedResponse<T>` y `CleaningTaskFilters
  {propertyId?, status?}`, con las firmas exactas de design «Data & interfaces». [R1, R2, R3]
- [x] 2.2 Crear `frontend/features/cleaning/data/cleaning-source.ts`: interfaz `CleaningDataSource`
  con `listTasks`, `listCleaners`, `listProperties` y `assignTask`, `tenantId` explícito en la
  frontera (patrón de `features/dashboard/data/dashboard-source.ts`). Documentar en la cabecera que
  los métodos rechazan con `ApiError`. **Sin `data/mock/`** ni test de frontera (D1). [R1, R2, R4]
- [x] 2.3 Crear `frontend/features/cleaning/data/http/http-cleaning-source.ts` sobre `ApiClient`:
  `listTasks` manda `page`, `per_page`, y solo los filtros presentes en `property_id`/`status`
  (R3.1–R3.3, nunca filtrado en cliente); `listCleaners` pide `role=CLEANER&per_page=100` **sin
  `status`** (D4) y `listProperties` `page=1&per_page=100` (D3), ambos marcados `ASSUMPTION` en el
  código por el techo de 100; `assignTask` hace `PATCH /api/v1/cleaning-tasks/{task_id}` con
  `assigned_cleaner_id` como **único** campo del cuerpo (R4.6). Mapea
  `CleaningTaskPageResponse`/`UserPageResponse`/`PropertyResponse` a los DTOs, tomando `name` de
  `UserResponse`, `internal_code`+`name` de la propiedad e `isActive` de `status === "ACTIVE"`.
  Test (`http-cleaning-source.test.ts`, patrón de `http-dashboard-source.test.ts`): query string
  exacta de cada método con y sin filtros, cuerpo del `PATCH`, y mapeo de campos. [R2.1, R2.2, R3.1, R3.2, R3.3, R4.6]
- [x] 2.4 Crear `frontend/features/cleaning/data/index.ts` como único punto de composición
  (`createAuthenticatedClients` + `notifySessionExpired` + `getCleaningDataSource()`), reexportando
  la interfaz y los DTOs, igual que `features/dashboard/data/index.ts`. [R1]

## 3. Claves de query y consultas de lectura <!-- panel: PASS 2026-08-21 (con 2-5) -->

- [x] 3.1 Crear `frontend/features/cleaning/hooks/query-keys.ts`: `cleaningKeys.tasks(tenantId,
  filters, page)`, `.cleaners(tenantId)`, `.properties(tenantId)` sobre `tenantScopedKey`
  (`lib/query/query-keys.ts`), con los recursos `cleaning-tasks`, `cleaning-cleaners`,
  `cleaning-properties`. Test: toda clave empieza por `['tenant', tenantId, ...]`, dos combinaciones
  de filtro/página dan claves distintas, y el prefijo `['tenant', id, 'cleaning-tasks']` es prefijo
  de todas las de tareas (lo que D9 invalida). [R1, R2.5, R3]
- [x] 3.2 Crear `frontend/features/cleaning/hooks/use-cleaning-data.ts` con `useCleaningTasks(filters,
  page)`, `useCleanerDirectory()` y `usePropertyDirectory()` — `useQuery`, `retry: retryPolicy`,
  `tenantId` desde `useAuth()` (patrón `use-dashboard-data.ts`). Test
  (`use-cleaning-data.test.tsx`): los filtros y la página viajan a `listTasks` tal cual; con dos
  hooks de tareas montados para páginas distintas, el doble de `CleaningDataSource` recibe **una
  sola** llamada a `listCleaners` y **una** a `listProperties` (R2.5). [R1.1, R2.5, R3.1, R3.2, R3.3]

## 4. Estado de filtros y página <!-- panel: PASS 2026-08-21 (con 2-5) -->

- [x] 4.1 Crear `frontend/features/cleaning/state/use-cleaning-filters-store.ts` (Zustand, D6/OQ1)
  con `propertyId`, `status`, `page`, y `setPropertyId`/`setStatus` que ponen **`page: 1` dentro del
  propio setter**, más `setPage`, `clearPropertyId`, `clearStatus` y `reset`. Test directo del store,
  sin renderizar: estando en `page: 3`, cambiar o limpiar cualquiera de los dos filtros deja
  `page: 1`; `setPage` no toca los filtros. [R3.4, R3.5]

## 5. Presentación pura (`features/cleaning/lib/`) <!-- panel: PASS 2026-08-21 (con 2-5) -->

- [x] 5.1 Crear `frontend/features/cleaning/lib/task-status.ts` (D12): `Record<CleaningTaskStatus,
  StatusColorGroup>` sobre los nueve valores y su mapa de clases Tailwind, copiado de
  `STATE_BADGE_CLASS` (`features/dashboard/components/property-card.tsx`) con el comentario que
  apunta a su gemelo, y `ASSUMPTION` de que PRD §9.1 fija colores del estado **de la propiedad**, no
  de la tarea. Test parametrizado sobre la unión generada: los nueve estados tienen grupo y clase, y
  la clave i18n de cada uno existe en `locales/es/cleaning.json` — de modo que un décimo estado
  rompa en rojo. [R1.6]
- [x] 5.2 Crear `frontend/features/cleaning/lib/directory.ts`: construcción del `Map<id, identidad>`
  a partir de `CleanerSummary[]`/`PropertySummary[]` y una resolución que devuelve los **tres**
  casos de D5 (`unassigned` / `pending` / `unavailable` / resuelto). Test: id nulo, catálogo en
  vuelo, catálogo resuelto sin ese id, catálogo en error, e id presente. [R2.3, R2.4]
- [x] 5.3 Crear `frontend/features/cleaning/lib/assign-error.ts` (D10): `ApiError.status` → clave
  i18n con entradas para `403`, `404`, `409`, `422` y genérico por defecto; `ApiError.message`
  **nunca** se devuelve. Test: los cuatro status dan cuatro claves distintas, un `500` y un error no
  `ApiError` caen en la genérica, y ninguna salida contiene texto del backend. [R4.4, R4.5, R5.1]

## 6. Componentes de la vista en solo lectura <!-- panel: PASS 2026-08-21 (secciones 6-7 juntas) -->

- [x] 6.1 Crear `frontend/features/cleaning/components/cleaning-task-row.tsx`: propiedad
  (`internal_code` + `name`), limpiadora por nombre, badge de estado con etiqueta traducida y fechas
  relevantes; identidad resuelta con `lib/directory.ts` y celda de asignación como **texto de solo
  lectura** en esta sección. Mobile-first: legible y sin scroll horizontal desde 320 px. Test:
  fila con propiedad y limpiadora por nombre; `assigned_cleaner_id === null` → «sin asignar»; id no
  resoluble → indicador degradado **y el resto de la fila intacta**; catálogo en vuelo → marcador
  neutro; nunca se pinta un UUID ni el identificador crudo del enum. [R1.6, R2.1, R2.2, R2.3, R2.4, R5.2]
- [x] 6.2 Crear `frontend/features/cleaning/components/cleaning-pagination.tsx` (D13),
  presentacional: prev/next con etiqueta accesible, «página X de Y» y `total`, botones
  deshabilitados en los extremos. Test: en la página 1 prev está deshabilitado, en la última next
  también, cada botón llama a `onPageChange` con la página correcta, y con `total_pages === 1` no
  hay navegación. [R1.5, R5.3]
- [x] 6.3 Crear `frontend/features/cleaning/components/cleaning-filters.tsx`: dos `<select>`
  nativos (propiedad desde `usePropertyDirectory`, estado sobre los nueve valores) con etiqueta
  accesible asociada, y una acción explícita de limpiar **cada** filtro. Escribe en el store de 4.1.
  Test: elegir propiedad/estado llama al setter correspondiente; limpiar cada filtro lo pone a
  `undefined`; ambos controles son alcanzables y operables por teclado; toda string sale de i18n. [R3.1, R3.2, R3.5, R5.1, R5.3]
- [x] 6.4 Crear `frontend/features/cleaning/components/cleaning-view.tsx` (`"use client"`) y el
  barrel `frontend/features/cleaning/index.ts` exportando `CleaningView`: orquesta las tres
  consultas y el store, y renderiza `LoadingState` (con `aria-busy`), `ErrorState` (`role="alert"` y
  reintento que relanza `refetch`), `EmptyState` o la lista + filtros + paginación, con una única
  región viva `role="status" aria-live="polite"` ya presente (D11, se llena en 8.3). El error de
  **catálogo** no propaga a `ErrorState` (D5). Test (`cleaning-view.test.tsx`, doble de
  `CleaningDataSource`): renderiza la página que devuelve la fuente y no `RoutePlaceholder`;
  los tres estados de la consulta de tareas; vacío con filtros activos distinguible de error y de
  carga; catálogo caído y lista igualmente renderizada; los nueve estados con etiqueta traducida. [R1.1, R1.2, R1.3, R1.4, R1.6, R2.5, R5.2]

## 7. Cableado de la ruta `/cleaning` <!-- panel: PASS 2026-08-21 (con 6-7) -->

- [x] 7.1 `frontend/app/(workspace)/cleaning/page.tsx` deja de renderizar `RoutePlaceholder` y
  renderiza `<CleaningView />`, conservando `generateMetadata`. En el mismo paso, y porque la página
  pierde el `routeId=` del que hoy depende el test:
  `frontend/app/route-coverage.test.ts` añade `"(workspace)/cleaning/page.tsx": "cleaning"` a
  `REAL_PAGE_ROUTE_IDS`, y `frontend/app/route-wiring.test.tsx` gana el caso de que `/cleaning`
  monta `CleaningView`. Al terminar esta sección `/cleaning` es la lista real en solo lectura. [R1.1]

## 8. Asignar y reasignar <!-- panel: PASS 2026-08-21 (2 rondas de arreglo) -->

- [x] 8.1 Crear `frontend/features/cleaning/hooks/use-assign-cleaning-task.ts` (D9): `useMutation`
  con `retry: false` sobre `assignTask` y, en `onSettled`, `invalidateQueries` del prefijo
  `['tenant', tenantId, 'cleaning-tasks']` — **en éxito y en fallo**, sin escritura optimista de la
  caché. Test: la mutación manda solo `assigned_cleaner_id`; se invalida el prefijo tras un éxito y
  también tras un `404`; ninguna combinación de filtro/página queda con datos viejos; no hay
  `setQueryData`. [R4.1, R4.5, R4.6]
- [x] 8.2 Crear `frontend/features/cleaning/components/assign-cleaner-control.tsx` (D8): `<select>`
  nativo con las candidatas (`role=CLEANER` **y** `isActive`, filtrado en cliente sobre el catálogo
  de D4) más un **botón de confirmación explícito** que dispara la mutación; sin
  `MANAGE_CLEANING_TASKS` el componente no se renderiza y la celda queda como texto de solo lectura.
  Cablearlo en `cleaning-task-row.tsx` sustituyendo el texto de 6.1 cuando hay permiso. Test:
  candidatas = solo activas (una limpiadora `INACTIVE` sigue resolviendo su nombre en la fila pero
  no aparece como opción); `change` en el `<select>` **no** dispara `PATCH` y solo lo hace el botón;
  con `TENANT_OWNER` no hay control y sí texto; etiqueta accesible y operación por teclado. [R4.1, R4.2, R4.3, R5.1, R5.3]
- [x] 8.3 Integrar el resultado en `cleaning-view.tsx`: la región viva de 6.4 recibe la frase
  traducida de la última asignación — éxito en `polite`, fallo marcado `alert` dentro de la misma
  región (D11) — y el texto del fallo sale de `lib/assign-error.ts`, nunca de `ApiError.message`.
  Test: éxito anuncia y la fila muestra la nueva asignación tras la invalidación; `403`, `404`,
  `409` y `422` anuncian su mensaje traducido, la lista se refresca y **la fila nunca muestra la
  asignación rechazada**; una tarea que sale del filtro activo al asignarse desaparece de la
  página tras el refresco. [R4.1, R4.4, R4.5, R5.1, R5.4]

## 9. Documentación

- [x] 9.1 `README.md` (raíz): la línea de superficies del frontend deja de decir que `/cleaning`
  «muestra un placeholder en preparación» y la declara funcional, enlazando a `docs/cleaning.md`
  (`steering/documentation.md`: «README raíz al día por change»). [R1.1]
- [x] 9.2 `docs/cleaning.md`: sección nueva de **cómo opera el manager desde `/cleaning`** — qué ve
  cada rol (y por qué la propietaria no ve el control de asignación), cómo se filtra y se pagina,
  qué significa «identidad no disponible», y el límite de 100 propiedades/limpiadoras del catálogo
  (D3). Sin duplicar las reglas EARS de `sdd/specs/`. [R2.4, R4.3]

## 10. Verificación

- [x] 10.1 Suite completa del frontend en verde: `cd frontend && npm test` (incluye
  `catalog-parity.test.ts`, `route-coverage.test.ts` y `route-wiring.test.tsx`).
- [x] 10.2 Tipos y lint: `cd frontend && npm run typecheck` (`npx tsc --noEmit`) y
  `cd frontend && npm run lint`, ambos limpios.
- [x] 10.3 Comprobación manual en navegador. En este worktree hace falta publicar puertos:
  `make up PORT_OFFSET=<n>` y abrir `http://localhost:30<n>`… (ver `make ports`). Con sesión de
  `PROPERTY_MANAGER`: lista, filtros combinados, paginación, asignar y reasignar; con sesión de
  `TENANT_OWNER`: la misma lista sin control de asignación. A 320 px de ancho sin scroll horizontal,
  recorrido completo por teclado, y la vista en `es` y en `en`. [R4.3, R5.2, R5.3]
  <!-- Hecho 2026-08-21 con `make up PORT_OFFSET=40` + datos de `bootstrap`/`seed-demo`
       más 22 tareas creadas por API. Comprobado: a 320 px `scrollWidth == clientWidth`
       y ningún elemento desbordado (R5.2); lista, ambos filtros combinados y
       paginación «Página 1 de 2 · 23 tareas en total»; PROPERTY_MANAGER ve el control
       y TENANT_OWNER la misma lista con 0 selects y 0 botones de asignar (R4.3);
       candidatas solo activas — la limpiadora INACTIVE resuelve su nombre pero no se
       ofrece (R4.2/D4); asignación correcta anunciada en la región viva única como
       «Tarea asignada a Marta Ruiz.» sin `alert`, y un 409 real anunciado como «Esa
       tarea ya no admite un cambio de asignación.» con `alert`, dejando la fila en
       «Sin asignar» (R4.4/R4.5/D11); es y en completos; 0 errores de consola.
       El 409 salió del `PropertyStateMachine` del backend —asignar exige que la
       vivienda esté en `AWAITING_CLEANING`—, que es comportamiento suyo y no de este
       change. -->
- [x] 10.4 Repaso de cobertura de requisitos: R1 (§3, §6, §7), R2 (§2, §3, §5, §6), R3 (§2, §3, §4,
  §6), R4 (§1, §5, §8), R5 (§1, §6, §8, §10.3) — cada criterio de aceptación con al menos un test
  que lo demuestre.
