# Limpieza

## Purpose

Coordina el trabajo de limpieza entre checkouts: crea la tarea cuando el huésped se va, la pone
en manos de una limpiadora, guía su ejecución con un checklist y no la deja cerrar hasta que se
cumple la regla de validación de PRD §11. Sustituye la coordinación operativa que hacía MAGNO
(PRD §26.10, §11) y es lo que convierte `AWAITING_CLEANING` en un estado con continuación.

El *cómo se opera* está en [`docs/cleaning.md`](../../docs/cleaning.md); aquí vive el *qué hace*.

## Requirements

### Plantilla de checklist

- WHEN un `PROPERTY_MANAGER` o `TENANT_OWNER` solicita `POST /api/v1/cleaning-checklist-templates`,
  THE SYSTEM SHALL crear una plantilla del tenant del token y responder `201`.
- THE SYSTEM SHALL validar la estructura de `items` y `required_photos` antes de escribir nada:
  cada elemento con `item_id`/`photo_type` no vacío, único dentro de la plantilla, de como mucho
  100 caracteres y compuesto solo por letras, dígitos, `.`, `_` y `-`; `label` de como mucho 200;
  y `required` booleano estricto. IF no se cumple, THEN THE SYSTEM SHALL responder `422` en el
  envelope de PRD §23.
- THE SYSTEM SHALL persistir **el contenido ya validado** y no el cuerpo recibido, de modo que
  las dos columnas `JSONB` solo puedan contener las claves que el validador conoce.
- THE SYSTEM SHALL acotar el cuerpo a 1 MiB **antes de leerlo**, porque `items` es un array que
  dimensiona el cliente y las cotas de Pydantic corren después de la autenticación.
- WHEN se necesita la plantilla de una propiedad, THE SYSTEM SHALL resolver la activa de esa
  propiedad y, si no existe, la activa del tenant con `property_id` nulo.
- IF hay más de una plantilla activa candidata en el mismo nivel de resolución, THEN THE SYSTEM
  SHALL rechazar la resolución con `409` en lugar de desempatar.
- IF la `property_id` indicada no existe en el tenant del token, THEN THE SYSTEM SHALL responder
  `404`.

**Desviación registrada (`ASSUMPTION`)**: PRD §23 no declara endpoints de plantilla y PRD §27 no
siembra ninguna, pero `cleaning_tasks.checklist_template_id` es `NOT NULL`. Sin estas rutas el
alta automática no tendría a qué apuntar. Convención de desviación de ADR 0005.

### Alta automática al cerrar el checkout

- WHEN `process_checkouts` transiciona una propiedad a `AWAITING_CLEANING`, THE SYSTEM SHALL
  crear una `CleaningTask` en `CREATED` asociada a esa propiedad y a la reserva que originó la
  transición, **en la misma transacción** que la transición y su `TimelineEvent`.
- IF `TenantConfig.auto_create_cleaning_task` es falso O la reserva tiene `cleaning_required`
  falso, THEN THE SYSTEM SHALL transicionar sin crear la tarea.
- IF no hay plantilla resoluble para la propiedad, THEN THE SYSTEM SHALL transicionar sin crear
  la tarea, contarlo en `transitioned_without_task` y registrar `tenant_id` y `property_id`, en
  lugar de fallar la ejecución del resto del tenant.
- THE SYSTEM SHALL derivar `scheduled_start` del checkout **efectivo** y `scheduled_end` de la
  llegada de la siguiente reserva confirmada, anclados a la estancia y **no** al instante en que
  el job se ejecutó: un checkout procesado con retraso conserva su plazo.
- THE SYSTEM SHALL impedir que una reserva tenga dos limpiezas vivas a la vez mediante el índice
  único parcial `uq_cleaning_tasks_live_reservation`, no mediante una comprobación previa.

### Asignación

- WHEN una tarea se crea y el tenant tiene **exactamente una** persona con rol `CLEANER` en
  estado `ACTIVE` que no haya rechazado una tarea de esa reserva, THE SYSTEM SHALL asignársela,
  pasarla a `ASSIGNED` y transicionar la propiedad a `CLEANING_SCHEDULED`.
- IF no hay ninguna limpiadora elegible, O hay más de una activa, THEN THE SYSTEM SHALL dejar la
  tarea en `CREATED` y alertar al manager sin plazo de SLA.
- WHEN un `PROPERTY_MANAGER` solicita `PATCH /api/v1/cleaning-tasks/{id}` con una
  `assigned_cleaner_id`, THE SYSTEM SHALL exigir que esa persona tenga rol `CLEANER` **y** estado
  `ACTIVE` en el tenant del token, y responder `422` con un mensaje constante en caso contrario.
- THE SYSTEM SHALL aceptar la asignación solo desde `CREATED` o `ASSIGNED`, y no SHALL mover la
  propiedad al reasignar una tarea que ya estaba `ASSIGNED`.

