# Tasks: maintenance

Orden pensado para que el sistema siga funcionando tras cada sección: primero el dominio puro
(sin consumidores), luego los cambios en piezas compartidas (máquina de estados, auditoría,
permisos), después persistencia, casos de uso, job, API y por último contrato/documentación.

TDD obligatorio en `domain/` (`steering/testing.md`): el test que exige la invariante se escribe
antes que la implementación. En `infrastructure/` y `api/` los tests son de integración y van con
la tarea, no antes.

## 1. Dominio: errores, entidades e invariante del ciclo de vida <!-- panel: PASS 2026-08-15 -->

- [x] 1.1 Crear `backend/app/maintenance/domain/exceptions.py` con la jerarquía
  `MaintenanceDomainError` y las subclases que el flujo necesita (transición inválida, estado
  terminal, aprobación ya respondida, asignatario no válido, incidencia bloqueada por aprobación
  pendiente), calcada en forma de `app/cleaning/domain/exceptions.py`. Tests en
  `backend/tests/maintenance/test_exceptions.py` sólo si alguna lleva lógica de mensaje. [R4]
- [x] 1.2 (TDD) Escribir en `backend/tests/maintenance/test_entities.py` los tests que exigen la
  tabla `_TRANSITIONS` de `Incident`: cada transición legal del diagrama de *Data & interfaces*
  aceptada, y **cada** transición fuera de orden rechazada con el error de 1.1 y **sin mutar nada**.
  Incluye los estados terminales (`RESOLVED`, `CANCELLED`) como origen prohibido. [R4]
- [x] 1.3 Implementar en `backend/app/maintenance/domain/entities.py` la tabla `_TRANSITIONS`
  privada y los métodos de `Incident`: `classify`, `set_triage`, `require_owner_approval`,
  `resume_after_approval`, `assign`, `accept`, `start`, `wait_for_parts`, `resume_work`, `resolve`,
  `cancel`. Los campos siguen públicos (los leen `ReportGuestIncidentUseCase` y la máquina de
  estados) pero ningún caso de uso escribirá `status` (D5). [R1, R2, R3, R4]
- [x] 1.4 (TDD) Tests de `OwnerApproval.answer(...)` en el mismo fichero: registra `status`,
  `responded_at`, `responded_by`, `response_notes`; fija `approved_cost` sólo si `APPROVED`; y
  **rechaza responder dos veces** una aprobación ya resuelta. Implementarlo después en
  `entities.py`. [R2]
- [x] 1.5 (TDD) Tests y luego implementación de `classify` frente a la confianza: por encima del
  umbral fija `category`/`severity`/`ai_summary`/`ai_classification` y pasa a `CLASSIFIED`; por
  debajo deja `status = OPEN` con `category`/`severity` en defaults pero **con `ai_classification`
  escrita**, que es lo que distingue «confianza baja» de «recién creada» (D3). Ningún camino
  escribe `title` ni `description`. [R1]

## 2. Dominio: puertos, clasificación y SLA <!-- panel: PASS 2026-08-15 -->

- [x] 2.1 Añadir `IncidentClassification(category, severity, summary, confidence: Decimal)` como
  dataclass frozen en `backend/app/maintenance/domain/value_objects.py`, con validación de
  `confidence` en `0..1`. Test de validación en `backend/tests/maintenance/test_value_objects.py`.
  [R1]
- [x] 2.2 Crear `backend/app/maintenance/domain/ports.py` con los dos `Protocol` de un método:
  `IncidentClassifier.classify(*, title, description) -> IncidentClassification` (D1) y
  `LiveCleaningTaskQuery.list_live_for_property(tenant_id, property_id)` (D7). Docstring del
  primero fijando el contrato de D4: el `summary` **nunca** es eco de `title`/`description`. [R1]
- [x] 2.3 (TDD) Crear `backend/app/maintenance/domain/notifications.py` con la función pura
  `sla_minutes_for(severity, config)` que mapea `CRITICAL/HIGH/MEDIUM/LOW` a
  `TenantConfig.sla_{critical,high,medium,low}_minutes`, y los constructores
  `technician_assignment_notification(...)` (con `sla_deadline_at = now + minutes`,
  `related_type = "incident"`, `status = PENDING`) y `owner_approval_notification(...)` (**sin**
  `sla_deadline_at`, D12). Tests en `backend/tests/maintenance/test_notifications.py` cubriendo las
  cuatro severidades y la ausencia de plazo en la de aprobación. [R2, R3]

