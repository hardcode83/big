# Tasks: human-reply-outbound-delivery

## 1. Backend: inyectar canales, despachar por el canal de la conversación y enrutar `EMAIL` por SMTP

- [ ] 1.1 Cablear `channels=outbound_registry(messages)` en
      `backend/app/messaging/api/dependencies.py:108-114`, usando la misma
      instancia de `SqlAlchemyMessageRepository(session)` que
      `get_process_inbound_message_use_case:83-105` ya construye (compartir la
      instancia evita un segundo `MessageRepository` para resolver
      `last_inbound_at` en `WHATSAPP`). [R1, R2]
- [ ] 1.2 Mover el método de instancia `_recipient_contact`
      (`backend/app/messaging/application/use_cases.py:312-336`) a una función
      de módulo `_recipient_contact(guests, tenant_id, conversation)` al lado de
      los otros helpers; actualizar `ProcessInboundGuestMessageUseCase` para
      llamarla con `self._guests`. [R1]
- [ ] 1.3 Añadir `channels: dict[ConversationChannel, OutboundMessagePort]` como
      keyword-only al constructor de `RecordHumanReplyUseCase`
      (`backend/app/messaging/application/use_cases.py:655-666`); actualizar la
      factoría de tests `human_reply_use_case(harness)` en
      `backend/tests/messaging/test_use_cases.py:836-842` para pasar
      `channels=harness.channels`. [R1]
- [ ] 1.4 Reordenar `execute` (`use_cases.py:668-732`) para que el envío por el
      adapter ocurra **antes** de construir el `Message` y siguiendo el orden:
      (a) `_recipient_contact` para resolver el destinatario;
      (b) `adapter = self._channels.get(conversation.channel)` — si es `None`,
      construir `MessageMetadata(delivery_status=DELIVERY_STATUS_FAILED,
      delivery_error_code=ChannelErrorCode.ADAPTER_UNAVAILABLE)` y saltar el
      `adapter.send`;
      (c) `result = await adapter.send(...)` con `phone_number_id=
      conversation.business_phone_number` cuando
      `conversation.channel is WHATSAPP`, y sin `template_id`;
      (d) construir `Message` con `metadata=MessageMetadata(delivery_status=
      DELIVERY_STATUS_SENT if result.delivered else DELIVERY_STATUS_FAILED,
      delivery_error_code=result.error_code)`;
      (e) `register_message`/`take_over` (sin cambios) → `commit()` único. [R1]
- [ ] 1.5 Cambiar `backend/app/messaging/infrastructure/channels.py:265-267`
      para construir el delegate de `EMAIL` con `_email_adapter()` desde
      `app.notifications.infrastructure.adapters` en vez del
      `ConsoleEmailAdapter()` literal. [R2]
- [ ] 1.6 Añadir tests en `backend/tests/messaging/test_use_cases.py` para
      cubrir: (a) `WHATSAPP` con `result.delivered=True` →
      `delivery_status=SENT`; (b) `WHATSAPP` con `result.delivered=False` y
      código traducido → `delivery_status=FAILED` y `delivery_error_code`
      preservado; (c) `AIRBNB_MSG` (sin adapter) →
      `delivery_status=FAILED`, `delivery_error_code=ADAPTER_UNAVAILABLE`, sin
      `HUMAN_RESPONSE_SENT` levantado; (d) respuesta humana no escala aunque el
      envío falle; (e) `phone_number_id` pasa `business_phone_number` para
      `WHATSAPP`. [R1]

## 2. Specs y docs: enmendar R4 y declarar el límite de la ventana 24 h

- [ ] 2.1 Enmendar `sdd/specs/messaging-ai.md:187-191` para añadir a R4 las
      cuatro garantías del envío humano: despacho por el canal de la
      conversación, anotación en `metadata`, no-escalación y no-emisión de
      `AI_RESPONSE_SENT` (sólo `HUMAN_RESPONSE_SENT`). [R3]
- [ ] 2.2 Añadir el límite "respuesta humana por WhatsApp fuera de ventana de
      24 h queda como `FAILED` sin reintento automático —no hay plantillas
      aprobadas en MVP—" al bloque de siete límites de
      `docs/messaging-ai.md:243-275`, numerándolo en orden. [R3]

## 3. Verification

- [ ] 3.1 Suite del backend: `docker compose exec backend uv run pytest` pasa
      entera (incluye `tests/messaging/application/test_use_cases.py` y
      `tests/messaging/test_channels.py`). [R1, R2, R3]
- [ ] 3.2 Lint estático: `docker compose exec backend uv run pyright .` no
      añade findings al baseline. [R1, R2]
- [ ] 3.3 Grep de la regla de verificación del roadmap:
      `rtk proxy grep -n "adapter.send" backend/app/messaging/application/use_cases.py`
      devuelve dos caminos, no uno. [R1]
- [ ] 3.4 Comprobación manual con `WHATSAPP_PROVIDER=mock`: una respuesta
      humana en una conversación `WHATSAPP` produce una línea
      `notifications.mock_whatsapp_delivered` y la fila del `Message` lleva
      `metadata.delivery_status="SENT"`. [R1]

## Implementation Notes