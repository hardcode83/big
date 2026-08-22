# timeline-web

[FE] **la pantalla `/timeline`, que hoy es un placeholder sobre un backend entregado**: `frontend/app/(workspace)/timeline/page.tsx:11` renderiza `RoutePlaceholder routeId="timeline"` mientras `GET /api/v1/timeline/{property_id}` está en producción desde `dashboard-api` (archivada el 2026-08-09) y el frontend **ya lo llama**.

## Antes de nada: el timeline YA se pinta, y eso cambia la entrada de raíz

Verificado contra el código el 2026-08-22. Esta entrada **no construye un timeline**, porque ya existe uno completo y conectado a HTTP real:

- `frontend/features/dashboard/components/detail/property-timeline.tsx` (156 líneas) es un componente `PropertyTimeline` funcional con filtros por tipo, actor y severidad, estados de carga/error/vacío y formateo de fecha por locale.
- Lo monta `PropertyDetailView` (`property-detail-view.tsx:10` y `:54`), es decir **la pantalla `/properties/[id]` ya muestra el timeline de la propiedad**.
- Y lo hace contra el endpoint real, no contra un mock: `HttpDashboardSource.getPropertyTimeline` (`data/http/http-dashboard-source.ts:177-201`) pide `"/api/v1/timeline/{property_id}"` con `event_type`, `severity`, `actor_type`, `from` y `to`, y el punto de composición devuelve la implementación HTTP sin condición (`data/index.ts:24-26`). `MockDashboardSource` sobrevive solo para tests.
- La costura de datos está entera: `usePropertyTimeline` con TanStack Query (`hooks/use-dashboard-data.ts:65-80`), clave por tenant+propiedad+filtros (`hooks/query-keys.ts:15-20`) y un store Zustand de filtros (`state/use-timeline-filters-store.ts`).

Corolario, y es el eje de toda la nota: **el trabajo no es escribir una pantalla, es decidir qué hace `/timeline` sin duplicar la que ya hay, y terminar el componente que ya existe contra el contrato congelado.**

## La tensión central, y su decisión cerrada

El endpoint **exige una propiedad** (`backend/app/timeline/api/router.py:66-67`: `@router.get("/{property_id}")` bajo `prefix="/timeline"`). La ruta registrada, en cambio, es plana: `route-registry.ts:91-98` declara `id: "timeline"`, `pattern: "/timeline"`, `href: "/timeline"`, `match: "exact"`, `navigationGroup: "operation"`, `order: 2`. El menú lleva a una pantalla que no sabe de qué propiedad pedir datos.

**Decisión: opción (a)** — `/timeline` conserva su ruta plana y monta un **selector de propiedad** encima del `PropertyTimeline` que ya existe. Cinco reglas, todas cerradas, ninguna a debate:

1. **Un solo componente de timeline, dos puntos de montaje.** La página **importa** `PropertyTimeline` y le pasa el `propertyId` elegido. No se escribe una segunda lista de eventos, ni un segundo hook, ni un segundo store. Todo lo que esta entrada añade (paginación, rango de fechas, vocabulario completo de tipos) entra **dentro** de ese componente, así que la sección de `/properties/[id]` lo hereda sin tocarla. Es exactamente lo que hace que esto **no** duplique pantalla: duplica punto de montaje, no interfaz.
2. **Antes de elegir no se pide nada.** El selector arranca vacío y el cuerpo muestra `EmptyState` con copy propio («elige una vivienda»). **No hay autoselección de «la primera propiedad»**: con N viviendas cualquier elección automática es arbitraria, leer el feed de la vivienda equivocada es peor que un clic, y así el primer pintado no dispara ninguna petición de timeline.
3. **La elección se recuerda en memoria, no en disco.** Store Zustand nuevo, hermano de `use-timeline-filters-store.ts` (`steering/frontend.md:13`: Zustand solo para estado ligero de UI). **Ni `localStorage` ni cookie**: un `property_id` es un identificador de tenant y el almacenamiento del navegador no está acotado por tenant, así que tras un login como otro tenant sería un id ajeno y muerto que dispararía un `404`. Ir a la propiedad y volver conserva la elección; un recargado la pierde y cuesta un clic.
4. **Las opciones del selector salen de `useDashboardCards()`** (`hooks/use-dashboard-data.ts:42-51`), que ya devuelve `propertyCode` por card. **Cero endpoints nuevos, cero métodos nuevos en `DashboardDataSource`.** El `boundary.test.ts` de la feature sigue vigilando que nada importe fixtures del mock, así que el selector va por el hook y no por `data/mock/`.
5. **Cambiar de propiedad resetea los filtros**, que es lo que `property-timeline.tsx:43` ya hace con `useEffect(() => reset(), [propertyId, reset])`. La regla se conserva, no se reinventa.

