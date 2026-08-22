# Design: timeline-web

## Context

El timeline ya existe y ya habla HTTP real. `frontend/features/dashboard/components/detail/property-timeline.tsx`
(159 líneas) es un componente cliente con filtros de tipo/actor/severidad, estados
compartidos y formateo por locale, montado por `PropertyDetailView`
(`components/detail/property-detail-view.tsx`) y servido por
`HttpDashboardSource.getPropertyTimeline` (`data/http/http-dashboard-source.ts:177-201`)
contra `GET /api/v1/timeline/{property_id}`. La costura está entera: `usePropertyTimeline`
(`hooks/use-dashboard-data.ts:65-80`), clave por tenant+propiedad+filtros
(`hooks/query-keys.ts:15-20`) y un store Zustand de filtros
(`state/use-timeline-filters-store.ts`).

Lo que falta es la superficie: `app/(workspace)/timeline/page.tsx:11` renderiza
`RoutePlaceholder` sobre una ruta plana (`features/shell/navigation/route-registry.ts:90-100`:
`pattern: "/timeline"`, `match: "exact"`) mientras el endpoint exige una propiedad
(`backend/app/timeline/api/router.py:65-66`). Y le faltan tres piezas **dentro** del
componente: paginación (`TimelineFilters` en `data/dto.ts:110-116` no lleva `page`/`per_page`),
rango de fechas, y un vocabulario de tipos que hoy se deriva de los datos con una segunda
consulta (`property-timeline.tsx:47-54`).

Contrato verificado el 2026-08-22 y **congelado**: `page` (≥1), `per_page` (1..100, def. 20),
`event_type`, `severity`, `actor_type`, `from`/`to`
(`backend/app/timeline/api/router.py:89-95`); sobre plano `{data, total, page, per_page,
total_pages}`; `TimelineEventType` con **46** valores en
`frontend/lib/api/generated/openapi.d.ts` (contados) y en `backend/openapi.json`. No hay
`GET /api/v1/timeline` global — verificado: `backend/openapi.json` solo declara
`/api/v1/timeline/{property_id}`, y `sdd/specs/dashboard-api.md:40-41` lo prohíbe.

## Decisions

### D1 — La página monta una vista de feature nueva, `TimelineView`, y sigue siendo Server Component

**Chosen:** un componente cliente nuevo `features/dashboard/components/timeline/timeline-view.tsx`,
exportado desde `features/dashboard/index.ts`; `app/(workspace)/timeline/page.tsx` conserva
`generateMetadata` con `routeMetadata("timeline")` y sustituye el `RoutePlaceholder` por
`<TimelineView />`. Es el patrón literal de las otras cuatro superficies del repo —
`/dashboard` → `DashboardView`, `/properties` → `PropertiesView`, `/properties/[id]` →
`PropertyDetailView` — y `sdd/specs/frontend-foundation.md:14` exige que las páginas queden
como Server Components con `"use client"` acotado a islas interactivas. El selector es estado
interactivo, así que la isla es la vista, no la página.

Lectura de **R5.2**: lo que la regla protege es que la página importe del barrel de la feature
y nunca de una ruta interna, y eso se cumple con `TimelineView`. Su letra pide además exportar
`PropertyTimeline` y que la página lo importe; eso obligaría a que la página fuese cliente o a
partir la pantalla en dos islas que se coordinan por store. Resuelto en **OQ1**: solo `TimelineView`.

Rejected: página cliente que compone selector + `PropertyTimeline` — rompe `frontend-foundation.md:14`
y duplica en `app/` lógica que pertenece a la feature.
Rejected: montar el selector como isla y `PropertyTimeline` como segunda isla hermana — dos
componentes acoplados por un store para lo que es un solo árbol.

### D2 — Un solo componente de timeline, dos puntos de montaje; todo lo nuevo entra dentro

**Chosen:** paginación, rango de fechas y vocabulario cerrado se implementan **dentro** de
`property-timeline.tsx`. `TimelineView` no contiene ni una lista de eventos ni un hook de
timeline: elige la propiedad y monta `<PropertyTimeline propertyId={...} />`. Consecuencia
deliberada: la sección de `/properties/[id]` hereda las tres piezas sin que su diff la toque
(`property-detail-view.tsx` no cambia).

