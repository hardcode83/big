# Design: human-reply-outbound-delivery

## Context

Hoy, `RecordHumanReplyUseCase`
(`backend/app/messaging/application/use_cases.py:642-732`) persiste el `Message`,
deriva `sender_type` del rol, ejecuta `take_over` si la conversación estaba en
`PENDING_HUMAN`, escribe `TimelineEvent(HUMAN_RESPONSE_SENT)` y commitea — pero
no llama a ningún `OutboundMessagePort.send`. Su constructor (`:655-666`) recibe
`conversations, messages, timeline, uow` y nada más. La ruta
`POST /api/v1/conversations/{id}/messages` (`backend/app/messaging/api/router.py:223-255`)
delega en este caso de uso cuando `sender_type != "GUEST"` (`:246-254`).

`outbound_registry`
(`backend/app/messaging/infrastructure/channels.py:227-269`) construye los
`OutboundMessagePort` por canal — `MANUAL`/`PORTAL` con no-op, `WHATSAPP` con
`DelegatingOutboundAdapter` que delega a `WhatsAppCloudAdapter` o `MockWhatsAppAdapter`,
`EMAIL` con un `DelegatingOutboundAdapter` literal sobre `ConsoleEmailAdapter()`
(no sobre `_email_adapter()`), `PHONE_TRANSCRIPT` con `InboundOnlyAdapter`. Los dos
OTA (`AIRBNB_MSG`/`BOOKING_MSG`) están ausentes por diseño (R6.3). El único
consumidor actual es `ProcessInboundGuestMessageUseCase.execute`
(`backend/app/messaging/application/use_cases.py:509-550`), que lo inyecta como
`channels` en su constructor y lo llama **antes** de armar la fila — así el
`MessageMetadata` lleva ya el `delivery_status`/`delivery_error_code` que el commit
único de R4.7 hace durables a la vez que el `Message`.

## Decisions

### D1 — Inyectar el registry de canales en `RecordHumanReplyUseCase`

**Chosen:** añadir `channels: dict[ConversationChannel, OutboundMessagePort]` como
keyword-only al constructor de `RecordHumanReplyUseCase`, mismo nombre y misma forma
que `ProcessInboundGuestMessageUseCase.channels` (`:86-95`). Cablear en
`get_record_human_reply_use_case`
(`backend/app/messaging/api/dependencies.py:108-114`) con la misma instancia de
`outbound_registry(messages)` que `get_process_inbound_message_use_case` construye
(la función `outbound_registry` ya exige `messages: MessageRepository` para
resolver `last_inbound_at` en `WHATSAPP`).

**Rejected:** pasar el registry como argumento al `execute(...)` — invierte la
dependencia (la capa `api/` resolvería el registry y se lo pasaría al caso de uso,
que es donde la decisión de qué hay que cablear). Va contra `steering/backend.md`
("routers finos → casos de uso → servicios de dominio").

**Rejected:** una propiedad nueva en `Conversation` que diga "este canal ya fue
entregado" — duplica el dominio de `OutboundMessagePort` dentro de la entidad y
rompe la inversión de dependencias hexagonal.

### D2 — Despachar antes de construir la `Message`

**Chosen:** reordenar el `execute` para que el envío por el adapter ocurra **antes**
de construir el `Message`, igual que en el camino de la IA (D14 / R4.7): un único
commit con la fila ya armada con su `delivery_status`/`delivery_error_code`. El
`Message` y su `MessageMetadata` se construyen una sola vez con el resultado del
`adapter.send` ya conocido — `Message` es `frozen=True`
(`backend/app/messaging/domain/entities.py:280-297`), así que mutar después del
envío no es una opción.

**Rejected:** construir la `Message` primero, persistirla, llamar al adapter,
anotar el resultado en `metadata` con un `save()` posterior — exigiría `save()` en
`MessageRepository`, que R1.1 no admite, y rompe "append-only" del comentario de
`entities.py:282-296`. Es exactamente el patrón que D14 sustituyó en el camino de la
IA: nada durable hasta el único `commit`.

**Rejected:** una transacción por fila (commit tras el envío, otro tras el
timeline) — R4.7 fija un único commit por petición para evitar estado
"medio-escrito" entre el `Message`, el `Conversation` y el `TimelineEvent`. El
camino de la IA ya cumple esto; el humano hereda esa disciplina por simetría.

### D3 — Canal sin adapter: persistir y no lanzar

**Chosen:** cuando `conversation.channel` no esté en `channels`
(`AIRBNB_MSG`/`BOOKING_MSG`), construir `MessageMetadata(delivery_status=DELIVERY_STATUS_FAILED,
delivery_error_code=ChannelErrorCode.ADAPTER_UNAVAILABLE)`, persistir la fila,
ejecutar `register_message` + `take_over` si correspondía, escribir
`HUMAN_RESPONSE_SENT`, hacer el commit único, y **no** lanzar `PMSChannelUnavailableError`.
El resultado es un valor, no un 5xx.

