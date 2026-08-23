# Design: cleaning-assign-preconditions

## Context

La asignación vive en `AssignCleaningTaskUseCase` (`backend/app/cleaning/application/use_cases.py:800`).
Solo la primera asignación —la de una tarea `CREATED`— llama a `_transition(...)` con
`CLEANER_ASSIGNED` (`use_cases.py:851-860`); reapuntar una tarea ya `ASSIGNED` no toca la vivienda.
Ese `_transition` (`use_cases.py:558-615`) traduce `InvalidStateTransitionError` /
`IncompatibleTransitionContextError` a `PropertyStateBlocksCleaningError`, y la tabla `_MAPPING` de
`backend/app/cleaning/api/errors.py` la responde `409` con código `CONFLICT` — **el mismo código**
que `InvalidCleaningTransitionError`, que es lo que emite `CleaningTask.assign` cuando la tarea no
está en `CREATED` ni en `ASSIGNED` (`domain/entities.py`). Dos causas, un código.

En el frontend, `features/cleaning/lib/assign-error.ts` elige el mensaje **por status HTTP**
(`KEY_BY_STATUS`), no por código, así que ambos `409` caen en `assign.error.conflict` («Esa tarea ya
no admite un cambio de asignación»). El `409` de la vivienda queda descrito como si fuera de la
tarea.

Tres hechos del código que corrigen o afinan la proposal, y que mandan sobre las decisiones de
abajo:

1. **La pantalla sí tiene el dato; lo que no tiene es la regla.** La proposal dice que
   «`GET /api/v1/cleaning-tasks` no devuelve el estado operacional de la vivienda», y es cierto —
   pero `PropertyListItemResponse` **sí** lo lleva (`backend/app/properties/api/schemas.py:319`) y
   la vista ya pide ese catálogo entero (`data/http/http-cleaning-source.ts`, `listProperties`,
   `per_page=100`). El mapeador simplemente lo descarta (`mapProperty` se queda con
   `id`/`name`/`internal_code`). Lo que falta en el cliente no es el estado: es saber **qué
   estados admiten `CLEANER_ASSIGNED`**, que es matriz de la máquina y no dato de vivienda.
2. **R1.3 no tiene tensión por el lado del manager.** `MANAGE_CLEANING_TASKS` lo tiene un único
   rol, `PROPERTY_MANAGER`, y ese mismo rol tiene `READ_PROPERTIES` (`_CLEANING_MANAGE` y
   `_PROPERTY_MANAGE` en `backend/app/auth/domain/policy.py:296-303`). Publicar el estado
   operacional a quien puede asignar no amplía nada. La tensión real está en otro sitio y la
   recoge D3.
3. **El fixture que la proposal sitúa en `conftest.py` está en `test_tasks_api.py:77`.** `task_a`
   fuerza `AWAITING_CLEANING` ahí; `insert_property` (`conftest.py:119`) no toca el estado, así que
   una vivienda recién insertada nace en el default del modelo — que es exactamente el punto de
   partida que R1.4 pide y que hoy no usa ninguna prueba de asignación.

`PropertyStateMachine.source_states_for(trigger)` ya existe (`state_machine.py:80-89`), lo añadió
`celery-jobs` para no escribir una segunda copia de la matriz, y devuelve `{AWAITING_CLEANING}`
para `CLEANER_ASSIGNED`.

## Decisions

### D1 — Un código propio en el registro `ErrorCode`, no un discriminador en `details`

**Chosen:** un decimotercer miembro de `ErrorCode` (`backend/app/core/error_codes.py`),
`PROPERTY_STATE_CONFLICT`, con status `409` intacto. El cambio es una fila de la tabla `_MAPPING`
de `cleaning/api/errors.py`: `PropertyStateBlocksCleaningError` deja de mapear a `CONFLICT`.
`InvalidCleaningTransitionError` se queda como está, que es literalmente R1.2.