### Por qué NO la opción (c) — «retirar `/timeline` de la navegación»

Era la candidata natural en cuanto se descubre que el timeline ya vive en el detalle de propiedad, y **es impracticable**: `/timeline` no es una entrada suelta del registro, es una superficie del PRD §24 cercada por cuatro sitios distintos.

- `route-registry.test.ts:10-34` mantiene `PRD_24_SURFACES` como *«independent list for coverage»* del PRD e incluye `"/timeline"` (línea 16); el test de `:61-64` compara el registro con esa lista y se llama literalmente *«covers exactly the PRD §24 surfaces (no more, no less)»*.
- `select-routes.test.ts:34-46` fija el grupo `operation` en exactamente `["dashboard", "timeline", "properties"]`.
- `match-route.test.ts:44` fija que `/timeline/?x=1` resuelve al id `timeline`.
- `frontend/features/shell/components/bottom-navigation.tsx:17-22` la hace **una de las cuatro** destinaciones directas de la navegación móvil, por diseño D6.

Retirarla no es borrar una línea: es **enmendar el PRD §24 y un diseño archivado**, decisión de producto que una entrada `[FE]` no puede tomar por su cuenta — y en modo AUTO es precisamente la ambigüedad que bloquea.

### Por qué NO la opción (b) — «índice `/timeline` + detalle `/timeline/[id]`»

Rompe el mismo cerco por el otro lado: **añade** una superficie que PRD §24 no declara (`/timeline/[id]`), así que obliga a editar la lista de `route-registry.test.ts` igual que (c). Y encima su índice sería una segunda lista de propiedades al lado de `/properties` mientras `/timeline/[id]` sería una copia literal de la sección que `/properties/[id]` ya pinta: **esa sí es la duplicación real de pantalla**, dos veces.

## Alcance, y lo que queda deliberadamente fuera

**Dentro**: el selector de propiedad y la página que lo monta; **paginación real**; **rango de fechas**; el **vocabulario completo** de tipos de evento en el filtro; el export de `PropertyTimeline` desde el barrel de la feature; cada string nuevo en los dos locales; y la corrección de la descripción i18n de la ruta, que hoy miente (ver «Trabajo de shell»).

**Fuera, y cada una por una razón verificada**:

- **El timeline global.** `GET /api/v1/timeline` de PRD §23:1951 **no existe** (`backend/openapi.json` no tiene ese path) y `sdd/specs/dashboard-api.md:40-41` lo prohíbe con un `SHALL NOT` explícito: *«esta capacidad acota a la variante por propiedad»*. Una pantalla «todas las viviendas a la vez» no es implementable aquí y no se intenta.
- **Realtime.** `sdd/specs/dashboard-api.md:306-308`: PRD §9.2 dice «timeline en tiempo real» y lo entregado es lectura con filtros y paginación; WebSocket/SSE no está entregado por ninguna mitad. Nada de polling agresivo tampoco: eso es una decisión de producto con su propio coste.
- **Cualquier escritura.** No hay escritor en el módulo y no lo va a haber: `backend/app/timeline/api/router.py:10-11` lo dice — *«There is no writer here and there will not be one: events are appended by the use case that caused them, which is what keeps the timeline a record»*.
- **`metadata`.** Jamás se serializa: falta en `TimelineEntryResponse` (`api/schemas.py:26-43`) **y** en la proyección de dominio, y `sdd/specs/dashboard-api.md:138-143` llama a la ausencia «estructural». No hay nada que pintar ni que ir a buscar.
- **Resolver los tipos de evento huérfanos.** Es trabajo de backend y ya tiene dueño en el roadmap (`tech-cycle-completion` para «en ruta»). Ver la sección del vocabulario.

