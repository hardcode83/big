# Mensajería de personal (limpiadora/técnico ↔ manager)

## Purpose

Da a la limpiadora y al técnico un canal de respuesta dentro del producto, acotado a la tarea de
limpieza o a la incidencia que tienen asignada, sin abrir `Conversation` (que sigue siendo del
huésped por contrato) ni concederles `READ_CONVERSATIONS`. Antes de esta capacidad,
`MessageSenderType` tenía cinco miembros —`GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM`— y ninguno de
campo, y las siete rutas de `/conversations` respondían `403` a `CLEANER`/`TECHNICIAN`
(`backend/app/auth/domain/policy.py`).

Son **dos hilos gemelos**, uno por dominio — el de limpieza cuelga de [`cleaning`](cleaning.md), el
de incidencia de [`maintenance`](maintenance.md) — con el mismo esquema, las mismas reglas de
acotamiento y el mismo reparto de notificación, documentados una sola vez aquí. El *cómo se opera*
—qué ve la limpiadora, qué ve el manager— no tiene pantalla propia en esta entrega; ver «Fuera de
alcance».

## Requirements

### R1 — Persistencia: dos tablas gemelas, no una polimórfica

- THE SYSTEM SHALL persistir cada hilo en su propia tabla, `cleaning_task_messages` (dominio
  `cleaning`) e `incident_messages` (dominio `maintenance`), cada una con FK compuesta
  `(tenant_id, task_id)` / `(tenant_id, incident_id)` `ON DELETE RESTRICT` hacia su padre
  —literalmente el mismo `__table_args__` que `cleaning_photos`/`incident_photos`— en vez de una
  tabla `staff_messages` con `related_type`/`related_id` polimórfico como `NotificationLog`
  (design D1). El target de un mensaje es siempre una de dos entidades conocidas, así que la FK
  compuesta hace irrepresentable un `task_id`/`incident_id` que no exista o que exista en otro
  tenant, en vez de dejarlo para un `404` en tiempo de ejecución.
- THE SYSTEM SHALL declarar, para cada tabla, `id` (PK), `tenant_id`, el FK al padre, `author_id`
  (FK `users.id`, `ON DELETE RESTRICT`, sin cualificar por tenant — mismo patrón que
  `uploaded_by`), `author_role` (`VARCHAR(32)`, nunca el tipo `Enum` nativo de Postgres), `content`
  (`VARCHAR(2000)`) y `created_at`.
- THE SYSTEM SHALL escribir `created_at` desde el caso de uso y NEVER SHALL usar `server_default`:
  `now()` de Postgres es el instante de la *transacción*, así que una ráfaga de mensajes insertados
  juntos colapsaría el orden cronológico en el que el hilo se lee. Ninguna de las dos tablas tiene
  `updated_at`: ambas filas son inmutables tras el `INSERT` (solo `add`/`list_for_*`, nunca `save`).
- THE SYSTEM SHALL indexar cada tabla por `tenant_id` (heredado de `TenantScopedMixin`) y por
  `(tenant_id, task_id)` / `(tenant_id, incident_id)`, que es el predicado exacto del listado del
  hilo.

### R2 — Autor: `author_id` + `author_role` congelado, nunca `MessageSenderType`

- THE SYSTEM SHALL fijar `author_id` y `author_role` desde el actor autenticado que ejecuta la
  escritura —`CleaningActor`/`IncidentActor`— y NEVER SHALL aceptarlos, ni derivarlos, de ningún
  campo de la petición.
- THE SYSTEM SHALL congelar en `author_role` el `UserRole` **persistido del llamante en el
  instante de escribir** (design D2), y NEVER SHALL derivarlo por `JOIN` a `users.role` en cada
  lectura: un cambio de rol posterior no debe reescribir en silencio la autoría histórica —quien
  escribió como `CLEANER` y más tarde pasa a `PROPERTY_MANAGER` no se convierte retroactivamente en
  la autora-manager de un mensaje que envió de limpiadora.
- THE SYSTEM NEVER SHALL reutilizar `MessageSenderType` (`app/messaging/domain/enums.py`) para el
  autor de estos mensajes (R3.3 del proposal): ese enum es de `messaging`/`Conversation`, del
  huésped, y sus cinco miembros no tienen ninguno de campo.

### R3 — Escritura y lectura: `POST`/`GET` por dominio, mismo scoping por rol que el resto del módulo

- THE SYSTEM SHALL exponer `POST` y `GET /api/v1/cleaning-tasks/{task_id}/messages` en
  `cleaning/api/messages_router.py` (espejo de `photos_router.py`, no una decimotercera ruta de
  `tasks_router.py`), y `POST` y `GET /api/v1/incidents/{incident_id}/messages` en
  `maintenance/api/messages_router.py`.
