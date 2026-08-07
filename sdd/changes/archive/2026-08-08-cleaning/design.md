# Design: cleaning

## Context

`backend/app/cleaning/` tiene hoy `domain/entities.py` (cuatro dataclasses sin métodos),
`domain/enums.py` e `infrastructure/models.py`, y **nada más**: ni `application/`, ni `api/`,
ni puertos de repositorio. Es la forma que `steering/backend-architecture.md` §«Excepción:
dominios que todavía son solo estructura de datos» describe para las entidades nacidas en
`domain-foundation-ops`.

Todo lo que consume esas filas ya existe y está probado en vacío:
`PropertyStateMachine._POLICY` cubre las cinco transiciones de limpieza
(`state_machine.py:38-48`), `_validate_trigger_preconditions` exige que la tarea que va en
`PropertyTransitionContext.cleaning_tasks` tenga **ya** el estado esperado
(`state_machine.py:228-238`), `ContextualStateResolver` decide el destino tras completar
(`state_resolution.py:126-139`) y la política de escalado de `CLEANING_TASK_ASSIGNED` está
escrita (`notifications/domain/escalation.py:53-57`).

El precedente de módulo completo es `reservations`: `api/{router,schemas,dependencies,errors}.py`
+ `application/use_cases.py` + `domain/{entities,repositories,exceptions}.py` +
`infrastructure/repositories.py`, con una transacción por caso de uso vía
`SqlAlchemyUnitOfWork` (`core/unit_of_work.py:33`). Este change lo replica para `cleaning` y
añade el único punto realmente nuevo: cómo se compone el alta automática con un job que hoy
es dueño de su propia transacción.

## Decisions

### D1 — El alta al checkout entra por un puerto, no por el job ni por el router

**Chosen:** `AdvancePropertyStatesUseCase` recibe un colaborador **opcional**
`provisioner: CleaningProvisioningPort | None`, declarado en
`app/cleaning/domain/ports.py`, y lo invoca tras cada transición aceptada cuyo trigger sea
`CHECKOUT_TIME_REACHED`, **antes** de su `await self._uow.commit()` (`use_cases.py:140`).
Su implementación es `ProvisionCleaningTaskUseCase` en `cleaning/application/`.

Es lo único que satisface R2.3 sin romper el invariante que ese módulo declara en su propio
docstring («la transacción es el tenant, no la propiedad»): el commit sigue siendo suyo y
sigue siendo uno. `None` por defecto deja intactos `check_checkin_windows` y
`mark_occupied_estimated` y toda la suite existente de `celery-jobs`. La dirección de import
es la que ya usa ese módulo — `properties/application/` importa `ReservationRepository` de
`reservations/domain/` (`use_cases.py:55`) —, así que no abre un patrón nuevo.

Rejected: componer los dos casos de uso dentro de la tarea Celery — `scheduler/tasks.py` se
declara «el equivalente de un router» y orquestar flujo de negocio ahí es lo que
`steering/backend.md` prohíbe para los routers; además `execute` ya commitea, así que serían
dos transacciones y R2.3 se caería.
Rejected: que `AdvancePropertyStatesUseCase` devuelva los resultados y mueva el commit al
llamante — invierte la propiedad de la transacción de todo el scheduler para un solo trigger.
Rejected: eventos de dominio con despachador — no existe bus en el proyecto; introducirlo
para un consumidor es la sobreingeniería que `backend-architecture.md` §«Cuándo simplificar»
desaconseja.

