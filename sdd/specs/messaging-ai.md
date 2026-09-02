# Mensajería con IA y escalado humano

## Purpose

El módulo `messaging` atiende en primer nivel al huésped: registra la conversación y sus
mensajes, detecta el idioma, clasifica la intención con un puerto de IA propio, responde
desde un catálogo cerrado de plantillas cuando está seguro, y entrega la conversación a una
persona cuando no debe contestar. Es el único escritor de `conversations` y `messages`, y el
primero de `NotificationType.GUEST_ESCALATION` y de los cuatro eventos de mensajería del
timeline. **No hay ingesta automática desde OTA** — eso llega con `beds24-messaging-adapter`,
y `PMSMessagingPort` sigue siendo el puerto sin métodos que fijó
[`pms-provider-resolution.md`](pms-provider-resolution.md).

El pipeline tiene **dos puertas de entrada**, y es el mismo pipeline entero para las dos —no hay
una segunda copia. La primera es `POST /api/v1/conversations/{id}/messages` (R7), donde un
manager autenticado transcribe lo que le dijo el huésped. La segunda, desde
[`guest-portal-messaging`](guest-portal-api.md), es anónima: el propio huésped escribe desde su
token de estancia contra `POST /api/v1/guest/messages/{token}`, una ruta que este módulo no
declara y cuyo contrato de autorización, límites y esquema vive en
[`guest-portal-api.md`](guest-portal-api.md). Lo que sí es de aquí es el actor que el pipeline
acepta en cada camino (R4) y el canal `PORTAL`, cuya conversación es una por estancia y la abre
solo el primer mensaje del huésped (R1, R6, R7).

## Requirements

### R1 — Persistencia de conversaciones y mensajes

- THE SYSTEM SHALL declarar dos puertos de repositorio en `messaging` —uno por raíz de
  agregado— con solo los métodos que esta capability consume: `ConversationRepository`
  (`add`, `get`, `save`, `list`) y `MessageRepository` (`add`, `list_for_conversation`,
  `count_guest_messages`, `count_unresolved_guest_messages_with_intent`).
- WHEN se consulta cualquier `Message`, THE SYSTEM SHALL partir del `JOIN` con
  `conversations` para acotar por `tenant_id`, y NEVER SHALL consultar `messages`
  directamente. La tabla **no tiene columna `tenant_id`**, así que `tenant_scoped_classes()`
  no la selecciona y el filtro global de `with_loader_criteria` no la cubre: el `JOIN` no es
  defensa en profundidad, es el único mecanismo de aislamiento.
- THE SYSTEM SHALL demostrar con test de aislamiento propio que un tenant no lee ni escribe
  los mensajes de otro en **cada** vía de acceso: listado, detalle, alta y envío.
- WHEN se añade un mensaje a una conversación, THE SYSTEM SHALL actualizar
  `Conversation.last_message_at` en la misma transacción, a través de
  `Conversation.register_message()` y nunca por asignación directa desde el caso de uso, de
  modo que la bandeja se ordene sin recorrer `messages`.
- IF la conversación referida no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL
  responder `404` en ambos casos, y NEVER SHALL permitir distinguir una de otra.
- THE SYSTEM SHALL exigir `property_id` en toda `Conversation`, rechazándola en construcción
  si falta. La columna permanece nullable en base de datos a propósito: la restricción es de
  esta capability, y `beds24-messaging-adapter` deberá decidir qué hacer con una conversación
  que el PMS entregue antes de resolver su propiedad. El motivo es duro: `TimelineEventFactory`
  exige `property_id` no nulo, así que una conversación sin ella no podría emitir ninguno de
  los cuatro eventos obligatorios.
- THE SYSTEM SHALL rechazar en construcción una `Conversation` cuyo `language` no esté en
  `SUPPORTED_LANGUAGES`, y un `Message` cuyo `language` no lo esté ni sea nulo.
- THE SYSTEM SHALL tratar `messages` como **append-only**: `Message` es un dataclass `frozen`
  y nada edita una fila después de escribirla. `Conversation` sí es mutable, porque tiene
  ciclo de vida.
