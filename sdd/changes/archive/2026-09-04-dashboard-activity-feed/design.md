# Design: dashboard-activity-feed

## Context

El dominio `timeline` ya tiene las cuatro capas: `domain/` (factoría, entidades, catálogo de
títulos en `rendering.py`, puertos en `repositories.py`), `application/`
(`GetPropertyTimelineUseCase`), `infrastructure/` (`SqlAlchemyTimelineEventReader`) y `api/`
(un solo router con una sola ruta). Lo que falta es exactamente una variante de la lectura que
ya existe: `SqlAlchemyTimelineEventReader.list_for_property` construye sus condiciones en
`_conditions(tenant_id, property_id, filters)` y su orden en `_ordered(...)`, y ambas piezas
sirven igual sin el `property_id`.

La identidad legible de la propiedad tiene precedente literal en el árbol:
`ListReservationsUseCase` (`backend/app/reservations/application/use_cases.py:450-475`) resuelve
`property_name`/`property_internal_code` con un lector por lotes,
`PropertyRepository.list_for_ids` (`backend/app/properties/infrastructure/repositories.py:156`),
después de la consulta de página y nunca por fila; `tests/reservations/test_list_identity_queries.py`
lo fija contando sentencias con `tests/sql_counter.py`.

Dos cosas del estado actual que este design tiene que mover explícitamente. La primera:
`sdd/specs/dashboard-api.md:46-47` dice hoy *«THE SYSTEM SHALL NOT exponer el timeline global
`GET /api/v1/timeline` de PRD §23:1951»*, y el docstring de
`backend/app/timeline/api/router.py:8-11` repite la misma frase. Las dos describen el alcance de
`dashboard-api`, no una decisión permanente, y esta entrada las revoca. La segunda: los tres
índices de `timeline_events` (`backend/app/timeline/infrastructure/models.py:15-32`) están
construidos para lecturas *por propiedad*, *por tipo de evento dentro del tenant* y *por reserva*
— ninguno sirve la consulta que este feed hace por defecto.

## Decisions

### D1 — La ruta vive en el router de `timeline`, como path vacío

**Chosen:** `@router.get("")` en `backend/app/timeline/api/router.py`, que con el `prefix="/timeline"`
del router resuelve a `GET /api/v1/timeline` exactamente. Es la ruta literal de PRD §23:1951, y la
regla que `sdd/specs/dashboard-api.md` §Reparto de rutas aplica a su hermana por propiedad
—«dominio propio, con la capa `api/` que estrena»— vale igual aquí: el dato es de un solo dominio
y ese dominio ya tiene router.

No hay colisión con `"/{property_id}"`: un parámetro de ruta de Starlette no casa con un segmento
vacío, así que `/api/v1/timeline` sólo puede casar con la ruta nueva. `/api/v1/timeline/` (con
barra final) no casa con ninguna de las dos y Starlette redirige `307` a la nueva, que es
comportamiento estándar del proyecto y no una decisión propia.

Rejected: colgarla de `app/dashboard/api/router.py` — su prefijo es `/dashboard` y el PRD fija esta
ruta literal, así que habría que montar un segundo router sin prefijo sólo para una ruta.
Rejected: `@router.get("/")` — publica `/api/v1/timeline/` como ruta canónica y deja la que el PRD
nombra detrás de un redirect.

### D2 — Un tercer método en `TimelineEventReader`, no un puerto nuevo

**Chosen:** `list_for_tenant(tenant_id, *, filters, page, per_page) -> Page` junto a
`list_for_property` y `last_for_properties` en `backend/app/timeline/domain/repositories.py`.
`TimelineEventReader` es el puerto **de lectura** del timeline y esto es una lectura del timeline;
la segregación que el módulo defiende con tanto cuidado es la que separa **lectura de escritura**
—`TimelineEventRepository` tiene un solo método, `add`, y eso *es* la inmutabilidad expresada en
una firma—, no una que exija un puerto por consulta.

