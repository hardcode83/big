# Design: guest-portal-messaging

## Context

El pipeline de `messaging-ai` está entero y tiene un solo emisor: `POST /api/v1/conversations/{id}/messages`
en `backend/app/messaging/api/router.py`, con `MANAGE_CONVERSATIONS`. Su núcleo,
`ProcessInboundGuestMessageUseCase` (`backend/app/messaging/application/use_cases.py:152`), hace los nueve
pasos en **una transacción y un `commit()`**, y su único parámetro que no se puede satisfacer desde el portal
es `actor_user_id: uuid.UUID`, que viaja exclusivamente hasta `_open_incident` →
`IncidentReportingPort.report` (`backend/app/messaging/domain/ports.py`), implementado por
`ReportIncidentFromConversationUseCase` (`backend/app/maintenance/application/use_cases.py:248`).

El portal anónimo son cuatro rutas en `backend/app/guests/api/portal_router.py`, todas pasando por el helper
`_authorised` (probe → authorize → record_failed → request_allowed) y devolviendo un `404` constante. Su
autorizador devuelve un `GuestSession` frozen (`backend/app/guests/domain/portal_ports.py`) con
`tenant_id`, `reservation_id`, `property_id`, `guest_id` y `token_hash`, y liga la sesión de BD al tenant.
Ese router ya importa un caso de uso de **otro módulo** (`ReportGuestIncidentUseCase` de `maintenance`),
cableado en `backend/app/guests/api/portal_dependencies.py`: el precedente de que la capa `api/` del portal
es la que conoce dos módulos.

En el front, `frontend/features/guest-portal/` monta tres secciones bajo un gate de `useStayInfo`
(`components/guest-portal-view.tsx:246`), con cliente `createApiClient({ baseUrl: "" })` **sin `getHeaders`**
y `retryPolicy` que ya no reintenta ningún `4xx`. No hay una sola llamada con `refetchInterval` en todo
`frontend/` — este change estrena el polling — ni un `WebSocket`/`EventSource` en front ni en back
(verificado por grep en `frontend/features|lib|app` y `backend/app`), lo que confirma la afirmación de
alcance del proposal. `MockAIAdapter` sigue siendo el único implementador de `AIAdapter`, también
verificado.

## Decisions

### D1 — `PORTAL` es miembro nuevo de `ConversationChannel`, con adapter propio

**Chosen:** añadir `PORTAL` a `ConversationChannel` (`backend/app/messaging/domain/enums.py`) y registrar un
`PortalOutboundAdapter` en el `dict` de `outbound_registry()`
(`backend/app/messaging/infrastructure/channels.py`), cuya entrega es la fila que lee
`GET /api/v1/guest/messages/{token}`. `contact_kind_for` **no gana entrada**: devuelve `None` por ausencia,
como `MANUAL`, y eso es lo correcto — el portal no direcciona a nadie.

Es un adapter propio y no una segunda clave apuntando a `PanelOutboundAdapter` porque el docstring de esa
clase fija su condición de verdad: *«Reporting success is therefore a true statement — and it is only true
because that endpoint exists (R7.1). If it ever goes away, this adapter is a lie»*. Su endpoint es el del
manager; el nuestro es el del huésped. Dos promesas distintas necesitan dos clases, cada una nombrando el
endpoint que la sostiene.

Rejected: reutilizar `MANUAL` — miente sobre quién lee la fila (R3.1).
Rejected: registrar `PORTAL: PanelOutboundAdapter()` — una clase con dos condiciones de verdad; borrar
cualquiera de los dos endpoints la deja mintiendo sin que nadie lo note.

### D2 — Las dos rutas viven en el portal; el comportamiento vive en `messaging`

**Chosen:** `GET`/`POST /api/v1/guest/messages/{token}` se declaran en
`backend/app/guests/api/portal_router.py`, usando el mismo `_authorised` sin una segunda copia del orden
(R1.2), y delegan en **dos puertos declarados en `backend/app/guests/domain/portal_ports.py`** que
`messaging` implementa en un módulo nuevo `backend/app/messaging/application/portal.py`. El cableado va en
`backend/app/guests/api/portal_dependencies.py`.

Es exactamente la forma de `IncidentReportingPort`: el puerto en el `domain/` del **consumidor**, el
implementador en el `application/` del **dueño**, y el cableado en la única capa con derecho a conocer los
dos módulos (D12 de `messaging-ai`). Y es la única disposición que deja `_authorised` como un solo sitio:
un router propio en `messaging` tendría que copiar la secuencia de cuatro pasos, que es justo lo que R1.2
prohíbe.

Rejected: un router nuevo en `messaging/api/` — duplica el orden de autorización, que es el contrato de
seguridad.
Rejected: que `guests` importe `messaging.domain.entities.Message` y proyecte ahí — construiría la
proyección de R2.4 en un módulo que no posee los campos que debe excluir.

### D3 — Dos puertos, no uno

**Chosen:** `GuestPortalThreadReader` (leer el hilo) y `GuestPortalMessageSubmitter` (escribir un mensaje),
ambos en `guests/domain/portal_ports.py`. Preguntas distintas con implementadores distintos: uno proyecta
filas, el otro corre un pipeline transaccional entero. Es el mismo criterio con el que ese fichero ya separa
`GuestPortalStayReader` de `PortalStayLocator`.

Rejected: un puerto con dos métodos — junta una lectura barata con la escritura más cara del sistema bajo un
solo nombre, y `steering/backend-architecture.md` pide puertos por rol.

### D4 — La proyección congelada y sus dos vocabularios cerrados

**Chosen:** en `guests/domain/portal_ports.py`, junto a `StayInfo` y por su misma razón declarada («el
listado de campos *es* el control de seguridad»):

