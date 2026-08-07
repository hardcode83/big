# Tasks: cleaning

Convenciones: TDD obligatorio en `domain/` (`steering/testing.md`); cada tarea trae su test.
Comandos del proyecto (`sdd/project.md`): `make up` para levantar el stack del worktree,
`docker compose exec backend uv run pytest` para la suite, `make openapi` para el contrato.

## 1. Dominio de limpieza (Python puro, sin infraestructura) <!-- panel: PASS 2026-08-06 (2 rondas: 7 hallazgos, todos corregidos) -->

- [x] 1.1 `backend/app/cleaning/domain/exceptions.py` — jerarquía `CleaningDomainError` con
  `CleaningTaskNotFoundError`, `ChecklistTemplateNotFoundError`,
  `AmbiguousChecklistTemplateError`, `ChecklistItemNotFoundError`,
  `InvalidCleaningTransitionError`, `ChecklistIncompleteError`, `BlockingIncidentError`,
  `DuplicateLiveCleaningTaskError`, `CleaningValidationError`. Sin imports de FastAPI ni
  SQLAlchemy — `tests/test_layering.py` lo verifica por glob. [R1, R3, R4, R5]
- [x] 1.2 `backend/app/cleaning/domain/value_objects.py` — `ChecklistItemSpec` (frozen:
  `item_id`, `label`, `required`), `RequiredPhotoSpec` y `CleaningCompletionEvidence`
  (ítems requeridos, ítems completados, incidencias `CRITICAL` activas). Tests puros. [R4, R5]
- [x] 1.3 `backend/app/cleaning/domain/templates.py` — validación de estructura de `items` y
  `required_photos` (cada elemento con `item_id` no vacío y **único** dentro de la plantilla y
  un `required` booleano) y `resolve_template(candidates, property_id)` con la precedencia
  propiedad → tenant. Dos activas en el mismo nivel → `AmbiguousChecklistTemplateError`.
  Test primero, incluyendo el caso de ambigüedad y el de `item_id` duplicado (D5). [R1.2, R1.3, R1.4]
- [x] 1.4 `backend/app/cleaning/domain/entities.py` — `CleaningTask` gana `assign`, `accept`,
  `reject`, `start` y `record_manual_validation`; cada método valida el estado de partida y
  lanza `InvalidCleaningTransitionError` desde cualquier otro, y los de la limpiadora exigen
  además ser la persona asignada. `reject` **conserva** `assigned_cleaner_id` — es el registro
  de quién rechazó (D3). Los campos conservan nombre y tipo (D4). Test primero, cubriendo la
  matriz completa de estado × método, incluidas las combinaciones inválidas. [R3.4, R3.5, R3.6, R3.7]
- [x] 1.5 `backend/app/cleaning/domain/entities.py` — `CleaningTask.complete(evidence)`:
  exige todos los ítems `required: true` completados (`ChecklistIncompleteError`, enumerando
  los que faltan) y ninguna incidencia `CRITICAL` activa (`BlockingIncidentError`); al pasar,
  fija `status=COMPLETED`, `completed_at` y `validation_status=PASSED`. **Sin cláusula de
  fotos** — es de `cleaning-photos-storage`, y el test lo deja anotado. Test primero (D4). [R5.1, R5.2, R5.3, R5.6]
- [x] 1.6 `backend/app/cleaning/domain/repositories.py` — puertos `CleaningTaskRepository`,
  `CleaningChecklistTemplateRepository` y `CleaningChecklistCompletionRepository`, todos con
  `tenant_id` explícito en cada método y hablando en entidades de dominio, nunca en modelos
  ORM (D6). [R7.1, R7.5]
- [x] 1.7 `backend/app/cleaning/domain/ports.py` — `CleaningProvisioningPort` con
  `provision_for_checkout(...) -> CleaningTask | None`, y el docstring que explica por qué
  devuelve `None` en vez de lanzar (D1). [R2.1, R2.4]

## 2. Persistencia <!-- panel: PASS 2026-08-06 (con seccion 3, 2 rondas: 7 hallazgos) -->

- [x] 2.1 `backend/app/cleaning/infrastructure/repositories.py` —
  `SqlAlchemyCleaningTaskRepository` (`get`, `add`, `save`, `list_page`, `list_live_for_reservation`,
  `list_for_property`) y `SqlAlchemyCleaningChecklistTemplateRepository` (`list_active_for_property`,
  `add`, `list_page`). Filtro `tenant_id` explícito en toda sentencia; traducen a entidades de
  dominio antes de devolver. Tests de integración contra Postgres. [R7.1]
