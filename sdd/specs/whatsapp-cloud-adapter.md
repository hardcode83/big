# WhatsApp Cloud API

## Purpose

Un huésped puede escribir y recibir mensajes de WhatsApp de verdad, en las dos direcciones,
contra la **Cloud API de WhatsApp Business de Meta** — una única App de Meta para toda la
cuenta de AutoHostAI, con un número de WhatsApp Business por tenant bajo esa misma App. La
salida reutiliza el puerto `NotificationAdapter`/`OutboundMessagePort` que ya existía (antes
servido por un mock); la entrada añade el primer camino real por el que un huésped inicia una
conversación sin que un manager la transcriba ni el huésped tenga un enlace de portal.

Meta impone una **ventana de servicio al cliente**: texto libre solo dentro de las 24 horas
siguientes al último mensaje del huésped; fuera de ella, solo una plantilla pre-aprobada por
Meta. El adapter hace cumplir esa ventana él mismo, en vez de confiar en que cada llamante la
recuerde.

Operación (variables de entorno, alta de un número por tenant, el handshake de verificación de
Meta): ver `docs/whatsapp-cloud-adapter.md`.

## Requirements

### R1 — Adapter de salida real

- THE SYSTEM SHALL resolver el canal `WHATSAPP` en `adapter_registry()`
  (`app/notifications/infrastructure/adapters.py`) a `WhatsAppCloudAdapter` cuando
  `WHATSAPP_PROVIDER=meta`, o a `MockWhatsAppAdapter` (preservando el comportamiento previo)
  cuando `WHATSAPP_PROVIDER=mock` — sin valor por defecto para la propia variable, regla 8 de
  `steering/security.md`. `twilio` es un valor futuro no implementado.
- THE SYSTEM SHALL implementar `WhatsAppCloudAdapter` contra `NotificationAdapter`, con el mismo
  contrato de retorno que el mock que sustituye: nunca lanza por un fallo de entrega, y un
  destinatario en blanco se rechaza como `NotificationResult.failure`.
- IF Meta no responde, responde con un error no clasificable, o hay un timeout de red, THEN THE
  SYSTEM SHALL devolver `NotificationResult.failure`/`ChannelSendResult.failure` con un código
  del enum cerrado — nunca una excepción sin capturar ni el texto libre del proveedor en el
  resultado.
- THE SYSTEM SHALL enviar el "from" de una respuesta dentro de una conversación desde el mismo
  `phone_number_id` al que escribió el huésped (`Conversation.business_phone_number`, fijado una
  vez al abrir el hilo), y no desde el `WHATSAPP_PHONE_NUMBER_ID` global de la plataforma —
  Meta rechaza una respuesta que llega desde un número con el que el huésped no abrió sesión.
  Un envío proactivo sin conversación de huésped detrás (staff) SHALL usar el `phone_number_id`
  de construcción del adapter, al no tener un número de guest-session del que partir.

### R2 — Ventana de servicio al cliente de 24 horas

- THE SYSTEM SHALL resolver `last_inbound_at` para un envío por el canal `WHATSAPP` desde
  `MessageRepository.last_guest_message_at(tenant_id, conversation_id)` — el `created_at` del
  `Message` más reciente con `sender_type = GUEST` en esa conversación — y no desde
  `Conversation.last_message_at`, que se actualiza también con mensajes de la IA o de un manager
  y reabriría la ventana sin que el huésped haya escrito.
- WHEN el último mensaje del huésped fue hace **menos** de 24 horas (o no hay conversación de
  huésped detrás, con texto libre pedido explícitamente), THE SYSTEM SHALL permitir texto libre.
- IF el último mensaje del huésped fue hace **24 horas o más**, THEN THE SYSTEM SHALL exigir un
  `template_id` en vez de texto libre; sin ninguno de los dos, SHALL devolver
  `OUTSIDE_SESSION_WINDOW` (`NotificationErrorCode`/`ChannelErrorCode`) en vez de intentar un
  envío de texto libre que Meta rechazaría o descartaría en silencio.
- THE SYSTEM SHALL tratar toda notificación proactiva (staff, sin conversación de huésped detrás
  — p.ej. `CLEANING_TASK_ASSIGNED`) como fuera de ventana por construcción, ya que no existe hoy
  ningún registro de "último mensaje entrante" para un hilo de staff.

### R3 — Webhook de entrada: ruta única, firma real de Meta

- THE SYSTEM SHALL exponer la recepción en una **única ruta fija**,
  `POST /api/v1/webhooks/whatsapp` (anónima, sin segmento por tenant) — Meta admite una sola URL
  de webhook por App, no una por tenant, así que no hay ruta ni token que mintar por tenant.
