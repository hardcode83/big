# Proposal: timeline-web

## Why

`/timeline` es una de las cuatro destinaciones directas de la navegación móvil y una
superficie declarada del PRD §24, y hoy `frontend/app/(workspace)/timeline/page.tsx:11`
renderiza un `RoutePlaceholder`. El backend que la surte está en producción desde
`dashboard-api` (archivada el 2026-08-09): `GET /api/v1/timeline/{property_id}` con su
contrato congelado y sus tipos generados.

**Y el timeline ya se pinta.** `features/dashboard/components/detail/property-timeline.tsx`
es un componente funcional, montado por `PropertyDetailView`, que ya llama al endpoint real
vía `HttpDashboardSource.getPropertyTimeline`. Así que esto **no construye una lista de
eventos**: resuelve la tensión entre una ruta plana (`route-registry.ts:91-98` declara
`pattern: "/timeline"`) y un endpoint que exige propiedad, y termina el componente que ya
existe. Verificado contra el código el 2026-08-22.

El análisis completo, con la decisión de ruta ya cerrada y las dos alternativas descartadas
con su evidencia, está en `sdd/roadmap/timeline-web.md`. Entrada de roadmap:
`sdd/roadmap.md:137` (`needs: dashboard-api, dashboard-web · size: S · kind: feature`).

## What changes

Después de este change, `/timeline` es una pantalla real: un selector de propiedad —
alimentado por `useDashboardCards()`, sin endpoint ni método de datos nuevo — que monta
**el mismo** `PropertyTimeline` que ya usa `/properties/[id]`. Un solo componente, dos
puntos de montaje: todo lo que se añade (paginación real, rango de fechas, el vocabulario
completo de 46 tipos de evento) entra **dentro** del componente, así que la sección del
detalle de propiedad lo hereda sin tocarla. Se elimina la derivación del desplegable de
tipos a partir de los datos —que además es incorrecta en cuanto exista paginación— y con
ella una petición HTTP por render. No hay ruta que registrar, ni cerco de tests de
navegación que enmendar, ni tipos que generar.

## Requirements

### R1 — `/timeline` monta el timeline sobre una propiedad elegida

**As a** propietaria o manager, **I want** abrir `/timeline` y elegir de qué vivienda quiero
el historial, **so that** la entrada del menú lleve a una pantalla útil y no a un placeholder.

Acceptance criteria:

1. WHEN un usuario con `READ_PROPERTIES` abre `/timeline`, THE SYSTEM SHALL renderizar un
   selector de propiedad cuyas opciones son exactamente las propiedades devueltas por
   `useDashboardCards()`, identificadas por su `propertyCode`.
2. WHILE no haya ninguna propiedad elegida, THE SYSTEM SHALL renderizar el estado vacío
   compartido con copy propio de «elige una vivienda» y **NEVER SHALL** emitir una petición
   a `GET /api/v1/timeline/{property_id}`.
3. WHEN el usuario elige una propiedad, THE SYSTEM SHALL renderizar el componente
   `PropertyTimeline` existente con ese `propertyId`, sin introducir una segunda lista de
   eventos, un segundo hook de timeline ni un segundo store de filtros.
4. WHERE la elección se conserva, THE SYSTEM SHALL guardarla **solo en memoria** (store
   Zustand, hermano de `use-timeline-filters-store.ts`), y **NEVER SHALL** escribirla en
   `localStorage`, `sessionStorage` ni cookie — un `property_id` es un identificador de
   tenant y el almacenamiento del navegador no está acotado por tenant.
5. WHEN el usuario cambia de propiedad, THE SYSTEM SHALL resetear los filtros activos
   (comportamiento que `property-timeline.tsx:43` ya implementa y que se conserva).
6. WHILE la consulta de propiedades esté pendiente o haya fallado, THE SYSTEM SHALL
   renderizar los estados compartidos de carga y error, sin exponer detalle de error crudo.

### R2 — El filtro de tipo de evento ofrece el enum cerrado, no lo que trajeron los datos

**As a** manager, **I want** que el desplegable de tipos ofrezca siempre el vocabulario
completo y traducido, **so that** filtrar sea predecible y no dependa de qué página estoy viendo.

Acceptance criteria:

1. THE SYSTEM SHALL poblar el desplegable de tipo de evento con los **46** valores del enum
   `TimelineEventType` publicado en `frontend/lib/api/generated/openapi.d.ts`, del mismo modo
   que `ACTOR_TYPES` y `SEVERITIES` ya son constantes en `property-timeline.tsx:13-21`.
2. THE SYSTEM SHALL eliminar `optionsQuery` (`property-timeline.tsx:47-51`), la segunda
   consulta con filtros vacíos que hoy cosecha los tipos presentes, y con ella su petición
   HTTP por render.
