# Reporte de incidencia por la limpiadora

## Purpose

Da a la limpiadora **una sola cosa que hacer con lo que se encuentra en el piso**: abrir una
incidencia de mantenimiento desde la tarea de limpieza que está haciendo, con un título y una
descripción. Es «reportar incidencia» de PRD §11 y la fuente «reporte de limpiadora durante
checklist» de PRD §12, entregadas como **una ruta de alta colgada de la tarea** — no como una
superficie de `maintenance`.

La incidencia nace `OPEN`, sellada con `IncidentSource.CLEANER`, atribuida a su usuario y
vinculada a la tarea por `incidents.cleaning_task_id`. A partir de ahí es una incidencia como
cualquier otra: el job de clasificación de [`maintenance`](maintenance.md) le pone `category` y
`severity` en su siguiente tick y el manager la triaga. La limpiadora **no lee, no lista, no
clasifica y no resuelve** nada: recibe el acuse de la que acaba de crear y nada más.

Cuelga de una tarea de [`cleaning`](cleaning.md) y reusa su acotamiento por rol sin ampliarlo,
igual que [`cleaner-task-context`](cleaner-task-context.md). El *cómo se opera* está en
[`docs/cleaning.md`](../../docs/cleaning.md) y [`docs/maintenance.md`](../../docs/maintenance.md).

## Requirements

### La ruta de alta, colgada de la tarea

- WHEN se solicita `POST /api/v1/cleaning-tasks/{task_id}/incidents` con `title` y `description`
  sobre una tarea alcanzable por el llamante, THE SYSTEM SHALL crear la incidencia y responder
  `201` con el acuse de tres campos.
- THE SYSTEM SHALL montar la ruta **bajo `cleaning`** (`app/cleaning/api/tasks_router.py`) y NEVER
  SHALL exponer una ruta de creación de incidencias bajo `/api/v1/incidents`: el sujeto de esta
  ruta es la tarea de limpieza, no la incidencia, de modo que la negativa de
  [`maintenance`](maintenance.md) R8 sigue siendo cierta.
- THE SYSTEM SHALL aceptar **exactamente dos campos** en el cuerpo —`title` y `description`— con
  `extra="forbid"`, y NEVER SHALL aceptar `property_id`, `reservation_id`, `tenant_id`, `source`,
  `category`, `severity`, `status`, `cleaning_task_id`, `assigned_technician_id` ni ningún campo de
  coste. Un campo no declarado se **rechaza**, no se ignora.
- THE SYSTEM SHALL derivar `property_id` de la tarea ya resuelta dentro del tenant, y NEVER SHALL
  tomarlo de la petición.
- THE SYSTEM SHALL declarar la operación en `backend/openapi.json` como
  `report_task_incident_api_v1_cleaning_tasks__task_id__incidents_post`, con sus respuestas `201`,
  `401`, `403`, `404`, `409` y `422`, y SHALL mantener regenerado y commiteado
  `frontend/lib/api/generated/openapi.d.ts`.
- THE SYSTEM SHALL declarar `404`, `409` y `422` en la propia ruta con el sobre
  `{error:{code,message,details}}` (`ErrorEnvelope`) de PRD §23.

### Quién puede llamarla, y sobre qué filas

- THE SYSTEM SHALL exigir `EXECUTE_CLEANING_TASKS` en la puerta (`ExecuteDep`) y responder `403`
  **antes de resolver la tarea y sin escribir ninguna fila** cuando el llamante no lo tiene. No hay
  permiso nuevo: ese permiso lo tiene hoy **solo** el rol `CLEANER` — un `PROPERTY_MANAGER` tiene
  `MANAGE_CLEANING_TASKS`, no éste—, que es exactamente el conjunto de llamantes que PRD §12 nombra
  para esta fuente.
