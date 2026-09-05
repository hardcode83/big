# Proposal: incident-triage-web

## Why

La app del técnico (`/tech`, `/tech/incidents/[id]`, archivada en `tech-app`) es la superficie de campo más completa del producto y **es inalcanzable desde el navegador**: `POST /api/v1/incidents/{id}/assign` no tiene ningún llamante de producción fuera de `backend/app/cli/seed_demo.py` (:1256), y el mantenimiento no tiene autoasignación como sí la tiene la limpieza (`cleaning/domain/assignment.py`). Una incidencia que reporta un huésped desde el portal o una limpiadora desde su tarea se queda en `OPEN`/`CLASSIFIED` hasta que alguien haga un `curl`. `incidents-web` dejó las mutaciones fuera de alcance por escrito (`changes/archive/2026-08-20-incidents-web/proposal.md`, «Mutaciones de la incidencia») y no registró el seguimiento; `frontend/features/incidents/components/detail/incident-detail-view.tsx:17-21` lo declara: *«No mutation controls»*.

Es la entrada 1 del hito «MVP operable» (auditoría de flujos por rol del 2026-09-04): *ciclo operativo completo desde el navegador*. Fuente: `sdd/roadmap.md` (entrada `incident-triage-web`) y su nota `sdd/roadmap/incident-triage-web.md`. PRD §12 (flujo de mantenimiento: clasificación → técnico asignado → notificación), §6 (`PROPERTY_MANAGER`: «gestionar mantenimiento (asignar técnicos)»), §26.11.

**Tres hechos que la nota del roadmap afirma y el código desmiente, medidos el 2026-09-05 sobre `6bed6c65`**, y que este proposal corrige en vez de heredar:

1. **`classify` no es «clasificar a mano».** `POST /incidents/{id}/classify` relanza el clasificador (`ClassifyIncidentUseCase`, docstring de la ruta: *«Force the classifier over one incident»*), no acepta cuerpo y sólo admite origen `OPEN`. La corrección humana de categoría y severidad es `PATCH /incidents/{id}` (`TriageIncidentRequest`: `category`, `severity`, `estimated_cost`, todos opcionales).
2. **El triaje humano no saca a una incidencia de `OPEN`.** `Incident.set_triage` (`maintenance/domain/entities.py:406-431`) anota campos «wherever it is in the flow» y **no transiciona**; la única fila `OPEN → CLASSIFIED` de `_TRANSITIONS` es `classify`, y `assign` exige `CLASSIFIED` (`specs/maintenance.md` R1). El `MockAIAdapter` devuelve confianza `0.30` para un texto sin aciertos, por debajo del umbral `0.75` (R2), así que una incidencia que el clasificador dejó en `OPEN` **no tiene ningún camino humano a `CLASSIFIED`** —relanzar el clasificador sobre el mismo texto da el mismo veredicto— y por tanto no se puede asignar. Sólo con frontend, el ciclo que esta entrada existe para cerrar seguiría roto para esas incidencias. Decisión del gate de `/sdd:new` (2026-09-05): la regla de backend que lo cierra **entra en este change** (R3.5) y la entrada pasa a `[FE+BE]`.
3. **Los hooks del manager no existen.** `features/incidents/data/http/http-incidents-source.ts:195-338` expone `accept`, `en-route`, `reject`, `wait-parts`, `resume`, `resolve` y las fotos; **no hay** `classify`, `assign`, `PATCH` ni `cancel` en ningún fichero de `frontend/` (sólo sus rutas en `lib/api/generated/openapi.d.ts:480-496`). El change los añade; no «los monta».

Y un cuarto matiz: **`cancel` no acepta cuerpo**, así que «cancelar con motivo» no existe en el contrato. Decisión del gate: cancelar con confirmación y sin motivo (R5); el motivo, si algún día hace falta, es entrada `[BE]` aparte.

## What changes