- [x] 2.2 Mismo fichero — `SqlAlchemyCleaningChecklistCompletionRepository` con `JOIN
  cleaning_tasks ON id = cleaning_task_id AND cleaning_tasks.tenant_id = :tenant_id` en
  **todos** sus métodos, incluida la escritura. Ningún método acepta solo `cleaning_task_id`,
  y `upsert` lleva **un solo** identificador de tarea —el de la entidad—, corregido tras el
  panel de la sección 1: dos ids independientes para la misma tarea permitían validar uno y
  escribir el otro sobre una tabla sin `tenant_id` ni red del filtro global. Test que
  demuestra que una completion del tenant B es invisible e inescribible desde el tenant A
  (D6). [R7.5]
- [x] 2.3 `backend/alembic/versions/d4b0c7a91f38_cleaning_live_task_unique.py` — índice único
  parcial `uq_cleaning_tasks_live_reservation` sobre `(tenant_id, reservation_id)` `WHERE
  reservation_id IS NOT NULL AND status IN ('CREATED','ASSIGNED','ACCEPTED','IN_PROGRESS')`
  —cuatro estados, no cinco: `PENDING_REVIEW` se cayó tras el panel de la sección 1 porque el
  resolutor no lo cuenta y la discrepancia reintroducía el estado partido (D2)—, reversible,
  encadenada sobre `c3f81a5d7e42`. Declarado también en `__table_args__` del modelo para que
  `alembic check` quede limpio, y `tests/cleaning/test_live_task_index.py` extrae el predicado
  del modelo y lo compara con `LIVE_STATUSES`. Verificar `alembic check` y
  `alembic downgrade base` (D2, D12). [R2.5]

## 3. Plantillas de checklist (API) <!-- panel: PASS 2026-08-06 (con seccion 2, 2 rondas: 7 hallazgos) -->

- [x] 3.1 `backend/app/auth/domain/policy.py` — `READ_CLEANING_TEMPLATES` y
  `MANAGE_CLEANING_TEMPLATES` en `Permission`, con el reparto de la tabla del design D7 y el
  comentario que explica por qué `SUPER_ADMIN` no recibe ninguno. [R1.1, R1.5, R7.4]
- [x] 3.2 `backend/app/cleaning/application/use_cases.py` — `CreateChecklistTemplateUseCase`
  (valida con 1.3, persiste, commit) y `ListChecklistTemplatesUseCase` (envelope paginado).
  Tests de aplicación con fakes en memoria de los puertos. [R1.1, R1.2, R1.5]
- [x] 3.3 `backend/app/cleaning/api/{router,schemas,dependencies,errors}.py` — endpoints
  `GET`/`POST /api/v1/cleaning-checklist-templates`, schemas Pydantic, un builder por caso de
  uso, y `cleaning/api/errors.py` con la tabla ordenada de excepción → status → `ErrorCode`
  del design D11. Registro en `backend/app/main.py`. Tests de integración con `httpx`. [R1, R7.6]

## 4. Alta automática al cerrar el checkout <!-- panel: PASS 2026-08-06 (2 rondas: 5 hallazgos, incluido un bug real en scheduled_end) -->

- [x] 4.1 `backend/app/cleaning/application/use_cases.py` — `ProvisionCleaningTaskUseCase`
  implementando `CleaningProvisioningPort`: lee `TenantConfig.auto_create_cleaning_task` y
  `Reservation.cleaning_required`, resuelve plantilla con 1.3, comprueba que no haya tarea
  viva para esa reserva, deriva `scheduled_start` del checkout efectivo y `scheduled_end` del
  check-in de la siguiente reserva confirmada, y devuelve `None` en cada caso de «no procede».
  La plantilla y la propiedad llegan ya resueltas dentro del tenant —el llamante es el job, que
  las obtuvo de repositorios con `tenant_id`—, y el caso de uso **no** acepta un identificador
  sin resolver: los INSERT no tienen red (`core/db.py:99-101`) y `add` solo comprueba
  `task.tenant_id` (obligación derivada de D6, panel de las secciones 2-3).
  Tests con fakes cubriendo los cinco caminos de `None`. [R2.1, R2.2, R2.4, R2.5, R2.6]