- THE SYSTEM SHALL responder el **mismo `403`** para una tarea real y para un uuid inventado, de
  modo que la puerta no sirva de sonda de qué tareas existen. (La autenticación misma lee la fila
  del usuario antes de evaluar el permiso; lo que la garantía fija es que ese `403` llega antes de
  resolver la tarea y sin escribir nada.)
- WHILE el llamante tiene rol `CLEANER`, THE SYSTEM SHALL restringir la tarea a las que llevan su
  `assigned_cleaner_id`, derivado de `CleaningActor.restrict_to_cleaner_id` sobre el rol
  **persistido** que se relee de la fila del usuario en cada petición, y NEVER SHALL aceptar ni
  ensanchar ese acotamiento desde la petición.
- IF la tarea no existe, pertenece a otro tenant, está asignada a otra limpiadora, o su
  `property_id` no resuelve dentro del tenant, THEN THE SYSTEM SHALL responder `404 NOT_FOUND` con
  un cuerpo **idéntico** en los cuatro casos.
- THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado y SHALL pasarlo explícito a
  cada método de repositorio.
- THE SYSTEM SHALL permitir el alta sobre una tarea en `ASSIGNED`, `ACCEPTED` o `IN_PROGRESS`
  (`INCIDENT_REPORTABLE_STATUSES`) y SHALL rechazarla con `409` sobre una tarea ya terminal
  (`COMPLETED`, `REJECTED`, `CANCELLED`): PRD §12 dice «durante checklist».
- THE SYSTEM SHALL comprobar la pertenencia **antes** que el estado —`assert_incident_reportable`
  llama a `_require_assignee` y después a `_require_status`—, de modo que un `409` nunca describa
  una tarea que el llamante no puede ver.
- IF una tarea es propia y terminal y además su `property_id` no resuelve dentro del tenant, THEN
  THE SYSTEM SHALL responder el `409`: la puerta de estado corre antes que la resolución de la
  propiedad, y para llegar ahí el llamante ya ha pasado las dos comprobaciones de pertenencia.

### El escritor que sella `IncidentSource.CLEANER`

- THE SYSTEM SHALL crear la incidencia con `source = IncidentSource.CLEANER`, sellado por el
  escritor, y NEVER SHALL leerlo de la petición.
- THE SYSTEM SHALL dejarla en `status = OPEN` sin fijar `category`, `severity`, `ai_summary` ni
  `ai_classification`, de modo que la recoja el job de clasificación de
  [`maintenance`](maintenance.md) R3 en su siguiente tick, y NEVER SHALL clasificarla dentro de la
  petición que la crea.
- THE SYSTEM SHALL escribir `reported_by_user_id` con el id del usuario autenticado, y NEVER SHALL
  escribir `reported_by_guest_token`.
- THE SYSTEM SHALL resolver `property_id` dentro del tenant antes de escribir nada. Las claves
  ajenas de `incidents` son globales y no compuestas con `tenant_id`, así que
  `IncidentRepository.add` declara esa precondición como del llamante; aquí se satisface por
  composición, porque el `property_id` sale de una tarea ya cargada con `tenant_id` explícito.
- THE SYSTEM SHALL escribir la entidad, su `AuditLog` (`INCIDENT_CREATED`, actor el usuario, con su
  IP) y su `TimelineEvent` (`INCIDENT_CREATED`, actor `USER`) en **una sola transacción**, con un
  título de timeline **constante** y metadatos que sean solo identificadores y el `source`.
- THE SYSTEM SHALL exigir actor: una creación sin actor SHALL rechazarse y no comitear nada.
- THE SYSTEM SHALL reusar `ReportIncidentUseCase` (`maintenance`) en vez de duplicar un alta para
  esta fuente, envolviéndolo en `CleanerIncidentReporter`, que implementa el puerto
  `TaskIncidentReportingPort` que declara `cleaning`. THE SYSTEM SHALL cablear los dos módulos
  **solo en `app/cleaning/api/dependencies.py`**: un caso de uso que importe los casos de uso de
  otro módulo es lo que la regla de dependencias prohíbe.

### El vínculo con la tarea, y el acuse

