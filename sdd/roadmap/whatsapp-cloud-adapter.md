# whatsapp-cloud-adapter

[BE] **WhatsApp real: salida *y* entrada**, sustituyendo `MockWhatsAppAdapter` y estrenando el primer canal
por el que un huésped puede escribir al sistema desde fuera.

**El hecho medido (2026-08-28)**: `MockWhatsAppAdapter` (`notifications/infrastructure/adapters.py`) hace un
`logger.info` y devuelve éxito; está marcado `EXTERNAL_DEPENDENCY` y su docstring dice qué falta —*"the real
one needs a WhatsApp Business account and its credentials (rule 8 ... already reserves the variable names)"*—,
aunque **esa frase es hoy inexacta y conviene corregirla al pasar**: `.env.example` reserva los seis nombres
`SMTP_*` y **ninguno** de WhatsApp. `messaging/infrastructure/channels.py` delega en ese mock la respuesta de
la IA por el canal `WHATSAPP`, así que el mock cubre las dos capabilities a la vez.

**Esto NO es `beds24-messaging-adapter`, y la distinción es la que evita planificarlo mal**: aquella entrada
es mensajería **de OTA** (Airbnb/Booking) a través de `PMSMessagingPort`, y está aplazada a que los canales
OTA reales se conecten —ventana de corte sin fecha, más una cuenta de Beds24 que venció el 2026-08-17—.
WhatsApp Business no depende de ninguna de las dos condiciones: se puede construir y probar hoy.

**Las dos restricciones del proveedor que condicionan el diseño y no la implementación**:

1. **La ventana de 24 h.** WhatsApp solo permite texto libre dentro de las 24 horas siguientes al último
   mensaje del usuario. Fuera de ella únicamente se pueden enviar **plantillas aprobadas** previamente por
   Meta. Eso decide qué notificaciones pueden viajar por este canal: la respuesta de la IA a un huésped que
   acaba de escribir, sí; una `CLEANING_TASK_ASSIGNED` proactiva a una limpiadora, **no**, salvo plantilla.
   Un adapter que ignore esto devolverá éxito y no entregará nada — exactamente el fallo silencioso que
   `messaging/infrastructure/channels.py` argumenta por escrito que hay que evitar.
2. **El webhook de entrada es un segundo endpoint entrante sin firma propia sobre datos de huésped**, así que
   le aplica entera la **regla 12** de `steering/security.md`, con el precedente ya construido de
   `reservations-webhooks`: ruta con **token opaco por tenant** (`POST /api/v1/webhooks/{provider}/{webhook_token}`
   ya existe con esa forma), verificación de la firma del proveedor, **idempotencia por el id de mensaje del
   proveedor**, y desacople entre el volumen entrante y las llamadas salientes — que en aquel change se
   resolvió con `process_webhook_events` cada 60 s, y su cadencia *es* el techo.

**Recomendación de proveedor para poder probar ya**: escribir el adapter contra el puerto existente y
levantarlo primero sobre el **sandbox de WhatsApp de Twilio**, que da número y credenciales en minutos sin
verificación de Meta Business, y dejar la Cloud API de Meta como sustitución posterior — el puerto es el
mismo y el cambio queda acotado al cliente HTTP. Elegir directamente Cloud API es defendible, pero mete la
verificación del negocio y la aprobación de plantillas en el camino crítico de una prueba de extremo a
extremo.

**Alcance de entrada**: el mensaje entrante tiene que resolver **tenant y estancia** a partir de un número de
teléfono, que es un dato que hoy no indexa nada. Ése es el trabajo real de la mitad de entrada, y es donde
`guest-portal-messaging` ayuda si va antes: deja probado el camino
`ProcessInboundGuestMessageUseCase` → IA → escalación → bandeja con un emisor que ya está autenticado por
token, de modo que aquí solo se discute la resolución de identidad y no todo el pipeline a la vez.
