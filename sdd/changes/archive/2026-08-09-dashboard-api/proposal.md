# Proposal: dashboard-api

## Why

El dashboard es «la UX más crítica del producto» (PRD §9) y el principio 2 de
`steering/product.md` lo cifra: responder «¿qué pasa y quién tiene la próxima acción?» en
menos de 10 segundos. La pantalla existe desde `dashboard-web-frontend` (2026-08-01), pero
consume `MockDashboardSource` con datos fijos de REDES11 y PAJARITOS8, porque **el backend
agregado que debe alimentarla no existe**. Hoy `backend/openapi.json` publica 45 rutas y
ninguna de las tres que el PRD §23:1942-1943 y §23:1952 reservan para esto.

Fuentes: `sdd/roadmap/dashboard-api.md` (la nota de la entrada, con la verificación contra
el código del 2026-08-08), PRD §9, §10, §23 y §26.15. El contrato de frontera ya está
escrito y es vinculante: `frontend/features/dashboard/data/dashboard-source.ts:23-41`
(tres métodos) y `frontend/features/dashboard/data/dto.ts` (las formas), que declara en
`:9-12` que son «the contract that `MockDashboardSource` satisfies today and
`HttpDashboardSource` must satisfy tomorrow».

El propio código se asigna este trabajo, en `backend/app/properties/api/router.py:9-10`:
*«Also absent: `GET /{id}/state` and `GET /{id}/dashboard` from §23:1942-1943.»*

## What changes

Después de este cambio el backend expone **cuatro endpoints de lectura**, todos
tenant-scoped y con permiso RBAC declarado: la colección de cards del dashboard, el
agregado de detalle de una propiedad (PRD §9.2), su estado operacional y su timeline
filtrable (PRD §10). El módulo `app/timeline/` gana la capa `api/` que hoy no tiene —
existe `domain/` e `infrastructure/`, y su puerto sólo sabe `add`, porque
`app/timeline/domain/repositories.py:10-11` dejó dicho que *«reading events back belongs to
the change that introduces the timeline endpoints»*. Las entradas del timeline y las
etiquetas de las cards se **componen al leer** en el idioma del usuario autenticado. No se
crea ninguna tabla, no se añade ninguna vía de escritura, y no se toca un solo fichero de
`frontend/`.

## Requirements

### R1 — Colección de cards del dashboard

**Como** propietaria, **quiero** una sola llamada que me devuelva la card de cada una de
mis viviendas, **para** ver en una pantalla qué pasa en todas sin esperar una petición por
propiedad.

Nota de alcance: PRD §23 no lista esta ruta — sólo la variante por propiedad. Se añade
como extensión explícita porque el frontend renderiza `/dashboard` como una rejilla de
cards (`sdd/specs/dashboard-web-frontend.md`) y la alternativa estricta al PRD es un N+1
que tensiona el principio 2 de `product.md`. Queda documentada como tal en la spec.

**Corregido en el gate de diseño (2026-08-09, `design.md` D7)**: la ruta pasa de
`/api/v1/properties/dashboard` a `/api/v1/dashboard/properties`. La primera colisiona con
`/properties/{id}`, que FastAPI resuelve por orden de registro. Al ser la única ruta que el
PRD no nombra, es también la única que puede moverse: las dos de §23:1942-1943 se quedan
literales.

Criterios de aceptación:

1. WHEN un usuario autenticado hace `GET /api/v1/dashboard/properties`, THE SYSTEM SHALL
   devolver el envelope de paginación de PRD §23 (`{data, total, page, per_page,
   total_pages}`) con una card por propiedad **de su tenant**, y ninguna de otro tenant.
2. THE SYSTEM SHALL incluir en cada card exactamente los campos de
   `PropertyDashboardCard` (`frontend/.../dto.ts:85-96`): `propertyId`, `propertyCode`,
   `operationalState`, `currentOrNextReservation`, `cleaningStatus`,
   `openIncidentsCount`, `nextAction`, `lastEventLabel` y `lastEventAt`.
3. THE SYSTEM SHALL emitir `operationalState` como uno de los once literales canónicos de
   `PropertyOperationalState` (PRD §3.1), sin traducir, y SHALL NOT calcular en la
   respuesta ningún color: el mapeo de color es del frontend (PRD §9.1).
4. WHERE una propiedad no tiene reserva actual ni próxima, THE SYSTEM SHALL devolver
   `currentOrNextReservation: null` en vez de omitir la clave.
