# Tasks: timeline-web

Todo el trabajo es de frontend. Las rutas son relativas a `frontend/` salvo cuando se
indica otra cosa. Las sección 1-4 no cambian ninguna pantalla, así que el sistema sigue
funcionando igual después de cada una; la 5 cambia `/properties/[id]` (que hereda las tres
piezas nuevas por compartir componente, D2) y la 6 estrena `/timeline`.

## 1. Capa de datos: paginación en el DTO y en el mapper <!-- panel: PASS 2026-08-22 -->

- [x] 1.1 `TimelineFilters` (`features/dashboard/data/dto.ts:109-116`) gana `page?: number` y
  `perPage?: number`, anotando que `perPage` viaja **explícito** para que la clave de caché
  declare el tamaño de página que describe. Ni `DashboardDataSource` ni ningún otro DTO
  cambian de firma. [R3.1]
- [x] 1.2 `HttpDashboardSource.getPropertyTimeline`
  (`features/dashboard/data/http/http-dashboard-source.ts:177-201`) mapea `page → page` y
  `perPage → per_page` con el mismo patrón condicional que ya usa para `event_type` y
  `actor_type`. Test en `http-dashboard-source.test.ts`: con los dos campos aparecen en el
  query; sin ellos no se emite ninguna de las dos claves. [R3.1]
- [x] 1.3 `MockDashboardSource.getPropertyTimeline`
  (`features/dashboard/data/mock/mock-dashboard-source.ts:72-83`) trocea el resultado
  filtrado por `page`/`perPage` en lugar de devolver `singlePage(filtered)`, y el sobre
  refleja `page`, `per_page`, `total` y `total_pages` reales. Test en
  `mock-dashboard-source.test.ts` con más entradas que caben en una página: la página 2
  trae el resto y `total_pages` es 2. Es test-only, pero un mock que ignora la paginación
  dejaría que un test «demostrara» una paginación que no ocurre (D9). [R3.1, R3.3]

## 2. Vocabulario cerrado de tipos de evento <!-- panel: PASS 2026-08-22 -->

- [x] 2.1 `features/dashboard/lib/timeline-event-types.ts` **(nuevo)**: `TIMELINE_EVENT_TYPES`
  con los **46** valores, tipado desde el contrato generado
  (`components["schemas"]["TimelineEventType"]`), más la guardia de exhaustividad de D5
  (`type Missing = Exclude<...>`) para que `tsc --noEmit` falle si el enum del backend crece.
  `timeline-event-types.test.ts` **(nuevo)**: longitud 46, sin duplicados, y ningún valor
  fuera del enum del contrato. [R2.1]
- [x] 2.2 Las 46 etiquetas `timeline.eventType.*` en `locales/es/dashboard.json` **y**
  `locales/en/dashboard.json`, redactadas a partir de `TIMELINE_TITLE_TEMPLATES`
  (`backend/app/timeline/domain/rendering.py:70-265`): 41 nuevas y las **5 existentes
  reescritas** con la redacción del catálogo (OQ2 — cambia copy visible hoy en
  `/properties/[id]`: ES `CHECKOUT_WINDOW_REACHED` «Hora de checkout alcanzada» → «Hora de
  salida alcanzada», `PROPERTY_STATE_CHANGED` «Cambio de estado» → «Estado de la vivienda
  actualizado», y sus equivalentes EN). Los dos únicos casos con marcador
  —`RESERVATION_IMPORTED` y `PROPERTY_STATE_CHANGED`— se escriben **sin el marcador y sin la
  preposición que lo introduce**: «Reserva importada», no «Reserva importada desde».
  [R2.3, R2.4]
- [x] 2.3 `features/dashboard/locales/dashboard-locale.test.ts` **(nuevo)**, con el patrón de
  `features/reservations/locales/reservations-locale.test.ts`: recorre los 46 valores del enum
  del contrato y exige etiqueta no vacía en los dos locales, y comprueba que **ninguna**
  etiqueta contiene `{` — que es la forma de que R2.4 no se degrade en silencio cuando alguien
  copie una plantilla del servidor tal cual. La simetría es/en ya la fuerza
  `lib/i18n/catalog-parity.test.ts`. [R2.3, R2.4]

## 3. Estado de UI: página, borrador de rango y propiedad elegida <!-- panel: PASS 2026-08-22 -->