### Ciclo de vida de la tarea

- WHEN la limpiadora asignada acepta, THE SYSTEM SHALL pasar la tarea a `ACCEPTED` y registrar
  `accepted_at`, sin mover el estado de la propiedad.
- WHEN la limpiadora asignada rechaza, THE SYSTEM SHALL pasar la tarea a `REJECTED` —terminal, y
  **conservando** `assigned_cleaner_id` como registro de quién rechazó—, transicionar la
  propiedad a `AWAITING_CLEANING` y crear en la misma transacción una tarea de reemplazo en
  `CREATED` sin asignar.
- WHEN la limpiadora asignada inicia, THE SYSTEM SHALL pasar la tarea a `IN_PROGRESS` y
  transicionar la propiedad a `CLEANING_IN_PROGRESS`.
- THE SYSTEM SHALL resolver toda transición de estado de propiedad a través de
  `PropertyStateMachine`, persistiendo su `PropertyStateTransition` y su `TimelineEvent`, y no
  SHALL escribir `current_operational_state` por ninguna otra vía.
- IF una operación se solicita desde un estado de tarea que no la admite, THEN THE SYSTEM SHALL
  responder `409` sin tocar la tarea ni el estado de la propiedad.
- IF el estado de la propiedad no admite la transición —por ejemplo cerrar una limpieza con el
  siguiente huésped ya dentro—, THEN THE SYSTEM SHALL responder `409` y no un error interno.
- THE SYSTEM SHALL registrar en `AuditLog` cada operación iniciada por una persona (creación
  manual, asignación, aceptación, rechazo, inicio, cierre y validación), con su actor y su IP. El
  alta automática del checkout lleva actor `SYSTEM` y está exenta por la regla 9 de
  `steering/security.md`.

### Checklist

- WHEN se solicita `GET /api/v1/cleaning-tasks/{id}/checklist`, THE SYSTEM SHALL devolver los
  ítems **de la plantilla** de la tarea con su estado de completado, de modo que un ítem que
  nadie ha tocado aparece y una completion de un ítem que la plantilla ya no declara no.
- WHEN la limpiadora asignada marca un ítem, THE SYSTEM SHALL registrar la completion con su
  autora y su instante, de forma idempotente y segura ante concurrencia: la escritura es un
  único `INSERT ... ON CONFLICT DO UPDATE`, sin lectura previa.
- IF el `item_id` no pertenece a la plantilla de la tarea, THEN THE SYSTEM SHALL responder `404`.
- IF la tarea no está en `IN_PROGRESS`, THEN THE SYSTEM SHALL responder `409`.

### Cierre y validación

- WHEN la limpiadora asignada cierra la tarea, THE SYSTEM SHALL verificar que todos los ítems
  `required` de la plantilla están completados y que no hay ninguna incidencia `CRITICAL` sin
  resolver en la propiedad, y responder `409` enumerando los ítems que falten.
- WHEN el cierre supera la validación, THE SYSTEM SHALL pasar la tarea a `COMPLETED` con
  `completed_at`, poner `validation_status` en `PASSED` y resolver el estado de la propiedad por
  contexto: `AWAITING_CHECKIN` si hay reserva que llega hoy, `READY_FOR_NEXT_GUEST` si la hay
  futura, `VACANT_READY` si no hay ninguna.
- WHEN un `PROPERTY_MANAGER` valida manualmente una tarea cerrada, THE SYSTEM SHALL registrar
  `validated_by_user_id` y `validated_at` y admitir los veredictos `PASSED`, `FAILED` y `WAIVED`,
  rechazando `PENDING` con `409`.
- THE SYSTEM SHALL dejar `ai_validation_result` sin escribir: la validación automática depende
  de `MockAIAdapter`, que llega con `messaging-ai`.

**La cláusula de fotos de PRD §11 no se aplica todavía.** La regla tiene tres partes y aquí
rigen dos; «todas las fotos `required` subidas» llega con `cleaning-photos-storage`, que trae el
`StorageAdapter` y la subida. **Hasta entonces una limpieza puede cerrarse sin fotos**, y es un
hueco conocido, no un descuido.

### Notificación y SLA

- WHEN una tarea pasa a `ASSIGNED`, THE SYSTEM SHALL escribir una fila de `NotificationLog` con
  `notification_type` `CLEANING_TASK_ASSIGNED`, estado `PENDING`, la tarea en
  `related_type`/`related_id` y `sla_deadline_at` igual a `now + TenantConfig.sla_medium_minutes`.
- WHEN no hay limpiadora a la que asignar, THE SYSTEM SHALL avisar a los managers activos —o al
  owner si no hay ninguno— **sin** plazo de SLA.
- THE SYSTEM SHALL escribir `subject` y `body` conforme al contrato de la regla 11 que fijó
  `celery-jobs`: identificadores y tipo, nunca el contenido de otra fila.