## Por qué depende de lo que depende

- **`needs: dashboard-api`** — es quien entregó `GET /api/v1/timeline/{property_id}` con su capa `api/` entera. Archivada el 2026-08-09 (`roadmap.md:127` → `changes/archive/2026-08-09-dashboard-api/`).
- **`needs: dashboard-web`** — es quien entregó los ficheros que esta entrada modifica: `HttpDashboardSource`, el punto de composición y el `PropertyTimeline` conectado. Archivada el 2026-08-11 (`roadmap.md:129` → `changes/archive/2026-08-11-dashboard-web/`). Es el mismo patrón que `cleaning-manager-view`, que declara `needs: cleaning, dashboard-web` (`roadmap.md:138`).

**No declara `frontend-auth-session`** aunque el endpoint sea del tenant autenticado: la absorbe `dashboard-web`, que ya la declara (`roadmap.md:130`: `needs: dashboard-api, frontend-auth-session`). Es la misma poda que hizo `reservations-web` con `api-ingress-routing`. Ambas dependencias están archivadas, así que la entrada es atacable hoy.

## El contrato está congelado y el cliente tipado ya lo conoce

No hay nada que negociar al llegar, y esto es lo que sostiene la talla:

- **Ruta y permiso** — `GET /api/v1/timeline/{property_id}`, `Permission.READ_PROPERTIES` (`api/router.py:63`).
- **Parámetros** (`api/router.py:89-95`): `page` (≥1, ≤`MAX_PAGE` = 100 000), `per_page` (1..`MAX_PER_PAGE` = 100, por defecto **20**), `event_type`, `severity`, `actor_type`, y el rango con los nombres de contrato **`from` / `to`** (en Python llegan como `occurred_from`/`occurred_to` por alias, porque `from` es palabra reservada). Los cinco filtros combinan con **AND** y el rango es **inclusivo en los dos extremos** (`sdd/specs/dashboard-api.md:133-135`).
- **Sobre de respuesta** — `TimelinePageResponse` (`api/schemas.py:58-65`): `{data, total, page, per_page, total_pages}`. Es **el mismo sobre plano de PRD §23** que ya usa el resto de la API; **no** hay `meta` anidado. `total` cuenta el conjunto **filtrado**, no todos los eventos de la vivienda (`sdd/specs/dashboard-api.md:144-146`).
- **Forma de la entrada** — `TimelineEntryResponse` (`api/schemas.py:26-43`): exactamente `id`, `occurred_at`, `actor_type`, `event_type`, `severity`, `title`, `description` (anulable). Nada más.
- **`title` llega ya traducido, `description` no.** El backend compone el título al leer, contra un catálogo de 46 tipos × 2 idiomas en `backend/app/timeline/domain/rendering.py:70-265`, en el idioma de `preferred_language` del usuario (`sdd/specs/dashboard-api.md:151-158`). `description` es texto de operador y vuelve **verbatim** en el idioma en que se tecleó. **El frontend no traduce títulos**: eso ya está hecho, y volver a hacerlo sería una segunda fuente de verdad.
- **Orden** — instante descendente con desempate determinista por `id`, para que paginar no repita ni omita (`sdd/specs/dashboard-api.md:128-132`). El cliente no reordena.
- **Tipos** — `frontend/lib/api/generated/openapi.d.ts:612-617` declara el path y `:6831` la operación con sus siete parámetros; `:3172` es el enum `TimelineEventType` completo y `:3177` el sobre. El fichero se genera desde `backend/openapi.json` y la CI lo verifica, así que **no hay tipos que escribir ni nada que regenerar**. `lib/api/client.test.ts:50-60` incluso usa esta ruta como caso de prueba del cliente tipado, con `page=1` en el query.

