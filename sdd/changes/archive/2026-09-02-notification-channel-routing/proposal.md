# Proposal: notification-channel-routing

## Why

`TenantConfig.notification_email_enabled` (por defecto `True`) y `notification_whatsapp_enabled`
(por defecto `False`) se guardan, se parchean por `PATCH /api/v1/tenants/{id}`, están en
`AUDITABLE_FIELDS` y tienen tests de mutación — **y no los lee nadie**. Medido en este árbol
(2026-08-31): 12 y 16 apariciones respectivamente, todas dentro de `tenants/`, `audit/`, la
migración baseline y los tests de tenants. Ni un escritor de notificaciones ni el emisor los
consultan. Un barrido sobre `sdd/specs/` da el mismo resultado por el otro lado: **los dos flags no
aparecen en ninguna spec**, así que el conmutador tampoco tiene hoy requisito que lo gobierne.

La consecuencia es la que motiva la entrada: los 15 sitios que escriben una fila fijan el canal a
pelo — **13 fijan `NotificationChannel.IN_APP`** (`cleaning` ×4, `maintenance` ×5, `guests`,
`messaging`, `pricing`, `notifications/application/use_cases.py`) y **2 fijan `EMAIL`**
(`auth/application/recovery.py`, la excepción declarada del reset de contraseña). Por tanto
ninguna fila nace con `EMAIL` o `WHATSAPP` fuera de la recuperación de contraseña, y de ahí se sigue
lo que hace urgente esta pieza: **un adapter SMTP real o uno de WhatsApp real no tendría hoy quién
lo invocase**. `smtp-delivery-adapter`, `whatsapp-cloud-adapter` y `guest-scheduled-comms` la
declaran `needs:` por eso.

Fuente: `sdd/roadmap/notification-channel-routing.md` (la nota de la entrada) y PRD §14. El censo
de la nota decía «ocho de los diez, en cinco ficheros»; la cifra de arriba es la remedida sobre este
árbol, mayor porque `notification-writers-gap` (archivado el 2026-08-30) añadió escritores y porque
`pricing/domain/notifications.py` no estaba en la lista original.

## What changes

Un **resolutor de canales** en el dominio de notificaciones que, dado el tenant y el destinatario,
devuelve el conjunto de canales por los que ese aviso debe salir: `IN_APP` siempre, más `EMAIL` si
`notification_email_enabled`, más `WHATSAPP` si `notification_whatsapp_enabled`, y **descartando
todo canal para el que el destinatario no tenga contacto**. Los escritores dejan de fijar el canal a
mano y escriben una fila por canal resuelto. Como `GET /api/v1/notifications` no filtra hoy por
canal, la bandeja de `notifications-inbox-web` se acota a `channel = IN_APP` para que la campana no
duplique. El plazo de SLA queda en una sola fila por aviso.

Los 17 tipos viajan igual: no se introduce política por tipo ni por rol ni preferencia por usuario.
El único conmutador es el par de flags que el tenant ya tiene.

## Requirements

### R1 — El canal sale de la configuración del tenant, no del código

**Como** propietaria de un tenant, **quiero** que el conmutador de canales que ya edito y que queda
auditado decida de verdad por dónde salen los avisos, **para que** activar el email o WhatsApp tenga
un efecto observable en vez de ser un campo muerto.

Criterios de aceptación:

1. WHEN el emisor resuelve los canales de un aviso operativo, THE SYSTEM SHALL devolver `IN_APP`
   siempre, y SHALL añadir `EMAIL` IF `notification_email_enabled` del tenant es verdadero, y SHALL
   añadir `WHATSAPP` IF `notification_whatsapp_enabled` del tenant es verdadero.
2. THE SYSTEM SHALL incluir `IN_APP` en el conjunto resuelto con independencia del valor de los dos
   flags: no existe configuración que apague la bandeja, que es el registro que la campana lee.
3. THE SYSTEM SHALL resolver los canales con **un solo** servicio de dominio, alcanzable por los
   cinco módulos que hoy escriben filas (`cleaning`, `maintenance`, `guests`, `messaging`,
   `pricing`) y por `notifications/application/use_cases.py`, sin que ninguno gane una arista nueva
   hacia otro dominio — la misma restricción de forma que `RoleRecipients` cumple para los
   destinatarios (`specs/access-notifications.md`, «El censo de escritores»).
4. THE SYSTEM SHALL aplicar la misma resolución a los 17 miembros de `NotificationType`, sin tabla
   por tipo ni por rol destinatario.
5. WHERE el tenant no tenga fila de configuración recuperable, THE SYSTEM SHALL resolver a `IN_APP`
   únicamente, y SHALL registrarlo.

### R2 — Una fila por canal resuelto