`/incidents/[id]` deja de ser sólo lectura para el `PROPERTY_MANAGER`: gana los cuatro controles de gestión de la incidencia —**asignar/reasignar** a un técnico activo del tenant con nota opcional, **triar** (corregir categoría y severidad, fijar coste estimado), **relanzar el clasificador** y **cancelar**— visibles sólo para quien tiene `MANAGE_INCIDENTS` y sólo en los estados donde la tabla de transiciones de `maintenance.md` R1 los admite. El técnico asignado pasa a mostrarse por nombre en vez de por UUID, resuelto contra `GET /api/v1/users?role=TECHNICIAN` con la misma forma que `cleaning-manager-view` usó para las limpiadoras. En backend, una sola regla nueva: un triaje humano que fija categoría **y** severidad sobre una incidencia `OPEN` la pasa a `CLASSIFIED`, que es el origen desde el que `assign` reparte. El listado `/incidents` no cambia. Al terminar, el ciclo *huésped reporta desde el portal → manager asigna desde `/incidents/[id]` → técnico acepta y resuelve desde `/tech`* es posible por primera vez sin CLI, y el change lo deja recorrido en dev.

## Requirements

### R1 — Controles del manager, gateados por permiso y por estado

**Como** manager, **quiero** ver en el detalle de la incidencia sólo las acciones que puedo ejecutar ahora, **para** operar sin adivinar qué va a rechazar el backend.

Acceptance criteria:

1. WHEN el usuario autenticado tiene `MANAGE_INCIDENTS` en el espejo de `lib/auth/permissions.ts`, THE SYSTEM SHALL mostrar en `/incidents/[id]` una sección de acciones con asignar/reasignar, triar, relanzar clasificador y cancelar; la entrada `MANAGE_INCIDENTS` del espejo SHALL copiarse de `backend/app/auth/domain/policy.py` para **todos** los roles (`PROPERTY_MANAGER` sí; `TENANT_OWNER`, `TECHNICIAN`, `CLEANER`, `SUPER_ADMIN` no), como exige `specs/frontend-foundation.md`.
2. WHEN el usuario no tiene `MANAGE_INCIDENTS` (el `TENANT_OWNER` incluido), THE SYSTEM SHALL renderizar el detalle **sin ningún control de mutación ni hueco reservado para ellos**. La única diferencia respecto a hoy SHALL ser la de R2.6 —el técnico asignado se pinta por nombre y no por UUID, también para quien sólo lee—, porque el `TENANT_OWNER` tiene `READ_USERS` y enseñarle un identificador opaco no es comportamiento que preservar.
   > Enmienda del gate de `/sdd:design` (2026-09-05, OQ2): la redacción original decía «exactamente como hoy» y contradecía a R2.6 para el único otro rol que alcanza esta pantalla.
3. THE SYSTEM SHALL ofrecer cada acción sólo en los orígenes que `specs/maintenance.md` R1 admite: relanzar clasificador en `OPEN`; asignar/reasignar en `CLASSIFIED`, `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS` y `WAITING_EXTERNAL_PARTS`; triar en cualquier estado no terminal salvo `AWAITING_OWNER_APPROVAL`; cancelar en los siete no terminales. Esa tabla SHALL ser un `Record<IncidentStatus, …>` sobre el enum del contrato generado, como `TECH_ACTIONS` en `features/tech/lib/tech-actions.ts`, de modo que un décimo estado rompa el build en vez de dejar un botón fantasma.
4. WHEN la incidencia está en `AWAITING_OWNER_APPROVAL`, THE SYSTEM SHALL mostrar sólo cancelar y un texto localizado que diga que la incidencia espera la respuesta de la propietaria en `/approvals`; NEVER SHALL ofrecer responder la aprobación desde esta pantalla.
5. WHEN la incidencia está en `RESOLVED` o `CANCELLED`, THE SYSTEM SHALL no mostrar ninguna acción.
6. THE SYSTEM SHALL tratar esa tabla como presentación del contrato y no como autorización: el backend decide con `403`/`409` y el frontend sólo oculta (`steering/frontend.md`).