- [x] 3.1 `features/dashboard/state/use-timeline-filters-store.ts` gana `page: number`
  (arranca en 1), el borrador `fromDate?`/`toDate?` en formato `YYYY-MM-DD`, y los setters
  `setPage` y `setRange`. **Cada setter de filtro** (`setActorType`, `setSeverity`,
  `setEventType`, `setRange`) escribe `page: 1` **en la misma mutación**; solo `setPage` mueve
  la página; `reset()` vuelve a `page: 1` y vacía el borrador. Test nuevo
  `use-timeline-filters-store.test.ts`: partiendo de `page: 3`, cada uno de los cuatro setters
  deja `page` en 1 en un solo cambio de estado — la invariante es de la transición, no de un
  efecto posterior (D7). [R3.5, R4.1]
- [x] 3.2 `features/dashboard/state/use-timeline-property-store.ts` **(nuevo)**: guarda el par
  `{ tenantId, propertyId }` en memoria, con `select(tenantId, propertyId)` y `clear()`. El par
  —y no un `propertyId` suelto— porque `logout` no vacía los stores
  (`lib/auth/auth-provider.tsx:107-120`), así que sin el tenant la selección sobreviviría a un
  logout → login como otro tenant (D3). Test `use-timeline-property-store.test.ts`: la
  selección se conserva entre lecturas y **no** hay ni una escritura en `localStorage`,
  `sessionStorage` ni `document.cookie` (espiar los tres y exigir cero llamadas). [R1.4]

## 4. Aritmética del rango de fechas <!-- panel: PASS 2026-08-22 -->

- [x] 4.1 `features/dashboard/lib/timeline-range.ts` **(nuevo)** con `startOfDayIso`,
  `endOfDayIso` e `isInverseRange`, más `timeline-range.test.ts` **(nuevo)**: `startOfDayIso`
  devuelve el **inicio del día local** como instante con zona y `endOfDayIso` el **final**
  (`23:59:59.999` local), ninguna salida es *naive* —un extremo sin zona horaria es un `422`
  del dominio (`backend/app/timeline/domain/repositories.py:73-78` →
  `backend/app/timeline/api/errors.py:30`)—, el día se toma **local** y no UTC porque la lista
  formatea los instantes en la zona del navegador (`features/dashboard/lib/format.ts`), e
  `isInverseRange` es cierto solo cuando `toDate < fromDate` comparando `YYYY-MM-DD`. Es la
  única aritmética de la pantalla y es donde está la trampa del `422`, así que va aislada y con
  su test. [R4.2, R4.3, R4.4]

## 5. `PropertyTimeline`: enum cerrado, paginación y rango <!-- panel: PASS 2026-08-22 -->

- [x] 5.1 Borrar `optionsQuery` y `eventTypeOptions`
  (`features/dashboard/components/detail/property-timeline.tsx:45-54`) y poblar el desplegable
  de tipo con `TIMELINE_EVENT_TYPES`. `t("timeline.eventType." + type)` pasa a llamarse
  **sin** segundo argumento, para que no quede el literal crudo del enum como texto de
  respaldo. Desaparece una petición HTTP por render. [R2.1, R2.2, R2.5]
- [x] 5.2 El componente envía `page` (del store) y `perPage: 20` fijo en cada consulta, y
  renderiza los controles de página — `<nav aria-label>`, prev/next deshabilitados en los
  extremos, «página X de Y» por clave interpolada, clase `tap-target` — **solo si
  `total_pages > 1`**, copiando `features/properties/components/list/properties-view.tsx:252-280`.
  `per_page` no se expone en la interfaz. `hooks/query-keys.ts` y `hooks/use-dashboard-data.ts`
  **no se tocan**: la clave ya mete el objeto de filtros entero, así que cada página es una
  entrada de caché distinta y nada se acumula en Zustand. [R3.2, R3.3, R3.4, R3.6]
- [x] 5.3 Dos `<input type="date">` con etiqueta propia cada uno (precedente
  `features/reservations/components/list/reservations-filters.tsx:77-116`) sobre el borrador
  del store. El par comprometido `from`/`to` se recalcula con los helpers de 4.1 **solo si el
  borrador no es inverso**; si lo es, se pinta `timeline.range.errorInverse` junto a los campos
  y el par comprometido **no se toca** — al no cambiar la clave de query, TanStack Query no
  dispara nada: ni la petición inválida ni una «válida» colateral. Los dos extremos son
  opcionales e independientes y se combinan en AND con los demás filtros. [R4.1, R4.3, R4.4]