**Como** operador, **quiero** que cada canal por el que sale un aviso tenga su propia fila con su
propio estado de entrega, **para que** «entregado por in-app pero fallido por email» sea un hecho
consultable y no una ambigüedad.

Criterios de aceptación:

1. WHEN un escritor produce un aviso cuyo conjunto resuelto tiene N canales, THE SYSTEM SHALL
   escribir N filas en `notification_logs`, idénticas en `notification_type`, `recipient_user_id`,
   `related_type`, `related_id`, `subject` y `body`, y distintas en `channel`.
2. THE SYSTEM SHALL escribir cada una de esas filas con `status = PENDING` y SHALL no intentar
   entregarla en el momento de escribirla: la entrega sigue siendo de `dispatch_notifications`.
3. THE SYSTEM SHALL fijar `recipient_contact` al contacto que corresponde al canal de esa fila:
   `User.email` para `EMAIL` e `IN_APP`, `User.phone` para `WHATSAPP`.
4. THE SYSTEM SHALL dejar de fijar `NotificationChannel.IN_APP` como literal en los 13 sitios que lo
   hacen hoy, y SHALL mantener intacta la excepción declarada de `auth/application/recovery.py`
   (R6 abajo).
5. THE SYSTEM SHALL incluir un test que enumere los sitios de escritura sobre el **AST** de
   `backend/app/`, con la forma y el alcance exactos que ya fija `specs/access-notifications.md`, y
   SHALL fallar si aparece un literal de canal fuera de la lista blanca cerrada que design.md D6
   fija: el resolutor y el fan-out (que deciden y consumen el canal), la excepción de recuperación,
   el registro de adapters, el canal de conversación de `messaging`, cada sitio cuyo único literal
   es el valor por defecto del parámetro `channel: NotificationChannel = IN_APP` (los cuatro
   módulos de builders, los casos de uso y ambos repositorios de `notifications/`), y el propio
   guard. Trece sitios en total — no solo el resolutor y la excepción — porque cada default de
   parámetro nuevo que este change introduce es él mismo un lugar que nombra el enum.

### R3 — Un canal sin contacto no produce fila

**Como** operador, **quiero** que no se escriban filas que nadie puede entregar, **para que** la
tabla no acumule avisos muertos ni reintentos por un dato que no va a cambiar solo.

Criterios de aceptación:

1. IF `WHATSAPP` está en el conjunto resuelto y `User.phone` del destinatario es `NULL` o vacío,
   THEN THE SYSTEM SHALL excluir `WHATSAPP` del conjunto y SHALL no escribir fila para ese canal.
2. IF `EMAIL` está en el conjunto resuelto y el destinatario no tiene email utilizable, THEN THE
   SYSTEM SHALL excluir `EMAIL` del conjunto y SHALL no escribir fila para ese canal.
3. THE SYSTEM SHALL registrar cada exclusión por contacto ausente con el tipo de aviso y el canal
   descartado, y SHALL no registrar el valor del contacto ni `subject` ni `body` (regla 11 de
   `steering/security.md`).
4. THE SYSTEM SHALL no fallar la operación de negocio que produjo el aviso por una exclusión de
   canal, y SHALL escribir de todos modos la fila `IN_APP`.
5. THE SYSTEM SHALL no degradar en silencio a otro canal cuando el elegido queda excluido: el
   precedente vinculante es `messaging/infrastructure/channels.py`, que argumenta por escrito por
   qué los dos canales de OTA no tienen adapter en vez de tener un no-op — *«it would show an
   operator a delivered message the guest never received»*.

### R4 — El plazo de SLA vive en una sola fila

**Como** manager, **quiero** un solo escalado por incumplimiento, **para que** una limpieza tardía
no genere dos `SLA_BREACH` por el mismo hecho.

Criterios de aceptación:

1. WHEN un aviso con escalado definido se abanica en N filas, THE SYSTEM SHALL fijar
   `sla_deadline_at` **únicamente** en la fila `IN_APP`, y SHALL escribir las demás con
   `sla_deadline_at = NULL`.
2. THE SYSTEM SHALL preservar el comportamiento de `cancel_sla_deadline(tenant_id, related_type,
   related_id, notification_type)`, que casa sin filtrar por canal y por tanto cierra el plazo de
   todas las filas hermanas en una sola llamada.
3. THE SYSTEM SHALL mantener que `list_sla_breach_candidates` devuelva como mucho una candidata por
   aviso, verificado con un test que abanique un `CLEANING_TASK_ASSIGNED` y un
   `TECHNICIAN_ASSIGNED` — los dos únicos tipos que hoy fijan `sla_deadline_at` — con los dos flags
   del tenant activos.
