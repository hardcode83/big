# Proposal: notification-writers-gap

## Why

`NotificationType` declara diecisiete tipos (`backend/app/notifications/domain/enums.py`) y **diez no los
escribe nadie**. Uno de los huecos no es funcionalidad pendiente sino un fallo de producto: un huésped puede
reportar una incidencia crítica desde el portal (`POST /api/v1/guest/incident/{token}`) y **no se entera
nadie** — `ReportGuestIncidentUseCase` escribe la incidencia, el `AuditLog` y el `TimelineEvent`, y ninguna
notificación; el manager sólo lo sabe si abre la pantalla. Que `classify_incidents` corra cada cinco minutos
no lo tapa: `ClassifyIncidentUseCase` asigna severidad y dispara la transición de propiedad, y tampoco
notifica.

Fuente: entrada de roadmap `notification-writers-gap` y su nota `sdd/roadmap/notification-writers-gap.md`
(PRD §14 fija los nombres de los tipos y no su semántica). PRD §11 y §12 para los plazos.

**Corrección del censo de la nota, medida contra `backend/app/` el 2026-08-29**: la nota dice «nueve sin
escritor» y son **diez**. Con escritor de producción hay siete —`PASSWORD_RESET_REQUESTED`
(`auth/application/recovery.py`), `CLEANING_TASK_ASSIGNED` y `CLEANING_NO_RESPONSE`
(`cleaning/domain/notifications.py`), `TECHNICIAN_ASSIGNED` y `OWNER_APPROVAL_REQUIRED`
(`maintenance/domain/notifications.py`), `GUEST_ESCALATION` (`messaging/domain/notifications.py`) y
`SLA_BREACH` (`notifications/domain/escalation.py`)—. El décimo huérfano que la nota omitió es
`PRICE_RECOMMENDATION`: `revenue-pricing` está archivado y su `GeneratePriceRecommendationsUseCase` escribe
`TimelineEvent` y `AuditLog` pero ninguna notificación, y ninguna otra entrada del roadmap lo reclama. Entra
aquí por decisión de Jose (2026-08-29).

Los dos tipos que existen fuera del enum —`INCIDENT_REJECTED` y `LEGAL_REGISTRATION_FAILED`, texto libre
sobre la columna `String(100)`— sí tienen escritor y no son parte de este hueco.

## What changes

Cinco escritores de producción nuevos, todos sobre la maquinaria que ya existe (`NotificationLog` +
`NotificationLogRepository` + el `dispatch_notifications` que `access-notifications` dejó drenando
`PENDING → SENT`), sin adapters nuevos, sin migración y sin tocar `NotificationType`:
`INCIDENT_CREATED_CRITICAL`, `INCIDENT_CREATED_HIGH`, `CLEANING_COMPLETED`, `CLEANING_FAILED` y
`PRICE_RECOMMENDATION`. Además, la escalación de `TECHNICIAN_ASSIGNED` deja de emitir `SLA_BREACH` y pasa a
emitir `TECHNICIAN_NO_RESPONSE`, que es el sexto tipo que gana escritor. Al cerrar, los tipos sin escritor
bajan de diez a cuatro (`LOCK_ALERT` y los tres recordatorios al huésped), y un test estructural fija esa
lista para que el censo no se vuelva a pudrir.

## Requirements

### R1 — La incidencia grave avisa al manager

**As a** manager, **I want** enterarme en cuanto una incidencia de mis viviendas es CRITICAL o HIGH, **so
that** un huésped con una fuga no dependa de que yo abra la pantalla.

Acceptance criteria:

1. WHEN una incidencia pasa a `severity = CRITICAL` —por `ClassifyIncidentUseCase` por encima del umbral de
   confianza, o por `TriageIncidentUseCase` cuando un humano la corrige—, THE SYSTEM SHALL escribir una fila
   `NotificationLog` de tipo `INCIDENT_CREATED_CRITICAL` por cada destinatario de R5.1.
2. WHEN una incidencia pasa a `severity = HIGH` por cualquiera de esas dos vías, THE SYSTEM SHALL escribir
   `INCIDENT_CREATED_HIGH` con la misma forma.
3. THE SYSTEM SHALL escribir el aviso **una sola vez por incidencia y severidad**: IF ya existe una fila de
   ese tipo para esa incidencia (`related_type = "incident"`, `related_id = incident.id`), THEN THE SYSTEM
   SHALL no escribir otra. Sin esto, una clasificación seguida de un triage que confirma la severidad avisa
   dos veces, y `TriageIncidentUseCase` admite ser llamado repetidamente.