**Y el provisioner hace una segunda transición, no solo la creación** — conviene nombrarlo
aquí porque una redacción anterior de D1 solo hablaba de crear la tarea, y quien leyera esta
decisión sola no lo esperaría (lo señaló el revisor de arquitectura de la sección 4). Cuando
auto-asigna, dispara `CLEANER_ASSIGNED` (`AWAITING_CLEANING` → `CLEANING_SCHEDULED`) sobre la
**misma** entidad `Property` que el llamante ya avanzó en memoria, y persiste su
`PropertyStateTransition` + `TimelineEvent` + la propiedad, todo dentro de la misma
transacción. Pasa por `PropertyStateMachine.evaluate` como cualquier otra transición
(`steering/architecture.md`: «el único lugar donde ocurren transiciones»), y la tarea entra en
el contexto **ya `ASSIGNED`** porque `_validate_trigger_preconditions` lee el estado de la
entidad que recibe (`state_machine.py:228-238`). Es el mismo patrón que usan los casos de uso
manuales de la sección 5, no una excepción de este.

### D2 — La idempotencia del alta la sostiene el esquema, no un `if`

**Chosen:** índice único **parcial** `uq_cleaning_tasks_live_reservation` sobre
`(tenant_id, reservation_id)` `WHERE reservation_id IS NOT NULL AND status IN ('CREATED',
'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS')`, más la comprobación previa en el caso de uso para
dar un error de dominio en vez de un `IntegrityError`.

**Cuatro estados y no cinco**: una redacción anterior incluía `PENDING_REVIEW`, y el panel de
la sección 1 lo señaló. `ContextualStateResolver` **no** lo cuenta como limpieza pendiente
(`state_resolution.py:143-147`), así que incluirlo aquí significaría una tarea que impide
crear su sucesora mientras la propiedad informa de que no tiene limpieza pendiente — la misma
clase de estado partido que dejó `AWAITING_CLEANING` terminal. Nada en este change produce
`PENDING_REVIEW`. La correspondencia entre el predicado y `LIVE_STATUSES` no es una promesa:
`tests/cleaning/test_live_task_index.py` extrae el predicado del modelo y compara conjuntos.

Parcial y no total porque una tarea `REJECTED` o `CANCELLED` debe poder convivir con su
reemplazo (D3) y una `COMPLETED` con una limpieza posterior de la misma reserva. R2.5 dice
«una segunda ejecución del job no crea una segunda tarea», y `process_checkouts` corre cada
5 minutos: dejarlo solo en el `if` es un *check-then-insert* que la primera concurrencia
rompe.

Rejected: unicidad total sobre `(tenant_id, reservation_id)` — impide el reemplazo tras
rechazo y cierra la puerta a una segunda limpieza legítima.
Rejected: solo la comprobación en el caso de uso — deja la invariante en la memoria del
llamante, que es justo lo que `pms-provider-resolution` documentó como caro de retrofitear.

### D3 — Rechazar es terminal para esa tarea y crea un reemplazo sin asignar

**Chosen:** `POST /reject` pone la tarea en `REJECTED` (terminal), dispara
`CLEANER_REJECTED` y, **en la misma transacción**, crea una tarea nueva en `CREATED` para la
misma propiedad, reserva y plantilla, sin `assigned_cleaner_id`. La auto-asignación de R3.1
**excluye** a quien haya rechazado una tarea de esa misma reserva.

**La fila rechazada conserva su `assigned_cleaner_id`** y esa columna es el registro de quién
rechazó — borrarla destruiría justo la evidencia con la que se justifica esta decisión. Quien
libera el hueco es la tarea de reemplazo, que nace sin asignar. R3.5 del proposal decía
«liberar `assigned_cleaner_id`» porque se redactó antes de esta decisión; se corrigió durante
la sección 1 del run.

Lo impone la máquina: `_validate_trigger_preconditions` exige `status is REJECTED` en el
instante de `evaluate` (`state_machine.py:232`), así que la tarea no puede volver a `CREATED`
antes de la transición. Y sin reemplazo la propiedad queda en `AWAITING_CLEANING` **sin
ninguna tarea viva**, con lo que `ContextualStateResolver` volvería a ver «sin limpieza
pendiente» (`state_resolution.py:146`) — exactamente el agujero que este change existe para
cerrar, reintroducido por la puerta de atrás. El reemplazo llega sin asignar, así que la
reasignación sigue siendo del manager y la reasignación **automática** sigue fuera de alcance.