Rejected: una segunda lista en `TimelineView` — es la duplicación de pantalla que la nota de
roadmap descartó al rechazar la opción (b).

### D3 — La propiedad elegida vive en un store Zustand **con el tenant dentro**

**Chosen:** store nuevo `features/dashboard/state/use-timeline-property-store.ts`, hermano de
`use-timeline-filters-store.ts`, que guarda el par `{ tenantId, propertyId }`. `TimelineView`
honra la selección **solo si `tenantId` coincide** con el del contexto autenticado; si no,
la trata como «ninguna».

El par, y no un `propertyId` suelto, porque `logout` no limpia nada más que la sesión:
`lib/auth/auth-provider.tsx:107-120` descarta tokens y usuario, y **no** vacía ni los stores
Zustand ni la caché de TanStack Query. Un `propertyId` suelto sobreviviría a un
logout → login como otro tenant en la misma pestaña y dispararía un `GET` sobre una propiedad
ajena, que el backend contesta con un `404` indistinguible de inexistente
(`sdd/specs/dashboard-api.md:147-148`) y que `retryPolicy` no reintenta — exactamente el
síntoma mudo por el que R1.4 prohíbe `localStorage`. Comparar el tenant es la forma de que la
regla valga también para la memoria.

Rejected: `useState` en `TimelineView` — se pierde al navegar a `/properties/[id]` y volver,
que es justo lo que R1.4 conserva.
Rejected: `localStorage` / cookie — prohibido por R1.4.
Rejected: parámetro de URL `?property=` — sobrevive al recargado, sí, pero mete un
identificador de tenant en la barra y en el historial (la misma clase de fuga que R1.4
rechaza para el disco) y R1.4 ya cerró la decisión en memoria.

### D4 — Antes de elegir no se monta el timeline, y por eso no hay petición

**Chosen:** mientras no haya selección válida, `TimelineView` renderiza `EmptyState` con copy
propio (`timeline.picker.empty*`) y **no monta** `PropertyTimeline`. Como el hook vive dentro
del componente, no montarlo es lo que garantiza R1.2 sin añadir un `enabled` a
`usePropertyTimeline` ni un flag a la clave de query. Sin autoselección de «la primera
propiedad»: con N viviendas cualquier elección automática es arbitraria y el primer pintado no
debe pedir un feed que nadie pidió.

Estados del propio selector (R1.6): `LoadingState` y `ErrorState` compartidos de
`@/components/states` con las claves ya existentes `dashboard:cards.error.*` y
`states:error.retry`, igual que `DashboardView` (`components/dashboard-view.tsx:21-34`) — sin
detalle de error crudo.

Rejected: `enabled: false` en el hook — mete una condición de UI en la capa de datos y deja la
entrada de caché en un estado que nadie consulta.

### D5 — El desplegable de tipos ofrece el enum cerrado, con guardia en tiempo de compilación

**Chosen:** constante nueva `features/dashboard/lib/timeline-event-types.ts` con los 46 valores,
tipada desde el contrato generado (`components["schemas"]["TimelineEventType"]`), como
`ACTOR_TYPES` y `SEVERITIES` ya son constantes en `property-timeline.tsx:13-21`. Se acompaña de
una guardia **de tipos**, no solo de test:

```ts
type Missing = Exclude<TimelineEventType, (typeof TIMELINE_EVENT_TYPES)[number]>;
const _exhaustive: Missing extends never ? true : Missing = true;
```

Si el enum del backend crece, `tsc --noEmit` falla antes que cualquier test. Se borra
`optionsQuery` (`property-timeline.tsx:45-54`) y con ella una petición HTTP por render, y se
borra el literal crudo como respaldo: `t("timeline.eventType." + type, type)` pasa a
`t(...)` sin segundo argumento (R2.5).

**Las 46 etiquetas se levantan de `backend/app/timeline/domain/rendering.py`**
(`TIMELINE_TITLE_TEMPLATES`, ES y EN), con dos reglas de redacción que hay que decir aquí
porque el catálogo no las tiene:

1. Se quita el marcador **y la preposición que lo introduce** (R2.4). `RESERVATION_IMPORTED`
   es «Reserva importada desde {source}» → **«Reserva importada»**, no «Reserva importada
   desde»; `PROPERTY_STATE_CHANGED` es «Estado de la vivienda actualizado a {to_state}» →
   **«Estado de la vivienda actualizado»**. Son los dos únicos con sustitución
   (`rendering.py:60-66`).
2. Las **cinco** etiquetas que ya existen en `locales/{es,en}/dashboard.json` se **reescriben**
   con la redacción del catálogo, para que las 46 tengan un solo origen. Cambia copy visible:
   p. ej. ES `CHECKOUT_WINDOW_REACHED` pasa de «Hora de checkout alcanzada» a «Hora de salida
   alcanzada», y `PROPERTY_STATE_CHANGED` de «Cambio de estado» a «Estado de la vivienda
   actualizado». Resuelto en **OQ2**: se reescriben.

Guardia de i18n: test nuevo `features/dashboard/locales/dashboard-locale.test.ts` que exige
etiqueta para cada uno de los 46 en **los dos** ficheros — precedente exacto en
`features/properties/locales/properties-locale.test.ts` y
`features/reservations/locales/reservations-locale.test.ts`. La simetría es/en ya la fuerza
`frontend/lib/i18n/catalog-parity.test.ts`, que compara los conjuntos de claves por namespace.

Rejected: derivar de los datos (hoy) — solo ve la primera página, así que con paginación es
incorrecto por construcción.
Rejected: lista curada a mano — se podrirá cada vez que una capacidad gane escritor.
Rejected: solo test de runtime sobre la exhaustividad — falla más tarde y más lejos que el
compilador.

### D6 — Paginación con `page`/`perPage` en el DTO y los controles del precedente más reciente

**Chosen:** `TimelineFilters` (`data/dto.ts:110-116`) gana `page?: number` y `perPage?: number`;
`HttpDashboardSource.getPropertyTimeline` los mapea a `page` / `per_page` con el mismo patrón
condicional que ya usa para `event_type` y `actor_type`. `per_page` se **envía explícito a 20**
en lugar de confiar en el defecto del servidor, para que la clave de caché declare el tamaño de
página que describe. No se expone en la interfaz (R3.2). `hooks/query-keys.ts` **no cambia**:
`dashboardKeys.propertyTimeline` mete el objeto de filtros entero en la clave (R3.6).

Los controles copian el precedente más reciente, `features/properties/components/list/properties-view.tsx:252-280`:
`<nav aria-label>` que **solo se renderiza si `total_pages > 1`**, posición «página X de Y» por
clave interpolada, prev/next deshabilitados en los extremos y clase `tap-target` (mobile-first).
El propio `properties-web` dejó escrito el motivo del gate: una barra con dos flechas
permanentemente deshabilitadas es mobiliario muerto, y con 20 por página un timeline de dos
viviendas sembradas casi siempre cabe en una.

Cada página es una entrada de caché distinta y no se acumula nada en Zustand (R3.4,
`steering/frontend.md`: no duplicar server state en stores).

Rejected: scroll infinito acumulativo — acumular páginas en una clave duplica server state
fuera de TanStack Query.
Rejected: control de `per_page` en la UI — fuera de alcance por R3.2.

### D7 — El reset a la página 1 lo hace el **store**, no un efecto

**Chosen:** `page` se añade a `use-timeline-filters-store.ts` y **cada setter de filtro**
(`setActorType`, `setSeverity`, `setEventType`, `setRange`) escribe `page: 1` en la misma
mutación; solo `setPage` mueve la página. `reset()` vuelve a `page: 1`.

Hacerlo con un `useEffect` en el componente sería una carrera con dos peticiones: cambiar de
filtro con `page: 3` produce primero una consulta de la página 3 del filtro nuevo y solo
después el efecto la baja a 1. La invariante de R3.5 es de la transición, así que vive donde
ocurre la transición.

