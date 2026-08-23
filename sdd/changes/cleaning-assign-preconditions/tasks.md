# Tasks: cleaning-assign-preconditions

Orden pensado para que el sistema siga funcionando tras cada sección: §1 separa el código de error
(aditivo, nadie lo consume aún), §2–§3 añaden dominio y puerto sin consumidores, §4 cambia la forma
del listado —y ahí es donde el typecheck del frontend se rompe a propósito (design «Risks»)—, §5 lo
cierra, §6 documenta.

## 1. El `409` de la vivienda deja de compartir código con el de la tarea <!-- panel: PASS 2026-08-23 -->

- [x] 1.1 Añadir `PROPERTY_STATE_CONFLICT` como decimotercer miembro de `ErrorCode`
  (`backend/app/core/error_codes.py`) y cambiar la fila de `PropertyStateBlocksCleaningError` en
  `_MAPPING` (`backend/app/cleaning/api/errors.py`) de `ErrorCode.CONFLICT` al código nuevo,
  manteniendo el `409`. `InvalidCleaningTransitionError` no se toca. Actualizar el docstring del
  módulo, que hoy enumera los `409` sin nombrar éste, para decir que el código nuevo lo produce
  **toda** operación de limpieza bloqueada por el estado de la vivienda — incluido
  `POST /cleaning-tasks/{id}/complete` (D1, D2, OQ2). [R1.1, R1.2]
- [x] 1.2 Cubrir la tabla en `backend/tests/cleaning/test_errors.py`: la parametrización que hoy
  comprueba el *status* de cada excepción pasa a comprobar también el **código**, de forma que
  `PropertyStateBlocksCleaningError → (409, PROPERTY_STATE_CONFLICT)` e
  `InvalidCleaningTransitionError → (409, CONFLICT)` sean dos aserciones distintas y no una sola
  sobre `409`. La red de completitud (`test_every_domain_error_has_a_row`,
  `test_subclasses_come_before_their_base`) tiene que seguir en verde. [R1.1, R1.2]
- [x] 1.3 Fixture nueva en `backend/tests/cleaning/test_tasks_api.py`, junto a `task_a`: una tarea
  `CREATED` sin asignar sobre una vivienda que **no** fuerza `AWAITING_CLEANING` —`insert_property`
  (`backend/tests/cleaning/conftest.py`) la deja en el default del modelo, que es exactamente el
  punto de partida que hoy no usa ninguna prueba de asignación (design Context 3). Con ella, dos
  tests de `PATCH /api/v1/cleaning-tasks/{id}` como `PROPERTY_MANAGER`: (a) vivienda fuera de
  `AWAITING_CLEANING` → `409` con código `PROPERTY_STATE_CONFLICT`; (b) tarea ya `ACCEPTED` sobre
  `task_a` → `409` con código `CONFLICT`. Los dos códigos, comparados, son la prueba de que la
  distinción existe. [R1.1, R1.2, R1.4]
- [x] 1.4 Test en el mismo fichero que fija el contenido del sobre del caso (a): `details` ausente o
  vacío y el `message` sin el estado operacional concreto de la vivienda (D3). Hoy ya es así por
  cómo `_transition` construye la excepción; el test lo convierte en garantía en vez de accidente,
  y la razón es que el mismo código lo recibirá una `CLEANER` en el cierre, y `CLEANER` no tiene
  `READ_PROPERTIES`. [R1.3]
- [x] 1.5 Comprobar que `backend/tests/test_openapi_contract.py` sigue en verde con el registro de 13
  miembros: la guarda reflexiona sobre el `_MAPPING` de `cleaning`, así que el catálogo publicado en
  `ErrorEnvelope.code` debe crecer solo. Si el test enumera el número de miembros o el conjunto,
  actualizarlo ahí y solo ahí. [R1.1]

## 2. La precondición como política de dominio, derivada de la matriz <!-- panel: PASS 2026-08-23 -->