### R2 — Asignar o reasignar un técnico

**Como** manager, **quiero** asignar la incidencia a un técnico activo del tenant, con una nota si hace falta, **para** que aparezca en su `/tech` y arranque su plazo de SLA.

Acceptance criteria:

1. WHEN el manager abre la acción de asignar, THE SYSTEM SHALL ofrecer el roster de técnicos del tenant resuelto contra `GET /api/v1/users?role=TECHNICIAN` (permiso `READ_USERS`, que el `PROPERTY_MANAGER` tiene), con la **misma forma** que `features/cleaning/data/http/http-cleaning-source.ts` usa para `role=CLEANER` (catálogo sin filtro de `status`, `is_active` acarreado en el DTO), y SHALL permitir elegir sólo a los `ACTIVE`; los inactivos SHALL poder resolverse por nombre pero no seleccionarse.
2. WHEN la incidencia ya tiene asignatario, THE SYSTEM SHALL etiquetar la acción como reasignar, preseleccionar a nadie y avisar en texto localizado de que la ETA y la nota de la asignación vigente se pierden (`maintenance.md` R5: `eta_at` a `NULL`, `assignment_note` reescrita en cada llamada).
3. THE SYSTEM SHALL aceptar una nota de asignación opcional de hasta 2000 caracteres y SHALL rechazar en cliente, antes de enviar, cualquier carácter de control (`U+0000`–`U+001F` salvo salto de línea y tabulador), con mensaje localizado.
   > `ASSUMPTION`: `incidents.assignment_note` sigue sin pasar por `storable_text` en backend (entrada `assignment-note-storable-text`, pendiente), así que un `U+0000` hoy es un `500`. La guarda de cliente acota el síntoma; la corrección de fondo es de aquella entrada y este change no la absorbe.
4. WHEN el backend responde `200`, THE SYSTEM SHALL invalidar la consulta del detalle y la del contexto de la incidencia, cerrar el control y mostrar la incidencia en `ASSIGNED` con el nuevo técnico; NEVER SHALL pintar la transición antes de que el backend la confirme (sin actualización optimista, mismo criterio que `use-incident-cycle.ts`).
5. IF el backend responde `422` (`InvalidTechnicianError`: el usuario no es `TECHNICIAN` `ACTIVE` del tenant), THEN THE SYSTEM SHALL mostrar un mensaje localizado propio y mantener el control abierto; NEVER SHALL renderizar el `message` técnico del sobre de error.
6. WHEN el detalle muestra al técnico asignado, THE SYSTEM SHALL pintar su nombre resuelto contra el mismo roster en vez del UUID que hoy imprime `DetailAssignedTechnicianBlock`, y «no disponible» localizado si el roster no lo contiene o falla; el UUID NEVER SHALL ser visible. Esto SHALL valer para **todo** el que abra `/incidents/[id]`, tenga o no `MANAGE_INCIDENTS` (R1.2 enmendada).

### R3 — Triar: corregir categoría y severidad, fijar coste estimado

**Como** manager, **quiero** corregir lo que el clasificador dejó mal o no supo poner, y presupuestar el trabajo, **para** que la incidencia siga su curso con la severidad y el coste correctos.

Acceptance criteria:

1. WHEN el manager abre la acción de triar, THE SYSTEM SHALL presentar un formulario con categoría (`IncidentCategory`), severidad (`IncidentSeverity`) y coste estimado, precargado con los valores actuales, con las etiquetas de los dos locales que `incidents-web` ya dejó en `locales/*/incidents.json`.
2. THE SYSTEM SHALL enviar por `PATCH /api/v1/incidents/{id}` **sólo los campos que han cambiado** (el esquema es `extra="forbid"` y todo opcional), y el coste SHALL validarse en cliente como decimal no negativo con hasta dos decimales antes de enviarse, con la misma expresión que `resolve-incident-dialog.tsx`.
3. WHEN el backend responde `200` con `status = AWAITING_OWNER_APPROVAL`, THE SYSTEM SHALL comunicar en texto localizado que el coste estimado superó el umbral del tenant y la incidencia espera a la propietaria (`maintenance.md` R4), y SHALL ocultar las acciones conforme a R1.4.
4. WHEN el backend responde `200` con la incidencia todavía en `OPEN`, THE SYSTEM SHALL decir en texto localizado que sigue pendiente de clasificar y que para clasificarla hay que fijar categoría **y** severidad.
5. **[BE]** WHEN un triaje humano (`PATCH /incidents/{id}`) fija en la misma petición `category` **y** `severity` sobre una incidencia en `OPEN`, THE SYSTEM SHALL pasarla a `CLASSIFIED` mediante una operación de la tabla de transiciones de R1 (una fila nueva, no una excepción fuera de la tabla), escribir su `TimelineEvent` `INCIDENT_CLASSIFIED` con actor `USER` —la excepción de actor ausente de R9 es sólo de la vía automática— y reflejar el cambio de `status` en el `ChangeSet` del `AuditLog` `INCIDENT_TRIAGED`; NEVER SHALL tocar `ai_classification`, `title` ni `description`. WHERE esa clasificación deja la severidad en `HIGH` o `CRITICAL`, THE SYSTEM SHALL pedirle además a `PropertyStateMachine` que recomponga el estado de la vivienda con el mismo disparador que usa la vía automática (`INCIDENT_HIGH` / `INCIDENT_CRITICAL`), y NEVER SHALL disparar nada para `MEDIUM` ni `LOW`; ese disparo SHALL ser exclusivo de esta transición y NEVER SHALL alcanzar a un triaje que no clasifique. IF fija sólo uno de los dos, o ninguno, THEN la incidencia SHALL seguir en `OPEN` exactamente como hoy. IF el mismo triaje abre la puerta de aprobación (R4), THEN la incidencia SHALL acabar en `AWAITING_OWNER_APPROVAL` pasando por `CLASSIFIED`, que es el origen que `require_owner_approval` admite.
   > `ASSUMPTION`: exigir los dos campos, y no uno, porque una incidencia `CLASSIFIED` con la categoría o la severidad por defecto sería indistinguible de una clasificada de verdad, que es lo que R2 quiere evitar al dejarla en `OPEN`.
   >
   > Enmienda del gate de `/sdd:design` (2026-09-05, OQ1): la cláusula del estado de la vivienda no estaba en la redacción original y se añade porque el design la midió — crear una incidencia no dispara ningún trigger (`ReportIncidentUseCase`) y el clasificador sólo lo dispara al alcanzar `CLASSIFIED`, así que **hoy** una incidencia que quedó en `OPEN` no lleva la vivienda a `CRITICAL_INCIDENT` ni marcándola crítica a mano. Sin esto, el ciclo de R6.6 se recorrería dejando la vivienda en un estado que miente.
   >
   > Resuelto en el mismo gate: la operación se llama **`classify_by_triage`** y es fila propia de la tabla (design D1); `openapi.json` **sí** se regenera, porque cambia la descripción de la ruta (design D12) — el esquema no cambia. Y `docs/diagrams/2026-08-23_autohost-secuencia-mantenimiento.png` se regenera, por ser un paso nuevo del ciclo (OQ3).
6. THE SYSTEM SHALL cubrir R3.5 con tests de dominio y de API en `backend/tests/maintenance/`, incluido el caso negativo (un solo campo → sigue `OPEN`) y el aislamiento por tenant que ya cubre el `PATCH`.

### R4 — Relanzar el clasificador

**Como** manager, **quiero** pedir la clasificación automática ahora, sin esperar a los cinco minutos del job, **para** decidir con su veredicto si necesito triar a mano.

Acceptance criteria:

1. WHEN la incidencia está en `OPEN` y el manager relanza el clasificador, THE SYSTEM SHALL llamar a `POST /api/v1/incidents/{id}/classify` sin cuerpo y refrescar el detalle al terminar.
2. WHEN la respuesta llega con la incidencia todavía en `OPEN`, THE SYSTEM SHALL decir en texto localizado que el clasificador no alcanzó el umbral de confianza y ofrecer el triaje manual (R3) en el mismo sitio; NEVER SHALL mostrar el `ai_classification` en bruto.
3. WHEN la respuesta llega en `CLASSIFIED`, THE SYSTEM SHALL mostrar la categoría y severidad nuevas y habilitar asignar conforme a R1.3.

### R5 — Cancelar con confirmación

**Como** manager, **quiero** cerrar una incidencia que no procede, **para** que deje de bloquear el estado operativo de la vivienda.

Acceptance criteria:

1. WHEN el manager pulsa cancelar, THE SYSTEM SHALL pedir confirmación en un diálogo localizado que nombre la consecuencia (terminal, irreversible, el estado de la vivienda se recompone) antes de llamar a `POST /api/v1/incidents/{id}/cancel` sin cuerpo.
2. WHEN el backend responde `200`, THE SYSTEM SHALL mostrar la incidencia en `CANCELLED` sin ninguna acción disponible e invalidar también la lista `/incidents` y las consultas del dashboard que la muestren como estancamiento (`blocked-transitions`).
3. THE SYSTEM SHALL no pedir ni enviar motivo de cancelación: el contrato no lo tiene, y añadirlo es una entrada `[BE]` aparte.

### R6 — Errores, i18n, patrones y verificación de extremo a extremo

**Como** equipo, **quiero** que las cuatro mutaciones sigan los patrones que `tech-app` y `cleaning-manager-view` ya fijaron, **para** no estrenar una tercera forma de hacer lo mismo.

Acceptance criteria:

1. IF cualquier mutación responde `409`, THEN THE SYSTEM SHALL refrescar el detalle **también en el fallo** (`onSettled`) y explicar la negativa con `conflictReason(status)` de `features/incidents/lib/conflict-reason.ts` —cerrada, esperando a la propietaria, fuera de orden— en texto localizado; NEVER SHALL renderizar el `message` del sobre.
2. IF cualquier mutación responde `403`, THEN THE SYSTEM SHALL ocultar la sección de acciones y mostrar el texto de «sin permiso» que ya usa el detalle; `401` SHALL delegarse al flujo de expiración de sesión sin variante propia.
3. THE SYSTEM SHALL implementar los cuatro hooks nuevos en la capa de datos de `features/incidents` (fuente HTTP tipada sobre `openapi.d.ts` + hooks TanStack Query con `retry: false`, sin actualización optimista), exportados por el barrel de la feature, y SHALL cubrirlos con tests unitarios de fuente y de hook como los que ya existen para el ciclo del técnico.
4. THE SYSTEM SHALL pasar toda string visible por `locales/es/` y `locales/en/` (`incidents.json`, y `navigation.json` si hace falta), sin ninguna hardcodeada, y SHALL mantener el color de estado como está hoy (chip neutro): la tabla estado→`Tone` es la entrada `incident-status-tone` y este change **no la crea ni la absorbe**.
5. THE SYSTEM SHALL cubrir con tests de componente: visibilidad por permiso (manager sí, owner no), la tabla estado→acciones, los tres caminos del `409`, el `422` de técnico inválido, la validación en cliente del coste y de la nota, y el nombre del técnico resuelto.
6. WHEN el change se declare implementado, THE SYSTEM SHALL haber recorrido en dev —con Playwright o a mano, con `PORT_OFFSET` si va en worktree (`sdd/project.md` §Worktree bootstrap)— el ciclo *huésped reporta desde el portal → clasificador o triaje → manager asigna desde `/incidents/[id]` → técnico acepta y resuelve desde `/tech`*, y dejarlo anotado en `tasks.md` con lo observado.