**Excepción descubierta en la comprobación de navegador de `/sdd:run` (2026-08-22): un borrador
de rango inverso no resetea la página.** `setRange` escribía `page: 1` sin condición, así que
volver el rango inverso **estando en la página 2** movía la clave de query aunque el par
comprometido no cambiara: la lista saltaba a la página 1 por detrás del mensaje de error, y en
caché fría eso es una petición — exactamente la «válida colateral» que D8 prohíbe. La regla
correcta es que el reset de página existe porque *cambió el conjunto de resultados*; si los
filtros comprometidos no se mueven, la página tampoco. En el caso inverso `setRange` no toca
nada más que el borrador.

No lo vieron ni los tests unitarios ni el panel de las secciones 3-5: todos los casos de rango
inverso partían ya de la página 1, donde el reset es un no-op. Cubierto ahora por dos tests de
regresión —uno de store y uno de componente— que arrancan en la página 2, y verificados en rojo
contra el comportamiento anterior.

### D8 — Rango de fechas: borrador en el store, se compromete solo si es válido, y se envía como instante local del día

**Chosen:** dos `<input type="date">` (precedente `features/reservations/components/list/reservations-filters.tsx:77-116`)
sobre un borrador `fromDate`/`toDate` en formato `YYYY-MM-DD` guardado en el store de filtros.
El par **comprometido** (`from`/`to` del DTO) se recalcula solo cuando el borrador es válido; si
es inverso, el comprometido no se toca.

**Dónde vive el par comprometido, anotado en `/sdd:run` (2026-08-22).** En el store de filtros,
junto al borrador — no derivado en el componente. La primera implementación lo guardaba en un
`useRef` que el render mutaba, y la regla de lint del propio proyecto la rechazó
(`react-hooks/refs`: «Cannot access refs during render»). No es una desviación de esta decisión
sino su consecuencia: «si es inverso, el comprometido **no se toca**» solo significa algo si el
par sobrevive al render en el que el borrador es inválido, así que hace falta estado persistente
y el `useRef` era la única forma de tenerlo fuera del store. Queda además coherente con D7: la
invariante «el par comprometido solo avanza desde un borrador válido» es de la transición
(`setRange`), igual que el reset a página 1, y vive donde ocurre la transición. Lo que
`steering/frontend.md` prohíbe guardar en Zustand es *server state* —las entradas del timeline,
que son de TanStack Query—, no los parámetros de la consulta, que es lo que `page`, `eventType` y
`actorType` ya son en este mismo store. Confirmado por el panel de arquitectura de la sección 5.

Dos conversiones, y las dos son requisito:

- **Zona horaria obligatoria (R4.2).** `<input type="date">` da una fecha *naive* y el dominio
  la rechaza con `422`: `backend/app/timeline/domain/repositories.py:73-78` lanza
  `TimelineFilterValidationError` si `tzinfo is None`, y `api/errors.py:30` la mapea a `422`.
  Se convierte con `Date#toISOString()`, que produce un instante con `Z`.
- **Extremos del día local (R4.4).** El rango es inclusivo en los dos extremos
  (`sdd/specs/dashboard-api.md:133-135`), así que `from` es el **inicio** del día local elegido
  y `to` el **final** (`23:59:59.999`). Mandar la medianoche local como `to` excluiría
  prácticamente todo el día que la operadora acaba de elegir. Se toma el día **local** y no el
  UTC porque la lista formatea los instantes en la zona del navegador
  (`features/dashboard/lib/format.ts`, `Intl` sin `timeZone`): pedir «el día 5» y ver entradas
  del 4 sería incoherente con lo que la propia pantalla pinta.

**Rango inverso (R4.3):** se compara el borrador en crudo (`toDate < fromDate`, comparación
lexicográfica válida sobre `YYYY-MM-DD`), se renderiza un error de campo localizado junto a los
inputs (`timeline.range.errorInverse`) y **no se emite petición**: al no actualizarse el par
comprometido, la clave de query no cambia, así que TanStack Query no dispara nada. Ni una
petición inválida, ni una petición «válida» colateral por haber vaciado el rango.

