# Proposal: guest-portal-messaging

## Why

`messaging-ai` entregó el pipeline completo —detección de idioma, clasificación de intent,
umbral de confianza, escalación por seis razones, respuesta desde catálogo cerrado y bandeja
del manager— y **no tiene ni un solo emisor real**. Su única puerta de entrada es
`POST /api/v1/conversations/{id}/messages` con `sender_type: "GUEST"`, que exige
`MANAGE_CONVERSATIONS` y por tanto rol de manager; el propio esquema lo dice
(`messaging/api/schemas.py`: *"the caller is transcribing what the guest said"*). El portal del
huésped tiene exactamente cuatro rutas —`GET /guest/info/{token}`, `GET`/`POST /guest/checkin/{token}`,
`POST /guest/incident/{token}`— y **ninguna es de mensajería**. Hoy el huésped no puede escribir:
solo escribe *por* él un operador.

Es la única forma de cerrar el bucle huésped → IA → escalación → manager → huésped **sin
depender de ningún proveedor externo**: ni cuenta de Meta ni plantillas aprobadas
(`whatsapp-cloud-adapter`), ni la ventana de corte de las OTA que tiene aplazado sin fecha a
`beds24-messaging-adapter`. Todo lo que necesita ya está construido: el token opaco, la
autorización por estancia y tenant, el throttle por token y la auditoría con
`actor_guest_token_hash`, de `guest-portal-api`; y la página `/guest/[token]` con su i18n ES/EN,
de `guest-portal-web`.

Contexto: entrada de roadmap `guest-portal-messaging` y su nota `sdd/roadmap/guest-portal-messaging.md`
(medida el 2026-08-28). PRD §§13, 16, 23, 24. Specs vivas:
[`messaging-ai`](../../specs/messaging-ai.md), [`guest-portal-api`](../../specs/guest-portal-api.md),
[`guest-portal`](../../specs/guest-portal.md).

## What changes

Después de este change el portal del huésped tiene **dos rutas anónimas más** —leer su hilo y
escribir en él, con el token como último segmento— que alimentan el pipeline de `messaging-ai`
ya existente sin duplicarlo. La conversación del portal es **una por estancia**, de un canal
nuevo `PORTAL` cuya entrega *es* la fila leída por el navegador del huésped, y la crea el primer
mensaje que el huésped escribe. La página `/guest/[token]` gana una sección de conversación
mobile-first, con envío, hilo, estados accesibles e i18n ES/EN, que se refresca por polling
mientras la pestaña está visible. El pipeline pasa a aceptar un actor **portador de token** allí
donde hoy exige un `User`, y el censo de la regla 11 registra que `messages.content` recibe por
primera vez escritura anónima desde internet.

## Requirements

### R1 — El huésped escribe desde su token

**As a** huésped con un enlace de portal vigente, **I want** escribir un mensaje al alojamiento
desde la propia página de mi estancia, **so that** pueda preguntar sin instalar nada, sin cuenta
y sin que un operador tenga que transcribirme.

Acceptance criteria:

1. THE SYSTEM SHALL exponer `POST /api/v1/guest/messages/{token}` en
   `app/guests/api/portal_router.py`, anónima, con el token como último segmento, respondiendo
   `201` con el mensaje registrado.
2. WHEN llega una petición a esa ruta, THE SYSTEM SHALL aplicar **la misma secuencia de
   autorización** que las cuatro rutas existentes y en el mismo orden —`probe_allowed(ip)` antes
   de cualquier consulta, `authorize(token, now)`, `record_failed_authorisation(ip)` en toda
   negativa, y `request_allowed(token_hash)` solo después de autorizar— reutilizando el helper
   `_authorised` y sin una segunda copia de ese orden.
3. THE SYSTEM SHALL derivar tenant, reserva, propiedad y `token_hash` **de la fila del token**, y
   NEVER SHALL leer ninguno de ellos de la ruta, del cuerpo, de la query ni de una cabecera.
4. WHEN el mensaje se acepta, THE SYSTEM SHALL ejecutar el pipeline de `messaging-ai` **entero y
   sin duplicarlo** —detección de idioma, clasificación, persistencia con intent y confianza,
   `TimelineEvent(GUEST_MESSAGE_RECEIVED)`, evaluación de escalación, respuesta automática o
   escalación con su notificación, y apertura de incidencia para `MAINTENANCE_ISSUE`/`ACCESS_PROBLEM`—
   en **una sola transacción**, tal y como lo describen R4 y R5 de [`messaging-ai`](../../specs/messaging-ai.md).
5. THE SYSTEM SHALL aceptar en el cuerpo **exactamente un campo**, `content`, rechazando cualquier
   campo no declarado —incluidos `sender_type`, `tenant_id`, `reservation_id`, `property_id`,
   `conversation_id` y `ai_generated`— con `422`. El `sender_type` es `GUEST` por construcción de la
   ruta y NEVER SHALL ser expresable por el llamante.
