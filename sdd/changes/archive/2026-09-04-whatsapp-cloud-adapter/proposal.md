# Proposal: whatsapp-cloud-adapter

## Why

WhatsApp es hoy un mock en las dos direcciones. `MockWhatsAppAdapter`
(`backend/app/notifications/infrastructure/adapters.py`) hace un `logger.info` y devuelve
éxito para toda notificación por el canal `WHATSAPP`, y `messaging/infrastructure/channels.py`
delega en ese mismo mock la respuesta de la IA a un huésped por WhatsApp — así que ambas
capabilities (notificaciones y mensajería conversacional) comparten el mismo cuello de botella.
Y no existe ningún camino de entrada: nada recibe un mensaje de WhatsApp desde fuera, así que
un huésped no puede escribir por este canal aunque el sistema pueda (en teoría) contestarle.

Este change sustituye el mock por un adapter real, salida y entrada, contra el puerto que ya
existe (`NotificationAdapter` / `OutboundMessagePort`) — sin tocar esos puertos ni el
`ConversationChannel.WHATSAPP` que ya está declarado.

**No es** `beds24-messaging-adapter`: aquella entrada del roadmap es mensajería de OTA
(Airbnb/Booking) a través de `PMSMessagingPort`, aplazada sin fecha a que los canales OTA
reales se conecten. WhatsApp Business no depende de ninguna de esas dos condiciones.

**Corrección de hecho que este change arrastra al pasar**: el docstring de
`MockWhatsAppAdapter` afirma que "rule 8 of `sdd/steering/security.md` already reserves the
variable names" para las credenciales de WhatsApp. Es inexacto — `.env.example` reserva los
seis nombres `SMTP_*` y ninguno de WhatsApp — y se corrige como parte de R1.

Fuente: nota de roadmap `sdd/roadmap/whatsapp-cloud-adapter.md` (measured 2026-08-28).

## What changes

`MockWhatsAppAdapter` se sustituye por un adapter real que habla con la **Cloud API de WhatsApp
Business de Meta** (decisión tomada con el usuario el 2026-09-02, sustituyendo la asunción
original de "Twilio Sandbox primero": la ventana de servicio al cliente de Meta —gratuita
durante 24h desde el último mensaje del huésped, de pago con plantilla fuera de ella— es
exactamente el mecanismo que R2 exige, y el modo de desarrollo de Meta da un número de prueba y
hasta 5 destinatarios sin verificación de negocio, la misma propiedad que hacía atractivo a
Twilio Sandbox sin su limitación de número compartido entre cuentas). El puerto sigue siendo
`NotificationAdapter`/`OutboundMessagePort`, provider-neutral; `WHATSAPP_PROVIDER` sigue
existiendo como interruptor (`mock`/`meta` hoy, `twilio` queda como valor futuro no
implementado) para que un proveedor adicional detrás del mismo puerto siga siendo solo una
clase nueva, sin tocar `domain/` ni `application/`. El adapter respeta la ventana de 24 horas
del proveedor: dentro de ella puede mandar texto libre, fuera de ella solo plantillas aprobadas
— y una notificación proactiva que no tenga plantilla aplicable falla de forma explícita en vez
de reportar éxito sin entregar nada.

Se añade el primer endpoint de entrada de WhatsApp: un webhook por tenant, con la misma
disciplina de la regla 12 de `steering/security.md` que ya gobierna `reservations-webhooks`
(ruta con token opaco, autenticación de dos factores, límites de tasa, desacople de la
re-lectura/proceso), que resuelve tenant y huésped a partir del número de teléfono del remitente
y entrega el mensaje al pipeline de conversación existente
(`ProcessInboundGuestMessageUseCase` → IA → escalación → bandeja), con `ConversationChannel.
WHATSAPP` como canal.

## Requirements

### R1 — Adapter de salida real, sustituyendo el mock

**As a** operador del sistema, **I want** que las notificaciones y respuestas por WhatsApp se
entreguen de verdad, **so that** un huésped o una limpiadora reciban lo que el sistema cree
haberles enviado.

Acceptance criteria:

1. WHEN el registro de adapters (`adapter_registry`) resuelve el canal `WHATSAPP`, THE SYSTEM
   SHALL usar un adapter real que implemente `NotificationAdapter` con el mismo contrato de
   `MockWhatsAppAdapter` (mismo tipo de retorno, mismo fallo-por-valor, mismo rechazo de
   destinatario en blanco).