**Los dos únicos huecos de la capa de datos**, y son pequeños: `TimelineFilters` (`data/dto.ts:110-116`) y `HttpDashboardSource.getPropertyTimeline` (`:177-201`) **no pasan `page` ni `per_page`** — hoy se come siempre el defecto del servidor. Hay que añadirlos al DTO en camelCase y mapearlos a snake_case en el wire, como el mapper ya hace con `event_type`/`actor_type`. La clave de query los absorbe sola, porque `dashboardKeys.propertyTimeline` mete el objeto de filtros entero en la clave (`hooks/query-keys.ts:15-20`): **no hay que tocar `query-keys.ts`**. Decisión cerrada: **`per_page` se fija a 20 y no se expone en la UI**; solo se navega `page`, con `total_pages` que ya viene en el sobre.

## El vocabulario de `TimelineEventType`: 46 valores, 41 sin etiqueta, 19 sin escritor

`backend/app/timeline/domain/enums.py:20-72` declara **46** valores (`backend/openapi.json` confirma 46 en el enum publicado; la spec `dashboard-api.md:156` todavía dice «45» porque `GUEST_CHECKIN_COMPLETED` llegó después con `guest-portal-api`). En los locales del frontend hay **cinco**: `locales/{es,en}/dashboard.json:74` solo tiene `timeline.eventType` para `ACCESS_CODE_DELIVERED`, `CHECKOUT_WINDOW_REACHED`, `CLEANING_TASK_CREATED`, `GUEST_MESSAGE_RECEIVED` y `PROPERTY_STATE_CHANGED`. **Faltan 41 × 2 idiomas, y eso es el grueso del trabajo de i18n de esta entrada.**

Faltan: `RESERVATION_IMPORTED`, `RESERVATION_CREATED_MANUAL`, `RESERVATION_UPDATED`, `RESERVATION_CANCELLED`, `CHECKIN_WINDOW_OPENED`, `ACCESS_CODE_PENDING`, `ACCESS_CODE_CREATED_EXTERNAL`, `ACCESS_CODE_MANUAL_ADDED`, `AI_RESPONSE_SENT`, `AI_ESCALATED_TO_HUMAN`, `HUMAN_RESPONSE_SENT`, `CLEANER_ASSIGNED`, `CLEANER_ACCEPTED`, `CLEANER_REJECTED`, `CLEANING_STARTED`, `CLEANING_PHOTO_UPLOADED`, `CLEANING_COMPLETED`, `CLEANING_FAILED_VALIDATION`, `INCIDENT_CREATED`, `INCIDENT_CLASSIFIED`, `TECHNICIAN_ASSIGNED`, `TECHNICIAN_ACCEPTED`, `TECHNICIAN_EN_ROUTE`, `TECHNICIAN_STARTED`, `INCIDENT_RESOLVED`, `INCIDENT_CANCELLED`, `OWNER_APPROVAL_REQUIRED`, `OWNER_APPROVED_EXPENSE`, `OWNER_REJECTED_EXPENSE`, `LOCK_ALERT_RECEIVED`, `PRICE_RECOMMENDATION_CREATED`, `PRICE_UPDATED_EXTERNAL`, `LEGAL_REGISTRATION_SUBMITTED`, `REVIEW_IMPORTED`, `REVIEW_RESPONSE_DRAFTED`, `REVIEW_RESPONSE_APPROVED`, `SLA_BREACH_WARNING`, `NOTIFICATION_SENT`, `NOTIFICATION_FAILED`, `WEBHOOK_RECEIVED`, `GUEST_CHECKIN_COMPLETED`.