El registro existe precisamente para esto: su propio docstring dice que se publica como `enum` en
`ErrorEnvelope.code` «para que un consumidor pueda hacer un `switch` exhaustivo comprobado por su
compilador», y `sdd/specs/api-contract.md` lo declara fuente única. El precedente es del mismo
dominio: `cleaning-photos-storage` añadió `BAD_GATEWAY` para distinguir «reintentar puede
funcionar» de «esto es un bug nuestro», con el argumento textual de que «son dos mensajes distintos
que enseñar a una limpiadora». Aquí son dos mensajes distintos que enseñar a un manager.

Rejected: discriminar con una clave en `details` — no está tipada por el contrato, y el frontend
tendría que leer el cuerpo del error, que es justo lo que `assign-error.ts` evita hoy.
Rejected: un status nuevo (`422`, `423`) — la causa es un conflicto de estado, `409` es correcto, y
mover el otro rompería R1.2.
Rejected: subclasear `PropertyStateBlocksCleaningError` para tener dos filas en `_MAPPING` — la
tabla está ordenada subclase-primero por una razón que ya documenta; añadir una jerarquía para
obtener un código es indirección sin dueño.

### D2 — El código nuevo cubre **toda** operación de limpieza bloqueada por el estado de la vivienda

**Chosen:** el discriminador es la clase de excepción, y `PropertyStateBlocksCleaningError` no la
lanza solo la asignación: su docstring nombra el caso realista de `POST /{id}/complete` (cerrar una
limpieza cuando el siguiente huésped ya está dentro). Con D1, **ese** `409` también pasa a
`PROPERTY_STATE_CONFLICT`. Es honesto —es la misma causa— y no rompe a nadie hoy: ningún consumidor
mapea los errores del cierre, porque la UI de `/cleaner` no existe todavía y
`features/cleaning/lib/assign-error.ts` es el único mapeador de errores de limpieza del frontend
(verificado sobre `frontend/features` y `frontend/lib`).

Rejected: acotar el código nuevo a la ruta de asignación — obligaría al caso de uso a traducir la
misma excepción a dos clases según quién preguntó, es decir a nombrar la causa por el llamante en
vez de por lo que pasó.

### D3 — El sobre de error no lleva el estado operacional concreto (R1.3)

**Chosen:** `details` sigue vacío y el `message` sigue siendo el de la excepción de `properties`
(`str(exc)`, técnico y en inglés, que el frontend nunca pinta). Hoy ya es así —
`PropertyStateBlocksCleaningError(str(exc))` no arrastra el `from_state` que la excepción de origen
guarda como atributo— y el design lo **fija con un test** en vez de dejarlo como accidente.

La razón es D2: el mismo código lo recibe la limpiadora en el cierre, y `CLEANER` no tiene
`READ_PROPERTIES`. Y el manager no lo necesita en el sobre: ya tiene el estado de cada vivienda en
el catálogo que la pantalla carga (Context 1).

Rejected: `details={"property_state": ...}` solo para quien tenga `READ_PROPERTIES` — una respuesta
cuyos campos dependen del rol, para un dato que ese rol ya puede leer por otra ruta.

### D4 — La precondición se deriva de la matriz, nunca de una constante

**Chosen:** una función pura en `backend/app/cleaning/domain/assignment.py`, al lado de
`resolve_auto_assignee` y por el mismo motivo que aquélla vive ahí (es política de negocio, no
orquestación):

```python
def assignment_blocker(
    *, task_status: CleaningTaskStatus, property_state: PropertyOperationalState | None
) -> CleaningAssignmentBlocker | None: ...
```

Con este orden, que reproduce el del caso de uso:

1. `task_status ∉ {CREATED, ASSIGNED}` → `TASK_STATUS` (lo que rechaza `CleaningTask.assign`).
2. `task_status is CREATED` y `property_state ∉ PropertyStateMachine.source_states_for(CLEANER_ASSIGNED)`
   → `PROPERTY_STATE`.