```python
class PortalMessageSender(str, enum.Enum):   GUEST = "GUEST";  PROPERTY = "PROPERTY"
class PortalThreadState(str, enum.Enum):     AUTOMATIC = "AUTOMATIC";  AWAITING_HUMAN = "AWAITING_HUMAN"

@dataclass(frozen=True)
class PortalMessage:  id: uuid.UUID; sender: PortalMessageSender; content: str; created_at: datetime

@dataclass(frozen=True)
class PortalThread:   items: tuple[PortalMessage, ...]; total: int; page: int; per_page: int
                      state: PortalThreadState
```

No hay `sender_user_id`, `ai_generated`, `confidence_score`, `intent`, `metadata`, `conversation_id` ni
razón de escalación: no existen como campos, así que ningún serializador futuro puede filtrarlos (R2.2,
R2.4). El `201` de la escritura devuelve un `PortalMessage`, no un cuerpo propio — un solo tipo publicado.

`PortalThreadState` es un enum de dos miembros y no un `bool` porque el front conmuta sobre un nombre para
elegir su copia localizada (R5.6), y porque un booleano llamado `awaiting_human` invita a que alguien le
cuelgue el porqué al lado.

La agrupación de remitente es un `dict[MessageSenderType, PortalMessageSender]` **total** en el
implementador, con un test que afirma `set(mapa) == set(MessageSenderType)`: un miembro nuevo de
`MessageSenderType` rompe el test en vez de caer por defecto en `PROPERTY`.

Rejected: exponer `sender_type` tal cual y agrupar en el cliente — R2.2 y R5.5 lo prohíben, y el cliente es
el sitio donde la distinción IA/persona volvería a ser derivable.
Rejected: reutilizar `MessageResponse` de `messaging/api/schemas.py` — publica seis campos internos.

### D5 — El pipeline se reutiliza entero; el caso de uso nuevo solo resuelve la conversación

**Chosen:** `PostPortalGuestMessageUseCase` (en `messaging/application/portal.py`) hace dos cosas: resuelve
o crea la conversación `PORTAL` de la estancia, y llama a `ProcessInboundGuestMessageUseCase.execute(...)`,
que sigue siendo el dueño del único `commit()`. **No construye ningún `Message`.**

Eso hace que R1.4 («entero y sin duplicarlo») sea estructural y no una promesa, y tiene una consecuencia que
conviene decir en voz alta: el censo de la regla 11 cuenta *casos de uso que escriben `messages.content`*, y
ese número **no se mueve** — siguen siendo los dos de `messaging/application/use_cases.py`.

Comparten `AsyncSession`, así que la conversación creada y el mensaje caen en la misma transacción sin
necesidad de un `UnitOfWork` extra.

Rejected: un caso de uso nuevo que persista el mensaje y luego clasifique — duplica el pipeline y añade un
tercer escritor al sumidero.
Rejected: reutilizar `ProcessInboundGuestMessageUseCase` a secas pasándole un `conversation_id` que el
router resuelva — pondría la decisión «esta estancia tiene hilo o no» en `api/`.

### D6 — Una sola conversación `PORTAL` por estancia, resuelta sin carrera

**Chosen:** índice único parcial sobre `conversations (tenant_id, reservation_id)` con predicado
`WHERE channel = 'PORTAL'` (comparación de enum a secas — el casteo a `text` que esta línea eligió
en la primera redacción no es declarable en un predicado de índice; el porqué y lo que cuesta
evitarlo, en D7), y un método nuevo del repositorio,
`ConversationRepository.ensure_portal(...)`, que hace **`INSERT … ON CONFLICT DO NOTHING`** seguido de un
`SELECT`. El perdedor de la carrera no revienta la transacción: bloquea hasta el commit del ganador, no
inserta, y su `SELECT` ve la fila del ganador (`READ COMMITTED`, el nivel por defecto de PostgreSQL — se
declara aquí porque el diseño depende de él). Los dos mensajes acaban en el mismo hilo, que es literalmente
lo que pide R3.4.

`on_conflict_do_*` ya tiene precedente en el árbol (`cleaning/infrastructure/repositories.py:397`,
`pricing/infrastructure/repositories.py:443`). Un `SELECT`-luego-`add` no puede hacerse seguro sin
`SAVEPOINT`, que no tiene precedente aquí.

Un segundo método, `find_portal(tenant_id, reservation_id) -> Conversation | None`, sirve la lectura de R2.5
sin crear nada.

**El `language` de la conversación (R3.3)** lo calcula `PostPortalGuestMessageUseCase` con
`detect_language(content) or "es"` y solo se aplica en la creación: en la rama `DO NOTHING` la conversación
conserva el suyo, que es lo que pide el requisito. El pipeline vuelve a llamar a `detect_language` para el
mensaje; es la misma función pura sobre el mismo texto, así que las dos lecturas coinciden por construcción y
no hay un segundo criterio que mantener. `property_id`, `reservation_id` y `guest_id` salen del
`GuestSession` (R1.3); `guest_id` puede ser `None` y la columna lo admite.

**Hasta dónde llega el índice, medido el 2026-08-29 y dicho aquí para que la tarea 3.2 lo cierre
en código.** PostgreSQL trata los `NULL` como distintos en un índice único, y
`conversations.reservation_id` es nullable: dos filas `PORTAL` del mismo tenant con
`reservation_id IS NULL` **entran las dos**, comprobado insertándolas. Añadir
`AND reservation_id IS NOT NULL` al predicado no cambiaría nada — esas filas ya no colisionan—.
Así que el índice cierra R3.4 para las estancias con reserva y **no** para una fila sin ella, y
lo que mantiene la garantía es que `reservation_id` sale del `GuestSession`, donde es
`uuid.UUID` y no `uuid.UUID | None`. Eso hoy es cierto por construcción del autorizador y por
nada más: `ensure_portal` **tipa su `reservation_id` como obligatorio** y no acepta `None`, de
modo que la promesa deje de depender de qué llamante tenga. Lo levantó el panel de seguridad de
la sección 1.