## 3. Máquina de estados de propiedades (D8, D9) <!-- panel: PASS 2026-08-15 -->

- [x] 3.1 (TDD) En `backend/tests/properties/` añadir el test de aceptación y el de rechazo de la
  precondición ampliada de `PropertyStateMachine._validate_trigger_preconditions`: `INCIDENT_RESOLVED`
  admite una incidencia en `RESOLVED` **y** en `CANCELLED`, y sigue rechazando cualquier otro
  estado. Implementar el cambio en `backend/app/properties/domain/state_machine.py`. [R2, R4]
- [x] 3.2 (TDD) Añadir a `_POLICY` las dos entradas que D8 declara omisiones, cada una con su test
  de aceptación y su test de rechazo (DoD §28.19): `VACANT_READY` + `INCIDENT_CRITICAL` →
  `CRITICAL_INCIDENT`, y `CLEANING_SCHEDULED` + `INCIDENT_HIGH` → `MAINTENANCE_REQUIRED`. [R4]
- [x] 3.3 Test que fija la tolerancia de D8 al nivel de la máquina: para los estados que **siguen**
  sin admitir `INCIDENT_HIGH`/`INCIDENT_CRITICAL` (`MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT`,
  `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE`) la máquina levanta su excepción — el que la tolera es el
  mixin de la sección 6, no la máquina. [R4]

## 4. Auditoría y permisos (piezas compartidas) <!-- panel: PASS 2026-08-15 -->

- [x] 4.1 En `backend/app/audit/domain/actions.py` añadir la entidad `ENTITY_OWNER_APPROVAL` y las
  diez acciones de D6 (`INCIDENT_CLASSIFIED`, `INCIDENT_TRIAGED`, `INCIDENT_ASSIGNED`,
  `INCIDENT_ACCEPTED`, `INCIDENT_STARTED`, `INCIDENT_WAITING_PARTS`, `INCIDENT_RESOLVED`,
  `INCIDENT_CANCELLED`, `OWNER_APPROVAL_REQUESTED`, `OWNER_APPROVAL_ANSWERED`). **Sustituir**, no
  borrar, el comentario de `actions.py:199-204` que hoy explica su ausencia: decir que este change
  es la puerta que ese párrafo describía. [R6]
- [x] 4.2 Ensanchar `AUDITABLE_FIELDS` en `backend/app/audit/domain/value_objects.py`:
  `INCIDENT` suma `category`, `severity`, `assigned_technician_id`, `owner_approval_required`,
  `estimated_cost`, `approved_cost`, `final_cost`, `resolved_at`; `OWNER_APPROVAL` entra con
  `{status, amount, related_type, responded_by, responded_at, approved_cost_applied}`. Test en
  `backend/tests/audit/` que **falla si aparece** `title`, `description`, `ai_summary`,
  `ai_classification`, `reason` o `response_notes` en el allowlist (R6.2, D4). [R6]
- [x] 4.3 En `backend/app/auth/domain/policy.py` añadir los cuatro permisos de D13 con su reparto
  exacto: `READ_INCIDENTS` (owner/manager/técnico), `MANAGE_INCIDENTS` (manager),
  `EXECUTE_INCIDENTS` (manager + técnico), `RESPOND_OWNER_APPROVALS` (owner). `CLEANER` y
  `SUPER_ADMIN` no reciben ninguno. Test en `backend/tests/auth/` que fija la matriz completa rol ×
  permiso, incluida la negativa de `CLEANER`. [R5]

## 5. Persistencia: repositorios y adaptadores <!-- panel: PASS 2026-08-15 -->

- [x] 5.1 Ampliar `backend/app/maintenance/domain/repositories.py`: `IncidentReader.list(...)`
  paginado con filtros `status`/`severity`/`property_id`/`assigned_technician_id`,
  `IncidentReader.list_active_for_property(tenant_id, property_id) -> Sequence[Incident]` (D7),
  `IncidentRepository.get/save`, y el puerto `OwnerApprovalRepository` (`get`, `add`, `save`,
  `find_approved_for_incident`). **Todos con `tenant_id` explícito** (D15). [R2, R4, R5]
