# Design: dashboard-api

## Context

El backend monta 11 routers y 45 rutas (`backend/app/main.py:65-92`), ninguna de las que
alimentan el dashboard. Lo que ya existe y este diseño reutiliza en vez de reinventar:

- **La composición sin N+1 ya tiene precedente**: `AdvancePropertyStatesUseCase`
  (`backend/app/properties/application/use_cases.py:300-310`) lee las reservas de *todas* las
  propiedades candidatas con `ReservationRepository.list_for_properties` y las agrupa en
  memoria. Es exactamente la forma que R1.7 necesita, y ya está en el árbol.
- **La proyección PII-safe ya tiene precedente**: `GuestSummary`
  (`backend/app/guests/domain/value_objects.py:24-39`) es un `frozen dataclass` sin
  `document_number_encrypted`, «so no future serialiser can reach a field that is not here».
- **El aislamiento por tenant es doble**: cada método de repositorio toma `tenant_id`
  explícito, y además `bind_session_to_tenant` (`backend/app/core/db.py:132-162`) marca la
  sesión y filtra globalmente toda tabla con `TenantScopedMixin`.
- **El estado operacional ya se resuelve** en `ContextualStateResolver`
  (`backend/app/properties/domain/state_resolution.py`), y `steering/backend.md` prohíbe
  recalcularlo fuera de `PropertyStateMachine`.
- **El timeline es escritura pura**: su puerto sólo tiene `add`, y
  `backend/app/timeline/domain/repositories.py:10-11` deja dicho que *«reading events back
  belongs to the change that introduces the timeline endpoints»* — este change.
- **`maintenance` y `statements` son sólo estructura de datos**: `domain/entities.py` +
  `infrastructure/models.py`, sin `application/` ni puertos, la forma que
  `steering/backend-architecture.md:140` describe para dominios sin caso de uso todavía.

## Decisions

### D1 — Un módulo `app/dashboard/` para el agregado, no una ampliación de `properties`

**Chosen:** dominio nuevo `backend/app/dashboard/` con `domain/`, `application/` y `api/`, y
**sin `infrastructure/` propia**: compone los puertos que ya poseen los demás dominios. El
agregado de PRD §9.2 toca siete dominios (properties, reservations, cleaning, maintenance,
statements, guests, access) más timeline; alojarlo en `properties/application/` convertiría a
`properties` —que ya custodia la invariante de la máquina de estados— en un hub que importa
otros siete módulos.

Es la misma divergencia que `steering/architecture.md:13` ya documentó para `reviews` y
`audit`: dominios que no están en la lista de PRD §3.2 y se justifican por lo que son. Aquí,
además, es el lado de lectura de un CQRS pobre — no hay entidad nueva ni tabla nueva.

Rejected: `properties/application/dashboard_use_cases.py` — acopla el dominio con invariante
a seis que no la tienen.
Rejected: un read model con SQL propio que haga JOIN entre las siete tablas — es el
«repositorio Dios» que `steering/backend-architecture.md:147` prohíbe, y deja el filtro de
tenant en manos de un único SELECT escrito a mano.

### D2 — Sin `infrastructure/` propia: lectores por lotes en el puerto de cada dominio

**Chosen:** cada dominio gana un método de lectura por lotes en **su** puerto, con la firma
que `ReservationRepository.list_for_properties` ya estableció, y el caso de uso del dashboard
agrupa en memoria. El coste queda en **un número fijo de consultas** (≈5 para la colección),
independiente del número de propiedades — que es lo que R1.7 exige y lo que un test
verificará contando sentencias.

| Dominio | Método nuevo (lectura) |
|---|---|
| `properties` | reutiliza `list` (ya existe, paginado) |
| `reservations` | reutiliza `list_for_properties` (ya existe) |
| `cleaning` | `list_live_for_properties(tenant_id, property_ids)` |
| `maintenance` | `count_open_for_properties` + `list_open_for_property` (**puerto nuevo**) |
| `timeline` | `last_for_properties` + `list_for_property` (**lectura nueva en el puerto**) |
| `properties` (transiciones) | `last_for_property` en `PropertyStateTransitionRepository` |
| `statements` | `summary_for_property` (**puerto nuevo**, devuelve vacío hoy) |
| `guests` | `list_for_ids` (**añadida al implementar la sección 6**) |