**El predicado y por qué la migración necesita salir de la transacción.** Ver D7.

Rejected: unicidad sobre `(tenant_id, reservation_id, channel)` sin predicado — prohibiría dos hilos
`MANUAL` de una misma estancia, que hoy son legales.
Rejected: dejar que la violación de unicidad salga como `500` — no está declarada en `_PORTAL_RESPONSES` y
un doble toque en el móvil la provoca.

### D7 — La migración añade la etiqueta en `autocommit_block()` y luego sí la usa

**Chosen** (corregido el 2026-08-29 durante `/sdd:run`, contra la base de datos real): una sola
revisión que hace `ALTER TYPE conversation_channel ADD VALUE IF NOT EXISTS 'PORTAL'` **dentro de
`op.get_context().autocommit_block()`**, y crea después el índice de D6 con el predicado
**`WHERE channel = 'PORTAL'`**, sin casteo.

La redacción original de esta decisión elegía el casteo a `text` para no tener que salir de la
transacción, y **no funciona**. Las dos mitades del razonamiento se midieron una por una:

- Que el predicado `WHERE channel = 'PORTAL'` falla dentro de la transacción que añade la
  etiqueta **es cierto**: `ERROR: unsafe use of new value "PORTAL" of enum type`, con su
  `HINT: New enum values must be committed before they can be used`.
- Que `channel::text = 'PORTAL'` lo evita **es falso**, y no por un matiz: PostgreSQL rechaza el
  índice mucho antes de llegar a leer nada, con `ERROR: functions in index predicate must be
  marked IMMUTABLE`. El casteo enum→text pasa por `enum_out`, que es `STABLE` y no `IMMUTABLE`
  —porque una etiqueta puede renombrarse—, y un predicado de índice solo admite funciones
  inmutables. El casteo no es que sea caro para el planificador: **no es declarable**.

Así que la salida es la que esta misma sección ya nombraba en *Risks* como plan B, y se paga su
coste con los ojos abiertos: `alembic/env.py` envuelve la ejecución entera en un
`context.begin_transaction()`, y `autocommit_block()` **commitea lo aplicado hasta ese punto**
antes de ejecutar el `ALTER TYPE` fuera de transacción. Se pierde la propiedad todo-o-nada de
`alembic upgrade head` —el coste que `c8e1f4a92b70` describe y que aquel evitó porque no usaba
la etiqueta—. Verificado en limpio: `alembic downgrade base && alembic upgrade head` pasa.

A cambio se recupera lo que el casteo costaba: el predicado queda sobre el enum, así que el
planificador **sí** puede usar el índice para un `WHERE channel = ConversationChannel.PORTAL`.

**El índice se declara dos veces y hace falta**: en la revisión y en `__table_args__` de
`ConversationModel` (`backend/app/messaging/infrastructure/models.py`), con el mismo predicado.
La suite construye su esquema con `create_all` sobre la metadata y **no corre las migraciones**
(`steering/testing.md`), así que sin la segunda declaración el índice no existiría en los tests y
el test de concurrencia de la tarea 3.3 no probaría nada. Ahí no hace falta `autocommit_block`
porque `create_all` **crea el tipo** en esa misma transacción en vez de ampliarlo, y PostgreSQL 12+
permite usar las etiquetas de un enum creado en la propia transacción. Precedente exacto de la
doble declaración: `uq_cleaning_tasks_live_reservation`.

El `downgrade` borra el índice y **deja la etiqueta** —PostgreSQL no puede quitarla— y lo dice,
como hizo `c8e1f4a92b70`.

Rejected: `channel::text = 'PORTAL'` — medido, no es declarable en un predicado de índice.
Rejected: dos revisiones — `env.py` mete toda la ejecución en una transacción, así que un
`upgrade head` desde base seguiría fallando.
Rejected: unicidad sobre `(tenant_id, reservation_id, channel)` sin predicado, para no necesitar
la etiqueta en ningún predicado — prohibiría dos hilos `MANUAL` de una misma estancia, que hoy
son legales (ya rechazado en D6).

### D8 — El actor: un value object de `messaging`, no un `uuid`

**Chosen:** `InboundMessageActor` frozen en `backend/app/messaging/domain/value_objects.py`, con
`user_id: uuid.UUID | None`, `token_hash: str | None`, `ip: str | None` y un `__post_init__` que exige
**exactamente uno** de los dos. Sustituye a `actor_user_id` + `ip` en
`ProcessInboundGuestMessageUseCase.execute` y en `IncidentReportingPort.report`.

`ReportIncidentFromConversationUseCase.report` deriva de él las tres cosas que hoy tiene fijas: el reportante
del `Incident` (`reported_by_user_id` **o** `reported_by_guest_token`), el actor del `AuditLog`
(`actor_user_id` **o** `actor_guest_token_hash`) y el `TimelineActorType` (`USER` **o** `GUEST`). Con eso
R4.1 queda cerrado por construcción en las **dos** barreras que ya existen: el value object y
`AuditLogFactory.build`, que rechaza el par y rechaza un `token_hash` que no sea un digest SHA-256.

Rejected: reutilizar `GuestActor` de `guests/application/use_cases.py` — obligaría a
`messaging/domain/ports.py` a importar el `application/` de otro módulo, contra la regla de dependencia.
Rejected: mover `GuestActor` a un módulo compartido — es un refactor de `guests` que este change no pidió.
Rejected: enrutar la incidencia del portal por `ReportGuestIncidentUseCase` (que ya acepta digest) —
commitea por su cuenta, lo que rompe la transacción única de R1.4, y no valida el catálogo cerrado de
títulos.