Rejected: permitir `REJECTED → ASSIGNED` sobre la misma fila — pierde el registro de quién
rechazó y cuándo, que es la mitad del valor de un rechazo.
Rejected: dejar la tarea `REJECTED` sin reemplazo — deja el resolutor mintiendo mientras nadie
reasigne, y ese es un estado que ningún job repara.

**Confirmado por Jose el 2026-08-06**, al cerrar `/sdd:review`: se mantiene. El coste —una fila
por intento— no es desperdicio sino el registro de quién rechazó, que es la mitad del valor de
un rechazo; y la alternativa de reutilizar la fila exigiría decidir dónde se conserva ese
registro antes de poder aplicarse.

### D4 — La regla de validación de PRD §11 vive en la entidad

**Chosen:** `CleaningTask` gana métodos (`assign`, `accept`, `reject`, `start`, `complete`) y
deja de ser una dataclass de campos públicos. `complete()` recibe un value object
`CleaningCompletionEvidence` (ítems requeridos, ítems completados, incidencias `CRITICAL`
activas) y lanza `ChecklistIncompleteError` / `BlockingIncidentError`; el caso de uso solo
orquesta.

Es el ejemplo canónico que `steering/backend-architecture.md` usa **literalmente** para
explicar entidad con invariante (§DDD, `CleaningTask.complete()`), y `steering/testing.md`
exige TDD para «checklist de limpieza». Los campos siguen existiendo con los mismos nombres,
así que `state_resolution.py` y `state_machine.py`, que solo leen `.status`, `.tenant_id` y
`.property_id`, no se tocan.

Rejected: la regla en el caso de uso — es una regla de negocio, y `backend-architecture.md`
§Don'ts lo prohíbe explícitamente.

### D5 — La plantilla se resuelve por precedencia y la ambigüedad se rechaza en dominio

**Chosen:** función pura `resolve_template(candidates, property_id)` en `cleaning/domain/`:
plantilla activa de la propiedad; si no hay, la activa del tenant con `property_id IS NULL`.
Dos activas en el mismo nivel → `AmbiguousChecklistTemplateError` (409). Sin restricción de
base de datos.

Un índice único parcial sobre `(tenant_id, property_id) WHERE active` obligaría a desactivar
antes de activar en cualquier rotación de plantilla, que es una decisión de producto que nadie
ha pedido. Detectar y rechazar deja la ambigüedad visible y no restringe el flujo de edición.

Rejected: desempatar por `created_at` o por `id` — ancla el contenido del checklist a un
desempate arbitrario, que es el mismo razonamiento por el que `AdvancePropertyStatesUseCase`
cuenta `ambiguous` en vez de elegir reserva (`use_cases.py:201-215`).

### D6 — Las dos tablas sin `tenant_id` se scopean por `JOIN` obligatorio

**Chosen:** `CleaningChecklistCompletionRepository` y (más adelante)
`CleaningPhotoRepository` reciben `tenant_id` explícito como todos los demás puertos, y sus
adaptadores **siempre** hacen `JOIN cleaning_tasks ON id = cleaning_task_id AND
cleaning_tasks.tenant_id = :tenant_id`. Ningún método acepta solo `cleaning_task_id`.

`tenant_scoped_classes()` selecciona por columna `tenant_id` (`core/db.py:62`), así que el
filtro global de defensa en profundidad **no cubre** estas dos tablas: aquí no hay red, el
`JOIN` es el único mecanismo. De ahí que R7.5 exija test de aislamiento propio y no le baste
el genérico del módulo.

Rejected: añadirles `tenant_id` — revierte una decisión de esquema de `domain-foundation-ops`
tomada porque el PRD §7 no declara esa columna, y arrastra migración de datos.

