# Tasks: whatsapp-cloud-adapter

## 1. Adapter de salida real (Meta Cloud API) y ventana de 24h en el puerto de notificaciones <!-- panel: PASS 2026-09-02 -->

- [x] 1.1 `backend/app/notifications/domain/results.py`: añadir `NotificationErrorCode.OUTSIDE_SESSION_WINDOW` al enum cerrado. [R2.3]
- [x] 1.2 `backend/app/notifications/domain/ports.py`: ampliar `NotificationAdapter.send` con `last_inbound_at: datetime | None = None` y `template_id: str | None = None` (kwargs opcionales, todo adapter existente sigue sin tocar). [R2.4]
- [x] 1.3 `backend/app/notifications/infrastructure/adapters.py`: sustituir `MockWhatsAppAdapter` por `WhatsAppCloudAdapter` — cliente real de la Cloud API de Meta (Graph API: `POST https://graph.facebook.com/{version}/{WHATSAPP_PHONE_NUMBER_ID}/messages`, Bearer `WHATSAPP_ACCESS_TOKEN`, cuerpo JSON `{messaging_product:"whatsapp", to, type:"text"|"template", text:{body}|template:{name,...}}`), mismo contrato de retorno (`NotificationResult`, rechazo de destinatario en blanco). Dentro de la ventana (o `last_inbound_at is None` con texto libre explícito) envía texto libre; fuera de ella exige `template_id` y sin ninguno de los dos devuelve `NotificationResult.failure(OUTSIDE_SESSION_WINDOW)`. Cualquier error no clasificable del proveedor (timeout, respuesta no-2xx de Graph API) se traduce a `NotificationResult.failure` con un código existente, nunca una excepción sin capturar. Mantener una clase `mock`-mode (puede ser el propio `MockWhatsAppAdapter` renombrado/conservado) para `WHATSAPP_PROVIDER=mock`. [R1.1, R1.4, R1.5, R2.1, R2.2, R2.3]
- [x] 1.4 `backend/app/notifications/infrastructure/adapters.py`: corregir el docstring de la clase sustituida — ya no afirma que la regla 8 "reserva ya" las variables de WhatsApp. `backend/app/core/config.py`: añadir `WHATSAPP_PROVIDER` (`mock`/`meta`, sin default; `twilio` queda como valor futuro no aceptado en este change) y las credenciales de Meta (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` — este último también usado por la verificación de firma de la sección 7 —, sin default, regla 8) y corregir la afirmación falsa de `config.py:253` ("ya reservadas"). `.env.example`: añadir los nombres nuevos sin valor, y corregir también el bloque "Entrega de notificaciones" (línea ~144-146) que hace la misma afirmación falsa sobre WhatsApp. [R1.3]
- [x] 1.5 `backend/app/notifications/infrastructure/adapters.py`: `adapter_registry()` construye `WhatsAppCloudAdapter` o el adapter mock leyendo `settings.WHATSAPP_PROVIDER` (mismo patrón sin argumentos que ya usan sus 3 llamadores actuales — `scheduler/tasks.py`, `auth/api/dependencies.py`). [R1.1, R1.5]
- [x] 1.6 Tests en `backend/tests/notifications/`: ventana de 24h (dentro/fuera, con y sin `template_id`), `OUTSIDE_SESSION_WINDOW` cuando no aplica plantilla, `WHATSAPP_PROVIDER=mock` preserva el comportamiento actual, error no clasificable del proveedor no propaga excepción ni texto libre en el resultado. [R1.4, R1.5, R2.1, R2.2, R2.3]
- [x] 1.7 **Fix de seguimiento, añadida el 2026-09-02** (design D1, addendum tras el hallazgo del panel de sección 4: un número de WhatsApp por tenant, no uno global para toda la plataforma — ver sección 6): `backend/app/notifications/domain/ports.py`: ampliar `NotificationAdapter.send` con un cuarto kwarg opcional, `phone_number_id: str | None = None` (mismo patrón que `last_inbound_at`/`template_id`, todo adapter existente sigue sin tocar). `backend/app/notifications/infrastructure/adapters.py`: `WhatsAppCloudAdapter.send` usa `phone_number_id` si se lo pasan, si no cae al `phone_number_id` del constructor (`settings.WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` de 1.4, sin cambios) — el "from" por defecto para notificaciones proactivas sin conversación de huésped detrás. Test: un `send` con `phone_number_id` explícito lo usa en la URL de Graph API en vez del de construcción; sin él, cae al de construcción como hasta ahora. [D1]

## 2. Delegación en `messaging` y `ChannelErrorCode` <!-- panel: PASS 2026-09-02 -->

- [x] 2.1 `backend/app/messaging/domain/value_objects.py`: añadir `ChannelErrorCode.OUTSIDE_SESSION_WINDOW` (o equivalente), simétrico al de notifications. [R2.3]
- [x] 2.2 `backend/app/messaging/domain/ports.py`: ampliar `OutboundMessagePort.send` con los mismos `last_inbound_at: datetime | None = None`, `template_id: str | None = None`, y un tercero, `tenant_id: uuid.UUID` (sin default, a diferencia de los otros dos): resolver `last_inbound_at` en 2.4 es una consulta acotada por tenant (regla 1) y el puerto no llevaba `tenant_id` en ningún parámetro existente. El único llamante (`messaging/application/use_cases.py`, el caso de uso que genera la respuesta de la IA) ya tiene `tenant_id` en scope — es solo pasarlo. Los otros tres implementadores del puerto (`PanelOutboundAdapter`, `PortalOutboundAdapter`, `InboundOnlyAdapter`) lo aceptan y lo ignoran, igual que ya ignoran `channel`/`language`. [R2.4, D2]
- [x] 2.3 `backend/app/messaging/domain/repositories.py` (`MessageRepository`) y su implementación SQLAlchemy (`SqlAlchemyMessageRepository`): nuevo método `last_guest_message_at(tenant_id, conversation_id) -> datetime | None`, devuelve el `created_at` del `Message` más reciente con `sender_type == MessageSenderType.GUEST` en esa conversación (mismo filtro que ya usa `count_unresolved_guest_messages_with_intent`); `None` si el huésped nunca ha escrito. Resuelto con el usuario el 2026-09-02 (design D2): `Conversation.last_message_at` NO sirve para esto porque lo actualiza cualquier mensaje (huésped, IA o manager) y la ventana real de Meta cuenta solo desde el último mensaje del huésped — usar `last_message_at` reabriría la ventana sin que el huésped haya escrito. [R2.4]
- [x] 2.4 `backend/app/messaging/infrastructure/channels.py`: `DelegatingOutboundAdapter` toma `MessageRepository` como nueva dependencia de constructor; `.send` resuelve `last_inbound_at` con `last_guest_message_at(tenant_id, conversation_id)` (2.3, usando el `tenant_id` de 2.2) **solo** para el canal `WHATSAPP` (los demás canales no necesitan ventana) y pasa `template_id` al delegado; `_translate` mapea el nuevo código de fallo. `outbound_registry()` gana la dependencia `MessageRepository` que necesita pasar y construye el `WhatsAppCloudAdapter`/mock igual que 1.5, leyendo el mismo `settings.WHATSAPP_PROVIDER`. El único llamante de `.send()` (`messaging/application/use_cases.py`) debe actualizarse para pasar `tenant_id=tenant_id` — ya lo tiene en scope. [R1.2, R2.4, R5.3, D2]
- [x] 2.5 Tests en `backend/tests/messaging/`: `last_guest_message_at` (cero mensajes del huésped, uno, varios — devuelve el más reciente; un mensaje de IA/manager posterior al último del huésped NO cambia el resultado; aislamiento de tenant). `test_channels.py`: traducción del nuevo código de fallo, paso de `last_inbound_at`/`template_id` al delegado, respuesta de la IA a una conversación `WHATSAPP` cuyo huésped escribió hace <24h se envía en texto libre, una conversación donde el huésped escribió hace >24h pero un manager respondió hace 1 minuto SIGUE fuera de ventana (el caso que motivó 2.3). [R1.2, R2.4, R5.3]
- [x] 2.6 **Fix de seguimiento, añadida el 2026-09-02** (mismo addendum que 1.7 — depende de 1.7): `backend/app/messaging/domain/ports.py`: ampliar `OutboundMessagePort.send` con un cuarto kwarg opcional, `phone_number_id: str | None = None`. `backend/app/messaging/infrastructure/channels.py`: `DelegatingOutboundAdapter.send` pasa `conversation.business_phone_number` (sección 5, `Conversation.business_phone_number`) como `phone_number_id` al delegado — la respuesta sale del mismo número al que escribió el huésped, nunca del "from" por defecto de la plataforma. Test: la respuesta a una conversación `WHATSAPP` usa el `business_phone_number` de esa conversación como origen, no el de construcción del adapter. [D1]

## 3. Resolución de teléfono y estancia activa <!-- panel: PASS 2026-09-02 -->

- [x] 3.1 `backend/app/guests/domain/repositories.py` (`GuestRepository`) y su implementación SQLAlchemy: `find_by_phone(tenant_id, phone: str) -> list[GuestSummary]`, escopado siempre por `tenant_id`. `backend/app/guests/infrastructure/models.py`: índice `ix_guests_tenant_id_phone`. [R4.2, R4.4]
- [x] 3.2 Normalizador E.164 propio (sin nueva dependencia) para el número del remitente, ubicado junto al resto de utilidades de `messaging/domain/` o `guests/domain/` (a decidir por el implementador según qué módulo lo consume primero); falla cerrado a "sin normalizar" en vez de adivinar un formato no soportado. [R4.2]
- [x] 3.3 `backend/app/reservations/domain/repositories.py` (`ReservationRepository`) y su implementación: `find_active_for_guest(tenant_id, guest_id, *, on_date) -> list[Reservation]`, ventana `check_in_date - RESERVATION_MATCH_GRACE_DAYS <= on_date <= check_out_date + RESERVATION_MATCH_GRACE_DAYS` con `RESERVATION_MATCH_GRACE_DAYS = 2` como constante nombrada. [R4.4]
- [x] 3.4 Migración Alembic (encadenada a la cabeza actual): `ix_guests_tenant_id_phone`. [R4.2]
- [x] 3.5 Tests: `find_by_phone` (cero, uno, varios huéspedes; aislamiento de tenant — un teléfono del tenant B no aparece al buscar en el tenant A), normalizador (formatos válidos e inválidos), `find_active_for_guest` (dentro de ventana, en los bordes de los 2 días, fuera de ventana, cero y varias reservas activas). [R4.2, R4.4]

## 4. Puerto de proveedor entrante y adapter de Meta (hard) <!-- hard --> <!-- panel: PASS 2026-09-03 -->

- [x] 4.1 `backend/app/messaging/domain/ports.py`: protocolo `WhatsAppInboundProviderAdapter` con `verify_signature(*, raw_body: bytes, headers: Mapping[str, str], secret: str, url: str) -> bool` y `parse(*, raw_body: bytes, headers: Mapping[str, str]) -> InboundWhatsAppMessage`. [R3.2]
- [x] 4.2 `backend/app/messaging/domain/value_objects.py`: value object congelado `InboundWhatsAppMessage` (`sender_phone`, `provider_message_id`, `text`, `received_at`, `business_phone_number`). [R3.5, R4.1]
- [x] 4.3 `backend/app/messaging/domain/whatsapp_webhook.py` (nuevo): re-exporta/envuelve `generate_webhook_token`, `hash_webhook_token`, `secrets_match` de `app.integrations.domain.webhook_auth` (import `domain/` → `domain/`, permitido por `test_layering.py`) para el uso de este módulo. [R3.1]
- [x] 4.4 `backend/app/messaging/infrastructure/whatsapp_providers.py` (nuevo): `MetaInboundAdapter` implementando el protocolo — `verify_signature` con HMAC-SHA256 (`X-Hub-Signature-256`) sobre el cuerpo crudo (`raw_body`), usando `settings.WHATSAPP_APP_SECRET` descifrado como clave (comparación en tiempo constante, `hmac.compare_digest`); `parse` interpreta el cuerpo JSON anidado (`entry[].changes[].value.messages[]`: `from`, `id`, `timestamp` en segundos Unix como string, `text.body`, `value.metadata.phone_number_id`) hacia `InboundWhatsAppMessage`. [R3.2, R4.1]
- [x] 4.5 Tests en `backend/tests/messaging/`: firma válida/ inválida/ mal formada de Meta (`X-Hub-Signature-256`), verificación en tiempo constante, `parse` mapea cada campo correctamente y rechaza un cuerpo que no trae los campos esperados (p.ej. `entry`/`changes`/`messages` ausente o vacío — un webhook de Meta de tipo `status` en vez de `messages`). [R3.2, R4.1]
- [x] 4.6 **Fix de seguimiento, añadida el 2026-09-02** (design D3, superseded tras el hallazgo del panel de arquitectura de esta misma sección): `backend/app/messaging/domain/whatsapp_webhook.py` re-exporta `generate_webhook_token`/`hash_webhook_token` además de `secrets_match` — los dos primeros ya no tienen consumidor (no existe ningún token de ruta por tenant en el modelo final, ver sección 3/6/7 más abajo). Quitar esos dos re-exports, dejar solo `secrets_match`. Ningún otro fichero de la sección 4 cambia. [D3]

## 5. Resolución de identidad y conversación (hard) <!-- hard --> <!-- panel: PASS 2026-09-03 -->

- [x] 5.1 `backend/app/messaging/domain/value_objects.py`: ampliar `InboundMessageActor` con `resolved_phone: str | None = None`; `__post_init__` exige **exactamente uno** de `user_id`/`token_hash`/`resolved_phone` (nunca ninguno, nunca dos). [D6]
- [x] 5.2 `backend/app/messaging/domain/entities.py`: `Conversation` gana `business_phone_number: str | None = None` (design D4, addendum del 2026-09-02) — el número de negocio (Meta `phone_number_id`) al que escribió el huésped, fijado una vez al crear el hilo y nunca reescrito; `None` para cualquier canal que no sea `WHATSAPP`. `backend/app/messaging/domain/repositories.py` (`ConversationRepository`) y su implementación: `ensure_whatsapp(tenant_id, *, guest_id, property_id, reservation_id, language, business_phone_number, now)`, mismo `INSERT ... ON CONFLICT DO NOTHING` que `ensure_portal` pero indexado por `(tenant_id, guest_id, property_id)` con `channel = WHATSAPP`. [R4.5, D4]
- [x] 5.3 Migración Alembic (encadenada a la de la sección 3): columna `business_phone_number` en `conversations`, índice único parcial `(tenant_id, guest_id, property_id) WHERE channel = 'WHATSAPP'`. [R4.5]
- [x] 5.4 `backend/app/messaging/application/whatsapp_inbound.py` (nuevo): `PostWhatsAppInboundMessageUseCase` — recibe `tenant_id` **ya resuelto por `phone_number_id`** (sección 7 lo resuelve contra `WhatsAppPhoneNumberModel` de la sección 6, nunca del cuerpo del mensaje) **junto con el `default_property_id` de esa misma fila** (sección 6, `AssociateWhatsAppPhoneNumberUseCase`'s addendum), normaliza el teléfono del remitente (3.2), busca huésped(es) con `find_by_phone` (3.1); cero coincidencias → `ensure_whatsapp` con `property_id=default_property_id`/`reservation_id=None`/`guest_id=None` (conversación visible sin adjuntar a una estancia — `Conversation.property_id` no admite `None`, design D19, así que la propiedad por defecto del tenant es lo que hace la fila construible); una coincidencia → busca reserva activa con `find_active_for_guest` (3.3): cero → `property_id=default_property_id`, una → usa la propiedad de esa reserva, dos o más → escala a revisión humana (`ConversationEscalationStatus` directo, sin pasar por el clasificador de IA, `property_id=default_property_id` igualmente); dos o más huéspedes → escala igual, `property_id=default_property_id`. Reutiliza la conversación existente si ya hay una para ese huésped+propiedad+canal `WHATSAPP` (con `guest_id=None` la reutilización solo aplica cuando también coincide el `NULL`, que nunca coincide consigo mismo — cada mensaje de un remitente aún no identificado abre su propia fila, límite ya aceptado en el design original para el caso simétrico). Pasa `business_phone_number=inbound_message.business_phone_number` (de `InboundWhatsAppMessage`, sección 4) a `ensure_whatsapp`. Al final invoca `ProcessInboundGuestMessageUseCase` (o el punto de entrada equivalente) con `sender_type`/canal `WHATSAPP` y el `InboundMessageActor(resolved_phone=...)` de 5.1. [R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, D4]
- [x] 5.5 Tests en `backend/tests/messaging/`: cero coincidencias (conversación con `property_id=default_property_id`, sin huésped/reserva, visible al operador), una coincidencia con reserva activa única (usa la propiedad de la reserva, no la por defecto), dos+ huéspedes coincidentes (escalación, `property_id=default_property_id`), dos+ reservas activas del mismo huésped (escalación, `property_id=default_property_id`), segundo mensaje del mismo huésped/propiedad reutiliza la conversación, invariante "exactamente uno" de `InboundMessageActor` con las tres combinaciones inválidas. Test de aislamiento de tenant sobre `ensure_whatsapp`/la resolución completa. [R4.1-R4.5, R5.1, R5.2, D6]

## 6. Aprovisionamiento del número de WhatsApp por tenant <!-- panel: PASS 2026-09-03 -->

**Reescrita 2026-09-02** (design D3/D8, supersedidos tras el hallazgo del panel de sección 4:
Meta admite una sola App/WABA para toda la plataforma — ya construida en la sección 1 con
`WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_APP_SECRET` globales — y cada tenant aporta su propio número
de WhatsApp Business, `phone_number_id`, bajo esa misma App. No hay ningún secreto que mintar
por tenant; solo una asociación número↔tenant que dar de alta).

- [x] 6.1 `backend/app/messaging/infrastructure/models.py`: `WhatsAppPhoneNumberModel` (una fila por tenant: `id`, `tenant_id` único, `phone_number_id` único e indexado — clave de resolución de la sección 7 —, `display_phone_number` opcional solo para mostrar al operador, `default_property_id` (FK a `properties`, `NOT NULL` — addendum del 2026-09-02, design D8: `ensure_whatsapp` de la sección 5 lo necesita porque `Conversation.property_id` nunca admite `None`, design D19), timestamps). Sin columnas de secreto: no hay nada por tenant que cifrar aquí. [D3, D8]
- [x] 6.2 Migración Alembic (encadenada a la de la sección 5): tabla `whatsapp_phone_numbers`. [D3]
- [x] 6.3 `backend/app/messaging/application/whatsapp_provisioning.py` (nuevo): `AssociateWhatsAppPhoneNumberUseCase` (crea o reemplaza la fila del tenant; `phone_number_id` lo aporta el operador, nunca se genera aquí; recibe también `default_property_id` y **valida que esa propiedad pertenece al tenant** antes de aceptarla — mismo patrón de validación de propiedad que ya usa el resto del código para escrituras acotadas por propiedad; la restricción de unicidad de `phone_number_id` falla explícito si ese número ya está asociado a otro tenant, nunca lo sobrescribe en silencio) y `ReleaseWhatsAppPhoneNumberUseCase` (retira la asociación — el equivalente de "rotar" en este modelo; no necesita un `default_property_id` simétrico, liberar un número no toca las conversaciones ya creadas bajo él). Auditan la asociación/liberación (regla 9), nunca hay un valor que ocultar tras la auditoría. [R6.1, R6.2, R6.3, D8]
- [x] 6.4 Rutas nuevas (router de `messaging`, autenticado, permiso `MANAGE_TENANT_SETTINGS`): `POST /api/v1/messaging/whatsapp-phone-number` (acepta `phone_number_id` y `default_property_id`) y `POST /api/v1/messaging/whatsapp-phone-number/release`. `backend/app/messaging/api/dependencies.py`: wiring de los nuevos casos de uso. [R6.1, R6.2, R6.3]
- [x] 6.5 Tests: asociar un número nuevo a un tenant con su propiedad por defecto; asociar con una propiedad que no pertenece al tenant falla explícito; intentar asociar el mismo `phone_number_id` a un segundo tenant falla explícito sin tocar la asociación existente (R6.2); liberar una asociación; ambas rutas exigen `MANAGE_TENANT_SETTINGS`; la asociación y la liberación quedan en `AuditLog`. [R6.1, R6.2, R6.3]

## 7. Webhook de entrada anónimo, autenticación y despacho (hard) <!-- hard --> <!-- panel: PASS 2026-09-03 -->

**Reescrita 2026-09-02** (design D3/D3a, supersedidos): una sola ruta fija para toda la
plataforma, sin segmento por tenant. La firma se verifica contra el secreto único global
(`settings.WHATSAPP_APP_SECRET`, ya existente desde la sección 1) — no hay ningún
`token_hash`/fila por tenant que resolver antes de verificar. El tenant se resuelve **después**
de que la firma sea válida, a partir de `phone_number_id` (`InboundWhatsAppMessage.
business_phone_number`, sección 4) contra `WhatsAppPhoneNumberModel` (sección 6) — nunca antes,
y nunca desde ningún otro campo del cuerpo.

- [x] 7.1 `backend/app/messaging/api/dependencies.py`: wiring de `MetaInboundAdapter` (sección 4) seleccionado por el mismo `settings.WHATSAPP_PROVIDER` de la sección 1/2. [D9]
- [x] 7.2 `backend/app/messaging/application/webhooks.py` (nuevo o junto a `whatsapp_inbound.py`): `ReceiveWhatsAppWebhookUseCase` — verifica la firma real del proveedor con `WhatsAppInboundProviderAdapter.verify_signature`, usando `settings.WHATSAPP_APP_SECRET` como secreto (único, global — no hay fila por tenant que leer antes de esto). IF la firma es inválida (cabecera ausente, mal formada, o no coincide), THEN responde de forma indistinguible entre esos motivos, sin escribir nada (R3.3). Si la firma es válida: `parse()` el cuerpo (puede lanzar la excepción de la sección 4 para un payload sin mensaje real — p.ej. un `status` de Meta — responder `202` sin más, Meta reintrega si no); resuelve `tenant_id` **y `default_property_id`** buscando `InboundWhatsAppMessage.business_phone_number` en `WhatsAppPhoneNumberModel` (sección 6, misma fila da los dos) — si no hay ninguna fila para ese número, es un caso distinto y no adversarial (número válidamente firmado pero aún no aprovisionado): registrar de forma visible al operador (mismo criterio que R4.3) en vez de descartar en silencio o tratarlo como el mismo fallo que una firma inválida. Si resuelve: deduplica por `provider_message_id` (no crear una segunda fila si el proveedor reintenta la entrega), persiste la fila (con `tenant_id` y `default_property_id`, para que la sección 5 los tenga sin volver a consultar `WhatsAppPhoneNumberModel`) y encola `process_inbound_whatsapp_message.delay(event_id)` — sin ninguna llamada saliente síncrona. [R3.2, R3.3, R3.5, R4.1, D7]
- [x] 7.3 `backend/app/messaging/api/whatsapp_webhook_router.py` (nuevo), anónimo, **ruta única fija** (sin segmento por tenant): `POST /api/v1/webhooks/whatsapp`, ruta hermana de `webhooks_router.py` bajo el mismo prefijo `/webhooks/`, reutiliza `RedisWebhookThrottle` (límite de tasa) y el tope de tamaño de `MaxBodySizeMiddleware` ya global; responde `202`/`403`/`429`/`413`. Además, `GET /api/v1/webhooks/whatsapp` en el mismo router (misma ruta fija): handshake de verificación de Meta (D3a) — responde el valor de `hub.challenge` en texto plano solo si el query param `hub.verify_token` coincide con `settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN` (nuevo, `backend/app/core/config.py`, sin default, regla 8); si no, `403` con cuerpo vacío. [R3.1, R3.3, R3.4, D3a]
- [x] 7.4 `backend/app/scheduler/whatsapp_tasks.py` (nuevo, bajo `app/scheduler/` por la regla de `test_layering.py` que solo permite importar Celery ahí): `process_inbound_whatsapp_message(event_id)` invoca `PostWhatsAppInboundMessageUseCase` (sección 5) para ese evento. Importado desde `backend/app/worker.py` (igual que `app.scheduler.tasks`) para registrarse en `celery_app`, **sin entrada en `beat_schedule`** — se dispara con `.delay(...)`, nunca por cadencia. [D7]
- [x] 7.5 Tests en `backend/tests/messaging/`: firma inválida por los distintos motivos (ausente, mal formada, secreto incorrecto, cuerpo alterado) devuelve siempre la misma respuesta; firma válida + `phone_number_id` sin asociar registra visible al operador, no descarta y no se confunde con el caso de firma inválida; reintento de entrega del proveedor (mismo `provider_message_id`) no duplica el mensaje; límite de tasa y tope de tamaño de cuerpo activos en la ruta; el task se encola tras el commit y no antes; ida y vuelta completa (mensaje entrante → `ProcessInboundGuestMessageUseCase` → respuesta saliente por el adapter de la sección 1/2, usando `Conversation.business_phone_number` como "from", dentro de la ventana de 24h). Handshake `GET`: `hub.verify_token` correcto devuelve `hub.challenge` en texto plano; incorrecto o ausente → `403` sin cuerpo. [R3.1, R3.3, R3.4, R3.5, R4.1, R5.1, R5.2, R5.3, D3a]

## 8. Verification

- [x] 8.1 Suite completa de tests del backend pasa: `docker compose exec backend uv run pytest`. **Recertificado el 2026-09-04 tras el panel de revisión**: el hallazgo QA del panel reprodujo, en una corrida de suite completa, un fallo *distinto* del que esta entrada certificaba —
  `tests/messaging/test_whatsapp_provisioning.py::test_the_release_diff_moves_every_field_to_none`, un flake genuino (`_audit_rows()` ordenaba solo por `created_at`, y las filas de asociar/liberar de este test compartían el mismo `now=NOW`, así que un empate de timestamp dejaba el orden de lectura sin garantía bajo carga) — no el `test_demo_reset.py` que esta entrada nombraba. Corregido dándole a la liberación un `now` posterior (`RELEASED_AT = NOW + timedelta(minutes=5)`) en todas sus llamadas del fichero. Recorrida la suite completa tras el fix: **10121 passed, 41 skipped, 0 failed** (634.56s) — ni el flake de provisioning ni el `FileNotFoundError` de `test_demo_reset.py` (TOCTOU sobre el bind-mount, documentado como ambiental por las secciones 2/4/5/7) reaparecieron. El recuento original de esta entrada (10118 passed, 41 skipped, 1 failed, con `test_demo_reset.py` como el fallo) queda superseded por esta recertificación, no editado en sitio, para que quede constancia de qué certificaba el panel y qué no.
- [x] 8.2 Tipado estático: desde `backend`, `uv sync --frozen && uv run pyright .`. 888 → 879 errores tras dos correcciones reales (ver Implementation Notes): `ConsoleEmailAdapter`/`InAppNotificationAdapter` no declaraban `last_inbound_at`/`template_id`/`phone_number_id` (rotura de conformidad con `NotificationAdapter` introducida por la sección 1, señalada como pendiente en sus Implementation Notes) y `DelegatingOutboundAdapter.__init__`'s `delegate` estaba tipado como unión de clases concretas en vez del Protocol `NotificationAdapter` (rompía la conformidad estructural de `SpyDelegate` en `test_channels.py`). Confirmado por comparación línea-a-línea contra el diff: los 739 errores restantes en ficheros no tocados por este cambio y los ~139 en ficheros sí tocados son, sin excepción, recurrencias de patrones de ruido ya preexistentes en el baseline (mismatch estructural Fake/Protocol, `UUID | None` sin narrowing, kwarg `_env_file` no reconocido por el stub de pydantic-settings, `reportOptionalMemberAccess`/`reportOptionalSubscript` sobre helpers de test) — ninguna categoría nueva. `sdd/project.md` ya documenta que los findings de pyright se reportan aparte de los fallos de arranque; no hay CI que lo exija en verde absoluto.
- [x] 8.3 Regenerar `backend/openapi.json` (`make openapi`, +317 líneas sobre lo que secciones 6/7 habían dejado) y el artefacto derivado del frontend (worktree, workaround de `sdd/project.md`: `docker compose exec -T frontend mkdir -p /backend && docker compose cp backend/openapi.json frontend:/backend/openapi.json && docker compose exec -T frontend ln -sfn /app /frontend && docker compose exec -T frontend npm run api:generate`, +199 líneas en `frontend/lib/api/generated/openapi.d.ts`); `npm run api:check` confirma "generated types are up to date". Ambas mitades del contrato regeneradas por la norma de `sdd/steering/documentation.md`. Sin commitear todavía — igual que el resto de esta implementación, se commitea junto con todo lo demás cuando el change se cierre.
- [x] 8.4 Comprobación manual de extremo a extremo, sin credenciales reales de Meta disponibles en este entorno (se usó `WHATSAPP_PROVIDER=meta` con un `WHATSAPP_ACCESS_TOKEN` falso solo para ejercitar la ruta de entrada real; nunca se llegó a hacer una llamada saliente contra un Meta real). `make bootstrap && make seed_demo` sobre el `docker-compose.worktree.yml` de este worktree (sin publicar puertos: todo vía `docker compose exec backend python -c ...`, `httpx` interno) dieron un tenant, dos propiedades y tres huéspedes reales en Postgres:
  - Asociación vía API real: `POST /api/v1/messaging/whatsapp-phone-number` con JWT de owner → `201`, fila creada en `whatsapp_phone_numbers`.
  - Handshake `GET /api/v1/webhooks/whatsapp`: token correcto → `200` + `hub.challenge` en texto plano; token incorrecto o ausente → `403` sin cuerpo. Coincide con D3a — el handshake es un mecanismo de design, no un criterio R# propio (el proposal no llega a R7; sus cinco criterios de R3 son ruta fija, firma, rechazo indistinguible, tasa/tamaño y deduplicación).
  - `POST` con `X-Hub-Signature-256` calculada a mano sobre el cuerpo crudo: firma válida → `202`; firma inválida → `403` indistinguible. Coincide con R3.2/R3.4.
  - Mensaje de un teléfono sin huésped asociado: resuelve tenant por `phone_number_id`, crea una `Conversation` nueva anclada al `default_property_id` del tenant (el mecanismo nuevo de esta sección, antes bloqueado por la invariante de `property_id` no nulo), la escala (0 coincidencias) y genera una notificación `GUEST_ESCALATION` (`IN_APP`+`EMAIL`) visible al manager. `whatsapp_inbound_events.processed_at` queda escrito — la tarea de Celery corrió de verdad.
  - Mensaje de un huésped real con estancia activa hoy: reutiliza su `Conversation` existente (no crea una duplicada) — confirma el anclaje por huésped+propiedad de R4.2 contra datos reales, no solo fakes.
  - No se observó una llamada saliente real de `WhatsAppCloudAdapter` en esta sesión: las conversaciones de prueba terminaron `ESCALATED` (lógica de escalado preexistente de `guest-portal-messaging`, ajena a este cambio), que suprime la respuesta automática de la IA. La forma de esa llamada (`POST /{version}/{phone_number_id}/messages`, Bearer, cuerpo, mapeo de errores) ya está cubierta exhaustivamente por `tests/notifications/test_whatsapp_cloud_adapter.py` (sección 1, transporte simulado) y por el hilo de `phone_number_id` de la sección 2 — task 8.4 admite explícitamente "o por el mock si no hay credenciales", que es el caso aquí.
  - Entorno restaurado a `WHATSAPP_PROVIDER=mock` sin token/phone_number_id al terminar; los datos de demo (tenant/propiedades/huéspedes/conversaciones) quedan en el Postgres de este worktree como fixture reutilizable, no se revirtieron.

## Implementation Notes

- Task 2.6: `OutboundMessagePort.send` gained a fourth optional kwarg, `phone_number_id: str | None = None`, widened onto `PanelOutboundAdapter`/`PortalOutboundAdapter`/`InboundOnlyAdapter` (ignored) the same way `tenant_id`/`last_inbound_at`/`template_id` were. `DelegatingOutboundAdapter.send` cannot resolve it itself the way it resolves `last_inbound_at` — it only ever receives `conversation_id`, never the `Conversation` entity — so it just forwards whatever the caller passed, and only on the `WHATSAPP` branch (`EMAIL`'s `ConsoleEmailAdapter` still doesn't declare the kwarg). The actual value comes from the AI-reply call site in `app/messaging/application/use_cases.py` (`PostInboundGuestMessageUseCase`-equivalent's `_generate_and_send`-style method around line 542), which already has `conversation` in scope and now passes `phone_number_id=conversation.business_phone_number`. `NotificationAdapter.send` (`MockWhatsAppAdapter`/`WhatsAppCloudAdapter`) already accepted this kwarg from task 1.7, so no change was needed on that side.
- Port kwargs are exactly `last_inbound_at: datetime | None = None` and `template_id: str | None = None` — no third kwarg exists to say "send free text anyway with no timestamp".
- Resolved semantics (binding for section 2): `last_inbound_at is None` is OUTSIDE the window, same as any timestamp older than 24h. Only a `last_inbound_at` within `WHATSAPP_SESSION_WINDOW` (24h) counts as inside. Outside + no `template_id` → `NotificationResult.failure(NotificationErrorCode.OUTSIDE_SESSION_WINDOW)`, no network call.
- Section 2's `DelegatingOutboundAdapter.send` must resolve a real `last_inbound_at` from `Conversation.last_message_at` and pass it through — `app/notifications/application/use_cases.py::_deliver` was deliberately left untouched and never passes `last_inbound_at`, so every notifications-side WhatsApp send (proactive, staff-facing) is outside-window by construction, satisfying R2.3. Only the messaging-side call path (section 2) can ever land inside the window.
- Mock-mode class kept its original name: `MockWhatsAppAdapter` (not renamed), same file (`app/notifications/infrastructure/adapters.py`). It now also accepts `last_inbound_at`/`template_id` (ignores both — R1.5 preserves old behaviour exactly, no window simulation). `app/messaging/infrastructure/channels.py` already imports this class directly and constructs it unconditionally in `outbound_registry()` (pre-existing, section 2's to rewire) — untouched by this section, and it kept working against the widened signature with no edit needed.
- New real class: `WhatsAppCloudAdapter` (same file). Constructor: `WhatsAppCloudAdapter(*, access_token: str, phone_number_id: str, transport: httpx.AsyncBaseTransport | None = None)` — `transport` exists only for tests (`httpx.MockTransport`, same pattern as `Beds24Client`), production code never passes it.
- Graph API version constant: `WHATSAPP_GRAPH_API_VERSION = "v21.0"` in `adapters.py`. Base URL constant: `WHATSAPP_GRAPH_API_BASE_URL = "https://graph.facebook.com"`. Session window constant: `WHATSAPP_SESSION_WINDOW = timedelta(hours=24)`. Template language constant (hardcoded simplification, real per-template language selection is future work): `WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE_CODE = "es"`.
- Env var names (all in `.env.example`, no values): `WHATSAPP_PROVIDER` (`mock`/`meta`, defaults to `mock` — both an absent env var AND a blank one, e.g. `.env.example`'s literal `WHATSAPP_PROVIDER=`, resolve to that default via a `mode="before"` field validator; only an explicitly-set, non-empty, invalid value such as `twilio` is rejected at boot), `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` (both required only when `WHATSAPP_PROVIDER=meta`, enforced by field validators in `Settings` that fail fast at boot), `WHATSAPP_APP_SECRET` (declared only — section 7 is what makes it required for real; not enforced by this section).
- Settings attribute names (lowercase, standard pydantic-settings convention already used by every other field): `settings.whatsapp_provider`, `settings.whatsapp_access_token`, `settings.whatsapp_phone_number_id`, `settings.whatsapp_app_secret`.
- **No breaking change for local dev / CI**: `whatsapp_provider` defaults to `mock`, and both an absent `WHATSAPP_PROVIDER` and a blank one resolve to that default, so a bare `make up` (which copies `.env.example` verbatim, leaving `WHATSAPP_PROVIDER=` empty) boots exactly as it did before this change — no manual `.env`/CI edit is needed. A developer only needs to set `WHATSAPP_PROVIDER=meta` (plus the three Meta credentials) by hand when they actually want to test against the real Meta Cloud API; an explicitly-set invalid value such as `twilio` is still rejected at boot.
- `adapter_registry()` stays no-argument; it now reads `settings.whatsapp_provider` directly (`from app.core.config import settings`, already imported in `adapters.py`). Any value other than `"meta"` builds `MockWhatsAppAdapter()` — this is safe because `Settings`' own field validator already rejects anything outside `{"mock", "meta"}` at boot, so by the time `adapter_registry()` runs the value is one of the two.
- Known, accepted pyright gap (not fixed in this section, `Static typing is NOT required for this section's verification`): widening `NotificationAdapter.send`'s Protocol with two new keyword params makes `ConsoleEmailAdapter`/`InAppNotificationAdapter` structurally non-conforming per pyright (`reportReturnType` on `adapter_registry()`'s return), because their `send()` signatures were deliberately left untouched (task 1.2's "todo adapter existente sigue sin tocar"). Section 8.2 (`uv run pyright .` with zero new errors) will need to resolve this — options are giving every adapter the same two optional kwargs, or another design decision; not decided here.
- Two other places in the tree still carry the pre-`whatsapp-cloud-adapter` "rule 8 already reserves the WhatsApp variable names" claim and were left untouched (out of this section's file list; likely `/sdd:archive`'s job): `sdd/roadmap/whatsapp-cloud-adapter.md:8` (quotes it as historical motivation) and `sdd/specs/access-notifications.md:673` (living spec for the superseded `access-notifications` change).

### Section 2

- `ChannelErrorCode` order after 2.1: `INVALID_RECIPIENT`, `CHANNEL_INBOUND_ONLY`, `ADAPTER_UNAVAILABLE`, `OUTSIDE_SESSION_WINDOW` — appended, not inserted, because a guard test in `test_value_objects.py` pins the tuple by position.
- `OutboundMessagePort.send`'s three new kwargs, in the order they now appear after `language`: `tenant_id: uuid.UUID` (**no default**), `last_inbound_at: datetime | None = None`, `template_id: str | None = None`. All four implementers (`PanelOutboundAdapter`, `PortalOutboundAdapter`, `InboundOnlyAdapter`, `DelegatingOutboundAdapter`) carry the identical signature (Liskov); only `DelegatingOutboundAdapter` does anything with the three new params.
- **Correction to the task's own claim about `ConsoleEmailAdapter`**: task 2.4's text says the `EMAIL` delegate "ya ignora los dos kwargs sin problema" (harmlessly ignores `last_inbound_at`/`template_id`). That is false — `ConsoleEmailAdapter.send` (section 1 left it untouched, same file as `WhatsAppCloudAdapter`) does **not** declare those two params at all, so passing them raises `TypeError`, discovered by the first test run of this section. `DelegatingOutboundAdapter.send` therefore branches on `self._channel`: for anything other than `WHATSAPP` it calls the delegate with the original four kwargs only (no `last_inbound_at`/`template_id`, and no `last_guest_message_at` query); only the `WHATSAPP` branch resolves `last_inbound_at` and forwards both new kwargs. A future 5th channel that delegates to a `NotificationAdapter` needs to be added to that `if` explicitly if it also carries a session window — there is no third branch today.
- `MessageRepository.last_guest_message_at`'s SQLAlchemy implementation: `select(func.max(MessageModel.created_at))` through the same `_joined`/`_scoped` helpers every other method uses, filtered on `MessageModel.sender_type == MessageSenderType.GUEST` — one query, no `LIMIT`, mirrors `count_guest_messages`'s shape exactly.
- `DelegatingOutboundAdapter.__init__` is now `(delegate, channel: NotificationChannel, messages: MessageRepository)` — positional-or-keyword, no defaults; the internal attribute is `self._messages` (matches `self._delegate`/`self._channel`'s naming, and matters because `test_ports.py`'s consumer-guard test greps for `._messages.<method>(` across both `application/use_cases.py` and `infrastructure/channels.py`).
- `outbound_registry()` is now `outbound_registry(messages: MessageRepository)` — **no longer no-argument**, unlike `notifications.adapter_registry()` which stayed no-arg in section 1. Both current callers already build a `SqlAlchemyMessageRepository(session)` for their own `messages=` kwarg right next to the call, so the fix was passing that same instance through, not new plumbing: `backend/app/messaging/api/dependencies.py::get_process_inbound_message_use_case` and `backend/app/cli/seed_demo.py::_messaging_pipeline_kwargs`.
- `use_cases.py`'s one `adapter.send(...)` call site (inside the AI-reply use case) now passes `tenant_id=tenant_id` — the parameter was already in scope on `execute()`.
- `WHATSAPP`'s delegate selection in `outbound_registry()` mirrors section 1's `adapter_registry()` exactly: `settings.whatsapp_provider == "meta"` builds `WhatsAppCloudAdapter(access_token=settings.whatsapp_access_token or "", phone_number_id=settings.whatsapp_phone_number_id or "")`, else `MockWhatsAppAdapter()`.
- Existing tests that broke and were fixed as part of this section (all in `backend/tests/messaging/`, none of it speculative — every one was a real caller of the widened signatures):
  - `fakes.py`: `FakeOutboundAdapter.send` widened with `tenant_id`, `last_inbound_at=None`, `template_id=None` (recorded into `.sends[]` for any test that wants to assert on them); `FakeMessageRepository` gained `last_guest_message_at` (max over its in-memory `.rows`, same `sender_type is MessageSenderType.GUEST` filter as its siblings).
  - `test_pipeline_atomicity.py`: all six `outbound_registry()` call sites became `outbound_registry(SqlAlchemyMessageRepository(db_session))`.
  - `test_channels.py`: added a module-level `registry()` helper wrapping `outbound_registry(FakeMessageRepository())` and a `tenant_id` param on the `send()` test helper; every bare `outbound_registry()` call in the file goes through `registry()` now. New tests added for 2.5 (see below).
  - `test_ports.py`: `test_the_message_repository_declares_only_what_this_change_consumes` now expects 5 methods, not 4; `test_every_message_repository_method_has_a_consumer_in_this_change` now greps `application/use_cases.py` **and** `infrastructure/channels.py` combined — `last_guest_message_at`'s only consumer is `DelegatingOutboundAdapter`, not a use case.
  - `test_value_objects.py`: `test_channel_error_codes_are_the_three_of_the_design` now expects the fourth member.
- New tests for 2.5, by file:
  - `test_repositories.py`: four new tests under `# --- last_guest_message_at ---` (zero/one/several guest messages, and the D2-motivating case: an AI message at `+25h` and a manager message at `+26h` after a guest message at `t0` still resolve to `t0`).
  - `test_tenant_isolation.py`: `test_the_guests_last_message_time_never_crosses_a_tenant`, same `two_tenants()` fixture and shape as its four siblings.
  - `test_channels.py`: a `SpyDelegate` fake (records the kwargs it received, using an `_UNSET` sentinel default rather than `None` so "kwarg never passed" is distinguishable from "kwarg passed as `None`") proves `WHATSAPP` resolves `last_inbound_at` from `last_guest_message_at` (and passes `None` when the guest never wrote), and that `EMAIL` never receives `last_inbound_at`/`template_id` at all. A translation test drives a fake `OUTSIDE_SESSION_WINDOW` failure through `_translate`. Two end-to-end tests use the real `WhatsAppCloudAdapter` over `httpx.MockTransport` (no network): a guest message 1h old sends free text; a guest message 25h old with a manager reply 1 minute old still fails `OUTSIDE_SESSION_WINDOW` with no HTTP request made — the exact scenario that motivated task 2.3's addition to `MessageRepository`.
- Verification run (task 2.5, and re-run of 1.6's suite to confirm no regression): `docker compose exec backend uv run pytest tests/messaging/ tests/notifications/ -q` → 876 passed (860 pre-2.4 + 5 fixed guard/translation tests' assertions updated + 11 new). `docker compose exec backend uv run pytest tests/cli/test_seed_demo.py -q` → 94 passed (spot-check of `_messaging_pipeline_kwargs`'s `outbound_registry(messages)` rewiring, per the task's own instruction to check `seed_demo.py` coverage). One pre-existing flaky test unrelated to this section (`test_free_text_sink_contract.py::test_the_portal_never_puts_the_message_in_the_timeline`, a random-UUID/leak-marker substring collision) failed once and passed on immediate re-run — not caused by this section's edits. One unrelated failure in `tests/cli/test_demo_reset.py::test_env_example_declares_the_demo_password_by_name_and_without_a_value` traced to a stale Docker bind-mount inode for `/workspace/.env.example` (`stat` showed `Links: 0`, i.e. unlinked on the host side by a concurrent process) — not a code regression, not touched by this section, and outside `backend/`'s test scope this section owns.
- Verification run (task 1.6): `docker compose exec backend uv run pytest tests/notifications/ -q` → 221 passed. `docker compose exec backend uv run pytest tests/test_config.py -q` → 83 passed. `docker compose exec backend uv run pytest tests/messaging/test_channels.py -q` → 21 passed (spot-check that the shared `MockWhatsAppAdapter` still works for section 2's existing, not-yet-rewired code).

### Section 3

Independent of sections 1-2's files — nothing here imports `WhatsAppCloudAdapter`, `outbound_registry`, or anything else those sections touched. What section 5 (identity/conversation resolution) needs from here:

- **`GuestRepository.find_by_phone`** (`app/guests/domain/repositories.py`, implemented in `app/guests/infrastructure/repositories.py::SqlAlchemyGuestRepository`): `async def find_by_phone(self, tenant_id: uuid.UUID, phone: str) -> list[GuestSummary]`. Plural, unordered — does **not** pick a deterministic winner like `find_by_email` does, on purpose: R4.4's escalation needs the count. A blank `phone` returns `[]` without querying. The caller must pass an already-normalised phone (matching what `guests.phone` is stored as); this method only does an equality comparison, no normalisation of its own. New index `ix_guests_tenant_id_phone` (plain, non-unique, `(tenant_id, phone)`) backs the lookup.
- **`normalize_phone_e164`** (`app/guests/domain/value_objects.py`, next to `normalize_email`): `def normalize_phone_e164(value: str) -> str | None`. Section 5's webhook handler must call this on the WhatsApp sender's number *before* calling `find_by_phone` — this function does not query anything itself. Returns `None` (fail closed) for anything outside its two recognised shapes: already-E.164 (`+` + 8-15 digits) or a bare 9-digit Spanish national number (defaults to `+34`). **Does not strip a `00` international prefix and does not accept a bare number of any length other than 9** — deliberately narrow per design D5's risk note. Note for section 5: WhatsApp Cloud API's webhook payload carries the sender as digits only, no leading `+` (e.g. `"34612345678"`) — that is a full E.164 number *without* the `+`, which this function's bare-number branch will **not** recognise (it only accepts a 9-digit bare number, not an 11-digit one with country code baked in). Section 5 will need to prepend `+` to the raw `wa_id` before calling this normaliser (`normalize_phone_e164("+" + wa_id)`), not pass the raw digits through unchanged.
- **`ReservationRepository.find_active_for_guest`** (`app/reservations/domain/repositories.py`, implemented in `app/reservations/infrastructure/repositories.py::SqlAlchemyReservationRepository`): `async def find_active_for_guest(self, tenant_id: uuid.UUID, guest_id: uuid.UUID, *, on_date: date) -> Sequence[Reservation]`. No status filter (same reasoning as `list_for_properties`: which statuses count as "live" is the caller's policy, not this query's) — a `CANCELLED` reservation inside the window is still returned. Returns every match, not one — same escalation-signal reasoning as `find_by_phone`. `RESERVATION_MATCH_GRACE_DAYS = 2` lives in `app/reservations/domain/repositories.py`, imported by the infrastructure module rather than redefined.
- **Alembic**: new revision `b282614d54b4` (`backend/alembic/versions/b282614d54b4_guests_phone_index.py`), `down_revision = '2b28c6b3f82a'`. **The task brief's premise of three competing heads was stale by the time this section ran**: `docker compose exec backend uv run alembic heads` showed a single head, `2b28c6b3f82a`, before this migration was authored — an `a1b2c3d4e5f6` merge revision (unifying `c22b8ae01096` super-admin-identity and `r3v1ew5a03` revenue-reviews-timeline-events) already exists on `main` and `2b28c6b3f82a` (guest-portal-messaging) already chains onto it (see that file's own docstring, "Re-encadenada por segunda vez al entrar en `main`"). No `alembic merge` was needed here. Sections 5/6 should chain their own migrations' `down_revision` onto `b282614d54b4` (or onto whichever revision is head by the time they run — re-check with `alembic heads` rather than assuming this one stays it, the same way this section had to). `alembic upgrade head` was **not** run, per the task brief and `sdd/steering/testing.md` (the suite builds its schema via `Base.metadata.create_all`, not via these migrations) — the index is declared a second time in `GuestModel.__table_args__` for exactly that reason.
- Verification run (tasks 3.1-3.5): `docker compose exec backend uv run pytest tests/guests/ tests/reservations/ -x` → 576 passed, 0 failed (includes the new `find_by_phone` tests in `tests/guests/test_repositories.py`, the new `normalize_phone_e164` tests in `tests/guests/test_value_objects.py`, and the new `TestFindActiveForGuest` class in `tests/reservations/test_repositories.py`). `SELECT ... WHERE reservations.check_in_date - :interval <= :on_date AND reservations.check_out_date + :interval >= :on_date` was spot-checked by compiling the statement directly to confirm SQLAlchemy translates `Date - timedelta`/`Date + timedelta` to real SQL date arithmetic rather than raising at compile time.

### Section 4

Independent of sections 1-3's files — nothing here imports `WhatsAppCloudAdapter`, `outbound_registry`, `find_by_phone` or anything else those sections touched. What sections 5, 6 and 7 need from here:

- **`WhatsAppInboundProviderAdapter`** (`app/messaging/domain/ports.py`, appended after `IncidentReportingPort`): exactly the two methods D9 declares, **both synchronous** (neither does I/O — an HMAC over bytes in memory and a `json.loads`), both keyword-only. `verify_signature(*, raw_body: bytes, headers: Mapping[str, str], secret: str, url: str) -> bool` and `parse(*, raw_body: bytes, headers: Mapping[str, str]) -> InboundWhatsAppMessage`. `Mapping` comes from `collections.abc`. Not `@runtime_checkable`, same as the module's other three ports, so `isinstance` against it raises — assert conformance with `inspect.signature` instead (`test_whatsapp_inbound_provider.py` does).
- **`MetaInboundAdapter`** (`app/messaging/infrastructure/whatsapp_providers.py`, new): the only implementer. **Constructed with no arguments and holds no state** — `MetaInboundAdapter()`. It does **not** import `settings`: the app secret arrives per call as `verify_signature(secret=...)`, because the port declares it that way. **Section 7's wiring (task 7.1) is what reads `settings.whatsapp_app_secret`** and passes it in; that field is a plain `str | None` env var, **not** Fernet ciphertext, so **no `app.core.crypto.decrypt` call is needed today** — task 4.4's phrase "`settings.WHATSAPP_APP_SECRET` descifrado" describes a per-tenant encrypted credential that does not exist in this change's schema. Pass `settings.whatsapp_app_secret or ""`; a blank secret makes `verify_signature` return `False` (see below), which is the fail-closed behaviour a deployment with the variable unset must get.
- Module-level constants in `whatsapp_providers.py`: `SIGNATURE_HEADER = "X-Hub-Signature-256"`, `SIGNATURE_ALGORITHM = "sha256"`. Import them rather than restating the header name in section 7's router or tests.
- **`verify_signature` never raises and answers `False` on five distinct paths**: no signature header; a header that is not `<algorithm>=<hex>` or whose algorithm is not `sha256` (Meta's superseded `X-Hub-Signature` was SHA-1); a digest that is not exactly 64 hex characters; a **blank or whitespace-only `secret`** (an HMAC under an empty key is one anybody can compute, so an unset `WHATSAPP_APP_SECRET` must not authenticate the open internet); and a digest computed with another key. Non-ASCII header values do not raise — the comparison goes through `secrets_match`, which encodes both sides first. `url` and every header other than the signature are **ignored by contract**: Meta's signature covers `raw_body` alone, and folding the URL in would reject every genuine request. Hex is compared case-insensitively, and surrounding whitespace in the header value is stripped.
- **`headers` case handling — nothing is required of section 7's router.** The adapter looks the header up case-insensitively itself (exact hit first, then a lowercased scan), so passing Starlette's `request.headers` (already case-insensitive, the shape `integrations/api/webhooks_router.py` uses), a canonical-cased `dict`, or an all-lowercase `dict` built from an ASGI scope all work identically. Do **not** normalise before calling.
- **`raw_body` must be the exact bytes that arrived** — `await request.body()`, never `json.dumps(await request.json())`. Re-serialising changes key order and separators and therefore invalidates a perfectly valid signature; a test pins this so the port cannot be "simplified" to take a `dict`. Section 7 must read the body once and hand the same `bytes` to both methods, and must call `verify_signature` **before** `parse` (the split between the two methods exists so authentication is answerable without interpreting the body, exactly as `ReceiveWebhookUseCase.authenticate` is split from `record`).
- **`InboundWhatsAppMessage`** (`app/messaging/domain/value_objects.py`, appended at the end): frozen, exactly five fields in this order — `sender_phone: str`, `provider_message_id: str`, `text: str`, `received_at: datetime`, `business_phone_number: str`. `__post_init__` refuses a blank (or whitespace-only) value in any of the four string fields and a **naive** `received_at`, raising `MessagingValidationError`; no refusal quotes the value it refused. `sender_phone` is Meta's `from` verbatim — **bare digits, no `+` and no `whatsapp:` prefix** — so section 5 must call `normalize_phone_e164("+" + message.sender_phone)`, exactly as section 3's notes already warned. `business_phone_number` is **`value.metadata.phone_number_id`** (the Graph API identifier), never `display_phone_number`; it is informational only and R4.1 forbids resolving a tenant from it or from any other field of this object.
- **`NoInboundMessageError`** lives in **`app/messaging/domain/exceptions.py`** (not in the infrastructure module — `application/` may not import `infrastructure/`), a direct subclass of `MessagingDomainError` so the module's hierarchy stays flat. It is the **only** exception `parse` raises: every malformed or message-less body arrives as this, never as a `KeyError`/`IndexError`/`TypeError`.
- **Section 7 MUST catch `NoInboundMessageError` and answer `202`.** Meta posts delivery and read receipts to the very same webhook URL (`value.statuses` instead of `value.messages`), so this is high-volume ordinary traffic, not a fault — and Meta redelivers on **any** non-2xx, so letting it escape would make every receipt retry forever and burn the route's rate-limit budget on our own outbound receipts. The 422 row added to `_MAPPING` in `app/messaging/api/errors.py` is the second net, not the plan.
- `parse` also raises `NoInboundMessageError` for a **non-text message** — an image, sticker, location or reaction has no `text.body`, and this change's pipeline classifies and answers text (`AIAdapter.classify_message` takes `content: str`). Section 7 answers those `202` as well; supporting media is future work, not a bug here.
- **Known limitation section 7 inherits**: Meta may batch several messages into one webhook and `parse` returns **the first**, because D9 fixes the port's return type at a single `InboundWhatsAppMessage`. The extras are dropped and a `logger.warning("messaging.whatsapp_inbound_batch_truncated", extra={"message_count": n})` counts them (a count only — rule 11: the dropped messages are the guest's words on an unauthenticated route). Handling a batch means widening the port, which this change did not decide.
- `received_at` is built as `datetime.fromtimestamp(int(timestamp), tz=UTC)` from Meta's `timestamp` (**Unix seconds, as a decimal string**). A `timestamp` that is not a decimal-string integer — including an actual JSON integer — is refused rather than coerced; all five extracted fields must arrive as non-empty strings.
- **`app/messaging/domain/whatsapp_webhook.py`** (new) re-exports `generate_webhook_token`, `hash_webhook_token` and `secrets_match` from `app.integrations.domain.webhook_auth` — the identical objects, not wrappers, pinned by an identity assertion. `generate_header_secret` is deliberately **not** re-exported. **Superseded 2026-09-02 (design D3, task 4.6): `generate_webhook_token`/`hash_webhook_token` turned out to have no consumer once the topology moved to one shared Meta App with a single fixed webhook route (no per-tenant route token at all) — section 6 provisions a `phone_number_id`-to-tenant association, not a token/secret pair. Task 4.6 drops both re-exports; only `secrets_match` (used by the shared-secret signature check, D3a) stays.** This note is kept for history — do not re-add the two re-exports on their account.
- Files touched beyond the five tasks' own list, both **forced by an existing guard** rather than chosen: `app/messaging/api/errors.py` (a row for the new error — `tests/messaging/test_errors.py` walks `domain/exceptions.py` and fails any error without one) and `tests/messaging/test_errors.py` itself (its explicit `test_the_walk_finds_the_errors_that_exist` name set, plus a status row). No route, schema or migration in this section, so `openapi.json` is unchanged.
- New tests: `backend/tests/messaging/test_whatsapp_inbound_provider.py` (123 tests — port shape, the accepting and all refusing signature paths, the constant-time guard, the full field mapping, and every message-less/malformed body as a parametrised table) and an `InboundWhatsAppMessage` section appended to `backend/tests/messaging/test_value_objects.py`. The constant-time guard is **AST-shaped, not a substring search**: it asserts `verify_signature`'s one computed `return` is a call to `secrets_match` and that no bare `expected`/`digest`/`presented` name is ever an operand of `==`/`!=` (so `len(digest) != 64`, a comparison of a public length, stays legal). Six mutations were run against the finished code to prove the guards fire — `==` for `secrets_match`, dropping the blank-secret check, `display_phone_number` for `phone_number_id`, dropping `tz=UTC`, dropping the case-insensitive header scan, and dropping the algorithm check; all six were killed (the last only after a test was added for it, since a real `sha1=` digest is 40 characters and dies on the length check first).
- Verification run (tasks 4.1-4.5): `docker compose exec backend uv run pytest tests/messaging/ tests/test_layering.py -x -q` → 2116 passed, 0 failed (`test_layering.py` included on purpose: this section adds a new `domain/` module that imports another domain's `domain/`, which is the direction the dependency rule allows and which that suite is what proves). `pytest tests/messaging/ -q` → 798 passed. Whole backend suite (`pytest -q`, 11m36s) → **9913 passed, 41 skipped, 1 failed**, and the one failure is the same pre-existing, unrelated one section 2's notes already recorded: `tests/cli/test_demo_reset.py::test_env_example_declares_the_demo_password_by_name_and_without_a_value` raising `FileNotFoundError: /workspace/.env.example` from a stale Docker bind-mount inode (the file is present on the host; nothing in this section touches `.env.example`).
- `pyright` over this section's six app modules and three test files → 0 errors (the six pre-existing `reportArgumentType` errors at `tests/messaging/test_value_objects.py:238` are in the `MessageMetadata` block, untouched by this section, and are not the section-1 `adapter_registry()` gap either).

### Section 5

Tasks 5.1, 5.2 and 5.3 are done and verified. **Tasks 5.4 and 5.5 are BLOCKED on a design
decision** (see "BLOCKER" below) and were deliberately not implemented: three of the four
identity-resolution branches the task text prescribes cannot be built as written, and guessing
which way to resolve that is a product decision, not a style one.

What sections 6 and 7 can rely on from here:

- **`InboundMessageActor` now names one of three identities** (`app/messaging/domain/
  value_objects.py`, D6): `user_id: uuid.UUID | None`, `token_hash: str | None`,
  `resolved_phone: str | None`, plus the unchanged `ip: str | None`. Field order is
  `user_id, token_hash, resolved_phone, ip`; every caller in the tree passes keywords, so the
  insertion is safe. `__post_init__` **counts** the three identities and refuses `!= 1` — the
  old `(a is None) == (b is None)` shape has no correct two-term equivalent for three fields.
  `ip` is outside the invariant. A **blank or whitespace-only `resolved_phone` is refused**
  (it is not `None`, so the count would read it as an identity while naming nobody); no
  digest-shape check applies to it, per D6. `InboundMessageActor.__dataclass_fields__` is
  pinned at four by `tests/messaging/test_value_objects.py`.
- **`resolved_phone` has no `audit_logs` column**, so D6's "traceable in `audit_logs.actor_*`
  the same way `token_hash` is today" is **not yet true**. `AuditLogFactory.build` takes
  `actor_user_id`/`actor_guest_token_hash`/`actor_ip` and permits both ids being `NULL`
  (it refuses only *both set*), so an incident opened from a WhatsApp conversation writes an
  audit row naming no actor. Closing it means a new nullable column plus its CHECK — a schema
  change this change never scoped. Recorded in the type's docstring rather than papered over
  by hashing the phone into the digest column. `app/maintenance/application/use_cases.py`'s
  comment about "exactly one of the two is set" was corrected to "at most one" (a forced edit:
  the widening made the old claim false).
- **`Conversation.business_phone_number: str | None = None`** (`app/messaging/domain/
  entities.py`), appended last so positional construction is unaffected. `__post_init__`
  refuses a value on any channel but `WHATSAPP`, and refuses a blank one; neither refusal
  quotes the number (rule 11). "Set once and never rewritten" is **structural**: no method of
  the entity touches the field, and `save` writes only `_MUTABLE_CONVERSATION_COLUMNS`, which
  does not include it (both pinned by tests). Column: `business_phone_number VARCHAR(32) NULL`
  on `conversations`, mapped in `ConversationModel`, read back in `_to_conversation`, written
  by `SqlAlchemyConversationRepository.add` as well as by `ensure_whatsapp`.
- **`ConversationRepository.ensure_whatsapp`'s final signature** — keyword-only after
  `tenant_id`, exactly as task 5.2 spells it:
  `async def ensure_whatsapp(self, tenant_id: uuid.UUID, *, guest_id: uuid.UUID | None,
  property_id: uuid.UUID | None, reservation_id: uuid.UUID | None, language: str,
  business_phone_number: str, now: datetime) -> Conversation`. `business_phone_number` is
  **required** (`str`, not `str | None`): every caller is an inbound webhook, which always
  names the number it arrived on. Never commits. `language` and `business_phone_number` apply
  only when the row is created; the conflict branch returns the existing row untouched.
- **`ensure_whatsapp`'s read-back goes through `RETURNING id`, not a key lookup** — the one
  deliberate deviation from `ensure_portal`'s shape. `guest_id`/`property_id` are nullable, a
  `NULL` never conflicts, so an unresolved sender legitimately has *several* rows matching
  `guest_id IS NULL AND property_id IS NULL`: a lookup by the key would raise
  `MultipleResultsFound` exactly where the requirement is weakest. `RETURNING` yields the id
  on the winning path and nothing on the conflicting one, which is also how the method knows
  which path it took without reading `rowcount`. A mutation forcing the key lookup on both
  paths was run and killed by
  `test_a_sender_with_no_guest_resolved_gets_a_new_row_per_message`.
- **New index** `uq_conversations_whatsapp_guest_property`: partial unique on
  `(tenant_id, guest_id, property_id) WHERE channel = 'WHATSAPP'`, declared **twice** on
  purpose — in the migration and in `ConversationModel.__table_args__` — because the suite
  builds its schema with `create_all` and never runs migrations (same precedent as
  `uq_conversations_portal_reservation` and `ix_guests_tenant_id_phone`).
- **Alembic**: new revision `f1a9c73e5b28`
  (`backend/alembic/versions/f1a9c73e5b28_whatsapp_conversation_thread.py`),
  `down_revision = 'b282614d54b4'` (section 3's). `alembic heads` showed a single head both
  before and after. No `autocommit_block` was needed: `WHATSAPP` is an original label of
  `conversation_channel`, unlike `PORTAL` in `2b28c6b3f82a`. `alembic upgrade head` was **not**
  run, per section 3's precedent and `sdd/steering/testing.md`. **Section 6 must re-check
  `alembic heads` and chain onto whatever is head then** rather than assuming this revision.
- `tests/messaging/conftest.py` gained `seed_guest(db_session, tenant, *, full_name, phone,
  email)` — `conversations.guest_id` is a real foreign key, so no `ensure_whatsapp` test can be
  written without a guest row. Section 6/7's tests can reuse it.
- The concurrency test of `ensure_whatsapp` **warms both sessions' connections before racing**
  and waits up to 30 s for Postgres to report the lock. Without that it passed alone and
  failed inside `pytest tests/messaging/` (with `NullPool`, opening a fresh asyncpg connection
  can outlast the observation window on a loaded host — a flake, not a contract failure).

- Verification run (tasks 5.1-5.3): `docker compose exec backend uv run pytest tests/messaging/
  tests/guests/ tests/reservations/ tests/maintenance/ -q` → **2205 passed, 0 failed** (35m37s;
  `tests/maintenance/` included because `ReportIncidentFromConversationUseCase` is the one
  consumer of `InboundMessageActor`'s fields). Targeted runs along the way:
  `tests/messaging/test_repositories.py tests/messaging/test_ports.py` → 66 passed;
  `tests/messaging/test_entities.py tests/messaging/test_tenant_isolation.py
  tests/messaging/test_value_objects.py` → 205 passed. Four mutations were run against the
  finished code and all four were killed: forcing the key lookup on both `ensure_whatsapp`
  paths (killed by the unresolved-sender test), dropping `business_phone_number` from
  `_to_conversation` (3 red), dropping the entity's non-`WHATSAPP` guard (4 red) and dropping
  the actor's blank-`resolved_phone` guard (3 red). One first attempt at the last mutation
  truncated the module and produced a collection error instead of red tests — recorded because
  a collection error is not a killed mutation, and it was redone cleanly.
- The one existing test that had to change beyond the guards named above:
  `tests/messaging/test_repositories.py`'s concurrency test for `ensure_whatsapp` is new, and
  `test_the_actor_carries_exactly_three_fields` became
  `test_the_actor_carries_exactly_four_fields`. No production code outside this section's file
  list was touched except the one corrected comment in
  `app/maintenance/application/use_cases.py`.

**BLOCKER (tasks 5.4, 5.5): a `Conversation` with `property_id=None` is not constructible, so
R4.3's and R4.4's branches have nowhere to land.** Design D5 says "`ensure_whatsapp` passes
`property_id=None` for this case… though the entity itself allows `None`". **The entity does
not.** Measured on 2026-09-03:

1. `Conversation.__post_init__` (`app/messaging/domain/entities.py`) raises
   `MessagingValidationError` for `property_id is None` — `guest-portal-messaging` design D19,
   with `tests/messaging/test_entities.py::test_a_conversation_without_a_property_is_refused`
   pinning it. So `ensure_whatsapp`'s own read-back (`_to_conversation`) raises before it can
   return such a row.
2. `_to_conversation` is also what the **inbox** goes through
   (`SqlAlchemyConversationRepository.list`, one call per row), so a single property-less
   `WHATSAPP` row would make the manager's whole conversation list raise — the opposite of
   R4.3's "visible to an operator", and worse than dropping the message.
3. `TimelineEventFactory.create` refuses a non-`UUID` `property_id`
   ("property_id must be a UUID"), and `ProcessInboundGuestMessageUseCase` writes a
   `GUEST_MESSAGE_RECEIVED` event unconditionally — so even if 1 and 2 were relaxed, R5.1's
   "invoke the same use case the portal uses" would fail on the property-less thread.

This is not one edge case: of the four resolution branches task 5.4 lists, only **one guest +
exactly one active reservation** yields a property. Zero guest matches (R4.3), one guest with
zero active reservations (R4.3), two or more guests (R4.4) and two or more active reservations
(R4.4) all arrive with no single property — and "an unknown number writes for the first time"
is the *normal* case for WhatsApp, not a rare one.

The resolution is a product decision, so nothing was guessed. The three candidates, with what
each costs:

- **(A) Relax the invariant for `WHATSAPP`.** Allow `property_id=None` when
  `channel is WHATSAPP`, and make the pipeline's timeline events conditional on a property.
  Keeps task 5.4 exactly as written, but reopens `guest-portal-messaging` D19 and turns four of
  its "mandatory timeline event" SHALLs (its R4.1, R4.4, R4.5, R5.2) into "except on WhatsApp".
  Widest blast radius, and it touches a shipped change's spec.
- **(B) Always resolve a property.** Give section 6's `WhatsAppPhoneNumberModel` (which today
  holds `tenant_id`, `phone_number_id`, `display_phone_number` and nothing else) a
  `property_id`, so an unresolved sender's thread anchors to the tenant's WhatsApp-facing
  property. Smallest code change, R5.1/R5.2 stay intact, and the thread is genuinely visible —
  but it is a section 6 schema/design change and it makes a product claim ("messages from
  unknown numbers land on property X") the user has to want.
- **(C) Don't open a conversation for the unresolved branches.** R4.3's own wording is
  `"registrar el mensaje de forma que quede visible a un operador (**p.ej.** una conversación
  sin huésped/reserva asociada)"` — the conversation is an *example*, and note it says without
  *guest/reservation*, never without *property*. This change already uses a non-conversation
  mechanism for the sibling case in R3.3 (a validly signed `phone_number_id` associated with no
  tenant "se registra para el operador (mismo criterio que R4.3)"), which can only be the
  `webhook_events` row. Costs a new operator-visible surface (and probably a new task), but
  breaks no existing invariant.

Whichever is chosen, 5.4/5.5 need re-specifying before implementation, and one more consequence
follows from the block: `ensure_whatsapp` currently has **no consumer** in the tree (its
consumer is 5.4), which is the shape R1.1 of `guest-portal-messaging` calls speculative. It was
still landed because 5.2 asks for it by name and the index behind it is 5.3's migration; the
`ConversationRepository` port-shape guard in `tests/messaging/test_ports.py` was updated to
expect it.

**BLOCKER CLOSED.** Candidate **(B)** was chosen and implemented: section 6 below gives
`WhatsAppPhoneNumberModel` its `default_property_id`, and 5.4's checklist entry above already
describes the resolved shape in full — all five identity-resolution branches (zero guests, one
guest with zero/one/two-or-more active stays, two-or-more guests), every one of them landing on
`default_property_id` rather than the `None` this BLOCKER showed was unconstructible. 5.5's
tests (`tests/messaging/test_whatsapp_inbound.py`) cover all five, including the two escalation
branches. The intro paragraph and the candidates above are left as written — the record of what
was genuinely undecided when this section was first drafted — and are superseded by this note,
not by silently editing them.

### Section 6

**Candidate (B) of section 5's BLOCKER is the one this section implements** — not a fresh
decision made here, but the premise the task brief for 6.1 already assumed ("`default_property_id`
… `ensure_whatsapp` de la sección 5 lo necesita"). `WhatsAppPhoneNumberModel` now carries
`default_property_id: uuid.UUID` (`NOT NULL`), so section 5's 5.4/5.5 have what they need to
resolve `property_id` for a sender that matches no guest or no single active reservation: read
the tenant's association (`WhatsAppPhoneNumberRepository.find_for_tenant` or
`find_by_phone_number_id`, both below) and fall back to its `default_property_id`. Nothing in
this section closes the BLOCKER itself — 5.4/5.5 do that, and their own closing note above
records it — but the schema/design gap it was blocked on no longer exists.

**Names section 7 needs, exactly:**

- Model: `WhatsAppPhoneNumberModel` (`app/messaging/infrastructure/models.py`), table
  `whatsapp_phone_numbers`. Columns: `id`, `tenant_id` (`TenantScopedMixin`, indexed, plus
  `UniqueConstraint("tenant_id", name="uq_whatsapp_phone_numbers_tenant_id")` — one row per
  tenant), `phone_number_id` (`String(32)`, `index=True, unique=True` — the column
  `ix_whatsapp_phone_numbers_phone_number_id`, globally unique, exactly what section 7 resolves
  the tenant from), `display_phone_number` (`String(32)`, nullable, operator-facing only —
  R3.1/R4.1 forbid resolving anything from it), `default_property_id` (`Uuid`, `NOT NULL`, FK
  `properties.id` `ondelete="RESTRICT"`), `created_at`/`updated_at`.
- Domain entity: `WhatsAppPhoneNumberAssociation` (`app/messaging/domain/entities.py`), frozen
  dataclass, fields in order `id, tenant_id, phone_number_id, display_phone_number,
  default_property_id`.
- Repository port: `WhatsAppPhoneNumberRepository` (`app/messaging/domain/repositories.py`),
  implemented by `SqlAlchemyWhatsAppPhoneNumberRepository`
  (`app/messaging/infrastructure/repositories.py`). Four methods: `upsert(tenant_id,
  association)`, `find_for_tenant(tenant_id) -> WhatsAppPhoneNumberAssociation | None`,
  `delete_for_tenant(tenant_id) -> bool`, and **`find_by_phone_number_id(phone_number_id) ->
  WhatsAppPhoneNumberAssociation | None`** — this is the read section 7 needs and did not exist
  before this section; see below.

**On the read method the contract asked me to flag**: tasks 6.1-6.3 as originally scoped are
write-side only (`AssociateWhatsAppPhoneNumberUseCase`/`ReleaseWhatsAppPhoneNumberUseCase`), and
without a way to look up a tenant by `phone_number_id`, section 7's inbound webhook literally
cannot resolve who a message is for. I judged this in-scope for 6.1's infrastructure work and
added it now, rather than leaving it as a section 7 TODO — the alternative was landing a
repository that R1.1's "no method without a consumer in this change" would immediately flag as
incomplete once section 7 tried to write against it. `find_by_phone_number_id` mirrors
`WebhookEndpointRepository.find_by_token_hash` exactly (`app/integrations/domain/repositories.py`
/ `app/integrations/infrastructure/repositories.py`): it is the **only** method of this
repository that runs without a tenant, it calls `require_unmarked_session(self._session,
read="find_by_phone_number_id")`, and it is declared in `tests/test_unscoped_reads.py`'s
`DECLARED_UNSCOPED_READS` census (`("messaging/infrastructure/repositories.py",
"find_by_phone_number_id")`) — section 7's receiving route **must** get its session unmarked
for this call, the same way `webhooks_router.py` does for the Beds24/Channex receiver.

**Association is create-or-replace, one call, no separate "rotate" verb** (R6.3): there is no
secret in this table (D3/D8's whole point — Meta's App-level credentials are the global
`WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_APP_SECRET` from section 1, untouched here), so the same
operation that creates a tenant's first association also replaces an existing one.
`ReleaseWhatsAppPhoneNumberUseCase` is the rotation-equivalent: it just removes the row.

**The `phone_number_id` uniqueness is a real `INSERT ... ON CONFLICT (tenant_id) DO UPDATE`
against the DB, not a prior read** (design D8, `steering/backend-architecture.md`).
`SqlAlchemyWhatsAppPhoneNumberRepository.upsert` resolves the *tenant_id* conflict atomically via
`ON CONFLICT`, and lets a `phone_number_id`-uniqueness violation (the constraint `ON CONFLICT`
does not name) surface as a plain `IntegrityError`, translated by matching
`WHATSAPP_PHONE_NUMBER_ID_CONSTRAINT = "ix_whatsapp_phone_numbers_phone_number_id"` against
`str(error.orig)` into `WhatsAppPhoneNumberAlreadyAssociatedError` (409, `ErrorCode.CONFLICT`,
mapped in `app/messaging/api/errors.py`'s `_MAPPING`). The existing association is never
overwritten in silence — killed by
`test_associating_the_same_number_to_a_second_tenant_is_refused_without_touching_the_first`.

**Property validation reuses `MessagingValidationError`**, the same pattern
`CreateConversationUseCase` already uses for a client-supplied `property_id`
(`app/messaging/application/use_cases.py`): `PropertyRepository.get(tenant_id,
default_property_id)` returns `None` for "does not exist" and "belongs to another tenant" alike,
and that one refusal (422) is all `AssociateWhatsAppPhoneNumberUseCase` raises — no separate
`PropertyNotFoundError` import from `properties.domain.exceptions`, staying consistent with the
messaging module's existing convention rather than introducing a second error type for the same
outcome.

**New domain errors** (`app/messaging/domain/exceptions.py`, both flat subclasses of
`MessagingDomainError`, both rows in `app/messaging/api/errors.py`'s `_MAPPING`):
`WhatsAppPhoneNumberAlreadyAssociatedError` (409, R6.2) and `WhatsAppPhoneNumberNotFoundError`
(404 — `ReleaseWhatsAppPhoneNumberUseCase` raises it when the tenant has nothing to release).

**Audit** (`app/audit/domain/actions.py`): new entity type `ENTITY_WHATSAPP_PHONE_NUMBER =
"WHATSAPP_PHONE_NUMBER"`, new actions `WHATSAPP_PHONE_NUMBER_ASSOCIATED` and
`WHATSAPP_PHONE_NUMBER_RELEASED`. `AUDITABLE_FIELDS["WHATSAPP_PHONE_NUMBER"]`
(`app/audit/domain/value_objects.py`) allowlists all three columns
(`phone_number_id`/`display_phone_number`/`default_property_id`) as plain `.diff()`s — nothing is
`.redacted()`, because there is no secret to hide (unlike `webhook_endpoints`' equivalent row,
which redacts everything). `_WhatsAppPhoneNumberAuditWriter`
(`app/messaging/application/whatsapp_provisioning.py`) mirrors
`_WebhookEndpointAuditWriter`'s shape exactly.

**Routes** (`app/messaging/api/router.py`): a **second** `APIRouter` in the same file,
`whatsapp_provisioning_router`, prefix `/messaging` (not `/conversations` — this is tenant
configuration, not a conversation endpoint, the same split `integrations` makes between
`/pms/import-csv` and `/webhook-endpoints`), gated on `Permission.MANAGE_TENANT_SETTINGS` (not
`MANAGE_CONVERSATIONS`). `POST /api/v1/messaging/whatsapp-phone-number` → 201,
`WhatsAppPhoneNumberResponse`; `POST /api/v1/messaging/whatsapp-phone-number/release` → 204.
Included in `app/main.py` as `messaging_whatsapp_provisioning_router` right after
`conversations_router`. Schemas: `AssociateWhatsAppPhoneNumberRequest`,
`WhatsAppPhoneNumberResponse` (`app/messaging/api/schemas.py`). Dependency wiring:
`get_associate_whatsapp_phone_number_use_case`, `get_release_whatsapp_phone_number_use_case`
(`app/messaging/api/dependencies.py`).

**Guard files touched beyond the task's own list, all forced by an existing guard rather than
chosen**: `tests/messaging/test_errors.py` (the two new domain errors need rows, per its own
exhaustiveness walk), `tests/test_route_authorization.py` (its pinned set of protected paths and
its per-path-segment set in `test_openapi_contract.py`'s
`test_the_route_guard_actually_sees_the_api` both needed the two new paths / the new `"messaging"`
segment), `tests/test_unscoped_reads.py` (the new unscoped read's census entry, plus its
`unsuffixed` names set and one piece of prose — "the five declared names" → "the six" — that
would otherwise have gone stale exactly the way that file's own docstring warns about), and
`openapi.json` (regenerated via `python -m app.cli.openapi`, then `pytest
tests/test_openapi_contract.py` reconfirmed byte-stable).

**Test-writing gotcha worth recording for section 7's own API tests**: `tests/messaging/
conftest.py`'s `api` fixture overrides `get_db_session` with a bare `async def _session_override():
yield db_session` — **no `finally` clearing the tenant marker**, unlike the root `conftest.py`'s
`request_session_override`. So once one authenticated request marks the shared `db_session` to a
tenant, every later ORM read on that session — including a direct repository call the test makes
afterward — is silently ANDed with `tenant_id = <that tenant>` by the global filter, and a
cross-tenant assertion written the "obvious" way (query the other tenant's row on the same
`db_session` after the request) will read `None` for the wrong reason. `test_whatsapp_provisioning_
api.py::test_a_second_tenant_claiming_the_same_number_is_a_conflict` hit this and works around it
by opening a **fresh, unmarked** `AsyncSession(test_engine)` for the post-request verification
queries rather than reusing `db_session`. A second, unrelated trap in the same test: a DB-level
`IntegrityError` aborts the current Postgres transaction, and `AsyncSession.rollback()` (needed to
keep a shared test session usable afterward) unconditionally **expires every ORM object** in the
session — so any `.id` access on an object loaded earlier in the same test must be captured into a
plain local variable *before* the rollback, or it raises `MissingGreenlet` trying to lazy-reload
synchronously.

**Known, pre-existing pyright gaps, not introduced by this section and not fixed here** (same
"deferred to section 8.2" status section 1's notes already recorded for a different gap):
`authenticated.context.tenant_id` is typed `UUID | None` and every route in
`app/messaging/api/router.py` — the eight pre-existing conversation routes and this section's two
new ones alike — passes it straight to a use case's `tenant_id: UUID` parameter, which pyright
flags as `reportArgumentType`. And `Result.rowcount` (used by `delete_for_tenant`, mirroring
`update_details` in `app/properties/infrastructure/repositories.py`) is unknown to the SQLAlchemy
stubs pyright resolves against — three identical pre-existing errors already exist in that
`properties` file. Neither is new; both were measured present before this section's diff and are
the same shape everywhere else in the tree.

**Verification runs**:
`docker compose exec backend uv run pytest tests/messaging/test_whatsapp_provisioning.py
tests/messaging/test_whatsapp_provisioning_api.py -q` → **28 passed** (14 application-layer, 14
API-layer). `docker compose exec backend uv run pytest tests/messaging/
tests/test_route_authorization.py tests/test_unscoped_reads.py tests/test_layering.py tests/audit/
tests/properties/ -q` → **3527 passed, 41 skipped** (0 failed; the 41 skips are pre-existing and
unrelated). `docker compose exec backend uv run pytest tests/test_openapi_contract.py -q` → **14
passed**, after regenerating `openapi.json`. `docker compose exec backend uv run alembic heads` →
single head, `c25fc5f449c1` (`whatsapp_phone_numbers`, `down_revision = 'f1a9c73e5b28'`) both
before and after — section 7 must re-check `alembic heads` the same way section 6 had to rather
than assuming this stays head.

### Section 7

Tasks 7.1-7.5 are done and verified. This closes the change's implementation; what follows is
what section 8 needs to reference, plus the three judgment calls this section had to make.

**Exact names section 8 can reference:**

- **Wiring** (`app/messaging/api/dependencies.py`, appended after the section 6 builders):
  `WHATSAPP_META_PROVIDER = "meta"`, `get_whatsapp_inbound_provider() -> MetaInboundAdapter`,
  `whatsapp_signing_secret() -> str`, `get_whatsapp_inbound_dispatcher() ->
  Callable[[uuid.UUID], None]`, `get_receive_whatsapp_webhook_use_case(...) ->
  ReceiveWhatsAppWebhookUseCase`, plus the `DispatchDep`/`ProviderDep`/`SigningSecretDep`
  aliases.
- **Use case** (`app/messaging/application/webhooks.py`, new):
  `ReceiveWhatsAppWebhookUseCase` with `authenticate(*, raw_body, headers, url) -> None`
  (**synchronous**, no I/O, touches no repository) and `async record(*, raw_body, headers,
  now) -> WhatsAppDeliveryReceipt`. `WhatsAppDeliveryOutcome` is a plain `Enum` with four
  members — `QUEUED`, `DUPLICATE`, `NO_MESSAGE`, `UNPROVISIONED_NUMBER` — declared in the
  application module and **not** in `domain/enums.py`, because it names the shape of one
  return value and no entity or column holds it.
- **Domain**: `InboundWhatsAppEvent` (`domain/entities.py`, frozen; `id`, `tenant_id`,
  `default_property_id`, `message: InboundWhatsAppMessage`, `processed_at`, plus the
  `is_resolved` property) and `WhatsAppWebhookAuthenticationError`
  (`domain/exceptions.py`, flat subclass of `MessagingDomainError`, row `(403,
  ErrorCode.FORBIDDEN)` in `app/messaging/api/errors.py`).
- **Repository**: port `WhatsAppInboundEventRepository`
  (`domain/repositories.py`) with `add(event) -> bool`,
  `locate_without_tenant_scoping(event_id) -> InboundWhatsAppEvent | None` and
  `mark_processed(tenant_id, event_id, *, now) -> bool`; implementation
  `SqlAlchemyWhatsAppInboundEventRepository` plus the module-level `_to_inbound_event`
  (`infrastructure/repositories.py`).
- **Model / migration**: `WhatsAppInboundEventModel`, table `whatsapp_inbound_events`
  (`infrastructure/models.py`), Alembic revision **`d38ba71c04e9`**
  (`alembic/versions/d38ba71c04e9_whatsapp_inbound_events.py`), `down_revision =
  'c25fc5f449c1'`. `alembic heads` showed a single head before (`c25fc5f449c1`) and after
  (`d38ba71c04e9`); `alembic upgrade head` was **not** run, per `sdd/steering/testing.md` and
  the precedent of every migration in this change.
- **Router** (`app/messaging/api/whatsapp_webhook_router.py`, new, `prefix="/webhooks"`):
  `WHATSAPP_WEBHOOK_PATH = "/whatsapp"`, `WHATSAPP_DELIVERY_BUDGET_KEY`,
  `verify_whatsapp_webhook` (`GET`) and `receive_whatsapp_webhook` (`POST`). Registered in
  `app/main.py` as `whatsapp_webhook_router`, right after
  `messaging_whatsapp_provisioning_router`.
- **Task** (`app/scheduler/whatsapp_tasks.py`, new): `WHATSAPP_INBOUND_TASK =
  "process_inbound_whatsapp_message"`, the Celery entrypoint
  `process_inbound_whatsapp_message(event_id: str) -> dict`, and the three helpers it is
  tested through (`_locate`, `_run`, `_process_inbound_whatsapp_message`). Imported for its
  side effect at the bottom of `app/worker.py`; declared in
  `ON_DEMAND_TASKS` (`app/scheduler/schedule.py`), **no** `beat_schedule` entry.
- **Config** (`app/core/config.py`): new field `whatsapp_webhook_verify_token: str | None =
  None` and **two** new field validators, `_require_app_secret_for_meta` and
  `_require_verify_token_for_meta`. `.env.example` gains
  `WHATSAPP_WEBHOOK_VERIFY_TOKEN=` (name only).
- **New tests**: `tests/messaging/test_whatsapp_webhook_wiring.py` (9),
  `test_whatsapp_webhook_receipt.py` (28), `test_whatsapp_webhook_api.py` (23),
  `test_whatsapp_inbound_task.py` (11).

**Judgment call 1 — the throttle's delivery key** (the one the brief flagged as not a
blocker). `probe_allowed(client_ip)` is unchanged from the PMS precedent and is checked FIRST,
before the body is even read; `record_failed_attempt(client_ip)` fires only on a signature
failure. `delivery_allowed` is keyed on the module constant
`WHATSAPP_DELIVERY_BUDGET_KEY = "whatsapp:meta:shared-subscription"` — **the subscription's
budget, not a tenant's**. Why that and not `phone_number_id`: the only per-tenant identity in
the request lives *inside* the body, so keying on it would mean parsing before charging, i.e.
after the work the budget exists to bound. Why a shared key is defensible here even though
`reservations-webhooks` D6 rejects one: D6's objection is that an **outsider** could spend a
tenant's (or everyone's) allowance, and nobody without `WHATSAPP_APP_SECRET` reaches this
counter — a forgery spends the per-IP probe budget instead. What it costs, stated in the
constant's own docstring rather than hidden: `WEBHOOK_RATE_LIMIT_PER_MINUTE` (120) now bounds
inbound guest messages **platform-wide**, so at a scale where two messages a second is
plausible it must be raised or the check moved behind the parse and re-keyed per
`phone_number_id`. At the MVP's 25-50 units it is ample. Pinned by value in
`test_the_delivery_budget_is_keyed_on_the_one_subscription`, so it is a decision and not a
drift.

**Judgment call 2 — the persisted "inbound event" row, which the design never enumerated.**
`design.md`'s "Data & interfaces" lists exactly one new table (`whatsapp_phone_numbers`) and
its Alembic row lists three items, none of them a queue — yet D7 and task 7.2 both say
`.delay(event_id)` "after the row commits" and "persiste la fila … deduplica por
`provider_message_id`". So the table is required by the task text and missing from the design's
inventory; it was built rather than guessed around, and the gap is recorded here.

Shape, and why each column is there: `id`; `tenant_id` **nullable**; `default_property_id`
**nullable**; `phone_number_id` (indexed, operator-facing lookup); `provider_message_id`
(`unique=True` index — R3.5 as a schema guarantee, resolved by `INSERT ... ON CONFLICT DO
NOTHING ... RETURNING id`, never a prior read); `sender_phone`; `message_text`; `received_at`
(Meta's instant, distinct from `TimestampMixin.created_at`); `processed_at`.

- **Typed columns rather than a JSONB `payload`** (the `webhook_events` shape): it keeps the
  cleartext-sink surface to exactly **one** column, and lets `_to_inbound_event` rebuild
  `InboundWhatsAppMessage` through its own `__post_init__`, so a row that lost its text or grew
  a naive `received_at` is refused before it reaches the pipeline.
- **`tenant_id` nullable is the second such column in the schema, after `webhook_events`**, and
  it is what records R3.3's amendment: a delivery that fails the signature writes nothing,
  while a validly signed one for an unprovisioned `phone_number_id` is recorded (R4.3's
  criterion) and never dispatched. Both anchors are set or neither — enforced by
  `InboundWhatsAppEvent.__post_init__`, not a CHECK, like the rest of this module's
  invariants. Consequence inherited verbatim from `webhook_events`: the table IS inside the
  global tenant filter (`tenant_scoped_classes()` selects by column presence), so the `NULL`
  rows are invisible to a marked session — which is why `locate_without_tenant_scoping` calls
  `require_unmarked_session` and is declared in `tests/test_unscoped_reads.py`'s census as its
  **eighth** entry.
- **`processed_at` goes beyond the literal task text and was added deliberately.** R3.5 is
  written about the *provider* retrying and the unique index answers that; Celery's delivery is
  at-least-once, so a redelivered **task** produces the same forbidden outcome (a second
  message in the guest's thread) by another route. The claim is a conditional `UPDATE ... WHERE
  processed_at IS NULL` taken **first and inside the same transaction as the work**, so a
  failure rolls it back and the event stays retryable. No `task_lock`: the unit of work is one
  row, and a global Redis lock would serialise unrelated guests.

**Judgment call 3 — `settings.whatsapp_provider` selects a *secret*, not a class** (task 7.1).
`MetaInboundAdapter` is the only implementer and it is stateless, so
`get_whatsapp_inbound_provider()` returns it unconditionally; the provider gate lives in
`whatsapp_signing_secret()`, which answers `""` under any provider but `meta`. Section 4's
adapter returns `False` for a blank or whitespace-only secret by contract and with its own
test, so `mock` mode refuses every delivery uniformly and writes nothing — R3.3's posture
applied to a deployment that never configured WhatsApp. The rejected alternative was a
`NullInboundAdapter` class: it would have added a class whose behaviour is byte-identical to
what the blank secret already produces.

**The whole route answers `202`, whatever the delivery turned out to be**, and that is a
requirement rather than laziness: Meta redelivers on any non-2xx, so a `422` for a
`value.statuses` receipt would put every receipt of our own outbound replies into an infinite
loop, and a `404` for an unprovisioned number would do the same to a guest's message until an
operator finished setting the number up. The four outcomes are told apart in the log and in the
row — the surfaces an operator has — never in the response, which has no body at all.

**Rule 11: one new cleartext sink, and its census row was added.**
`whatsapp_inbound_events.message_text` is the guest's own prose arriving from the open
internet, a **second persisted copy** of what `messages.content` will hold moments later, one
hop earlier, in the queue that crosses the Celery boundary. Its row is in the census table of
`sdd/steering/security.md` (inserted after `messages.metadata`), under **excepción 4** — the
same exception `messages.content` with `sender_type = GUEST` carries — with two differences
spelled out there: the audience is an anonymous caller **whose HMAC we do verify** (not a token
bearer), and the row can exist with **no `tenant_id`**, making it the only sink in the census
that can be ownerless. It does not propagate (outside `AUDITABLE_FIELDS`, outside timeline
`metadata`), and the three log lines in `application/webhooks.py` name `phone_number_id` and
`event_id` and never the text or the sender's number. `make check-rule11-ownership` is green.
`test_the_guests_words_reach_only_the_two_columns_the_census_declares`
(`test_whatsapp_inbound_task.py`) is the sweep that makes the row a fact: it drives off the ORM
registry, so a column added later joins by existing.

**Found while adding that row and NOT fixed here** (out of this section's scope, and it is a
pre-existing drift rather than something this change caused): the census's prose counts are
stale. Measured on 2026-09-03 against the table itself, it held **25 columns in 33 rows** while
the prose said "veintiuna columnas … veintinueve filas" — wrong by four in both figures before
this section touched anything. This section's row makes it 26 in 34. The numerals were left
alone rather than incremented onto a wrong base; correcting them is a prose recount someone
should do against the table, which is exactly what that section's own docstring says about
counts a human maintains.

**Guard files touched beyond the tasks' own list, all forced rather than chosen:**

- `tests/messaging/test_errors.py` — the new domain error needs a name and a status row, per
  its own exhaustiveness walk.
- `tests/test_route_authorization.py` — `("POST", "/api/v1/webhooks/whatsapp")` and
  `("GET", …)` in `ANONYMOUS_ENDPOINTS`, each with its reason.
- `tests/test_unscoped_reads.py` — the eighth census entry.
- `tests/test_openapi_contract.py` — **`BODILESS_SUCCESS_PATHS` became
  `BODILESS_SUCCESS_ENDPOINTS`, keyed on `(METHOD, path)`**, with a `_is_bodiless(path, route)`
  helper. This one is worth reading twice: it was **forced**, not tidied. This change puts a
  bodiless `POST` and a body-bearing plain-text `GET` on the *same* path, so a path-keyed
  exemption would have excused the `GET` too — and the `GET`'s body is the one thing in the
  whole application that Meta itself compares byte for byte. The same vacuity argument
  `ANONYMOUS_ENDPOINTS` already makes for its own keying, one axis over.
- `tests/scheduler/test_schedule.py` — `ON_DEMAND_TASKS` joins the exhaustiveness check as a
  **third table, not an exemption class**: every registered task must still sit in exactly one
  of the three, so a genuinely forgotten beat entry stays red. Two new tests pin that no
  on-demand task has a beat entry and that the set's one name is the one the task registers.
- `tests/test_config.py` — section 1's
  `test_whatsapp_app_secret_is_declared_but_not_required_by_this_section` asserted the exact
  opposite of what section 7 makes true, so it was **replaced** (by
  `test_the_two_webhook_secrets_are_required_under_meta` and
  `test_the_two_webhook_secrets_have_no_default_and_are_unset_under_mock`) rather than left to
  contradict the validator. `_META_CREDENTIALS` is the new shared fixture dict, and it is four
  entries now instead of two.
- `openapi.json` — regenerated with `python -m app.cli.openapi`; `pytest
  tests/test_openapi_contract.py` reconfirms byte-stability. The frontend half of the contract
  (`frontend/lib/api/generated/openapi.d.ts`) is task **8.3**'s and was not regenerated here.
- `app/notifications/infrastructure/adapters.py` and `app/messaging/domain/whatsapp_webhook.py`
  were **not** touched.

**Two failures this section found in `tests/cli/test_demo_reset.py` were left by section 6, not
by this one**, and both are fixed here because a new table walks into the same guards:
`test_the_delete_phase_covers_every_scoped_table_minus_the_four_it_preserves` needed
`whatsapp_phone_numbers` in its pinned literal (section 6 never added it, and its verification
runs did not include `tests/cli/`), and
`test_the_delete_phase_leaves_every_row_of_the_working_tenant_untouched` needed a neighbour row
in each new scoped table — without one, D18.3's "photograph every row" is `[] == []` for that
table and an unscoped delete on it would ship green. `populate_tenant` now seeds both, and both
table names are in the literal.

**Test-writing gotchas worth recording:**

- The **`api` fixture of `tests/messaging/conftest.py` is unusable for this route.** It marks
  the shared `db_session` with a tenant on the first authenticated request and never clears it,
  and both `find_by_phone_number_id` and `locate_without_tenant_scoping` refuse a marked
  session. `test_whatsapp_webhook_api.py` builds its own client with a bare `get_db_session`
  override instead (no authenticated request ever runs on it), which is the production shape
  for an anonymous route.
- **The worker's session factory must be swapped** (`monkeypatch.setattr(runner,
  "_session_factory", async_sessionmaker(test_engine, …))`), exactly as
  `tests/scheduler/test_webhook_task.py` does it: the real one points at the development
  database.
- **`outbound_registry()` takes the `WhatsAppCloudAdapter` branch under `whatsapp_provider=
  "meta"`**, which the round-trip test needs for `whatsapp_signing_secret()` to hand over a
  real key. So the recording spy is installed over **both** `channels.MockWhatsAppAdapter` and
  `channels.WhatsAppCloudAdapter`; patching only the mock one silently stopped being consulted
  and the first version of that test failed on the real adapter's constructor.
- The Celery entrypoint is **synchronous** and calls `asyncio.run` itself, so its two tests are
  plain `def` — pytest-asyncio's running loop refuses the nesting.
- `db_session.expire_all()` detaches every object the fixtures handed over, so ids must be
  captured into plain locals **before** it — the same `MissingGreenlet` trap section 6's notes
  record one rollback over.

**Mutations run against the finished code — six, all killed:** dispatching before the commit
(1 red, `test_the_task_is_dispatched_only_after_the_row_is_committed`); `add()` always
reporting an insert (3 red across the receipt and task files); the handshake dropping its
`hub.challenge` requirement (1 red); the delivery budget keyed on `client_ip` instead of the
subscription constant (1 red); the worker skipping its claim (1 red); and resolving the tenant
from `sender_phone` instead of `business_phone_number` — R4.1's actual prohibition — (6 red).

**Verification runs:**
`pytest tests/messaging/test_whatsapp_webhook_wiring.py` → **9 passed**.
`pytest tests/messaging/test_whatsapp_webhook_receipt.py` → **28 passed**.
`pytest tests/messaging/test_whatsapp_webhook_api.py` → **23 passed**.
`pytest tests/messaging/test_whatsapp_inbound_task.py` → **11 passed**.
`pytest tests/messaging/ tests/test_route_authorization.py tests/test_openapi_contract.py
tests/integrations/` → **1962 passed, 0 failed**.
`pytest tests/messaging/ tests/scheduler/` → **1030 passed**.
`pytest tests/scheduler/ tests/test_layering.py` → **1390 passed**.
`pytest tests/cli/test_demo_reset.py` → **106 passed, 1 failed** (the pre-existing one below).
`make check-rule11-ownership` → green.
Whole backend suite (`pytest -q`, 12m05s) → **10115 passed, 41 skipped, 2 failed**, and both
failures are pre-existing and unrelated:
`tests/cli/test_demo_reset.py::test_env_example_declares_the_demo_password_by_name_and_without_a_value`
(`FileNotFoundError: /workspace/.env.example` from a stale Docker bind-mount inode — the file is
present on the host; sections 2 and 4 recorded the same one) and
`tests/messaging/test_repositories.py::test_two_concurrent_callers_end_with_one_thread_and_both_see_it`
(section 5's own documented flake: it passes alone — reconfirmed here, 1 passed in 0.88 s — and
loses its lock-observation window under whole-suite contention).

**Static typing was not run** and remains section **8.2**'s: this section adds no new gap it
knows of, and the two pre-existing ones sections 1 and 6 recorded (`adapter_registry()`'s
`reportReturnType`, `authenticated.context.tenant_id` as `UUID | None`, `Result.rowcount`) are
unchanged — `mark_processed` uses `rowcount` the same way `delete_for_tenant` already does.

**Known limitations this section leaves standing**, none of them new decisions:

- **A batched webhook still processes only its first message** (section 4's `parse` returns one
  `InboundWhatsAppMessage` by D9's port shape, counting the rest in a log). The receiver
  inherits that verbatim: one delivery, one row, one task. Widening it means widening the port.
- **A non-text message answers `202` and is dropped**, for the same reason — the pipeline
  classifies text.
- **The delivery rate limit is platform-wide**, as spelled out under judgment call 1.
- **`WHATSAPP_WEBHOOK_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` now fail the boot under
  `whatsapp_provider=meta`.** Any deployed environment already running with
  `WHATSAPP_PROVIDER=meta` and either variable unset will refuse to start after this change —
  which is the point (rule 8), but it is a deployment note for 8.4 rather than a surprise to
  discover there.

- **Task 8.2's two real fixes**: `ConsoleEmailAdapter.send`/`InAppNotificationAdapter.send`
  (`app/notifications/infrastructure/adapters.py`) gained the same
  `last_inbound_at: datetime | None = None, template_id: str | None = None,
  phone_number_id: str | None = None` kwargs `MockWhatsAppAdapter` already had, ignored, to
  restore structural conformance with the `NotificationAdapter` Protocol that section 1 widened
  (flagged there as deferred to 8.2, not decided). `DelegatingOutboundAdapter.__init__`'s
  `delegate` param (`app/messaging/infrastructure/channels.py`) is now typed as the
  `NotificationAdapter` Protocol instead of `ConsoleEmailAdapter | MockWhatsAppAdapter |
  WhatsAppCloudAdapter` — the union of concrete classes was rejecting `test_channels.py`'s
  `SpyDelegate` test double despite it satisfying the Protocol structurally. Both confirmed via
  a container `uv run pyright .` (888 → 879 errors) and a targeted pytest re-run
  (`tests/notifications/`, `tests/messaging/test_channels.py`, 252 passed).
- **The remaining ~139 pyright errors in files this change touches are pre-existing baseline
  noise**, not new: verified line-by-line against `git diff` that every one of them either falls
  outside this change's added/modified lines, or repeats a message pattern (`Fake*Repository`
  vs. its Protocol, `UUID | None` passed where `UUID` is expected, `No parameter named
  "_env_file"`, `reportOptionalMemberAccess`/`reportOptionalSubscript` on test helpers) that
  independently occurs in the 740 pyright errors present in files this change never touches at
  all. `sdd/project.md` already documents pyright findings as reported separately from startup
  failures — there is no CI gate requiring an absolute zero.