6. IF `content` excede `MAX_MESSAGE_CONTENT_LENGTH` (4000 caracteres) o no supera el guardián de
   texto almacenable, THEN THE SYSTEM SHALL rechazarlo con `422` **antes de crear nada**, y el
   cuerpo del error NEVER SHALL hacer eco del valor rechazado.
7. THE SYSTEM SHALL responder al fallo de autorización con el **mismo `404` constante** que las
   cuatro rutas existentes, indistinguible entre token inexistente, mal formado, revocado, fuera
   de ventana o de reserva cancelada.

### R2 — El hilo que el huésped lee

**As a** huésped, **I want** ver lo que he escrito y lo que me han contestado, **so that** sepa
que mi mensaje llegó y si me responde ya alguien.

Acceptance criteria:

1. THE SYSTEM SHALL exponer `GET /api/v1/guest/messages/{token}`, anónima, devolviendo los
   mensajes de la conversación del portal de esa estancia en **orden cronológico ascendente** y
   paginados, con la misma secuencia de autorización de R1.2. WHEN la petición no declara `page`,
   THE SYSTEM SHALL devolver la **última** página —la ventana más reciente, ascendente dentro—, y
   un `page` explícito SHALL seguir alcanzando las anteriores.
2. WHEN se devuelve un mensaje, THE SYSTEM SHALL emitir un remitente **agrupado en dos valores**
   —el huésped y el alojamiento—, derivado en el backend de `sender_type`, y NEVER SHALL
   **publicar** si una respuesta la escribió la IA o una persona, ni `sender_user_id`, ni
   `confidence_score`, ni `intent`, ni `metadata`.
   **Acotado a lo publicado el 2026-08-29**, durante `/sdd:run` y a propuesta del panel de
   seguridad de las secciones 5-6: la redacción original decía «revelar», y eso es más de lo
   que el sistema puede dar. La respuesta automática lleva el **mismo instante** que el mensaje
   que la provocó —el pipeline las escribe en la misma llamada—, llega en el mismo sondeo, y su
   texto sale de un catálogo cerrado; los tres canales dejan la distinción inferible desde
   fuera del cuerpo de la respuesta. Lo que este requisito exige y el sistema sí garantiza es
   que **la distinción no viaja en la proyección**. El residuo queda declarado en
   [`design.md`](design.md) §«Residuo de R2.2».
3. WHERE la conversación está `PENDING_HUMAN` o `HUMAN_HANDLING`, THE SYSTEM SHALL declararlo en
   la respuesta como un **estado cerrado de espera** —«te responderá una persona»— y NEVER SHALL
   devolver la razón de escalación, que es información interna.
4. THE SYSTEM SHALL devolver una proyección congelada cuyos campos sean **solo** los que R2.2 y
   R2.3 nombran, de modo que la exclusión sea estructural y ningún serializador futuro pueda
   filtrar un campo interno por descuido.
5. WHEN la estancia todavía no tiene conversación de portal, THE SYSTEM SHALL responder `200` con
   un hilo vacío, y NEVER SHALL crearla ni responder `404`: leer no abre conversación.
6. THE SYSTEM NEVER SHALL ofrecer al portador del token ninguna ruta para escalar, resolver,
   cerrar o reabrir una conversación, ni para listar conversaciones que no sean la de su estancia.

### R3 — La conversación del portal: canal propio, una por estancia

**As a** manager, **I want** que lo que escribe el huésped desde el portal llegue a mi bandeja
como un hilo identificable y con un canal que no mienta sobre cómo se entrega, **so that** pueda
contestarle sabiendo dónde lo va a leer.

Acceptance criteria:

1. THE SYSTEM SHALL añadir `PORTAL` como miembro de `ConversationChannel` y NEVER SHALL reutilizar
   `MANUAL`: `PanelOutboundAdapter` reporta entrega porque la fila *es* la entrega **para un
   operador que mira el panel**, y aquí el lector es el huésped en su navegador. Es una migración
   de enum, no de datos.
2. THE SYSTEM SHALL registrar para `PORTAL` un adapter de salida propio en el `dict` visible de
   `messaging/infrastructure/channels.py`, cuya entrega es la persistencia de la fila que el
   huésped lee, y NEVER SHALL despacharlo dinámicamente.
3. WHEN el huésped escribe y su estancia no tiene conversación de canal `PORTAL`, THE SYSTEM SHALL
   crearla en la misma transacción, con `property_id`, `reservation_id` y `guest_id` derivados del
   token, y su `language` detectado del propio mensaje; IF el idioma no puede decidirse, THEN SHALL
   usar `es`.
