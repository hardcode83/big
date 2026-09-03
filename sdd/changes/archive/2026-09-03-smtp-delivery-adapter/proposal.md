# Proposal: smtp-delivery-adapter

## Why

El único adaptador de email hoy es `ConsoleEmailAdapter` (`backend/app/notifications/infrastructure/adapters.py`): hace un `logger.info` con las *longitudes* de `subject`/`body` y devuelve siempre éxito. Las seis variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` y `SMTP_USE_TLS` ya están reservadas y vacías en `.env.example`, y nada las lee.

Hasta ahora esto era razonable porque ninguna fila nacía con `channel = EMAIL` salvo el reset de contraseña (`recovery.py`). `notification-channel-routing` acaba de mergear (PR #143) y `channel_resolver.py` ya añade `EMAIL` a cualquier notificación cuando el tenant lo tiene activo y el contacto es usable — así que un adaptador real ahora tiene destinatario a quien entregarle algo, no solo el caso de prueba del reset de contraseña. Extraído de `hardening-release`, que lo tenía enterrado junto a la suite E2E y el DoD §28; ese entrega dejó explícitamente la pantalla de settings/integraciones y **no** las credenciales ni el adaptador, que son este change.

## What changes

Un `SMTPEmailAdapter` real sustituye a `ConsoleEmailAdapter` en el registro de `EMAIL`/`CONSOLE` cuando hay relay configurado (`ConsoleEmailAdapter` se conserva como comportamiento de dev/sin-configurar, no se borra). El adaptador cumple el mismo contrato que ya cumplen `ConsoleEmailAdapter` y `MockWhatsAppAdapter` — mismo tipo de retorno (`NotificationResult`), mismo fallo-por-valor, mismo precondition de destinatario en blanco — y traduce cualquier fallo del cliente SMTP al vocabulario cerrado de `NotificationErrorCode` (rule 11 de `steering/security.md`: `last_error` nunca lleva texto del proveedor). Las credenciales llegan al despliegue de dev por el mismo mecanismo ya establecido para secretos añadidos después del aprovisionamiento (OCI Vault por nombre, como el token del túnel y los secretos de medios) — no un GitHub Actions secret nuevo. Fuera del código: DNS del dominio de dev con SPF y DKIM.

## Requirements

### R1 — SMTPEmailAdapter sustituye a ConsoleEmailAdapter para EMAIL/CONSOLE

**As a** operador del sistema, **I want** un adaptador SMTP real entregando `EMAIL`/`CONSOLE`, **so that** huéspedes y personal reciban de verdad el correo en vez de una línea de log.

Acceptance criteria:

1. WHEN `adapter_registry()` (`backend/app/notifications/infrastructure/adapters.py`) construye el registro con el relay SMTP configurado, THE SYSTEM SHALL registrar `SMTPEmailAdapter` (implementando el `Protocol NotificationAdapter`) para `NotificationChannel.EMAIL` y `NotificationChannel.CONSOLE`.
2. WHEN `SMTPEmailAdapter.send` recibe `recipient_contact` en blanco, THE SYSTEM SHALL devolver `NotificationResult.failure(INVALID_RECIPIENT)` sin contactar el relay — misma precondición que `ConsoleEmailAdapter` y `MockWhatsAppAdapter`.
3. WHEN el relay acepta el mensaje (2xx de SMTP), THE SYSTEM SHALL devolver `NotificationResult.ok()`.
4. THE SYSTEM SHALL NOT loguear `recipient_contact`, `subject` ni `body` en `SMTPEmailAdapter` — mismo criterio que el docstring de `ConsoleEmailAdapter` ya declara para rule 11.

### R2 — Selección de adaptador y fallo temprano en configuración parcial

**As a** operador de un despliegue, **I want** que un SMTP a medio configurar falle alto y claro, en vez de parecer sano, **so that** un despliegue mal configurado no entregue en silencio y nadie lo note hasta que un huésped reclame.

Acceptance criteria:

1. WHEN `SMTP_HOST` no está definido, THE SYSTEM SHALL registrar `ConsoleEmailAdapter` para `EMAIL`/`CONSOLE` igual que hoy — un entorno sin relay configurado sigue arrancando sin exigir credenciales que no usa (mismo motivo por el que `config.py` no declara hoy `SMTP_*` en `Settings`).
2. IF `SMTP_HOST` está definido Y falta cualquiera de `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_USERNAME`/`SMTP_PASSWORD`, THEN THE SYSTEM SHALL fallar al construir `adapter_registry()` — no al importar el módulo — nombrando la variable ausente. Amendment (design D2, resuelto en el gate de diseño): username/password pasan a ser incondicionales y no solo "cuando SMTP_USE_TLS lo requiera" — el proveedor elegido (D6, OCI Email Delivery) siempre exige TLS y auth juntos, así que la condición nunca era alcanzable en la práctica; `smtp_use_tls = False` con credenciales puestas también falla, por el mismo motivo (cifrado en texto plano si no).
3. THE SYSTEM SHALL nunca aceptar `SMTP_PASSWORD` en blanco de forma silenciosa cuando `SMTP_HOST` está activo — ausente en ese caso es el que R2.2 cubre. Amendment (design D2): el campo lleva default vacío en `Settings` como los otros cinco (R2.1 exige que el import nunca falle); el "nunca una cadena vacía silenciosa" lo hace cumplir `adapter_registry()` al construirse, no la ausencia de un default en `Settings`.

### R3 — Errores del relay real, en el vocabulario cerrado existente

**As a** operador que depura una entrega fallida, **I want** que los fallos del relay SMTP lleguen a `last_error` en el vocabulario cerrado de `NotificationErrorCode`, **so that** ningún texto del proveedor —que rutinariamente incluye el propio mensaje que falló— llegue a esa columna.

Acceptance criteria:

1. WHEN el cliente SMTP lanza una excepción (fallo de auth, conexión rechazada, destinatario rechazado, timeout), THE SYSTEM SHALL capturarla dentro de `SMTPEmailAdapter.send` y devolver `NotificationResult.failure(...)` — nunca dejarla propagar ni pasar su mensaje.
2. WHEN el relay no responde dentro de un timeout acotado, THE SYSTEM SHALL devolver `NotificationErrorCode.TIMEOUT`.
3. WHEN el relay rechaza la dirección del destinatario, THE SYSTEM SHALL devolver `NotificationErrorCode.INVALID_RECIPIENT`.
4. THE SYSTEM SHALL clasificar cualquier otro fallo SMTP como `NotificationErrorCode.ADAPTER_ERROR` — el cajón de sastre que el propio enum declara deliberadamente grueso; este change no añade códigos nuevos.

### R4 — "SENT" significa aceptado por el relay, no entregado

**As a** dueño de producto, **I want** que el significado de una fila `SENT` quede dicho por escrito, **so that** nadie lo lea como "llegó a la bandeja del huésped".

Acceptance criteria:

1. WHEN `SMTPEmailAdapter.send` devuelve `ok()`, THE SYSTEM SHALL documentar que significa exactamente "el relay aceptó el mensaje" (2xx en `RCPT`/`DATA`) — no que llegó a un buzón.
2. THE SYSTEM SHALL NOT modelar rebotes, quejas de spam ni confirmaciones de lectura con ninguna columna o estado nuevo — quedan fuera de alcance (ver Out of scope).

### R5 — Proveedor del relay y DNS del dominio

**As a** operador, **I want** un relay transaccional autenticado para el dominio de dev con SPF y DKIM, **so that** el correo no se rechace ni caiga en spam.

Acceptance criteria:

1. THE SYSTEM SHALL enviar a través de una cuenta de relay SMTP transaccional sobre el dominio que sirve dev (`autohostai.digitalsec.work`), alcanzable por SMTP estándar (host/puerto/TLS) — sin SDK propietario nuevo, que es lo que las seis variables `SMTP_*` ya reservadas permiten. La elección concreta de proveedor (Brevo/Resend/SES) es decisión de `/sdd:design`.
2. THE SYSTEM SHALL tener registros SPF y DKIM publicados en el DNS del dominio de dev antes de considerar el change operativo — por Terraform (IaC-first, `steering/infra.md`), no a mano en la consola de Cloudflare.

### R6 — Credenciales en el pipeline de despliegue de dev

**As a** operador desplegando a dev, **I want** que las credenciales del relay lleguen a la VM por el mecanismo de secretos ya existente, **so that** nada se configure a mano.

Acceptance criteria:

1. WHEN el pipeline de despliegue (`app-deploy-dev`) renderiza el `.env` de runtime, THE SYSTEM SHALL leer los secretos `SMTP_*` del OCI Vault **por nombre** — mismo mecanismo que el token del túnel y los secretos de medios (`specs/app-deploy-dev.md`) — y no crear un GitHub Actions secret nuevo.
2. IF un secreto `SMTP_*` configurado no se puede leer del Vault, THEN THE SYSTEM SHALL fallar el paso "Render .env" nombrando la clave ausente, antes de tocar contenedores — mismo contrato fail-fast que `app-deploy-dev` ya tiene para sus otros secretos del Vault.
3. THE SYSTEM SHALL NOT commitear ningún valor real de `SMTP_*` al repo; `.env.example` conserva los seis nombres sin valor.

### R7 — Primer recorrido real: reset de contraseña

**As a** usuario que pide un reset de contraseña, **I want** recibir el correo de verdad, **so that** el primer camino EMAIL→destinatario real (que `notification-channel-routing` ya deja nacer) quede probado de punta a punta.

Acceptance criteria:

1. WHEN se pide un reset de contraseña en dev con SMTP configurado, THE SYSTEM SHALL entregar el correo a través del relay real de punta a punta — el primer recorrido que este change mide en dev (Verification section de `tasks.md`).

## Out of scope

- **Rebotes y quejas del proveedor** (webhook de bounces/complaints): decisión 5 de la nota de roadmap los deja fuera; "entregado" en este change significa "aceptado por el relay" (R4), nunca confirmado en buzón. Change futuro si hace falta.
- **`WhatsApp` real**: es `whatsapp-cloud-adapter`, entrada de roadmap separada.
- **Pantalla de settings/integraciones (FE)**: la retiene `hardening-release`, que ya declaró explícitamente no llevarse las credenciales ni el adaptador.
- **Terraform del provider `github`** para gestionar secrets/variables de Actions como código: es `infra-github-iac`, entrada de roadmap separada. Este change usa el patrón de Vault-por-nombre ya existente, no depende de que ese change aterrice antes.
- **Staging/prod**: `steering/infra.md` es explícito en que esas decisiones son propias y futuras; este change es solo dev.
- **Backoff/pacing de reintentos SMTP**: el comentario de `config.py` sobre `notification_max_attempts` apunta a revisar el backoff "cuando llegue un SMTP real". Este change no añade columna ni pacing nuevo — sigue siendo reintento en cada tick hasta el techo, sin backoff — y deja anotado que ese comentario debe re-apuntar aquí en vez de a `hardening-release`.
- **Reescribir el retry/estado de `notification_logs`**: el mecanismo de "registrar el intento antes de llamar al adaptador" (`use_cases.py`) no cambia; este change solo sustituye qué hay detrás del puerto.

## Affected specs

- `sdd/specs/access-notifications.md` — documenta el adaptador real de `EMAIL`/`CONSOLE`, la selección por presencia de `SMTP_HOST`, y la semántica de `SENT` (R1-R4).
- `sdd/specs/app-deploy-dev.md` — documenta el secreto `SMTP_*` nuevo leído del Vault por nombre y su fail-fast en "Render .env" (R6).