**Obligación derivada para todo escritor de `cleaning_tasks`** (panel de seguridad de las
secciones 2-3): `CleaningTaskRepository.add` comprueba `task.tenant_id`, pero escribe
`property_id`, `checklist_template_id` y `reservation_id` tal como llegan, y el listener de
`app/core/db.py:99-101` documenta que **los INSERT no tienen red** — `session.add` no emite una
sentencia que el listener pueda reescribir. Así que cada uno de esos tres identificadores se
resuelve por su repositorio con `tenant_id` **en el caso de uso**, nunca se acepta a ciegas; es
la fila que ancla todos los `JOIN` de abajo, incluido el de la tabla sin red. Aplica a
`ProvisionCleaningTaskUseCase` (sección 4) y a `CreateCleaningTaskUseCase` (sección 5), y cada
uno lleva su test negativo **por identificador** — tres casos, no uno: es prosa, no un
mecanismo, así que la cobertura es lo único que la sostiene.

**Segundo residuo de la misma clase, y va aquí para que quien escriba encuentre los dos
juntos**: `SqlAlchemyCleaningChecklistTemplateRepository.add` escribe `template.items` tal
como llega, así que la normalización de las dos columnas `JSONB` es una propiedad del **caso
de uso** (`spec.items_as_json()`), no de la columna. Quien añada un segundo escritor de
plantillas normaliza igual, y el test que lo sostiene es de caso de uso con repositorio falso
—no de HTTP—, porque `extra="forbid"` en el schema hace que ninguna aserción sobre la API
pueda fallar: lo midió el panel de las secciones 2-3.

### D7 — Cinco permisos nuevos, y la restricción del `CLEANER` es por fila y no por permiso

**Chosen:** `Permission` gana `READ_CLEANING_TASKS`, `MANAGE_CLEANING_TASKS`,
`EXECUTE_CLEANING_TASKS`, `READ_CLEANING_TEMPLATES` y `MANAGE_CLEANING_TEMPLATES`. Reparto:

| Rol | Permisos de limpieza |
|---|---|
| `SUPER_ADMIN` | ninguno (mismo criterio que `reservations` design D7) |
| `TENANT_OWNER` | `READ_CLEANING_TASKS`, `READ_CLEANING_TEMPLATES`, `MANAGE_CLEANING_TEMPLATES` |
| `PROPERTY_MANAGER` | `READ_CLEANING_TASKS`, `MANAGE_CLEANING_TASKS`, `READ_CLEANING_TEMPLATES`, `MANAGE_CLEANING_TEMPLATES` (R1.1 lo nombra explícitamente) |
| `CLEANER` | `READ_CLEANING_TASKS`, `EXECUTE_CLEANING_TASKS` |
| `TECHNICIAN` | ninguno |

**`EXECUTE_CLEANING_TASKS` es exclusivo del `CLEANER`**, y una redacción anterior se lo daba
también al manager. Lo destapó el panel de seguridad de la sección 1 por su consecuencia:
`_require_assignee` responde `404` a quien no es la persona asignada, así que un manager con
ese permiso vería la tarea en el listado y recibiría un `404` al actuar sobre ella — una
respuesta incoherente que solo existía porque el permiso no debía estar ahí. R3.4, R3.5 y R3.6
dicen «la limpiadora asignada» sin excepción; lo que el manager necesita —reasignar, crear,
validar— lo cubre `MANAGE_CLEANING_TASKS`.

**Y esto precisa la semántica de R3.7**: el `409` de «estado que no la admite» aplica a quien
**sí** es la persona asignada. Quien no lo es no llega a esa comprobación y recibe `404`, que
es lo que R7.2 y R7.3 exigen. Las dos reglas no compiten: se ordenan.

La restricción de R7.2 («solo sus tareas») **no** es un permiso: el caso de uso recibe un
`restrict_to_cleaner_id` derivado del rol del token dentro del propio caso de uso, nunca de un
parámetro de la petición. Un permiso no puede expresar «solo las filas cuyo
`assigned_cleaner_id` sea el tuyo», y ponerlo en el router lo dejaría a merced de que cada
endpoint nuevo se acuerde.