- [x] 4.2 Mismo caso de uso — auto-asignación: si el tenant tiene **exactamente una** persona
  con rol `CLEANER` y estado `ACTIVE`, asigna, pasa a `ASSIGNED` y prepara el disparo de
  `CLEANER_ASSIGNED`; con cero o más de una, deja `CREATED`. Excluye a quien haya rechazado
  una tarea de esa misma reserva (D3). Tests de los tres recuentos. [R3.1, R3.2]
- [x] 4.3 `backend/app/properties/application/use_cases.py` — `AdvancePropertyStatesUseCase`
  acepta `provisioner: CleaningProvisioningPort | None = None` e invoca
  `provision_for_checkout` tras cada transición aceptada de `CHECKOUT_TIME_REACHED`, **antes**
  del `commit`. Nuevo contador en `AdvanceReport` para «transicionada sin tarea» y su registro
  con `tenant_id`/`property_id`. Test que demuestra que un `None` del provisioner no aborta el
  resto del tenant, y que la suite existente de `celery-jobs` sigue verde con
  `provisioner=None` (D1). [R2.3, R2.4]
- [x] 4.4 `backend/app/scheduler/tasks.py` — `_advance` construye el provisioner cuando el
  trigger es `CHECKOUT_TIME_REACHED`; retirar del docstring de `process_checkouts` el párrafo
  que declara la deuda (`tasks.py:104-109`). Test de integración del job completo: checkout →
  `AWAITING_CLEANING` + `CleaningTask` en la misma transacción. [R2.1, R2.3]

## 5. Ciclo de vida de la tarea (API) <!-- panel: PENDIENTE — revisores colgados sin veredicto; ver BLOCKED.md OQ0, reanudar con /sdd:review -->

- [x] 5.1 `backend/app/auth/domain/policy.py` — `READ_CLEANING_TASKS`,
  `MANAGE_CLEANING_TASKS` y `EXECUTE_CLEANING_TASKS` con el reparto del design D7. [R7.4]
- [x] 5.2 `backend/app/audit/domain/actions.py` — `ENTITY_CLEANING_TASK` y las acciones
  `CLEANING_TASK_ASSIGNED`, `CLEANING_TASK_ACCEPTED`, `CLEANING_TASK_REJECTED`,
  `CLEANING_TASK_STARTED`, `CLEANING_TASK_COMPLETED`, `CLEANING_TASK_VALIDATED`, añadidas a
  `ENTITY_TYPES`/`ACTIONS` con el comentario que cita la regla 9 (D8). [R3.8]
- [x] 5.3 `backend/app/cleaning/application/use_cases.py` — un caso de uso por acción
  (`AcceptCleaningTaskUseCase`, `RejectCleaningTaskUseCase`, `StartCleaningTaskUseCase`): muta
  la entidad, construye `PropertyStateChangeRequest` con la tarea **ya mutada** en
  `PropertyTransitionContext.cleaning_tasks` y `source_entity_id` = id de la tarea, llama a
  `PropertyStateMachine.evaluate`, persiste transición + `TimelineEvent` + tarea, escribe el
  `AuditLog` con actor `USER` y commitea una sola vez. Tests con fakes. [R3.4, R3.5, R3.6, R3.8]
- [x] 5.4 `RejectCleaningTaskUseCase` — tras la transición, crea la tarea de reemplazo en
  `CREATED` sin asignar, misma propiedad/reserva/plantilla, en la misma transacción, y no la
  auto-asigna a quien rechazó. Test que verifica que la propiedad queda en `AWAITING_CLEANING`
  **con** una tarea viva (D3). [R3.5]
- [x] 5.5 `AssignCleaningTaskUseCase` para `PATCH /cleaning-tasks/{id}` — exige que la persona
  indicada tenga rol `CLEANER` en el tenant del token (`422` si no), asigna, dispara
  `CLEANER_ASSIGNED` y escribe el `AuditLog`. Test del `422` y del camino feliz. [R3.3, R3.8]
- [x] 5.6 `CreateCleaningTaskUseCase` para `POST /cleaning-tasks` (alta manual del manager):
  resuelve plantilla, respeta el índice parcial de 2.3 traduciendo el `IntegrityError` a
  `DuplicateLiveCleaningTaskError`. **Resuelve `property_id` y `reservation_id` por su
  repositorio con `tenant_id`** antes de construir la tarea — los INSERT no tienen red
  (`core/db.py:99-101`) y `add` solo comprueba `task.tenant_id` (obligación derivada de D6,
  panel de las secciones 2-3). Tests: la colisión del índice y **un `404` por cada uno de los
  tres identificadores** (`property_id`, `checklist_template_id`, `reservation_id`) — la
  obligación es prosa, así que la cobertura es lo único que la sostiene. [R2.5, R7.3]
