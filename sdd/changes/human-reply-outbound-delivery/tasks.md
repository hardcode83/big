# Tasks: human-reply-outbound-delivery

## 1. Backend: inyectar canales, despachar por el canal de la conversación y enrutar `EMAIL` por SMTP

- [x] 1.1 Cablear `channels=outbound_registry(messages)` en
      `backend/app/messaging/api/dependencies.py:108-114`, usando la misma
      instancia de `SqlAlchemyMessageRepository(session)` que
      `get_process_inbound_message_use_case:83-105` ya construye (compartir la
      instancia evita un segundo `MessageRepository` para resolver
      `last_inbound_at` en `WHATSAPP`). [R1, R2]
- [x] 1.2 Mover el método de instancia `_recipient_contact`
      (`backend/app/messaging/application/use_cases.py:312-336`) a una función
      de módulo `_recipient_contact(guests, tenant_id, conversation)` al lado de
      los otros helpers; actualizar `ProcessInboundGuestMessageUseCase` para
      llamarla con `self._guests`. [R1]
- [x] 1.3 Añadir `channels: dict[ConversationChannel, OutboundMessagePort]` como
      keyword-only al constructor de `RecordHumanReplyUseCase`
      (`backend/app/messaging/application/use_cases.py:655-666`); actualizar la
      factoría de tests `human_reply_use_case(harness)` en
      `backend/tests/messaging/test_use_cases.py:836-842` para pasar
      `channels=harness.channels`. [R1]
- [x] 1.4 Reordenar `execute` (`use_cases.py:668-732`) para que el envío por el
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
- [x] 1.5 Cambiar `backend/app/messaging/infrastructure/channels.py:265-267`
      para construir el delegate de `EMAIL` con `_email_adapter()` desde
      `app.notifications.infrastructure.adapters` en vez del
      `ConsoleEmailAdapter()` literal. [R2]
- [x] 1.6 Añadir tests en `backend/tests/messaging/test_use_cases.py` para
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

- Section 1 wired `channels` (and a `GuestRepository` for `_recipient_contact`) into
  `RecordHumanReplyUseCase.__init__` as keyword-only — the constructor's `guests` kwarg was not
  in task 1.3 but is required for the module-level `_recipient_contact` (task 1.2 / D7) to
  resolve the recipient on every channel; the next section's spec work should call this out.
- `_recipient_contact` keeps the `contact_kind_for` short-circuit before the guest lookup
  (`WHATSAPP`/`EMAIL` only) so a `MANUAL`/`PORTAL`/`PHONE_TRANSCRIPT` reply returns `None`
  cheaply — same precedence as the original method (D14).
- `RecordHumanReplyUseCase.execute` always builds the `Message` after the `adapter.send` call
  (or after the "no adapter" branch), so `metadata` is constructed once with the final
  `delivery_status`/`delivery_error_code` (D2/D4) — no `metadata=` mutation after `Message(...)`
  because the entity is `frozen=True`.
- The "no adapter" branch (`AIRBNB_MSG`/`BOOKING_MSG`) keeps the `Message`, the
  `HUMAN_RESPONSE_SENT` timeline event and the single `commit()`; no `PMSChannelUnavailableError`
  escapes (R1.2/D3).
- `outbound_registry` imports `_email_adapter` (a leading-underscore module-private function
  in `notifications.infrastructure.adapters`) for the `EMAIL` row only (R2/D5); `WHATSAPP` keeps
  its inline `MockWhatsAppAdapter`/`WhatsAppCloudAdapter` selection (no behaviour change for
  the inbound side).
- The human-reply `Message` carries `metadata` only — no `template_key`/`template_version`/
  `escalation_reason` (D4) — because the human writes prose, not templates, and a failed send
  must not re-escalate (R1.3, test 1.6 (d)).
- Test factory `human_reply_use_case(harness)` gained two kwargs (`guests`, `channels`) and
  three `# type: ignore[arg-type]` comments; the messaging subset of pyright goes from 28
  (baseline) to 27 on the four touched files.