Rejected: un `Permission.READ_OWN_CLEANING_TASKS` separado — el catálogo describe
capacidades, no predicados de fila; multiplicaría permisos por cada variante de scope.

### D8 — Las transiciones con actor `USER` escriben `AuditLog`

**Chosen:** se amplía el vocabulario cerrado de `audit/domain/actions.py` con
`ENTITY_CLEANING_TASK` y las acciones `CLEANING_TASK_ASSIGNED`, `CLEANING_TASK_ACCEPTED`,
`CLEANING_TASK_REJECTED`, `CLEANING_TASK_STARTED`, `CLEANING_TASK_COMPLETED`,
`CLEANING_TASK_VALIDATED` y `CLEANING_TASK_CREATED` — **siete**, no seis: el alta manual del
manager (`POST /cleaning-tasks`) también la dispara una persona, así que también se audita, y
una redacción anterior de esta decisión enumeraba solo las seis del ciclo de vida. Lo señaló el
revisor de arquitectura en `/sdd:review`. Las escriben los casos de uso con
`AuditLogFactory.build`, que es el único constructor legal (`audit/domain/services.py:25`).

No es opcional ni es celo: la regla 9 de `steering/security.md` exime del `AuditLog` a las
transiciones de estado de propiedad **solo con actor `SYSTEM`**, y dice explícitamente que
«una transición con cualquier otro actor —`USER`, `WEBHOOK` o `SCHEDULER`— NO está exenta».
Aceptar, iniciar, rechazar y completar los dispara una persona. El alta automática del
checkout va con actor `SYSTEM` y **sí** está exenta.

Rejected: apoyarse solo en `property_state_transitions` — es precisamente lo que la regla 9
acota al actor automático, y `audit_logs` aporta `actor_ip` y el índice por actor que un
repaso de incidente necesita.

### D9 — La notificación se escribe `PENDING`, y el escalado no se puede cerrar de extremo a extremo hoy

**Chosen:** el alta de la notificación de asignación usa `NotificationLogRepository.add` con
`status = PENDING`, `notification_type = CLEANING_TASK_ASSIGNED`,
`sla_deadline_at = now + sla_medium_minutes` y `related_type = "cleaning_task"`.

Aquí hay un hallazgo que obliga a recortar R6.5, y conviene no redondearlo:
`list_sla_breach_candidates` exige **`status = SENT`**
(`notifications/infrastructure/repositories.py:37`, y el docstring del puerto lo declara como
una de «las cuatro condiciones de PRD §14»), mientras que `add` documenta que las filas
nuevas llegan `PENDING` porque son «trabajo encolado para el emisor de
`access-notifications`». Nada en el repositorio pone `SENT`: **el emisor no existe todavía**.

Consecuencia medida, no supuesta: una notificación de asignación escrita por este change
**nunca** será candidata a escalado hasta que `access-notifications` la envíe y la marque.
R6.5 se reformula: el test demuestra la cadena completa marcando la fila como `SENT` en el
propio test —que es lo que hará el emisor— y la spec registra que en producción el escalado
queda inerte hasta ese change. Escribirla `SENT` desde aquí sería afirmar un envío que no ha
ocurrido, sobre una columna que `access-notifications` va a usar para decidir qué enviar.

**Y R6.4 se recorta con ello**: sin candidatos no hay nada que cancelar, y el puerto no tiene
método para modificar una notificación (`mark_breached` está deliberadamente acotado a
`sla_breached`, y su docstring dice por qué). Lo que este change hace al aceptar o rechazar es
**no escribir** una segunda notificación; el cierre real del SLA se diseña en
`access-notifications`, que es quien tendrá el emisor y el derecho a tocar `status`.
**Decidido por Jose el 2026-08-06**, al cerrar `/sdd:review`: se acepta y se documenta. Las
otras dos salidas se descartan por lo mismo que las hacía tentadoras — ampliar
`list_sla_breach_candidates` a `PENDING` cambia el comportamiento especificado de `celery-jobs`
desde un change que no es su dueño y le deja al emisor futuro filas ya escaladas, y adelantar
aquí un `NotificationAdapter` de consola crea el puerto en el change equivocado. El coste
aceptado, acotado y nombrado: entre este change y `access-notifications`, una limpiadora que no
responde no escala a nadie. La obligación viaja escrita en la entrada de roadmap de aquel
change, con su consecuencia.