4. THE SYSTEM SHALL seguir escribiendo sin `sla_deadline_at` toda fila cuyo tipo no tenga escalado
   definido, en cualquier canal (regla vigente de `specs/access-notifications.md`).

### R5 — La bandeja sigue siendo la bandeja

**Como** usuario de la campana, **quiero** ver cada aviso una sola vez, **para que** activar el
email en mi tenant no me duplique las notificaciones en la interfaz.

Criterios de aceptación:

1. THE SYSTEM SHALL acotar `GET /api/v1/notifications` a las filas con `channel = IN_APP`, además
   del acotamiento por usuario del token que ya aplica.
2. THE SYSTEM SHALL acotar igualmente el contador de no leídas a `channel = IN_APP`, de forma que
   el número de la campana y la longitud de la bandeja sigan siendo consistentes.
3. THE SYSTEM SHALL conservar sin cambios el envelope paginado, el orden, el parámetro `unread`, el
   conjunto de campos publicados y el acuse de lectura sobre `read_at`.
4. WHEN un tenant activa `notification_email_enabled`, THE SYSTEM SHALL no alterar el número de
   elementos que la bandeja devuelve para un mismo conjunto de avisos.

### R6 — Lo que ya resolvía bien no se toca

**Como** responsable del cambio, **quiero** que la recuperación de contraseña siga entregando como
hoy, **para que** una refactorización de canal no rompa el único camino síncrono del sistema.

Criterios de aceptación:

1. THE SYSTEM SHALL mantener `auth/application/recovery.py` escribiendo `EMAIL` y entregando
   síncronamente, sin pasar por `PENDING` ni por el resolutor — la excepción que
   `specs/access-notifications.md` ya declara.
2. THE SYSTEM SHALL no modificar `adapter_registry()`: `PUSH` sigue ausente a propósito y un canal
   sin adapter sigue produciendo `SKIPPED` sin consumir intentos (R4.5 vigente).
3. THE SYSTEM SHALL no alterar el comportamiento de `messaging/infrastructure/channels.py`, que
   gobierna respuestas a conversaciones y no filas de `notification_logs`.

## Out of scope

- **Adapters reales de entrega.** `EMAIL` sigue resolviendo a `ConsoleEmailAdapter` y `WHATSAPP` a
  `MockWhatsAppAdapter`. El SMTP real es `smtp-delivery-adapter`; el WhatsApp real es
  `whatsapp-cloud-adapter`. Este change les da el invocador que hoy no tienen, nada más.
- **Política de canal por tipo de notificación o por rol destinatario.** Decidido el 2026-08-31: los
  17 tipos viajan igual. Si más adelante hace falta que un `SLA_BREACH` y un
  `CLEANING_TASK_ASSIGNED` viajen distinto, es una entrada propia.
- **Preferencia de canal por usuario.** No hay columna y no se crea; los flags son del tenant.
- **`User.preferred_language` en el cuerpo del aviso.** `subject`/`body` se siguen escribiendo en
  inglés y para un operador. La nota de roadmap lo menciona como contexto; traducir los avisos es
  trabajo de i18n de notificaciones, no de enrutado de canal.
- **`PUSH`.** Sin adapter y sin escritor; sigue fuera por la misma razón que hoy.
- **Pantalla de configuración del conmutador.** Los flags ya entran por `PATCH /api/v1/tenants/{id}`;
  la superficie de ajustes es de `hardening-release`.
- **Notificaciones programadas al huésped.** Son `guest-scheduled-comms`, que declara este change
  como `needs:`.

## Affected specs

- `sdd/specs/access-notifications.md` — **modificar**. Es el hogar del emisor y contiene el `SHALL`
  que este change contradice de frente: *«THE SYSTEM SHALL escribir toda fila de `notification_logs`
  que nazca en el emisor con `status = PENDING` y `channel = IN_APP`»* (sección «El censo de
  escritores, y la forma común de todos ellos»). Pasa a ser una fila por canal resuelto. También se
  amplía la sección «La bandeja in-app» con el acotamiento por `channel = IN_APP` (R5) y el censo de
  escritores por AST con la forma nueva (R2.5).
- `sdd/specs/notifications-inbox-web.md` — **modificar**. Documenta el contrato de campana y listado
  que R5 acota; hoy no menciona el canal en absoluto, y después de este change el filtro es parte
  del contrato.
- `sdd/specs/celery-jobs.md` — **modificar**. Es el hogar del escalado de SLA; R4 fija que el plazo
  vive en la fila `IN_APP` y que sigue habiendo como mucho una candidata por aviso.
- `sdd/specs/auth-tenancy.md` — **modificar**. Es el hogar de `TenantConfig` y hoy no dice nada de
  los dos flags. Aquí adquieren por primera vez un requisito que declare qué significan.