La fila de `guests` faltaba en la primera redacción de esta tabla, y el panel de arquitectura
de la sección 6 lo señaló: D1 nombra `guests` entre los siete dominios que el agregado
compone, y la card lleva `guestName` (`dto.ts:72`), así que un `get` por card es exactamente
el N+1 que R1.7 prohíbe. El lector por lotes tiene la misma forma que los demás y devuelve
`GuestSummary`, nunca la entidad.

`maintenance` y `statements` pasan por primera vez de «sólo estructura de datos» a tener
puerto y adaptador. Se crea **sólo la mitad de lectura**: sin `add`, sin `save`. La escritura
llega con `maintenance` y `revenue`, y la firma es donde eso queda dicho — el mismo argumento
que `TimelineEventRepository` usa para tener sólo `add`.

Rejected: que `app/dashboard/infrastructure/` tenga su propio adaptador SQL — duplicaría el
mapeo ORM→entidad de siete dominios y sería el segundo sitio donde se escribe el scope de
tenant.

### D3 — El locale viaja en `RequestContext`, no en una consulta extra ni en `Accept-Language`

**Chosen:** añadir `preferred_language` a `RequestContext`
(`backend/app/auth/domain/context.py`). El valor **ya está cargado**: `get_authenticated_request`
relee el usuario de la base de datos en `backend/app/auth/api/dependencies.py:223` y construye
el contexto en `:239` descartándolo. Es una línea, cuesta cero consultas, y todo endpoint
futuro lo hereda.

Rejected: `Accept-Language` — PRD:205 dice «idioma del dashboard: preferencia del usuario
autenticado», que es la fila, no el navegador.
Rejected: una dependencia que relea el usuario — una consulta por petición para un dato que
la petición ya tenía en la mano.

**Coste que hay que declarar**: esto toca `auth`, así que `sdd/specs/auth-tenancy.md` entra en
las specs afectadas, cosa que el proposal no listaba.

### D4 — El catálogo de mensajes vive en el dominio que posee el vocabulario

**Chosen:** `app/core/i18n.py` aporta sólo el mecanismo (el tipo `Locale`, con `es`/`en`, y un
`Catalog` que resuelve clave+locale→plantilla y formatea con `metadata`); **las tablas de
mensajes viven en el `domain/` de quien posee el vocabulario**:

- `app/timeline/domain/rendering.py` — 45 `TimelineEventType` × 2 idiomas.
- `app/dashboard/domain/labels.py` — estados de limpieza, próxima acción, títulos de
  incidencia y de aprobación.

Que una traducción viva en `domain/` no es una violación de la regla de dependencia: son
`str` y `dict`, Python puro, sin `pydantic` ni `sqlalchemy`. Y hay precedente explícito de que
*una regla de presentación exigida por el producto es una regla de dominio*:
`app/access/domain/masking.py` alojó el enmascarado en `domain/` porque «the rule is a business
constraint and not a rendering detail». PRD §10 hace exactamente eso con la legibilidad.

Rejected: el catálogo en `api/schemas.py` — las cards, el detalle y el timeline necesitan el
mismo, y quedaría copiado en tres routers.
Rejected: un `app/core/i18n.py` que contenga también los mensajes — `architecture.md` reserva
`core/` para infraestructura compartida, «no aloja entidades de negocio».

### D5 — El renderizado lee `metadata`, y degrada al `title` almacenado

**Chosen:** `TimelineEventRenderer.render(event, locale) -> RenderedEntry` compone **`title`**
desde `event_type` + `metadata`. Si el tipo no está en el catálogo, devuelve el `title`
almacenado tal cual (R5.4).

**`description` no se compone: se pasa tal cual, y es una decisión, no una omisión.** Esta
decisión decía en su primera redacción «compone `title` y `description`», y se corrigió al
revisar la feature (2026-08-09). Lo que los escritores guardan en `description` es texto
**humano**, no de sistema: `PropertyStateTransition.reason`
(`app/timeline/domain/services.py:128`) lo teclea una persona, y `PropertyStateMachine` lo
exige precisamente para bloquear, desbloquear o poner fuera de servicio. No hay `metadata`
desde la que componerlo, y traducirlo sería reescribir lo que dijo un operador. Queda
declarado como `ASSUMPTION` en R5.1 del proposal, escrito en
`app/timeline/domain/rendering.py:280-283` y fijado por
`backend/tests/timeline/test_rendering.py:253-259`.