3. THE SYSTEM SHALL tener una etiqueta de tipo de evento para cada uno de los 46 valores en
   `locales/es/dashboard.json` **y** `locales/en/dashboard.json` (hoy hay 5), redactadas a
   partir del catálogo del servidor `backend/app/timeline/domain/rendering.py:70-265`.
4. WHERE un texto del catálogo del servidor lleva marcador de sustitución (`{source}` en
   `RESERVATION_IMPORTED`, `{to_state}` en `PROPERTY_STATE_CHANGED`), THE SYSTEM SHALL
   escribir la etiqueta del filtro **sin** el marcador.
5. THE SYSTEM SHALL resolver las etiquetas por clave de traducción declarada y **NEVER
   SHALL** usar el literal crudo del enum como texto visible de respaldo.
6. IF un tipo seleccionado no devuelve ninguna entrada, THEN THE SYSTEM SHALL renderizar el
   estado vacío del timeline — 19 de los 46 tipos no tienen escritor de producción y una
   página vacía es una respuesta correcta, no un fallo.

### R3 — Paginación real sobre el sobre que la API ya devuelve

**As a** manager con meses de historial, **I want** recorrer el timeline por páginas,
**so that** no quede oculto todo lo anterior a los primeros 20 eventos.

Acceptance criteria:

1. THE SYSTEM SHALL añadir `page` y `perPage` a `TimelineFilters` (`data/dto.ts:110-116`) y
   mapearlos a `page` / `per_page` en el query de `HttpDashboardSource.getPropertyTimeline`
   (`:177-201`), como el mapper ya hace con `event_type` y `actor_type`.
2. THE SYSTEM SHALL fijar `per_page` en **20** y no exponerlo en la interfaz; solo se navega
   `page`.
3. WHEN el sobre `TimelinePageResponse` indica `total_pages > 1`, THE SYSTEM SHALL renderizar
   controles de página que muestren la página actual y el total, y permitan avanzar y
   retroceder dentro de `1..total_pages`.
4. THE SYSTEM SHALL navegar por páginas discretas y **NEVER SHALL** acumular páginas en una
   sola entrada de caché — cada combinación de filtros incluye `page` y es una entrada
   distinta de TanStack Query, sin duplicar server state en Zustand
   (`steering/frontend.md`).
5. WHEN cambian los filtros de tipo, actor, severidad o rango, THE SYSTEM SHALL volver a la
   página 1.
6. THE SYSTEM SHALL dejar `hooks/query-keys.ts` sin cambios: `dashboardKeys.propertyTimeline`
   ya mete el objeto de filtros completo en la clave (`:15-20`).

### R4 — Rango de fechas que no provoca un 422

**As a** manager, **I want** acotar el timeline a un rango de fechas, **so that** pueda
auditar lo que pasó en una estancia concreta.

Acceptance criteria:

1. THE SYSTEM SHALL renderizar controles de fecha «desde» y «hasta» que alimentan los
   parámetros de contrato `from` y `to`, ambos opcionales e independientes.
2. WHEN el usuario introduce una fecha, THE SYSTEM SHALL convertirla a un instante **con
   zona horaria** antes de enviarla — un extremo sin zona horaria es un `422` del servidor
   (`sdd/specs/dashboard-api.md:136-137`).
3. IF `to` es anterior a `from`, THEN THE SYSTEM SHALL renderizar un error de campo
   localizado y **NEVER SHALL** emitir la petición, en lugar de mostrar el estado de error
   genérico ante el `422`.
4. WHEN el rango es válido, THE SYSTEM SHALL combinarlo en AND con los otros filtros
   activos, respetando que el rango es inclusivo en los dos extremos.

### R5 — El menú deja de prometer una pantalla que no existe

**As a** usuaria del menú, **I want** que la descripción de la ruta diga la verdad,
**so that** no espere un historial de todas las viviendas a la vez.

Acceptance criteria:

1. THE SYSTEM SHALL reescribir `routes.timeline.description` en
   `locales/es/navigation.json` **y** `locales/en/navigation.json` — hoy prometen
   «todas las propiedades» / «across all properties» — para describir el historial de **una
   vivienda a la vez**, que es lo que la API sirve y lo único que
   `sdd/specs/dashboard-api.md:40-41` permite.
2. THE SYSTEM SHALL exportar `TimelineView` desde `features/dashboard/index.ts`, y la
   página SHALL importarlo del barrel de la feature y nunca de una ruta interna.
   *(Enmendado en el gate de `/sdd:design` — OQ1: el barrel exporta `TimelineView` y
   `PropertyTimeline` sigue interno a la feature. La redacción original pedía exportar
   `PropertyTimeline`, lo que obligaba a que la página fuese cliente o a partir la pantalla
   en dos islas coordinadas por store; lo que la regla protege —que la página importe del
   barrel y nunca de una ruta interna— se conserva literal.)*