- THE SYSTEM SHALL verificar la autenticidad de cada entrega con la firma real de Meta
  (`X-Hub-Signature-256`, HMAC-SHA256 sobre el cuerpo crudo, clave `WHATSAPP_APP_SECRET` —
  única, global, comparación en tiempo constante) y no SHALL usar el mecanismo de cabecera
  estática de la regla 12(a): esa regla se acota a "webhooks sin firma", y el de Meta la lleva.
- IF la firma es inválida (cabecera ausente, mal formada, o secreto que no coincide), THEN THE
  SYSTEM SHALL responder de forma indistinguible entre esos motivos, sin persistir nada.
- IF la firma es válida pero el `phone_number_id` de la entrega no está asociado a ningún tenant
  (número aún sin aprovisionar, R6), THEN THE SYSTEM SHALL registrar la entrega, visible al
  operador, y no SHALL despacharla ni tratarla como el mismo caso que una firma inválida — no es
  adversarial: producirla exige conocer el `WHATSAPP_APP_SECRET`.
- THE SYSTEM SHALL responder a la ruta de recepción el mismo límite de tasa y tope de tamaño de
  cuerpo que el resto de webhooks entrantes, y SHALL desacoplar el procesamiento del mensaje de
  la respuesta HTTP: encola `process_inbound_whatsapp_message` inmediatamente tras el commit de
  la fila, sin esperar a ninguna cadencia periódica ni hacer ninguna llamada saliente síncrona.
- THE SYSTEM SHALL deduplicar por `provider_message_id` (el `wamid…` de Meta, único e indexado):
  una redelivery del mismo mensaje no crea una segunda fila ni se despacha una segunda vez.