- THE SYSTEM SHALL garantizar **como mucho una** `Conversation` de canal `PORTAL` por estancia
  —índice único parcial sobre `conversations (tenant_id, reservation_id) WHERE channel =
  'PORTAL'`— y SHALL resolverla sin carrera: `ConversationRepository.ensure_portal(...)` hace
  `INSERT … ON CONFLICT DO NOTHING` seguido de `SELECT`, de modo que el perdedor de dos mensajes
  simultáneos del mismo huésped no aborta su transacción — bloquea, no inserta y lee la fila del
  ganador, y los dos mensajes acaban en el mismo hilo. Ninguno de los dos métodos comitea: el
  camino del portal comparte el `commit()` único de R4. `reservation_id` es obligatorio en la
  firma —nunca `| None`— porque PostgreSQL no colisiona `NULL` contra `NULL` en un índice único,
  así que la garantía depende de que el llamante nunca pase uno vacío.
- THE SYSTEM SHALL exponer `ConversationRepository.find_portal(...)` como lectura pura —
  devuelve la conversación de canal `PORTAL` de la estancia o `None`, y NEVER SHALL crearla: leer
  no abre conversación. Filtra por `channel = PORTAL` además de por tenant, de modo que los
  hilos `WHATSAPP` o `MANUAL` de la misma estancia no sean ni devueltos ni alcanzables desde ahí.

### R2 — Puerto `AIAdapter` y clasificación

- THE SYSTEM SHALL declarar el puerto `AIAdapter` con **exactamente dos métodos**,
  `classify_message` y `generate_response`, y NEVER SHALL declarar `classify_incident`,
  `validate_cleaning_photo`, `summarize_incident` ni `draft_review_response` del PRD §13.
  Declarar los seis y dejar cuatro lanzando `NotImplementedError` rompería Liskov por el
  mismo razonamiento que la decisión 3 de [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md).
- THE SYSTEM SHALL dejar intacto el puerto `IncidentClassifier` de `maintenance`, y NEVER
  SHALL colgar de `AIAdapter` la clasificación de incidencias.
- THE SYSTEM SHALL declarar los catorce intents del PRD §13 como enum cerrado `MessageIntent`
  con esos nombres literales: `CHECKIN_INSTRUCTIONS`, `ACCESS_PROBLEM`, `WIFI`, `PARKING`,
  `LATE_CHECKOUT`, `EARLY_CHECKIN`, `CLEANING_ISSUE`, `MAINTENANCE_ISSUE`, `NOISE`,
  `REFUND_OR_COMPENSATION`, `EMERGENCY`, `GENERAL_FAQ`, `REVIEW_REQUEST` y `UNKNOWN`.
  `UNKNOWN` es miembro real, no un error: es lo que devuelve un clasificador sin veredicto.
- THE SYSTEM SHALL exigir que toda clasificación y toda respuesta generada declaren **en el
  valor que devuelven** el vocabulario cerrado del que salen: `MessageClassification` rechaza
  una confianza fuera de `0..1` o un `intent` que no sea miembro, y `GeneratedResponse`
  rechaza un `content` fuera del `vocabulary` que declara. La comprobación vive en el tipo,
  no en un barrido de directorio que un adaptador pueda esquivar mudándose.
- WHERE la declaración de vocabulario del adaptador es la *condición de admisión* y no la
  garantía, THE SYSTEM SHALL comparar el valor que va a persistir contra
  `templates.RESPONSE_VOCABULARY` —el catálogo— y nunca contra lo que el adaptador declaró.
  Es obligación del pipeline; ningún puerto puede imponerla.
- WHEN `MockAIAdapter` reconoce el intent de un mensaje, THE SYSTEM SHALL devolver
  `confidence = 0.80`; IF no lo reconoce, THEN SHALL devolver `UNKNOWN` con una confianza por
  debajo del umbral por defecto (`0.75`), de modo que el mock ejercite el camino de escalación.
- THE SYSTEM SHALL generar respuestas desde plantillas constantes versionadas por intent y por
  idioma (`es`/`en`), **sin ningún hueco de interpolación** —ni `{...}`, ni `%s`, ni
  `f`-string—, y un test recorre el catálogo y lo rechaza si aparece uno.
- WHERE el catálogo garantiza algo, THE SYSTEM SHALL limitarse a lo que garantiza: hace
  imposible que las palabras del huésped acaben en una respuesta, porque no hay dónde
  ponerlas. NEVER SHALL presentarse como garantía de que una plantilla no incumpla la regla 10
  de `steering/security.md` — una constante es lo que alguien escribió; eso lo guardan la
  revisión y la lista de frases prohibidas de `test_no_template_can_promise_what_rule_10_forbids`,
  que es una red y no una garantía.