4. IF una incidencia sube de `HIGH` a `CRITICAL`, THEN THE SYSTEM SHALL escribir el aviso `CRITICAL` aunque
   ya existiera el `HIGH`: son dos hechos distintos y el segundo es el urgente.
5. IF la clasificación queda por debajo del umbral de confianza —la incidencia sigue `OPEN` con su severidad
   por defecto `MEDIUM` y sólo se escribe `ai_classification`—, THEN THE SYSTEM SHALL no escribir ningún
   aviso, porque no hay severidad que anunciar.
6. THE SYSTEM SHALL escribir el aviso dentro de la misma transacción que ya commitean esos dos casos de uso,
   de modo que no exista un estado en el que la incidencia es crítica y el aviso no está.

### R2 — El lazo de la limpieza se cierra en las dos direcciones

**As a** manager, **I want** que me avisen cuando una limpieza se termina, **and as a** limpiadora, **I want**
enterarme si mi limpieza no pasa la validación, **so that** la validación de PRD §11 deje de depender de que
alguien mire la lista.

Acceptance criteria:

1. WHEN `CompleteCleaningTaskUseCase` cierra una tarea, THE SYSTEM SHALL escribir `CLEANING_COMPLETED` a cada
   destinatario de R5.1, con `related_type = "cleaning_task"` y `related_id` la tarea.
2. WHEN `ValidateCleaningTaskUseCase` registra `validation_status = FAILED`, THE SYSTEM SHALL escribir
   `CLEANING_FAILED` **a la limpiadora asignada a la tarea**, no al manager: el manager es quien acaba de
   emitir el veredicto, y el rol `CLEANER` ya tiene `READ_OWN_NOTIFICATIONS`.
3. IF la tarea no tiene limpiadora asignada al fallar la validación, THEN THE SYSTEM SHALL no escribir la
   fila y SHALL registrarlo, sin fallar la respuesta de validación.
4. WHEN `ValidateCleaningTaskUseCase` registra `PASSED` o `WAIVED`, THE SYSTEM SHALL no escribir ninguna
   notificación: `complete()` ya deja `validation_status = PASSED` por sí solo y avisar de cada una sería
   ruido sobre el mismo hecho que ya notificó R2.1.
5. THE SYSTEM SHALL escribir ambas filas dentro de la transacción única que esos casos de uso ya commitean.

### R3 — El silencio del técnico se llama por su nombre

**As a** manager, **I want** que el vencimiento del plazo de un técnico llegue como `TECHNICIAN_NO_RESPONSE`,
**so that** pueda distinguirlo de cualquier otro SLA incumplido sin abrir la fila incumplida.

Acceptance criteria:

1. WHEN vence el `sla_deadline_at` de una notificación `TECHNICIAN_ASSIGNED`, THE SYSTEM SHALL crear el
   escalado con `notification_type = TECHNICIAN_NO_RESPONSE` en lugar de `SLA_BREACH`, conservando
   destinatario (`PROPERTY_MANAGER` activo, con caída al `TENANT_OWNER`) y motivo.
2. THE SYSTEM SHALL dejar la escalación de `CLEANING_TASK_ASSIGNED` intacta como `SLA_BREACH`
   (`sdd/specs/cleaning.md` la fija así): este change cambia sólo la rama del técnico.
3. THE SYSTEM SHALL no añadir maquinaria de SLA nueva: el cambio es el valor de `Escalation.notification_type`
   en `notifications/domain/escalation.py`, que sigue siendo política pura sin reloj ni sesión.
4. THE SYSTEM SHALL no dar plazo propio ni escalación al `TECHNICIAN_NO_RESPONSE` que produce: un escalado que
   escala sería un bucle, y `escalation_for` devuelve `None` para él.
5. IF una fila `SLA_BREACH` ya existe de antes de este change, THEN THE SYSTEM SHALL dejarla como está —no hay
   migración ni reescritura de histórico.

### R4 — La recomendación de precio llega a quien la aprueba

**As a** propietaria, **I want** enterarme de que hay recomendaciones de precio nuevas esperándome, **so that**
la cola de PRD §19 modo 1 no dependa de que entre a mirar.

Acceptance criteria:

1. WHEN una ejecución de `GeneratePriceRecommendationsUseCase` **crea** al menos una recomendación para una
   propiedad, THE SYSTEM SHALL escribir **una sola** fila `PRICE_RECOMMENDATION` por propiedad y ejecución,
   con `related_type = "property"` y `related_id` la propiedad.