Rejected: un `TenantTimelineReader` aparte — Interface Segregation habla de puertos por *rol* de
consumidor, y aquí el consumidor es el mismo (una lectura paginada del timeline); partirlo daría
dos puertos que el mismo adaptador implementa y que la misma `dependencies.py` inyecta.
Rejected: un parámetro `property_id: UUID | None` en `list_for_property` — la firma dejaría de
decir lo que hace y el `404` de la ruta por propiedad colgaría de un argumento opcional.

### D3 — Las condiciones y el orden se generalizan, no se duplican

**Chosen:** `_conditions(tenant_id, filters, property_id=None)` en
`backend/app/timeline/infrastructure/repositories.py`: el `property_id` pasa a ser opcional y
sólo añade su cláusula cuando llega. `_ordered(...)` se reutiliza tal cual. Así R2.1 («los mismos
filtros AND-combinados») y R1.1 («mismo orden, mismo desempate por `id`») no son una promesa que
alguien tenga que recordar mantener sincronizada: son literalmente el mismo código, y una
divergencia futura tendría que escribirse a propósito.

`TimelineFilters` (`domain/repositories.py:51`) se reutiliza **sin tocar**: ya valida el rango
invertido y la falta de zona horaria en `__post_init__`, que es lo que R2.2 exige, y no contiene
ningún `property_id` que hubiera que anular.

Rejected: una función de condiciones propia para el feed — dos listas de filtros que empiezan
idénticas y divergen en el primer filtro nuevo.

### D4 — Índice nuevo `ix_timeline_events_tenant_id_created_at`, con su migración

**Chosen:** añadir `Index("ix_timeline_events_tenant_id_created_at", "tenant_id", text("created_at DESC"))`
a `TimelineEventModel.__table_args__` y su revisión de Alembic (down_revision: `4ba1f499f7c2`,
cabeza única hoy).

Los tres índices existentes no sirven la consulta por defecto de este feed. El widget pide la
página más reciente **sin filtro**, así que la consulta es `WHERE tenant_id = :t ORDER BY
created_at DESC, id DESC LIMIT :n`: `ix_timeline_events_property_id_created_at` no empieza por
`tenant_id`, `ix_timeline_events_reservation_id_created_at` tampoco, y
`ix_timeline_events_tenant_id_event_type_created_at` sí empieza por `tenant_id` pero pone
`event_type` **antes** que `created_at`, de modo que sin filtro por tipo no puede entregar el
orden y el planificador acaba ordenando todo el historial del tenant para devolver 20 filas.
La consulta de `total` (R1.2) tiene el mismo perfil y este índice la convierte en un recorrido
index-only del rango del tenant.

`timeline_events` es append-only y crece con cada operación de cada propiedad, así que es
precisamente la tabla donde «hoy son pocas filas» deja de ser cierto sin que nadie lo note. Un
índice de dos columnas es la mitigación barata y reversible.

Rejected: no añadir índice y anotar deuda — la consulta lenta es la del caso por defecto del
widget, no la de un filtro raro; la deuda se pagaría en la pantalla que esta entrada existe para
alimentar. Rejected: `(tenant_id, created_at DESC, id DESC)` — el desempate por `id` sólo ordena
dentro de un mismo instante (un puñado de filas), que es lo que los dos índices existentes ya
asumen; añadir la tercera columna ensancha el índice sin cambiar el plan.

### D5 — La identidad de la propiedad se resuelve por lotes con el puerto que ya existe

**Chosen:** el caso de uso llama a `PropertyRepository.list_for_ids(tenant_id, property_ids)`
**después** de la consulta de página, una sola vez, con los ids distintos de esa página, y compone
en memoria — el patrón exacto de `ListReservationsUseCase`. Total: **tres sentencias fijas**
(`count`, página, lote de propiedades), independientes de `per_page`, que es lo que R3.2 pide.
`list_for_ids` ya contrata lo que hace falta: entrada vacía sin viaje a SQL, deduplicado, y una
propiedad de otro tenant simplemente ausente del resultado.

