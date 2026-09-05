# human-reply-outbound-delivery

[BE] **la respuesta del manager se guarda y nunca sale**.

> Hito «MVP operable» 2 — *el huésped real* (auditoría del 2026-09-04). Prerrequisito de
> cualquier demostración por WhatsApp: sin esto el producto sólo contesta con la IA.

**El hecho medido (2026-09-04)**: `RecordHumanReplyUseCase`
(`backend/app/messaging/application/use_cases.py:642-732`) se construye con `conversations,
messages, timeline, uow` (:655-666) — **sin** `channels: dict[ConversationChannel,
OutboundMessagePort]`. Su `execute` deriva `sender_type` del rol, persiste el `Message`,
`register_message`, hace `take_over` si la conversación estaba `PENDING_HUMAN`, escribe
`HUMAN_RESPONSE_SENT` y commitea (:696-732). **No llama a ningún `adapter.send`.** El único
camino que usa un adapter de salida es el de la respuesta de la IA: `outbound_registry` en
:509-517 y `adapter.send(...)` en :542-550. El frontend llega por `POST /conversations/{id}/messages`
sin `sender_type` (`messaging/api/router.py:246-254`; `specs/conversations-inbox.md:103-107`).

**Por qué no es cosmético**: para `PORTAL` da igual —la fila es la entrega y el huésped la lee
en `GET /api/v1/guest/messages/{token}` cada 15 s—. Para `WHATSAPP` y `EMAIL`, el huésped que
abre un hilo recibe la respuesta automática y **nunca la humana**, con credenciales de Meta
configuradas o sin ellas. Es exactamente el bucle que el producto vende (PRD §13: IA de primer
nivel y escalado humano). Y está **verde y sin declarar**: R4 de `specs/messaging-ai.md:187-191`
exige sólo persistir + timeline + `take_over`, la suite lo prueba, y ningún spec ni doc lo lista
como límite (`docs/messaging-ai.md:243-275` enumera siete límites y éste no está).

**El segundo hueco, del mismo módulo**: `outbound_registry` (`messaging/infrastructure/channels.py:259-269`)
hardcodea `ConsoleEmailAdapter()` para `ConversationChannel.EMAIL` (:265-267) en vez de pasar
por `_email_adapter()` (`notifications/infrastructure/adapters.py:410-423`), que sí elige SMTP
cuando `SMTP_HOST` está configurado. Una conversación por email se registra en el log y no se
relevá aunque `smtp-delivery-adapter` esté entregado.

**Alcance**: (1) inyectar el registry de canales en `RecordHumanReplyUseCase` y enviar por el
canal de la conversación tras persistir, con el mismo contrato «el fallo es un valor, nunca una
excepción» que ya rige para la IA (`specs/messaging-ai.md:282-291`); (2) `outbound_registry`
resuelve `EMAIL` con `_email_adapter()`; (3) enmendar R4 del spec y añadir el límite que
corresponda a `docs/messaging-ai.md`.

**Lo que decide y no es cosmético**:

1. **Qué pasa cuando el envío falla** (`OUTSIDE_SESSION_WINDOW` en WhatsApp fuera de las 24 h,
   `CHANNEL_INBOUND_ONLY`, `PMSChannelUnavailableError` para `AIRBNB_MSG`/`BOOKING_MSG`). En el
   camino de la IA un fallo escala (`DELIVERY_FAILED`, :566-587); en el humano ya está el humano,
   así que escalar no significa nada. Recomendación: persistir igual, guardar
   `delivery_status`/`delivery_error_code` en `metadata` como ya hace la IA, y **responder al
   manager** con ese estado para que la UI lo pinte. Hoy `features/conversations/data/dto.ts:9-11,49-59`
   **no mapea `metadata`** a propósito, así que un fallo de entrega es invisible: o esta entrada
   ensancha el DTO —lo que la hace `[BE+FE]`— o lo deja como candidata `[FE]` declarada.
2. **La ventana de 24 h de WhatsApp muerde aquí más que en la IA**: la IA responde segundos
   después del mensaje del huésped; el humano puede tardar horas. Fuera de ventana sólo vale una
   plantilla aprobada, y **ningún productor pasa `template_id`** (auditoría 2026-09-04;
   `docs/whatsapp-cloud-adapter.md:86-92`). Para el MVP: fallo declarado y visible; la plantilla
   es trabajo de Meta posterior.
3. **`business_phone_number`** de la conversación es el remitente (`use_cases.py:542-550`,
   `phone_number_id=conversation.business_phone_number`): el humano responde desde el mismo
   número que la IA, no desde uno del tenant.
4. **Regla 11**: el cuerpo del mensaje del manager es prosa de una persona sobre su ámbito
   (excepción 3); no cambia nada de lo que ya rige para `messages.content`.

**Fuera de alcance**: `escalate`/`resolve` desde el frontend (`router.py:258`, :284, sin
llamante — candidata `[FE]`); borradores de IA con aprobación (no existen ni en PRD); plantillas
de Meta; mensajería OTA (`beds24-messaging-adapter`).

**Verificación**: con `WHATSAPP_PROVIDER=mock`, una respuesta humana produce una línea
`notifications.mock_whatsapp_delivered`; con `SMTP_HOST` y un hilo `EMAIL`, el correo llega. Y
`rtk proxy grep -n "adapter.send" backend/app/messaging/application/use_cases.py` devuelve dos
caminos, no uno.