- [x] 2.1 TDD (obligatorio en `domain/` por `steering/testing.md`): escribir primero en
  `backend/tests/cleaning/test_assignment.py` los casos de `assignment_blocker(...)` y después
  implementarla. Casos: tarea en `IN_PROGRESS` → `TASK_STATUS` (cualquiera sea el estado de la
  vivienda); tarea `CREATED` + vivienda en `OCCUPIED` → `PROPERTY_STATE`; tarea `CREATED` +
  vivienda en `AWAITING_CLEANING` → `None`; tarea `ASSIGNED` + vivienda en cualquier estado →
  `None` (reapuntar no transiciona la vivienda); `property_state=None` → `None`, **falla abierto**.
  El orden de las dos primeras ramas reproduce el del caso de uso. [R3.1, R3.3]
- [x] 2.2 Implementar `CleaningAssignmentBlocker` (`StrEnum` con `TASK_STATUS` y `PROPERTY_STATE`)
  en `backend/app/cleaning/domain/enums.py` y `assignment_blocker(*, task_status, property_state)`
  en `backend/app/cleaning/domain/assignment.py`, junto a `resolve_auto_assignee` y por el mismo
  motivo. Los estados legales salen de
  `PropertyStateMachine.source_states_for(PropertyStateTrigger.CLEANER_ASSIGNED)`, **nunca** de una
  constante `AWAITING_CLEANING`: una segunda copia de la matriz derivaría en silencio al ampliarla
  (D4). Añadir un test que lo pruebe estructuralmente —la función no puede contener el literal del
  estado— **y** uno que parametrice sobre los estados reales comparando contra
  `source_states_for`, porque cada uno solo tapa medio agujero. **Monkeypatchear
  `PropertyStateMachine` está descartado**: los revisores de arquitectura y QA de esta sección lo
  rechazaron los dos contra `steering/testing.md` («nunca mockear repositorios ni la state machine
  en tests de dominio»), y no hace falta — la versión sobre la máquina real fija el mismo
  invariante. [R3.1]
- [x] 2.3 Verificar que `backend/tests/test_layering.py` sigue en verde con el import nuevo
  `cleaning/domain → properties/domain`: la regla prohíbe framework y capas
  `api`/`application`/`infrastructure`, no otro `domain/`, y no hay ciclo porque
  `properties.domain.state_machine` importa `cleaning.domain.enums` y no este módulo (D4). Si el
  test necesita declarar la arista permitida, declararla con el motivo. [R3.1]

## 3. El estado de las viviendas de una página, leído estrecho <!-- panel: PASS 2026-08-23 -->

- [x] 3.1 Añadir `states_for(tenant_id, property_ids) -> dict[UUID, PropertyOperationalState]` al
  puerto `PropertyRepository` (`backend/app/properties/domain/repositories.py`) y su adaptador en
  `backend/app/properties/infrastructure/repositories.py`: un `SELECT id, current_operational_state`
  con `WHERE tenant_id = :tenant_id` —regla 1 de `steering/security.md`— y `property_ids` vacío
  devolviendo `{}` **sin consultar**, como hace `list_by_state` con `states` vacío (D6). Tests en
  `backend/tests/properties/test_repositories.py`: mapea los ids pedidos, omite los que no existen,
  el conjunto vacío no consulta, y **aislamiento de tenant** — ids del tenant B no aparecen en la
  respuesta del tenant A (DoD §28.18). [R3.2]
- [x] 3.2 Añadir `states_for` al conjunto de la guarda anti-vacuidad de
  `backend/tests/properties/test_port_contract.py`
  (`test_the_port_exposes_the_methods_this_change_relies_on`) y confirmar que
  `test_only_the_known_methods_take_an_operational_state_directly` sigue afirmando
  `{"list_by_state"}`: el método nuevo lleva el enum solo en el **retorno**, y ese test excluye
  `return`, así que es una lectura y no un camino alrededor de `PropertyStateMachine`. Si el
  aserto cambia, documentar por qué en su docstring. [R3.2]