**No hay que inventar la redacción: se levanta de `rendering.py:70-265`**, que ya tiene las 46 en ES y EN. Dos excepciones: `RESERVATION_IMPORTED` y `PROPERTY_STATE_CHANGED` llevan marcador (`{source}`, `{to_state}`, los dos únicos con sustitución autorizada — `rendering.py:284-288`), y **una etiqueta de filtro no puede llevar marcador**: se escriben sin él.

**El bug que hay que eliminar, no arrastrar**: hoy la lista de opciones del desplegable se **deriva de los datos**. `property-timeline.tsx:47-51` lanza una **segunda consulta** con filtros vacíos solo para cosechar los `eventType` presentes, y `:82` pinta `t("timeline.eventType." + type, type)` (una template string) con el literal crudo como fallback — por eso las 41 etiquetas ausentes no se notan: se ve `CLEANING_COMPLETED` en pantalla. Esa derivación es **incorrecta en cuanto exista paginación**, porque solo ve la primera página. **Decisión: el desplegable ofrece el enum cerrado de 46 valores** (`openapi.d.ts:3172`, exactamente como `ACTOR_TYPES` y `SEVERITIES` ya son constantes en `:13-21`), y `optionsQuery` **se borra** — lo que además quita una petición por render de la sección. Se ofrecen los 46 aunque algunos no devuelvan nada: el enum es el contrato publicado, una opción vacía es honesta y el estado vacío ya lo dice (`timeline.empty`), mientras que una lista curada a mano se podriría cada vez que una capacidad gane escritor.

**19 de los 46 no tienen escritor de producción** (comprobado grepeando cada `TimelineEventType.X` fuera de `enums.py` y `rendering.py`): `CHECKIN_WINDOW_OPENED`, `CHECKOUT_WINDOW_REACHED`, `CLEANING_TASK_CREATED`, `CLEANER_ASSIGNED`, `CLEANER_ACCEPTED`, `CLEANER_REJECTED`, `CLEANING_STARTED`, `CLEANING_PHOTO_UPLOADED`, `CLEANING_COMPLETED`, `CLEANING_FAILED_VALIDATION`, `TECHNICIAN_EN_ROUTE`, `LOCK_ALERT_RECEIVED`, `REVIEW_IMPORTED`, `REVIEW_RESPONSE_DRAFTED`, `REVIEW_RESPONSE_APPROVED`, `SLA_BREACH_WARNING`, `NOTIFICATION_SENT`, `NOTIFICATION_FAILED`, `WEBHOOK_RECEIVED`.

Dos observaciones que ahorran una investigación entera a quien diseñe:

1. **Los ocho de limpieza son huérfanos aunque `cleaning` esté entregada.** `TimelineEventFactory` tiene **un solo** método de fábrica, `property_state_changed` (`backend/app/timeline/domain/services.py`), y `app/cleaning/application/use_cases.py` escribe por ahí. O sea: **la limpieza aparece en el timeline como `PROPERTY_STATE_CHANGED`, no como `CLEANING_COMPLETED`.** Filtrar por «limpieza completada» devolverá vacío, y no es un fallo de la pantalla.
2. **`TECHNICIAN_EN_ROUTE` es huérfano declarado y ya tiene dueño.** `sdd/specs/maintenance.md:400-401`: *«existe y nadie lo escribe: no hay transición "en ruta" en el ciclo entregado»*, y `roadmap.md:149` (`tech-cycle-completion`) se encarga de decidir si es estado nuevo o si se retira. `sdd/specs/timeline-state-machine.md:174-183` documenta el patrón general: los cuatro de mensajería ganaron escritor el 2026-08-16 y los dos de pricing el 2026-08-18, «hasta entonces el enum los declaraba sin que nadie los escribiera». **Esta entrada no arregla ninguno**; solo tiene que no romperse cuando el filtro devuelve una página vacía.

## Texto libre y PII: lo único de esta entrada que no es rutinario

