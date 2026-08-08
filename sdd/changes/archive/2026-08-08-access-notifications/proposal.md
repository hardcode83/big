# Proposal: access-notifications

## Why

Tres capas operativas del MVP están hoy **construidas a medias y sin motor**: el dominio
`access` tiene entidad, enums y tabla (`domain-foundation-ops`) pero ni repositorio ni casos de
uso ni API; `notifications` tiene tabla, tipos, política de escalado y el job
`check_sla_breaches` (`celery-jobs`) pero **nadie envía nada**; y el registro legal de huéspedes
(PRD §17) tiene columnas (`guests.legal_registration_status`, `document_number_encrypted`) y un
evento de timeline (`LEGAL_REGISTRATION_SUBMITTED`) sin nada que los mueva.

La consecuencia medible ya está documentada en `sdd/specs/cleaning.md:133-138`: **el escalado de
SLA está inerte**. `list_sla_breach_candidates` exige `status = SENT`
(`backend/app/notifications/infrastructure/repositories.py:37`) y ningún código marca `SENT`, así
que `cleaning` escribe plazos que nadie puede incumplir. Este change trae el emisor y con él el
derecho a tocar `status` — y la obligación heredada de cerrar el plazo cuando la limpiadora
responde, recortada en el `/sdd:review` de `cleaning` del 2026-08-06 precisamente por no existir
el emisor.

Fuentes: PRD §14 (notificaciones y SLA), §15 (accesos), §17 (SES.Hospedajes), orden de desarrollo
§26.13-14; nota de roadmap `sdd/roadmap/access-notifications.md`; ADR 0006 decisión 4 (Chekin como
proveedor SES recomendado).

## What changes

Después de este change existen, en backend: (1) el **módulo de acceso** completo —
`AccessProviderAdapter` con `ManualAccessAdapter` y `MockAccessAdapter`, repositorio, casos de uso
y API para que un operador registre el código, lo marque como gestionado por GrinPass o confirme
su entrega, con los cuatro `TimelineEvent` de PRD §15; (2) el **emisor de notificaciones** —
`NotificationAdapter` con `ConsoleEmailAdapter`, `MockWhatsAppAdapter` e in-app, y un job Celery
que drena las filas `PENDING` a `SENT`/`FAILED` registrando `attempts` y `last_error`, lo que
enciende por primera vez el escalado de SLA que ya estaba definido; (3) el **cierre del SLA de
asignación de limpieza**, heredado de `cleaning` R6.4; y (4) la **capa operativa de
SES.Hospedajes** — `SESHospedajesAdapter` con `MockSESHospedajesAdapter` y la máquina de estados
`PENDING_GUEST_DATA → READY_TO_SUBMIT → SUBMITTED|FAILED` con submit manual desde la API, sin
submission real (PRD §29 lo excluye del MVP).

**Sobre el tamaño**: la entrada de roadmap agrupa dos changes del PRD (§26.13 y §26.14) más §17,
y esto se declara honestamente como **L**, no M. Se mantiene como un solo change porque las tres
piezas comparten el mismo esqueleto —puerto + adapter mock + transiciones de estado + timeline— y
porque `guest-portal-api` y `field-apps` dependen de la entrada **como unidad**; partirla dejaría
un `needs:` que no se puede satisfacer a medias. Si el diseño demuestra lo contrario, R6-R7
(SES.Hospedajes) son el corte natural.

## Requirements

### R1 — Un AccessRecord por reserva confirmada

**Como** manager, **quiero** que cada reserva confirmada tenga desde el primer momento un registro
de acceso en estado pendiente, **para** ver de un vistazo qué reservas todavía no tienen resuelto
el acceso del huésped.

Criterios de aceptación:

1. WHEN una reserva pasa a estado confirmado y no tiene ya un `AccessRecord`, THE SYSTEM SHALL
   crear uno con `status = PENDING`, `provider` y `created_mode` derivados de la configuración de
   la propiedad, y `property_id`/`reservation_id`/`tenant_id` los de la reserva.
