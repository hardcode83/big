# Tasks: cleaning-stall-blocks-next-stay

Orden elegido para que el sistema siga funcionando tras cada sección: primero el dominio puro
(máquina de estados y detección, sin consumidores todavía), después los dos consumidores del
desajuste (job y lectura), después la salida de R3, y al final contrato y documentación.
TDD en `domain/` (`steering/testing.md`): las secciones 1 y 2 escriben el test antes del código.

Nada aquí está preexistente: `git status` sólo tiene los tres documentos del change y el
diagrama nuevo.

## 1. Máquina de estados: la salida nueva y el camino falso retirado <!-- panel: PASS 2026-08-23 -->

- [x] 1.1 Retirar `CLEANING_ASSIGNMENT_EXPIRED` de `backend/app/properties/domain/transition_enums.py`
  y sus tres apariciones de `backend/app/properties/domain/state_machine.py`: la fila
  `(CLEANING_SCHEDULED, …)` de `_POLICY` (línea 49), la tupla de triggers de limpieza de
  `_validate_trigger_preconditions` (línea 237) y su entrada del mapa `expected` (línea 242).
  Ajustar `backend/tests/properties/test_state_machine.py` en sus cinco puntos —catálogo
  cerrado de triggers (~79), mapa de estados de tarea por trigger (~130 y ~134), matriz
  esperada (~197), pares trigger/estado incompatible (~487) y mapa de estados origen (~495)—
  de forma que el catálogo cerrado sea la prueba de la retirada. [R4.1]
- [x] 1.2 Test de que ningún camino de lectura reconstruye el trigger como enum, en
  `backend/tests/properties/test_state_machine.py`: `metadata["trigger"]` se escribe como
  texto y nada en `app/` construye `PropertyStateTrigger(...)` a partir de datos, así que las
  filas históricas con el valor retirado no rompen ninguna lectura. Es el riesgo que el design
  declara para la retirada, y sin test es una afirmación. [R4.1]
- [x] 1.3 `ContextualStateResolver.after_cleaning_cancellation` en
  `backend/app/properties/domain/state_resolution.py`, delegando en
  `_contextual_reservation_cleaning` (el mismo que usa `INCIDENT_RESOLVED`), sin rama propia.
  Test primero en `backend/tests/properties/test_state_resolution.py`: con estancia activa
  devuelve `OCCUPIED_ESTIMATED`; con una tarea viva en el contexto devuelve
  `AWAITING_CLEANING`. [R3.2]
- [x] 1.4 `PropertyStateTrigger.CLEANING_CANCELLED` + tres filas de `_POLICY` desde
  `AWAITING_CLEANING`, `CLEANING_SCHEDULED` y `CLEANING_IN_PROGRESS` con conjunto permitido
  `CONTEXTUAL_STATES - {estado origen, CRITICAL_INCIDENT, MAINTENANCE_REQUIRED}` (enmendado en
  el panel de la sección 1: el conjunto de D7 se copió de `INCIDENT_RESOLVED`, cuyo resolvedor
  sí lee incidencias, y declaraba dos arcos inalcanzables), rama en `_destination` que llama al resolvedor de 1.3,
  y `CLEANING_CANCELLED: {CleaningTaskStatus.CANCELLED}` en el mapa `expected` de
  `_validate_trigger_preconditions`. Tests en `backend/tests/properties/test_state_machine.py`:
  las tres filas en la matriz esperada, el destino contextual, y que una tarea que no está
  `CANCELLED` es rechazada con `IncompatibleTransitionContextError`. [R3.1, R3.2]

## 2. Detección del desajuste como hecho propio (dominio puro) <!-- panel: PASS 2026-08-23 -->

- [x] 2.1 `PropertyStateMachine.is_due(request) -> bool` en
  `backend/app/properties/domain/state_machine.py`: corre `_validate_request` y
  `_validate_trigger_preconditions` y devuelve `False` ante
  `IncompatibleTransitionContextError`, **sin consultar `_POLICY`**. Test en
  `backend/tests/properties/test_state_machine.py`: para una vivienda en un estado que no es
  origen del trigger, `is_due` contesta `True` cuando la hora ha llegado mientras `evaluate`
  sigue lanzando `InvalidStateTransitionError` — que es exactamente la pregunta que hoy no se
  puede hacer. [R1.1, R1.3]