Helper nuevo `features/dashboard/lib/timeline-range.ts` con `startOfDayIso`, `endOfDayIso` e
`isInverseRange`, con test unitario propio: es la única aritmética de esta pantalla y es donde
está la trampa del `422`.

Rejected: mandar el rango y mapear el `422` — R4.3 lo prohíbe explícitamente.
Rejected: botón «Aplicar» — un control y dos strings más para el mismo resultado que el par
borrador/comprometido consigue aplicando al instante.
Rejected: `datetime-local` — pide hora que nadie ha pedido y no arregla la zona por sí solo.

### D9 — `MockDashboardSource` aprende a paginar

**Chosen:** `data/mock/mock-dashboard-source.ts:72-83` ya filtra y luego devuelve
`singlePage(filtered)`; se le añade el troceado por `page`/`perPage`. Es test-only (el punto de
composición devuelve HTTP sin condición, `data/index.ts:24-26`), pero dejarlo ignorando la
paginación permitiría que un test «demostrara» sobre él una paginación que el mock no hace.

### D10 — Los controles nuevos son locales al componente, no compartidos

**Chosen:** el selector, la barra de paginación y los campos de rango se declaran dentro de la
feature (`timeline-view.tsx` / `property-timeline.tsx`), sin extraer nada a `components/`. Es lo
que hace el repo: `properties-view.tsx` y `reservations-view.tsx` tienen cada uno su propia
navegación de páginas y no existe ninguna compartida. Extraer una tocaría dos features
archivadas y es una decisión de refactor que esta entrada no toma; queda anotada como deuda.

### D11 — `description` y `title` siguen siendo texto interpolado, y la audiencia no se mueve

**Chosen:** no entra `dangerouslySetInnerHTML`, ni `innerHTML`, ni renderizador de markdown
sobre `description` ni sobre `title`; se conserva la interpolación de
`property-timeline.tsx:147-152`, que React escapa (R6.1). `title` se pinta tal como llega, ya
compuesto por el catálogo del servidor, sin retraducir (R6.3).

**Verificado en el código, no asumido (R6.2):** `READ_PROPERTIES` la tienen exactamente
`TENANT_OWNER` (`backend/app/auth/domain/policy.py:266`, vía `_PROPERTY_READ`) y
`PROPERTY_MANAGER` (`:299`, vía `_PROPERTY_MANAGE`); `CLEANER` y `TECHNICIAN` reciben
`_SELF_SERVICE | _CLEANING_EXECUTE` y `_SELF_SERVICE | _INCIDENT_EXECUTE` (`:327`, `:330`) y no
la tienen. `/timeline` es del perfil `workspace` y esta entrada **no toca** `policy.py`: no
añade ni un lector, así que la decisión de publicar `description`
(`sdd/specs/dashboard-api.md:307-313`) no se reabre.

### D12 — Registro de rutas, su cerco y la shell no se tocan; solo se corrige una descripción

**Chosen:** cero cambios en `route-registry.ts`, `route-registry.test.ts`,
`route-metadata.test.ts`, `breadcrumbs.test.ts`, `select-routes.test.ts`, `match-route.test.ts`
y `bottom-navigation.tsx` (R5.4). El único cambio de shell es i18n:
`routes.timeline.description` en `locales/es/navigation.json` y `locales/en/navigation.json`,
que hoy prometen «todas las propiedades» / «across all properties» — el timeline global que
`sdd/specs/dashboard-api.md:40-41` prohíbe y `backend/openapi.json` no sirve. Nota de alcance:
`routeMetadata` resuelve la `description` de la ruta, así que esa corrección también arregla la
meta-descripción de la página, no solo el menú.

El `<h1>` de la pantalla usa `tNav("routes.timeline.title")`, como
`reservations-view.tsx:85-87`.

