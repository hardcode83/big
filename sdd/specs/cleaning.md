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

- WHEN la limpiadora asignada cierra la tarea, THE SYSTEM SHALL verificar las **tres** cláusulas
  de la regla de PRD §11: que todos los ítems `required` de la plantilla están completados, que
  hay al menos una foto subida por **cada** `photo_type` con `required: true`, y que no hay
  ninguna incidencia `CRITICAL` sin resolver en la propiedad. Responde `409` enumerando lo que
  falte.
- THE SYSTEM SHALL comprobarlas en el orden en que ocurre el trabajo —ítems, fotos, incidencia—
  y reportar la primera que falle, con el orden fijado por tests en sus dos fronteras.
- THE SYSTEM SHALL enumerar los `photo_type` que faltan de forma **estable** —diferencia de
  conjuntos ordenada, igual que los ítems—, porque el orden de iteración de un `frozenset` varía
  con la semilla de hash y produciría cuerpos distintos entre dos procesos.
- WHERE la plantilla no declara ninguna foto `required: true`, THE SYSTEM SHALL permitir el cierre
  sin ninguna foto: la regla es «las requeridas», no «alguna».
- THE SYSTEM SHALL aplicar las tres cláusulas **dentro de `CleaningTask.complete()`** y en ningún
  otro sitio. El caso de uso solo reúne la evidencia —plantilla, completions, tipos de foto
  subidos e incidencias— y se la pasa a la entidad.
- WHEN el cierre supera la validación, THE SYSTEM SHALL pasar la tarea a `COMPLETED` con
  `completed_at`, poner `validation_status` en `PASSED` y resolver el estado de la propiedad por
  contexto: `AWAITING_CHECKIN` si hay reserva que llega hoy, `READY_FOR_NEXT_GUEST` si la hay
  futura, `VACANT_READY` si no hay ninguna.
- WHEN un `PROPERTY_MANAGER` valida manualmente una tarea cerrada, THE SYSTEM SHALL registrar
  `validated_by_user_id` y `validated_at` y admitir los veredictos `PASSED`, `FAILED` y `WAIVED`,
  rechazando `PENDING` con `409`.
- THE SYSTEM SHALL dejar `ai_validation_result` sin escribir: la validación automática depende
  de `MockAIAdapter`, que llega con `messaging-ai`.

### Fotos de la limpieza

El almacenamiento en sí —puerto, adaptadores `LOCAL`/`S3`, claves y firma— es una capability
compartida y vive en [`specs/file-storage.md`](file-storage.md). Aquí está lo que es de limpieza.

- WHEN la limpiadora asignada solicita `POST /api/v1/cleaning-tasks/{id}/photos` con un fichero y
  un `photo_type`, THE SYSTEM SHALL almacenar el fichero, persistir una fila de `CleaningPhoto`
  con `uploaded_by`, `photo_type` y `storage_key`, y responder `201` con la foto y su URL firmada.
- THE SYSTEM SHALL exigir `EXECUTE_CLEANING_TASKS` para subir —el permiso exclusivo del `CLEANER`—
  y `READ_CLEANING_TASKS` para listar, porque leer la evidencia es lo que hacen el manager y el
  owner mientras que subirla es de la limpiadora.
- IF el `photo_type` no pertenece a las `required_photos` de la plantilla de la tarea, THEN THE
  SYSTEM SHALL responder `404`, igual que el checklist con un `item_id` desconocido. La plantilla
  declara los tipos admisibles **con independencia de su `required`**: un tipo opcional se puede
  subir, y lo que `required: true` gobierna es el cierre.
- IF la tarea no está en `IN_PROGRESS`, THEN THE SYSTEM SHALL responder `409` sin escribir nada:
  ni fila ni objeto en el almacén.
- THE SYSTEM SHALL admitir **varias fotos del mismo `photo_type`** para una misma tarea, a
  propósito: una limpiadora fotografía dos ángulos del mismo baño, y el cierre exige «al menos
  una por tipo requerido», no «exactamente una». No hay restricción de unicidad en la tabla.