3. En cualquier otro caso, `None`: asignable ahora. Incluye la reasignación de una tarea `ASSIGNED`,
   que no transiciona la vivienda y por tanto no depende de su estado.

`property_state is None` (vivienda que la lectura de página no resolvió) devuelve `None`: **falla
abierto**, ofrece el botón y deja que el backend decida, que es exactamente R3.3.

El import cruzado `cleaning/domain → properties/domain` está permitido (`tests/test_layering.py`
prohíbe framework y capas `api`/`application`/`infrastructure`, no otro `domain/`), y no crea ciclo:
`properties.domain.state_machine` importa `cleaning.domain.enums`, no este módulo.

Rejected: escribir `AWAITING_CLEANING` como constante en el backend o en el frontend — es una
segunda copia de la matriz, y `source_states_for` existe porque `celery-jobs` ya rechazó
exactamente eso: «una lista mantenida a mano derivaría de `_POLICY` la primera vez que se añada una
transición, y derivaría en silencio». Con la constante, ampliar la matriz (explícitamente fuera de
alcance, pero previsto) dejaría la pantalla bloqueando para siempre.

### D5 — El pre-vuelo viaja en el **item del listado**, no en `CleaningTaskResponse`

**Chosen:** un modelo nuevo `CleaningTaskListItemResponse` = los campos de `CleaningTaskResponse`
más `assignment_blocked_by: CleaningAssignmentBlocker | None`, usado **solo** por
`CleaningTaskPageResponse.data`. El precedente es `PropertyListItemResponse`, que existe por la
misma razón de forma: un segundo modelo en vez de un campo opcional en el compartido.

`CleaningTaskResponse` la devuelven ocho endpoints (`POST`, `GET /{id}`, `PATCH`, `accept`,
`reject`, `start`, `complete`, `validate`); ponerle el campo obligaría a los ocho a leer el estado
de la vivienda para responder una pregunta que a ninguno le están haciendo. Y el `PATCH` no lo
necesita: la mutación invalida el prefijo entero de claves de tareas (`use-assign-cleaning-task.ts`,
`onSettled`), así que el refetch trae los indicadores frescos de toda la página.

El campo es aditivo, así que no rompe a ningún cliente; lo que **sí** cambia de forma es el tipo de
`CleaningTaskPageResponse.data` en el contrato derivado, y el mapeador del frontend se parte en la
misma PR (D7).

Rejected: una petición por fila — R3.2 lo prohíbe por escrito.
Rejected: `can_assign: bool` — R3.1 pide el **motivo**, y un booleano confunde las dos causas justo
después de que D1 las separe. El enum es simétrico con los dos códigos de error, que es lo que
permite un mensaje por causa en los dos sitios.

### D6 — El estado de las viviendas de la página se lee con un método nuevo y estrecho del puerto

**Chosen:** `PropertyRepository.states_for(tenant_id, property_ids) -> dict[UUID, PropertyOperationalState]`
(puerto en `properties/domain/repositories.py`, adaptador en `properties/infrastructure/repositories.py`),
consumido por `ListCleaningTasksUseCase`, que ya no recibe solo `tasks`. Un `SELECT` más por
petición de listado, acotado por la página (≤20 tareas ⇒ ≤20 ids distintos) y con
`WHERE tenant_id = :tenant_id` como manda la regla 1 de `steering/security.md`.

Rejected: `list_by_state` o `list_all` — sus propios docstrings dicen que alimentan un barrido y no
una pantalla, y las dos son no paginadas sobre el portfolio completo.
Rejected: unir `PropertyModel` dentro del adaptador de `cleaning` — hoy la infraestructura de
`cleaning` no importa ningún modelo de otro dominio, y empezar por aquí sería el primer cruce.