2. WHEN `DelegatingOutboundAdapter` de `messaging/infrastructure/channels.py` envía por
   `ConversationChannel.WHATSAPP`, THE SYSTEM SHALL delegar en ese mismo adapter real — sin
   duplicar la integración con el proveedor.
3. THE SYSTEM SHALL configurar el proveedor mediante variables de entorno reservadas en
   `.env.example` (sin valor por defecto, siguiendo la disciplina de la regla 8 de
   `steering/security.md`), y SHALL corregir el docstring de la clase sustituida, que hoy
   afirma que esas variables ya estaban reservadas cuando no lo estaban.
4. IF el proveedor configurado no responde o devuelve un error no clasificable, THEN THE
   SYSTEM SHALL devolver `NotificationResult.failure` con un código existente o uno nuevo del
   mismo enum cerrado — nunca una excepción no capturada ni un `str` de proveedor libre en el
   resultado.
5. WHERE no hay credenciales configuradas (entorno de desarrollo sin proveedor real), THE
   SYSTEM SHALL seguir aceptando `WHATSAPP_PROVIDER=mock` como opción explícita, preservando el
   comportamiento actual para quien no necesite probar contra un proveedor real.

### R2 — Ventana de 24 horas

**As a** propietaria del negocio, **I want** que el sistema nunca reporte como entregado un
mensaje que WhatsApp en realidad bloqueó, **so that** una notificación proactiva fuera de
ventana no se dé por enviada cuando no llegó a nadie.

Acceptance criteria:

1. WHEN se intenta un envío de texto libre por WhatsApp para una conversación cuyo último
   mensaje del huésped fue hace más de 24 horas, THE SYSTEM SHALL rechazar el envío de texto
   libre y SHALL exigir una plantilla aprobada por Meta en su lugar.
2. WHEN se intenta un envío dentro de las 24 horas siguientes al último mensaje del huésped
   (p.ej. la respuesta de la IA a un mensaje que acaba de llegar), THE SYSTEM SHALL permitir
   texto libre sin exigir plantilla.
3. IF una notificación proactiva (p.ej. `CLEANING_TASK_ASSIGNED`) se dirige a un destinatario
   de staff por WhatsApp y no hay plantilla aplicable configurada, THEN THE SYSTEM SHALL
   fallar con un código de error distinguible (nunca reportar éxito) en vez de descartar el
   mensaje en silencio.
4. THE SYSTEM SHALL determinar la ventana a partir de un dato objetivo del lado nuestro (p.ej.
   `Conversation.last_message_at` para conversaciones existentes) o del propio proveedor
   cuando lo exponga, y no SHALL asumir que un envío está dentro de ventana solo porque el
   llamante no dijo lo contrario.

### R3 — Webhook de entrada: autenticación y transporte (regla 12)

**As a** operador de seguridad, **I want** que el endpoint que recibe mensajes de WhatsApp
tenga la misma disciplina que el resto de webhooks entrantes del sistema, **so that** un
segundo endpoint anónimo sobre datos de huésped no reabra los riesgos que `reservations-
webhooks` ya cerró.

Acceptance criteria:

1. **Enmendada 2026-09-02** (design gate, tras descubrir en la sección 4 del panel de revisión
   que Meta solo admite UNA URL de webhook por App de Meta — no una por tenant, a diferencia de
   Twilio): THE SYSTEM SHALL exponer la recepción bajo una única ruta fija, no bajo un token por
   tenant en la URL. La autenticidad de la petición (R3.2) es lo que impide una entrega
   falsificada, no la ocultación de la ruta — la redacción original de este criterio ("token
   opaco por tenant... mismo patrón que `POST /api/v1/webhooks/{provider}/{webhook_token}`")
   asumía la topología de Twilio y no encaja con la de Meta. THE SYSTEM no SHALL resolver el
   tenant a partir de la ruta para este proveedor (ver R4.1, enmendado igual).
2. THE SYSTEM SHALL verificar la autenticidad de la petición con el mecanismo que el proveedor
   elegido sí soporta (firma HMAC de Meta/Twilio sobre el cuerpo, o el secreto de cabecera de
   la regla 12(a) si el proveedor no firma), comparado en tiempo constante. (Regla 12 del
   `steering/security.md` se acota expresamente a "webhooks entrantes sin firma"; el de Meta
   lleva firma real, así que ni 12(a) ni la exigencia literal de 12(b) — ruta por tenant — le
   aplican al pie de la letra, per D3a del design.)
3. IF la firma es inválida (secreto incorrecto, cuerpo alterado, cabecera ausente o mal
   formada), THEN THE SYSTEM SHALL responder de forma indistinguible entre esos motivos, sin
   escribir nada y sin exponer cuál fue la causa exacta del rechazo. Un `phone_number_id`
   válidamente firmado pero no asociado a ningún tenant (R4.1) es un caso distinto y no
   adversarial — un número de WhatsApp aún no aprovisionado — y no está sujeto a esta
   indistinguibilidad: se registra para el operador (mismo criterio que R4.3) en vez de
   tratarse como un intento de ataque.
4. THE SYSTEM SHALL aplicar límite de tasa y tope de tamaño de cuerpo a esta ruta, y SHALL
   desacoplar el procesamiento del mensaje de la respuesta HTTP inmediata (encolado, como
   `process_webhook_events`), nunca una llamada saliente síncrona por webhook recibido.
5. THE SYSTEM SHALL deduplicar por el id de mensaje que asigna el proveedor, de forma que un
   reintento de entrega del proveedor no genere un segundo mensaje en la conversación.

### R4 — Resolución de identidad: teléfono → tenant y huésped

**As a** manager, **I want** que un mensaje entrante de WhatsApp se asocie a la vivienda y al
huésped correctos, **so that** no aparezca como un mensaje huérfano ni, peor, en la
conversación de otro huésped.

Acceptance criteria:

1. **Enmendada 2026-09-02** (mismo descubrimiento que R3.1): WHEN llega un mensaje entrante
   autenticado, THE SYSTEM SHALL resolver el `tenant_id` a partir del `phone_number_id` que el
   proveedor adjunta como metadato de entrega (`value.metadata.phone_number_id` en el payload de
   Meta — un identificador técnico de qué número de negocio recibió el mensaje, no un dato que
   el huésped controla), consultando una tabla de aprovisionamiento propia (R6) que asocia cada
   `phone_number_id` a un único tenant — y no SHALL resolver el tenant desde la ruta (no existe
   ninguna, R3.1) ni desde ningún campo del cuerpo que el remitente del mensaje controle
   (número de origen, texto).
2. THE SYSTEM SHALL buscar, dentro de ese tenant, un huésped cuyo número de teléfono
   coincida (normalizado a un formato canónico, p.ej. E.164) con el remitente del mensaje.
3. IF ningún huésped de ese tenant tiene ese teléfono registrado, THEN THE SYSTEM SHALL
   registrar el mensaje de forma que quede visible a un operador (p.ej. una conversación sin
   huésped/reserva asociada) en vez de descartarlo en silencio, y no SHALL inventar una
   asociación.
4. IF el teléfono coincide con más de un huésped o con más de una estancia activa del mismo
   huésped en ese tenant, THEN THE SYSTEM SHALL escalar a revisión humana en vez de adivinar
   cuál es la conversación correcta.
5. WHEN la resolución identifica una conversación existente para ese huésped y canal
   `WHATSAPP`, THE SYSTEM SHALL reutilizarla en vez de crear una nueva por cada mensaje.

### R5 — Entrega al pipeline de conversación existente

**As a** huésped, **I want** que mi mensaje de WhatsApp reciba el mismo tratamiento que uno
del portal, **so that** la IA me conteste o me escale a un humano igual que por cualquier otro
canal soportado.

Acceptance criteria:

1. WHEN la identidad se resuelve (R4), THE SYSTEM SHALL invocar el mismo caso de uso de
   ingesta de mensajes de huésped que usa el portal (`ProcessInboundGuestMessageUseCase` o el
   punto de entrada equivalente), con `sender_type` y canal marcados como `WHATSAPP`.
2. THE SYSTEM SHALL respetar, sin duplicarlas, las reglas ya existentes de esa ingesta:
   clasificación de intención, prohibiciones de la regla 10 de `steering/security.md`,
   escalación a humano, y aparición en la bandeja del manager.
3. WHEN el pipeline genera una respuesta automática para una conversación `WHATSAPP`, THE
   SYSTEM SHALL enviarla de vuelta por el mismo adapter de R1, dentro de las restricciones de
   R2.

### R6 — Aprovisionamiento del número de WhatsApp por tenant

**Reescrita 2026-09-02** (design gate de la sección 4 del panel de revisión): la redacción
original asumía que cada tenant mintaría su propio token de ruta y su propio secreto de firma,
como con los webhooks de PMS — un modelo que no encaja con Meta, donde toda la cuenta de
AutoHostAI comparte una única App de Meta (un único `WHATSAPP_ACCESS_TOKEN`/
`WHATSAPP_APP_SECRET`, ya globales desde la sección 1) y cada tenant aporta, en cambio, su
propio número de WhatsApp Business (`phone_number_id`) bajo esa misma App. No hay ningún
secreto que mintar por tenant: lo único que un tenant necesita dar de alta es la asociación
entre su `phone_number_id` y su `tenant_id`, para que R4.1 pueda resolver a quién pertenece
cada mensaje entrante.

**As a** operador, **I want** asociar el número de WhatsApp Business de un tenant a su cuenta,
**so that** los mensajes que lleguen a ese número se enruten a la conversación correcta sin
tocar ningún otro tenant.

Acceptance criteria:

1. THE SYSTEM SHALL permitir asociar un `phone_number_id` de la Cloud API de Meta a un tenant,
   mediante un endpoint autenticado con el mismo permiso (`MANAGE_TENANT_SETTINGS`) que ya rige
   el aprovisionamiento de webhooks de otros proveedores. **Enmendada 2026-09-02** (descubierto
   al implementar la sección 5: `Conversation` exige siempre una propiedad, design D19): la
   asociación SHALL incluir una propiedad por defecto del tenant (`default_property_id`),
   validada como propia de ese tenant, a la que se adjuntan los mensajes de R4.3/R4.4 que no
   resuelven a una estancia concreta.
2. THE SYSTEM SHALL impedir que el mismo `phone_number_id` quede asociado a más de un tenant a
   la vez (restricción de unicidad) — un intento de asociarlo a un segundo tenant sin liberarlo
   antes del primero SHALL fallar de forma explícita, nunca sobrescribir la asociación existente
   en silencio.
3. THE SYSTEM SHALL permitir reasignar o retirar la asociación de un `phone_number_id`
   (equivalente operativo de "rotar" en este modelo: un número que cambia de tenant o deja de
   usarse), auditado (regla 9 de `steering/security.md`) igual que la creación.

## Out of scope

- `beds24-messaging-adapter` (mensajería de OTA vía `PMSMessagingPort`) — proveedor y ventana
  de corte distintos, aplazado sin fecha.
- Verificación de negocio de Meta y aprobación de plantillas ante Meta — se asume que las
  plantillas necesarias ya están aprobadas y se referencian por su identificador; el flujo de
  solicitud/aprobación de plantillas no es parte de este change.
- Verificación de negocio (WABA) de Meta para el número de producción — el número/credenciales
  de desarrollo (test number, hasta 5 destinatarios sin verificar) bastan para probar de
  extremo a extremo en este change; pasar a un número de producción verificado por Meta es
  trabajo operativo posterior, no de este change.
- Añadir Twilio (u otro proveedor) como alternativa a Meta detrás del mismo puerto — el adapter
  se diseña para que ese añadido no toque `domain/` ni `application/` (D1/D9 de `design.md`),
  pero construirlo no es parte de este change.
- Notificaciones `PUSH` — siguen sin adapter, sin relación con este change.
- Mensajes salientes a limpiadoras/técnicos que ya usa el canal `WHATSAPP` de `notifications`
  fuera de la ventana de 24h sin plantilla — quedan en `FAILED` por R2.3; construir el catálogo
  de plantillas aprobadas para cada tipo de notificación proactiva no es parte de este change
  (se puede resolver con una plantilla mínima o quedar documentado como brecha conocida).
- UI de configuración del proveedor de WhatsApp en el panel — la configuración es por variable
  de entorno (R1.3) y por el endpoint de aprovisionamiento (R6), no por una pantalla nueva.

## Affected specs

- `sdd/specs/whatsapp-cloud-adapter.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/access-notifications.md` — sustitución de `MockWhatsAppAdapter` en la tabla de
  adapters y en las secciones que la describen como mock.
- `sdd/specs/messaging-ai.md` — canal `WHATSAPP` deja de ser solo de salida (delegado al mock);
  gana un camino de entrada real hacia `ProcessInboundGuestMessageUseCase`.
- `sdd/specs/conversations-inbox.md` — conversaciones `WHATSAPP` pasan de no poder originarse
  nunca a poder originarse desde el webhook entrante.
- `sdd/specs/reservations-webhooks.md` — posible extensión si el diseño generaliza
  `webhook_endpoints`/`PMSProvider` a un proveedor no-PMS; a decidir en `/sdd:design`.