**Y una consecuencia que el panel de seguridad de la sección 2 levantó y que hay que leer antes de
construir la puerta anónima (sección 7): con esto, un portador de token pasa a ser escritor de
`audit_logs`.** Cada mensaje suyo con intent de incidencia escribe su fila, a la cadencia que él
decida y sin `MANAGE_CONVERSATIONS` detrás. Es el mismo patrón de hecho que la **tercera excepción
de la regla 9** de `steering/security.md` describe para los webhooks —«auditarla concede a un
tercero no autenticado la capacidad de escribir filas en `audit_logs` a voluntad: es una denegación
de servicio disfrazada de diligencia, y ahoga exactamente el índice
`ix_audit_logs_tenant_id_actor_user_id_created_at`»— con dos diferencias que **acotan y no
resuelven**: aquí el llamante presenta un token válido en vez de ser anónimo del todo, y la fila
exige una clasificación de incidencia y no una petición cualquiera.

Lo que la acota de verdad es el **throttle por token** de R4.3, y por eso ese límite deja de ser
sólo «el límite sobre la ruta» y pasa a ser también lo único que acota este sumidero. La sección 7
lo hereda como obligación explícita, citando esta decisión: no se pide exención de la regla 9 —la
fila se escribe— sino que se nombra quién sostiene el techo. Las filas del portal, además, van con
`actor_user_id` a `NULL`, así que **no** cargan el índice por actor que la tercera excepción existe
para proteger; cargan la tabla.

**Rejected**: eximir al portal de escribir la fila, por parecido con la tercera excepción — el
párrafo de cierre de la regla 9 dice literalmente que ese razonamiento «no es un criterio
reutilizable», y una incidencia sin autor no es auditable en absoluto.

### D9 — Leer no crea, y qué se ve al abrir la página

**Chosen:** `GET /guest/messages/{token}` resuelve la conversación `PORTAL` con `find_portal`; si no hay,
responde `200` con `PortalThread(items=(), total=0, state=AUTOMATIC)` (R2.5). Si la hay, reutiliza
`MessageRepository.list_for_conversation`, que **ya** ordena ascendente por `(created_at, id)` y filtra por
`JOIN` con `conversations` — la única forma de aislamiento que tiene `messages`, que no tiene `tenant_id`.
Paginación `?page&per_page` de PRD §23, con los mismos topes que `messaging/api/schemas.py` ya declara
(`MAX_PER_PAGE = 100`, `MAX_PAGE = 100_000`).

`state` sale de `conversation.escalation_status in (PENDING_HUMAN, HUMAN_HANDLING)` — la misma condición que
`_is_handed_over` aplica en el pipeline, extraída a una función compartida para que no puedan divergir.

**Sin `page`, la última página** (resuelto el 2026-08-29; bajado a R2.1 del proposal). Omitir `page` devuelve
la ventana más reciente —ascendente dentro—, y un `page` explícito sigue alcanzando las anteriores. Es un
valor por defecto documentado, no oculto: la convención del repositorio (`page=1` = los más antiguos) abriría
un hilo largo por el principio, que para un chat es el sitio equivocado, y obligaría al front a una segunda
vuelta en cada apertura **y en cada poll** contra un presupuesto de 60 peticiones/minuto. `total`, `page` y
`per_page` viajan en la respuesta, así que el cliente sabe siempre qué ventana tiene.

Implementación: el caso de uso calcula `page = max(1, ceil(total / per_page))` cuando el parámetro no viene, y
pasa ese número al `list_for_conversation` que ya existe — la paginación del repositorio no se toca.

### D10 — El front: una sección más bajo el mismo gate, y el primer polling del proyecto

**Chosen:** `ConversationSection` en `frontend/features/guest-portal/components/guest-portal-view.tsx`, cuarta
hija de `GuestPortalView`. R5.2 sale gratis: ese componente ya devuelve antes de renderizar ninguna sección
si `useStayInfo` no ha autorizado. R5.1 también: cada sección tiene su propio `useQuery`/`useMutation` y sus
propios estados, así que un fallo del hilo no toca a las otras tres.

Polling con `useQuery({ refetchInterval: PORTAL_THREAD_POLL_MS, ... })` y **sin** listener propio de
`visibilitychange`: el `focusManager` de TanStack Query v5 (`^5.101.2`) ya se suscribe a
`visibilitychange`, que es exactamente el disparador que nombra R5.3. Se pasa
`refetchIntervalInBackground: false` explícito en el código y se fija con un test que oculte la pestaña.

**Corregido durante `/sdd:run` el 2026-08-30**: este párrafo decía que la librería trae
`refetchIntervalInBackground: false` «por defecto», y es falso — no tiene defecto ninguno. La opción se
declara `refetchIntervalInBackground?: boolean` y el único sitio que la lee es `queryObserver`:
`this.options.refetchIntervalInBackground || focusManager.isFocused()`. Dejarla sin poner es simplemente
*falsy* y cae en la misma rama, que da el comportamiento que R5.3 pide — pero **por ausencia, no por un
valor por defecto**. Comprobado en el `@tanstack/query-core` 5.101.2 instalado, no supuesto: lo levantó el
panel de documentación de las secciones 9-10, con el número al revés (afirmó que el defecto era `true`), y
leer el fuente resolvió las dos versiones. La decisión no cambia —se pasa explícito— y ahora el motivo
escrito es el correcto: porque una garantía que descansa en una opción ausente no se ve, no porque duplique
un defecto. El test que oculta la pestaña se verificó **en rojo** poniendo la bandera a `true`.

`PORTAL_THREAD_POLL_MS = 15_000`, una constante de módulo. La aritmética que lo elige: el throttle por token
es **60 peticiones/minuto compartidas entre las seis rutas** del portal
(`guest_portal_rate_limit_per_minute`), y la página ya gasta `info` + `checkin` al abrir. A 15 s el hilo
cuesta 4/min; tres pestañas abiertas siguen en 12/min. A 5 s serían 36/min y un `429` de más deja la
página entera sin datos, porque el presupuesto es uno solo.