3. THE SYSTEM SHALL conservar `generateMetadata` con `routeMetadata("timeline")` en
   `app/(workspace)/timeline/page.tsx:6-8`, sustituyendo únicamente el `RoutePlaceholder`
   de la línea 11.
4. THE SYSTEM SHALL dejar sin modificar el descriptor de ruta y su cerco de tests:
   `route-registry.ts`, `route-registry.test.ts`, `route-metadata.test.ts`,
   `breadcrumbs.test.ts`, `select-routes.test.ts`, `match-route.test.ts` y
   `bottom-navigation.tsx`. IF un diff los toca, THEN la decisión de ruta se ha derivado mal.
5. THE SYSTEM SHALL tener cada string nueva de la pantalla — selector, estado «elige una
   vivienda», rango de fechas, controles de paginación — en `locales/es` **y** `locales/en`,
   sin ninguna hardcodeada.

### R6 — `description` se renderiza como texto, nunca como marcado

**As a** responsable de seguridad, **I want** que el único campo de texto libre de operador
del timeline siga escapándose, **so that** una tabla append-only no se convierta en un XSS
almacenado.

Acceptance criteria:

1. THE SYSTEM SHALL renderizar `TimelineEntry.description` como texto interpolado por React,
   y **NEVER SHALL** usar `dangerouslySetInnerHTML`, `innerHTML` ni ningún renderizador de
   markdown sobre ese campo, ni sobre `title`.
2. THE SYSTEM SHALL dejar el permiso y la audiencia intactos: la pantalla vive tras
   `READ_PROPERTIES`, que solo tienen `TENANT_OWNER` y `PROPERTY_MANAGER`, y este change
   **NEVER SHALL** añadir un rol lector — eso reabriría la decisión de publicar `description`
   (`sdd/specs/dashboard-api.md:311-314`).
3. THE SYSTEM SHALL mostrar `title` tal como llega del servidor, ya traducido por el catálogo
   de `rendering.py`, sin retraducirlo en el cliente.

## Out of scope

- **El timeline global de todas las viviendas.** `GET /api/v1/timeline` del PRD §23:1951 no
  existe en `backend/openapi.json` y `sdd/specs/dashboard-api.md:40-41` lo prohíbe con un
  `SHALL NOT` explícito. No es implementable aquí.
- **Índice `/timeline` + detalle `/timeline/[id]`** (opción (b)) y **retirar `/timeline` de la
  navegación** (opción (c)). Las dos obligan a enmendar la lista `PRD_24_SURFACES` de
  `route-registry.test.ts` — es decir, el PRD §24 y un diseño archivado — y eso es una
  decisión de producto que una entrada `[FE]` no toma. Razonadas en
  `sdd/roadmap/timeline-web.md`.
- **Realtime** (WebSocket/SSE) y polling agresivo. `sdd/specs/dashboard-api.md:306-308` deja
  constancia de que el «tiempo real» del PRD §9.2 no está entregado por ninguna mitad.
- **Cualquier escritura sobre el timeline.** No hay escritor en el módulo y no lo va a haber
  (`backend/app/timeline/api/router.py:10-11`).
- **`metadata` de los eventos.** No se serializa ni en el schema ni en la proyección de
  dominio; la ausencia es estructural (`sdd/specs/dashboard-api.md:138-143`).
- **Dar escritor a los 19 tipos de evento huérfanos.** Es trabajo de backend con dueño ya
  asignado en el roadmap (`tech-cycle-completion` para `TECHNICIAN_EN_ROUTE`,
  `sdd/specs/maintenance.md:400-401`). Esta pantalla solo tiene que no romperse cuando el
  filtro devuelve vacío.
- **Exponer `per_page` en la interfaz** y el scroll infinito acumulativo (R3.2, R3.4).
- **Tocar `/properties/[id]`** más allá de lo que hereda automáticamente por compartir el
  componente `PropertyTimeline`.
- **Endpoints, métodos de `DashboardDataSource`, DTOs nuevos y regeneración de tipos.** El
  contrato está congelado y `openapi.d.ts` ya lo declara entero.

## Affected specs

- `sdd/specs/dashboard-web-frontend.md` — es el dueño de la capa de presentación del
  dashboard y del timeline por propiedad. Se amplía con la superficie `/timeline`, el
  selector de propiedad, la paginación, el rango de fechas y el vocabulario cerrado de tipos.
- `sdd/specs/frontend-foundation.md` — dueño del registro de rutas y de `RoutePlaceholder`.
  Se anota que `/timeline` deja de ser una ruta con placeholder, y la corrección de la
  descripción i18n del descriptor.
- `sdd/specs/dashboard-api.md` — sin cambio de comportamiento de backend, pero sus líneas 156
  y 328 dicen «45 valores de `TimelineEventType`» y el enum publicado tiene **46**
  (`GUEST_CHECKIN_COMPLETED` llegó con `guest-portal-api`). Este change enumera los 46 para
  etiquetarlos, así que es el momento natural de corregir la cifra.