- [x] 5.7 `GetCleaningTaskUseCase` y `ListCleaningTasksUseCase` — envelope paginado con las
  mismas cotas de `page`/`per_page` que `reservations`, filtros por propiedad y estado, y
  `restrict_to_cleaner_id` derivado del rol dentro del caso de uso, **nunca** de un parámetro
  de la petición (D7). Tests con los cinco roles. [R7.1, R7.2]
- [x] 5.8 `backend/app/cleaning/api/{router,schemas,dependencies}.py` — los ocho endpoints de
  tarea con `require(...)` en cada uno, summary/description para OpenAPI y schemas de
  respuesta. Tests de integración por endpoint. [R3, R7.6]

## 6. Checklist y cierre <!-- panel: PENDIENTE — revisores colgados sin veredicto; ver BLOCKED.md OQ0, reanudar con /sdd:review -->

- [x] 6.1 `GetChecklistUseCase` + `GET /cleaning-tasks/{id}/checklist` — devuelve los ítems de
  la plantilla de la tarea con su estado de completado, respetando la restricción de fila del
  `CLEANER`. Test. [R4.1, R7.2]
- [x] 6.2 `CompleteChecklistItemUseCase` + `POST /cleaning-tasks/{id}/checklist/{item_id}/complete`
  — `404` si el `item_id` no pertenece a la plantilla, `409` si la tarea no está `IN_PROGRESS`,
  e idempotente frente a `uq_cleaning_checklist_completions_cleaning_task_id_item_id`. Tests de
  los tres casos. [R4.2, R4.3, R4.4, R4.5]
- [x] 6.3 `CompleteCleaningTaskUseCase` + `POST /cleaning-tasks/{id}/complete` — reúne la
  evidencia (ítems requeridos, completados, incidencias `CRITICAL` activas leídas de
  `incidents`), llama a `CleaningTask.complete`, dispara `CLEANING_COMPLETED` y deja que
  `ContextualStateResolver.after_cleaning_completion` decida el destino. Tests de los tres
  destinos (`AWAITING_CHECKIN`, `READY_FOR_NEXT_GUEST`, `VACANT_READY`), del `409` por
  checklist incompleto, del `409` por incidencia `CRITICAL` insertada directamente, y del
  `409` cuando hay reserva activa (`IncompatibleTransitionContextError`). [R5.1, R5.2, R5.3, R5.4]
- [x] 6.4 `ValidateCleaningTaskUseCase` — validación manual del manager: registra
  `validated_by_user_id`/`validated_at`, admite `WAIVED`, y escribe el `AuditLog`
  `CLEANING_TASK_VALIDATED`. Test. [R5.5]

## 7. Notificación de asignación y SLA <!-- panel: PENDIENTE — revisores colgados sin veredicto; ver BLOCKED.md OQ0, reanudar con /sdd:review -->

- [x] 7.1 Al pasar una tarea a `ASSIGNED` (por 4.2 o por 5.5), escribir una fila de
  `NotificationLog` con `notification_type = CLEANING_TASK_ASSIGNED`, `status = PENDING`,
  `related_type = "cleaning_task"`, `related_id` = id de la tarea y
  `sla_deadline_at = now + TenantConfig.sla_medium_minutes`, en la misma transacción.
  `subject`/`body` conforme al contrato vigente de la regla 11 — sin reenviar valores de
  otras filas, siguiendo `_escalation_row` (`notifications/application/use_cases.py:198-232`).
  Test del contenido y del plazo. [R6.1, R6.2, R6.6]
- [x] 7.2 Cuando no haya `CLEANER` activa a la que asignar, escribir la notificación al
  manager **sin** `sla_deadline_at`. Test. [R6.3]
- [x] 7.3 Test de integración de la cadena de escalado: fila `CLEANING_TASK_ASSIGNED` marcada
  `SENT` en el propio test (que es lo que hará el emisor de `access-notifications`), reloj
  pasado el plazo, `check_sla_breaches` → `SLA_BREACH` al `PROPERTY_MANAGER`. El test lleva el
  comentario que explica por qué el `SENT` es del test y no del código (D9, `BLOCKED.md` OQ1). [R6.5]