- **`title` es seguro por construcción**: lo compone el catálogo del servidor, y la interpolación está acotada a una lista blanca **por tipo de evento** de escalares de hasta 200 caracteres (`rendering.py:284-288` y `:320-334`). Además, los eventos que vienen de un mensaje de huésped llevan **título constante** por diseño: `sdd/specs/timeline-state-machine.md:189-192` lo razona porque `timeline_events` es append-only y una palabra del huésped no podría redactarse después.
- **`description` sí es texto libre de operador.** `sdd/specs/dashboard-api.md:309-314`: *«es el primer campo de texto libre que esta capacidad publica… no está entre las columnas enumeradas como sumideros de texto en claro, pero es de la misma clase»*. `sdd/steering/security.md` documenta esa clase repetidamente y su conclusión invariable: la columna **no es un sitio seguro para PII** y lo que una persona teclee ahí se le enseña al operador tal cual.
  **Obligación concreta, y es una sola**: se renderiza **como texto y nunca como HTML**. Hoy ya se hace bien (`property-timeline.tsx:148-151` interpola `{entry.description}`, que React escapa). La regla es que al enriquecer el estilo de la entrada **no entre** `dangerouslySetInnerHTML`, ni markdown, ni `innerHTML`: es el único camino por el que este change podría introducir un XSS almacenado sobre una tabla append-only.
- **La audiencia no se ensancha, y no puede ensancharse.** La decisión de publicar `description` se tomó a sabiendas porque hoy no hay cruce de privilegio (`sdd/specs/dashboard-api.md:311-314`, con el aviso de que *«el primer rol de sólo-auditoría que se añada obliga a revisarla»*). El endpoint exige `READ_PROPERTIES` (`api/router.py:63`) y solo la tienen `TENANT_OWNER` y `PROPERTY_MANAGER` (`backend/app/auth/domain/policy.py`, vía `_PROPERTY_READ` / `_PROPERTY_MANAGE`; `CLEANER` y `TECHNICIAN` **no**), que son exactamente los lectores que ya veían la sección en `/properties/[id]`. La ruta es del perfil `workspace`, así que **`/timeline` no añade ni un lector** — y esta entrada **no debe** añadir ningún rol, porque eso sí reabriría esa decisión.

## Riesgos que no son rutinarios

- **El rango de fechas se rechaza con `422` por dos motivos distintos.** `sdd/specs/dashboard-api.md:136-137`: si el rango es inverso (`to` anterior a `from`) **o alguno de sus extremos llega sin zona horaria**, la respuesta es `422`. Un `<input type="date">` produce una fecha **naive**, así que enviarla en crudo es un `422` garantizado: hay que convertirla a instante con zona antes de mandarla. Y el rango inverso hay que **validarlo en el cliente** antes de disparar, para que el operador vea un error de campo y no el estado de error genérico. Estas dos son las trampas reales de la entrada.
- **La política de reintentos ya distingue el `404`.** `retryPolicy` (`hooks/use-dashboard-data.ts:35-40`) no reintenta 4xx a propósito. Importa aquí porque una propiedad de otro tenant responde **`404` indistinguible de una inexistente** (`api/router.py` en su descripción, y `sdd/specs/dashboard-api.md:147-148`): si la elección de propiedad se rehidratara de un sitio persistente, el síntoma sería un 404 mudo. Es la razón operativa de la regla 3 de la decisión.
- **La paginación cambia el significado de la clave de caché.** Al meter `page` en `TimelineFilters`, cada página es una entrada de caché distinta; hay que decidir explícitamente que se navega por páginas (no scroll infinito acumulativo), porque acumular páginas en una sola clave duplicaría el server state fuera de TanStack Query, que es lo que `steering/frontend.md:13` prohíbe.

## Precedente que hay que seguir, no reinventar