2. THE SYSTEM SHALL contar como creaciones sólo las que la sentencia declara insertadas (`written.inserted`),
   nunca las actualizadas: en régimen la ejecución diaria crea una fecha por propiedad y actualiza 59, y la
   primera pasada sobre una propiedad crea 60. Una fila por recomendación serían 60 notificaciones el primer
   día.
3. IF una ejecución no crea ninguna recomendación para una propiedad, THEN THE SYSTEM SHALL no escribir nada
   para ella.
4. THE SYSTEM SHALL dirigirla a **cada `PROPERTY_MANAGER` activo y cada `TENANT_OWNER` activo** del tenant —
   los dos roles que tienen `MANAGE_PRICE_RECOMMENDATIONS` (`auth/domain/policy.py`)—, y no al patrón de R5.1:
   aquí el propietario es quien aprueba y no puede quedar fuera por el hecho de que exista un manager.
5. THE SYSTEM SHALL escribirla tanto en la ejecución del job nocturno (sin actor) como en
   `POST /api/v1/price-recommendations/generate` (con actor): la diferencia es quién lo pidió, no qué ocurre.
6. THE SYSTEM SHALL no dar `sla_deadline_at` a esta fila: nadie ha definido en cuánto tiempo hay que decidir
   un precio.

### R5 — Forma común de los seis escritores

**As a** responsable de seguridad, **I want** que los escritores nuevos no inventen forma propia, **so that**
la regla 11 de `steering/security.md` siga cerrada y el SLA no escale a nadie por accidente.

Acceptance criteria:

1. WHERE un criterio de arriba dice «destinatarios de R5.1», THE SYSTEM SHALL resolverlos como **cada
   `PROPERTY_MANAGER` activo del tenant y, WHERE no haya ninguno, cada `TENANT_OWNER` activo** — el patrón que
   `celery-jobs` fijó y que `guests/application/use_cases.py::_managers` ya implementa. THE SYSTEM SHALL
   reusar ese patrón y no derivar **uno nuevo**.

   **Enmendado en `/sdd:review` (panel de arquitectura, 2026-08-29).** Este criterio decía «no derivar un
   **tercero**», un ordinal que se escribió contando dos implementadores del patrón y que el panel midió
   en tres: el que faltaba es `cleaning/application/use_cases.py::_notify_manager_unassigned`, anterior a
   este change y fuera de su alcance. Lo que el criterio exige no cambia —reusar el resolvedor común en
   vez de escribir el bucle otra vez—, pero enunciarlo con un ordinal lo ataba a un censo que ya estaba
   mal; sin la enmienda, la spec viva heredaría un `SHALL` que se lee como incumplido de partida.
2. IF no hay ni manager ni owner activo, THEN THE SYSTEM SHALL no escribir filas y SHALL registrarlo, sin
   fallar la operación que las habría producido.
3. THE SYSTEM SHALL escribir toda fila nueva con `status = PENDING` y `channel = IN_APP`, y SHALL no intentar
   entregarla: la entrega es de `dispatch_notifications`.
4. THE SYSTEM SHALL componer `subject` y `body` con una plantilla fija más identificadores, y SHALL no leer
   `title`, `description`, `ai_summary`, `assignment_note` ni ningún otro texto libre de la entidad
   notificada — el contrato de la regla 11 que `celery-jobs` fijó para esas dos columnas.
5. THE SYSTEM SHALL escribir las seis filas **sin `sla_deadline_at`**. Motivo medido: `dispatch_notifications`
   ya mueve `PENDING → SENT` cada minuto y `list_sla_breach_candidates` exige `SENT`, así que un plazo nuevo
   produciría escalaciones reales desde el primer minuto contra tipos para los que `escalation_for` devuelve
   `None` — la fila se marcaría incumplida sin avisar a nadie.
6. THE SYSTEM SHALL construir cada fila en un builder puro del dominio correspondiente, al modo de
   `cleaning/domain/notifications.py` y `maintenance/domain/notifications.py`, testeable sin sesión.

### R6 — El censo deja de poder pudrirse

**As a** quien mantenga esto, **I want** un test que falle cuando un tipo pierde o gana escritor, **so that**
el próximo censo no se haga a mano y salga mal, como salió éste.

Acceptance criteria:

1. THE SYSTEM SHALL incluir un test que enumere **todos** los miembros de `NotificationType` y afirme, contra
   una lista literal declarada en el propio test, cuáles tienen escritor de producción y cuáles no.
2. THE SYSTEM SHALL declarar en esa lista exactamente cuatro tipos sin escritor al cerrar este change —
   `LOCK_ALERT`, `CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H`, `CHECKOUT_REMINDER`— y THE SYSTEM SHALL fallar
   si el conjunto medido difiere en cualquier dirección.
