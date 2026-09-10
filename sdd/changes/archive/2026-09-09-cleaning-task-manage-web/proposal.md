# Proposal: cleaning-task-manage-web

## Why

De las **catorce** rutas de `backend/app/cleaning/api/tasks_router.py`, el manager alcanza desde
el navegador exactamente **una**: asignar/reasignar (`PATCH` :202, desde
`features/cleaning/components/cleaning-view.tsx:77`). `POST /cleaning-tasks` (:147) y
`POST /{id}/validate` (:384) **no tienen ningún llamante en `frontend/`** — verificado el
2026-09-05 recorriendo todos los `*.ts*` fuera de `node_modules`: `createCleaningTask` y
`validateCleaningTask` dan **cero** ocurrencias, y `frontend/features/cleaning/data/http/http-cleaning-source.ts`
sólo llama a listar (:110/:113), leer (:159) y cancelar (:182).

Las consecuencias no son cosméticas:

1. **Una `CleaningTask` sólo nace si `process_checkouts` la crea** (`scheduler/tasks.py`,
   respetando `auto_create_cleaning_task`). Una limpieza extraordinaria —entre estancias largas,
   tras una incidencia, a petición de la propietaria— no tiene vía desde el producto.
2. **El manager no puede cerrar el bucle**: la limpiadora completa, la vivienda cambia de estado,
   y la validación manual de PRD §11 se queda sin hacer porque no hay botón. `validation_status`
   se queda en `PENDING` para siempre.
3. **Cancelar existe pero está escondido**: el hook `useCancelCleaningTask` ya vive en
   `features/cleaning/hooks/`, exportado por `features/cleaning/index.ts:2` — y su **único**
   consumidor es `features/dashboard/stalls/components/cancel-cleaning-dialog.tsx:57`, sobre una
   fila de `blocked-transitions`. Desde `/cleaning`, donde están las tareas, no se puede cancelar.

Entrada de roadmap `cleaning-task-manage-web` (hito «MVP operable» 1, *ciclo operativo completo
desde el navegador*), con su nota larga en `sdd/roadmap/cleaning-task-manage-web.md`.

### Tres afirmaciones de la nota de roadmap que la medición corrige

Se comprueban aquí porque nadie las vuelve a revisar después, y dos de ellas cambian el alcance:

- **«crear … con plantilla, fecha límite y limpiadora opcional»** — falso.
  `CreateCleaningTaskRequest` (`cleaning/api/schemas.py`) acepta exactamente
  `property_id`, `reservation_id?`, `scheduled_start?`, `scheduled_end?`. **No hay campo de
  plantilla** (`resolve_template` la elige en servidor) **ni de limpiadora**.
- **«Autoasignación: si el manager elige una en el formulario y hay una sola…»** — no aplica.
  `CreateCleaningTaskUseCase` **no llama a `resolve_auto_assignee`** (eso lo hace
  `ProvisionCleaningTaskUseCase`, el camino automático). Una tarea creada a mano nace **siempre**
  `CREATED` y sin asignar; asignarla es una segunda operación, y es esa segunda la que puede dar
  `409`.
- **«el owner … hoy el control de asignar se le pinta igual y le responde 403 — arreglarlo de
  paso con `useHasPermission`»** — ya está arreglado.
  `cleaning-task-row.tsx:120` hace `useHasPermission("MANAGE_CLEANING_TASKS")` y oculta el
  control. No hay nada que arreglar de paso; sí hay que **no reintroducir** el defecto con los
  tres controles nuevos (R5).

Y una decisión que la nota mandaba medir (`Lo que decide` §3), medida:
**`validate` no mueve la vivienda.** `ValidateCleaningTaskUseCase` lo dice en un comentario
literal — *«No property transition: validating does not move the property, which already left
`CLEANING_IN_PROGRESS` when the task was completed»*. La pantalla no debe sugerir lo contrario.

## What changes