- THE SYSTEM SHALL declarar plantillas para **once intents y no catorce**:
  `REFUND_OR_COMPENSATION`, `EMERGENCY` y `UNKNOWN` no tienen entrada, de modo que quien
  esquive la rama del pipeline reciba un `KeyError` ruidoso en vez de una frase que el huésped
  no debía recibir.
- `EXTERNAL_DEPENDENCY`: el adaptador real contra un proveedor de modelos queda fuera.
  `MockAIAdapter` es el único implementador; uno real implementa este mismo puerto y vive en
  `app/integrations/`.

### R3 — Sumideros de texto en claro de `messages`

- THE SYSTEM SHALL declarar `messages.content`, `messages.intent` y `messages.metadata` en el
  censo de la regla 11 de [`steering/security.md`](../steering/security.md), único sitio donde
  viven ese contrato **y su atribución**: esta línea las declara, no dice de quién son.
- WHERE el mensaje lo escribe el huésped (`sender_type = GUEST`), `messages.content` SHALL ir
  bajo **excepción de prosa de tercero**: el valor no es nuestro y ningún código nuestro
  renderiza ahí un valor de la regla 3. Se acota con tipo y longitud máxima, sin pretender que
  la columna sea estructurada.
- WHERE el mensaje lo escribe el sistema (`ai_generated = true`), `messages.content` SHALL ser
  **forma cerrada**: una plantilla del catálogo, sin interpolación de texto recibido.
- `messages.intent` SHALL ser **forma cerrada**, y THE SYSTEM SHALL degradar a `UNKNOWN` todo
  valor que no sea miembro de `MessageIntent`, nunca almacenarlo tal cual. La degradación
  ocurre en `Message.__post_init__`, no en el llamante, y cubre también un payload no hashable
  (`TypeError` junto a `ValueError`). `None` no es un valor irreconocible: una respuesta humana
  nunca se clasifica y queda sin clasificar.
- `messages.metadata` SHALL ser **estructurada**: el repositorio y la entidad aceptan
  `MessageMetadata` y nunca un `dict`, con el conjunto cerrado de claves
  `escalation_reason`, `template_key`, `template_version`, `delivery_status`,
  `delivery_error_code` y `source_message_id`. Cada una es identificador, miembro de enum o
  constante comprobada; `to_dict()` emite solo las presentes.
- THE SYSTEM SHALL impedir la propagación: el `TimelineEvent` de un mensaje SHALL llevar
  título constante e identificadores en `metadata`, y NEVER SHALL copiar el contenido del
  mensaje a `timeline_events` ni a `audit_logs.changes`. La garantía es del `Message`, no del
  camino de entrada: `test_free_text_sink_contract.py` la comprueba igual para un mensaje que
  llega transcrito por un manager y para uno que escribe directamente el portador de un token
  del portal (`guest-portal-messaging`).
- THE SYSTEM SHALL rechazar un `content` de más de `MAX_MESSAGE_CONTENT_LENGTH` (4000
  caracteres) en la propia entidad, además de en el esquema Pydantic. `ASSUMPTION`: el número
  no está medido contra el canal real; `beds24-messaging-adapter` lo ajustará con datos. Son
  caracteres y no bytes — la columna es `TEXT` sin límite, así que es decisión de producto y no
  restricción de almacenamiento. NEVER SHALL presentarse esta comprobación como rechazo previo
  a leer el cuerpo: eso solo lo hace `MaxBodySizeMiddleware` (regla 14 de `security.md`).

### R4 — Pipeline del mensaje entrante

- WHEN se registra un mensaje con `sender_type = GUEST`, THE SYSTEM SHALL, en este orden:
  detectar su idioma, clasificar el intent con `AIAdapter`, persistir el mensaje con ambos y
  emitir `TimelineEvent(GUEST_MESSAGE_RECEIVED)`. La clasificación precede a la persistencia
  porque `Message` es `frozen` y necesita `intent` e idioma en construcción. Este pipeline es
  **el mismo, entero y sin una segunda copia**, tanto si el mensaje lo transcribe un manager
  autenticado en `POST /conversations/{id}/messages` como si lo escribe directamente el
  portador de un token en `POST /api/v1/guest/messages/{token}` — lo único que cambia entre
  los dos caminos es el actor que lo dispara (ver más abajo).