- THE SYSTEM SHALL responder `201` con el mensaje creado (`id`, `author_id`, `author_role`,
  `content`, `created_at`) en el `POST`, y `200` con la página cronológica ascendente en el `GET`,
  paginada `page`/`per_page` con el envelope de PRD §23 (`data`, `total`, `page`, `per_page`,
  `total_pages`; cotas 100.000 y 100, la convención de `cleaning`/`reservations`).
- THE SYSTEM SHALL resolver la tarea/incidencia **dentro del tenant** antes de tocar el hilo,
  reusando `_load_task`/`_load_incident_in_scope` — el mismo colaborador que ya usa el resto del
  dominio — y NEVER SHALL introducir una segunda ruta de resolución para este sub-recurso.
- WHILE el llamante tiene rol `CLEANER`, THE SYSTEM SHALL acotar escritura y lectura del hilo de
  limpieza a la tarea cuya `assigned_cleaner_id` es la suya (R1.5); WHILE tiene rol `TECHNICIAN`,
  THE SYSTEM SHALL acotar el hilo de incidencia a la incidencia cuyo `assigned_technician_id` es el
  suyo (R2.5). Ambas restricciones se derivan del rol **persistido** del llamante, nunca de un
  campo de la petición — mismo patrón que `restrict_to_cleaner_id`/`restrict_to_technician_id`.