Al enviar: botón deshabilitado mientras `isPending`, región `role="alert" aria-live="polite"` como ya hacen
`CheckinSection` e `IncidentSection`, e invalidación de la clave del hilo al terminar, que es lo que muestra
«el hilo actualizado» de R5.4 junto con la respuesta de la IA escrita en la misma transacción. El `429` no se
reintenta: `retryPolicy` ya devuelve `false` para todo `4xx` y las mutaciones van con `retry: false`; el
texto es el `guest:errors.rateLimit` que ya existe y que ya dice «no sabemos si se recibió».

Rejected: WebSocket/SSE — fuera de alcance y sin superficie previa en el proyecto (verificado).
Rejected: un `useEffect` con `document.addEventListener("visibilitychange", …)` — reimplementa lo que el
`focusManager` ya hace y añade un segundo sitio donde equivocarse.

### D11 — i18n: el portal **y** la bandeja del manager

**Chosen:** claves nuevas `guest:conversation.*` en `frontend/locales/es/guest.json` y
`frontend/locales/en/guest.json` (título, vacío, cargando, campo, enviar, enviando, «tú», «el alojamiento»,
la copia de espera de R5.6, y los estados de error que R5.8 enumera reutilizando `guest:errors.*`).

Y, **que el proposal no nombra y el código sí exige**: `conversations:channel.PORTAL` en
`frontend/locales/es/conversations.json` y `.../en/conversations.json`. La bandeja del manager pinta el canal
con `t(\`conversations:channel.${row.channel}\`)` en `conversations-view.tsx:102` y
`conversation-thread-view.tsx:126`; sin esas dos claves, todo hilo de portal se muestra con la clave cruda.
Es consecuencia directa de R3.1 y de que R3.6 mande al manager a contestar desde ahí.

### D12 — El censo de la regla 11 se **enmienda**, no se parte

**Chosen:** la fila «`messages.content` — escritor: el **huésped** (`sender_type = GUEST`)» de
`sdd/steering/security.md` se amplía para nombrar a `guest-portal-messaging` como escritor vivo y para
declarar el cambio de audiencia: la prosa deja de llegar transcrita por un operador autenticado y pasa a
llegar directa de un portador anónimo desde internet. La excepción 4, que hoy dice que lo que aterriza es «lo
que una persona dijo por WhatsApp, por teléfono o por el panel», gana el portal en esa enumeración.

Se enmienda y no se parte porque el criterio del censo es **quién teclea**, y quien teclea sigue siendo el
huésped; lo que cambia es el camino. Los cuatro precedentes de partición del árbol (`incidents.title` entre
huésped y limpiadora, el seed frente a la persona) son casos en que cambió el escritor, no la ruta. La
cláusula que concede la excepción —«el valor no es nuestro y no lo hemos ido a buscar»— sigue siendo cierta
palabra por palabra.

**Trampa para `/sdd:run`**: `backend/tests/test_rule11_ownership.py` se pone en rojo si un bloque de
`backend/app/`, `backend/tests/`, `backend/alembic/versions/` o `docs/` declara quién escribe o quién hereda
una columna del censo. El código nuevo puede citar la regla; no puede reafirmar la propiedad. (`sdd/changes/`
está excluido del guardián, por eso este documento sí puede decirlo.)

### D13 — El censo de rutas anónimas y su prosa

**Chosen:** dos entradas nuevas en `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py`, que
pasa de cuatro rutas de portal a seis (R4.6). El comentario que las precede (líneas 82-84) afirma hoy *«That
is the whole of PRD §23's guest surface»* y habla de *«a fifth route under `/api/v1/guest/`»*: se reescribe
contra la lista resultante, no incrementando el número. Un recuento en prosa que se incrementa a ojo propaga
el desvío con aire de verificado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Enum + canal | `backend/app/messaging/domain/enums.py`, `.../infrastructure/channels.py` | miembro `PORTAL`; `PortalOutboundAdapter` y su entrada en `outbound_registry()` (D1) |
| Migración | `backend/alembic/versions/<new>.py`, `backend/app/messaging/infrastructure/models.py` | `ADD VALUE IF NOT EXISTS 'PORTAL'` en `autocommit_block()` + índice único parcial `channel = 'PORTAL'`, declarado también en `__table_args__` porque la suite usa `create_all` (D6, D7) |
| Actor | `backend/app/messaging/domain/value_objects.py`, `.../domain/ports.py`, `.../application/use_cases.py`, `.../api/router.py`, `backend/app/maintenance/application/use_cases.py` | `InboundMessageActor`; sustituye `actor_user_id`+`ip` en el pipeline y en `IncidentReportingPort`; el implementador de `maintenance` deriva reportante, actor de auditoría y `TimelineActorType` (D8) |
| Repositorio | `backend/app/messaging/domain/repositories.py`, `.../infrastructure/repositories.py` | `ensure_portal(...)` y `find_portal(...)` en `ConversationRepository` (D6) |
| Guarda de apertura | `backend/app/messaging/application/use_cases.py` (`CreateConversationUseCase`) | rechaza `channel = PORTAL`: el hilo del portal solo lo abre el huésped (D14, R3.7) |
| Puertos del portal | `backend/app/guests/domain/portal_ports.py` | `PortalMessage`, `PortalThread`, `PortalMessageSender`, `PortalThreadState`, `GuestPortalThreadReader`, `GuestPortalMessageSubmitter` (D3, D4) |
| Implementador | `backend/app/messaging/application/portal.py` *(nuevo)* | `PostPortalGuestMessageUseCase` y `ReadPortalThreadUseCase`; mapa total de remitente; extracción compartida de `_is_handed_over` (D5, D9) |
| Rutas + esquemas | `backend/app/guests/api/portal_router.py`, `.../portal_schemas.py`, `.../portal_dependencies.py` | `GET`/`POST /guest/messages/{token}` sobre `_authorised`; `PostGuestMessageRequest` con `extra="forbid"` y un solo campo; cableado reutilizando `get_process_inbound_message_use_case` (D2) |
| Censos | `sdd/steering/security.md`, `backend/tests/test_route_authorization.py` | fila de `messages.content` enmendada y excepción 4 ampliada; dos rutas más y su prosa recontada (D12, D13) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados y commiteados en el mismo PR (R5.10) |
| Front — datos | `frontend/features/guest-portal/data/{dto.ts,guest-portal-source.ts,http/http-guest-portal-source.ts}`, `hooks/{query-keys.ts,use-conversation.ts}` | DTOs desde los tipos generados, dos métodos en la fuente, clave `guestKeys.conversation(token)`, hook con polling (D10) |
| Front — UI | `frontend/features/guest-portal/components/guest-portal-view.tsx` | `ConversationSection` bajo el gate de `info` (D10) |
| Front — i18n | `frontend/locales/{es,en}/guest.json`, `frontend/locales/{es,en}/conversations.json` | `guest:conversation.*` y `conversations:channel.PORTAL` (D11) |
| Docs | `docs/guest-portal.md`, `docs/messaging-ai.md` | la sección de conversación del portal y su canal (`steering/documentation.md`) |