- [x] 5.2 Implementar los adaptadores en
  `backend/app/maintenance/infrastructure/repositories.py`, incluido el de `LiveCleaningTaskQuery`
  sobre la tabla de `cleaning` (construcción simétrica a `BlockingIncidentQuery`, D7). Tests de
  integración en `backend/tests/maintenance/test_repositories.py`. [R2, R4, R5]
- [x] 5.3 Test de aislamiento de tenant de los repositorios nuevos, **sobre sesión no marcada con
  tenant** (D15, y por el riesgo conocido de que el listener global de `app/core/db.py` haga que el
  test no pueda fallar): un `tenant_id` no ve incidencias ni aprobaciones de otro. [R5]
- [x] 5.4 Crear `backend/app/maintenance/infrastructure/classifier.py` con
  `RuleBasedIncidentClassifier` determinista: categoría y severidad por reglas sobre el texto, y
  `summary` sacado de un **vocabulario cerrado por categoría**, nunca del texto de entrada (D4).
  Tests en `backend/tests/maintenance/test_classifier.py`: determinismo, cobertura de categorías, y
  un test que falla si el `summary` contiene una subcadena distintiva del `title`/`description` de
  entrada. [R1]

## 6. Casos de uso <!-- panel: PASS 2026-08-15 -->

- [x] 6.1 En `backend/app/maintenance/application/use_cases.py` añadir `IncidentActor` con
  `restrict_to_technician_id` (devuelve el id si el rol es `TECHNICIAN`, `None` si no — calcado de
  `CleaningActor`, D13) y `_AuditWriter`, que escribe `AuditLog` + `TimelineEvent` **en la misma
  transacción** que el cambio (R6.1), con actor `USER` o, para el job, sin actor y timeline `AI`
  (D6, D10). Tests unitarios de ambos. [R5, R6]
- [x] 6.1b Hacer estructural lo que R6.4 sólo pide por convención: `AuditLogFactory.build`
  admite hoy `actor_user_id = None` para **cualquier** acción, así que una clasificación manual
  cuyo caso de uso pierda el actor escribe una fila indistinguible de la del job, en una tabla
  append-only. *(Condición del panel de seguridad de la sección 4; complementa a 9.1b, que
  escribe la excepción en el steering pero no la hace cumplir.)*
  **Hecho en `_AuditWriter` y no en `AuditLogFactory`**: la factoría es el punto de paso de
  todos los módulos y hay cinco que escriben filas sin actor a propósito
  (`ACCESS_RECORD_CREATED`, `ACCESS_REVOKED`, `USER_PASSWORD_RESET` y `PMS_CREDENTIAL_ROTATED`
  desde línea de órdenes, `PMS_CREDENTIAL_READ` desde un sync), así que declarar allí el
  conjunto cerrado es re-decidir las exenciones de otros cuatro changes, y este no tiene
  potestad. Lo que sí puede —y hace— es que sus propias acciones no se puedan escribir de
  forma anónima por descuido. La versión a nivel de factoría queda como **candidata a change
  propio**. [R6]
- [x] 6.2 Añadir `_IncidentTransitionMixin` (calcado de `_TaskTransitionMixin`,
  `cleaning/application/use_cases.py:513-598`): carga la incidencia con el filtro del actor,
  construye `PropertyStateChangeRequest` con las **tres** colecciones que D7 exige (incidencias
  activas de la propiedad, reservas de la ventana, tareas de limpieza vivas), llama a
  `PropertyStateMachine.evaluate` y persiste `PropertyStateTransition` + `TimelineEvent` +
  `Property`. Nunca escribe `current_operational_state` directamente. [R4]
- [x] 6.3 En el mixin, capturar `NoOperationalStateChangeError`, `InvalidStateTransitionError` e
  `IncompatibleTransitionContextError`, dejar `logger.warning` y continuar (D8). Test: una
  incidencia `HIGH` sobre una propiedad en `BLOCKED_BY_OWNER` queda `CLASSIFIED` y la propiedad no
  se mueve, sin error. [R4]
- [x] 6.4 `ClassifyIncidentUseCase`: invoca `IncidentClassifier`, aplica el resultado por
  `Incident.classify`, audita y —si queda `CLASSIFIED` con severidad `HIGH`/`CRITICAL`— dispara
  `INCIDENT_HIGH`/`INCIDENT_CRITICAL` por el mixin. Si el adaptador falla o no responde, deja la
  incidencia en `OPEN` sin `ai_classification` y **no** la pierde ni la deja a medias (R1.6). Tests
  de las tres ramas (alta confianza, baja confianza, fallo del adaptador). [R1, R4, R6]