Rejected: escribir `SENT` — miente sobre el envío y contamina la cola del emisor futuro.
Rejected: ampliar el filtro a `PENDING` — cambia el comportamiento especificado de
`celery-jobs` (`specs/celery-jobs.md`) desde un change que no es su dueño.

### D10 — `validation_status` se resuelve por regla determinista, sin IA

**Chosen:** un cierre que supera la validación deja `validation_status = PASSED` y
`ai_validation_result = NULL`; la validación manual del manager escribe
`validated_by_user_id`/`validated_at` y puede poner `WAIVED`. `FAILED` no lo produce nada en
este change.

`MockAIAdapter` es de `messaging-ai` (PRD §26.12) y `architecture.md` exige que todo sistema
externo entre por adapter: inventar aquí un `AIAdapter` para rellenar una columna sería
crear el puerto en el change equivocado.

### D11 — Errores de dominio → envelope de PRD §23 en un solo sitio

**Chosen:** `cleaning/api/errors.py` con el mismo patrón que
`reservations/api/errors.py:25-31`: tabla ordenada de `(excepción, status, ErrorCode)` y un
`@app.exception_handler(CleaningDomainError)` registrado en `main.py`. Mapeo completo — la
tabla es exhaustiva sobre la jerarquía de `cleaning/domain/exceptions.py`, y un error sin
entrada cae a 500, que es lo correcto para un bug nuestro pero nunca para uno previsto:

| Excepción | Status |
|---|---|
| `CleaningTaskNotFoundError` | 404 |
| `ChecklistTemplateNotFoundError` | 404 |
| `ChecklistItemNotFoundError` | 404 |
| `PropertyNotFoundError` | 404 |
| `InvalidCleaningTransitionError` | 409 |
| `ChecklistIncompleteError` | 409 |
| `BlockingIncidentError` | 409 |
| `AmbiguousChecklistTemplateError` | 409 |
| `DuplicateLiveCleaningTaskError` | 409 |
| `CleaningValidationError` | 422 |

`ChecklistTemplateNotFoundError` faltaba en una redacción anterior de esta tabla; lo detectó
el revisor de arquitectura de la sección 1, y sin él la sección 3 habría inventado el mapeo
al cablear el manejador.

### D13 — `notes` queda fuera de la superficie escribible de este change

**Chosen:** ningún endpoint de este change acepta `cleaning_tasks.notes` ni
`cleaning_checklist_completions.notes`; los casos de uso no los escriben y un test lo fija.

Las levantó el panel de seguridad de la sección 1 y el referente es la **regla 11** de
`steering/security.md`: su tabla enumera **seis** columnas y ninguna de estas dos está en
ella, mientras que este change es el primero que da capa de aplicación a esas tablas y pone
detrás a una limpiadora y a un manager. Una nota de campo es exactamente la forma que la
regla describe — texto libre humano donde acaba un código de acceso (reglas 3 y 4) o una
contraseña WiFi.

Abrirlas exigiría **ampliar la tabla de la regla 11**, y esa tabla se declara a sí misma «el
único sitio donde vive el contrato»: ampliarla es una decisión de steering, no un efecto
colateral de un endpoint. El proposal no pide escribir notas en ningún requisito, así que la
salida barata y honesta es no abrir el camino de escritura. Quien lo necesite —`field-apps`
es el candidato natural— añade la fila a la tabla en su propio change.

Rejected: aceptar `notes` en el `PATCH` y confiar en la revisión — es la forma exacta en que
la regla 11 dice que se pudren estas columnas.
Rejected: ampliar la tabla de la regla 11 aquí — decisión de steering sin requisito que la
pida en este change.