Se decide en `application/`, no en el router: el caso de uso devuelve una lista de vistas
(`CleaningTaskListView`, dataclass con la tarea y su `blocker`) y `api/schemas.py` la mapea al
alambre, como el resto del módulo.

### D7 — El frontend refina el `409` por código y conserva el `switch` por status

**Chosen:** `assignErrorKey` mantiene `KEY_BY_STATUS` y añade una tabla por código consultada
**solo** cuando el status es `409`. `PROPERTY_STATE_CONFLICT` → `assign.error.propertyState`;
cualquier otro código con `409` —`CONFLICT` incluido, y también uno desconocido— sigue cayendo en
`assign.error.conflict`. Ese fallback es la ventana de deploy-skew: el mismo razonamiento del
`?? "gray"` de `lib/task-status.ts`, que ya distingue la garantía de compilación de la de runtime.

En el lado de los datos, `dto.ts` se parte igual que el backend: `CleaningTask` (base, lo que
devuelve `assignTask`) y `CleaningTaskListItem extends CleaningTask` con `assignmentBlockedBy`, que
es lo que devuelve `listTasks` y lo que recibe la fila. `HttpCleaningSource` gana `mapListItem`
junto a `mapTask`.

Rejected: pasar todo el mapeo a códigos — reescribiría un mapeador entregado sin ganancia, y
`403`/`404`/`422` no tienen código propio que los distinga de otros errores del mismo status.

### D8 — La fila bloqueada explica el motivo en texto estático asociado al botón

**Chosen:** `AssignCleanerControl` recibe `blockedBy: CleaningAssignmentBlocker | null`. Cuando no
es `null`, el botón queda deshabilitado (junto a las dos condiciones que ya lo deshabilitan) y
debajo aparece una línea con el motivo localizado, referenciada desde el botón con
`aria-describedby`. El `<select>` **sigue habilitado**: R3.4, y la razón ya documentada en el
componente (deshabilitar un elemento con el foco lo manda al `<body>`).

Rejected: `title` o tooltip — la vista es mobile-first y no hay hover donde se opera.
Rejected: ocultar el control entero — el manager perdería la pista de que esa fila *tiene* una
asignación posible más tarde, y R3.1 pide indicar el motivo, no esconder la acción.

### D9 — La fila no deriva nada: pinta el campo

**Chosen:** la condición de R3 llega calculada en el DTO y `cleaning-task-row.tsx` la usa tal cual.
Es lo que hace que siga siendo verdad el «No lógica de negocio en componentes — el backend es la
fuente de verdad de estados y validaciones» de `steering/frontend.md`, que la alternativa (derivar
en el cliente desde `current_operational_state` del catálogo) violaría de frente.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Registro de errores | `backend/app/core/error_codes.py` | 13.º miembro `PROPERTY_STATE_CONFLICT` (D1) |
| Errores de limpieza | `backend/app/cleaning/api/errors.py` | `PropertyStateBlocksCleaningError` → código nuevo; docstring: enumera los `409` y hoy omite éste (D1, D2) |
| Política de dominio | `backend/app/cleaning/domain/assignment.py`, `domain/enums.py` | `assignment_blocker(...)` y el `StrEnum` `CleaningAssignmentBlocker` (D4) |
| Puerto de propiedades | `backend/app/properties/domain/repositories.py`, `properties/infrastructure/repositories.py` | `states_for(tenant_id, property_ids)` (D6) |
| Caso de uso del listado | `backend/app/cleaning/application/use_cases.py`, `api/dependencies.py` | `ListCleaningTasksUseCase` recibe `properties`, devuelve vistas con `blocker` (D5, D6) |
| Contrato del listado | `backend/app/cleaning/api/schemas.py`, `api/tasks_router.py` | `CleaningTaskListItemResponse`; descripción OpenAPI del `PATCH` (R4.1) y del `GET` (D5) |
| Contrato publicado | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados en la misma PR (R4.2, `steering/documentation.md`) |
| Mapeo de error | `frontend/features/cleaning/lib/assign-error.ts` | Tabla por código dentro del `409` (D7) |
| DTO y fuente | `frontend/features/cleaning/data/dto.ts`, `data/cleaning-source.ts`, `data/http/http-cleaning-source.ts` | `CleaningTaskListItem`, `mapListItem` (D7) |
| Fila y control | `frontend/features/cleaning/components/cleaning-task-row.tsx`, `components/assign-cleaner-control.tsx`, `components/cleaning-view.tsx` | `blockedBy` hasta el botón + pista con `aria-describedby` (D8, D9) |
| i18n | `frontend/locales/{es,en}/cleaning.json` | `assign.error.propertyState`, `assign.blocked.propertyState`, `assign.blocked.taskStatus` (R2.4) |
| Tests backend | `backend/tests/cleaning/test_tasks_api.py`, `test_errors.py`, `tests/properties/…` | Fixture que **no** fuerza `AWAITING_CLEANING` (R1.4), las dos causas con códigos distintos, `details` vacío (D3), `states_for` con aislamiento de tenant |
| Tests frontend | `assign-error.test.ts`, `assign-cleaner-control.test.tsx`, `cleaning-task-row.test.tsx`, `cleaning-view.test.tsx`, `http-cleaning-source.test.ts` | Código nuevo, fallback de skew, botón deshabilitado con motivo, `<select>` vivo |
| Docs | `docs/cleaning.md` | La precondición junto a la operación de asignación (R4.3) |