- THE SYSTEM SHALL tener en `incidents` una columna `cleaning_task_id` **nullable**, con clave
  ajena a `cleaning_tasks(id)` y `ondelete="RESTRICT"` —la misma postura que `property_id` y
  `reservation_id` en esa tabla—, creada por la migración `b3f5d1c8a047` sin backfill y sin índice.
- THE SYSTEM SHALL dejarla `NULL` en toda incidencia que no nazca de una tarea de limpieza, y NEVER
  SHALL exigirla: las incidencias del portal del huésped, de una conversación y del comando de
  siembra siguen siendo válidas sin ella.
- THE SYSTEM SHALL escribirla en el alta con el `task_id` de la ruta, y NEVER SHALL aceptarla en
  ningún esquema de petición ni exponer una ruta que la modifique después.
- WHEN el alta tiene éxito, THE SYSTEM SHALL responder un acuse de **tres campos** —`id`, `status`
  y `created_at`—, espejo del `IncidentReportedResponse` del portal del huésped, y NEVER SHALL
  incluir en él `category`, `severity`, `ai_summary`, `ai_classification`,
  `reported_by_guest_token` ni el `description` de vuelta.
- THE SYSTEM SHALL fijar con tests propios tanto el conjunto de campos aceptados como el de campos
  devueltos, de modo que añadir uno sea un acto deliberado y no una deriva.

### Texto libre: el sumidero de la excepción 3

- THE SYSTEM SHALL acotar `title` y `description` en el **esquema de petición**, no en la entidad,
  con `min_length=1`, recorte de espacios (`str_strip_whitespace=True`) y los máximos importados de
  `maintenance` (`MAX_INCIDENT_TITLE` = 300, `MAX_INCIDENT_DESCRIPTION` = 5000) — los mismos que
  usa el portal del huésped, nunca redefinidos localmente.
- THE SYSTEM SHALL validar que las dos son texto que la base de datos puede almacenar, con
  `SingleLineText` para el título (sin ningún carácter de control, porque se renderiza en listas y
  logs) y `MultiLineText` para la descripción (admite tabulador y saltos de línea), del guardián
  común `app/core/storable_text.py`. IF el valor lleva `U+0000` o un sustituto sin pareja, THEN THE
  SYSTEM SHALL responder `422` y NEVER SHALL dejarlo llegar al driver como un `500` no declarado.
- THE SYSTEM NEVER SHALL propagar `title` ni `description` a `audit_logs.changes` ni a
  `timeline_events`: las dos están fuera de `AUDITABLE_FIELDS["INCIDENT"]`, así que `ChangeSet` las
  rechaza por construcción, y el título del evento de timeline es una constante literal.
- THE SYSTEM SHALL registrar este escritor bajo la **excepción 3** de la regla 11 de
  `sdd/steering/security.md` —persona autenticada con RBAC escribiendo sobre su propio alcance, no
  el anónimo de la excepción 2 con el que comparte columna— y SHALL hacer que el guardián
  automático `backend/tests/maintenance/test_free_text_sink_contract.py` lo reconozca.
- THE SYSTEM SHALL gatear en ese guardián también a quien **importe** `app.cleaning.domain.ports`,
  leído del AST a un salto, porque un llamante tipado solo contra el alias del puerto no menciona
  ninguno de los cuatro nombres que la cláusula anterior vigilaba.
- THE SYSTEM SHALL registrar en logs el `tenant_id`, el `cleaning_task_id` y el `incident_id`, y
  NEVER SHALL registrar el texto reportado.

### La incidencia que le bloquea su propio cierre

- THE SYSTEM SHALL dejar intacta la tercera cláusula de evidencia de `CleaningTask.complete()`:
  sigue siendo `has_unresolved_critical(tenant_id, property_id)`, acotada a la **propiedad** y no a
  la tarea, como [`cleaning`](cleaning.md) ya declara.