**Un fichero del cerco que esta decisión no enumeró, anotado en `/sdd:run` (2026-08-22).**
`frontend/app/route-coverage.test.ts` mantiene `REAL_PAGE_ROUTE_IDS`, el registro explícito de
páginas que han **graduado** de placeholder a implementadas, y falla si una página deja de llevar
`routeId=` sin aparecer ahí. Sustituir el `RoutePlaceholder` de `/timeline` es exactamente esa
graduación, así que hay que añadir `"(workspace)/timeline/page.tsx": "timeline"`. No está entre
los ficheros que R5.4 blinda —esos son los del registro de rutas y sus tests de navegación— y
tocarlo no reabre la decisión de ruta: el descriptor de `/timeline` no cambia, solo se declara que
su página ya es real. Lo destapó la suite completa, no el diff: ningún test de `features/` lo
cubre.

### D13 — Sin diagrama

**Chosen:** no se genera. Lo que hay que entender es «un componente, dos puntos de montaje» y
una regla de reset de página: dos frases que el documento ya dice. No hay máquina de estados,
ni secuencia con varios actores, ni topología nueva — y mirar un PNG cuesta ~140k de contexto
(shared rule 11).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Página | `frontend/app/(workspace)/timeline/page.tsx` | Sustituye `RoutePlaceholder` por `<TimelineView />`; conserva `generateMetadata` (D1) |
| Vista nueva | `frontend/features/dashboard/components/timeline/timeline-view.tsx` **(nuevo)** + `.test.tsx` **(nuevo)** | Selector por `useDashboardCards()`, estados carga/error/vacío, monta `PropertyTimeline` (D1, D3, D4) |
| Barrel | `frontend/features/dashboard/index.ts` | Exporta `TimelineView`; `PropertyTimeline` sigue interno (OQ1) |
| Timeline | `frontend/features/dashboard/components/detail/property-timeline.tsx` + `.test.tsx` | Borra `optionsQuery`, enum cerrado sin respaldo crudo, paginación, rango de fechas (D2, D5, D6, D8) |
| Store propiedad | `frontend/features/dashboard/state/use-timeline-property-store.ts` **(nuevo)** + `.test.ts` **(nuevo)** | Par `{tenantId, propertyId}` en memoria (D3) |
| Store filtros | `frontend/features/dashboard/state/use-timeline-filters-store.ts` + `.test.ts` **(nuevo)** | Añade `page`, el borrador `fromDate`/`toDate` y el par comprometido `from`/`to`; cada setter de filtro resetea a página 1 (D7, D8) |
| Enum | `frontend/features/dashboard/lib/timeline-event-types.ts` **(nuevo)** + `.test.ts` **(nuevo)** | 46 valores tipados desde el contrato + guardia de exhaustividad (D5) |
| Rango | `frontend/features/dashboard/lib/timeline-range.ts` **(nuevo)** + `.test.ts` **(nuevo)** | `startOfDayIso`, `endOfDayIso`, `isInverseRange` (D8) |
| DTO | `frontend/features/dashboard/data/dto.ts` | `TimelineFilters` += `page?`, `perPage?` (D6) |
| Mapper HTTP | `frontend/features/dashboard/data/http/http-dashboard-source.ts` + `.test.ts` | `page` / `per_page` en el query (D6) |
| Mock | `frontend/features/dashboard/data/mock/mock-dashboard-source.ts` + `.test.ts` | Trocea por página (D9) |
| i18n dashboard | `frontend/locales/{es,en}/dashboard.json` | 46 `timeline.eventType.*` (41 nuevas, 5 reescritas), `timeline.picker.*`, `timeline.pagination.*`, `timeline.range.*` (D5, D6, D8) |
| i18n navegación | `frontend/locales/{es,en}/navigation.json` | Reescribe `routes.timeline.description` (D12) |
| Cerco de rutas | `frontend/app/route-coverage.test.ts` | Añade `timeline` al registro `REAL_PAGE_ROUTE_IDS` de páginas graduadas — no lo previó D12, lo descubrió la suite completa en `/sdd:run` (ver nota) |
| Test i18n | `frontend/features/dashboard/locales/dashboard-locale.test.ts` **(nuevo)** | Etiqueta para los 46 tipos en ambos locales (D5) |
| **Sin tocar** | `route-registry.ts` y su cerco, `bottom-navigation.tsx`, `hooks/query-keys.ts`, `hooks/use-dashboard-data.ts`, `dashboard-source.ts`, `property-detail-view.tsx`, `backend/**` | R3.6, R5.4, D2, D11 |

