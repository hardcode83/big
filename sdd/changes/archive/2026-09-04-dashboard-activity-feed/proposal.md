# Proposal: dashboard-activity-feed

## Why

PRD §23 lista `GET /api/v1/timeline` (línea 1951) junto a `GET /api/v1/timeline/{property_id}`
(línea 1952) como dos rutas del grupo timeline. `dashboard-api` sólo entregó la segunda —su
router lo dice explícitamente: *"the global variant of §23:1951 — is out of scope (the roadmap
entry bounds this to the per-property one)"* (`backend/app/timeline/api/router.py:8-11`)— y esa
ruta global es exactamente esta entrada.

Lo que la convierte en trabajo vivo hoy es la Decisión 4 de `visual-restyle-workspace`
(Jose, 2026-08-23, `sdd/roadmap/visual-restyle-workspace.md`): el dashboard rediseñado
(`docs/design/2026-08-23-stitch-export/dashboard_autohostai_emerald_style/`) añade sobre las
property cards reales un widget «Actividad Reciente» — una línea de tiempo vertical con icono,
título («Limpieza completada»), subtítulo con el código de la vivienda y descripción («REDES11 -
Estado actualizado») y tiempo relativo («Hace 10 min»)— para el que hoy no existe ninguna lectura
a nivel de tenant. Es la tercera de las tres entradas nacidas de esa decisión, junto a
`dashboard-operational-kpis` (entregada) y `dashboard-occupancy-series` (entregada): las tres
cuentan datos que el sistema **ya tiene** y no expone agregados — en este caso, los eventos de
`timeline_events` que `timeline-state-machine` ya escribe para cada propiedad.

**Nota para el design**: el roadmap marca «ojo al radio de agregación que acota la regla 11 de
`steering/security.md`». `GET /api/v1/timeline/{property_id}` ya sirve `description` verbatim —
texto que teclea un operador— bajo `READ_PROPERTIES`, y su propio comentario de router documenta
por qué ese permiso ya implica todo lo que una entrada puede revelar (`test_reading_properties_
implies_every_permission_a_timeline_entry_can_reveal`). Este change no añade lector nuevo ni
amplía ese permiso; lo que cambia es que una sola petición ahora agrega eventos de **todas** las
propiedades del tenant en vez de una. Si el panel de seguridad de `/sdd:design` concluye que ese
radio de agregación sí exige una fila propia en el censo de la regla 11 (más allá de la que ya
cubre el lector por propiedad), esa fila se añade en el design de este change — no está resuelto
aquí.

## What changes

Un nuevo endpoint de sólo lectura, `GET /api/v1/timeline`, que devuelve una página de eventos de
timeline de **todas** las propiedades del tenant del token, con el mismo orden, los mismos
filtros y el mismo permiso que `GET /api/v1/timeline/{property_id}` ya usa, más la identidad
legible de la propiedad de cada entrada (nombre y código interno, mismo patrón que
`reservation-property-identity` fijó para reservas) para que el frontend no tenga que resolver un
`property_id` pelado por fila. Sin escritor nuevo: los eventos siguen naciendo de los mismos
sitios que `timeline-state-machine` ya gobierna.

## Requirements

### R1 — Feed de actividad a nivel de tenant

**As a** manager o propietaria autenticada, **I want** una página de eventos de timeline de todas
mis propiedades en una sola petición, **so that** el widget «Actividad Reciente» del dashboard
no tenga que consultar propiedad por propiedad.

Acceptance criteria:

1. WHEN un usuario autenticado con `READ_PROPERTIES` solicita `GET /api/v1/timeline`, THE SYSTEM
   SHALL devolver eventos de todas las propiedades de su tenant, paginados con `page`/`per_page`
   (PRD §23), ordenados por `occurred_at` descendente con desempate determinista por `id` —mismo
   criterio que R4.1 de `dashboard-api` fija para el endpoint por propiedad, para que paginar no
   repita ni omita entradas cuando varias comparten instante.
2. THE SYSTEM SHALL contar en `total` el mismo conjunto filtrado que devuelve en `data`, nunca
   todos los eventos del tenant.
3. IF el tenant no tiene ninguna propiedad o ninguna tiene eventos, THEN THE SYSTEM SHALL
   devolver una página vacía con `200`, nunca `404` — a diferencia del endpoint por propiedad, no
   hay un identificador de recurso que pueda no existir.
4. THE SYSTEM SHALL NOT aceptar ni exigir un `property_id`: esta ruta es la variante sin él que
   PRD §23:1951 declara junto a la de la línea 1952, que ya lo exige.

### R2 — Mismos filtros que el endpoint por propiedad

**As a** operador que ya filtra el timeline de una propiedad, **I want** los mismos filtros
disponibles en el feed de tenant, **so that** la vista cross-propiedad no sea una versión
reducida de la que ya existe.

Acceptance criteria:

1. THE SYSTEM SHALL aceptar los mismos filtros AND-combinados que `GET /api/v1/timeline/{property_id}`
   ya acepta —`event_type`, `severity`, `actor_type`, y el rango `from`/`to` inclusivo en ambos
   extremos—, con los mismos nombres de contrato.
2. IF el rango es inverso (`to` anterior a `from`), o alguno de sus extremos llega sin zona
   horaria, THEN THE SYSTEM SHALL rechazarlo con `422` y el envelope de error — mismo criterio que
   ya aplica `TimelineFilters.__post_init__`.

### R3 — Identidad legible de la propiedad en cada entrada

**As a** operador que mira el feed de tenant, **I want** que cada entrada muestre el nombre o
código de la propiedad a la que pertenece, **so that** el widget no tenga que enseñar un UUID
pelado ni pedir `/properties` aparte para resolverlo.

Acceptance criteria:

1. THE SYSTEM SHALL incluir en cada entrada, además de los campos que ya expone
   `GET /api/v1/timeline/{property_id}` (`id`, `occurred_at`, `actor_type`, `event_type`,
   `severity`, `title`, `description`), los campos `property_id`, `property_name` y
   `property_internal_code` de la vivienda que originó el evento.
2. THE SYSTEM SHALL resolver `property_name` y `property_internal_code` en un número de consultas
   acotado e independiente del tamaño de página —mismo principio de "N propiedades sin N
   consultas" que `TimelineEventReader.last_for_properties` ya respeta (R1.7 de `dashboard-api`)—,
   nunca una consulta por entrada.
3. THE SYSTEM SHALL NOT serializar la columna `metadata`, que sigue sin formar parte del
   contrato de lectura (R4.3 de `dashboard-api`).

### R4 — Mismo permiso, mismo idioma, ningún lector nuevo de la regla 11

**As a** responsable de seguridad del proyecto, **I want** que el feed de tenant no abra una vía
de lectura nueva ni un permiso nuevo, **so that** agregar por tenant no ensanche quién puede leer
qué.

Acceptance criteria:

1. THE SYSTEM SHALL gatear `GET /api/v1/timeline` con el mismo permiso que
   `GET /api/v1/timeline/{property_id}` ya usa (`READ_PROPERTIES`); esta entrada SHALL NOT
   declarar un permiso nuevo.
2. THE SYSTEM SHALL componer `title` en el idioma de `preferred_language` del usuario autenticado
   y SHALL devolver `description` verbatim, sin traducir —mismas reglas R5.1/R5.5 de
   `dashboard-api`— y SHALL NOT traducir los literales canónicos (`event_type`, `actor_type`,
   `severity`).
3. THE SYSTEM SHALL restringir la consulta al `tenant_id` del token de forma explícita por
   consulta (convención D2 de `sdd/specs/dashboard-api.md`), de modo que ningún evento de otro
   tenant aparezca en la respuesta.

## Out of scope

- La mitad `[FE]` que consume y pinta el widget «Actividad Reciente» — queda para su propia
  entrada de roadmap, cuando la composición visual pueda verse contra datos reales (D4 de
  `visual-restyle-workspace`), igual que se dejó fuera en `dashboard-operational-kpis` y
  `dashboard-occupancy-series`.
- El filtro por reserva que PRD §10 menciona («por reserva») — `GET /api/v1/timeline/{property_id}`
  tampoco lo implementa hoy, y añadirlo aquí ampliaría el alcance de esta entrada a un endpoint que
  no lo tiene.
- Tiempo real / push (WebSockets, SSE, polling automático) — sigue siendo una lectura paginada
  bajo demanda, igual que el endpoint por propiedad; PRD §9.2 pide "tiempo real" para la página de
  detalle de propiedad, no para este feed.
- Cambiar el comportamiento o contrato de `GET /api/v1/timeline/{property_id}` — este change sólo
  añade la variante sin `property_id` que la misma sección de PRD ya declaraba.
- Añadir una fila nueva al censo de la regla 11 o cambiar el permiso que gatea el timeline — se
  reutiliza `READ_PROPERTIES` tal cual (R4). Si el design de este change concluye que el radio de
  agregación sí lo exige, esa decisión y esa fila se toman y se escriben allí.
- El buscador global de la maqueta («Buscar reservas, propiedades») — ya descartado explícitamente
  por la Decisión 4 de `visual-restyle-workspace` por no ser un dato que el sistema ya tenga.

## Affected specs

- `sdd/specs/dashboard-api.md` — añade el grupo de endpoints del timeline con la ruta
  `GET /api/v1/timeline` y su contrato de respuesta.
- `sdd/specs/timeline-state-machine.md` — el puerto `TimelineEventReader` gana un método de
  lectura a nivel de tenant (junto a `list_for_property` y `last_for_properties` ya existentes);
  se documenta en la sección "Dónde se leen".