La composición vive en el caso de uso y no en el modelo de respuesta, que es la decisión D1 de
`reservation-property-identity` y la razón por la que `api/` no toca `infrastructure/`.

Rejected: un `JOIN` entre `timeline_events` y `properties` en el adaptador — sería el segundo
sitio donde se escribe el scope de tenant, que es exactamente lo que
`sdd/specs/dashboard-api.md` §Composición por lotes prohíbe.
Rejected: una proyección estrecha nueva en `PropertyRepository` (estilo `states_for`, sólo
`id`/`name`/`internal_code`) — cerraría que las tres notas de `properties` entren en memoria en
esta petición, pero añade un método al puerto compartido para una garantía que la respuesta ya
tiene por construcción (los campos se enumeran uno a uno, nunca `from_attributes`), y divergiría
del único precedente vivo de esta misma composición. Anotado en §Risks.

### D6 — `property_name` y `property_internal_code` viajan anulables

**Chosen:** `str | None`, `null` cuando el id de la entrada no aparece en el lote. Las claves
**siempre están presentes** (`sdd/specs/dashboard-api.md` §Forma del contrato: una clave ausente y
una nula no son lo mismo).

No es defensivo por costumbre: las claves ajenas de `timeline_events` son globales y no compuestas
con `tenant_id` —lo dice la precondición de `TimelineEventRepository.add` y está registrado como
deuda en el design D18 de `reservations`—, así que una fila corrupta podría apuntar a una
propiedad de otro tenant. En ese caso `list_for_ids`, que sí filtra por tenant, no la devuelve, y
la respuesta sale con la identidad a `null` en vez de con un `500` o —peor— con el nombre de la
vivienda del vecino. `property_id` sí es siempre no nulo: la columna lo es y la factoría lo exige.

Rejected: descartar la entrada sin identidad — un feed con huecos silenciosos es peor superficie
de auditoría que uno que enseña la entrada y admite que no pudo resolver la vivienda, que es el
mismo razonamiento con el que el router por propiedad rechazó filtrar entradas por permiso.

### D7 — Un modelo de lectura propio, y `render()` se reutiliza intacto

**Chosen:** `backend/app/timeline/domain/read_models.py` (fichero nuevo) con un dataclass congelado
`TenantActivityEntry`: los siete campos que `RenderedEntry` ya tiene más `property_id`,
`property_name` y `property_internal_code`, y un constructor
`from_rendered(entry, *, property_id, property_name, property_internal_code)`. El caso de uso
llama a `render(event, locale)` **sin modificarlo** y envuelve el resultado.

`read_models.py` es el nombre que `maintenance`, `cleaning` y `dashboard` ya dan a este fichero, y
`domain/rendering.py` está acotado por su propio docstring al catálogo de localización — el feed
compone dos dominios, que no es lo que ese módulo hace. Sigue siendo Python puro: `str`, `dict`,
`dataclass`, sin pydantic ni sqlalchemy (regla de dependencia de `steering/backend-architecture.md`).

Que `RenderedEntry` no gane campos es lo que mantiene R4.2 cierto sin escribir nada nuevo: el
`title` se compone en el idioma del usuario contra el mismo catálogo de 47 valores, la
`description` pasa verbatim, y los literales canónicos no se traducen — porque es exactamente la
misma función.

Rejected: añadir los tres campos opcionales a `RenderedEntry` — los volvería opcionales también
para la ruta por propiedad, que no los tiene, y `TimelineEntryResponse` tendría que acordarse de
no serializarlos.

### D8 — Esquemas de respuesta propios, por herencia, sin tocar el contrato existente

**Chosen:** en `backend/app/timeline/api/schemas.py`,
`TenantTimelineEntryResponse(TimelineEntryResponse)` añadiendo los tres campos de identidad, y
`TenantTimelinePageResponse` con el envelope de PRD §23 sobre esa lista. Los campos heredados se
declaran una vez, así que R3.1 («además de los campos que ya expone la ruta por propiedad») queda
sostenida por la herencia y no por dos listas que hay que comparar a mano.