`dashboard-web` (archivada el 2026-08-11) ya dejó montada la costura completa y **la frontera está vigilada por tests**: `data/boundary.test.ts` prohíbe que cualquier componente, hook, store o lib de la feature importe el mock o sus fixtures —el único fichero exento es `data/index.ts`—, y `hooks/import-boundary.test.ts` repite la guardia en la capa de hooks. Todo lo que añada esta entrada cae dentro de ese cerco: el selector va por `useDashboardCards`, no por `data/mock/fixtures.ts`.

De `sdd/steering/frontend.md` aplican sin excepción: server state con **TanStack Query v5 con clave por recurso+tenant** (ya la hay: `tenantScopedKey` en `hooks/query-keys.ts`), **Zustand solo para estado ligero de UI** (los filtros ya lo son; la propiedad seleccionada también), y **cada string en `locales/es` y `locales/en`**, nada hardcodeado — incluidas las 41 etiquetas de tipo, las del selector, las del rango de fechas, las de paginación y el copy del estado «elige una vivienda». El panel `sdd-review-i18n` verifica exactamente eso, así que una clave a medias sale en rojo.

## Trabajo de shell y de registro de rutas: casi ninguno, y ese es el punto

Es la consecuencia directa de haber elegido la opción (a), y es la mitad del argumento de la talla.

- **La ruta ya está registrada** y navegable (`route-registry.ts:91-98`) y **sus claves i18n ya existen** en los dos locales (`locales/es/navigation.json:13`, `locales/en/navigation.json:13`). **No hay ruta que dar de alta**, así que no hay que imitar el descriptor sin `href` ni `navigationGroup` de `property-detail` (`route-registry.ts:115-119`) — que sería el precedente si esta entrada hubiera necesitado una ruta de detalle, y no la necesita.
- **No se toca ningún cerco de navegación**: `route-registry.test.ts`, `route-metadata.test.ts`, `breadcrumbs.test.ts`, `select-routes.test.ts`, `match-route.test.ts` ni `bottom-navigation.tsx` cambian. Si un diff los toca, la decisión se ha derivado mal.
- **Sí hay que exportar `PropertyTimeline`** desde `features/dashboard/index.ts`, que hoy solo exporta `DashboardView` y `PropertyDetailView` (líneas 1-2). La convención está demostrada en `app/(workspace)/properties/[id]/page.tsx:3`: la página importa del barrel de la feature, nunca de una ruta interna.
- **Y hay una string que hoy miente y hay que corregir**: `routes.timeline.description` promete *«Historial de eventos operativos de **todas las propiedades**»* / *«Operational event history **across all properties**»*. Eso describe el timeline global que `sdd/specs/dashboard-api.md:40-41` prohíbe y que `backend/openapi.json` no sirve. Se reescribe en **los dos locales** para decir la verdad —una vivienda a la vez— porque dejarla es prometer desde el menú una pantalla que no existe.
- El `page.tsx` de `/timeline` conserva su `generateMetadata` con `routeMetadata("timeline")` (`app/(workspace)/timeline/page.tsx:6-8`); lo único que se sustituye es el `RoutePlaceholder` de la línea 11.

## Metadatos propuestos

`needs: dashboard-api, dashboard-web · size: S · kind: feature`

**Por qué `S`**: no hay endpoint nuevo, ni método nuevo en `DashboardDataSource`, ni DTO nuevo, ni ruta que registrar, ni cerco de tests que enmendar, ni tipos que generar. El componente de timeline, su store de filtros, su clave de query y su mapper HTTP existen y ya hablan el contrato congelado. El volumen se concentra en trabajo mecánico y acotado: 41 × 2 etiquetas levantadas literalmente de `rendering.py:70-265`, un selector alimentado por un hook que ya existe, `page`/`per_page` añadidos a un DTO y a un mapper, y controles de paginación y rango de fechas sobre **un** componente. Es comparable a `reservations-web` (`S`), que además tuvo que construir lista y detalle desde cero. Lo que la subiría a `M` sería meter el timeline global, el realtime o el arreglo de los 19 tipos huérfanos: las tres están explícitamente fuera y las tres tienen dueño en otro sitio.