## Data & interfaces

**Esquema.** Un miembro de enum (`conversation_channel += PORTAL`) y un índice único parcial sobre
`conversations`. Ninguna columna nueva, ninguna tabla nueva, ningún backfill.

**API.**

```
POST /api/v1/guest/messages/{token}   → 201 PortalMessage      | 404 | 422 | 429 | 413
     body: { "content": <MultiLineText, 1..MAX_MESSAGE_CONTENT_LENGTH> }   extra="forbid"
GET  /api/v1/guest/messages/{token}?page&per_page → 200 PortalThread | 404 | 429
```

Sin códigos de error nuevos (R4.7): `NOT_FOUND`, `RATE_LIMITED`, `PAYLOAD_TOO_LARGE` y `VALIDATION_ERROR` ya
están en `app/core/error_codes.py`. Las respuestas declaradas reutilizan `_PORTAL_RESPONSES` tal cual, cuyo
`404` no enumera causas — y esa prosa se publica en `/openapi.json`, que es anónimo.

**Dónde caen los límites de R4.3, que son tres cosas distintas.** El tope de cuerpo (1 MiB) lo aplica
`MaxBodySizeMiddleware` antes del routing, sin rama propia. El tope de texto es
`MAX_MESSAGE_CONTENT_LENGTH = 4000` en el esquema *y* en `Message.__post_init__`, más el guardián
`MultiLineText` de `app/core/storable_text.py` — que no es cosmético: sin él un `U+0000` o un sustituto
suelto sale como `500` sin manejador, medido dos veces en `guest-portal-api`. El tope de ritmo es el throttle
por token. Ninguno sustituye a otro.

**R1.6 sale por construcción, y el orden es el que ya está documentado.** El `422` lo emite Pydantic
mientras FastAPI resuelve dependencias, **antes** de que la función de ruta corra y antes de gastar
presupuesto de throttle — el docstring de `portal_router.py` ya lo mide y lo justifica: el `422` es idéntico
sea cual sea el token, así que no distingue nada. Y no hace eco del valor rechazado porque
`_serialisable_validation_errors` (`app/core/errors.py:107`) publica solo `loc`, `type` y `msg`, nunca
`input`.

**Config / env.** Ninguna variable nueva. `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE` (60) pasa a repartirse entre
seis rutas en vez de cuatro; el comentario de `.env.example` se actualiza para decirlo, porque el polling de
D10 lo convierte en un número con consecuencia visible.

### D14 — `PORTAL` no es un canal que la bandeja pueda abrir

**Chosen:** `CreateConversationUseCase` rechaza `ConversationChannel.PORTAL` con un
`MessagingValidationError`, y su test. Sin eso, `POST /api/v1/conversations` lo aceptaría hoy sin tocar nada
—porque D1 lo convierte en un miembro válido del enum— y crearía un hilo que el huésped ve en su página sin
haber escrito, esquivando el índice único de D6 solo por suerte: el índice impide el segundo, no el primero.

Se rechaza en el caso de uso y no en el esquema de la petición porque es una regla de negocio —quién puede
abrir un hilo de portal— y `steering/backend-architecture.md` no la deja vivir en `api/`. Es la misma forma
con que `RecordHumanReplyUseCase` rechaza un rol sin `sender_type` en vez de inventarse uno.

Resuelto el 2026-08-29; bajado a R3.7 del proposal, porque una regla sin requisito detrás no la genera
`/sdd:tasks` ni la comprueba el panel.

Rejected: dejarlo abierto y confiar en que nadie lo pida — el hueco es alcanzable desde una ruta autenticada
existente, no hipotético.

## Requisitos sin decisión propia

Estos se cumplen por reutilización o por ausencia, y constan aquí para que nadie los busque en las
decisiones:

- **R1.3** (identificadores del token y de ningún otro sitio) — `GuestSession` es frozen y solo lleva
  `tenant_id`, `reservation_id`, `property_id`, `guest_id` y `token_hash`, todos resueltos por el
  autorizador. Los casos de uso nuevos reciben el `GuestSession` y nada más: no hay de dónde sacarlos de la
  ruta, del cuerpo ni de una cabecera.
- **R1.7** (`404` constante e indistinguible) — `_authorised` y `_unauthorised` ya lo producen, y las rutas
  nuevas los usan sin variante. La única cautela de implementación es enrutar por `_unauthorised` cualquier
  `GuestPortalUnauthorised` que un caso de uso levante *después* de autorizar, como hacen las tres rutas que
  ya lo hacen (`report_incident` es la excepción del árbol y no el modelo a copiar).
- **R2.6** (sin rutas de escalar, resolver, cerrar ni listar) — por ausencia: las únicas rutas anónimas son
  las seis del censo de D13, y los dos puertos de D3 no declaran ningún método más.