- THE SYSTEM SHALL identificar a quien dispara el pipeline con `InboundMessageActor` —value
  object `frozen` de `messaging/domain/value_objects.py`, con `user_id: uuid.UUID | None`,
  `token_hash: str | None` e `ip: str | None`—, y SHALL exigir en su construcción
  **exactamente uno** de `user_id`/`token_hash`: ninguno de los dos a la vez, ninguno de los
  dos ausente. `ProcessInboundGuestMessageUseCase.execute` y `IncidentReportingPort.report`
  reciben este actor en lugar del `actor_user_id: uuid.UUID` + `ip` que tenían antes de
  `guest-portal-messaging` — el cambio es lo que le abre la puerta a un portador de token sin
  ensanchar el pipeline a admitir un actor sin identidad. `IncidentReportingPort` (implementado
  en `maintenance`) deriva de él el reportante del `Incident` (`reported_by_user_id` **o**
  `reported_by_guest_token`), el actor del `AuditLog` (`actor_user_id` **o**
  `actor_guest_token_hash`) y el `TimelineActorType` (`USER` **o** `GUEST`).
- THE SYSTEM SHALL ejecutar todo el procesamiento de un mensaje entrante en **una sola
  transacción**, de modo que no quede el mensaje persistido sin evento de timeline ni la
  conversación escalada sin notificación. Desde fuera no hay estado intermedio observable.
- IF la confianza de la clasificación es **estrictamente menor** que
  `TenantConfig.ai_confidence_threshold`, THEN THE SYSTEM SHALL escalar y NEVER SHALL generar
  respuesta. IF es mayor o igual, THEN SHALL continuar. El borde es el mismo que usa
  `Incident.classify` en `maintenance`, deliberadamente.
- IF `Conversation.ai_enabled` es `false`, THEN THE SYSTEM SHALL clasificar y registrar el
  mensaje pero NEVER SHALL generar ni enviar respuesta automática.
- IF la conversación ya está en manos de una persona (`PENDING_HUMAN` o `HUMAN_HANDLING`),
  THEN THE SYSTEM SHALL registrar el mensaje sin responder automáticamente: **la IA deja de
  contestar en cuanto ha traspasado**. Sin esto el huésped recibiría la respuesta del manager y
  una plantilla contradiciéndola, y el manager estaría discutiendo con su propio sistema.
  `RESOLVED` no cuenta como traspasada: la escalación terminó, un mensaje nuevo reabre la
  conversación con el eje en `NONE` y la IA vuelve a contestar, porque es un problema nuevo.
- WHEN se envía una respuesta automática, THE SYSTEM SHALL persistirla como `Message` con
  `sender_type = AI`, `ai_generated = true`, su `confidence_score` y su `intent`, y SHALL
  emitir `TimelineEvent(AI_RESPONSE_SENT)`.
- WHEN un usuario autenticado contesta manualmente, THE SYSTEM SHALL persistir el mensaje con
  `sender_type` derivado de su rol y `sender_user_id`, SHALL emitir
  `TimelineEvent(HUMAN_RESPONSE_SENT)`, y WHERE la conversación esperaba a una persona SHALL
  tomarla (`take_over`).
- WHEN el intent clasificado es `MAINTENANCE_ISSUE` o `ACCESS_PROBLEM`, THE SYSTEM SHALL crear
  un `Incident` a través de `IncidentReportingPort` —puerto declarado en `messaging` e
  implementado por `maintenance`, cableado en `messaging/api/dependencies.py`— y NEVER SHALL
  clasificarlo en la misma petición: la incidencia nace `OPEN` con `ai_classification` sin
  fijar, que es lo que recoge el job `classify_incidents`.
- WHERE se abre una incidencia desde una conversación, `title` SHALL salir de un catálogo
  cerrado de constantes y `description` SHALL ser el mensaje del huésped **literal**, sin
  añadir, quitar ni parafrasear. El implementador recibe una `CallerOwnedUnitOfWork` y NEVER
  SHALL commitear: el único commit sigue siendo el del pipeline.
- THE SYSTEM SHALL detectar el idioma entre `es` y `en` y SHALL responder en el detectado;
  IF no puede decidirlo, THEN SHALL usar `Conversation.language`.
- WHEN un huésped escribe en una conversación `RESOLVED`, THE SYSTEM SHALL reabrirla, y
  WHERE su `escalation_status` era `RESOLVED` SHALL devolverlo a `NONE` — sin esto la
  conversación reabierta no podría volver a escalar nunca, porque `escalate` solo admite
  `NONE` como origen.

