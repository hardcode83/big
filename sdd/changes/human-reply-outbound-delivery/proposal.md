# Proposal: human-reply-outbound-delivery

## Why

La respuesta humana en una conversación se persiste (`RecordHumanReplyUseCase`,
`backend/app/messaging/application/use_cases.py:642-732`), pero **no sale del backend**:
el caso de uso se construye con `conversations, messages, timeline, uow` y sin registry
de canales (`:655-666`), y su `execute` (`:696-732`) persiste el `Message`, hace
`take_over` si tocaba, escribe `HUMAN_RESPONSE_SENT` y commitea — pero no llama a
ningún `adapter.send`. El único que sí lo hace es el camino de la IA
(`ProcessInboundGuestMessageUseCase`, `outbound_registry` en `:509-517` y
`adapter.send(...)` en `:542-550`). Para `PORTAL` da igual —la fila es la entrega—;
para `WHATSAPP` y `EMAIL` el huésped recibe la IA y nunca al humano, con credenciales
de Meta configuradas o sin ellas. Es el bucle que el producto vende (PRD §13: IA de
primer nivel y escalado humano) y está **verde y sin declarar**: R4 de
`specs/messaging-ai.md:187-191` exige sólo persistir + timeline + `take_over`, la
suite lo prueba, y ningún spec ni doc lo lista como límite. Análisis completo en
`sdd/roadmap/human-reply-outbound-delivery.md`.

El segundo hueco, del mismo módulo: `outbound_registry`
(`backend/app/messaging/infrastructure/channels.py:259-269`) hardcodea
`ConsoleEmailAdapter()` para `ConversationChannel.EMAIL` (`:265-267`) en vez de pasar
por `_email_adapter()` (`backend/app/notifications/infrastructure/adapters.py:410-423`),
que sí elige SMTP cuando `SMTP_HOST` está configurado. Una conversación por email se
registra en el log y no se envía aunque `smtp-delivery-adapter` esté entregado.

## What changes

`RecordHumanReplyUseCase` recibe el registry de canales
(`dict[ConversationChannel, OutboundMessagePort]`) en su constructor —mismo puerto que
ya inyecta el camino de la IA, sin nuevo adaptador—. Tras persistir el `Message`,
derivar el `sender_type`, ejecutar `register_message` y, si la conversación esperaba a
una persona, hacer `take_over`, **despacha el `content` por el adapter del canal de la
conversación** (`conversation.channel`), siguiendo el mismo contrato "el fallo es un
valor, nunca una excepción" que ya rige para la IA (`specs/messaging-ai.md:282-291`):
la fila se conserva, el resultado se anota en `metadata` con la misma forma que la IA
usa para `delivery_status`/`delivery_error_code`/`escalation_reason`, y el commit se
hace una vez al final.

`outbound_registry` resuelve `EMAIL` con `_email_adapter()` en vez de la instancia
literal de `ConsoleEmailAdapter`, así una conversación `EMAIL` con `SMTP_HOST`
configurado llega al relay real. Sin SMTP configurado, sigue cayendo a
`ConsoleEmailAdapter` —la forma de R2.1/R2.2 del módulo `notifications`—.

`business_phone_number` de la conversación es el `phone_number_id` que se pasa al
adapter de WhatsApp (mismo trato que el camino de la IA,
`backend/app/messaging/application/use_cases.py:542-550`): el humano responde desde
el mismo número que la IA, no desde uno del tenant.

## Requirements

### R1 — La respuesta humana se envía por el canal de la conversación

**As a** property manager o tenant owner, **I want** que mi respuesta en una
conversación `WHATSAPP`/`EMAIL`/`MANUAL`/`PORTAL`/`PHONE_TRANSCRIPT` llegue al huésped
o quede registrada como intento de envío en mi registro, **so that** el bucle "IA
responde → humano toma el relevo" cumpla lo que el producto promete (PRD §13).

Acceptance criteria:

1. WHEN un operador autenticado llama `POST /api/v1/conversations/{id}/messages` con
   `body: { content }` y `sender_type` ausente (R7 de `messaging-ai.md`), THE SYSTEM
   SHALL persistir el `Message`, ejecutar `take_over` si correspondía, emitir
   `TimelineEvent(HUMAN_RESPONSE_SENT)`, y SHALL enviar el `content` por el adapter
   asociado a ese canal en `outbound_registry(conversation.channel)` —incluyendo los
   canales `MANUAL`/`PORTAL`, donde el envío es no-op y la entrega es la propia fila.
2. IF el canal de la conversación no está en `outbound_registry` (`AIRBNB_MSG` o
   `BOOKING_MSG`), THEN THE SYSTEM SHALL persistir el `Message` igual, anotar
   `delivery_status=FAILED`, `delivery_error_code=CHANNEL_INBOUND_ONLY` (o el código
   que traduzca `PMSChannelUnavailableError`, hoy `ADAPTER_UNAVAILABLE`), **sin**
   lanzar la excepción al router —el resultado es un valor, no un 5xx—.