**Rejected:** lanzar `PMSChannelUnavailableError` como hace el camino de la IA —
rompe R1.2 (la fila humana debe persistir) y propagaría un 5xx al router para una
operación que el operador sí hizo bien: el `Message` queda en la BD y el humano
sigue siendo responsable del canal.

**Rejected:** marcar la conversación con un nuevo `ConversationStatus.UNREACHABLE`
o similar — mete un estado nuevo sólo para este caso y ningún spec lo pide.

### D4 — `MessageMetadata` con `delivery_status`/`delivery_error_code`, sin `escalation_reason` ni `template_*`

**Chosen:** el `MessageMetadata` lleva sólo los dos campos del envío (los que la
IA también lleva) y `source_message_id` no aplica aquí (la IA cita el del huésped
porque es una respuesta a algo; el humano responde por su cuenta). No lleva
`escalation_reason`: la IA lo usa para registrar por qué la conversación pasó a un
humano, y el humano no escala — ya está en el hilo. No lleva `template_key` ni
`template_version`: el humano escribe prosa, no plantilla (regla 11, excepción 3).

**Rejected:** copiar la estructura completa de la IA con `escalation_reason=None` y
`template_*=None` — `to_dict` (`backend/app/messaging/domain/value_objects.py:444-458`)
emite sólo las claves presentes, así que pasar `None` no aporta y oscurece la
intención. Si la `MessageMetadata` no nombra un campo, no está contando nada sobre
él.

### D5 — `outbound_registry` resuelve `EMAIL` con `_email_adapter()`

**Chosen:** cambiar la línea `ConversationChannel.EMAIL` en `outbound_registry`
(`backend/app/messaging/infrastructure/channels.py:265-267`) para construir el
`ConsoleEmailAdapter()` desde la función `_email_adapter()`
(`backend/app/notifications/infrastructure/adapters.py:394-423`). Sin
`smtp_host`, devuelve `ConsoleEmailAdapter()`; con `smtp_host`, valida los cinco
campos SMTP y devuelve `SMTPEmailAdapter()`. El `DelegatingOutboundAdapter`
resultante pasa el `body` igual que antes; el `notification_logs` lo escribe la
`SMTPEmailAdapter` cuando hay relay.

**Rejected:** construir `SMTPEmailAdapter()` directamente — pierde la validación
de los cinco campos y el TLS check que `_email_adapter()` ya hace, y duplica la
disciplina de R2.1/R2.2 en dos sitios.

**Rejected:** un getter perezoso (`def email_adapter(): ...`) — `outbound_registry`
es eager por contrato y por test
(`backend/tests/messaging/test_channels.py`), cambiarlo a perezoso obligaría a
mover el `try/except` de `SMTPConfigurationError` al lugar donde se llama, y ese
sitio es exactamente el que se quiere que NO lance.

### D6 — `phone_number_id` desde `conversation.business_phone_number`, sin `template_id`

**Chosen:** pasar `phone_number_id=conversation.business_phone_number` al
`adapter.send` cuando `conversation.channel is WHATSAPP`, igual que el camino de la
IA (`backend/app/messaging/application/use_cases.py:542-550`). No pasar
`template_id` (ningún productor lo hace hoy; auditoría 2026-09-04,
`docs/whatsapp-cloud-adapter.md:86-92`). El resultado de un envío fuera de la
ventana de 24 h se traduce a `ChannelErrorCode.OUTSIDE_SESSION_WINDOW` por la
`_ERROR_TRANSLATION` (`channels.py:50-59`), se persiste como `FAILED` con ese
código en `metadata`, y queda como límite conocido (R3.2).

**Rejected:** un `template_id` hardcoded — ninguna plantilla de Meta está aprobada
en MVP, y el roadmap marca el trabajo de plantillas como posterior a MVP.

**Rejected:** dejar `template_id` parametrizable desde el router — el FE no lo
conoce y la API no lo acepta; abrir esa puerta sin consumidor es dead surface.

### D7 — `_recipient_contact` como helper a nivel de módulo

**Chosen:** mover el `_recipient_contact` actual de
`ProcessInboundGuestMessageUseCase` a una función de módulo en
`backend/app/messaging/application/use_cases.py` (al lado de los otros helpers)
que toma `(guests: GuestRepository, tenant_id, conversation)` y devuelve el
contacto por canal. Ambos casos de uso (`ProcessInboundGuestMessageUseCase` y
`RecordHumanReplyUseCase`) la llaman. La forma de los argumentos no cambia: el
camino de la IA pasa `self._guests`, el humano también.

**Rejected:** duplicar el helper en cada caso de uso — son ~10 líneas idénticas
que ahora mismo viven en `ProcessInboundGuestMessageUseCase._recipient_contact`
(`use_cases.py:312-336`). Una vez copiadas en otro sitio, divergen sin que nadie
lo note.