## Out of scope

- **Responder aprobaciones** y la pantalla `/approvals` — entrada `approvals-web`. Aquí sólo se pinta el estado `AWAITING_OWNER_APPROVAL` y a quién le toca (R1.4).
- **Crear una incidencia como manager** — no existe `POST /api/v1/incidents` para ese rol, ausencia deliberada (docstring de `incidents_router.py`; DoD §28.8 pide huésped / limpiadora / propietario). Sería entrada `[BE]` aparte.
- **Motivo de cancelación** — el contrato no lo tiene (R5.3).
- **`incident-status-tone`** — el chip de estado sigue neutro; la tabla estado→`Tone` es decisión de vocabulario de esa entrada (R6.4).
- **`assignment-note-storable-text`** — la guarda de cliente de R2.3 acota el síntoma; el `storable_text` en backend es de aquella entrada.
- **`incident-list-property-projection`** — el listado `/incidents` no cambia.
- **Las seis operaciones del técnico** (`accept`, `reject`, `en-route`, `wait-parts`, `resume`, `resolve`) desde `/incidents/[id]` — el manager tiene `EXECUTE_INCIDENTS` «para desatascar» (`maintenance.md` R8), pero la superficie donde se ejercen es `/tech` y la tarjeta de estancamiento del dashboard; abrirlas aquí sería una segunda copia del ciclo.
- **Autoasignación de incidencias** (equivalente a `resolve_auto_assignee` de limpieza) — decisión de producto que PRD §12 no pide; si se quiere, entrada `[BE]` propia.
- **Fotos de incidente** desde la vista del manager (ya en `/tech`), **hilo de mensajes del personal** (`staff-messaging-web`), **ETA** del técnico (la fija el técnico en `accept`/`en-route`).
- **`tech-app`, `cleaner-app`, `/cleaning`** y cualquier otra superficie: no se tocan.

## Affected specs

- **`sdd/specs/maintenance.md`** — se modifica: R1 gana la operación `classify_by_triage` (`OPEN → CLASSIFIED`) en la tabla de transiciones y su regla; R9 anota que ese `INCIDENT_CLASSIFIED` lleva actor `USER`; **R4.6 anota que esa misma transición dispara `INCIDENT_HIGH`/`INCIDENT_CRITICAL` sobre la vivienda** (enmienda de R3.5 en el gate de design); la tabla RBAC de R8 no cambia (el manager ya tenía «leer, clasificar, triar, asignar, cancelar»).
- **`sdd/specs/frontend-foundation.md`** — se modifica: la frase de la línea de rutas que dice que «las cuatro operaciones del manager … se exponen en entradas futuras» pasa a nombrar esta; la regla del espejo de permisos gana la fila `MANAGE_INCIDENTS`.
- **`sdd/specs/incidents-web.md`** *(no existe aún — se creará al archivar)* — la superficie `/incidents` del manager no tiene spec propia: `incidents-web` documentó lista y detalle sólo en la línea de rutas de `frontend-foundation.md`. Con mutaciones, la superficie tiene comportamiento que merece capability propia (precedente: `cleaning-manager-view.md` para `/cleaning`). Si el gate prefiere no estrenarla, el destino alternativo es una sección en `maintenance.md`.
- **`sdd/specs/frontend-api-contract-consumer.md`** — no se modifica salvo que el design decida regenerar `openapi.json` por la descripción del `PATCH` (R3.5); el esquema de los cuatro cuerpos no cambia.
- **`sdd/specs/tech-app.md`**, **`tech-incident-context.md`**, **`user-management.md`** — no se modifican; se consumen tal cual (`/context`, `GET /users?role=`).
- **`sdd/roadmap.md`** — no se toca aquí (regla compartida 1); al archivar, la entrada pasa de `[FE]` a `[FE+BE]` por la decisión del gate y se tica.