### R5 — Escalación a humano

- THE SYSTEM SHALL escalar en las seis condiciones del PRD §13, evaluadas por una función pura
  sin repositorios, reloj ni E/S, y SHALL registrar **la primera que se cumpla** en este orden
  declarado —de menos a más dependiente del clasificador—: `EMERGENCY_KEYWORD`,
  `LOW_CONFIDENCE`, `EMERGENCY_INTENT`, `REFUND_OR_COMPENSATION`,
  `IMMINENT_CHECKIN_ACCESS_PROBLEM`, `REPEATED_INTENT`.
- THE SYSTEM SHALL tratar `UNKNOWN` bajo `LOW_CONFIDENCE` y no como séptima condición: ambos
  significan que el clasificador no dio veredicto accionable, y `UNKNOWN` no tiene plantilla.
- THE SYSTEM SHALL declarar `EscalationReason.DELIVERY_FAILED` como séptima razón **que no
  procede del PRD** y que la política de escalación nunca devuelve: no decide si contestar,
  sino el estado en que queda una conversación cuya respuesta no pudo entregarse.
- THE SYSTEM SHALL detectar palabras clave de emergencia sobre palabras completas y texto sin
  acentos, en **ambos idiomas a la vez** e independientemente del idioma detectado, de modo que
  «intoxicación» e «intoxicacion» acierten y «gasolinera» no cuente como «gas».
- `ASSUMPTION`: la «lista configurable de palabras clave de emergencia» del PRD §13 se entrega
  como constante de dominio versionada (`EMERGENCY_KEYWORDS_VERSION`), no como columna de
  `TenantConfig`. Configurarla por tenant exige migración y UI de settings, que son de
  `hardening-release`; la constante es sustituible sin tocar el pipeline.
- THE SYSTEM SHALL considerar inminente un check-in a **estrictamente menos** de 2 h, y
  repetido un intent con **estrictamente más** de 2 mensajes de huésped sin resolver.
- IF la condición de check-in inminente necesita una reserva y la conversación no tiene
  `reservation_id`, THEN THE SYSTEM SHALL tratarla como no cumplida, y NEVER SHALL fallar el
  procesamiento por ello.
- WHEN se escala, THE SYSTEM SHALL fijar `status = ESCALATED` y
  `escalation_status = PENDING_HUMAN`, emitir `TimelineEvent(AI_ESCALATED_TO_HUMAN)` y
  registrar una notificación `GUEST_ESCALATION`.
- THE SYSTEM SHALL declarar las transiciones en la propia entidad `Conversation`, en **dos
  tablas separadas** por eje, y SHALL comprobar ambos ejes **antes** de escribir ningún campo:

  | Eje | Operación | Orígenes | Destino |
  |---|---|---|---|
  | escalación | `escalate` | `NONE` | `PENDING_HUMAN` |
  | escalación | `take_over` | `PENDING_HUMAN` | `HUMAN_HANDLING` |
  | escalación | `resolve_escalation` | `PENDING_HUMAN`, `HUMAN_HANDLING` | `RESOLVED` |
  | conversación | `escalate` | `OPEN` | `ESCALATED` |
  | conversación | `resolve` | `OPEN`, `ESCALATED` | `RESOLVED` |
  | conversación | `reopen` | `RESOLVED` | `OPEN` |

- WHERE `escalate` admite **solo** `NONE` como origen, THE SYSTEM SHALL obtener de ahí, y no de
  un `if` en el pipeline, que una conversación ya escalada registre el mensaje entrante sin
  emitir una segunda notificación mientras siga `PENDING_HUMAN`.
- THE SYSTEM SHALL dejar `CLOSED` como origen y nunca como destino: esta capability no le da
  escritor.
- WHEN se resuelve una conversación, THE SYSTEM SHALL cerrar con ella su escalación si la
  tenía, porque ninguna ruta resuelve ese eje por separado y una conversación resuelta con la
  escalación pendiente se quedaría para siempre en cualquier lista de traspasos pendientes.
- IF una transición no es válida, THEN THE SYSTEM SHALL rechazarla con
  `InvalidConversationTransitionError`, y `POST /escalate` sobre una conversación ya escalada
  SHALL responder `409`.

### R6 — Canales de salida

- THE SYSTEM SHALL declarar `OutboundMessagePort` en `messaging`, y los casos de uso SHALL
  depender de él y nunca de un adapter concreto.