- [x] 6.5 `TriageIncidentUseCase` (`PATCH`): permite a owner/manager fijar o corregir `category` y
  `severity` mientras la incidencia no esté en estado terminal, y fijar `estimated_cost`. Si el
  coste estimado supera `TenantConfig.owner_approval_threshold_eur`, abre la **puerta del
  presupuesto** de D11: `OwnerApproval` en `PENDING` con `related_type = INCIDENT`,
  `owner_approval_required = True`, incidencia a `AWAITING_OWNER_APPROVAL` y notificación al
  propietario por `NotificationAdapter` con su `NotificationLog`. Por debajo del umbral, o sin
  coste, el flujo continúa sin crear nada. Tests de ambos lados del umbral. [R1, R2, R6]
- [x] 6.6 `RespondOwnerApprovalUseCase`: sólo `TENANT_OWNER`, sólo del propio tenant, sólo una vez.
  `APPROVED` fija `approved_cost` y devuelve la incidencia al estado que **se deriva del
  `related_type`** (`INCIDENT` → `CLASSIFIED`; `MAINTENANCE_COST` → `IN_PROGRESS`, D11);
  `REJECTED` la pasa a `CANCELLED` y dispara `INCIDENT_RESOLVED` por el mixin para recomponer el
  estado de la propiedad (posible gracias a 3.1). Tests de las cuatro combinaciones y de los tres
  rechazos de R2.6. [R2, R4, R6]
  *(Encargo del panel de seguridad de la sección 1)*: el `approved_cost` que llega a
  `Incident.resume_after_approval` tiene que ser **el valor que devolvió
  `OwnerApproval.answer`** y nada más — la entidad no puede comprobarlo porque la
  aprobación es otro agregado, así que esta es la costura donde R2.4 se cierra.
- [x] 6.7 `AssignIncidentUseCase`: fija `assigned_technician_id`, pasa a `ASSIGNED`, notifica al
  técnico y abre el plazo de SLA con `technician_assignment_notification`. Rechaza un asignatario
  cuyo rol no sea `TECHNICIAN` o que sea de otro tenant (leyendo por `UserRepository` dentro del
  tenant, como `AssignCleaningTaskUseCase`). Reasignar una incidencia no terminal **cancela el plazo
  anterior** con `cancel_sla_deadline` y abre el nuevo. Tests de asignación, reasignación y los dos
  rechazos. [R3, R6]
- [x] 6.8 Casos de uso del ciclo del técnico: `AcceptIncidentUseCase` (cancela el plazo pendiente,
  R3.3), `StartIncidentUseCase`, `WaitForPartsUseCase`, `ResumeWorkUseCase`. Cada uno delega el
  orden en la tabla de 1.3, audita y escribe su `TimelineEvent` según la tabla de D10
  (`WAITING_EXTERNAL_PARTS` **no** genera evento de timeline). Sólo el técnico asignado o un
  `PROPERTY_MANAGER` pueden conducirlas. Tests por transición, incluido el rechazo del técnico no
  asignado. [R4, R6]
- [x] 6.9 `ResolveIncidentUseCase`: exige `final_cost`, fija `resolved_at`, pasa a `RESOLVED` y
  dispara `INCIDENT_RESOLVED` por el mixin. Si `final_cost` supera el umbral y no está cubierto por
  una aprobación aprobada (`approved_cost is not None and final_cost <= approved_cost`), abre la
  **puerta del coste real** de D11: `OwnerApproval` con `related_type = MAINTENANCE_COST`,
  incidencia a `AWAITING_OWNER_APPROVAL` **sin** `resolved_at`, y no resuelve. Tests: resolución
  limpia, resolución cubierta por aprobación previa, y desbordamiento del umbral. [R4, R2, R6]
- [x] 6.10 Test de las cinco ramas de `ContextualStateResolver.after_incident_resolution`
  **conducidas desde `ResolveIncidentUseCase`**, no desde el resolver: limpieza viva, reserva
  activa, próxima reserva hoy, próxima reserva futura, y nada. Es la mitigación del riesgo funcional
  principal de D7 (un contexto incompleto da un destino plausible y equivocado sin fallar). [R4]