### D12 — Una sola migración, y solo para el índice

**Chosen:** una revisión de Alembic encadenada sobre la cabeza actual que crea
`uq_cleaning_tasks_live_reservation` (D2) y nada más. Ninguna tabla ni columna nueva: las
cuatro tablas existen desde `domain-foundation-ops` (`a1a72da30f8e`).

## Changes by area

| Area | Files | Change |
|---|---|---|
| `cleaning/domain` | `entities.py` | `CleaningTask` gana métodos y deja de exponer mutación libre (D4) |
| | `ports.py` *(nuevo)* | `CleaningProvisioningPort` (D1) |
| | `repositories.py` *(nuevo)* | Puertos de tarea, plantilla y completions (D6) |
| | `exceptions.py` *(nuevo)* | Jerarquía `CleaningDomainError` |
| | `value_objects.py` *(nuevo)* | `CleaningCompletionEvidence`, `ChecklistItemSpec` |
| | `templates.py` *(nuevo)* | `resolve_template` y validación de `items`/`required_photos` (D5, R1.2) |
| `cleaning/application` | `use_cases.py` *(nuevo)* | Provisión, asignación, accept/reject/start/complete, checklist, plantillas |
| `cleaning/infrastructure` | `repositories.py` *(nuevo)* | Adaptadores SQLAlchemy con `JOIN` de tenant (D6) |
| `cleaning/api` | `router.py`, `schemas.py`, `dependencies.py`, `errors.py` *(nuevos)* | Endpoints de PRD §23 menos los de fotos |
| `properties/application` | `use_cases.py` | `provisioner` opcional invocado antes del commit (D1) |
| `scheduler` | `tasks.py` | `process_checkouts` cablea el provisioner; docstring de la deuda retirado |
| `auth/domain` | `policy.py` | Cinco permisos y su reparto (D7) |
| `audit/domain` | `actions.py` | Entidad y **siete** acciones nuevas (D8) |
| `alembic` | `versions/<rev>_cleaning_live_task_unique.py` *(nuevo)* | Índice único parcial (D12) |
| `app` | `main.py` | Registro del router y del manejador de errores |
| `backend/tests` | `cleaning/` *(nuevo)* | Dominio (TDD), aplicación con fakes, integración de endpoints, aislamiento |
| docs | `docs/cleaning.md` *(nuevo)*, `README.md`, `openapi.json` | `steering/documentation.md` |

## Data & interfaces

**Esquema**: sin tablas ni columnas nuevas. Un índice: `uq_cleaning_tasks_live_reservation`.

**Endpoints** (todos bajo `/api/v1`, todos con `require(...)` — `tests/test_route_authorization.py`
lo verifica por recorrido):

```
GET    /cleaning-checklist-templates          READ_CLEANING_TEMPLATES
POST   /cleaning-checklist-templates          MANAGE_CLEANING_TEMPLATES
GET    /cleaning-tasks                        READ_CLEANING_TASKS   (CLEANER: solo las suyas)
POST   /cleaning-tasks                        MANAGE_CLEANING_TASKS
GET    /cleaning-tasks/{id}                   READ_CLEANING_TASKS   (idem)
PATCH  /cleaning-tasks/{id}                   MANAGE_CLEANING_TASKS
POST   /cleaning-tasks/{id}/accept            EXECUTE_CLEANING_TASKS
POST   /cleaning-tasks/{id}/reject            EXECUTE_CLEANING_TASKS
POST   /cleaning-tasks/{id}/start             EXECUTE_CLEANING_TASKS
POST   /cleaning-tasks/{id}/complete          EXECUTE_CLEANING_TASKS
POST   /cleaning-tasks/{id}/validate          MANAGE_CLEANING_TASKS
GET    /cleaning-tasks/{id}/checklist         READ_CLEANING_TASKS   (idem)
POST   /cleaning-tasks/{id}/checklist/{item_id}/complete   EXECUTE_CLEANING_TASKS
```