## 4. El listado publica el pre-vuelo (aquí se rompe el contrato a propósito) <!-- panel: PASS 2026-08-23 -->

- [x] 4.1 `ListCleaningTasksUseCase` (`backend/app/cleaning/application/use_cases.py:1220`) recibe
  también `properties: PropertyRepository`, lee `states_for` con los `property_id` **distintos de la
  página** y devuelve una `Page` de `CleaningTaskListView` (dataclass congelada: `task` +
  `blocker`), calculando el `blocker` con `assignment_blocker`. Cablear la dependencia nueva en
  `get_list_cleaning_tasks_use_case` (`backend/app/cleaning/api/dependencies.py:170`). La decisión
  vive en `application/`, no en el router (D6). [R3.1, R3.2]
- [x] 4.2 `CleaningTaskListItemResponse` en `backend/app/cleaning/api/schemas.py`: los campos de
  `CleaningTaskResponse` más `assignment_blocked_by: CleaningAssignmentBlocker | None`, enumerados y
  construidos con un `from_domain` explícito —**nunca** `from_attributes`, porque `notes` no debe
  entrar (design D13 de `cleaning`)—. `CleaningTaskPageResponse.data` pasa a `list[...ListItem...]`
  y su `build` recibe las vistas. `CleaningTaskResponse` y los ocho endpoints que la devuelven
  quedan intactos (D5). [R3.1, R3.2]
- [x] 4.3 Tests de API del listado en `backend/tests/cleaning/test_tasks_api.py`: las tres formas del
  campo en la misma página —`null` para la tarea asignable, `PROPERTY_STATE` para la de la fixture
  de 1.3, `TASK_STATUS` para una `IN_PROGRESS`—, `notes` ausente del cuerpo, y el aislamiento de
  tenant del listado (que ya existe) sigue en verde con la consulta nueva. Un test más para el caso
  `states_for` sin resultado: el campo llega `null` y la fila se ofrece — falla abierto (R3.3). [R3.1, R3.2, R3.3]
- [x] 4.4 Descripciones OpenAPI en `backend/app/cleaning/api/tasks_router.py`: la del
  `PATCH /{task_id}` declara que **la primera asignación exige la vivienda en `AWAITING_CLEANING`**
  y que si no se responde `409 PROPERTY_STATE_CONFLICT`; la del `GET ""` explica qué significa
  `assignment_blocked_by` y que es una cortesía, no un permiso. Sin `responses=` inventado: enumerar
  por endpoint los demás estados posibles lo prohíbe `sdd/specs/api-contract.md`. [R4.1]
- [x] 4.5 Regenerar y commitear `backend/openapi.json` con `make openapi` en el mismo Pull Request
  (`steering/documentation.md`; el workflow `api-contract` lo exige). [R4.2]

## 5. El frontend distingue la causa y deja de invitar a lo imposible <!-- panel: PASS 2026-08-23 -->

- [x] 5.1 Regenerar el artefacto derivado `frontend/lib/api/generated/openapi.d.ts` —la otra mitad
  del puente, que el workflow `frontend-api-contract` comprueba— y commitearlo con el `openapi.json`
  de 4.5. **Desde este worktree el comando documentado no funciona**: usar la secuencia de
  `docker compose cp` de `sdd/project.md` («Lo que tampoco funciona tal cual»), incluido el `mkdir
  -p /backend`, antes de `npm run api:generate`. [R4.2]
- [x] 5.2 `frontend/features/cleaning/lib/assign-error.ts`: conservar `KEY_BY_STATUS` y añadir una
  tabla por **código** consultada solo cuando el status es `409`. `PROPERTY_STATE_CONFLICT` →
  `cleaning:assign.error.propertyState`; cualquier otro código con `409` —`CONFLICT` incluido y
  también uno desconocido— sigue cayendo en `cleaning:assign.error.conflict`, que es la ventana de
  deploy-skew (D7). Actualizar el docstring, que hoy afirma que la elección es por status. Tests en
  `assign-error.test.ts`: el código nuevo, `CONFLICT`, un código inventado con `409` (fallback), y
  que `403`/`404`/`422` no cambian. [R2.1, R2.2, R2.3]