## Data & interfaces

- **Backend**: ningún cambio. Ni endpoint, ni schema, ni permiso, ni migración, ni `openapi.json`.
- **Tipos generados**: ninguna regeneración. `frontend/lib/api/generated/openapi.d.ts` ya
  declara el path, la operación con sus siete parámetros, el enum de 46 valores y
  `TimelinePageResponse`. (Relevante porque `cd frontend && npm run api:check` no funciona tal
  cual en un worktree enlazado — `sdd/project.md`; aquí no hace falta correrlo.)
- **`DashboardDataSource`**: la firma no cambia. `getPropertyTimeline(tenantId, propertyId,
  filters?)` sigue igual; los dos campos nuevos son opcionales dentro de `TimelineFilters`.
- **Claves de query**: sin cambios de forma. `['tenant', tenantId, 'property-timeline',
  propertyId, filters]` absorbe `page`/`perPage`/`from`/`to` porque el objeto entero es parte de
  la clave. Consecuencia buscada: cada página y cada rango son entradas distintas.
- **Contrato de wire nuevo que esta pantalla empieza a usar**: `page` (int ≥1),
  `per_page` (fijo 20), `from` / `to` (ISO-8601 **con zona**).
- **i18n**: namespace `dashboard` (claves de pantalla y las 46 etiquetas) y `navigation`
  (descripción de la ruta). Ninguna string nueva fuera de `locales/`.
- **Config / env vars**: ninguna.

## Risks & mitigations

- **El selector solo verá 20 viviendas.** `useDashboardCards()` no manda parámetros y
  `GET /api/v1/dashboard/properties` sirve `per_page = 20` por defecto
  (`backend/app/dashboard/api/router.py:88-89`). Con dos viviendas sembradas es teórico, y
  `/dashboard` tiene hoy exactamente el mismo techo sin paginación. **Mitigación:** aceptado y
  documentado; R1.1 ata las opciones a lo que el hook devuelve. Resuelto en **OQ3**.
- **Selección viva tras cambiar de tenant en la misma pestaña.** `logout` no limpia stores ni
  caché (`lib/auth/auth-provider.tsx:107-120`). **Mitigación:** el par con `tenantId` de D3.
  Nota aparte: la caché de TanStack tampoco se vacía al salir, pero sus claves están acotadas
  por tenant (`lib/query/query-keys.ts` → `tenantScopedKey`), así que nada ajeno es legible;
  es preexistente y fuera de alcance aquí.
- **19 de los 46 tipos no tienen escritor de producción** (los ocho de limpieza incluidos: la
  limpieza aparece como `PROPERTY_STATE_CHANGED`, no como `CLEANING_COMPLETED`). Filtrar por
  ellos devuelve vacío. **Mitigación:** R2.6 lo declara respuesta correcta; el `EmptyState` ya
  existe y el test lo fija. Esta entrada no da escritor a ninguno — `TECHNICIAN_EN_ROUTE` es de
  `tech-cycle-completion` (`sdd/specs/maintenance.md:400-401`).
- **Cambia copy visible en `/properties/[id]`** al reescribir las cinco etiquetas existentes
  (D5.2). **Mitigación:** decidido y aceptado en el gate (OQ2); el cambio de copy es intencionado y
  queda enumerado ahí para que review no lo lea como una regresión.
- **41 × 2 etiquetas es trabajo mecánico y por tanto propenso a un hueco silencioso.**
  **Mitigación:** tres guardias encadenadas — la de tipos (D5) si el enum crece, el test de
  locale nuevo si falta una etiqueta, y `catalog-parity.test.ts` si es/en divergen. El panel
  `sdd-review-i18n` lo verifica además en review.
- **La aritmética del rango es donde está el `422`.** **Mitigación:** helper aislado con test
  unitario (D8) en vez de conversiones dispersas por el JSX.