- **R3.5** (los hilos de otros canales, intactos) — `find_portal` y `ensure_portal` filtran por
  `channel = PORTAL`, así que ni la lectura los ve ni la escritura los alcanza. La bandeja del manager los
  sigue viendo todos, que es lo correcto.
- **R3.6** (el manager contesta con el flujo que ya existe) — `RecordHumanReplyUseCase` y `take_over` no se
  tocan; su mensaje sale con `sender_type = MANAGER` y R2.2 lo agrupa como «el alojamiento». La única
  consecuencia de este change en esa superficie es la clave i18n de D11.
- **R4.4** (el contenido no llega a `timeline_events` ni a `audit_logs.changes`) — ya cerrado en el pipeline:
  `_timeline_event` usa títulos constantes y `metadata` de identificadores, y `ChangeSet` rechaza por
  construcción cualquier campo fuera de `AUDITABLE_FIELDS`. `tests/messaging/test_free_text_sink_contract.py`
  lo comprueba y gana el caso del portal.
- **R5.9** (cliente sin `getHeaders`) — `frontend/features/guest-portal/data/index.ts` ya construye
  `createApiClient({ baseUrl: "" })` sin esa opción; los dos métodos nuevos van por la misma instancia. No
  hay decisión, sí un test que fije que sigue siendo así.

## Risks & mitigations

- **La migración usa la etiqueta que acaba de crear.** Era el riesgo real de este change y **se
  materializó**: el casteo a `text` con el que D7 pensaba esquivarlo no es declarable en un predicado de
  índice. Cerrado con el plan B que este mismo apartado nombraba —`autocommit_block()` alrededor del
  `ADD VALUE`— y con su coste aceptado; el detalle medido está en D7. Probado con
  `alembic downgrade base && alembic upgrade head` en limpio.
- **El pipeline sigue siendo síncrono dentro de la petición**, y este change amplía quién puede dispararlo:
  de un manager autenticado a cualquier portador de token. Con `MockAIAdapter` el coste es aritmética. Con un
  proveedor real, una petición anónima mantendría abierta una transacción durante la latencia del proveedor.
  El remedio es el que `messaging-ai` ya nombró en sus Risks (sacar la clasificación de la petición) y está
  fuera de alcance aquí; lo que acota el daño mientras tanto son el throttle por token y el tope de cuerpo.
- **Cambiar la firma de `IncidentReportingPort` toca `maintenance`.** Es un módulo que este change no
  entrega, así que la suite de `maintenance` y la de `messaging` entran en la verificación, no solo la del
  portal.
- **El `total` que decide la última página se lee y se pagina en dos consultas.** Entre ambas puede entrar un
  mensaje, y entonces la ventana devuelta se queda a uno de ser la última. Es benigno —el siguiente poll lo
  trae— y no se cierra con una transacción explícita: la lectura es anónima y de solo lectura, y el coste de
  serializarla no compra nada que el polling no arregle en 15 s.
- **Aislamiento sobre sesión ya ligada.** El autorizador liga la sesión al tenant que resuelve, así que un
  test de aislamiento escrito sobre una sesión marcada **no puede fallar**. Los tests de R4.5 conducen la
  ruta real con el token del tenant B y montan la fixture del tenant A antes de cualquier ligado.

## Residuo de R2.2 — qué queda inferible y por qué no se cierra aquí

Levantado por el panel de seguridad de las secciones 5-6 y decidido con el usuario el
**2026-08-29**. La proyección de D4 hace que la distinción IA/persona **no se publique**: no hay
`ai_generated`, no hay `sender_user_id`, y `AI` y `MANAGER` colapsan al mismo `PROPERTY`. Lo que
no hace —y lo que una redacción anterior de D4 y del propio `portal_ports.py` afirmaba— es
volverla **indecidible**. Quedan tres canales, y ninguno vive en el cuerpo de la respuesta:

1. **El instante.** `ProcessInboundGuestMessageUseCase` escribe el mensaje del huésped y la
   respuesta automática con el **mismo `now`**, en la misma llamada; una respuesta humana viene
   de otra petición y nunca puede coincidir. Un `PROPERTY` cuyo `created_at` iguala al `GUEST`
   inmediatamente anterior es, con certeza, de la máquina.
2. **La latencia.** La respuesta aparece en el mismo sondeo que el envío. Aunque los instantes
   difirieran, contestar en menos de quince segundos no lo hace una persona.
3. **El catálogo cerrado.** `templates.assert_in_catalogue` obliga a que toda respuesta de la IA
   sea un miembro de `RESPONSE_VOCABULARY`, así que su texto es reconocible entre estancias. Es
   `messaging-ai` R3.3 y es inherente al producto: es lo que impide que un proveedor real
   parafrasee al huésped.

**Por qué no se cierra en este change.** Desplazar el instante de la respuesta toca el pipeline
de `messaging-ai` —cuyos tests y cuyo orden en la bandeja del manager dependen de él— y no
cerraría ni (2) ni (3); redondear el instante en la proyección degrada el orden visible del hilo
y tampoco cierra (2) ni (3). Es decir: las dos vías tocan cosas fuera de alcance y ninguna
compra la garantía que se estaría prometiendo. Lo honesto es acotar el requisito a lo que el
sistema sostiene —R2.2 se enmendó en el proposal el mismo día— y dejar el residuo escrito aquí.

**Consecuencia para quien lo lea después**: R2.2 es una obligación sobre **la proyección**. Quien
quiera de verdad la indecidibilidad necesita un change propio que decida qué hacer con la
latencia, y ese change empieza por preguntarse si el producto la quiere: una respuesta instantánea
es buena para el huésped, y disimularla es empeorar el servicio para ocultar cómo funciona.

## Roadmap candidates

Trabajo que este change **no** hace y que conviene que no se pierda. `/sdd:archive` los traslada
a `sdd/roadmap.md`; aquí sólo quedan enunciados.