- THE SYSTEM SHALL registrar los adapters en un `dict` construido con antelación y visible,
  no por despacho dinámico: `MANUAL` → `PanelOutboundAdapter`, `PORTAL` →
  `PortalOutboundAdapter`, `WHATSAPP` → `MockWhatsAppAdapter`, `EMAIL` → `ConsoleEmailAdapter`
  (el que ya gobierna `access-notifications`), `PHONE_TRANSCRIPT` → `InboundOnlyAdapter`.
- THE SYSTEM SHALL tratar `PORTAL` como `MANUAL`: la entrega **es** la fila que ya se persistió,
  así que `PortalOutboundAdapter.send` es un no-op que devuelve éxito — verdadero porque
  `GET /api/v1/guest/messages/{token}` existe y es lo que el huésped lee (`guest-portal-api.md`),
  igual que `PanelOutboundAdapter` es verdadero porque `GET /conversations/{id}/messages` existe
  para el manager. Son dos clases y no una segunda entrada apuntando a `PanelOutboundAdapter`
  porque cada una nombra el endpoint que sostiene su promesa, y son promesas distintas.
- THE SYSTEM SHALL dejar `PORTAL` sin entrada en `contact_kind_for`: el portal no direcciona a
  nadie, es el propio huésped quien vuelve a su página — misma ausencia que `MANUAL`.
- IF el canal de la conversación es `AIRBNB_MSG` o `BOOKING_MSG`, THEN THE SYSTEM SHALL fallar
  con `PMSChannelUnavailableError`, y NEVER SHALL caer en silencio a consola. Esos dos canales
  no tienen entrada en el registro a propósito: existen solo a través de `PMSMessagingPort`.
  Una conversación abierta sobre ellos se acepta y es **muda por diseño**.
- THE SYSTEM SHALL dejar `PMSMessagingPort` exactamente como está —un puerto sin métodos— y
  NEVER SHALL añadirle `get_messages` ni `send_message`: su forma la decide el primer proveedor
  que lo implemente.
- WHEN el envío falla, `OutboundMessagePort.send` SHALL devolver el resultado y NEVER SHALL
  lanzar excepción: una excepción abortaría la transacción única y se llevaría por delante el
  mensaje del propio huésped, que es exactamente la pérdida silenciosa que esto prohíbe.
- THE SYSTEM SHALL registrar el fallo en forma estructurada —código y campo— y SHALL escalar la
  conversación con `DELIVERY_FAILED` para que una persona pueda recuperarla.
  `ChannelSendResult` no tiene campo de texto libre, así que lo que diga el proveedor se queda
  en el adapter y no puede llegar a `messages.metadata`.

### R7 — API de bandeja de conversaciones

- THE SYSTEM SHALL exponer los siete endpoints del PRD §16 con estas rutas y permisos, y no
  más:

  | Ruta | Permiso |
  |---|---|
  | `GET /api/v1/conversations` | `READ_CONVERSATIONS` |
  | `POST /api/v1/conversations` | `MANAGE_CONVERSATIONS` |
  | `GET /api/v1/conversations/{id}` | `READ_CONVERSATIONS` |
  | `GET /api/v1/conversations/{id}/messages` | `READ_CONVERSATIONS` |
  | `POST /api/v1/conversations/{id}/messages` | `MANAGE_CONVERSATIONS` |
  | `POST /api/v1/conversations/{id}/escalate` | `MANAGE_CONVERSATIONS` |
  | `POST /api/v1/conversations/{id}/resolve` | `MANAGE_CONVERSATIONS` |

- THE SYSTEM SHALL declarar el permiso de cada ruta con `require(...)`, recorrido por
  `tests/test_route_authorization.py`.
- WHEN se listan conversaciones, THE SYSTEM SHALL permitir filtrar por `status`,
  `escalation_status` y `property_id`, paginar con `page`/`per_page`, y ordenar por
  `last_message_at` descendente **con nulos al final**, para que una conversación recién creada
  y nunca escrita no se coloque por encima de lo que está ardiendo.
- WHEN se listan los mensajes de una conversación, THE SYSTEM SHALL devolverlos en orden
  cronológico ascendente y paginados: una conversación se lee hacia adelante, al revés que el
  timeline, que es un feed.