2. WHEN se crea ese registro, THE SYSTEM SHALL escribir un `TimelineEvent` de tipo
   `ACCESS_CODE_PENDING` asociado a la propiedad y a la reserva.
3. IF la reserva ya tiene un `AccessRecord`, THEN THE SYSTEM SHALL no crear un segundo y no
   escribir un segundo evento de timeline.
4. WHEN una reserva se cancela, THE SYSTEM SHALL dejar su `AccessRecord` en `REVOKED` y escribir el
   evento de timeline correspondiente.

### R2 — Registro del acceso por el operador (`AccessProviderAdapter`)

**Como** manager, **quiero** registrar manualmente el código de acceso, o declarar que GrinPass ya
lo gestionó, **para** poder comunicar al huésped cómo entra sin que AutoHostAI controle la
cerradura.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer un puerto `AccessProviderAdapter` con `get_access_status`,
   `create_manual_access` y `mark_external_managed` (PRD §15), con dos implementaciones:
   `ManualAccessAdapter` (el operador introduce el código) y `MockAccessAdapter` (genera un código
   demo enmascarado).
2. WHEN el operador registra un código manualmente, THE SYSTEM SHALL pasar el registro a
   `MANUAL_ADDED`, persistir **solo** la forma enmascarada en `code_masked`, y escribir
   `ACCESS_CODE_MANUAL_ADDED` en el timeline.
3. WHEN el operador declara que el acceso lo gestiona el proveedor externo, THE SYSTEM SHALL pasar
   el registro a `CREATED_EXTERNAL` con `provider = EXTERNAL_MANAGED` y escribir
   `ACCESS_CODE_CREATED_EXTERNAL`.
4. WHEN el operador confirma que el huésped recibió las instrucciones, THE SYSTEM SHALL pasar el
   registro a `DELIVERED` y escribir `ACCESS_CODE_DELIVERED`.
5. IF se solicita una transición que no sale del estado actual (por ejemplo `DELIVERED` desde
   `PENDING`), THEN THE SYSTEM SHALL rechazarla con `409` y no escribir ningún evento.
6. THE SYSTEM SHALL no persistir, registrar en logs ni devolver por API el código de acceso
   completo en ningún punto: solo `code_masked`.

### R3 — API de accesos con aislamiento y RBAC

**Como** manager, **quiero** consultar y operar los accesos desde la API con el mismo contrato que
el resto del backend, **para** que el frontend y las apps de campo puedan construirse encima.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer endpoints para listar accesos de un tenant (con el envelope paginado
   de PRD §23 y las mismas cotas de `page`/`per_page` que `reservations`), leer el de una reserva y
   ejecutar las transiciones de R2.
2. THE SYSTEM SHALL devolver únicamente registros del tenant del token.
3. IF se referencia un acceso, reserva o propiedad que existe pero pertenece a otro tenant, THEN
   THE SYSTEM SHALL responder `404` con un cuerpo **idéntico** al de un identificador inexistente.
4. WHILE el solicitante tiene un rol sin permiso de escritura sobre accesos, THE SYSTEM SHALL
   admitir la lectura y rechazar las transiciones con `403`.

### R4 — El emisor de notificaciones (`NotificationAdapter`)

**Como** sistema, **quiero** entregar las notificaciones que los demás módulos encolan, **para**
que las alertas lleguen a su destinatario y el enforcement de SLA deje de estar inerte.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer el puerto `NotificationAdapter` de PRD §14
   (`send(recipient_contact, subject, body, channel) -> NotificationResult`) con las
   implementaciones de la tabla de canales MVP: `ConsoleEmailAdapter` en dev, `MockWhatsAppAdapter`
   e in-app.
2. WHEN el job de envío encuentra una fila de `NotificationLog` con `status = PENDING`, THE SYSTEM
   SHALL invocar el adapter del canal de la fila e incrementar `attempts`.