`metadata` sigue sin existir en ningún punto del camino —ni en `TenantActivityEntry`, ni en
`RenderedEntry`, ni en ninguno de los dos esquemas—, que es lo que R3.3 exige y lo que el
docstring de `schemas.py` llama «dos negativas estructurales en vez de una omisión recordada».

`TimelineEntryResponse` y `TimelinePageResponse` **no se tocan**: la ruta por propiedad conserva su
contrato campo por campo, que es lo que el proposal declara fuera de alcance.

Rejected: un solo esquema con los tres campos anulables para las dos rutas — publicaría en el
contrato de `GET /api/v1/timeline/{property_id}` tres claves que siempre valdrían lo mismo, y
cambiar ese contrato está fuera de alcance.

### D9 — Sin `404` y sin lectura previa de propiedades

**Chosen:** `ListTenantActivityUseCase.execute` va directo a `list_for_tenant`. No hay
`PropertyRepository.get` de comprobación previa y no hay `PropertyNotFoundError`.

`GetPropertyTimelineUseCase` sí lo hace, y su docstring explica por qué: sin esa lectura, el código
de estado distinguiría «tu vivienda no tiene eventos» de «esa vivienda no es tuya». Aquí no hay
identificador de recurso en la ruta que pueda existir o no, así que no hay nada que ocultar y una
página vacía con `200` es la respuesta correcta y la única — R1.3, y R1.4 (la ruta no acepta ni
exige `property_id`).

Rejected: devolver `404` cuando el tenant no tiene ninguna propiedad — inventaría un recurso
inexistente para una ruta de colección.

### D10 — `READ_PROPERTIES` reutilizado, y por qué agregar por tenant no concede nada

**Chosen:** la ruta declara el `ReadDep` que ya existe en el módulo
(`require(Permission.READ_PROPERTIES)`), sin permiso nuevo (R4.1). El `tenant_id` sale del token y
viaja explícito a cada método de repositorio, nunca como filtro que el cliente pueda poner (R4.3,
convención D2 de `sdd/specs/dashboard-api.md`).

El radio de agregación que el roadmap señala se resuelve así, y conviene decirlo entero porque es
lo que el proposal delegó aquí:

- **No crece quién puede leer.** El mismo permiso, los mismos dos roles que hoy lo tienen
  (`TENANT_OWNER`, `PROPERTY_MANAGER`), y ningún permiso nuevo declarado.
- **No crece qué se puede leer.** `GET /api/v1/properties` está gateado por `READ_PROPERTIES`
  (`backend/app/properties/api/router.py:74`) y `GET /api/v1/timeline/{property_id}` también, así
  que un portador de ese permiso ya puede enumerar todas las viviendas de su tenant y pedir el
  timeline de cada una. **Este feed es exactamente la unión de N peticiones que el llamante ya
  puede hacer**, en una sola.
- **La regla «agregar no puede conceder» se hereda sin ensancharla.** El bloque de comentario de
  `backend/app/timeline/api/router.py:38-62` argumenta que una entrada de timeline anuncia hechos
  de otros dominios y que ningún rol tiene `READ_PROPERTIES` sin los permisos que esos hechos
  exigirían; lo sostiene
  `tests/auth/test_policy.py::test_reading_properties_implies_every_permission_a_timeline_entry_can_reveal`.
  Ese test no cambia y sigue siendo la puerta: si algún día falla, se reabre allí.
- **Los tres campos de identidad son una proyección que estrecha, no una unión.**
  `sdd/specs/dashboard-api.md` cierra su §Permisos con la regla que sobrevive a los dos
  precedentes: *«una proyección puede estrechar, nunca unir»*. `property_name` e
  `internal_code` son dos campos de `Property`, protegidos por el mismo `READ_PROPERTIES` que
  gatea esta ruta; no se añade ningún valor que otro permiso guarde como un todo.