5. THE SYSTEM SHALL aceptar `?page` y `?per_page` con los mismos límites y validación que
   `GET /api/v1/properties` ya aplica, y IF los parámetros son inválidos THEN THE SYSTEM
   SHALL responder con el envelope de error `{error:{code,message,details}}` de PRD §23.
6. THE SYSTEM SHALL declarar su permiso con `require(...)` como todo endpoint del
   proyecto, de modo que `tests/test_route_authorization.py` lo recorra.
7. IF el rol que llama carece del permiso que protege el origen de un bloque
   (`READ_RESERVATIONS` para reserva y huésped, `READ_CLEANING_TASKS` para limpieza),
   THEN THE SYSTEM SHALL omitir ese bloque de la card en vez de entregarlo — agregar no
   concede (`design.md` D10).
8. THE SYSTEM SHALL resolver la colección completa **sin una consulta por propiedad**
   (sin N+1), y un test SHALL demostrarlo contando las consultas emitidas.

### R2 — Agregado de detalle de una propiedad

**Como** propietaria, **quiero** abrir una vivienda y ver de una vez su reserva, huésped,
acceso, limpieza, incidencias, financiero, notas y aprobaciones, **para** entender su
situación completa sin navegar entre pantallas.

Criterios de aceptación:

1. WHEN un usuario autenticado hace `GET /api/v1/properties/{id}/dashboard` sobre una
   propiedad de su tenant, THE SYSTEM SHALL devolver los campos de `PropertyDetail`
   (`frontend/.../dto.ts:161-174`), que son las secciones de PRD §9.2.
2. IF el `id` no existe **o pertenece a otro tenant**, THEN THE SYSTEM SHALL responder con
   el mismo 404 y el mismo envelope de error de PRD §23 en ambos casos, sin revelar por la
   respuesta ni por el tiempo cuál de los dos ocurrió.
3. WHERE el dominio que escribe un bloque todavía no existe (`incidents` y
   `owner_approvals` esperan a `maintenance`; `expenses` a `revenue`), THE SYSTEM SHALL
   consultar igualmente su tabla real y devolver la lista vacía o `null`, de modo que el
   contrato no cambie cuando esos changes aterricen.
4. THE SYSTEM SHALL devolver `lastCleaningPhotos: []` marcado `EXTERNAL_DEPENDENCY`,
   porque `cleaning_photos` persiste `storage_key` y no una URL, y firmarla es
   `StorageAdapter.get_signed_url` (`steering/security.md` regla 5), que entrega
   `cleaning-photos-storage`. THE SYSTEM SHALL NOT construir ninguna URL de almacenamiento
   ni exponer `storage_key`.
5. THE SYSTEM SHALL devolver en `guest` únicamente el nombre, y en `access` únicamente una
   etiqueta de estado: nunca `document_number` (`steering/security.md` regla 4: jamás en
   listados) ni un código de acceso, ni siquiera enmascarado.
6. THE SYSTEM SHALL declarar su permiso con `require(...)`.
7. IF el rol que llama carece del permiso que protege el origen de un bloque
   (`READ_RESERVATIONS`, `READ_CLEANING_TASKS`, `READ_ACCESS_RECORDS`), THEN THE SYSTEM
   SHALL omitir ese bloque en vez de entregarlo (`design.md` D10).

### R3 — Estado operacional de una propiedad

**Como** cliente del dashboard, **quiero** un endpoint ligero con el estado de una
vivienda, **para** refrescar el indicador sin traerme el agregado entero.

Criterios de aceptación:

1. WHEN un usuario autenticado hace `GET /api/v1/properties/{id}/state` sobre una
   propiedad de su tenant, THE SYSTEM SHALL devolver su `PropertyOperationalState`
   canónico y el instante ISO-8601 UTC de su última transición.