3. WHEN la entrega tiene éxito, THE SYSTEM SHALL pasar la fila a `SENT` y fijar `sent_at`.
4. IF la entrega falla, THEN THE SYSTEM SHALL dejar la fila en `PENDING` y registrar el motivo en
   `last_error` en forma **estructurada** —código y tipo de error, nunca el `subject`/`body` que no
   se pudo enviar— reintentando hasta un máximo configurado, tras el cual la fila pasa a `FAILED`.
5. IF no existe adapter para el canal de una fila, THEN THE SYSTEM SHALL dejarla en `SKIPPED` con
   el motivo en `last_error` y no reintentarla indefinidamente.
6. THE SYSTEM SHALL procesar cada fila una sola vez por ejecución y ser idempotente frente a
   ejecuciones solapadas del job, sin marcar `SENT` una fila cuya entrega no confirmó el adapter.
7. THE SYSTEM SHALL escoper cada ejecución por tenant y no entregar a un `recipient_contact` que no
   pertenezca al tenant de la fila.

### R5 — Cierre del SLA al responder una asignación (heredado de `cleaning` R6.4)

**Como** manager, **quiero** que aceptar o rechazar una limpieza cierre el plazo pendiente,
**para** no recibir un escalado por una asignación que ya fue respondida en segundos.

Criterios de aceptación:

1. WHEN una limpiadora acepta o rechaza una tarea de limpieza, THE SYSTEM SHALL cerrar el plazo de
   la fila `CLEANING_TASK_ASSIGNED` asociada a esa tarea, de modo que deje de ser candidata para
   `check_sla_breaches`.
2. THE SYSTEM SHALL ampliar `NotificationLogRepository` con la vía mínima necesaria para ese cierre
   —hoy `mark_breached` está acotado a propósito y no lo permite— sin abrir la escritura de
   `subject`, `body`, `recipient_contact` ni `status` a sus llamantes.
3. IF la tarea no tiene fila de asignación, o su plazo ya está cerrado o ya incumplido, THEN THE
   SYSTEM SHALL completar la respuesta sin error y sin modificar la fila.
4. WHEN el plazo se cierra, THE SYSTEM SHALL no producir ningún escalado `SLA_BREACH` para esa
   tarea en ejecuciones posteriores del job.

### R6 — Capa operativa de SES.Hospedajes

**Como** manager, **quiero** llevar el registro legal del huésped por sus estados y poder enviarlo,
**para** que cuando existan credenciales solo haya que enchufar el adapter real.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer el puerto `SESHospedajesAdapter` de PRD §17 (`submit_guest`,
   `get_submission_status`) con una única implementación `MockSESHospedajesAdapter` que simula una
   submission exitosa y está marcada `EXTERNAL_DEPENDENCY`.
2. WHEN una reserva se confirma, THE SYSTEM SHALL fijar su `legal_registration_status` a
   `PENDING_GUEST_DATA`.
3. WHEN el huésped asociado tiene los ocho datos mínimos de PRD §17 (`full_name`, `nationality`,
   `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`, `check_in_date`,
   `check_out_date`), THE SYSTEM SHALL pasar el estado a `READY_TO_SUBMIT`.
4. WHEN un rol autorizado ejecuta el envío sobre una reserva en `READY_TO_SUBMIT`, THE SYSTEM SHALL
   invocar el adapter, pasar el estado a `SUBMITTED` y escribir un `TimelineEvent`
   `LEGAL_REGISTRATION_SUBMITTED`.
5. IF el adapter devuelve un fallo, THEN THE SYSTEM SHALL pasar el estado a `FAILED`, encolar una
   notificación al manager y no escribir el evento de submission.
6. IF se solicita el envío sobre una reserva que no está en `READY_TO_SUBMIT`, THEN THE SYSTEM
   SHALL rechazarlo con `409` sin invocar el adapter.