4. THE SYSTEM SHALL garantizar que una estancia tiene **como mucho una** conversación de canal
   `PORTAL`, y SHALL escribir siempre sobre ella, de modo que dos mensajes simultáneos del mismo
   huésped no produzcan dos hilos.
5. WHERE la estancia ya tiene conversaciones de otros canales abiertas por un operador
   (`WHATSAPP`, `MANUAL`, …), THE SYSTEM SHALL dejarlas intactas y NEVER SHALL escribir en ellas
   desde el portal ni mostrárselas al huésped: son hilos distintos y este change no los fusiona.
6. WHEN un manager contesta desde la bandeja a una conversación `PORTAL`, THE SYSTEM SHALL
   registrar su mensaje con el flujo que ya existe (`RecordHumanReplyUseCase`, `take_over`), sin
   ruta nueva, y el huésped SHALL leerlo por R2.
7. THE SYSTEM NEVER SHALL admitir la apertura de una conversación de canal `PORTAL` desde
   `POST /api/v1/conversations`: el hilo del portal lo abre el primer mensaje del huésped y ninguna
   otra vía. IF un llamante lo intenta, THEN THE SYSTEM SHALL rechazarlo en el caso de uso —no solo
   en el esquema— de modo que un hilo que el huésped ve sin haber escrito no sea construible.

### R4 — Una escritura anónima sobre `messages`: actor, límites y sumideros

**As a** responsable de la seguridad del sistema, **I want** que abrir `messages.content` a un
portador anónimo quede declarado, acotado y auditable, **so that** no se convierta en el sumidero
sin dueño que la regla 11 existe para impedir.

Acceptance criteria:

1. THE SYSTEM SHALL admitir en el pipeline de mensaje entrante un actor **portador de token**
   —identificado por su digest— allí donde hoy exige `actor_user_id: uuid.UUID`, y toda fila de
   `AuditLog` que ese camino escriba SHALL llevar `actor_guest_token_hash` y **exactamente uno** de
   los dos actores, nunca los dos ni ninguno.
2. THE SYSTEM SHALL declarar en el censo de la regla 11 de
   [`steering/security.md`](../../steering/security.md) que la fila de `messages.content` con
   `sender_type = GUEST` **cambia de audiencia**: pasa de recibir prosa transcrita por un operador
   autenticado a recibir escritura directa de un portador anónimo desde internet, bajo la misma
   excepción 4 de prosa de tercero y con el escritor nuevo nombrado.
3. THE SYSTEM SHALL acotar el contenido con `MAX_MESSAGE_CONTENT_LENGTH`, que es **el límite de
   producto sobre el texto**, y SHALL acotar el ritmo con el throttle por token del portal, que es
   **el límite sobre la ruta**: son dos cosas distintas y ninguna sustituye a la otra. El tope de
   cuerpo de 1 MiB lo sigue aplicando `MaxBodySizeMiddleware` antes del routing, sin rama propia.
4. THE SYSTEM NEVER SHALL propagar el contenido del mensaje a `timeline_events` ni a
   `audit_logs.changes`: los eventos llevan título constante e identificadores, como ya exige R3 de
   [`messaging-ai`](../../specs/messaging-ai.md).
5. THE SYSTEM SHALL demostrar con test de aislamiento propio que un token de un tenant no lee ni
   escribe mensajes ni conversaciones de otro, en **cada** vía nueva: lectura del hilo y envío.
6. THE SYSTEM SHALL registrar las dos rutas nuevas en el censo `ANONYMOUS_ENDPOINTS` de
   `tests/test_route_authorization.py`, que pasa de cuatro entradas de portal a seis, de modo que
   la ampliación de la superficie anónima sea un diff visible y no un descuido.
7. THE SYSTEM NEVER SHALL introducir un código de error nuevo: `NOT_FOUND`, `RATE_LIMITED`,
   `PAYLOAD_TOO_LARGE` y `VALIDATION_ERROR` ya existen en el registro.

### R5 — La conversación en `/guest/[token]`

**As a** huésped en el móvil, **I want** una sección de conversación en la página de mi estancia,
**so that** escribir y leer sea parte del mismo enlace y no otra herramienta.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a `/guest/[token]` una sección de conversación con el hilo y un campo
   de envío, mobile-first, cuyo fallo NEVER SHALL derribar las secciones de estancia, check-in ni
   incidencia — salvo el gate de `info`, que sigue gobernando la página entera.
2. WHILE `info` no ha autorizado, THE SYSTEM SHALL NOT renderizar la sección de conversación: un
   enlace muerto no ofrece su formulario.
3. WHEN la pestaña está visible, THE SYSTEM SHALL re-consultar el hilo periódicamente por polling,
   y SHALL detener el refresco cuando deja de estarlo; NEVER SHALL abrir WebSocket ni SSE.
4. WHEN el huésped envía un mensaje, THE SYSTEM SHALL deshabilitar el botón mientras el envío está
   en curso, SHALL anunciar el progreso mediante una región `aria-live`, y SHALL mostrar el hilo
   actualizado al terminar.