3. WHEN el envío del adapter devuelve `delivered=False`, THE SYSTEM SHALL mantener la
   fila del `Message`, anotar `delivery_status=FAILED` y `delivery_error_code` con el
   código traducido (`OUTSIDE_SESSION_WINDOW`, `ADAPTER_UNAVAILABLE`,
   `INVALID_RECIPIENT`, etc., simétrico con la IA), SHALL **no** escalar la
   conversación (ya está el humano), y SHALL no emitir `AI_RESPONSE_SENT`. El commit
   sigue siendo único.
4. WHEN el envío del adapter devuelve `delivered=True`, THE SYSTEM SHALL anotar
   `delivery_status=SENT` y `delivery_error_code=None` en `metadata`, simétrico con la
   IA.
5. THE SYSTEM SHALL pasar `phone_number_id=conversation.business_phone_number` al
   adapter cuando `conversation.channel is WHATSAPP` — el humano responde desde el
   mismo número que la IA, no desde un `phone_number_id` del tenant.

### R2 — `EMAIL` se enruta a SMTP cuando está configurado

**As a** property manager, **I want** que una respuesta humana en una conversación
`EMAIL` salga por el relay SMTP real si `smtp-delivery-adapter` está desplegado, **so
that** el huésped reciba la respuesta humana por correo y no se quede en una consola
que nadie lee.

Acceptance criteria:

1. WHEN `settings.smtp_host` está configurado, THE SYSTEM SHALL resolver
   `ConversationChannel.EMAIL` en `outbound_registry` con `SMTPEmailAdapter()` vía
   `_email_adapter()`, SHALL heredar su disciplina (verificación de los cinco campos
   SMTP con `SMTPConfigurationError` si falta alguno, TLS obligatorio), y SHALL
   propagar el fallo al anotarlo en `metadata` de la respuesta humana con
   `delivery_error_code=ADAPTER_UNAVAILABLE`.
2. WHEN `settings.smtp_host` está vacío, THE SYSTEM SHALL resolver
   `ConversationChannel.EMAIL` con `ConsoleEmailAdapter()` —la misma instancia que
   `notifications.adapter_registry` elige hoy sin relay—.
3. THE SYSTEM SHALL **no** instanciar `ConsoleEmailAdapter()` directamente en
   `outbound_registry` para `EMAIL`: la resolución pasa por `_email_adapter()`.

### R3 — La especificación declara el nuevo comportamiento y el límite conocido

**As a** reader del spec `messaging-ai.md`, **I want** que R4 cubra el envío por el
canal de la conversación y que el límite "una respuesta humana en `WHATSAPP` puede
fallar fuera de la ventana de 24 h sin plantilla aprobada" esté declarado, **so that**
el siguiente lector del spec no tenga que reauditar el camino para descubrir lo que
hoy ya pasa en producción.

Acceptance criteria:

1. WHEN `specs/messaging-ai.md` se enmienda, THE SYSTEM SHALL añadir a R4 las cuatro
   garantías del envío (despacho por el canal, anotación en `metadata`, no-escalación,
   no-emisión de `AI_RESPONSE_SENT`), con redacción simétrica a R6.2/R6.5.
2. WHEN `docs/messaging-ai.md` se enmienda, THE SYSTEM SHALL añadir el límite
   "respuesta humana por WhatsApp fuera de ventana de 24 h queda como `FAILED` y no
   se reintenta automáticamente —no hay plantillas aprobadas en MVP—" en el bloque de
   siete límites (`:243-275`), numerándolo para preservar el orden.

## Out of scope

- **Mostrar `metadata.delivery_status`/`delivery_error_code` en la UI**:
  `features/conversations/data/dto.ts:9-11,49-59` no mapea `metadata` a propósito,
  así que un fallo de entrega de la respuesta humana es invisible para el operador
  aunque la fila lo registre. Ensanchar el DTO es trabajo `[FE]` propio y se declara
  como candidata a entrada propia; mientras tanto, la fila es la verdad y el fallo
  queda recuperable vía `GET /api/v1/conversations/{id}/messages` cuando el FE lo
  exponga.
- `escalate`/`resolve` desde el frontend (`messaging/api/router.py:258, :284`, sin
  llamante) — candidata `[FE]` declarada.
- Borradores de IA con aprobación —no existen ni en PRD—.
- Plantillas aprobadas de Meta —es trabajo posterior a MVP, ningún productor pasa
  `template_id` hoy (2026-09-04, `docs/whatsapp-cloud-adapter.md:86-92`).
- Mensajería OTA (`beds24-messaging-adapter`) — los canales `AIRBNB_MSG` y
  `BOOKING_MSG` siguen sin adapter y la propuesta los sigue dejando fuera del registry.

## Affected specs

- `sdd/specs/messaging-ai.md` — enmienda de R4 (R3.1).
- `docs/messaging-ai.md` — adición del nuevo límite en el bloque de
  `docs/messaging-ai.md:243-275` (R3.2).