### R7 — Protección del dato de documento en el camino legal

**Como** responsable del tratamiento, **quiero** que el número de documento no salga nunca de su
sitio, **para** cumplir lo que PRD §17 y `steering/security.md` exigen sobre el dato más sensible
del sistema.

Criterios de aceptación:

1. THE SYSTEM SHALL persistir `document_number` cifrado en reposo y no devolverlo nunca en
   listados: en ellos solo viaja `document_status`.
2. WHILE el solicitante no tiene rol `SUPER_ADMIN`, `TENANT_OWNER` o `PROPERTY_MANAGER`, THE SYSTEM
   SHALL no devolver el documento completo en ningún endpoint.
3. WHEN un usuario accede al documento completo, THE SYSTEM SHALL registrar el acceso en
   `AuditLog` con actor, tenant, huésped y momento.
4. THE SYSTEM SHALL no incluir `document_number`, fecha de nacimiento ni ningún dato de documento
   en `notification_logs.subject`, `body` ni `last_error`, ni en logs de aplicación.

## Out of scope

- **Submission real a SES.Hospedajes** y la integración con Chekin: PRD §29 lo excluye del MVP y
  ADR 0006 decisión 4 exige cerrar antes DPA, política de retención y verificación de salida de
  PII, además de la regla 12 de `steering/security.md` para sus webhooks
  (`PoliceRegistration.created|complete|error|retry_error`). Aquí solo vive el mock. Debe salir a
  su propia entrada de roadmap cuando se decida integrarlo.
- **Captura de los datos del huésped por el propio huésped** (token web, formulario de check-in):
  es `guest-portal-api`, que declara `needs: access-notifications` precisamente por esto. Aquí los
  datos se introducen por el operador o llegan del PMS.
- **Frontend**: pantallas de accesos, bandeja de notificaciones y formularios de registro legal son
  `field-apps` y `dashboard-web`.
- **SMTP real y WhatsApp real**: los adapters de producción llegan con `hardening-release`
  (settings + integraciones). Aquí `ConsoleEmailAdapter` y `MockWhatsAppAdapter`.
- **`PhoneAdapter`** y la rama `TECHNICIAN_ASSIGNED + CRITICAL` de PRD §14: no existe puerto ni
  implementación y `escalation.py:44` deja constancia. Sigue escalando al manager.
- **Lógica basada en apertura de puerta** (`DoorSensorAdapter`, `DOOR_OPENED_SENSOR`): PRD §15 y
  §29 la excluyen explícitamente.
- **Rellenar las catorce escalaciones que `escalation.py` deja en `None`**: cada tipo recibe su
  escalado en el change que le da un `sla_deadline_at`, no aquí.

## Affected specs

- `sdd/specs/access-notifications.md` — *(no existe aún — se creará al archivar)*: accesos,
  emisión de notificaciones y capa operativa de SES.Hospedajes.
- `sdd/specs/cleaning.md` — se modifica: la sección «Notificación y SLA» declara hoy que el
  escalado «queda inerte hasta `access-notifications`» y que cerrar el SLA al responder viaja con
  este change (líneas 133-138). Al archivar deja de ser cierto y R5 lo sustituye.
- `sdd/specs/celery-jobs.md` — se modifica: `check_sla_breaches` pasa de no tener candidatos
  posibles a tenerlos, y se suma el nuevo job de envío.
- `sdd/specs/domain-foundation-ops.md` — se modifica si el diseño necesita tocar el esquema de
  `access_records` o `notification_logs` (por ejemplo para el cierre de plazo de R5.2).
- `sdd/specs/reservations.md` — se modifica: confirmar una reserva pasa a tener dos efectos nuevos
  (R1.1 y R6.2).
- `sdd/specs/timeline-state-machine.md` — se modifica: los cinco eventos de acceso y registro legal
  dejan de ser enums sin escritor.