- **`conversations` debería referenciar `(tenant_id, reservation_id)` con una FK compuesta**, no
  `reservation_id` con una global. Levantado por el panel de seguridad de las secciones 3-4 al
  revisar `ensure_portal`: es el **segundo** escritor de esa tabla y no hereda las tres lecturas
  con las que `CreateConversationUseCase` demuestra que los anclajes son del tenant, así que hoy
  una llamada con la reserva de otro tenant escribe una fila cuyo `reservation_id` apunta fuera
  de su tenant. En el camino del portal no ocurre —los tres ids salen del `GuestSession`, y la
  tarea 6.2 lo fija con un test—, pero lo sostiene el llamante y no el esquema.

  El arreglo estructural es el que el propio árbol ya usa: `guest_access_tokens` referencia
  `(tenant_id, reservation_id)` contra `uq_reservations_tenant_id_id` —que **ya existe**— y su
  comentario dice exactamente por qué («makes it impossible for the row to name a reservation of
  another tenant»). Cerraría el hueco para `ensure_portal` y para `add` a la vez, y haría
  redundantes dos de las tres lecturas de `CreateConversationUseCase`.

  Fuera de alcance aquí porque este change declara «ninguna columna nueva, ninguna tabla nueva,
  ningún backfill», y retrofitar una FK compuesta sobre una tabla con filas no es eso: hay que
  decidir qué hacer con las que ya la violen. El hueco queda fijado, mientras tanto, en
  `tests/messaging/test_tenant_isolation.py::test_ensure_portal_does_not_verify_the_stay_belongs_to_the_tenant`,
  que es un test de caracterización y **debe borrarse** el día que alguien añada la comprobación.

- **La copia de `429` del portal es de escritura, y tres lecturas preexistentes la usan.**
  `guest:errors.rateLimit` dice «no sabemos si se recibió lo que enviaste», que es lo correcto
  tras un envío y falso tras un `GET`: el huésped no ha escrito nada. Este change lo arregló en
  sus **dos** caminos de lectura —el primer cargado del hilo y el sondeo fallido, con
  `conversation.rateLimited` y `conversation.staleNotice`— pero las otras tres lecturas del portal
  siguen usando la copia de envío: `StayInfoSection` (`guest-portal-view.tsx:88`),
  `CheckinSection` (`:180`) y el gate de la página (`:393`). Son de `guest-portal-web` y ninguna
  la toca este change.

  Levantado por el panel de i18n de las secciones 9-10, que encontró el residuo en el camino de
  lectura nuevo después de que el mismo defecto se hubiera arreglado en el del sondeo. **Fuera de
  alcance aquí a propósito**: arreglarlas es tocar tres secciones que este change no toca, y la
  regla de disciplina de alcance dice anotarlo en vez de hacerlo. El arreglo es mecánico —
  `readErrorText` ya existe y es el sitio— y el coste de no hacerlo es que un huésped que agote el
  presupuesto compartido al abrir la página lea que no sabemos si se recibió algo que nunca envió.

- **El guardián de propiedad de la regla 11 tiene vocabulario sólo en castellano, y por eso falla
  en las dos direcciones.** `backend/tests/test_rule11_ownership.py` decide si un texto reafirma
  quién escribe una columna del censo con un eje de propiedad en español
  (`(?:ya\s+)?tienen?\s+escritor` y compañía). De ahí salen los dos defectos que este change se
  encontró de frente:

  **Falso positivo**: la frase «sus tres tipos no tienen escritor» de la entrada
  `guest-scheduled-comms` en `sdd/roadmap.md` disparaba el guardián sin ser una afirmación de
  censo — es una entrada de roadmap describiendo trabajo pendiente. Llegó roja a este change desde
  `0537b69` (2026-08-28), verificado inherited antes de tocar nada, y la tarea 8.3 la reescribió a
  «siguen sin implementar» **para desbloquear una puerta de merge que fallaba por un defecto
  ajeno**. El panel de review de 2026-08-30 lo levantó cuatro veces como violación de la regla 1
  compartida, y la decisión registrada fue mantener la edición declarada: es visible en el diff,
  no toca ninguna casilla ni ningún enlace de archivo, y revertirla vuelve a romper el gate.

  **Falso negativo**, que es el peor de los dos: el comentario que este change añadió en
  `backend/app/messaging/application/portal.py:95-97` —«the rule-11 census counts use cases that
  write `messages.content` … it is still the two in …»— es exactamente la clase de prosa que el
  guardián existe para cazar, está en inglés, y casi con seguridad no dispara. La afirmación es
  cierta hoy (el panel de seguridad la verificó contra el AST), así que no hay nada roto; el
  agujero de cobertura sí lo está.

  El arreglo no es ampliar la lista de frases prohibidas —un guardián por nombres prohibidos se
  sortea sin querer, y este ya se sorteó solo cambiando de idioma— sino **fijar la forma exacta y
  los ficheros en alcance**: qué documentos son censo (`sdd/steering/security.md` y poco más),
  cuáles son prosa que puede citar la regla sin reafirmarla, y hacer el eje de propiedad
  bilingüe. Levantado por el panel de seguridad de review (2026-08-30) como observación sin
  referente, y por el de arquitectura, i18n y documentación como el hallazgo de `roadmap.md`: son
  el mismo defecto visto desde los dos lados.

## Open questions

Ninguna abierta. Las dos que este diseño levantó se resolvieron con el usuario el **2026-08-29** y las dos
enmendaron el proposal, porque un acuerdo que no baja a un requisito no lo genera `/sdd:tasks` ni lo
comprueba el panel:

| OQ | Decisión | Dónde vive ahora |
|---|---|---|
| Qué ventana del hilo devuelve el `GET` sin `page` | La **última** página, ascendente dentro; `page` explícito alcanza las anteriores | D9 · proposal R2.1 |
| Si la bandeja puede abrir una conversación `PORTAL` | No: `CreateConversationUseCase` la rechaza en el caso de uso | D14 · proposal R3.7 |