Lo que **sí** cambia es el **bulto**: una sola respuesta puede llevar la `description` de eventos
de todas las viviendas. Esa mitad es la open question OQ1, y no la decide este bloque.

Rejected: un permiso propio del feed — `app/auth/domain/policy.py` sostiene que el catálogo «no
tiene capacidades especulativas que nadie comprueba», y aquí no hay ninguna capacidad nueva que
nombrar.

### D11 — La spec vigente afirma lo contrario y el archive la reescribe

**Chosen:** `sdd/specs/dashboard-api.md` tiene hoy dos afirmaciones que esta entrada revoca, y
las dos se corrigen al archivar, no antes: la línea 46-47 (`SHALL NOT exponer el timeline global`)
y la tabla §Reparto de rutas, que enumera «exactamente estas seis rutas» y pasa a siete. El
docstring de `backend/app/timeline/api/router.py:8-11` («*is out of scope*») se corrige **en la
implementación**, porque es código y lo escribe este change.

Se anota como decisión y no como tarea suelta porque una spec viva que contradice el código es
justo lo que `/sdd:review` detecta como deriva, y porque quien archive tiene que saber que su
trabajo aquí no es sólo añadir una sección sino **borrar una prohibición**.

## Cobertura de requisitos

| Requisito | Dónde se resuelve |
|---|---|
| R1.1 — eventos de todas las propiedades, paginados, orden + desempate | D2, D3 (`_ordered` compartido), D4 |
| R1.2 — `total` cuenta el mismo conjunto filtrado | D3 (mismas condiciones para `count` y página) |
| R1.3 — página vacía `200`, nunca `404` | D9 |
| R1.4 — no acepta ni exige `property_id` | D1, D9 |
| R2.1 — mismos filtros AND-combinados, mismos nombres | D3 (`TimelineFilters` reutilizado sin cambios) |
| R2.2 — `422` para rango invertido o sin zona horaria | D3 — **sin implicación de diseño nueva**: `TimelineFilters.__post_init__` ya lo hace y el manejador de error del módulo ya lo traduce; lo único que hace falta es cubrirlo con test en la ruta nueva |
| R3.1 — identidad legible en cada entrada | D7, D8 |
| R3.2 — consultas acotadas, nunca una por entrada | D5 |
| R3.3 — `metadata` nunca se serializa | D8 (ausencia estructural en las tres capas) |
| R4.1 — mismo permiso, ninguno nuevo | D10 |
| R4.2 — `title` localizado, `description` verbatim, literales sin traducir | D7 — **sin implicación de diseño nueva**: es la misma función `render()` sobre el mismo catálogo |
| R4.3 — scope de tenant explícito por consulta | D5, D10 |

## Changes by area

| Area | Files | Change |
|---|---|---|
| `timeline` / domain | `backend/app/timeline/domain/repositories.py` | `TimelineEventReader` gana `list_for_tenant` (D2) |
| `timeline` / domain | `backend/app/timeline/domain/read_models.py` **(nuevo)** | `TenantActivityEntry` + `from_rendered` (D7) |
| `timeline` / application | `backend/app/timeline/application/use_cases.py` | `ListTenantActivityUseCase` + `RenderedTenantPage`; compone identidad por lotes (D5, D9) |
| `timeline` / infrastructure | `backend/app/timeline/infrastructure/repositories.py` | `SqlAlchemyTimelineEventReader.list_for_tenant`; `_conditions` con `property_id` opcional (D2, D3) |
| `timeline` / infrastructure | `backend/app/timeline/infrastructure/models.py` | índice `ix_timeline_events_tenant_id_created_at` (D4) |
| `timeline` / api | `backend/app/timeline/api/schemas.py` | `TenantTimelineEntryResponse`, `TenantTimelinePageResponse` (D8) |
| `timeline` / api | `backend/app/timeline/api/dependencies.py` | `get_tenant_activity_use_case` (mismas dos adaptadores que la ruta hermana) |
| `timeline` / api | `backend/app/timeline/api/router.py` | `GET ""`; docstring del módulo corregido (D1, D10, D11) |
| Migración | `backend/alembic/versions/<rev>_timeline_tenant_created_at_index.py` **(nuevo)** | `down_revision = "4ba1f499f7c2"`; sólo `create_index`/`drop_index` (D4) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados (workflows `api-contract` / `frontend-api-contract`) |
| Tests | `backend/tests/timeline/test_api.py` o un `test_tenant_feed_api.py` nuevo, `test_read_repository.py`, y un test de recuento de sentencias con `tests/sql_counter.py` | ver §Data & interfaces |
| Docs | `docs/dashboard.md` (o el que documente la capacidad) | según `steering/documentation.md`, se decide en `/sdd:tasks` |