- THE SYSTEM SHALL limitarse a persistir la notificación; la entrega la hace
  `dispatch_notifications`, de `access-notifications`.
- WHEN la limpiadora responde, THE SYSTEM SHALL no escribir una segunda notificación de
  asignación.
- WHEN una limpiadora acepta o rechaza la tarea, THE SYSTEM SHALL anular el plazo de la fila
  `CLEANING_TASK_ASSIGNED` de esa tarea —`cancel_sla_deadline`, que solo pone `sla_deadline_at`
  a nulo— **antes de su único `commit`**, de modo que la respuesta y el plazo cerrado sean una
  escritura o ninguna: una aceptación comiteada con el plazo vivo es exactamente el escalado que
  esto evita.
- THE SYSTEM SHALL conceder esa escritura únicamente a los dos casos de uso que **responden** a
  una asignación, y no a iniciar, cerrar ni validar: para entonces el plazo ya está cerrado.
- IF la tarea no tiene fila de asignación o su plazo ya está cerrado, THEN THE SYSTEM SHALL
  completar la respuesta sin error y sin modificar nada: una tarea creada antes de
  `access-notifications` no tiene plazo que anular, así que cero filas es el caso normal.

**El escalado está vivo desde `access-notifications`.** Este es el primer escritor de
`CLEANING_TASK_ASSIGNED`, cuyo escalado a `SLA_BREACH` para el `PROPERTY_MANAGER` está definido
desde `celery-jobs`; `check_sla_breaches` solo considera candidatos con `status = SENT`, y el
emisor que llegó con `access-notifications` es el primero que escribe ese valor. La cadena
funciona entera: se encola aquí, se entrega allí, y responder cierra el plazo.

### Aislamiento y autorización

- THE SYSTEM SHALL devolver únicamente las tareas y plantillas del tenant del token, con el
  envelope paginado de PRD §23 y las mismas cotas de `page`/`per_page` que `reservations`.
- WHILE el solicitante tiene rol `CLEANER`, THE SYSTEM SHALL devolver y admitir acción **solo**
  sobre las tareas cuya `assigned_cleaner_id` sea la suya. La restricción se deriva del rol
  **persistido** dentro del caso de uso y no hay ningún parámetro de petición que la alcance.
- IF se referencia una tarea, plantilla, propiedad o reserva que existe pero pertenece a otro
  tenant, THEN THE SYSTEM SHALL responder `404` con un cuerpo **idéntico** al de un identificador
  inexistente. Lo mismo aplica a una tarea de este tenant asignada a otra limpiadora, y a una
  tarea sin asignar.
- THE SYSTEM SHALL resolver dentro del tenant `property_id`, `reservation_id` y la plantilla
  antes de crear una tarea: los `INSERT` no pasan por el filtro global de sesión, así que esas
  búsquedas son lo único que impide una fila que apunte fuera.
- THE SYSTEM SHALL demostrar con tests propios que `cleaning_checklist_completions` no es
  alcanzable desde otro tenant. No tiene columna `tenant_id` —scoping transitivo por FK— y
  `tenant_scoped_classes()` selecciona por columna, así que el filtro global **no la cubre** y
  todo su aislamiento recae en el `JOIN` con la tarea padre.
- THE SYSTEM SHALL declarar el permiso de cada endpoint. `EXECUTE_CLEANING_TASKS` es exclusivo
  del `CLEANER`: aceptar, rechazar, iniciar, cerrar y marcar el checklist son de la persona
  asignada, y lo que el manager necesita —crear, asignar y validar— va por
  `MANAGE_CLEANING_TASKS`.
- THE SYSTEM SHALL dejar `cleaning_tasks.notes` y `cleaning_checklist_completions.notes` fuera de
  toda superficie de escritura y de toda respuesta: son texto libre que la tabla de la regla 11
  de `steering/security.md` no enumera, y ampliarla es una decisión de steering.

## Key files

- `backend/app/cleaning/domain/` — `entities.py` (la invariante de PRD §11 en
  `CleaningTask.complete`), `templates.py` (resolución y ambigüedad), `assignment.py`
  (`resolve_auto_assignee`), `value_objects.py` (validación del contenido de plantilla),
  `notifications.py`, `ports.py`, `repositories.py`, `exceptions.py`.
- `backend/app/cleaning/application/use_cases.py` — provisión al checkout y los casos de uso del
  ciclo de vida, el checklist y las plantillas.
- `backend/app/cleaning/infrastructure/repositories.py` — adaptadores; el de completions es el
  único aislamiento de su tabla.
- `backend/app/cleaning/api/` — `tasks_router.py`, `templates_router.py`, `schemas.py`,
  `dependencies.py`, `errors.py`.
- `backend/app/properties/application/use_cases.py` — el punto donde el provisioner se compone
  con la transición del checkout.
- `backend/alembic/versions/d4b0c7a91f38_cleaning_live_task_unique.py` — el índice parcial.
- Tests: `backend/tests/cleaning/`.