- [x] 2.2 `backend/app/properties/domain/stalls.py` nuevo: value object
  `BlockedTransition(property_id, reservation_id, trigger, blocking_state, due_since)` y
  `detect(property, reservations, now, checkin_window)`, que combina `is_due(...)` con
  `state not in PropertyStateMachine.source_states_for(trigger)` —más la pinza de
  `opens_checkin_window` para `CHECKIN_WINDOW_OPENED`, enmendada en D2 tras el panel de la
  sección 2, y **más la evidencia `applied`**, enmendada en D1 tras el panel de la sección 3
  porque sin ella la definición reportaba toda la cartera activa—. Sin I/O y sin comparar horas
  por su cuenta: `applied` llega como parámetro. Nuevo `backend/tests/properties/test_stalls.py`: el caso REDES11
  (`CLEANING_IN_PROGRESS` + reserva `CONFIRMED` iniciada tres días antes → un
  `BlockedTransition` con `CHECKIN_TIME_REACHED`, el estado que bloquea y `due_since` en el
  inicio efectivo); una vivienda en estado origen no produce nada; la hora no vencida no
  produce nada; dos reservas solapadas producen dos entradas distintas por su clave
  `(property_id, reservation_id, trigger)`. [R1.1, R1.3]
- [x] 2.3 Comprobar que `backend/tests/test_layering.py` sigue verde sin excepciones nuevas:
  `stalls.py` es Python puro y no importa `application/` ni `infrastructure/`. Es la razón por
  la que el módulo vive en `domain/` (design D1) y sólo cuenta si el test lo prueba. [R1.3]

## 3. El job de reloj cuenta el desajuste <!-- panel: PASS 2026-08-23 -->

- [x] 3.1 `AdvanceReport.blocked: int` en
  `backend/app/properties/application/use_cases.py`, con el comentario que dice **por qué está
  fuera de `candidates`** y que `not_eligible` sigue significando «la hora no ha llegado», en
  la misma forma en que el dataclass ya documenta `ambiguous` y `unresolvable_time`. Llega
  solo al resultado de las tareas Celery porque `scheduler/tasks.py` serializa el informe con
  `asdict`. [R1.2]
- [x] 3.2b `PropertyStateTransitionRepository.applied_clock_triggers(tenant_id, reservation_ids)`
  —puerto, adaptador SQLAlchemy sobre `metadata->>'reservation_id'`/`->>'trigger'`, y doble en
  memoria derivado de las filas realmente añadidas—, con sus tests contra la base de datos real
  en `backend/tests/properties/test_repositories.py`, aislamiento por tenant incluido. Añadida
  por la enmienda de D1 del panel de la sección 3: es la evidencia de `applied`. El trigger
  vuelve como **texto**, nunca como enum, para no estrenar el camino de lectura que la retirada
  de D10 depende de que no exista. [R1.1]
- [x] 3.2 Segunda consulta en `AdvancePropertyStatesUseCase.execute`
  (`backend/app/properties/application/use_cases.py`): `list_by_state` por el **complemento**
  de `source_states_for(trigger)`, sus reservas por la misma `candidate_window` que ya usa
  `_reservations_by_property`, y `detect` sobre cada una. Cada vivienda con desajuste
  incrementa `report.blocked` y ningún otro cubo. Tests en
  `backend/tests/properties/test_advance_states.py`: la vivienda atascada da `blocked == 1`,
  `not_eligible == 0` y `candidates` sin tocar; una vivienda candidata normal no incrementa
  `blocked`; dos reservas solapadas sobre la misma vivienda cuentan **una** vivienda.
  [R1.1, R1.2, R1.3, R1.4]
- [x] 3.3 Log `logger.warning("scheduler.blocked_transition", extra={tenant_id, property_id,
  reservation_id, trigger, blocking_state, due_since})`, uno por desajuste, con la misma forma
  que `scheduler.unresolvable_reservation_time`. Test con `caplog` en
  `backend/tests/properties/test_advance_states.py` que comprueba los seis campos: es lo que
  satisface «identificando la vivienda, la reserva, el trigger y el estado que lo impide» en
  el lado del job. [R1.1]

## 4. La colección consultable: llega a quien puede actuar

- [ ] 4.1 `ListBlockedTransitionsUseCase` en
  `backend/app/properties/application/use_cases.py`: `PropertyRepository.list_all` +
  `TenantConfigRepository.get_or_create` para la ventana de check-in + `detect` sobre los tres
  triggers de reloj, **sin persistir nada**, y paginación del **resultado** (no de la fuente).
  Tests de caso de uso en `backend/tests/properties/test_stalls.py` o fichero propio: el
  desajuste aparece; al cancelar la tarea deja de aparecer sin ninguna escritura (R2.4); una
  vivienda atascada que caería en la página 3 de la fuente sigue apareciendo. [R2.1, R2.4]