`POST`/`GET /cleaning-tasks/{id}/photos` **no se declaran**: son de
`cleaning-photos-storage`.

**`POST /cleaning-tasks/{id}/validate` tampoco está en PRD §23**, que se detiene en `complete`,
y faltaba en una redacción anterior de esta tabla — lo señaló el revisor de arquitectura en
`/sdd:review`. Es el mismo hueco del PRD que los endpoints de plantilla: R5.5 pide la validación
manual de PRD §11 y no hay ruta para ella. Se registra igual, marcado `ASSUMPTION` en el
proposal y con la convención de desviación de ADR 0005. La validación **automática** con
`MockAIAdapter` sigue siendo de `messaging-ai` (D10).

**Puerto nuevo**:

```python
class CleaningProvisioningPort(Protocol):
    async def provision_for_checkout(
        self,
        *,
        tenant_id: UUID,
        property: Property,
        reservation: Reservation,
        known_reservations: Sequence[Reservation],
        now: datetime,
    ) -> CleaningTask | None: ...
```

Devuelve `None` cuando no procede crear (config desactivada, `cleaning_required=False`, ya hay
una viva, o no hay plantilla resoluble), para que el informe del job pueda contarlo (R2.4).

`known_reservations` **no estaba en una redacción anterior de esta firma** y lo señaló el
revisor de arquitectura de la sección 4. Son las reservas que el job ya cargó para esa
propiedad en su ventana de candidatas: de ahí sale `scheduled_end` (R2.6), y pasarlas ahorra
una consulta por propiedad y mantiene el puerto libre de un `ReservationRepository`.

**Config/env**: ninguna variable nueva.

## Risks & mitigations

- **El provisioner rompe el job del checkout para todo el tenant.** `run_for_every_tenant`
  ya aísla el fallo por tenant y hace rollback (`scheduler/runner.py:139-148`), pero una
  propiedad sin plantilla no debe tumbar a las demás: por eso el puerto devuelve `None` en vez
  de lanzar, y solo las excepciones inesperadas escapan (R2.4).
- **`after_cleaning_completion` lanza si hay reserva activa** (`state_resolution.py:128-131`):
  cerrar una limpieza mientras el siguiente huésped ya está dentro devuelve 409 en vez de 500.
  El mapeo de D11 lo cubre y hay test.
- **La entidad deja de ser una dataclass abierta** (D4). Riesgo de romper a un lector
  existente: los únicos son `state_machine.py` y `state_resolution.py`, y solo leen tres
  campos. Verificado por `git grep`.
- **Coste del filtro global**: este change no añade clases con `tenant_id`, así que
  `tenant_scoped_classes()` no crece (sigue en 22) y la anotación de coste de `celery-jobs` no
  empeora.
- **Concurrencia del alta**: el índice parcial de D2 convierte una carrera en un
  `IntegrityError` que el caso de uso traduce a `DuplicateLiveCleaningTaskError`, no en una
  segunda tarea.

## Open questions

- **OQ1 — El escalado por SLA queda inerte hasta `access-notifications`** (D9). La cadena
  `CLEANING_TASK_ASSIGNED → SLA_BREACH` no puede dispararse porque el job exige `status = SENT`
  y nada marca `SENT`. Tres salidas: (a) aceptarlo y documentarlo, que es lo que este design
  hace por defecto; (b) ampliar `list_sla_breach_candidates` a `PENDING`, que cambia el
  comportamiento especificado de `celery-jobs` desde fuera de su change; (c) adelantar aquí un
  `NotificationAdapter` de consola, que invade `access-notifications`. Va a `BLOCKED.md`.
- **OQ2 — Rechazo terminal con reemplazo** (D3). Es la lectura que la máquina de estados
  fuerza, pero cambia la forma de la tabla con el tiempo (una fila por intento). La
  alternativa —reutilizar la fila— pierde el registro del rechazo. Va a `BLOCKED.md` por si
  se prefiere la otra.