## Data & interfaces

- **Sin migración, sin columna nueva, sin variable de entorno.** Todo lo que este change publica ya
  está en la base de datos.
- `ErrorCode` pasa de 12 a 13 miembros. El catálogo publicado en `ErrorEnvelope.code` crece con él;
  la guarda de `tests/test_openapi_contract.py` ya importa el `_MAPPING` de `cleaning`, así que la
  correspondencia registro↔contrato se comprueba sola.
- `CleaningAssignmentBlocker` (`StrEnum`): `TASK_STATUS`, `PROPERTY_STATE`. Aparece en el contrato
  como enum del campo `assignment_blocked_by`, nullable.
- `CleaningTaskListItemResponse`: los 16 campos de `CleaningTaskResponse` más
  `assignment_blocked_by`. Enumerado y construido con un `from_domain`, nunca volcado con
  `from_attributes` —`notes` no debe entrar (design D13 de `cleaning`)—.
- Puerto: `PropertyRepository.states_for(tenant_id, property_ids) -> dict[UUID, PropertyOperationalState]`.
  Un `property_ids` vacío devuelve `{}` sin consultar, como hace `list_by_state` con `states` vacío.
- OpenAPI: la `description` del `PATCH /api/v1/cleaning-tasks/{task_id}` declara que la primera
  asignación exige la vivienda en `AWAITING_CLEANING` y que si no se responde `409`
  `PROPERTY_STATE_CONFLICT` (R4.1). No se enumeran por endpoint los demás estados posibles —
  `sdd/specs/api-contract.md` lo prohíbe explícitamente—, así que esto va en la prosa de la
  operación y no en un `responses=` inventado.

## Risks & mitigations

- **Deploy skew en los dos sentidos.** Frontend viejo + backend nuevo: el `409` con código
  desconocido cae en `assign.error.conflict`, el mensaje de hoy — degrada, no rompe. Frontend nuevo
  + backend viejo: `assignment_blocked_by` llega ausente, que el mapeador trata como `null` y la
  fila ofrece el botón; el backend sigue siendo la autoridad (R3.3).
- **El código nuevo alcanza `POST /complete`** (D2). Sin consumidor hoy, verificado; queda anotado
  en el docstring de la tabla para quien construya `/cleaner`.
- **Un `SELECT` más por página de listado** (D6). Acotado a los ids de la página; el listado ya hace
  dos consultas (filas y `total`).