- [x] 5.4 Claves nuevas del componente en `locales/es/dashboard.json` **y**
  `locales/en/dashboard.json`: `timeline.pagination.{label,prev,next,position}` y
  `timeline.range.{from,to,errorInverse}`. Ninguna string hardcodeada. [R5.5]
- [x] 5.5 Ampliar `property-timeline.test.tsx` — y **enmendar las aserciones existentes**, que
  hoy esperan `usePropertyTimeline("redes11", {})` y a partir de 5.2 recibirán también
  `page`/`perPage`: el desplegable ofrece 46 opciones traducidas (ninguna es el literal crudo),
  el hook se llama **una sola vez por render** (murió `optionsQuery`), la barra de páginas no
  se pinta con `total_pages: 1` y sí con `total_pages: 2` navegando adelante y atrás dentro de
  `1..total_pages`, cambiar un filtro estando en `page: 3` consulta la página 1, un rango
  inverso **no cambia los argumentos del hook** y pinta el error de campo, un rango válido
  manda extremos con zona horaria, y un tipo sin escritor de producción pinta el `EmptyState`.
  [R2.1, R2.6, R3.3, R3.5, R4.3, R4.4]
- [x] 5.6 Tests de lo que R6 protege y que hoy nadie cubre: una `description` con marcado
  (`<img src=x onerror=...>`) se pinta como **texto** y no crea nodo, `title` se pinta tal como
  llega sin retraducir, y el reset de filtros al cambiar `propertyId`
  (`property-timeline.tsx:43`, comportamiento preexistente **sin test**) se conserva. Ni
  `dangerouslySetInnerHTML`, ni `innerHTML`, ni renderizador de markdown entran en el diff.
  [R1.5, R6.1, R6.3]

## 6. La superficie `/timeline` <!-- panel: PASS 2026-08-22 (docs: obligación docs/dashboard.md diferida a /sdd:archive, ver design.md § Risks) -->

- [x] 6.1 `features/dashboard/components/timeline/timeline-view.tsx` **(nuevo)**, componente
  cliente: `<h1>` con `tNav("routes.timeline.title")` (como
  `features/reservations/components/list/reservations-view.tsx:85-87`); selector de propiedad
  alimentado por `useDashboardCards()`, cuyas opciones son **exactamente** las propiedades que
  devuelve el hook, identificadas por `propertyCode`; `LoadingState` y `ErrorState` compartidos
  de `@/components/states` con `dashboard:cards.error.*` y `states:error.retry` mientras la
  consulta esté pendiente o haya fallado, sin detalle de error crudo; `EmptyState` con copy
  propio `timeline.picker.*` mientras no haya selección — y en ese estado **no se monta**
  `PropertyTimeline`, que es lo que garantiza que no se emita ninguna petición a
  `GET /api/v1/timeline/{property_id}` sin añadir un `enabled` al hook (D4). Con selección
  válida monta `<PropertyTimeline propertyId={...} />` y nada más: ni una segunda lista, ni un
  segundo hook de timeline, ni un segundo store de filtros. La selección del store se honra
  **solo si su `tenantId` coincide** con el del contexto autenticado; si no, se trata como
  «ninguna». Sin autoselección de «la primera propiedad». Claves nuevas
  `timeline.picker.*` en los dos locales. [R1.1, R1.2, R1.3, R1.4, R1.6, R5.5]
- [x] 6.2 `features/dashboard/index.ts` exporta `TimelineView` — y solo eso: `PropertyTimeline`
  sigue interno de la feature (OQ1, que enmienda la letra de R5.2) —, y
  `app/(workspace)/timeline/page.tsx` sustituye `<RoutePlaceholder routeId="timeline" />` por
  `<TimelineView />` importado **del barrel** y nunca de una ruta interna, conservando
  `generateMetadata` con `routeMetadata("timeline")`. La página sigue siendo Server Component:
  la isla cliente es la vista (`sdd/specs/frontend-foundation.md:14`). [R5.2, R5.3]
- [x] 6.3 `features/dashboard/components/timeline/timeline-view.test.tsx` **(nuevo)**: las
  opciones del selector son exactamente las propiedades del hook, por `propertyCode`; sin
  selección se pinta el estado «elige una vivienda» y el hook de timeline **no se llama**; al
  elegir se monta el timeline con ese `propertyId`; una selección guardada con **otro**
  `tenantId` se trata como «ninguna» y tampoco consulta; carga y error pintan los estados
  compartidos sin exponer detalle crudo. [R1.1, R1.2, R1.3, R1.4, R1.6]