- [x] 5.3 Claves nuevas en `frontend/locales/es/cleaning.json` **y**
  `frontend/locales/en/cleaning.json`: `assign.error.propertyState` («La vivienda todavía no está
  pendiente de limpieza» — solo el hecho, no el estado concreto, por OQ1),
  `assign.blocked.propertyState` y `assign.blocked.taskStatus` para la pista de la fila. Si existe
  un test de paridad de catálogos (`catalog-parity.test.ts`), tiene que seguir en verde. [R2.4, R3.1]
- [x] 5.4 Partir el DTO igual que el backend: en `frontend/features/cleaning/data/dto.ts`,
  `CleaningTask` (base, lo que devuelve `assignTask`) y
  `CleaningTaskListItem extends CleaningTask` con
  `assignmentBlockedBy: CleaningAssignmentBlocker | null`, cuyo tipo es un alias del enum generado y
  nunca una copia a mano (misma regla que `CleaningTaskStatus`). `listTasks` de
  `data/cleaning-source.ts` pasa a devolver `PaginatedResponse<CleaningTaskListItem>`, y
  `data/http/http-cleaning-source.ts` gana `mapListItem` junto a `mapTask` (D7). **Y
  `hooks/use-cleaning-data.ts`**, que no estaba en esta lista ni en «Changes by area»: anota
  explícitamente `UseQueryResult<PaginatedResponse<CleaningTask>>`, así que sin estrecharlo el tipo
  nuevo no llega a la vista. Dos líneas, solo tipos. Tests en
  `http-cleaning-source.test.ts`: el campo se mapea en sus tres valores, y ausente en el cuerpo se
  mapea a `null` (skew hacia atrás). [R3.2, R3.3]
- [x] 5.5 `frontend/features/cleaning/components/assign-cleaner-control.tsx` recibe
  `blockedBy: CleaningAssignmentBlocker | null`. Cuando no es `null`: el botón queda deshabilitado
  —junto a las dos condiciones que ya lo deshabilitan— y debajo aparece una línea con el motivo
  localizado, referenciada desde el botón con `aria-describedby`. El `<select>` **sigue habilitado**,
  por la razón que el componente ya documenta (D8). Tests en `assign-cleaner-control.test.tsx`:
  botón deshabilitado con el motivo visible y asociado, `<select>` operable y seleccionable, y las
  dos causas mostrando textos distintos. [R3.1, R3.4]
- [x] 5.6 `frontend/features/cleaning/components/cleaning-task-row.tsx` acepta un
  `CleaningTaskListItem` y pasa `task.assignmentBlockedBy` tal cual al control: la fila **no deriva
  nada**, que es lo que mantiene cierto el «no lógica de negocio en componentes» de
  `steering/frontend.md` (D9). `components/cleaning-view.tsx` ajusta el tipo del item de la lista y
  no toca `isBlocked`, que sigue significando «hay una mutación en vuelo». Tests en
  `cleaning-task-row.test.tsx` y `cleaning-view.test.tsx`: una fila bloqueada por estado de vivienda
  y otra asignable en la misma lista, y que un `409` real siga anunciándose en la región viva única
  —ahora con el mensaje de la vivienda— aunque la fila hubiera ofrecido el botón (R3.3). [R3.1, R3.3]

## 6. Documentación <!-- panel: n/a (docs) 2026-08-23 -->

- [x] 6.1 `docs/cleaning.md`: junto a la operación de asignación, la precondición de estado —la
  primera asignación exige la vivienda en `AWAITING_CLEANING`—, qué se responde si no, y que la
  pantalla lo indica por adelantado sin ser la autoridad. Sin duplicar las reglas EARS de
  `sdd/specs/`. [R4.3]