- WHEN una limpiadora reporta una incidencia, THE SYSTEM SHALL crearla con la `severity` por
  defecto (`MEDIUM`), de modo que **no bloquee el cierre en el momento**; SHALL bloquearlo solo si
  el job de clasificación de `maintenance` la sube después a `CRITICAL`, o si ya había una
  `CRITICAL` sin resolver en la propiedad por cualquier otra vía.
- IF el cierre se rechaza por esa cláusula, THEN THE SYSTEM SHALL responder el `409` de
  `BlockingIncidentError` nombrando la causa —una incidencia `CRITICAL` sin resolver **en la
  propiedad**— y NEVER SHALL incluir el identificador, el título ni la descripción de la incidencia
  que bloquea: `CLEANER` no tiene `READ_INCIDENTS` y ese cuerpo sería la lectura que se le niega.

### Lo que esta capacidad no hace

- THE SYSTEM NEVER SHALL permitir a `CLEANER` leer, listar, seguir, clasificar, asignar o resolver
  incidencias: el acuse de tres campos es toda la lectura que tiene. Las once rutas de
  `/api/v1/incidents` siguen cerradas a ese rol.
- THE SYSTEM NEVER SHALL permitirle fijar `category` ni `severity`: `classify` sigue siendo la
  única puerta de salida de `OPEN`.
- THE SYSTEM SHALL dejar `IncidentSource.LOCK_ALERT` sin escritor y sin superficie de importación.
- THE SYSTEM SHALL disparar las notificaciones por severidad (`INCIDENT_HIGH`/`INCIDENT_CRITICAL`)
  al **clasificar** y no al crear, como `maintenance` ya hace: el alta de la limpiadora no añade un
  camino de notificación propio.
- La UI (`/cleaner`, `/cleaner/tasks/[id]` y su botón «reportar incidencia») la implementa
  `cleaner-app`; adjuntar fotos a la incidencia es superficie de `maintenance` y PRD §11 no la pide.

## Key files

- `backend/app/cleaning/api/tasks_router.py` — `POST /{task_id}/incidents` y
  `_INCIDENT_REPORT_RESPONSES`.
- `backend/app/cleaning/api/schemas.py` — `ReportTaskIncidentRequest` (con `to_report()`) y
  `TaskIncidentReportedResponse`.
- `backend/app/cleaning/api/dependencies.py` — `get_report_task_incident_use_case`, el único sitio
  que conoce los dos módulos.
- `backend/app/cleaning/application/use_cases.py` — `ReportTaskIncidentUseCase` (los cinco pasos).
- `backend/app/cleaning/domain/entities.py` — `INCIDENT_REPORTABLE_STATUSES`,
  `CleaningTask.assert_incident_reportable`.
- `backend/app/cleaning/domain/ports.py` — `TaskIncidentReportingPort`, `IncidentReport`,
  `IncidentReportedAcknowledgement`.
- `backend/app/core/storable_text.py` — `SingleLineText`, `MultiLineText`.
- `backend/app/maintenance/application/use_cases.py` — `ReportIncidentUseCase` (con
  `reported_by_user_id` y `cleaning_task_id`) y `CleanerIncidentReporter`.
- `backend/app/maintenance/domain/entities.py` — `Incident.cleaning_task_id`,
  `MAX_INCIDENT_TITLE`, `MAX_INCIDENT_DESCRIPTION`.
- `backend/app/maintenance/infrastructure/models.py` — la columna y su FK.
- `backend/alembic/versions/b3f5d1c8a047_cleaner_incident_report.py` — la migración.
- `backend/app/audit/domain/value_objects.py` — `AUDITABLE_FIELDS["INCIDENT"]`, trece campos.
- Tests: `backend/tests/cleaning/test_task_incident_api.py`,
  `test_task_incident_use_case.py`, `test_completion_clause_contract.py`,
  `backend/tests/maintenance/test_cleaner_incident_reporter.py`,
  `test_free_text_sink_contract.py`, `backend/tests/core/test_storable_text.py`.