- WHILE el llamante tiene rol `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir escribir y leer
  cualquier hilo de su tenant, sin la restricción de asignación anterior.
- IF `CLEANER`/`TECHNICIAN` intenta leer o escribir en una tarea/incidencia que no es la suya, que
  no existe, o que pertenece a otro tenant, THEN THE SYSTEM SHALL responder el mismo
  `CleaningTaskNotFoundError`/`IncidentNotFoundError`-backed `404` que el resto de rutas acotadas
  por asignación de su dominio, y NEVER SHALL responder `403`: los tres casos son indistinguibles a
  propósito, para que el endpoint no sirva de sonda de qué tareas/incidencias existen.
- THE SYSTEM SHALL dejar el **estado** de la tarea/incidencia fuera del acceso al hilo: se puede
  escribir y leer sobre una en estado terminal, igual que `_load_task`/`_load_incident_in_scope` no
  filtran por estado hoy para el resto de esta lectura (design D4) — a diferencia de la subida de
  fotos, que sí exige un estado concreto.

### R4 — Permisos: los cuatro que cada dominio ya tenía, ninguno nuevo

- THE SYSTEM SHALL gatear el hilo de limpieza con `READ_CLEANING_TASKS` para leer y
  (`EXECUTE_CLEANING_TASKS` **o** `MANAGE_CLEANING_TASKS`) para escribir — el `or` hace falta
  porque, a diferencia de `maintenance`, `PROPERTY_MANAGER` de `cleaning` no tiene
  `EXECUTE_CLEANING_TASKS` (solo `MANAGE_CLEANING_TASKS`).
- THE SYSTEM SHALL gatear el hilo de incidencia con `READ_INCIDENTS` para leer y
  `EXECUTE_INCIDENTS` para escribir, sin `or`: `PROPERTY_MANAGER` de `maintenance` ya tiene las dos
  a la vez.
- THE SYSTEM NEVER SHALL declarar un permiso nuevo en `Permission`/`ROLE_PERMISSIONS` para esta
  capacidad (amienda R3.1 del proposal — design D3): los cuatro permisos que gatean lectura y
  escritura de los dos hilos ya existían, y cada rol que necesita acceder a un hilo ya tenía, antes
  de este change, el permiso equivalente sobre la entidad padre.
- **Efecto colateral aceptado.** THE SYSTEM SHALL conceder a `TENANT_OWNER` lectura tenant-wide de
  ambos hilos como consecuencia de reutilizar `READ_CLEANING_TASKS`/`READ_INCIDENTS` (que ya
  tenía), en vez de introducir un permiso o una restricción de rol dedicados solo para excluirlo —
  design D3, que amienda el out-of-scope original del proposal.
- THE SYSTEM SHALL mantener acotada por `tenant_id` toda consulta de este módulo (regla 1 de
  `steering/security.md`) y SHALL llevar un test automático que demuestre que un tenant no accede
  a los mensajes de otro, para cada uno de los dos hilos.

### R5 — Notificación al otro extremo

- WHEN se crea un mensaje de personal, THE SYSTEM SHALL encolar una fila de `NotificationLog` por
  destinatario, dirigida a quien no lo escribió, con `related_type`/`related_id` apuntando a la
  tarea o la incidencia (reusando `RELATED_TYPE_CLEANING_TASK`/`RELATED_TYPE_INCIDENT`, los mismos
  que `CLEANING_TASK_ASSIGNED`/`TECHNICIAN_ASSIGNED` ya usan — **no** un `related_type` nuevo) —
  mismo mecanismo que ya sirve la bandeja in-app de [`access-notifications`](access-notifications.md).
- IF quien escribe es `CLEANER` o `TECHNICIAN`, THEN THE SYSTEM SHALL notificar a **todos** los
  `PROPERTY_MANAGER` **activos** del tenant, una fila de `NotificationLog` por cada uno — decisión
  D9: hoy no existe el concepto de "manager asignado" a una tarea o incidencia, y no se introduce
  aquí. IF no hay ningún manager activo, THEN THE SYSTEM SHALL persistir igualmente el mensaje y
  SHALL registrarlo (`cleaning.staff_message_without_manager`/equivalente de `maintenance`) sin
  fallar la operación.
- IF quien escribe es `PROPERTY_MANAGER`, THEN THE SYSTEM SHALL notificar a la limpiadora o el
  técnico asignado a la tarea/incidencia, si la hay. IF la tarea/incidencia no tiene asignado, o el
  asignado no está activo, THEN THE SYSTEM SHALL persistir igualmente el mensaje, no notificar a
  nadie, y registrarlo.
- THE SYSTEM SHALL introducir dos `NotificationType` nuevos y **solo** dos —
  `CLEANING_TASK_MESSAGE`, `INCIDENT_MESSAGE` (`notifications/domain/enums.py`)— como divergencia
  declarada del catálogo de PRD §14, mismo precedente que `REVIEW_RESPONSE_APPROVED`. Ninguno lleva
  `sla_deadline_at` ni entra en escalación: un mensaje de personal no tiene plazo de respuesta.
  Sube el censo de `NotificationType` con escritor de producción de catorce a **dieciséis**
  (`test_writer_census.py`, `WITH_WRITER`).
- THE SYSTEM SHALL construir cada notificación con un builder puro y gemelo por dominio,
  `staff_message_notification` (`cleaning/domain/notifications.py`,
  `maintenance/domain/notifications.py`), cuyo `body` lleva **solo** `message_id` y
  `task_id`/`incident_id` más un texto constante ("Tienes un mensaje nuevo…"), y NEVER SHALL
  interpolar el `content` del mensaje ni ningún fragmento de él — la disciplina que el propio
  módulo `notifications` declara por escrito, la misma que sostiene R6.
- THE SYSTEM SHALL escribir el mensaje y cada fila de `NotificationLog` que fan-out produce en
  **una sola transacción** (design D9): un `uow.commit()`, después de que todas estén preparadas.

### R6 — Contenido gobernado por la regla 11

- THE SYSTEM SHALL acotar `content` a `Annotated[MultiLineText, Field(min_length=1,
  max_length=2000)]`, con `str_strip_whitespace=True` (así el máximo cuenta caracteres después del
  recorte, y un mensaje solo-espacios se rechaza en vez de persistirse) — la forma exacta de
  `CompleteIncidentRequest.materials`, no la de `messages.content` (4000): es el mismo contrato
  ("persona autenticada tecleando su propia nota corta"), no el de prosa de un tercero transcrita
  vía WhatsApp/IA (design D5).
- THE SYSTEM SHALL importar el límite (`MAX_CLEANING_TASK_MESSAGE_LENGTH`/su gemelo de
  `maintenance`) desde el módulo de dominio que declara la columna, y NEVER SHALL re-derivarlo en
  el schema de la API.
- THE SYSTEM SHALL pasar `content` por `MultiLineText` (`storable_text("\t\n\r")`,
  `app/core/storable_text.py`) antes de persistirlo — el guardián de todo sumidero de texto libre
  del sistema.
- IF `content` está vacío, excede 2000 caracteres, o el cuerpo lleva un campo desconocido, THEN THE
  SYSTEM SHALL responder `422` antes de tocar el caso de uso.
- THE SYSTEM SHALL tener su fila propia en el censo de la regla 11 de `steering/security.md`, bajo
  la **excepción 3** ("persona autenticada tecleando su propia nota, acotada, `storable_text`,
  fuera de `AUDITABLE_FIELDS` y fuera del `metadata` del timeline") — el mismo contrato que
  `assignment_note`/`materials`, no uno nuevo.

### R7 — Sin `AuditLog` ni `TimelineEvent`

- THE SYSTEM NEVER SHALL escribir `AuditLog` por un mensaje de personal (design D7): ni
  `CleaningTaskMessage` ni `IncidentMessage` están en la lista de entidades auditadas de la regla 9
  de `steering/security.md` (`Reservation`, estados de propiedad, documentos de `Guest`,
  `AccessRecord`, `PricingRule`/`PriceRecommendation`, `OwnerApproval`, roles de `User`,
  `Incident`), y un mensaje no es una mutación de su tarea/incidencia padre — es una entidad hija
  nueva, como `CleaningPhoto`/`IncidentPhoto`, que tampoco se audita.
- THE SYSTEM NEVER SHALL escribir `TimelineEvent` por un mensaje de personal (design D6, decidido
  con el usuario el 2026-09-02): el timeline es append-only y responde "qué pasa y quién tiene la
  próxima acción" sobre **estados operacionales de la propiedad** (principio 2 de
  `steering/product.md`), no un log de chat. Varios mensajes por tarea inundarían el timeline de la
  propiedad con entradas no accionables.

## Fuera de alcance

- **Huésped↔limpiadora y huésped↔técnico.** Nadie lo ha pedido, PRD §11/§12 no lo contemplan, y
  abriría la identidad del personal a un portador anónimo de token.
- **IA, escalación e intents** sobre estos hilos: no tocan `messaging` ni `Conversation`.
- **Ensanchar `Conversation`** o dar a `CLEANER`/`TECHNICIAN` `READ_CONVERSATIONS` (R3.3).
- **Manager "de guardia"/asignado** a una tarea o incidencia (D9): R5 notifica a todos los
  `PROPERTY_MANAGER` activos del tenant.
- **Restringir la escritura por estado** de la tarea/incidencia (D4): el scoping por asignación no
  mira el estado, igual que el resto de la lectura de estos dos dominios.
- **UI dedicada.** Ninguna pantalla de web/`cleaner-app`/`tech-app` consume estas rutas todavía —
  esta entrega es la API y su contrato publicado; una entrada de roadmap posterior decide la
  pantalla.

## Key files

- `backend/app/cleaning/domain/entities.py` — `CleaningTaskMessage`,
  `MAX_CLEANING_TASK_MESSAGE_LENGTH`.
- `backend/app/cleaning/domain/repositories.py` — `CleaningTaskMessageRepository` (`add`,
  `list_for_task`), `CleaningTaskMessagePage`.
- `backend/app/cleaning/domain/notifications.py` — `staff_message_notification`.
- `backend/app/cleaning/application/use_cases.py` — `SendCleaningTaskMessageUseCase`,
  `ListCleaningTaskMessagesUseCase`.
- `backend/app/cleaning/infrastructure/models.py` — `CleaningTaskMessageModel`
  (`cleaning_task_messages`).
- `backend/app/cleaning/infrastructure/repositories.py` — `SqlAlchemyCleaningTaskMessageRepository`.
- `backend/app/cleaning/api/messages_router.py`, `schemas.py`
  (`SendCleaningTaskMessageRequest`, `CleaningTaskMessageResponse`,
  `CleaningTaskMessagePageResponse`).
- `backend/app/maintenance/domain/entities.py` — `IncidentMessage`,
  `MAX_INCIDENT_MESSAGE_LENGTH`.
- `backend/app/maintenance/domain/repositories.py` — `IncidentMessageRepository`,
  `IncidentMessagePage`.
- `backend/app/maintenance/domain/notifications.py` — `staff_message_notification` (gemelo).
- `backend/app/maintenance/application/use_cases.py` — `SendIncidentMessageUseCase`,
  `ListIncidentMessagesUseCase`.
- `backend/app/maintenance/infrastructure/models.py` — `IncidentMessageModel`
  (`incident_messages`).
- `backend/app/maintenance/infrastructure/repositories.py` — el repositorio SQLAlchemy gemelo.
- `backend/app/maintenance/api/messages_router.py`, `schemas.py` (los tres schemas gemelos).
- `backend/app/notifications/domain/enums.py` — `NotificationType.CLEANING_TASK_MESSAGE`,
  `.INCIDENT_MESSAGE`.
- `backend/alembic/versions/3488de4c4f49_cleaning_task_messages_and_incident_.py` — la revisión
  única que crea las dos tablas (y la `UNIQUE(tenant_id, id)` que le faltaba a `cleaning_tasks`).
- `backend/app/main.py` — montaje de los dos routers nuevos.
- `backend/tests/cleaning/test_messages_api.py`, `test_task_messages_use_case.py`,
  `test_free_text_sink_contract.py` — el contrato de API, el caso de uso y el guardián de la regla
  11 para `cleaning_task_messages.content`.
- `backend/tests/maintenance/test_messages_api.py`, `test_incident_messages_use_case.py`,
  `test_incident_messages_free_text_sink_contract.py` — los gemelos de `maintenance`.
- `backend/tests/notifications/test_writer_census.py` — `CLEANING_TASK_MESSAGE`/`INCIDENT_MESSAGE`
  en `WITH_WRITER`.
- `sdd/steering/security.md` — las dos filas nuevas de la regla 11, excepción 3.