**Rejected:** poner la lógica en `Conversation` o en un helper de `channels.py` —
la consulta al `GuestRepository` cruza la capa de dominio (`:330-336`), así que
mantenerla en `application/` es lo que `steering/backend-architecture.md` espera.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Application use case | `backend/app/messaging/application/use_cases.py` | (1) añadir `channels: dict[ConversationChannel, OutboundMessagePort]` al constructor de `RecordHumanReplyUseCase`; (2) mover `_recipient_contact` a helper de módulo; (3) reordenar `execute` para llamar al adapter antes de construir el `Message`, persistir `MessageMetadata(delivery_status, delivery_error_code)`, mantener el commit único. |
| Composition root | `backend/app/messaging/api/dependencies.py:108-114` | Pasar `channels=outbound_registry(messages)` a `RecordHumanReplyUseCase`, usando la misma instancia de `messages` que `get_process_inbound_message_use_case:83-105` ya construye. |
| Channels registry | `backend/app/messaging/infrastructure/channels.py:265-267` | Reemplazar `ConsoleEmailAdapter()` literal por `_email_adapter()` para `EMAIL` (import ya existente vía `notifications.infrastructure.adapters`). |
| Spec | `sdd/specs/messaging-ai.md:187-191` | Enmendar R4 con las cuatro garantías del envío humano (despacho por canal, anotación en metadata, no-escalación, no-emisión de `AI_RESPONSE_SENT`). |
| Doc | `docs/messaging-ai.md:243-275` | Añadir el límite "fuera de ventana de 24 h en WhatsApp → FAILED, sin plantilla aprobada en MVP", numerándolo en la lista. |

## Data & interfaces

- `Message` (`backend/app/messaging/domain/entities.py:280-309`): sin cambios. Los
  campos nuevos que el `MessageMetadata` lleva (`delivery_status`,
  `delivery_error_code`) ya existían y estaban validados en `MessageMetadata.__post_init__`
  (`value_objects.py:411-443`).
- `MessageMetadata` (`backend/app/messaging/domain/value_objects.py:386-458`): sin
  cambios. La fila del humano no nombra `escalation_reason` ni `template_*` —
  `to_dict` no emite claves con valor `None`.
- API `POST /api/v1/conversations/{id}/messages` (`messaging/api/router.py:223-255`):
  sin cambios. El caso de uso ya devuelve `MessageResponse.from_domain(message)`,
  y la fila ya tiene su `metadata` (sólo las claves presentes, vía `to_dict`).
- `OutboundMessagePort.send` (`backend/app/messaging/domain/ports.py`): sin cambios.
  La firma ya exige `template_id`/`phone_number_id` (`:96-99` en `channels.py`); el
  humano pasa `phone_number_id` y omite `template_id`, como la IA.
- Alembic: sin migraciones. No cambia el esquema.

## Risks & mitigations

- **Riesgo**: el helper `_recipient_contact` se mueve de método de instancia a
  función de módulo; cualquier test que parchee `self._guests` con un mock puede
  romperse. Mitigación: el helper recibe `guests` como argumento explícito; el
  test del camino de la IA sigue parcheando `self._guests` y pasándoselo. La
  suite del módulo (`tests/messaging/application/test_use_cases.py`) verifica el
  contrato.
- **Riesgo**: el `EMAIL` con `SMTP_HOST` configurado pero a medias falla con
  `SMTPConfigurationError` al construir el `outbound_registry`. Mitigación: el
  `outbound_registry` ya se construye una vez por request en el composition
  root; la configuración parcial sigue siendo el mismo riesgo que el módulo
  `notifications` ya tenía documentado (R2.1, `adapters.py:394-423`). Ningún
  path nuevo lo expone.
- **Riesgo**: el `MessageMetadata(delivery_error_code=...)` con un código que no
  pertenezca a `ChannelErrorCode` levanta `MessagingValidationError` en
  `__post_init__`. Mitigación: la fuente del código es `_translate(...)` o el
  literal `ChannelErrorCode.ADAPTER_UNAVAILABLE`, ambos miembros del enum.
- **Riesgo**: la suite del camino de la IA asume que el helper `_recipient_contact`
  sigue siendo método de instancia (`test_process_inbound.py`). Mitigación:
  actualizar las aserciones que parchean el método a pasar el `guests` mock al
  helper de módulo; ningún cambio de comportamiento.
- **Riesgo**: el adapter `_email_adapter()` añade una dependencia de
  `notifications.infrastructure.adapters` desde `messaging.infrastructure.channels`
  (ya existente para `ConsoleEmailAdapter`/`MockWhatsAppAdapter`/`WhatsAppCloudAdapter`),
  pero `_email_adapter()` no estaba importado antes. Mitigación: el import es
  trivial y ya vive en el mismo módulo que los otros tres.

## Open questions

- Ninguna con respuesta: la única decisión que el roadmap marcaba como "elige uno
  de los dos" (mostrar `metadata` en la UI) ya está resuelta por el alcance `[BE]`
  del entry: queda como candidata `[FE]` declarada en el proposal (`Out of
  scope`).