- THE SYSTEM SHALL escribir el objeto en el almacén **antes** de insertar la fila, y borrarlo en
  *best effort* si la transacción falla. Una fila que apunte a un objeto inexistente es un `GET`
  roto para siempre; un objeto sin fila es basura recuperable, y ese es el fallo barato.
- IF la escritura en el almacén falla, THEN THE SYSTEM SHALL responder `502` —código
  `BAD_GATEWAY`, no `INTERNAL_ERROR`— y no dejar fila.
- IF el contenido no es una imagen admitida, THEN THE SYSTEM SHALL responder `422`; IF supera el
  tope de tamaño, THEN `413`. El formato se decide por los **bytes** del fichero y nunca por el
  `Content-Type` declarado, y el nombre del fichero que envía el cliente no llega ni a la clave de
  almacenamiento ni a la respuesta.
- WHEN se solicita `GET /api/v1/cleaning-tasks/{id}/photos`, THE SYSTEM SHALL devolver las fotos
  de esa tarea **de la más antigua a la más reciente**, cada una con una URL firmada acuñada para
  esa respuesta.
- THE SYSTEM SHALL no incluir `storage_key` en ningún cuerpo ni cabecera de respuesta. La única
  excepción, nombrada, es lo que una URL prefirmada de un proveedor S3-compatible lleva dentro por
  el propio protocolo de firma (ver [`file-storage`](file-storage.md) §Catálogo de asimetrías).
- WHERE el `storage_type` del tenant es `LOCAL`, THE SYSTEM SHALL servir el fichero desde
  `GET /api/v1/cleaning-photos/{photo_id}`, **anónimo a propósito**: un `<img src>` no envía
  cabecera `Authorization`, así que exigir el token haría la URL firmada inservible para lo único
  que existe. La firma es la credencial — cubre la clave completa, que empieza por el `tenant_id`,
  así que presentarla válida demuestra que quien la trae recibió una URL acuñada para esa foto de
  ese tenant.
- THE SYSTEM SHALL resolver en esa ruta `photo_id → (storage_key, tenant_id)` con una lectura
  **explícitamente sin scoping de tenant**, acotada a ese caso de uso, y verificar la firma
  **después** de reconstruir la clave. El orden es lo que la hace segura, y esa lectura no vive
  en el repositorio de fotos para que no quede al alcance de los casos de uso autenticados.
- IF la firma es inválida, ha caducado, ha sido manipulada o nombra una foto inexistente, THEN THE
  SYSTEM SHALL responder `403` con un cuerpo **constante y precomputado**, idéntico en los cuatro
  casos. No se serializa el mensaje de la excepción —el patrón de `errors.py`— porque los tres
  mensajes de firma más el «no existe» convertirían la ruta en un oráculo de existencia sobre el
  espacio de claves para un llamante sin credenciales; los mensajes sobreviven solo en el log.
- WHERE el `storage_type` del tenant es `S3`, THE SYSTEM SHALL responder `404` en esa ruta: el
  navegador va directo al proveedor y aquí no hay nada que servir. Solo es alcanzable **tras** una
  firma válida, así que no revela nada.
- THE SYSTEM SHALL sellar **toda** respuesta de esa ruta —los bytes y las tres negativas— con
  `X-Content-Type-Options: nosniff`, y derivar el `Content-Type` únicamente de la extensión de la
  clave. Sin ello, un polyglot que empiece por `FF D8 FF` y lleve HTML sería XSS almacenado sobre
  el origen de la API, que `api-ingress-routing` dejó alcanzable desde internet.
- THE SYSTEM SHALL responder los bytes con `Cache-Control: private, max-age=<lo que le queda a la
  firma>`, de modo que ninguna caché compartida los guarde y ninguna copia del navegador
  sobreviva a la credencial que la compró. Las negativas van con `no-store`: cada una es un
  veredicto sobre *esta* petición en *este* instante.