## Data & interfaces

**Esquema.** Ninguna tabla, columna ni enum nuevos. Un índice:
`ix_timeline_events_tenant_id_created_at (tenant_id, created_at DESC)`. La migración es
reversible y no toca datos.

**Puerto** (`TimelineEventReader`):

```python
async def list_for_tenant(
    self, tenant_id: uuid.UUID, *, filters: TimelineFilters, page: int, per_page: int
) -> Page: ...
```

**Contrato HTTP.** `GET /api/v1/timeline`, `require(Permission.READ_PROPERTIES)`.

- Query: `page` (1..`MAX_PAGE`), `per_page` (1..`MAX_PER_PAGE`), `event_type`, `severity`,
  `actor_type`, `from`, `to` — los mismos nombres, las mismas cotas y los mismos tipos que la ruta
  por propiedad, importados de las mismas constantes.
- Respuesta `200`: `{data, total, page, per_page, total_pages}`; cada entrada lleva `id`,
  `occurred_at`, `actor_type`, `event_type`, `severity`, `title`, `description`, `property_id`,
  `property_name`, `property_internal_code`. Todas las claves presentes, `null` cuando toque.
- `422` con el envelope de PRD §23 para paginación fuera de rango, rango invertido o extremo sin
  zona horaria. `401` sin token. No hay `404`.

**Configuración / variables de entorno**: ninguna.

**Verificación que este design compromete** (el desglose fino es de `/sdd:tasks`): aislamiento por
tenant con el vecino realmente sembrado —incluida una propiedad del vecino **con eventos**, que es
la única forma de que el test pueda fallar si el filtro se cae—; recuento de sentencias constante
con `tests/sql_counter.py` sobre dos tamaños de página distintos; paginación sobre una ráfaga de
eventos que comparten `created_at`, comprobando que no se repite ni se omite ninguno; y que
`metadata` no aparece en la respuesta.

**Diagrama**: no. El flujo son tres consultas y una composición en memoria, y el §Data &
interfaces ya lo dice con más precisión de la que daría un dibujo.

## Risks & mitigations

- **La migración compite con otras ramas vivas.** Hoy hay cabeza única (`4ba1f499f7c2`), pero hay
  varias sesiones abiertas en paralelo y más de una puede traer migración. Si al fusionar aparecen
  dos cabezas, la resolución es `alembic merge`, no reescribir el `down_revision` de nadie.
- **La composición carga la fila entera de `properties` en memoria** (D5, alternativa rechazada),
  incluidas `access_notes`/`cleaning_notes`/`emergency_notes`. No sale en la respuesta —los campos
  se enumeran uno a uno y `from_attributes` está prohibido por la spec—, pero es la misma forma
  que la entrada de roadmap `incident-list-property-projection` señala como precio a recortar. Si
  esa entrada llega a introducir una proyección estrecha de identidad en `PropertyRepository`,
  este caso de uso es el segundo cliente obvio.
- **Atribución de escritores fuera de `steering/security.md`.** La discusión de OQ1 nombra quién
  escribe `timeline_events.description`, y eso sólo es legítimo aquí: `sdd/changes/` y
  `sdd/roadmap*` están **fuera del censo** del guardián de la regla 11, pero `sdd/specs/` **no**.
  La sección que `/sdd:archive` escriba en `sdd/specs/dashboard-api.md` describe la lectura y no
  atribuye escritor a ninguna columna, o `make check-rule11-ownership` se pone en rojo.