Nota que hereda quien lea este campo después: al ganar `timeline` su capa `api/`, este change
es el **primer lector** de esa columna. `description` no está entre las seis columnas que
`steering/security.md` regla 11 enumera como sumideros de texto en claro, pero es de la misma
clase que las que D12 se niega a publicar en `notes`. Hoy no hay cruce de privilegio —los dos
únicos roles con `READ_PROPERTIES` tienen también `READ_ACCESS_RECORDS`, y
`tests/auth/test_policy.py:146` lo mantiene así—, así que la decisión de publicarla se toma a
sabiendas; el primer rol de sólo-auditoría que se añada obliga a revisarla.

La columna `title` no se modifica nunca: sigue siendo la copia de auditoría en inglés que
escribió `TimelineEventFactory`, coherente con `steering/backend.md` («mensajes de sistema,
logs y errores técnicos en inglés») y con la inmutabilidad de
`steering/architecture.md:21`. La degradación existe para un `TimelineEventType` **futuro**,
no para un olvido de hoy: un test recorre el enum y exige entrada en ambos idiomas, así que
un tipo nuevo sin traducir rompe la suite en vez de colarse en producción hablando inglés.

Riesgo asumido y declarado: los eventos ya escritos sólo tienen la `metadata` que su factoría
guardó. `property_state_changed` guarda `from_state`/`to_state`/`trigger`, suficiente para
renderizar. Un tipo cuya plantilla pida un dato que su factoría nunca guardó cae a la
degradación — correcto, no silencioso, y detectable con un test por tipo.

Rejected: reescribir `title` al idioma de cada usuario — imposible, el timeline es inmutable
y hay N usuarios por fila.
Rejected: devolver una clave y que traduzca el frontend — contradice `dto.ts:28-34`
(`LocalizedText` es *data*, no *chrome*) y obligaría a `dashboard-web` a mantener 45 claves.

### D6 — `nextAction` es una tabla de reglas determinista, marcada `ASSUMPTION`

**Chosen:** una función pura en `app/dashboard/domain/next_action.py` que mapea
`PropertyOperationalState` → `(clave de acción, responsable)`. PRD §9.1 pide «próxima acción
requerida y responsable» y da un ejemplo (`Limpiadora: María — pendiente de aceptar`) pero
**no define la tabla**, así que se escribe aquí y se marca `ASSUMPTION` en el código como
exige `project.md`. Acordada con el usuario en el gate de diseño:

| Estado | Acción | Responsable |
|---|---|---|
| `AWAITING_CLEANING` | Asignar limpiadora | manager |
| `CLEANING_SCHEDULED` | Pendiente de aceptar | limpiadora asignada |
| `CLEANING_IN_PROGRESS` | Limpieza en curso | limpiadora asignada |
| `AWAITING_CHECKIN` | Entregar acceso | manager |
| `MAINTENANCE_REQUIRED` | Revisar incidencia | `null` (hasta `maintenance`) |
| `CRITICAL_INCIDENT` | Atender incidencia | `null` (hasta `maintenance`) |
| `OCCUPIED_ESTIMATED`, `READY_FOR_NEXT_GUEST`, `VACANT_READY`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` | `nextAction: null` | — |

**El responsable es un rol, no una persona.** Se descartó resolver el nombre real («María
G.») porque cuesta una consulta más y, sobre todo, porque «el manager» no está definido
cuando un tenant tiene varios — una decisión que el PRD no toma y que este change no debe
inventar. Los once estados están cubiertos: la función es exhaustiva sobre el enum y un test
lo verifica, de modo que un estado nuevo rompa la suite en vez de devolver `null` en
silencio.

Rejected: derivarla en el frontend — `sdd/specs/dashboard-web-frontend.md` es explícito:
«THE SYSTEM SHALL NOT compute operational state, colors, or the next action in the component».
Rejected: dejar `nextAction: null` hasta que el PRD la defina — es el campo que responde la
pregunta del principio 2 de `product.md`.

### D7 — Ruta de la colección: `/api/v1/dashboard/properties`, no `/api/v1/properties/dashboard`

**Chosen:** desviarse del texto de R1.1 del proposal. Dos motivos, y el segundo es el que
manda:

1. **Colisión de rutas.** `/properties/dashboard` y `/properties/{id}` compiten en FastAPI,
   que resuelve por orden de registro: si `properties_router` se monta antes, `dashboard` se
   parsea como `{id}` y el endpoint responde 422 en vez de existir. Es un fallo que depende
   del orden de dos líneas de `main.py` y de en qué router acabe cada ruta.
2. **Las rutas que el PRD sí nombra se quedan literales.** §23:1942-1943 nombra
   `/properties/{id}/state` y `/properties/{id}/dashboard`; ésas no se tocan. La colección es
   la única invención de este change (R1 lo declara), así que es la única que puede moverse, y
   ponerla bajo su propio prefijo hace visible qué parte es PRD y qué parte es extensión.

Reparto resultante de rutas por módulo:

| Ruta | Router | Por qué ahí |
|---|---|---|
| `GET /api/v1/dashboard/properties` | `app/dashboard/api/router.py` | agregado multi-dominio, prefijo propio |
| `GET /api/v1/properties/{id}/dashboard` | `app/dashboard/api/router.py` (prefijo `/properties`) | agregado multi-dominio con ruta que fija el PRD |
| `GET /api/v1/properties/{id}/state` | `app/properties/api/router.py` | lectura de un solo dominio, del módulo que posee la columna |
| `GET /api/v1/timeline/{property_id}` | `app/timeline/api/router.py` (**capa `api/` nueva**) | dominio propio |

Precedente para un router que sirve un prefijo de otro módulo: `users_router` vive en `auth` y
sirve `/users` (`main.py:67-70`).

Rejected: `/properties/dashboard` con orden de registro fijado por un test — pone una garantía
de contrato en manos de un orden de líneas.

### D8 — Orden y paginación del timeline

**Chosen:** `ORDER BY created_at DESC, id DESC`, `LIMIT/OFFSET` como el resto del proyecto.
El índice `ix_timeline_events_property_id_created_at` (`property_id`, `created_at DESC`) ya
existe y cubre el caso principal; `ix_timeline_events_tenant_id_event_type_created_at` cubre
el filtro por tipo. El desempate por `id` no está en el índice, así que ordena en memoria
**dentro de un mismo instante**, que es un puñado de filas — y sin él la paginación repite u
omite entradas, que es el fallo que R4.1 nombra.

`occurredAt` del DTO mapea a `created_at`: la tabla no tiene otra columna temporal, y
`TimelineEventFactory` la recibe como el instante en que ocurrió, no en que se insertó.

Rejected: cursor sobre `(created_at, id)` — más correcto bajo escritura concurrente, pero el
contrato del frontend (`PaginatedResponse` con `page`/`total_pages`, `dto.ts:20-26`) es de
offset, y cambiarlo obliga a reescribir la otra mitad.

### D9 — Los bloques sin escritor se leen igual, y `access` no puede filtrar nada

**Chosen:** el caso de uso consulta las tablas reales de `incidents`, `owner_approvals` y
`expenses` y devuelve lista vacía o `null`. Cuando `maintenance` y `revenue` entren, se
pueblan sin tocar el contrato (R2.3).

`lastCleaningPhotos` devuelve `[]` con `EXTERNAL_DEPENDENCY` (R2.4): `cleaning_photos` guarda
`storage_key`, y firmarlo es `StorageAdapter.get_signed_url`, que entrega
`cleaning-photos-storage`. **El puerto de `cleaning` no gana método de fotos en este change**,
para no colisionar con esa rama.

Sobre R2.5 hay una garantía que conviene registrar porque **es estructural y no una
precaución**: el código de acceso en claro no existe en la base de datos.
`app/access/domain/masking.py` documenta que `AccessRecordModel` no tiene columna para él y
que «the plaintext never leaves the request handler». `AccessStatus.label` es, por tanto, una
etiqueta de estado y no hay nada que enmascarar. El huésped se proyecta con `GuestSummary`,
que ya excluye el documento por construcción.

### D10 — Permisos: `READ_PROPERTIES` en la ruta, y redacción por bloque según el origen

**Chosen:** las tres rutas del dashboard declaran `require(Permission.READ_PROPERTIES)`, y
**además** el caso de uso omite cada bloque cuyo permiso de origen no tenga el rol que llama
(`READ_RESERVATIONS` → reserva y huésped; `READ_CLEANING_TASKS` → limpieza;
`READ_ACCESS_RECORDS` → acceso). `is_allowed(role, permission)` ya es una función pura de
`app/auth/domain/policy.py`, así que la comprobación no necesita infraestructura.

El motivo es que **agregar no puede conceder**: `require()` acepta un solo permiso
(`dependencies.py:250`), de modo que una ruta con `READ_PROPERTIES` a secas entrega en una
respuesta lo que cuatro permisos distintos protegen por separado. Hoy no se observa —
`TENANT_OWNER` y `PROPERTY_MANAGER` tienen los cuatro (`policy.py`, `ROLE_PERMISSIONS`), y
`CLEANER`/`TECHNICIAN` no tienen `READ_PROPERTIES` y no pasan de la puerta. Se observaría en
el primer rol que se añada, y ahí ya sería una fuga en producción y no una decisión de diseño.

Rejected: sólo `require(READ_PROPERTIES)` — hoy equivalente, y convierte cada rol futuro en
una revisión de seguridad que nadie recordará hacer.
Rejected: cambiar `require()` para aceptar varios permisos — toca la superficie de `auth` que
recorre `tests/test_route_authorization.py`, y exigir la conjunción negaría el dashboard a un
rol que legítimamente sólo deba ver parte.

### D11 — 404 indistinguible, heredado y no reinventado

**Chosen:** todos los métodos de repositorio toman `tenant_id` y devuelven `None` fuera de él,
que es lo que `app/properties/domain/repositories.py:30-33` describe como el mecanismo por el
que un id ajeno responde 404 y no 403. Las cuatro rutas se apoyan en eso; no hay comprobación
de tenant escrita a mano en el router.

### D12 — `PropertyDetail.notes` viaja siempre `null`, y es una decisión

**Chosen:** el campo `notes` de PRD §9.2 se declara en el contrato y **no se rellena en este
change**. Añadida durante la implementación de la sección 5, a petición del panel de
seguridad, que señaló que el tipo no daba ninguna señal estructural a quien fuera a cablear
el caso de uso.

No hay columna que lo posea. Los únicos candidatos son `access_notes`, `cleaning_notes` y
`emergency_notes` de `properties`, y `app/properties/application/property_admin.py:53-58` ya
los nombra como sumideros de texto en claro de la regla 11: *«an operator can paste a door
code or a wifi key into "access notes"»*. Volcar uno en una respuesta que lee cualquier
portador de `READ_PROPERTIES` publicaría justo lo que las reglas 3 y 4 cifran y enmascaran
en todas partes.

El campo se queda en el contrato para que `dashboard-web` no cambie de forma después, y lo
rellena el change que dé a las notas de operación una columna propia. Marcado `ASSUMPTION`
en `read_models.py` y verificado por un test que afirma que el agregado nunca devuelve el
contenido de ninguna de las tres columnas.

Rejected: enmascarar la nota — la regla 11 dice que «la forma estructurada es el defecto: el
valor no sobrevive en absoluto, ni siquiera enmascarado».
Rejected: quitar el campo del contrato — obligaría a `dashboard-web` a cambiar de forma dos
veces, y `dto.ts` ya lo declara.

## Changes by area

| Area | Files | Change |
|---|---|---|
| dashboard (nuevo) | `backend/app/dashboard/domain/{read_models,labels,next_action,financials}.py` | proyecciones `frozen`, catálogo de etiquetas, tabla de próxima acción, regla de moneda (todo puro) |
| guests | `backend/app/guests/{domain,infrastructure}/repositories.py` | `list_for_ids`, el lector por lotes que la card necesita (D2) |
| dashboard (nuevo) | `backend/app/dashboard/application/use_cases.py` | `GetDashboardCardsUseCase`, `GetPropertyDashboardUseCase` |
| dashboard (nuevo) | `backend/app/dashboard/api/{router,schemas,dependencies}.py` | dos rutas + Pydantic de respuesta + wiring |
| timeline | `backend/app/timeline/api/{router,schemas,dependencies,errors}.py` | **capa `api/` que no existe** |
| timeline | `backend/app/timeline/application/use_cases.py` | **capa `application/` que tampoco existe** — `GetPropertyTimelineUseCase`. Omitida en la primera redacción de esta tabla y añadida al implementar la sección 2: `steering/backend-architecture.md` prohíbe a `api/` el "acceso a `infrastructure/` directo — siempre a través de un caso de uso", así que sin ella el router tendría que instanciar los adaptadores él mismo |
| timeline | `backend/app/timeline/domain/{repositories,rendering}.py` | lectura en el puerto; catálogo + renderer |
| timeline | `backend/app/timeline/infrastructure/repositories.py` | implementación de la lectura |
| properties | `backend/app/properties/api/router.py` | ruta `/{id}/state`; corregir el comentario `:10` (R6.3) |
| properties | `backend/app/properties/domain/repositories.py` | `last_for_property` en `PropertyStateTransitionRepository` |
| cleaning | `backend/app/cleaning/domain/repositories.py` + `infrastructure/` | `list_live_for_properties` |
| maintenance | `backend/app/maintenance/{domain/repositories.py,infrastructure/repositories.py}` | **primer puerto del módulo**, sólo lectura |
| statements | `backend/app/statements/{domain/repositories.py,infrastructure/repositories.py}` | **primer puerto del módulo**, sólo lectura |
| auth | `backend/app/auth/domain/context.py`, `api/dependencies.py` | `preferred_language` en `RequestContext` (D3) |
| core | `backend/app/core/i18n.py` | `Locale` + `Catalog` (mecanismo, sin mensajes) |
| main | `backend/app/main.py` | montar `dashboard_router` y `timeline_router` |
| contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados (R6.1-6.2) |
| docs | `docs/properties.md:109`, `docs/dashboard.md:5-10` | renombrados del split (R6.3) |

## Data & interfaces

**Sin migración.** Ninguna tabla, columna, índice ni enum nuevos: los cuatro endpoints leen
lo que ya existe. Es lo que hace este change aditivo y reversible.

**Sin variables de entorno nuevas.** Los idiomas soportados (`es`, `en`) son los de
`User.preferred_language`, que ya tiene default `es` en el esquema
(`app/auth/infrastructure/models.py:51`).

Firmas nuevas, en forma abreviada:

```python
# app/timeline/domain/repositories.py — se AÑADE a la lectura; add() sigue siendo el único escritor
class TimelineEventReader(Protocol):
    async def list_for_property(
        self, tenant_id: UUID, property_id: UUID, *,
        filters: TimelineFilters, page: int, per_page: int,
    ) -> Page[TimelineEvent]: ...
    async def last_for_properties(
        self, tenant_id: UUID, property_ids: Sequence[UUID]
    ) -> dict[UUID, TimelineEvent]: ...