- [x] 7.4 Aceptar o rechazar **no** escribe una segunda notificación de asignación. Test que
  lo fija, con la nota de que el cierre real del SLA es de `access-notifications` (D9). [R6.4]

## 8. Autorización y aislamiento <!-- panel: cubierto por los paneles de las secciones 1-4 y por OQ0 -->

**Nota de ubicación, escrita al cerrar la sección**: estas cuatro tareas pedían ficheros
propios (`test_authorization.py`, `test_tenant_isolation.py`). La cobertura existe y es la que
piden, pero vive **junto al endpoint que la ejerce** en lugar de en ficheros aparte: separarla
habría duplicado los fixtures de arranque (asignar → aceptar → iniciar) que cada aserción de
autorización necesita para llegar al punto donde el permiso decide. Se anota aquí en vez de
mover el código porque el sitio del test es una decisión de forma y la cobertura es lo
verificable.

- [x] 8.1 Matriz completa por endpoint y por los cinco roles de PRD §6, incluidos los `403`
  esperados: `tests/cleaning/test_tasks_api.py::test_authorization_matrix` (los tres tipos de
  permiso) y `tests/cleaning/test_templates_api.py::test_authorization_matrix` (plantillas).
  `tests/test_route_authorization.py` sigue verde y su snapshot de rutas protegidas crece con
  las once nuevas. [R7.4]
- [x] 8.2 `404` y no `403` al referenciar recursos de otro tenant, endpoint por endpoint, con
  el cuerpo **idéntico** al de un id inexistente:
  `test_tasks_api.py::test_reading_another_tenants_task_is_a_404`,
  `::test_creating_against_another_tenants_property_is_a_404`,
  `::test_creating_against_another_tenants_reservation_is_a_404`,
  `::test_assigning_a_cleaner_of_another_tenant_is_refused`,
  `test_templates_api.py::test_a_property_of_another_tenant_answers_404`. [R7.3]
- [x] 8.3 Aislamiento propio de `cleaning_checklist_completions` —lectura y escritura desde el
  tenant A sobre una completion del tenant B—:
  `tests/cleaning/test_repositories.py::test_completions_of_another_tenant_are_invisible` y
  `::test_completions_of_another_tenant_are_unwritable`. Es la tabla que el filtro global no
  cubre, así que el `JOIN` es lo único que la protege (D6). [R7.5]
- [x] 8.4 Restricción de fila del `CLEANER`:
  `test_tasks_api.py::test_a_cleaner_sees_only_their_own_tasks`,
  `::test_a_cleaner_cannot_read_another_cleaners_task` y
  `::test_accepting_a_task_assigned_to_someone_else_is_a_404`. [R7.2]

## 9. Documentación

- [x] 9.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo; el workflow
  `api-contract` debe quedar verde. [R7.6]
- [x] 9.2 `docs/cleaning.md` — cómo se opera el flujo (alta automática, asignación, checklist,
  cierre y validación), con la limitación de fotos y la del SLA nombradas y enlazadas a sus
  entradas de roadmap. Enlazar desde `docs/README.md`.
- [x] 9.3 `README.md` raíz — la sección de estructura menciona el módulo `cleaning` con capa
  de aplicación y API.
- [x] 9.4 `docs/diagrams/2026-07-13_autohost-secuencia-limpieza.png` **revisado y conservado**,
  no regenerado, y la divergencia documentada en `docs/cleaning.md` §«El diagrama de secuencia».
  Dibuja el flujo completo de PRD §11, que sigue siendo el objetivo: recortarlo a lo construido
  borraría el destino que van a levantar `cleaning-photos-storage` y `access-notifications`. Las
  tres cosas que no existen hoy —`NotificationAdapter` enviando de verdad, la subida de fotos
  con su validación por IA, y la creación de la tarea colgando de `PropertyStateMachine` en vez
  del provisioner— quedan enumeradas en una tabla, así que nadie las busca en el código.

## 10. Verificación

- [x] 10.1 Suite completa en verde: `docker compose exec backend uv run pytest -q -rs` →
  **3547 passed, 35 skipped**. Los 35 saltados son los preexistentes de
  `tests/properties/test_state_machine.py:296` («declared policy pair»), no introducidos aquí.
- [x] 10.2 Esquema y migración: `alembic upgrade head` limpio, `alembic check` → *No new upgrade
  operations detected* (el índice parcial está declarado también en `__table_args__`), y
  `alembic downgrade base` baja hasta el vacío sin huérfanos, con `upgrade head` volviendo a
  aplicarlo todo.