- **`per_page` sigue en 100 y ahora agrega todo el tenant.** Con el índice de D4 la consulta está
  cubierta; lo que crece es el tamaño de la respuesta, que es el mismo techo que ya tienen
  `GET /api/v1/properties` y `GET /api/v1/reservations`. No se baja el techo para no divergir de
  las cotas compartidas del proyecto.
- **El docstring del router afirma hoy que esta ruta no existirá** («*there is no writer here and
  there will not be one*» sigue siendo cierto; «*is out of scope*» deja de serlo). Corregirlo es
  parte de la implementación, no del archive: es código.

## Open questions

### OQ1 — ¿Entra `timeline_events.description` en el censo de la regla 11, y en este change? — **RESUELTA (Jose, 2026-09-04): opción (b)**

**Resolución.** No se añade ninguna fila al censo en este change y no se toca
`sdd/steering/security.md`. Se registra la entrada de roadmap `timeline-description-sink-census`
(ver §Roadmap candidates, que es de donde `/sdd:archive` la toma). El razonamiento de abajo es el
que sostiene la decisión y se conserva entero porque es el dato que esa entrada hereda.

---


El proposal delegó aquí la pregunta del radio de agregación, con una premisa que hay que corregir
antes de contestarla: dice *«más allá de la que ya cubre el lector por propiedad»*, y **no existe
ninguna fila que lo cubra**. `timeline_events.description` no está en el censo de la regla 11 de
`sdd/steering/security.md`, ni lo está `property_state_transitions.reason`, que es de donde sale
su valor.

Lo que se ha medido para poder decidir, en vez de razonarlo:

- De los **15** sitios del árbol que construyen un `TimelineEventData`, **14 pasan
  `description=None`**. El único que pasa un valor es
  `TimelineEventFactory.property_state_changed`, que copia `transition.reason`
  (`backend/app/timeline/domain/services.py:128`).
- Ese `reason` llega hoy por **una sola vía viva**: la cancelación de una tarea de limpieza
  (`backend/app/cleaning/application/use_cases.py:900`), donde lo teclea una persona autenticada,
  acotado por `min_length=1` y `MAX_CANCEL_REASON` en el esquema y por `String(500)` en el DDL.
  Es prosa de una persona sobre su propio ámbito — la forma de la **excepción 3**.
- Las cuatro transiciones manuales que también exigen `reason`
  (`OWNER_BLOCKED`, `PROPERTY_MARKED_OUT_OF_SERVICE`, `PROPERTY_REACTIVATED`,
  `OWNER_MANAGER_UNBLOCKED`) **no tienen todavía ningún llamante** fuera de la máquina de estados
  y sus tests, aunque el docstring de la ruta por propiedad y `sdd/specs/dashboard-api.md` ya las
  describan como el caso típico.

Y lo que este change hace con esa columna: **la lee en bulto**. No amplía el permiso, ni los
roles, ni el conjunto de valores alcanzables (D10); lo que cambia es que una respuesta puede
llevar la de todas las viviendas en vez de la de una.

Los dos precedentes del árbol apuntan en direcciones distintas y el discriminante entre ellos es
si **crece la audiencia**: `tech-incident-context` era lector y **sí** metió
`properties.access_notes` en el censo, porque estrenaba un rol (`TECHNICIAN`) que antes no
alcanzaba la columna; `cleaner-photo-requirements` era lector y **no** lo hizo con el `label` de
las plantillas, con su motivo escrito —«no abre audiencia nueva … al mismo permiso y a los mismos
tres roles»— y dejó la entrada de roadmap `template-label-sink-census`. Aquí la audiencia no
crece.

**Opciones:**