- WHERE `POST /messages` es **una ruta con dos comportamientos**, THE SYSTEM SHALL elegirlo por
  el `sender_type` del cuerpo, que es un `Literal`: con `"GUEST"` corre el pipeline completo;
  omitido, el llamante contesta él mismo y el `sender_type` se deriva de su rol. Cualquier otro
  valor SHALL ser `422` — un cliente no puede declarar que un mensaje lo escribió la IA.
- THE SYSTEM NEVER SHALL admitir `POST /api/v1/conversations` con `channel = PORTAL`, y SHALL
  rechazarlo con `MessagingValidationError` en el caso de uso —no en el esquema, porque «quién
  puede abrir un hilo de portal» es una regla de negocio y `steering/backend-architecture.md`
  no la deja vivir en `api/`. `PORTAL` es un miembro válido del enum desde R1/R6, así que sin
  este rechazo la ruta lo aceptaría sin tocar nada, y crearía un hilo que el huésped vería en
  su página sin haber escrito él mismo: el índice único de R1 no lo impide, porque solo prohíbe
  el *segundo* hilo de portal de una estancia, no el primero. La única vía legítima para abrir
  uno es el primer mensaje del propio huésped, vía `ensure_portal` (R1).
- THE SYSTEM SHALL mantener `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`
  regenerados en el mismo PR — las dos mitades del puente que exige `steering/documentation.md`.

## Key files

- `backend/app/messaging/domain/` — `entities.py` (`Conversation` mutable con sus dos tablas de
  transiciones, `Message` `frozen`), `enums.py` (los catorce intents, las siete razones de
  escalación), `escalation.py` (la política pura y su orden), `templates.py` (el catálogo
  cerrado), `value_objects.py` (`MessageMetadata`, `MessageClassification`, `GeneratedResponse`,
  `ChannelSendResult`, `InboundMessageActor`), `ports.py` (`AIAdapter`, `OutboundMessagePort`,
  `IncidentReportingPort`), `repositories.py` (incluye `ensure_portal`/`find_portal`),
  `language.py`, `notifications.py`, `exceptions.py`.
- `backend/app/messaging/application/use_cases.py` — el pipeline del mensaje entrante, el
  rechazo de `POST /conversations` con `channel = PORTAL`, y los siete casos de uso de la
  bandeja.
- `backend/app/messaging/application/portal.py` — `PostPortalGuestMessageUseCase` y
  `ReadPortalThreadUseCase`, los implementadores de los dos puertos que declara
  `guests/domain/portal_ports.py` (`guest-portal-api.md`): resuelven/crean la conversación
  `PORTAL` y proyectan `Message` a lo que el huésped puede ver, sin instanciar `Message` ellos
  mismos.
- `backend/app/messaging/api/` — `router.py` (las siete rutas y sus permisos), `schemas.py`,
  `dependencies.py` (la única capa que conoce `messaging` y `maintenance` a la vez), `errors.py`.
- `backend/app/messaging/infrastructure/` — `ai.py` (`MockAIAdapter`), `channels.py` (el
  registro de canales, incluido `PortalOutboundAdapter`), `repositories.py` (el `JOIN` que aísla
  `messages`, y `ensure_portal`/`find_portal`), `models.py` (el índice único parcial de
  `PORTAL`, declarado también aquí porque la suite construye su esquema con `create_all` y no
  corre las migraciones).
- `backend/alembic/versions/2b28c6b3f82a_guest_portal_messaging.py` — el miembro de enum
  `PORTAL` (`ALTER TYPE … ADD VALUE` en `autocommit_block()`, porque un predicado de índice no
  puede usar una etiqueta añadida en la misma transacción) y el índice único parcial de R1.
  Re-encadenada tras el merge (commit `b9d21e0`) porque el PR #152 sincronizó su base antes de
  que aterrizaran otros dos merges con migración propia (#146, #151), y `main` volvió a quedar
  con dos cabezas; el id cambió de `80ea2e544b36` a este por la misma razón que la primera
  re-cadena documentó: una BD de worktree ya sellada con el id viejo debe fallar alto, no
  creerse en cabeza y saltarse en silencio el DDL de las otras dos ramas.
- `backend/tests/messaging/` — incluye `test_tenant_isolation.py`,
  `test_free_text_sink_contract.py`, `test_pipeline_atomicity.py`, `test_escalation.py` y
  `test_portal_use_cases.py`.
- `docs/messaging-ai.md` — cómo se opera la capability.
- `docs/diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png` — el pipeline.