En `/cleaning`, y **sólo en el frontend**: aparecen las tres operaciones que hoy no tienen
superficie — **crear** una limpieza sobre una vivienda del catálogo, **validar** una tarea
`COMPLETED` con el veredicto del manager, y **cancelar** con motivo desde la propia fila,
reutilizando el hook que ya existe. La pantalla avisa **antes de crear** cuando la vivienda
elegida no está en un estado que admita asignación, y deja crear igualmente. Los DTO de
`features/cleaning` se ensanchan con campos que el backend **ya publica** y el mapper descarta
(`validation_status`, `validated_at`, `completed_at` en el ítem de listado;
`current_operational_state` en el ítem de propiedad).

**Sin backend y sin regenerar el contrato**: los cuatro campos ya están en
`CleaningTaskListItemResponse` y `PropertyListItemResponse`, y por tanto ya en
`frontend/lib/api/generated/openapi.d.ts`. Verificado el 2026-09-05 leyendo ambos esquemas.

## Requirements

### R1 — Crear una limpieza a mano

**Como** manager, **quiero** crear una limpieza sobre una vivienda desde `/cleaning`, **para**
poder programar una limpieza extraordinaria que ningún checkout implica.

Criterios de aceptación:

1. WHEN el usuario con `MANAGE_CLEANING_TASKS` abre `/cleaning`, THE SYSTEM SHALL ofrecer un
   control de creación de limpieza.
2. WHEN el usuario abre ese control, THE SYSTEM SHALL pedir una **vivienda** del catálogo del
   tenant (obligatoria) y una **ventana programada** `scheduled_start`/`scheduled_end`
   (opcionales), y ningún otro campo.
3. WHEN el usuario confirma, THE SYSTEM SHALL llamar a `POST /api/v1/cleaning-tasks` con
   exactamente esos campos y, al recibir `201`, invalidar la clave de listado de tareas para que
   la nueva fila aparezca sin recargar la página.
4. IF la llamada falla, THEN THE SYSTEM SHALL anunciar el error con un mensaje elegido **por
   código de estado HTTP**, nunca tomado de `ApiError.message`, siguiendo el patrón que
   `lib/assign-error.ts` ya establece.
5. WHEN la creación termina —con éxito o con error—, THE SYSTEM SHALL anunciarlo por la región
   viva única de la vista (`role="status" aria-live="polite"`, design D11 de
   `cleaning-manager-view`), sin añadir una segunda región.

### R2 — Decir antes de crear que la tarea nacerá inasignable

**Como** manager, **quiero** saber al elegir la vivienda si la tarea que voy a crear podrá
asignarse, **para** no descubrirlo con un `409` después de crearla.

Contexto medido: `CLEANER_ASSIGNED` tiene **una sola fila** en la matriz
(`properties/domain/state_machine.py:43`): `AWAITING_CLEANING → CLEANING_SCHEDULED`. Como
`CreateCleaningTaskUseCase` no mueve la vivienda, una tarea creada sobre cualquier otro estado
responde `409` (`PropertyStateBlocksCleaningError`) en el `PATCH` de asignación —medido en
`infra/environments/dev/RUNBOOK-seed-demo.md` §4-§5 el 2026-08-22—.

Criterios de aceptación:

1. WHEN el usuario elige en el formulario de creación una vivienda cuyo estado operacional no
   admite `CLEANER_ASSIGNED`, THE SYSTEM SHALL mostrar un aviso que diga que la tarea se creará
   pero no podrá asignarse hasta que la vivienda esté en `AWAITING_CLEANING`.
2. WHILE ese aviso está visible, THE SYSTEM SHALL seguir permitiendo crear la tarea — el aviso
   informa, no bloquea.
3. IF el estado operacional de la vivienda elegida no se ha podido resolver, THEN THE SYSTEM
   SHALL **no** mostrar aviso y permitir crear, dejando al backend como autoridad (la misma
   política de *fail open* que `assignment_blocker` documenta para `property_state is None`).
4. THE SYSTEM SHALL **no** ofrecer ninguna transición manual de la vivienda desde esta pantalla:
   no existe ruta de API para eso (`timeline-description-sink-census`, pendiente).

### R3 — Validar una limpieza terminada

**Como** manager, **quiero** emitir mi veredicto sobre una limpieza `COMPLETED`, **para** cerrar
la validación manual de PRD §11 sin salir de la pantalla.