- [x] 6.4 Reescribir `routes.timeline.description` en `locales/es/navigation.json` **y**
  `locales/en/navigation.json` para describir el historial de **una vivienda a la vez** — hoy
  prometen «todas las propiedades» / «across all properties», que es el timeline global que
  `sdd/specs/dashboard-api.md:40-41` prohíbe y `backend/openapi.json` no sirve. Como
  `routeMetadata` resuelve la `description` de la ruta, arregla también la meta-descripción de
  la página, no solo el menú. [R5.1]
- [x] 6.5 Comprobar por diff (`git diff --name-only origin/main...HEAD`) que quedan **fuera**:
  `features/shell/navigation/route-registry.ts` y su cerco de tests (`route-registry.test.ts`,
  `route-metadata.test.ts`, `breadcrumbs.test.ts`, `select-routes.test.ts`,
  `match-route.test.ts`), `features/shell/components/bottom-navigation.tsx`,
  `features/dashboard/hooks/query-keys.ts`, `features/dashboard/hooks/use-dashboard-data.ts`,
  `features/dashboard/data/dashboard-source.ts`,
  `features/dashboard/components/detail/property-detail-view.tsx` y todo `backend/**`
  —incluida `backend/app/auth/domain/policy.py`, que **no gana ni un rol lector**, porque eso
  reabriría la decisión de publicar `description`. Si alguno aparece en el diff, la decisión de
  ruta o la de audiencia se derivó mal. [R5.4, R6.2]

## 7. Verificación

- [x] 7.1 Preparar el contenedor para la suite: `make up` y luego el copiado de nueve ficheros
  que documenta `sdd/project.md` (§ Worktree bootstrap), para que los dos tests que leen por
  encima de `/app` —`features/provenance/workflow-contract.test.ts` y
  `lib/config/build-identity-contract.test.ts`— no den `ENOENT` ajeno al change. Sin esto la
  cifra de la suite no es interpretable.
- [x] 7.2 Suite completa del frontend en verde:
  `docker compose exec -T frontend npm test`. Anotar el número de ficheros y de tests y
  compararlo con el estado previo al change (63 ficheros / 415 tests el 2026-08-22, según
  `sdd/project.md`) — «PASS (0) FAIL (0)» es una colección fallida, no un verde.
- [x] 7.3 Typecheck sin errores: `docker compose exec -T frontend npm run typecheck`. Es aquí
  donde falla la guardia de exhaustividad de 2.1 si el enum del backend creciera. [R2.1]
- [x] 7.4 Lint sin errores: `docker compose exec -T frontend npm run lint`.
- [x] 7.5 Comprobación manual en navegador: `make up PORT_OFFSET=<n>` (un worktree enlazado no
  publica puertos) y en `/timeline` — se llega al estado «elige una vivienda» **sin ninguna
  petición a `/api/v1/timeline/`** en la pestaña de red, elegir una vivienda pinta su historial,
  filtrar por un tipo sin escritor da el estado vacío, paginar cuando hay más de 20 eventos,
  acotar un rango válido devuelve resultados y un rango inverso pinta el error de campo **sin**
  emitir petición. Comprobar además que `/properties/[id]` sigue funcionando y hereda el enum
  cerrado, la paginación y el rango sin que su diff la toque. [R1, R3, R4, R5]
- [x] 7.6 Backend: nada que correr. Este change no toca `backend/**`, ni `backend/openapi.json`,
  ni `lib/api/generated/openapi.d.ts`, así que `make openapi` y `npm run api:check` no aplican
  (y el segundo, además, no funciona tal cual en un worktree enlazado — `sdd/project.md`).

---

**Cobertura de requisitos**:
R1 → 3.2, 5.6, 6.1, 6.3 ·
R2 → 2.1, 2.2, 2.3, 5.1, 5.5, 7.3 ·
R3 → 1.1, 1.2, 1.3, 3.1, 5.2, 5.5 ·
R4 → 3.1, 4.1, 5.3, 5.5 ·
R5 → 5.4, 6.1, 6.2, 6.4, 6.5 ·
R6 → 5.6, 6.5.
Los seis quedan cubiertos.
