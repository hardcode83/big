# incident-triage-web

[FE] **las mutaciones del manager sobre la incidencia, que hoy sólo existen para el técnico y
para la CLI**: asignar, clasificar a mano, editar (triage) y cancelar desde `/incidents/[id]`.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04). Es la entrada con más palanca del hito: sin ella `/tech` no se puede alcanzar.

**El hecho medido (2026-09-04)**: `backend/app/maintenance/api/incidents_router.py` sirve las
diez operaciones de mutación de PRD §12 —`classify` (:240), `PATCH` de triage (:265), `assign`
(:294), `accept` (:326), `reject` (:355), en ruta (:386), `wait-parts` (:415), `resume` (:439),
`resolve` (:459), `cancel` (:493)— y el frontend consume **sólo las del técnico**:
`frontend/features/tech/lib/tech-actions.ts:26-36` y los hooks de
`features/incidents/data/http/http-incidents-source.ts:195-338`, que existen pero cuyos únicos
llamantes son `features/tech` y el diálogo de estancamiento del dashboard
(`features/dashboard/stalls/components/resolve-incident-dialog.tsx:60`, y sólo sobre una fila
de `blocked-transitions`). `frontend/features/incidents/components/detail/incident-detail-view.tsx:19`
lo declara: *«No mutation controls»*. `incidents-web` lo dejó fuera de alcance por escrito
(`sdd/roadmap.md`, entrada `incidents-web`: *«Fuera de alcance: las diez operaciones de
mutación»*) y no registró la entrada de seguimiento.

**Por qué no es cosmético, y es el argumento entero**: `assign` no tiene ningún llamante de
producción. El único sitio del árbol que asigna una incidencia a un técnico fuera de los tests es
`backend/app/cli/seed_demo.py:1256` y `:1315-1318`, y **no hay autoasignación de incidencias**
—la limpieza sí la tiene (`cleaning/domain/assignment.py:1-16`, `resolve_auto_assignee`), el
mantenimiento no—. Consecuencia: la app del técnico entera (`/tech`, `/tech/incidents/[id]`,
archivada en `tech-app` y la superficie de campo más completa del producto) sólo funciona sobre
la incidencia que sembró la demo. Una incidencia que reporta un huésped desde el portal o una
limpiadora desde su tarea se queda en `OPEN`/`CLASSIFIED` hasta que alguien haga un `curl`.

**Alcance**: los controles del manager en `/incidents/[id]`, gateados por permiso como ya hace
`conversation-thread-view.tsx:56` con `useHasPermission` —`MANAGE_INCIDENTS` es del
`PROPERTY_MANAGER` (`auth/domain/policy.py:384-421`); el `TENANT_OWNER` es sólo lectura y no
debe ver los botones—: (1) **asignar** a un técnico activo del tenant, con nota de asignación;
(2) **clasificar a mano** categoría y severidad cuando `classify_incidents` (cada 5 min,
`scheduler/schedule.py:65`) no lo ha hecho o lo ha hecho mal; (3) **triage** (`PATCH`); (4)
**cancelar** con motivo. Reutiliza los hooks de `http-incidents-source.ts` que ya existen y sólo
faltan por montar. El listado `/incidents` no cambia.

**Lo que decide y no es cosmético**:

1. **De dónde sale la lista de técnicos.** `GET /api/v1/users` con filtro de rol requiere
   `READ_USERS`, que el manager tiene (`policy.py:384-421`, sólo lectura sobre usuarios).
   `cleaning-manager-view` ya resolvió el mismo problema para las limpiadoras
   (`features/cleaning/data/http/http-cleaning-source.ts` expone `users`): heredar la forma,
   no inventar una tercera.
2. **Qué pasa con una incidencia `AWAITING_OWNER_APPROVAL`.** Desde esta pantalla no se
   resuelve —eso es `approvals-web`—, pero hay que pintar el estado y decir a quién le toca.
3. **`assignment_note` es un sumidero de texto libre que no pasa por `storable_text`**
   (`assignment-note-storable-text`, pendiente): el formulario no lo arregla, pero el design
   tiene que saber que un `U+0000` en la nota hoy es un `500` y acotarlo en cliente o dejar
   escrito que se acepta hasta que aquella entrada llegue.
4. **Color del estado**: `incident-status-tone` (pendiente) dice que no existe tabla
   estado→`Tone`; esta pantalla no la inventa por su cuenta —si la necesita, la abre primero
   o la absorbe declarándolo.

**Fuera de alcance**: crear una incidencia como manager —no hay `POST /api/v1/incidents` para
ese rol, ausencia deliberada (docstring de `incidents_router.py`), y DoD §28.8 pide «huésped /
limpiadora / propietario»; si se quiere, es entrada `[BE]` aparte—; responder aprobaciones
(`approvals-web`); fotos de incidente (ya en `/tech`); `incident-list-property-projection`.

**Verificación que el change debe dejar hecha**: recorrer en dev, con Playwright o a mano, el
ciclo entero *huésped reporta desde el portal → manager asigna desde `/incidents/[id]` →
técnico acepta y resuelve desde `/tech`*, con `PORT_OFFSET` si va en worktree (ver
`sdd/project.md` §Worktree bootstrap). Es la primera vez que ese ciclo será posible sin CLI.