- THE SYSTEM SHALL responder a `GET /api/v1/webhooks/whatsapp` el handshake de verificación de
  Meta — que se ejecuta al (re)registrar la suscripción del webhook en el panel de la App de
  Meta —: eco de `hub.challenge` en texto plano solo si `hub.verify_token` coincide con
  `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (rule 8, sin valor por defecto); si no coincide o falta,
  `403` sin cuerpo. Sin este valor correcto, Meta rehúsa guardar la suscripción — un fallo de
  configuración, no una brecha de seguridad en tiempo de ejecución.

### R4 — Resolución de identidad: teléfono → tenant → huésped → estancia

- THE SYSTEM SHALL resolver el `tenant_id` de una entrega autenticada a partir del
  `phone_number_id` que Meta adjunta como metadato de entrega
  (`value.metadata.phone_number_id`) contra la tabla de aprovisionamiento (R6) — nunca desde la
  ruta (no existe ninguna por tenant) ni desde ningún campo del cuerpo que el remitente
  controle (número de origen, texto).
- THE SYSTEM SHALL normalizar el número del remitente a E.164 y buscar, **solo dentro de ese
  tenant**, un huésped cuyo teléfono coincida — nunca entre tenants.
- WHERE ningún huésped del tenant tiene ese teléfono registrado, THE SYSTEM SHALL registrar el
  mensaje en una conversación visible al operador (sin huésped ni reserva asociados, anclada a
  la propiedad por defecto del tenant, R6) en vez de descartarlo o inventar una asociación.
- WHERE el teléfono coincide con exactamente un huésped y exactamente una estancia activa (con
  un margen de 2 días — `RESERVATION_MATCH_GRACE_DAYS` — a cada lado de la fecha de la
  estancia), THE SYSTEM SHALL anclar la conversación a esa propiedad y esa reserva.
- IF el teléfono coincide con más de un huésped, o con más de una estancia activa del mismo
  huésped, THEN THE SYSTEM SHALL escalar a revisión humana en vez de adivinar cuál es la
  conversación correcta — anclada igualmente a la propiedad por defecto del tenant.
- WHEN la resolución identifica una conversación ya existente para ese huésped, esa propiedad y
  el canal `WHATSAPP`, THE SYSTEM SHALL reutilizarla en vez de crear una nueva por cada mensaje.
  Un remitente aún sin huésped identificado abre su propia fila por mensaje (el `NULL` de
  `guest_id` nunca coincide consigo mismo bajo el índice único parcial), límite aceptado.

### R5 — Entrega al pipeline de mensajería existente

- WHEN la identidad se resuelve (R4), THE SYSTEM SHALL invocar el mismo
  `ProcessInboundGuestMessageUseCase` que usa el portal del huésped, con `sender_type = GUEST` y
  el canal de la conversación ya marcado `WHATSAPP` — sin una segunda copia de la lógica de
  clasificación, escalación o aparición en la bandeja del manager (ver `messaging-ai.md` R4).
- THE SYSTEM SHALL identificar al remitente con `InboundMessageActor(resolved_phone=...)` — la
  tercera identidad posible del actor, junto a `user_id`/`token_hash` (`messaging-ai.md` R4) —
  nunca reutilizando `token_hash` para un número de teléfono.
- WHEN el pipeline genera una respuesta automática para una conversación `WHATSAPP`, THE SYSTEM
  SHALL enviarla por el adapter de R1, sujeta a la ventana de R2.
- THE SYSTEM SHALL truncar (no rechazar) el texto de un mensaje entrante que supere los 4000
  caracteres — el mismo límite de `messages.content` — antes de que la fila pueda existir: un
  rechazo dejaría el mensaje sin la fila que R3 deduplica por `provider_message_id`, así que una
  redelivery de Meta reintentaría ese mensaje para siempre.

### R6 — Aprovisionamiento del número de WhatsApp por tenant

- THE SYSTEM SHALL permitir asociar un `phone_number_id` de la Cloud API de Meta a un tenant
  mediante `POST /api/v1/messaging/whatsapp-phone-number` (autenticado,
  `MANAGE_TENANT_SETTINGS`), aportando también una propiedad por defecto del tenant
  (`default_property_id`, validada como propia de ese tenant) — el destino de los mensajes de
  R4 que no resuelven a una estancia concreta.
- THE SYSTEM SHALL impedir que el mismo `phone_number_id` quede asociado a más de un tenant a la
  vez: un intento de asociarlo a un segundo tenant sin liberarlo antes SHALL fallar de forma
  explícita, nunca sobrescribir la asociación existente en silencio.
- THE SYSTEM SHALL permitir retirar la asociación de un `phone_number_id` con
  `POST /api/v1/messaging/whatsapp-phone-number/release` — el equivalente operativo de "rotar"
  en este modelo, ya que no hay ningún secreto por tenant que rotar (el secreto de firma y la
  ruta son globales, R3).
- THE SYSTEM SHALL auditar tanto la asociación como la liberación (regla 9 de
  `steering/security.md`) — no hay ningún valor que ocultar tras la auditoría, porque
  `phone_number_id` no es un secreto.
- THE SYSTEM SHALL no permitir que ninguna credencial (`WHATSAPP_ACCESS_TOKEN`,
  `WHATSAPP_APP_SECRET`, etc.) viva por tenant: son globales de `Settings`, una única App de
  Meta para toda la cuenta. Un `phone_number_id` filtrado o mal asociado no compromete el
  secreto de firma de ningún otro tenant, pero un secreto de firma filtrado sí compromete a
  todos los tenants a la vez — no hay una segunda ruta ni un segundo secreto por tenant que lo
  acote, a diferencia de `reservations-webhooks`.

## Key files

- `backend/app/notifications/infrastructure/adapters.py` — `WhatsAppCloudAdapter` (real),
  `MockWhatsAppAdapter` (`WHATSAPP_PROVIDER=mock`), `adapter_registry()`.
- `backend/app/messaging/infrastructure/channels.py` — `DelegatingOutboundAdapter` resuelve
  `last_inbound_at`/`template_id`/`phone_number_id` para el canal `WHATSAPP`.
- `backend/app/messaging/api/whatsapp_webhook_router.py` — la ruta única fija, `GET`
  (handshake) y `POST` (recepción).
- `backend/app/messaging/application/webhooks.py` — `ReceiveWhatsAppWebhookUseCase`:
  autenticación, deduplicación, persistencia y despacho.
- `backend/app/messaging/application/whatsapp_inbound.py` — `PostWhatsAppInboundMessageUseCase`:
  resolución de identidad (R4) y entrega al pipeline existente (R5).
- `backend/app/messaging/application/whatsapp_provisioning.py` — asociar/liberar un
  `phone_number_id` (R6).
- `backend/app/messaging/infrastructure/whatsapp_providers.py` — `MetaInboundAdapter`: verifica
  la firma y parsea el payload de Meta hacia `InboundWhatsAppMessage`.
- `backend/app/messaging/domain/value_objects.py` — `InboundWhatsAppMessage` (trunca el texto a
  4000 caracteres).
- `backend/app/messaging/domain/whatsapp_webhook.py` — reexporta `secrets_match`.
- `backend/app/messaging/infrastructure/models.py` — `WhatsAppPhoneNumberModel` (una fila por
  tenant), `WhatsAppInboundEventModel` (la cola de eventos entrantes).
- `backend/app/messaging/api/router.py` — rutas de aprovisionamiento (R6).
- `backend/app/scheduler/whatsapp_tasks.py` — `process_inbound_whatsapp_message`, sin entrada en
  `beat_schedule` (se dispara con `.delay(...)`, nunca por cadencia).
- `backend/app/core/config.py` — `WHATSAPP_PROVIDER` y las cuatro credenciales, sin valor por
  defecto.
- `docs/whatsapp-cloud-adapter.md` — el runbook operativo.
