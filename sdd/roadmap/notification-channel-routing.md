# notification-channel-routing

[BE] **el conmutador de canal existe, se guarda, se parchea y se audita — y no lo lee nadie**.

**El hecho medido (2026-08-28)**: `TenantConfig.notification_email_enabled` (por defecto `True`) y
`notification_whatsapp_enabled` (por defecto `False`) viven en `tenants/domain/entities.py`, tienen columna
en la migración baseline, entran y salen por `PATCH /api/v1/tenants/{id}`, están en `AUDITABLE_FIELDS` y
tienen tests de mutación. Un barrido por ambos nombres sobre `backend/` no encuentra **ni un lector fuera de
`tenants/` y `audit/`**: ningún escritor de notificaciones y ningún emisor los consulta.

**La consecuencia, que es el motivo de la entrada**: los escritores fijan el canal a pelo, y ocho de los
diez fijan `NotificationChannel.IN_APP` (`cleaning/domain/notifications.py`, `maintenance/domain/notifications.py`,
`messaging/domain/notifications.py`, `notifications/application/use_cases.py`, `guests/application/use_cases.py`).
La única excepción es la recuperación de contraseña, que fija `EMAIL` (`auth/application/recovery.py`).
Por tanto **ninguna fila nace con `channel = EMAIL` o `WHATSAPP` salvo el reset de contraseña**, y de ahí se
sigue algo que conviene entender antes de planificar nada: *un adapter SMTP real, o uno de WhatsApp real, no
tendría hoy quién lo invocase*. Esta entrada es la pieza que hace que las dos siguientes signifiquen algo,
y no una preferencia de usuario que se pueda posponer.

**Alcance**: resolver, en el momento de escribir la fila o en el emisor, **qué canales corresponden a este
destinatario y a esta notificación**, a partir de (a) los dos flags del tenant, (b) el contacto disponible
—`User.email` siempre, `User.phone` opcional (`auth/domain/entities.py`)—, y (c) `User.preferred_language`,
que hoy no lo lee ningún cuerpo de notificación: `subject`/`body` se escriben en inglés y para un operador.

**Lo que decide y no es cosmético**:

1. **Una fila por canal o una fila con varios canales**. `NotificationLog.channel` es singular y
   `dispatch_notifications` drena `PENDING`, así que «email **y** in-app» son hoy dos filas — con dos
   `sla_deadline_at` y por tanto dos candidatas a incumplir el mismo SLA. Es la trampa principal.
2. **Si el canal es del tipo de notificación o del destinatario**. No es lo mismo: un `SLA_BREACH` al
   manager y un `CLEANING_TASK_ASSIGNED` a la limpiadora no tienen por qué viajar igual, y el tenant tiene un
   solo par de flags para las diecisiete.
3. **Qué pasa cuando el canal está activado y falta el contacto**. `User.phone` es `str | None`, y los
   adapters tratan el destinatario vacío como fallo por valor y no como excepción: hay que decidir si eso
   es `SKIPPED` (como el canal sin adapter, R4.5) o `FAILED`, porque solo el segundo consume reintentos.
4. **La degradación silenciosa está prohibida por precedente**: `messaging/infrastructure/channels.py`
   argumenta por escrito por qué los dos canales de OTA **no** tienen adapter en vez de tener un no-op —
   *"it would show an operator a delivered message the guest never received"*. La resolución de canal tiene
   que heredar esa regla y no caer a `IN_APP` en silencio cuando el canal elegido no puede entregar.

**Se separa de `hardening-release` a propósito**: aquella entrada agrupa «settings/integraciones FE + suite
E2E + docker + README + DoD §28», y esto no es configuración de pantalla sino una decisión de dominio sobre
quién recibe qué y por dónde. Además es `needs:` de tres entradas y meterla dentro de un `[CROSS]` las
bloquearía a todas.