- **Falla abierto** cuando el estado de la vivienda no se resuelve: una fila puede ofrecer un
  confirmar que acabe en `409`. Es la elección de R3.3 (la guarda de la UI es cortesía), y el
  mensaje que se enseñará entonces ya será el correcto por R2.
- **`CleaningTaskPageResponse.data` cambia de esquema en el contrato**, así que el typecheck del
  frontend falla hasta que el mapeador se parte. Es intencionado: es la red que
  `steering/documentation.md` describe («las dos mitades del mismo puente»), y el arreglo va en la
  misma PR.

  **Corregido durante `/sdd:run` (§5, panel de arquitectura): esa red protege menos de lo que esta
  nota decía.** `CleaningTaskListItem extends CleaningTask` es un subtipo por ampliación, así que
  el typecheck solo se rompe en la frontera del mapeador — donde `mapPage(response, mapTask)` deja
  de satisfacer el tipo nuevo. Todo consumidor aguas abajo que siguiera tipado con la base
  **compilaba igual**: la anotación del hook (`use-cleaning-data.ts`) y la prop de
  `cleaning-task-row.tsx` aceptan un `CleaningTaskListItem` sin quejarse, porque lo es. Consecuencia
  medida: la UI de R3.1 podía haberse entregado incompleta —el botón nunca deshabilitado— con
  `tsc --noEmit` en verde. Lo que de verdad obliga a propagar el campo es estrechar a mano esos dos
  consumidores, y eso es una decisión de quien implementa, no una garantía del compilador.

  **Y una corrección de la corrección, porque el primer intento de esta nota también era falso**:
  no es que un tipo hermano sin `extends` habría dado la red. TypeScript es **estructural**, así
  que un hermano que declare los mismos campos es igual de asignable a un consumidor tipado con la
  base — el panel de arquitectura lo refutó compilando el caso. Ni `extends` ni un hermano
  idéntico dan esa garantía; solo la daría un tipo **nominal** (un campo marca), que es un precio
  bastante mayor que duplicar siete campos y que no se juzgó buen cambio para esto. Conclusión
  real, y precisa esta vez: la red de tipos **existe y para en el mapeador** —es lo que fuerza a
  que `mapListItem` exista— pero **no cubre la propagación del campo desde ahí hasta la fila**, que
  es justo donde vive la completitud de R3.1. Ese tramo lo cubren los tests que fijan que la fila
  bloqueada deshabilita el botón, y nada más.

  La corrección se propagó también a `sdd/steering/documentation.md`, cuya frase «eso lo atrapa el
  typecheck del frontend contra los tipos derivados» arrastraba el mismo error como regla
  permanente. Queda anotado aquí para que el radio del arreglo se vea sin diffear steering aparte.
- **Regenerar el contrato desde un worktree enlazado no funciona con el comando documentado**
  (`sdd/project.md`, «Lo que tampoco funciona tal cual»). La secuencia de `docker compose cp` de
  ahí es obligatoria en la sección de verificación, y `npm test` necesita además la lista de copias
  de `tech-incident-context` para no dar dos ficheros en rojo ajenos al change.

- **Deuda con disparador: la pasada visual de `/cleaning` a 320 px sigue pendiente, y se hace en
  `dev`.** Ningún criterio de aceptación depende de ella —R2.1/R3.1/R3.3/R3.4 están fijados por
  tests de componente con aserciones de DOM reales y por la API medida contra Postgres real—, así
  que es acabado y no cobertura. No se hizo en el worktree porque `PORT_OFFSET` sirve la página sin
  hidratarla (`next dev` sin `allowedDevOrigins`, recogido en `sdd/project.md`) y porque
  `AWAITING_CLEANING` no es alcanzable por el camino real en un mismo día. **Disparador**: el
  primer despliegue de este change en `dev`. **Qué mirar allí**: la fila bloqueada con el botón
  deshabilitado y el `<select>` vivo, el `409` de la carrera anunciándose con el mensaje de la
  vivienda, los dos idiomas, 320 px sin scroll horizontal y la consola limpia. `dev` es además
  donde se midió el fallo original el 2026-08-22, así que es el sitio natural para cerrarlo.