2. THE SYSTEM SHALL derivar ese estado de la misma fuente que ya gobierna las
   transiciones (`PropertyStateMachine` / `ContextualStateResolver`), y SHALL NOT
   reimplementar la resolución de estado en la capa de lectura (`steering/backend.md`,
   don't 1).
3. IF el `id` no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder 404 con
   el envelope de PRD §23, indistinguible entre ambos casos.
4. THE SYSTEM SHALL declarar su permiso con `require(...)`.

### R4 — Timeline por propiedad, filtrable

**Como** propietaria, **quiero** el histórico de lo que ha pasado en una vivienda con
filtros, **para** auditar la operación sin leer la base de datos.

Criterios de aceptación:

1. WHEN un usuario autenticado hace `GET /api/v1/timeline/{property_id}` sobre una
   propiedad de su tenant, THE SYSTEM SHALL devolver sus eventos en el envelope de
   paginación de PRD §23, **ordenados por instante de ocurrencia descendente** y con un
   desempate determinista, de modo que la paginación no repita ni omita entradas.
2. THE SYSTEM SHALL aceptar los filtros de PRD §10 que el contrato del frontend declara
   (`TimelineFilters`, `dto.ts:111-117`): `eventType`, `severity`, `actorType`, `from` y
   `to`; y SHALL combinarlos con AND.
3. THE SYSTEM SHALL incluir en cada entrada exactamente los campos de `TimelineEntry`
   (`dto.ts:99-108`) y SHALL NOT serializar la columna `metadata`, que es JSON libre y no
   forma parte del contrato de lectura.
4. THE SYSTEM SHALL añadir la lectura como un **método nuevo del puerto**, dejando intacta
   la inmutabilidad que `app/timeline/domain/repositories.py:8-11` expresa en la firma: no
   aparece `save`, `update` ni `delete`.
5. IF `property_id` no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder
   404 con el envelope de PRD §23, indistinguible entre ambos casos.
6. THE SYSTEM SHALL declarar su permiso con `require(...)`.

### R5 — Textos legibles en el idioma del usuario

**Como** usuaria autenticada, **quiero** leer el timeline y las etiquetas de las cards en
mi idioma, **para** entender la operación sin traducir literales de sistema.

PRD §10 exige entradas «legibles por humanos en el idioma del usuario autenticado» y
`dto.ts:28-34` declara `LocalizedText` como texto «ya localizado por el backend». Hoy eso
no se cumple y no puede cumplirse leyendo la fila: `TimelineEventFactory` congela el título
en inglés al escribir (`app/timeline/domain/services.py:112`: `f"Property state changed to
{...}"`), y el timeline es inmutable, así que reescribir el pasado no es una opción.

Criterios de aceptación:

1. WHEN el sistema compone una entrada de timeline para una respuesta, THE SYSTEM SHALL
   renderizar `title` a partir de `event_type` y `metadata` en el idioma de
   `User.preferred_language` (`app/auth/domain/entities.py:48`), soportando `es` y `en`.

   **`ASSUMPTION` — `description` no se renderiza: se entrega tal cual.** La primera
   redacción de este criterio decía «`title` y `description`», y la implementación no lo
   cumplió por una razón que resultó ser la correcta: lo que los escritores guardan en
   `description` **no es texto de sistema, es texto humano**. El caso vivo es
   `PropertyStateTransition.reason` (`app/timeline/domain/services.py:128`), que teclea una
   persona al bloquear una vivienda o ponerla fuera de servicio. Traducirlo sería inventar
   contenido ajeno, no localizar un literal, y no hay `metadata` desde la que componerlo.
   `app/timeline/domain/rendering.py:280-283` deja escrita esta decisión y
   `backend/tests/timeline/test_rendering.py:253-259` la fija con un test.

   Consecuencia aceptada: una entrada puede llegar con el `title` en el idioma de quien lee
   y la `description` en el idioma en que la escribió el operador. Un `TimelineEventType`
   cuya `description` **sí** sea generada por el sistema puede ganar plantilla más adelante
   sin cambiar el contrato — el renderer ya tiene el sitio.
2. THE SYSTEM SHALL aplicar el mismo criterio a los `LocalizedText` de las cards y del
   detalle (`cleaningStatus`, `nextAction.label`, `lastEventLabel`, títulos de incidencia y
   de aprobación).
3. THE SYSTEM SHALL conservar la columna `title` almacenada sin modificarla, como copia de
   auditoría en inglés, coherente con `steering/backend.md` («mensajes de sistema, logs y
   errores técnicos en inglés»).
4. IF un `TimelineEventType` no tiene entrada en el catálogo, THEN THE SYSTEM SHALL
   degradar al `title` almacenado en vez de fallar la petición, y un test SHALL demostrar
   que **los 45 valores de `TimelineEventType`** tienen entrada en ambos idiomas — de modo que la
   degradación cubra un enum futuro, no un olvido de hoy.
5. THE SYSTEM SHALL NOT traducir los literales canónicos (`PropertyOperationalState`,
   `TimelineActorType`, `TimelineSeverity`, `eventType`): viajan como valores exactos del
   PRD y el frontend los mapea (`dto.ts:36-66`).

### R6 — Contrato regenerado y referencias veraces

**Como** equipo, **quiero** que el artefacto de contrato y las referencias cruzadas digan
la verdad al terminar, **para** que la CI pase y nadie herede un puntero al change
equivocado.

Criterios de aceptación:

1. WHEN el cambio se da por terminado, THE SYSTEM SHALL tener `backend/openapi.json`
   regenerado, de modo que `.github/workflows/api-contract.yml:85` no detecte deriva.
2. THE SYSTEM SHALL tener `frontend/lib/api/generated/openapi.d.ts` regenerado, de modo que
   `npm run api:check` (`.github/workflows/frontend-api-contract.yml:41`) pase. Es el único
   fichero de `frontend/` que este change toca, y es generado, no escrito a mano.
3. THE SYSTEM SHALL corregir las tres referencias que el split del 2026-08-08 dejó
   atribuyendo esta mitad backend a `dashboard-web`:
   `backend/app/properties/api/router.py:10`, `docs/properties.md:109` y `docs/dashboard.md`
   — en este último, actualizando el bloque «Estado: solo lectura sobre datos mock»
   (`:5-10`), que deja de ser cierto, y no sólo el nombre.
4. THE SYSTEM SHALL dejar sin tocar las menciones a `dashboard-web` que se refieren al
   frontend y siguen siendo correctas (`docs/properties.md:107`, `docs/reservations.md:145`,
   `sdd/specs/user-management.md:16,255`, `sdd/specs/reservations.md:16,286`,
   `docs/dashboard.md:68`).

## Out of scope

- **El consumo desde el frontend** (`HttpDashboardSource` y el swap del mock): es
  `dashboard-web`, que ya declara `needs: dashboard-api`. Incluido el comentario
  `frontend/features/dashboard/data/dashboard-source.ts:12`, que le corresponde a esa
  mitad.
- **Cualquier vía de escritura.** Los cuatro endpoints son de lectura pura;
  `properties-crud` entregó la escritura canónica y no se toca. Eso es lo que hace este
  change aditivo.
- **`GET /api/v1/timeline`** (el timeline global de PRD §23:1951). La entrada de roadmap
  acota a la variante por propiedad, que es la que consume el detalle.
- **Firmar URLs de fotos de limpieza**: es el puerto de `cleaning-photos-storage`, en curso
  en paralelo. Aquí sólo queda el campo con lista vacía (R2.4).
- **Implementar `maintenance` o `revenue`**: sus tablas se leen, no se pueblan. Las
  incidencias, aprobaciones y el financiero llegan vacíos hasta que esos changes entren.
- **Realtime / streaming del timeline**: PRD §9.2 dice «timeline en tiempo real», y esto
  entrega lectura con filtros y paginación. Empujar cambios al cliente (WebSocket/SSE) no
  está en el alcance ni en `sdd/specs/dashboard-web-frontend.md`.
- **`sdd/specs/dashboard-web-frontend.md:116`**: la corrección de su referencia a
  `dashboard-web` es una spec viva, así que la escribe `/sdd:archive`, no el `run`.

## Affected specs

- `sdd/specs/dashboard-api.md` — *(no existe aún — se creará al archivar)*: la capacidad
  nueva, con los cuatro endpoints, el catálogo de localización y las dependencias vacías.
- `sdd/specs/timeline-state-machine.md` — deja de ser cierto que el timeline sólo se
  escribe: gana superficie de lectura y un método nuevo en el puerto.
- `sdd/specs/properties-crud.md` — el módulo `properties` suma dos rutas de lectura; hay que
  quitar la afirmación de que sólo expone las cuatro operaciones de §23.
- `sdd/specs/dashboard-web-frontend.md` — corrección de `:116` (`dashboard-web` →
  `dashboard-api`) y del párrafo que da por inexistente el backend agregado.
- `sdd/specs/auth-tenancy.md` — **añadida en el diseño** (D3): `RequestContext` gana
  `preferred_language`, y esa spec es la que describe qué transporta el contexto.
- `sdd/specs/api-contract.md` — sólo si el número de rutas o el proceso de regeneración
  aparece afirmado ahí; si no, no se toca.