- **(a) Añadir la fila (o dos) al censo en este change**, con el escritor atribuido a `cleaning`
  y la forma de la excepción 3, y `sdd/steering/security.md` editado por una tarea de este change
  (es como entraron las excepciones 5 y 6). Cierra el hueco donde vive la autoridad.
- **(b) No añadir fila aquí; registrar la entrada de roadmap** (p. ej.
  `timeline-description-sink-census`) que decida las dos columnas, su forma, y si el bulto de este
  feed pide alguna mitigación. Es el precedente exacto de `cleaner-photo-requirements` y respeta
  que el censo se hace **por escritor** y este change no escribe nada. **Recomendada.**
- **(c) Sacar `description` del feed de tenant** —el remedio con la forma del problema que pagó la
  excepción 6 al salir del listado paginado—, dejando la `description` sólo en la ruta por
  propiedad. **Esto enmienda R3.1 del proposal**, que exige los mismos campos que la ruta hermana,
  así que la enmienda tiene que bajar al `proposal.md` antes de `/sdd:tasks`.

Recomiendo **(b)**: la audiencia no crece, el censo se hace por escritor y este change no lo es, y
(c) mutila el widget que la entrada existe para alimentar por un riesgo que hoy no tiene ni
escritor de instrucciones de acceso detrás. Lo que (b) **no** hace es dar el hueco por bueno: la
entrada de roadmap queda con dueño y con los datos medidos de arriba dentro.

## Roadmap candidates

Para `/sdd:archive`, que es el único que escribe el roadmap. **Nada de esto entra en
`sdd/specs/`**: `sdd/roadmap.md` y `sdd/roadmap/` están fuera del censo del guardián de la regla
11, así que la atribución de escritor puede ir ahí; en una spec se pondría en rojo.

- **`timeline-description-sink-census`** — [TECH] **`timeline_events.description` y
  `property_state_transitions.reason` no tienen fila en el censo de la regla 11 de
  `sdd/steering/security.md`**, que es la autoridad y el único sitio donde eso se declara. Medido
  en el design de `dashboard-activity-feed` (2026-09-04): de los 15 sitios del árbol que
  construyen un `TimelineEventData`, 14 pasan `description=None`; el único valor vivo lo copia
  `TimelineEventFactory.property_state_changed` desde `transition.reason`
  (`backend/app/timeline/domain/services.py:128`), y ese `reason` llega hoy por una sola vía: la
  cancelación de tarea de limpieza (`backend/app/cleaning/application/use_cases.py:900`), donde lo
  teclea una persona autenticada, acotado por `min_length=1`/`MAX_CANCEL_REASON` en el esquema y
  por `String(500)` en el DDL — prosa de una persona sobre su propio ámbito, la forma de la
  excepción 3. Las cuatro transiciones manuales que también exigen `reason` (`OWNER_BLOCKED`,
  `PROPERTY_MARKED_OUT_OF_SERVICE`, `PROPERTY_REACTIVATED`, `OWNER_MANAGER_UNBLOCKED`) todavía no
  tienen ningún llamante fuera de la máquina de estados y sus tests, aunque el docstring de
  `GET /api/v1/timeline/{property_id}` y `sdd/specs/dashboard-api.md` ya las describan como el
  caso típico. **Decide**: si las dos columnas entran en el censo y con qué forma, y si el bulto
  del feed de tenant (`GET /api/v1/timeline`, que devuelve la `description` de todas las viviendas
  en una respuesta) pide alguna mitigación de las de la excepción 6. **Lo que no lo motiva**: la
  audiencia no creció con `dashboard-activity-feed` — mismo permiso `READ_PROPERTIES`, mismos dos
  roles, y los mismos valores ya eran alcanzables con N peticiones a la ruta por propiedad; por
  eso aquel change no añadió la fila, siguiendo el precedente de `cleaner-photo-requirements` y su
  entrada `template-label-sink-census` (no está en el plan original, decidido en el gate de
  `/sdd:design` de `dashboard-activity-feed`, OQ1, el 2026-09-04)
  `size: S · kind: tech`
