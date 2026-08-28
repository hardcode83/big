# guest-scheduled-comms

[BE] **lo que el sistema tiene que decirle al huésped por su cuenta, y que hoy no dice nada**: recordatorios
de check-in a 24 h y 2 h, recordatorio de checkout, y la entrega de las instrucciones de acceso de PRD §15.

**El hecho medido (2026-08-28)**: `send_checkin_reminders` es uno de los ocho jobs de PRD §8.3 y **no tiene
código**. `scheduler/schedule.py` lo dice por escrito y explica por qué no está en el calendario: *"it is a
message to a guest, so what it needs is the channel adapter and the template that `messaging-ai` /
`access-notifications` own. The clock is the trivial half, and a beat entry pointing at a task nobody has
written fails once, at 03:00, in a worker log nobody is reading."* Los tres tipos correspondientes
—`CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H`, `CHECKOUT_REMINDER`— existen en el enum, están cubiertos por
`tests/notifications/test_escalation.py` y no los escribe nadie.

**Y el segundo hueco, que es el que más se nota operando**: las instrucciones de acceso. `access-notifications`
entregó `AccessRecord`, el `ManualAccessAdapter` y `POST /access-records/{id}/delivered`, es decir el
**registro** de que alguien las entregó — a mano. No hay ningún escritor que se las mande al huésped: los
diez escritores de notificaciones del backend van a usuarios del tenant, y **ninguna fila de
`notification_logs` tiene hoy como destinatario a un huésped**.

**Por qué va la última del bloque**: la mitad de reloj es trivial y la mitad de canal no existía. Con
`notification-channel-routing` y `smtp-delivery-adapter` delante, el destinatario deja de ser un problema
(el huésped tiene email en `Guest`) y esto se convierte en un job, una plantilla y una decisión de zona
horaria. Sin ellos, sería escribir filas `PENDING` que nadie entrega.

**Lo que decide y no es cosmético**:

1. **La hora local**. El worker fija `celery_app.conf.timezone = "UTC"` a propósito (R3.7 de `celery-jobs`:
   el proceso nunca interpreta zonas, las horas locales se derivan de la zona de cada propiedad). «24 h
   antes del check-in» es relativo y se libra; «recordatorio de checkout» a una hora del día, no.
2. **La idempotencia**. Un job periódico que manda un email tiene que poder correr dos veces sin mandarlo
   dos veces, y el candado de `scheduler/locks.py` protege la ejecución, no el efecto. `NotificationLog` con
   `related_type`/`related_id` es el sitio natural para la clave, pero hay que decirlo.
3. **El idioma**. Un huésped no es un usuario del tenant: no tiene `preferred_language`. `messaging` ya
   resuelve idioma por conversación (`messaging/domain/language.py`, `SUPPORTED_LANGUAGES`) y conviene reusar
   esa resolución en vez de estrenar una tercera.
4. **Regla 11, y aquí sí muerde**: las instrucciones de acceso llevan **código de acceso**, que es el único
   contenido al que esa regla concede paso en forma enmascarada por `subject`/`body`. Todos los cuerpos
   escritos hasta hoy llevan solo ids y un tipo, precisamente para no tener que resolver esto; este change es
   el que no puede esquivarlo y tiene que declarar la forma exacta.