Contexto medido: `CleaningTask.record_manual_validation` exige estado `COMPLETED` y **rechaza
`PENDING` como veredicto**; los veredictos legales son `PASSED`, `FAILED` y `WAIVED`. Un veredicto
`FAILED` notifica a la limpiadora asignada (`NotificationType.CLEANING_FAILED`).

Criterios de aceptación:

1. THE SYSTEM SHALL ofrecer el control de validación **únicamente** en filas cuyo `status` sea
   `COMPLETED`, con o sin veredicto previo. **Enmendado en el gate de `/sdd:design` del 2026-09-05**
   (design D6): la redacción original lo limitaba además a `validation_status = PENDING`, lo que
   dejaba un `FAILED` mal pulsado —que notifica a la limpiadora— sin corrección posible desde el
   producto. `record_manual_validation` sólo exige `COMPLETED` y no comprueba el veredicto previo, así
   que revalidar no estrena ruta ni relaja regla alguna.
2. WHEN el usuario emite un veredicto, THE SYSTEM SHALL llamar a
   `POST /api/v1/cleaning-tasks/{id}/validate` con ese `validation_status` y, al recibir `200`,
   invalidar la clave de listado de tareas.
3. THE SYSTEM SHALL mostrar en la fila el `validation_status` vigente y, cuando exista, la fecha
   de validación — campos que el backend ya publica en `CleaningTaskListItemResponse` y que el
   DTO del frontend hoy descarta. **Acotado en el gate del 2026-09-05** (design D7): se pinta en las
   filas que se han completado alguna vez (`completed_at` no nulo) o que ya tienen veredicto, no en
   todas — «Pendiente de validación» sobre una tarea `CREATED` que nadie ha limpiado todavía se lee
   como una tarea atascada.
4. THE SYSTEM SHALL **no** afirmar en ningún texto que validar cambia el estado de la vivienda:
   `ValidateCleaningTaskUseCase` no ejecuta ninguna transición de propiedad.
5. IF la llamada falla, THEN THE SYSTEM SHALL anunciar el error por código de estado HTTP, con la
   misma regla que R1.4.
6. THE SYSTEM SHALL impedir reenviar el veredicto que la tarea ya tiene, deshabilitando su control:
   repetir `FAILED` volvería a notificar a la limpiadora y a escribir otra fila de auditoría.
   Añadido en el mismo gate, como contrapeso de la enmienda a R3.1.

### R4 — Cancelar desde la lista, no sólo desde el dashboard

**Como** manager, **quiero** cancelar una limpieza desde `/cleaning`, **para** no tener que
llegar a ella por la tarjeta de estancamiento del dashboard.

Contexto medido: `useCancelCleaningTask` ya existe y está exportado; el backend exige `reason`
no vacío de hasta `MAX_CANCEL_REASON` (500) y, al cancelar, **crea una tarea de reemplazo sin
asignar** salvo que haya un huésped dentro (descripción de la ruta `:287`).

Criterios de aceptación:

1. THE SYSTEM SHALL ofrecer el control de cancelación en las filas cuyo estado sea *vivo* (no
   terminal), reutilizando `useCancelCleaningTask` sin duplicar la mutación.
2. WHEN el usuario cancela, THE SYSTEM SHALL exigir un motivo no vacío de como máximo 500
   caracteres y enviarlo en el cuerpo; THE SYSTEM SHALL **no** añadir ningún otro campo.
3. WHEN la cancelación tiene éxito, THE SYSTEM SHALL invalidar la clave de listado, de modo que
   tanto la tarea cancelada como su tarea de reemplazo queden reflejadas.
4. THE SYSTEM SHALL advertir en el diálogo que la cancelación puede generar una tarea de
   reemplazo, para que la aparición de una fila nueva no se lea como un fallo.
5. IF la tarea ya es terminal y el backend responde `409`, THEN THE SYSTEM SHALL anunciarlo con
   un mensaje propio de esa causa.

### R5 — Los tres controles obedecen el permiso, no el rol

**Como** propietaria sin `MANAGE_CLEANING_TASKS`, **quiero** no ver controles que me van a
responder `403`, **para** que la pantalla no me ofrezca lo que no puedo hacer.

Criterios de aceptación:

1. THE SYSTEM SHALL condicionar los controles de crear, validar y cancelar a
   `useHasPermission("MANAGE_CLEANING_TASKS")`, igual que hoy hace el control de asignación en
   `cleaning-task-row.tsx:120`.
2. WHEN el usuario carece de ese permiso, THE SYSTEM SHALL seguir mostrando la lista completa y
   los datos de cada tarea —incluido `validation_status`—, ocultando sólo los controles.
3. THE SYSTEM SHALL tratar el ocultamiento como cortesía y nunca como autorización: el backend
   sigue siendo quien decide (`steering/frontend.md`, «el RBAC del backend decide, el frontend
   sólo oculta»).

## Preguntas abiertas para `/sdd:design`

**Las tres están resueltas en `design.md` (gate del 2026-09-05).** 1 → opción (a), con la deriva
escrita (design D2); 2 → confirmada, no se ofrece `reservation_id`; 3 → confirmada, `PASSED` y
`FAILED`, `WAIVED` fuera. Se conservan tal cual porque el razonamiento que las planteó es lo que
justifica la decisión.

1. **Cómo sabe el frontend qué estados admiten `CLEANER_ASSIGNED` (R2.1).** Hoy la única fuente
   es la matriz del backend, y `assignment_blocker` documenta explícitamente que una copia a mano
   «derivaría en silencio» en cuanto se añada una transición. Opciones: (a) constante
   `AWAITING_CLEANING` en el frontend con su aviso de deriva; (b) crear primero y leer el
   `assignment_blocked_by` de la fila recién creada, renunciando al «antes de crear»; (c) pedir
   al backend que publique los estados legales. (c) rompería el «sin backend» de este change.
   **Recomendación**: (a), con el aviso escrito, porque el aviso de R2 es cortesía y R2.3 ya deja
   al backend como autoridad.
2. **Si el formulario de creación ofrece `reservation_id`.** El backend lo acepta y valida que la
   reserva pertenezca a la vivienda. Se propone **no** ofrecerlo: una limpieza extraordinaria por
   definición no la implica ningún checkout, y un selector de reservas es una superficie nueva.
   Marcado como `ASSUMPTION`.
3. **Qué veredictos se ofrecen.** El backend admite `PASSED`, `FAILED` y `WAIVED`. `WAIVED`
   («dispensada») no tiene semántica declarada en el PRD. Se propone ofrecer `PASSED` y `FAILED`
   y dejar `WAIVED` fuera hasta que alguien defina qué significa. Marcado como `ASSUMPTION`.

## Out of scope

- **Cualquier cambio de backend.** Las tres rutas existen y publican todo lo que la pantalla
  necesita; este change es `[FE]`.
- **Gestión de plantillas de checklist** (`templates_router.py:50`, `:74`). `MANAGE_CLEANING_TEMPLATES`
  es de la propietaria y no tiene pantalla → candidata de roadmap `cleaning-templates-web`.
- **Abandonar una tarea en curso.** No existe operación; `cleaning-stall-blocks-next-stay` lo dejó
  escrito.
- **Transición manual del estado operacional de una vivienda.** No hay ruta
  (`timeline-description-sink-census`).
- **`cleaner-list-property-projection`**: que el listado traiga su vivienda embebida es una
  optimización de backend con su propia entrada de roadmap. Esta pantalla sigue resolviendo la
  identidad por el catálogo (`lib/directory.ts`).
- **Selector de reservas** en el formulario de creación (pregunta abierta 2).
- **El veredicto `WAIVED`** (pregunta abierta 3).
- **Validación automática con IA** — es de `messaging-ai`, según dice la propia descripción de la
  ruta `validate`.

## Affected specs

- `sdd/specs/cleaning-manager-view.md` — **se modifica**: es la spec viva de `/cleaning` y gana
  las tres operaciones, el aviso de no-asignabilidad y los campos nuevos del DTO.
- `sdd/specs/cleaning.md` — **no se toca**: describe la capacidad de backend, que este change no
  modifica. Se cita desde la spec del frontend.
- `sdd/specs/api-contract.md` — **no se toca**: no hay regeneración del contrato, porque los
  cuatro campos que el frontend empieza a leer ya están publicados.
