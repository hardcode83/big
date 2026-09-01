# guest-portal-messaging

[BE+FE] **el huésped no puede escribir; hoy solo puede escribir *por* él un operador**.

**El hecho medido (2026-08-28)**: `messaging-ai` entregó el pipeline completo —clasificación de intent,
umbral de confianza, escalación por seis razones, respuesta de la IA y bandeja del manager— y su única
puerta de entrada es `POST /api/v1/conversations/{id}/messages` con `sender_type: "GUEST"`, que exige
`MANAGE_CONVERSATIONS` y por tanto **rol de manager**. El propio esquema lo dice: *"the caller is
transcribing what the guest said"* (`messaging/api/schemas.py`, `CreateMessageRequest`). El portal del
huésped tiene exactamente cuatro rutas (`GET /guest/info/{token}`, `GET`/`POST /guest/checkin/{token}`,
`POST /guest/incident/{token}`) y **ninguna es de mensajería**. Resultado: la capability más cara del MVP
—`messaging-ai`, size L, con IA y escalación— no tiene ni un solo emisor real.

**Por qué esta entrada y no esperar a WhatsApp**: es la única forma de cerrar el bucle
huésped → IA → escalación → manager → huésped **sin depender de ningún proveedor externo, ni de una cuenta
de Meta, ni de plantillas aprobadas, ni de la ventana de corte de las OTA que tiene aplazado a
`beds24-messaging-adapter` sin fecha**. Todo lo que necesita ya está construido: el token opaco, la
autorización por estancia y tenant, el throttle por token (`guests/infrastructure/portal_throttle.py`) y la
auditoría con `actor_guest_token_hash`, todo de `guest-portal-api`; y la pantalla `/guest/[token]` con su
i18n ES/EN, de `guest-portal-web`.

**Lo que decide y no es cosmético**:

1. **Si estrena canal**. `ConversationChannel` tiene seis miembros (`WHATSAPP`, `AIRBNB_MSG`, `BOOKING_MSG`,
   `EMAIL`, `PHONE_TRANSCRIPT`, `MANUAL`) y ninguno es «el portal». Reusar `MANUAL` es barato y **miente**:
   `PanelOutboundAdapter` reporta entrega porque la fila *es* la entrega para un operador que mira el panel,
   y aquí el lector es el huésped en su navegador. Un miembro `PORTAL` nuevo con su adapter —cuya entrega es
   igualmente la fila, pero leída por la otra punta— es honesto y es una migración de enum, no de datos.
2. **Quién abre la conversación**. Hoy solo `POST /conversations` (manager). Si el huésped escribe primero,
   alguien tiene que crearla desde un token, y eso es un escritor nuevo acotado a la estancia.
3. **Qué ve el huésped de vuelta**. El hilo entero incluye mensajes con `sender_type` `AI`, `SYSTEM` y
   `MANAGER`; hay que decidir si el portal los distingue y si muestra el estado de escalación — decir
   «te responderá una persona» es producto, no adorno.
4. **Throttle y tamaño**. `MAX_MESSAGE_CONTENT_LENGTH` ya existe en `messaging`, y el portal ya tiene su
   propio throttle: hay que decir cuál manda, no aplicar dos por casualidad.

**Regla 11 de `steering/security.md`**: `messages.content` es un sumidero de texto libre que ahora recibe
escritura de un **portador anónimo** y no de un usuario autenticado. Es la primera vez que eso pasa en esa
columna, así que su fila del censo cambia de audiencia y la entrada tiene que decirlo. La disciplina que ya
existe ayuda: `MockAIAdapter` nunca cita la entrada del huésped en su respuesta (R3.3/D7 de `messaging-ai`).