- [x] 10.3 Contrato: `make openapi` regenerado y commiteado; las **diez** rutas de limpieza
  aparecen en `backend/openapi.json` y `tests/test_openapi_contract.py` está verde. El diff del
  fichero es grande porque `components.schemas` está ordenado alfabéticamente y los catorce
  esquemas nuevos desplazan el bloque; no hay ninguna línea *eliminada* de contenido.
- [x] 10.4 Comprobación manual del flujo de extremo a extremo contra el stack real, por HTTP,
  con `make bootstrap` + `process_checkouts` de verdad (el cuerpo del task Celery, no un
  helper de test). Verificado en orden: alta de plantilla `201` → job crea la tarea con
  `transitioned_without_task: 0` → asignación → `GET /cleaning-tasks` como limpiadora
  devolviendo **solo la suya** → `accept` → `start` → `complete` **rechazado con `409`
  enumerando `kitchen`** → tick del ítem `204` → `complete` `200` → `validate` como manager
  `200` → propiedad en `VACANT_READY`.
  Traza de auditoría observada: `CLEANING_TASK_ASSIGNED, ACCEPTED, STARTED, COMPLETED,
  VALIDATED`. Notificaciones observadas: `CLEANING_TASK_ASSIGNED` con plazo y
  `CLEANING_NO_RESPONSE` sin plazo, ambas `PENDING` (design D9).
  **Dos comportamientos se verificaron por accidente y merecen constar**: al repetir el script
  quedaron dos plantillas activas del tenant y la resolución las **rechazó** en vez de
  desempatar (R1.4, visto sobre datos reales), y al haber varias limpiadoras activas el job
  dejó la tarea en `CREATED` y avisó al manager (R3.2 + R6.3) en lugar de elegir por él.

## Registro de revisión

`/sdd:review cleaning` del 2026-08-06, panel de feature con cinco revisores y alcance
incremental (las secciones 1-4 solo por sus interacciones; las 5-7 a fondo, porque su panel de
sección se había caído sin veredicto). **i18n y cicd no se lanzaron**: los 43 ficheros del
change no tocan `frontend/`, `.github/` ni `infra/`, así que su alcance era vacío.

Primera ronda: tenancy PASS · seguridad PASS (2 bajos) · documentación FAIL (2) · arquitectura
FAIL (3) · QA FAIL (5) → **siete** tras deduplicar. Segunda ronda tras los arreglos: **los cinco
en PASS**.

Lo que cambió, y por qué importa más de lo que parece:

1. **Un defecto real de concurrencia (R4.4)** que arquitectura y QA encontraron por separado: el
   `upsert` del checklist era un *check-then-act* sin capturar `IntegrityError`, así que dos
   toques concurrentes del mismo ítem daban **500** en vez del `204` idempotente. Arreglado
   quitando la ventana —`ON CONFLICT DO UPDATE`, una sentencia— y no tratando su síntoma.
2. **R6.4 y R7.5 se recortaron en el proposal**, no se estiraron en el código: la cancelación del
   SLA viaja a `access-notifications` (no se puede construir sin el emisor que marque `SENT`) y
   el aislamiento de `cleaning_photos` a `cleaning-photos-storage` (la tabla no tiene aquí ni
   repositorio ni escritor). Ambas confirmadas por Jose.
3. **`CleaningTask.complete()`** era el único método del ciclo sin el guardián de asignataria.
4. **Tres huecos de test**, incluido uno que importaba: `test_authorization_matrix` afirmaba
   `!= 403`, así que habría pasado igual con un `500`.
5. **Dos endpoints sin `description`** y **dos artefactos de diseño desactualizados** respecto a
   lo entregado (la tabla de endpoints sin `/validate`, D8 enumerando seis acciones de siete).

Dos cosas que ningún revisor elevó a hallazgo y se arreglaron igual: la asignación manual ahora
exige `UserStatus.ACTIVE` —el camino automático ya lo hacía, y sin ello un manager podía dar
trabajo a alguien dado de baja— y se añadió el test cross-tenant de la consulta de incidencias.

Y una corrección a un test propio que conviene no olvidar: la primera versión del test de
carrera commiteaba al ganador antes de abrir la sesión del perdedor, de modo que **contra el
código viejo habría pasado igual**. Ahora usa `asyncio.gather` con las dos transacciones
abiertas a la vez, que es la única disposición en la que la carrera existe.