- THE SYSTEM SHALL aplicar a la ruta de subida su **propio** tope de tamaño, configurable con
  default 10 MB, comprobado **antes** de leer el cuerpo entero, y THE SYSTEM SHALL mantener el
  techo JSON de 1 MiB para **todas** las demás rutas bajo `/cleaning-`, con un test que falle si
  alguien lo sube globalmente. La rama del tope de fotos va **antes** que la de `/cleaning-` en el
  middleware, porque la ruta también empieza por ese prefijo y el orden del `if/elif` es lo que
  decide.
- THE SYSTEM SHALL registrar cada subida en `AuditLog` con actor e IP, contra la propia foto como
  entidad y no contra la tarea, y **sin** `storage_key` entre los campos auditables: la clave
  interna no entra en la columna diseñada para volcarse.
- THE SYSTEM SHALL dejar `ai_validation_result` sin escribir también en las fotos: la validación
  automática llega con `messaging-ai`. No hay borrado de fotos por ninguna vía de la API.

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
- THE SYSTEM SHALL demostrar con tests propios que `cleaning_checklist_completions` y
  `cleaning_photos` no son alcanzables desde otro tenant. Ninguna de las dos tiene columna
  `tenant_id` —scoping transitivo por FK— y `tenant_scoped_classes()` selecciona por columna, así
  que el filtro global **no las cubre** y todo su aislamiento recae en el `JOIN` con la tarea
  padre.
- THE SYSTEM SHALL hacer ese `JOIN` con `cleaning_tasks` en **todas** las consultas de
  `cleaning_photos` —alta, listado, lectura individual y tipos subidos—: ninguna parte de la tabla
  a secas. Los tests cubren el cruce de tenant en subida, listado y URL firmada.
- WHILE el solicitante tiene rol `CLEANER`, THE SYSTEM SHALL admitir subida y listado de fotos
  **solo** sobre las tareas cuya `assigned_cleaner_id` sea la suya, derivado del rol persistido en
  el token verificado y no de ningún campo de la petición.
- THE SYSTEM SHALL declarar el permiso de cada endpoint. `EXECUTE_CLEANING_TASKS` es exclusivo
  del `CLEANER`: aceptar, rechazar, iniciar, cerrar y marcar el checklist son de la persona
  asignada, y lo que el manager necesita —crear, asignar y validar— va por
  `MANAGE_CLEANING_TASKS`.
- THE SYSTEM SHALL dejar `cleaning_tasks.notes` y `cleaning_checklist_completions.notes` fuera de
  toda superficie de escritura y de toda respuesta: son texto libre que la tabla de la regla 11
  de `steering/security.md` no enumera, y ampliarla es una decisión de steering.

## Key files

- `backend/app/cleaning/domain/` — `entities.py` (las tres cláusulas de PRD §11 en
  `CleaningTask.complete`), `templates.py` (resolución y ambigüedad), `assignment.py`
  (`resolve_auto_assignee`), `value_objects.py` (validación del contenido de plantilla y
  `CleaningCompletionEvidence`), `notifications.py`, `ports.py`, `repositories.py`
  (`CleaningPhotoRepository` y la consulta sin scoping de la ruta anónima), `exceptions.py`.
- `backend/app/cleaning/application/use_cases.py` — provisión al checkout y los casos de uso del
  ciclo de vida, el checklist, las plantillas y las fotos (subida, listado y servido local).
- `backend/app/cleaning/infrastructure/repositories.py` — adaptadores; los de completions y fotos
  son el único aislamiento de sus tablas.
- `backend/app/cleaning/api/` — `tasks_router.py`, `templates_router.py`, `photos_router.py` (la
  ruta anónima firmada), `schemas.py`, `dependencies.py`, `errors.py`.
- `backend/app/integrations/domain/storage.py` y `.../infrastructure/storage/` — el puerto de
  almacenamiento y sus adaptadores, documentados en [`specs/file-storage.md`](file-storage.md).
- `backend/app/main.py` — el montaje del router anónimo y la rama del tope de subida en
  `MaxBodySizeMiddleware`.
- `backend/app/properties/application/use_cases.py` — el punto donde el provisioner se compone
  con la transición del checkout.
- `backend/alembic/versions/d4b0c7a91f38_cleaning_live_task_unique.py` — el índice parcial.
- Tests: `backend/tests/cleaning/`.