- [ ] 4.2 `GET /api/v1/blocked-transitions`: **router propio** en
  `backend/app/properties/api/router.py` (el que ya está lleva `prefix="/properties"` y un
  segmento literal ahí colisiona con `/properties/{id}`), su respuesta y sobre paginado en
  `backend/app/properties/api/schemas.py` con la forma `build(...)` y el `MAX_PER_PAGE` que ya
  usan las demás colecciones, su proveedor en `backend/app/properties/api/dependencies.py`, y
  un segundo `include_router` en `backend/app/main.py`. Permiso `READ_PROPERTIES` (D6, que
  enmienda R2.1). `trigger` y `blocking_state` viajan como literales canónicos, sin prosa.
  [R2.1, R2.2]
- [ ] 4.3 Nuevo `backend/tests/properties/test_blocked_transitions_api.py`: `PROPERTY_MANAGER`
  y `TENANT_OWNER` la leen; una `CLEANER` recibe `403`; **un usuario del tenant B no ve el
  desajuste del tenant A** (regla 1 de `steering/security.md`, DoD §28.18); el cuerpo lleva
  `trigger`, `blocking_state` y `due_since`; el sobre paginado tiene el `total` de desajustes.
  [R2.1, R2.2, R2.3]

## 5. Una limpieza que no puede cerrarse tiene salida

- [ ] 5.1 `CleaningTask.cancel(now, reason)` en `backend/app/cleaning/domain/entities.py` con
  `_require_status(LIVE_STATUSES, "cancel")` → `CleaningTaskStatus.CANCELLED`. Test primero en
  `backend/tests/cleaning/test_entities.py`: cada estado de `LIVE_STATUSES` se cancela; un
  estado terminal y `PENDING_REVIEW` lanzan `InvalidCleaningTransitionError` **con el estado en
  el mensaje** (la divergencia declarada en D9 respecto a la palabra «terminal» de R3.4).
  [R3.1, R3.4]
- [ ] 5.2 `audit_actions.CLEANING_TASK_CANCELLED` en
  `backend/app/audit/domain/actions.py`: la constante y su alta en el `frozenset` `ACTIONS`,
  que es exhaustivo. [R3.3]
- [ ] 5.3 `CancelCleaningTaskUseCase` sobre `_TaskLifecycleBase` en
  `backend/app/cleaning/application/use_cases.py`, con la plantilla exacta de
  `RejectCleaningTaskUseCase` y este orden en una sola transacción: `task.cancel()` → tarea de
  reemplazo si procede → `self._transition(..., trigger=CLEANING_CANCELLED,
  with_reservations=True)` → `AuditLog` → un solo `commit`. Las dos excepciones al reemplazo
  (D8): **no** se crea con una estancia activa en `now`, ni si ya hay otra tarea viva de la
  misma reserva. `NoOperationalStateChangeError` no es error: se cancela la tarea, la vivienda
  no se mueve y queda en el log. [R3.1, R3.2, R3.3]
- [ ] 5.4 Nuevo `backend/tests/cleaning/test_cancel_task.py` con la cobertura que el design
  declara mínima: (a) el caso REDES11 de extremo a extremo — `CLEANING_IN_PROGRESS`, estancia
  del 19→23 corriendo, `cancel` → la vivienda queda en `OCCUPIED_ESTIMATED` y **no** hay tarea
  de reemplazo; (b) sin estancia activa → `AWAITING_CLEANING` **con** reemplazo sin asignar;
  (c) con otra tarea viva de la misma reserva → sin reemplazo y sin `IntegrityError`;
  (d) `property_state_transitions`, `timeline_events` y `audit_logs` tienen su fila y
  `current_operational_state` no se escribió por fuera de la máquina; (e) la evidencia parcial
  —ítems de checklist y fotos— sigue entera después de cancelar. [R3.2, R3.3, R3.5]
- [ ] 5.5 `POST /api/v1/cleaning-tasks/{task_id}/cancel` en
  `backend/app/cleaning/api/tasks_router.py` con `ManageDep` (`MANAGE_CLEANING_TASKS`), cuerpo
  `{"reason": str}` obligatorio y no vacío en `backend/app/cleaning/api/schemas.py`, proveedor
  en `backend/app/cleaning/api/dependencies.py`, respuesta `CleaningTaskResponse`. El `409` de
  tarea no viva y el de `PropertyStateBlocksCleaningError` salen del mapeo que
  `backend/app/cleaning/api/errors.py` ya tiene. Tests en
  `backend/tests/cleaning/test_tasks_api.py`: `409` sobre una tarea ya cancelada **sin escribir
  ninguna fila**; `422` con `reason` vacío; `404` desde otro tenant; `403` para una `CLEANER`.
  [R3.1, R3.4]