- [x] 6.11 `CancelIncidentUseCase` y los casos de uso de lectura (`ListIncidentsUseCase`,
  `GetIncidentUseCase`), con el filtro de `IncidentActor.restrict_to_technician_id` aplicado en el
  repositorio, no en el router (R5.3). [R4, R5]

## 7. Job de clasificación (D2) <!-- panel: PASS 2026-08-15 -->

- [x] 7.1 Añadir el job `classify_incidents` en `backend/app/scheduler/tasks.py`, idempotente y con
  el lock por job que `celery-jobs` ya provee: recoge las incidencias con
  `status = OPEN AND ai_classification IS NULL` (D3) y las pasa por `ClassifyIncidentUseCase`.
  Registrar su cadencia en `CADENCES` de `backend/app/scheduler/schedule.py`. [R1]
- [x] 7.2 Tests de integración del job en `backend/tests/scheduler/`: clasifica lo pendiente, **no
  reintenta** una de confianza baja (porque ya tiene `ai_classification`), **sí reintenta** una que
  falló (porque no la tiene), y su fila de `audit_logs` va con `actor_user_id`/`actor_ip` a `NULL` y
  su `TimelineEvent` con actor `AI` (D6). [R1, R6]

## 8. API del módulo (D14, R5) <!-- panel: PASS 2026-08-15 -->

- [x] 8.1 Crear `backend/app/maintenance/api/__init__.py`, `schemas.py` (Pydantic v2, request y
  response de las doce rutas), `errors.py` (tabla exhaustiva al estilo de `cleaning/api/errors.py`:
  `404` inexistente/otro tenant/no asignada a este técnico, `409` transición inválida y bloqueo por
  aprobación pendiente, `422` validación, con la envoltura `{error:{code,message,details}}` de
  PRD §23) y `dependencies.py` (construcción de casos de uso e `IncidentActor`). [R5, R4]
- [x] 8.2 Crear `backend/app/maintenance/api/incidents_router.py` con `prefix="/incidents"` y las
  once rutas de la tabla de D14 (diez cuando se escribió esta tarea; `cancel` se añadió a D14 durante el run), cada una con su `require(<permiso>)`. Listado paginado
  `?page&per_page`, fechas ISO 8601 UTC. **No hay `POST /incidents`** (D14). [R5, R1, R3, R4]
  *(Encargo del panel de seguridad de la sección 5)*: el puerto sólo pone el suelo
  (`page`/`per_page` ≥ 1); el **techo de `per_page`** va en el esquema, como en
  `cleaning/api/schemas.py`, o una sola petición se lleva la tabla de incidencias entera del
  tenant con sus descripciones dentro.
- [x] 8.3 Crear `backend/app/maintenance/api/approvals_router.py` con
  `POST /owner-approvals/{id}/respond` bajo `RESPOND_OWNER_APPROVALS`. [R2, R5]
- [x] 8.4 Registrar los dos routers bajo `API_V1_PREFIX` y el manejador de errores en
  `backend/app/main.py`, junto a los ocho que ya hay. [R5]
- [x] 8.5 Tests de integración de endpoints en `backend/tests/maintenance/test_api_incidents.py` y
  `test_api_approvals.py` (httpx `AsyncClient`): camino feliz de cada ruta, códigos de error de 8.1,
  y paginación. [R5, R4]
- [x] 8.6 Tests de autorización y aislamiento del API: un `TECHNICIAN` sólo ve y opera **sus**
  incidencias (una no asignada da el mismo `404` que una inexistente, R5.3); `CLEANER` recibe `403`
  en las doce rutas; un portador de token de huésped no alcanza ninguna; y una incidencia de otro
  tenant da `404` (R5.4). [R5]

## 9. Contrato, steering y documentación