- **La suite en un worktree enlazado da 2 ficheros en rojo ajenos al change**
  (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`).
  **Mitigación:** el juego de `docker compose cp` que documenta `sdd/project.md` §Worktree
  bootstrap; sin él la cifra de la suite no es interpretable.
- **`sdd/specs/dashboard-api.md` dice «45 valores» en las líneas 156 y 328 y el enum publicado
  tiene 46** (`GUEST_CHECKIN_COMPLETED` llegó con `guest-portal-api`). No es riesgo de
  implementación: es una corrección de spec que le toca a `/sdd:archive`, y esta entrada la deja
  anotada porque es la que enumera los 46.
- **`docs/dashboard.md` queda desactualizado y su puesta al día es de `/sdd:archive`.** Lo levantó
  el panel de documentación de la sección 6 en `/sdd:run`; se anota aquí, y no se arregla aquí,
  porque `steering/documentation.md` pone esa obligación explícitamente **«al archivar»** (su
  frontmatter es `phases: [tasks, archive]` y tiene su propio «Checklist de archivado»). Tres cosas
  concretas, verificadas contra el fichero:
  1. **Línea 94 pasa a ser falsa**: «las opciones de tipo se derivan de los eventos que tiene esa
     propiedad». D5 la sustituye por el enum cerrado de 46 valores. Es el único sitio del árbol
     —fuera de `sdd/`— que afirma la derivación; comprobado con un grep de «se derivan» sobre
     `docs/` y el README.
  2. **§ «Rutas de la pantalla» (líneas 61-69) no lista `/timeline`**: enumera solo `/dashboard` y
     `/properties/[id]`. Ahora la cronología tiene dos puntos de montaje y el segundo es una ruta
     propia.
  3. **§ «Cronología» no menciona la paginación ni el rango de fechas**, que son controles nuevos
     de cara al operador (20 por página, barra solo con `total_pages > 1`, rango inclusivo en los
     dos extremos y error de campo si es inverso).
  El resto de menciones a «placeholder» o a «todas las propiedades» que quedan en el árbol están
  en `sdd/` (roadmap y documentos de este mismo change), y las cierra el propio archivado al
  ticar la entrada.

## Open questions

Las tres se resolvieron en el gate de `/sdd:design` (2026-08-22, Jose). Se conservan con su
respuesta porque cada una cierra una alternativa que un revisor podría reabrir.

**OQ1 — ¿Qué exporta el barrel y qué importa la página?** → **Solo `TimelineView`.**
`PropertyTimeline` sigue siendo interno de la feature. Cumple lo que R5.2 protege —la página
importa del barrel, nunca de una ruta interna— y evita una exportación pública que nadie
importa. **Consecuencia para `/sdd:tasks`: la redacción de R5.2 se enmienda** para decir
`TimelineView` en lugar de `PropertyTimeline`; su segunda mitad («y la página SHALL importarlo
del barrel de la feature y nunca de una ruta interna») se conserva literal.
Rechazado: exportar los dos, cumpliendo la letra de R5.2 a costa de API muerta.

**OQ2 — ¿Se reescriben las cinco etiquetas de tipo que ya existen?** → **Sí: las 46 se derivan
del catálogo del servidor.** Un solo origen de redacción, coherente con los títulos que se
pintan justo debajo. Cambia copy hoy visible en `/properties/[id]`: ES `CHECKOUT_WINDOW_REACHED`
«Hora de checkout alcanzada» → «Hora de salida alcanzada», `PROPERTY_STATE_CHANGED` «Cambio de
estado» → «Estado de la vivienda actualizado» (y sus equivalentes EN).
Rechazado: conservar las cinco — dos procedencias de redacción en el mismo desplegable.

**OQ3 — ¿Se acepta el techo de 20 viviendas del selector?** → **Sí, aceptado y documentado.** Es
lo que R1.1 describe y el mismo techo que `/dashboard` ya tiene; con dos viviendas sembradas es
teórico. `useDashboardCards()` **no** gana parámetros.
Rechazado: `perPage` opcional en el hook — amplía la firma de un hook compartido y añade una
petición con clave distinta de la del grid.