## 6. Contrato y documentación

- [ ] 6.1 Regenerar las **dos mitades** del contrato y commitearlas en el mismo PR
  (`steering/documentation.md`): `make openapi` para `backend/openapi.json`, y
  `frontend/lib/api/generated/openapi.d.ts` con el procedimiento de worktree de
  `sdd/project.md` §Worktree bootstrap (el `cd frontend && npm run api:generate` literal no
  corre aquí). Comprobar que las dos operaciones nuevas aparecen con su esquema de respuesta
  campo a campo y con sus códigos de error declarados. [R2.1, R3.1]
- [ ] 6.2 `docs/celery-jobs.md`: el cubo `blocked`, que no es `not_eligible` y por qué, y la
  ventana de detección —la misma `candidate_window` de 30 días atrás y 2 adelante— **con su
  consecuencia dicha en voz alta**: un atasco de más de 30 días deja de aparecer. En el mismo
  fichero, la retirada de `CLEANING_ASSIGNMENT_EXPIRED` y las razones de D10, para que el
  siguiente lector no la reintroduzca como olvido; la constancia en
  `sdd/specs/timeline-state-machine.md` la escribe `/sdd:archive` (ver *Affected specs*).
  [R1.2, R1.4, R4.1, R4.3]
- [ ] 6.3 `docs/cleaning.md`: la operación de cancelación —quién puede, qué le pasa a la
  vivienda, cuándo se crea tarea de reemplazo y cuándo no— y que la **evidencia parcial se
  conserva entera**, ítems y fotos, con las tres razones de D9. Enlazar la spec, no duplicarla.
  [R3.5]
- [ ] 6.4 `docs/properties.md`: la colección `GET /api/v1/blocked-transitions` — qué significa
  cada campo, qué rol la ve, que desaparece sola cuando el atasco se resuelve, y la deuda
  declarada de `list_all` sin paginar en origen **con su palanca escrita** (filtrar por el
  complemento de estados origen por trigger, como hace el job). [R2.1, R2.2, R2.4]

## 7. Verification

- [ ] 7.1 Suite completa verde: `docker compose exec backend uv run pytest` desde el worktree,
  con su propio stack levantado (`make up`). Cifras reales, no la salida colapsada de rtk.
- [ ] 7.2 `backend/tests/test_layering.py`, `test_route_authorization.py`,
  `test_openapi_contract.py` y `test_unscoped_reads.py` verdes **sin añadir ninguna entrada a
  sus listas de excepciones**: las dos rutas nuevas declaran su permiso y no son anónimas, así
  que ninguna necesita allowlist.
- [ ] 7.3 Lint/typecheck con el comando del proyecto. **El proyecto no tiene ese comando** (ni
  `ruff` ni `mypy` en el contenedor, ni paso de lint en `.github/workflows/backend-tests.yml`);
  lo verificable y lo que se verifica es **cero `type: ignore` nuevos** en el código del change.
- [ ] 7.4 Contrato sin deriva: `make openapi` no deja diff y el `openapi.d.ts` regenerado
  tampoco (equivalente de `npm run api:check` según §Worktree bootstrap).
- [ ] 7.5 Comprobación manual del flujo con el stack del worktree, desde dentro del contenedor
  (`docker compose exec backend ...`, porque un worktree no publica puertos): sembrar una
  vivienda en `CLEANING_IN_PROGRESS` con una estancia activa → `GET /api/v1/blocked-transitions`
  la muestra con su trigger y su estado bloqueante → `POST /cleaning-tasks/{id}/cancel` →
  la vivienda queda en `OCCUPIED_ESTIMATED` y la colección vuelve vacía sin tocar nada más.
- [ ] 7.6 Un tick real del job sobre esa misma vivienda antes de cancelar
  (`check_checkin_windows` / `mark_occupied_estimated`) devuelve `blocked: 1` con
  `candidates: 0` y `not_eligible: 0` — que es literalmente el informe vacío del 2026-08-22
  dejando de estar vacío.

## Cobertura de requisitos

Todos los criterios tienen al menos una tarea, con una única excepción declarada: **R4.2 queda
vacío por su propia condición**. Es un `WHERE se elija el emisor` y D10 eligió la retirada, así
que no hay plazo que derivar de `TenantConfig.sla_medium_minutes`; la necesidad operativa que lo
motivaba ya la cubre `EscalateBreachedSlasUseCase`, que **usa** ese mismo campo. No es un hueco
de la implementación: es la rama no tomada de un requisito con dos salidas.