- [x] 9.1 Añadir al censo de la regla 11 de `sdd/steering/security.md` las cuatro columnas de D4 —
  `incidents.ai_summary`, `incidents.ai_classification`, `owner_approvals.reason`,
  `owner_approvals.response_notes` — bajo la **forma estructurada por defecto**, no bajo la
  excepción 2, con el motivo escrito: el escritor es nuestro y el insumo es texto de un anónimo.
  *(Encargo del panel de seguridad de la sección 1)*: describir la forma de
  `ai_classification` por lo que el código impone —cuatro valores cerrados más un `adapter`
  que es un **identificador de Python**, y lo que no lo es degrada a `UNKNOWN_CLASSIFIER`—,
  sin prometer un vocabulario cerrado que nadie verifica.
  *(Segundo encargo, del panel de seguridad de la sección 5)*: la fila del censo tiene que
  decir la **condición de admisión de cualquier adaptador** de `IncidentClassifier` — que su
  `summary` salga de un vocabulario cerrado, con su test —, porque hoy D4 se cumple por la
  construcción del adaptador determinista y no por el tipo: `IncidentClassification.summary`
  es un `str` sin restringir, así que el segundo adaptador (un proveedor real) puede
  parafrasear la descripción del huésped y no lo para nada.
  [R1, R6]
- [x] 9.1b Añadir a la **regla 9** de `sdd/steering/security.md` la cuarta excepción nombrada
  que D6 necesita: la clasificación automática del job escribe su `AuditLog` **sin actor**
  (`actor_user_id`/`actor_ip` a `NULL`). La regla 9 dice de su segunda excepción que «este
  razonamiento **no es un criterio reutilizable**» y que ampliarla se hace «con una entrada nueva
  y nombrada aquí, aprobada en el design del change que la pida» — D6 la aprobó en el gate del
  2026-08-15 y el steering todavía no la recoge, así que hoy D6 se apoya en un precedente que la
  propia regla le niega. Acotarla como las otras tres: al actor y a la acción
  (`INCIDENT_CLASSIFIED` desde el job), diciendo qué **no** concede — la clasificación manual de
  un manager sí lleva actor. *(Levantado por el panel de seguridad de la sección 4.)* [R6]
- [x] 9.2 Regenerar `backend/openapi.json` con `make openapi` y commitearlo. [R5]
- [x] 9.3 Regenerar `frontend/lib/api/generated/openapi.d.ts` y commitearlo en el mismo PR. Desde el
  worktree el comando documentado no funciona: usar la salida verificada de `sdd/project.md`
  (`docker compose cp backend/openapi.json frontend:/backend/openapi.json`, `ln -sfn /app /frontend`
  dentro del contenedor, `npm run api:generate`) y confirmar con `api:check` dentro del contenedor.
  [R5]
- [x] 9.4 Crear `docs/maintenance.md`: cómo se opera el flujo de incidencias de punta a punta
  (clasificación automática y manual, triaje, aprobación de la propietaria, asignación y SLA, ciclo
  del técnico), enlazando a las specs en vez de duplicarlas. [R5]
- [x] 9.5 Actualizar el `README.md` de la raíz: `maintenance` pasa a ser un módulo con `api/`, y las
  secciones de estructura/tests deben reflejarlo. [R5]

## 10. Verificación

- [x] 10.1 Suite de backend completa en verde desde el worktree:
  `docker compose exec backend uv run pytest` (o `docker compose run --rm backend uv run pytest`
  con el stack parado).
- [x] 10.2 `docker compose exec backend uv run alembic check` — debe confirmar que **no hace falta
  ninguna migración** (*Data & interfaces*: las dos tablas ya existen con todas sus columnas).
- [x] 10.3 Cobertura de `domain/` ≥ 80 % en el módulo `maintenance` (PRD §4), y **toda** transición
  de la máquina de estados tocada en la sección 3 con su test de aceptación y su test de rechazo
  (DoD §28.19).
- [x] 10.4 Contrato sin deriva: `make openapi` no deja diff, y `npm run api:check` dentro del
  contenedor del frontend pasa (por la vía de 9.3).
- [x] 10.5 Comprobación manual del flujo completo contra el stack del worktree, por API (no hay UI
  ni puertos publicados desde un worktree): crear una incidencia por la vía del portal del huésped,
  dejar que el job la clasifique, triarla con un `estimated_cost` por encima del umbral, aprobarla
  como `TENANT_OWNER`, asignarla a un `TECHNICIAN`, recorrer `accept → start → wait-parts → resume
  → resolve`, y verificar que la propiedad pasó por `MAINTENANCE_REQUIRED`/`CRITICAL_INCIDENT` y
  volvió al estado que le toca, con su rastro en `audit_logs` y en el timeline.
</content>
</invoke>
