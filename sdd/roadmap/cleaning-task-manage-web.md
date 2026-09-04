# cleaning-task-manage-web

[FE] **crear y validar una limpieza desde `/cleaning`**, y cancelarla desde ahí y no sólo desde la
tarjeta de estancamiento del dashboard.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04).

**El hecho medido (2026-09-04)**: de las catorce rutas de `backend/app/cleaning/api/tasks_router.py`,
el manager alcanza desde el navegador exactamente **una**: asignar/reasignar (`PATCH` :202, desde
`features/cleaning/components/cleaning-view.tsx:77`). `POST /cleaning-tasks` (:147) y `validate`
(:384) no tienen ningún llamante en `frontend/`; `cancel` (:287) sólo se ofrece en
`features/dashboard/stalls/components/cancel-cleaning-dialog.tsx:57`, y sólo sobre una fila de
`blocked-transitions` (`stalls/lib/action-map.ts:57-62`). Las plantillas (`templates_router.py:50`,
:74) tampoco tienen pantalla.

**Por qué no es cosmético**: hoy una `CleaningTask` **sólo nace si `process_checkouts` la crea**
(`scheduler/tasks.py:410-421`, respetando `auto_create_cleaning_task`). Una limpieza extraordinaria
—entre estancias largas, tras una incidencia, a petición del owner— no tiene vía. Y al otro
extremo, el manager **no puede cerrar el bucle**: la limpiadora completa, la vivienda cambia de
estado, y la validación (PRD §11 «validación») se queda sin hacer porque no hay botón.

**Alcance**: en `/cleaning`, para `MANAGE_CLEANING_TASKS` (manager; el owner no lo tiene y hoy
el control de asignar se le pinta igual y le responde `403` — arreglarlo de paso con
`useHasPermission`): (1) **crear** tarea sobre una propiedad, con plantilla, fecha límite y
limpiadora opcional; (2) **validar** una tarea `COMPLETED` (o rechazar la validación, si el
contrato lo distingue); (3) **cancelar** con motivo desde la propia lista/detalle. Sin backend.

**Lo que decide y no es cosmético**, y está medido:

1. **Una tarea creada a mano nace inasignable.** RUNBOOK-seed-demo §4 lo midió el 2026-08-22:
   `POST /cleaning-tasks` no mueve la vivienda, y `CLEANER_ASSIGNED` sólo es legal desde
   `AWAITING_CLEANING` (`properties/domain/state_machine.py:43`), así que sobre cualquier otro
   estado la asignación responde `409` por `PropertyStateBlocksCleaningError`.
   `cleaning-assign-preconditions` ya publica `assignment_blocked_by` en el ítem del listado:
   la pantalla lo usa para **decir antes de crear** que esa tarea no se podrá asignar hasta que
   la vivienda esté en `AWAITING_CLEANING`, y ofrece igualmente crearla (la tarea tiene valor
   como registro aunque la asignación espere). Lo que **no** hace es proponer una transición
   manual de la vivienda: no existe ruta para eso (`timeline-description-sink-census`, pendiente).
2. **Autoasignación**: `resolve_auto_assignee` (`cleaning/domain/assignment.py:1-16`) asigna
   cuando hay exactamente una limpiadora activa. Si el manager elige una en el formulario y hay
   una sola, el resultado es el mismo; si hay varias y no elige, queda `CREATED`. Mostrarlo.
3. **Validar** cambia algo en la vivienda o sólo en la tarea? Medir `validate` (:384) antes de
   pintar: si no toca `current_operational_state`, la pantalla no debe sugerir que lo hace.
4. **Motivo de cancelación**: ya está acotado (`MAX_CANCEL_REASON`, `String(500)`) y es el único
   valor vivo de `timeline_events.description` (`timeline-description-sink-census`); la UI no
   añade campos.

**Fuera de alcance**: gestión de plantillas de checklist (`MANAGE_CLEANING_TEMPLATES` es del
owner y no tiene pantalla — candidata `cleaning-templates-web` si hace falta); abandonar una
tarea en curso (no existe operación, `cleaning-stall-blocks-next-stay` lo dejó escrito);
`cleaner-list-property-projection`.

**Verificación**: crear una limpieza sobre una vivienda en `VACANT_READY`, ver el aviso de
«no asignable todavía»; recorrer un checkout con `sim-advance`, asignar, que la limpiadora
complete en `/cleaner`, validar desde `/cleaning`.