## Requirement coverage

| Req | Dónde se resuelve |
|---|---|
| R1.1 | D1 — `PROPERTY_STATE_CONFLICT` ≠ `CONFLICT` |
| R1.2 | D1 — `InvalidCleaningTransitionError` intacto: `409`/`CONFLICT` |
| R1.3 | D3 — nada del estado en el sobre; Context 2 explica por qué el manager no lo necesita |
| R1.4 | Tests: fixture que no fuerza `AWAITING_CLEANING`, una prueba por causa |
| R2.1 | D7 + i18n `assign.error.propertyState` |
| R2.2 | D7 — el `409` sin código conocido sigue en `assign.error.conflict` |
| R2.3 | D7 — se elige por código dentro del status; el `message` del backend nunca se pinta. (Matiz: la regla vigente en `assign-error.ts` era «nunca por el texto», y la elección era por status; este change la sube a código.) |
| R2.4 | Claves nuevas en `locales/es` y `locales/en` |
| R3.1 | D8 — botón deshabilitado + motivo localizado con `aria-describedby` |
| R3.2 | D5 — el indicador viene en la respuesta del listado; ninguna petición por fila |
| R3.3 | D4 (falla abierto) + D7 (el rechazo del backend sigue mandando) |
| R3.4 | D8 — el `<select>` no se deshabilita |
| R4.1 | Descripción OpenAPI del `PATCH` |
| R4.2 | `backend/openapi.json` + `frontend/lib/api/generated/openapi.d.ts` en la misma PR |
| R4.3 | `docs/cleaning.md` |

Sin implicación de design: nada. Los diez criterios de R1–R3 y los tres de R4 tienen todos su
decisión o su tarea de verificación.

## Open questions

Ninguna abierta. Las tres se resolvieron en la puerta de design el 2026-08-23, y quedan aquí porque
la alternativa descartada es parte de la decisión:

**OQ1 — ¿El mensaje del bloqueo nombra el estado de la vivienda, o solo el hecho? → Solo el hecho.**
«La vivienda todavía no está pendiente de limpieza». La consecuencia es que `PropertySummary` **no**
gana `currentOperationalState` y `mapProperty` sigue descartándolo: el motivo entero viaja en el
enum del listado. Descartado nombrarlo («La vivienda está ocupada»), que exigía llevar
`current_operational_state` al catálogo del cliente y tomar prestada `dashboard:states.*` para un
dato que ya está a un clic en el dashboard.

**OQ2 — ¿El código nuevo se aplica también a `POST /{id}/complete`? → Sí, a toda la causa.**
Confirma D2: el discriminador es `PropertyStateBlocksCleaningError`, así que el `409` del cierre
bloqueado por un huésped ya dentro también pasa a `PROPERTY_STATE_CONFLICT`. Descartado acotarlo a
la asignación, que obligaba a una subclase nueva y a una rama en `_transition` para nombrar la causa
por el llamante. Anotado en la proposal (§R1) porque ningún criterio de aceptación nombra ese
endpoint y sin ello el spec vivo declararía un `SHALL` más estrecho que lo entregado.

**OQ3 — Nombre del código. → `PROPERTY_STATE_CONFLICT`.** Conserva el sufijo del `CONFLICT` del que
se separa, que es lo que hace legible que sigan compartiendo el `409`. Descartados
`PROPERTY_NOT_READY` (suena a `PropertyStatus` administrativo, no a estado operacional) y
`PROPERTY_STATE_BLOCKS_OPERATION` (el más largo del registro con diferencia; los otros doce son de
una o dos palabras).