5. THE SYSTEM SHALL presentar cada mensaje como **«tú» o «el alojamiento»** según el remitente
   agrupado que publica R2.2, y NEVER SHALL etiquetar una respuesta como escrita por la IA ni
   derivar esa distinción en el cliente.
6. WHERE la respuesta declara el estado de espera de R2.3, THE SYSTEM SHALL mostrar una copia
   localizada de «te responderá una persona», y NEVER SHALL mostrar razón de escalación alguna.
7. THE SYSTEM SHALL resolver **todo** texto visible por i18n ES/EN sobre el namespace `guest`
   (`locales/es/guest.json` y `locales/en/guest.json`), con toda clave nueva presente en ambos
   catálogos y ninguna cadena hardcodeada.
8. THE SYSTEM SHALL proporcionar estados accesibles y localizados de carga, vacío, error de
   autorización, validación (`422`), rate limit (`429`) y error genérico (`5xx`/red) para las dos
   operaciones nuevas; IF la API responde `429`, THEN NEVER SHALL reintentar automáticamente ni
   presentar el reintento como prueba de que el mensaje no se envió.
9. THE SYSTEM SHALL consumir exclusivamente los tipos generados desde `backend/openapi.json`,
   construyendo el cliente sin `getHeaders` de modo que estructuralmente no pueda emitir
   `Authorization: Bearer`, y NEVER SHALL renderizar el token en texto visible, metadata, título ni
   mensaje de error.
10. THE SYSTEM SHALL mantener regenerados y commiteados en el mismo PR `backend/openapi.json` y
    `frontend/lib/api/generated/openapi.d.ts` — las dos mitades del puente que exige
    [`steering/documentation.md`](../../steering/documentation.md).

## Out of scope

- **Entrega por canal externo.** WhatsApp real (`whatsapp-cloud-adapter`), email
  (`smtp-delivery-adapter`, `notification-channel-routing`) y mensajería de OTA
  (`beds24-messaging-adapter`, aplazada sin fecha). Aquí la entrega *es* la fila que el huésped lee
  en su navegador.
- **Aviso al huésped fuera de la página.** Que le llegue un email o un push cuando le contestan
  necesita canal externo: va con `notification-channel-routing` y `guest-scheduled-comms`.
- **Tiempo real.** WebSocket/SSE. No existe superficie de tiempo real en el proyecto y este change
  no la estrena; R5.3 fija polling.
- **Mensajería del personal.** limpiadora↔manager y técnico↔manager son `staff-messaging` y
  `staff-messaging-web`, con su propia decisión de entrada sobre `Conversation`.
- **Fusionar hilos de canales distintos** de una misma estancia (R3.5), y cualquier operación de
  bandeja nueva para el manager.
- **Adjuntos y fotos** en el mensaje del huésped. `incident-photos` y `file-storage` gobiernan las
  fotos, y el portal no las ofrece hoy.
- **Que el huésped resuelva, cierre o reabra su conversación** explícitamente, o escale a mano
  (R2.6). La reapertura por escribir sobre una `RESOLVED` ya la da `messaging-ai` R4.
- **Emisión automática del enlace de portal** al huésped: sigue siendo manual, como declara
  `guest-portal-api`.
- **Adapter de IA real.** `MockAIAdapter` sigue siendo el único implementador de `AIAdapter`.
- **Traducción de mensajes.** El sistema detecta idioma y responde en él; no traduce el hilo.

## Affected specs

- [`sdd/specs/messaging-ai.md`](../../specs/messaging-ai.md) — modificar: canal `PORTAL` y su
  adapter en el registro de R6, actor portador de token en el pipeline de R4, y la segunda puerta
  de entrada real a `messages`.
- [`sdd/specs/guest-portal-api.md`](../../specs/guest-portal-api.md) — modificar: el portal pasa de
  cuatro rutas anónimas a seis, con el mismo orden de autorización, el mismo `404` y los mismos
  límites.
- [`sdd/specs/guest-portal.md`](../../specs/guest-portal.md) — modificar: la superficie web gana la
  sección de conversación, su polling y sus estados.
- [`sdd/specs/api-contract.md`](../../specs/api-contract.md) — modificar: dos endpoints nuevos en el
  contrato publicado y en el artefacto derivado del frontend.
- [`sdd/specs/conversations-inbox.md`](../../specs/conversations-inbox.md) — revisar: la bandeja del
  manager empieza a recibir conversaciones de canal `PORTAL`.

Además, fuera de `sdd/specs/`: [`sdd/steering/security.md`](../../steering/security.md) — el censo
de la regla 11 registra el cambio de audiencia de `messages.content` (R4.2). No es una spec, pero es
donde vive ese contrato y este change lo toca.