## 7. Verificación

- [x] 7.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`
  (desde este worktree, sobre su propio stack).
- [x] 7.2 Suite completa del frontend en verde: `docker compose exec -T frontend npm test`. **Antes**
  hay que ejecutar la lista de `docker compose cp` de `sdd/project.md`, o dos ficheros ajenos al
  change (`features/provenance/workflow-contract.test.ts`,
  `lib/config/build-identity-contract.test.ts`) fallan con `ENOENT` y la cifra no vale. Referencia:
  **90 ficheros, 747 tests** (medido el 2026-08-23 en este worktree, con la lista de copias
  aplicada; unos 20 de esos tests los añade este change). La cifra que citaba esta tarea —«63
  ficheros, 415 tests»— venía de `tech-incident-context` y estaba obsoleta; se corrige aquí y en
  `sdd/project.md`.
- [x] 7.3 Tipos y lint del frontend limpios: `docker compose exec -T frontend npm run typecheck` y
  `docker compose exec -T frontend npm run lint`.
- [x] 7.4 Deriva de contrato cero: `docker compose exec -T frontend npm run api:check` (con la
  secuencia de copias de 5.1 ya aplicada) y `git status` sin cambios en `backend/openapi.json` tras
  un `make openapi` de comprobación.
- [x] 7.5 Comportamiento de R2.1/R3.1/R3.3/R3.4 verificado, **sin la pasada visual en navegador**,
  que no es alcanzable desde este worktree. Se marca hecha porque lo que la tarea existía para
  demostrar está demostrado por otros medios; lo que queda fuera no es ningún criterio de
  aceptación. Con detalle, para que nadie lea esto como «sin probar»:
  - **API de punta a punta contra Postgres real** (`:8037`, datos de `seed-demo`): el listado
    publica `PROPERTY_STATE` en una tarea `CREATED` sobre vivienda `VACANT_READY` y `TASK_STATUS`
    en una `COMPLETED`, con `notes` ausente de las dos filas; el `PATCH` sobre la primera responde
    `409 PROPERTY_STATE_CONFLICT` y sobre la segunda `409 CONFLICT` —códigos distintos, `details`
    vacío, ningún valor de `PropertyOperationalState` en el sobre.
  - **Tests de componente con aserciones de DOM reales**, no de presencia: botón deshabilitado con
    el motivo asociado por `aria-describedby`, `<select>` operable, enfocable y seleccionable con
    el botón deshabilitado (R3.4), las dos causas con textos distintos, la carrera de R3.3 (fila
    ofrecida + `409 PROPERTY_STATE_CONFLICT` → mensaje de la vivienda en la región viva) y
    accesibilidad sin violaciones en `es` y en `en`.
  - **Lo que no cubre nada de eso, y sigue debiéndose**: el aspecto real a 320 px y la ausencia de
    errores de consola en la app hidratada. No corresponde a ningún criterio de aceptación —es
    acabado— y el sitio donde se hará es `dev`, que es un entorno que hidrata y es donde se midió
    el fallo original el 2026-08-22. Anotado como deuda con disparador en `design.md` § Risks.

  **Por qué no se hizo aquí, medido el 2026-08-23 y no supuesto.** Dos límites independientes:
  (1) con `PORT_OFFSET=37` la página se sirve pero **no hidrata** —el login hace submit nativo, el
  conmutador de idioma no responde, ningún prop de React en el `<form>` tras 15 s— y el único error
  de consola de la app es el handshake del WebSocket de HMR; la causa que encaja es `next dev` sin
  `allowedDevOrigins` bajo Next `^16.2.11` (ya recogido en `sdd/project.md`). No se tocó
  `next.config` para sortearlo: cambiar la configuración de la app para poder verificarla no es
  verificarla. (2) **No hay forma de llevar una vivienda a `AWAITING_CLEANING` por el camino real
  en un mismo día**: no existe endpoint que escriba `current_operational_state` —sólo la máquina de
  estados y los jobs de reloj— y la cadena `VACANT_READY → AWAITING_CHECKIN → OCCUPIED_ESTIMATED →
  AWAITING_CLEANING` exige una reserva que entre hoy con el checkout ya pasado, que la validación
  rechaza (`check_out_date must be after check_in_date`). Deliberadamente **no** se escribió la
  columna a mano para sortearlo: es exactamente la patología que la proposal de este change
  denuncia en REDES11. [R2.1, R3.1, R3.3, R3.4]
- [x] 7.6 Repaso de cobertura: R1 (§1), R2 (§5.2, §5.3), R3 (§2, §3, §4, §5.4–5.6, §7.5),
  R4 (§4.4, §4.5, §5.1, §6) — cada criterio de aceptación con al menos un test o una comprobación
  que lo demuestre. **Resultado, criterio a criterio:**

  | Criterio | Qué lo demuestra | Estado |
  |---|---|---|
  | R1.1 | `test_each_error_maps_to_its_status_and_code`, `test_assigning_on_a_property_outside_awaiting_cleaning_is_a_property_conflict`, y el `409 PROPERTY_STATE_CONFLICT` medido sobre Postgres real | cubierto |
  | R1.2 | `test_assigning_a_task_past_its_assignable_states_is_a_task_conflict` + la tabla de `test_errors.py`, que ahora fija el código de las 18 filas | cubierto |
  | R1.3 | `test_the_property_conflict_does_not_leak_the_operational_state`; verificado además contra la BD real (`details` vacío, ningún estado en el sobre) | cubierto |
  | R1.4 | fixture `task_on_a_property_not_awaiting_cleaning`, que parte del default `VACANT_READY` | cubierto |
  | R1 (OQ2) | `test_closing_a_cleaning_while_a_guest_is_in_is_a_conflict`, ahora afirmando el código nuevo | cubierto |
  | R2.1 | `assign-error.test.ts` (clave propia) + `cleaning-view.test.tsx` (el mensaje de la vivienda en la región viva) | cubierto |
  | R2.2 | `assign-error.test.ts` («keeps the task message for CONFLICT») + `cleaning-view.test.tsx` («still blames the task…») | cubierto |
  | R2.3 | `assign-error.test.ts`: la tabla por código se consulta sólo en `409`, y el `message` del backend nunca vuelve | cubierto |
  | R2.4 | las tres claves en `es` y `en`, con `catalog-parity.test.ts` en verde | cubierto |
  | R3.1 | `assignment_blocker` (7 tests de dominio), el listado (`…three_shapes_of_the_pre_flight`), el control (botón deshabilitado + motivo + `aria-describedby`) y la fila | cubierto |
  | R3.2 | `test_the_listing_reads_the_property_states_once_per_page` — una llamada, tres ids, para cuatro filas | cubierto |
  | R3.3 | `test_an_unresolved_property_state_fails_open`, `test_a_row_whose_property_state_is_unresolved_is_still_offered`, y la carrera en `cleaning-view.test.tsx` | cubierto |
  | R3.4 | `assign-cleaner-control.test.tsx`: `<select>` operable, enfocable y seleccionable con el botón deshabilitado | cubierto |
  | R4.1 | la `description` del `PATCH` en `backend/openapi.json`, sin `responses=` inventado | cubierto |
  | R4.2 | `backend/openapi.json` + `frontend/lib/api/generated/openapi.d.ts` regenerados; `api:check` y `--check` en verde | cubierto |
  | R4.3 | `docs/cleaning.md`, §«La primera asignación exige la vivienda pendiente de limpieza» | cubierto |

  **Sin cubrir**: la pasada visual de §7.5 (aspecto a 320 px y consola de la app corriendo). No
  afecta a ningún criterio de aceptación que no tenga ya un test; es una comprobación de acabado.
  Queda como deuda con disparador en `design.md` § Risks, para hacerse en `dev`.