3. THE SYSTEM SHALL medir el conjunto sobre `backend/app/` excluyendo `notifications/domain/enums.py`, y
   SHALL nombrar en el propio test los ficheros y las **dos** formas exactas que cuentan como escritor, con el
   *callee* fijado en ambas, de modo que la comprobación no dependa de que nadie escriba el nombre en un
   comentario:
   - una llamada cuyo callee es literalmente `NotificationLog` con
     `notification_type=NotificationType.<X>.value`; y
   - una llamada cuyo callee es literalmente `Escalation` con `notification_type=NotificationType.<X>`
     (sin `.value`), en `notifications/domain/escalation.py`.

   **Enmendado en `/sdd:design` (D9), tras medir el AST del árbol el 2026-08-29.** Este criterio decía
   antes «`notification_type=NotificationType.<X>.value` en un builder o caso de uso», y esa forma sobra y
   falta a la vez: casa con **cuatro** llamadas a `cancel_sla_deadline` —`cleaning/application/use_cases.py:730`,
   `maintenance/application/use_cases.py:1729`, `:1901` y `:1979`— que borran un plazo y no escriben nada, de
   modo que `CLEANING_TASK_ASSIGNED` y `TECHNICIAN_ASSIGNED` contarían como escritos aunque desapareciesen sus
   builders; y no casa con `SLA_BREACH`, cuya fila compone `_escalation_row` desde el `_POLICY` de
   `escalation.py` (`notification_type=escalation.notification_type.value`, sin literal). Con la forma
   anterior, R6.2 tendría que declarar seis huérfanos y no cuatro, contradiciéndose a sí misma.
4. WHEN un miembro nuevo entra en `NotificationType` sin aparecer en ninguna de las dos listas, THEN THE
   SYSTEM SHALL fallar el test.

## Out of scope

- **Los tres recordatorios al huésped** (`CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H`, `CHECKOUT_REMINDER`):
  van a `guest-scheduled-comms`. No son un escritor que falta sino un job que no existe —`send_checkin_reminders`
  no tiene código y `scheduler/schedule.py` lo dice por escrito— y no tienen canal al huésped hasta que lo haya.
- **`LOCK_ALERT`**: necesita una superficie de importación de cerraduras que no existe
  (`maintenance/api/incidents_router.py` lo declara «out of scope for want of an import surface»). Este change
  no la inventa; sólo deja constancia en R6.2 de que ese tipo sigue huérfano.
- **`PhoneAdapter` y la rama `TECHNICIAN_ASSIGNED + CRITICAL` de PRD §14**: sigue sin puerto ni implementación
  (`specs/access-notifications.md:533`). R3 renombra el tipo del escalado, no lo convierte en una llamada.
- **Entrega real por email o WhatsApp**: es de `notification-channel-routing` + `smtp-delivery-adapter`. Aquí
  todo nace `IN_APP`.
- **La bandeja que las muestra**: es `notifications-inbox-web`, en vuelo en paralelo. Este change no toca
  frontend ni ficheros de `locales/`. **Coordinación**: introduce seis `notification_type` que hoy no llegan
  nunca al listado, así que la bandeja necesitará etiqueta es/en para cada uno; si `notifications-inbox-web`
  mergea antes, la etiqueta que falte es suya, no un defecto de este change.
- **Cambiar la semántica de `CLEANING_NO_RESPONSE`**, hoy escrita cuando el auto-asignador no encuentra
  limpiadora (`Cleaning unassigned`) y no cuando una limpiadora calla. La asimetría con R3 se reconoce y se
  deja como está: reinterpretarla reescribiría un `SHALL` vivo de `specs/cleaning.md` sin que nadie lo haya
  pedido.
- **Migración o reescritura de filas existentes** de cualquier tipo.

## Affected specs

- `sdd/specs/access-notifications.md` — hogar del censo de tipos y del emisor; cambia de diez huérfanos a cuatro.
- `sdd/specs/maintenance.md` — R1 (avisos de severidad en clasificación y triage) y R3 (tipo del escalado del técnico).
- `sdd/specs/cleaning.md` — R2 (completado y validación fallida).
- `sdd/specs/revenue-pricing.md` — R4 (aviso por propiedad y ejecución).
- `sdd/specs/celery-jobs.md` — R3: su bloque «SLA vencido» dice «la notificación de escalado que corresponda a
  su tipo» sin nombrarlo, así que se matiza, no se contradice.