# app/core/i18n.py — mecanismo, sin mensajes
class Locale(str, enum.Enum): ES = "es"; EN = "en"
```

Un `Protocol` de lectura **separado** de `TimelineEventRepository`, y no métodos añadidos al
existente: es Interface Segregation aplicado como pide `backend-architecture.md:109`, y
mantiene intacta la propiedad que el escritor exhibe hoy — que su firma no admite otra cosa
que `add`.

## Risks & mitigations

- **La colección se degrada a N+1 sin que nadie lo note.** Un `for` en el caso de uso que
  llame a un `get` por propiedad es sintácticamente idéntico al código correcto. Mitigación:
  el test de R1.7 cuenta sentencias con un listener de SQLAlchemy y fija un techo constante;
  no es una métrica, es un aserto.
- **`cleaning_photos` y `cleaning_checklist_completions` no llevan `TenantScopedMixin`**
  (`app/cleaning/infrastructure/models.py:97,117`), así que el filtro global no las cubre y se
  alcanzan por `cleaning_task_id`. Este change no las lee (D9), pero queda anotado para
  `cleaning-photos-storage`, que sí lo hará.
- **`preferred_language` es `String(5)` sin restricción a `es`/`en`.** Una fila con otro valor
  debe degradar a `es`, no reventar. Mitigación: `Locale` se resuelve con fallback explícito y
  un test cubre el valor desconocido.
- **Colisión con `cleaning-photos-storage`**, en curso en paralelo: ambos tocan
  `app/cleaning/domain/repositories.py`. El nuestro añade un lector por lotes; el suyo, fotos.
  Conflicto de merge probable pero trivial (métodos distintos). No se toca nada de fotos aquí.
- **Rendimiento del agregado de detalle**: son ~8 consultas por propiedad, sin JOIN. Con dos
  viviendas es irrelevante; la primera medición real que lo contradiga es motivo para un read
  model materializado, no para adelantarlo ahora.

## Open questions

Ninguna. Las tres que este diseño abrió se resolvieron en su gate (2026-08-09) y están
incorporadas arriba:

1. **Ruta de la colección** → `GET /api/v1/dashboard/properties` (D7). **R1.1 del proposal
   quedó corregido en consecuencia**; las dos rutas que PRD §23:1942-1943 nombra siguen
   literales.
2. **Redacción por bloque** → se implementa ahora (D10), no se deja como deuda.
3. **Tabla de `nextAction`** → acordada, con responsable expresado como rol (D6).
