# Proposal: cleaning-manager-task-detail

## Why

`/cleaning` ya existe como lista (`cleaning-manager-view`, archivada 2026-08-22) y entrega
`GET /api/v1/cleaning-tasks` con paginación, filtros por propiedad/estado y el control de
asignación gateado por `MANAGE_CLEANING_TASKS`. Pero el **detalle de una tarea**
(`/cleaning/[id]`) sigue sin existir: la única forma de ver qué pasa con una limpieza concreta
es ir al listado y leer una fila. PRD §24 no declara esa ruta, así que hoy el manager revisa
un `CLEANING_IN_PROGRESS` desde el listado, abre la ficha de la vivienda si necesita contexto
(`/properties/[id]`, `dashboard-web`), o salta a `/cleaner/tasks/[id]` con una cuenta de
limpiadora — un camino que no le corresponde y que pierde el control de asignación, validar y
cancelar que el listado sí le da.

La ausencia de esa página bloquea dos entradas del roadmap que la necesitan como base, ambas
añadidas el 2026-09-17 al auditar `staff-messaging-web`:

- **`photo-storage-manager-view`**: las fotos de limpieza del manager (`GET /cleaning-tasks/{id}/photos`)
  ya las sirve el backend con `READ_CLEANING_TASKS` y `useIncidentPhotos()` ya existe en el
  frontend, pero ninguna pantalla del manager las pinta. No tiene dónde montarse sin
  `/cleaning/[id]`.
- **`staff-messaging-manager-view`**: el hilo limpiadora↔manager
  (`GET/POST /cleaning-tasks/{id}/messages`) ya existe por backend (`staff-messaging` D3) y
  `staff-messaging-web` recortó explícitamente la vista del manager para no dar cobertura
  asimétrica frente a `/incidents/[id]`. La pieza que falta es la página donde colgarlo.

`cleaning-manager-view` (§Out of scope, *Detalle de una tarea*) ya dejó escrito que iría a
**«una entrada propia del roadmap cuando exista la superficie de detalle»**. Esta es esa
entrada.

Entrada de roadmap `cleaning-manager-task-detail` (hito «MVP operable», *superficie de detalle
para limpieza que ya existía para incidencias*; `needs: cleaning-manager-view`, archivada;
talla S, segunda entrada ad-hoc de Marta al roadmap de FE).

## What changes

Se añade `/cleaning/[id]` — la página de detalle de una tarea de limpieza para
`PROPERTY_MANAGER` y `TENANT_OWNER`, **consumiendo los endpoints que ya existen** y **sin
tocar el backend**. La página monta seis bloques de información (encabezado, identificación,
asignación, programación, ciclo de vida y metadatos) y, sólo para `MANAGE_CLEANING_TASKS`,
los tres controles que el listado ya posee — asignar/reasignar, validar y cancelar — sobre la
misma tarea, sin recargar la página entre operaciones. El acceso desde el listado es un enlace
por fila; el regreso es un enlace «Volver al listado» en la cabecera.

**No se regenera el contrato**: `CleaningTaskResponse` ya publica los 17 campos que la vista
consume (id, property_id, reservation_id, checklist_template_id, assigned_cleaner_id, status,
scheduled_start/end, accepted_at, started_at, completed_at, validated_at, validated_by_user_id,
validation_status y created_at) y `CleaningTask` en `features/cleaning/data/dto.ts` ya los
mapea vía `mapTask`. La identidad legible de la vivienda (`property_internal_code`,
`property_name`) **no viaja en `CleaningTaskResponse`** — verificado el 2026-09-17 contra
`backend/openapi.json` —, así que la página la resuelve vía `usePropertyDirectory()` (R3.5),
igual que `cleaning-manager-view` ya hace en el listado. Se añade un
`getTask(tenantId, taskId)` a la frontera `CleaningDataSource` y un `useCleaningTask` al lado
de los hooks existentes.

**Sin permiso nuevo**: la lectura usa `READ_CLEANING_TASKS` (la tienen manager y owner); las
tres mutaciones usan `MANAGE_CLEANING_TASKS` (sólo manager) — exactamente los tres permisos
que `cleaning-manager-view` y `cleaning-task-manage-web` ya verifican con
`useHasPermission`. El backend rechaza `404`/`403`/`409` con la misma forma que el resto de
las rutas de `cleaning/api/tasks_router.py`.

**El hueco que esta página cierra en `frontend/app/route-coverage.test.ts`**: hoy el fichero
declara `"(workspace)/incidents/[id]/page.tsx": "incident-detail"` pero no existe
`(workspace)/cleaning/[id]/page.tsx`, así que el conteo de superficies funcionales del
frontend está **subestimado** desde 2026-08-22 (cuando `cleaning-manager-view` dejó la página
fuera). Esta entrada añade la página real y la entrada correspondiente en la tabla
`REAL_PAGE_ROUTE_IDS`, dejando el contrato de cobertura cierto otra vez.

## Requirements

### R1 — Página de detalle para una tarea de limpieza

**As a** `PROPERTY_MANAGER` o `TENANT_OWNER`, **I want** abrir `/cleaning/[id]` para ver una
tarea concreta, **so that** pueda revisar su estado, su asignación y su ciclo de vida sin
recorrer el listado.

Acceptance criteria:

1. WHEN un usuario autenticado con `READ_CLEANING_TASKS` navega a `/cleaning/[id]` con un id
   que existe en su tenant, THE SYSTEM SHALL renderizar la página de detalle de la tarea
   indicada, **NO** el `RoutePlaceholder` que existe implícito al no haber ruta registrada, y
   NO una pantalla en blanco.
2. WHEN el id de la URL no corresponde a una tarea del tenant del usuario, THE SYSTEM SHALL
   mostrar el mismo `EmptyState` "tarea no disponible" que la app móvil ya usa para este
   caso, con un enlace de regreso a `/cleaning`.
3. WHEN la petición está en vuelo, THE SYSTEM SHALL mostrar `LoadingState` con `aria-busy`,
   sin pintar datos a medias ni un esqueleto que ocupe más de una pantalla.
4. IF la petición falla por un error distinto de `403`/`404`/`422`, THEN THE SYSTEM SHALL
   mostrar `ErrorState` con `role="alert"` y un botón de reintento que vuelve a lanzar la
   consulta, sin recargar la página.
5. THE SYSTEM SHALL registrar `/cleaning/[id]` en el `routeRegistry` con
   `pattern: "/cleaning/[id]"`, `profile: "workspace"`, `match: "exact"`, y
   `breadcrumbKeys: crumbs("cleaning", "cleaning-detail")`, además de añadir
   `(workspace)/cleaning/[id]/page.tsx` a `REAL_PAGE_ROUTE_IDS` en
   `frontend/app/route-coverage.test.ts` con la clave `cleaning-detail` — sin esto la suite
   `App Router coverage` falla en CI (R6.2 de `cleaning-manager-view`, gate del panel del
   2026-09-17 sobre el inventario de superficies).

### R2 — Encabezado con estado, validación y ventana programada

**As a** manager que llega del listado, **I want** ver de un vistazo el estado, el veredicto
de validación y la ventana programada de la tarea, **so that** decida sin desplazar la pantalla
qué acción tomar.

Acceptance criteria:

1. WHEN la página renderiza, THE SYSTEM SHALL mostrar en el encabezado: el estado de la tarea
   (`CleaningTaskStatus`, traducido y coloreado como en `cleaning-manager-view` R1.6), el
   `validation_status` vigente (`PENDING`/`PASSED`/`FAILED`/`WAIVED`, traducido), y el
   intervalo `scheduled_start`–`scheduled_end` formateado con el `formatDateTime` que la
   suite de frontend ya comparte (entrada `shared-datetime-formatter` pendiente —
   mientras no esté, se acepta la copia local que ya tiene `cleaning-task-manage-web` en
   `features/cleaning/components/cleaning-task-row.tsx`).
2. WHERE `completedAt !== null` o `validationStatus !== "PENDING"`, THE SYSTEM SHALL mostrar
   `completed_at` y, si existe, `validated_at` con la etiqueta traducida del rol de la
   operación (limpieza completada / validación registrada), siguiendo D7 de
   `cleaning-task-manage-web`.
3. WHERE `validation_status === "FAILED"` y `validated_at` existe, THE SYSTEM SHALL
   mostrar, **en todos los roles** (lectura no se oculta por permiso, igual que en
   `cleaning-manager-view` R3.3/D7), la fecha y la etiqueta de "Validación rechazada",
   sin texto de aviso de consecuencias (eso vive en el control de validar, R5).

### R3 — Identidad legible: vivienda y reserva por nombre, limpiadora por nombre

**As a** manager que viene del listado, **I want** leer en el detalle la vivienda y, si
existe, la reserva, **so that** entienda el contexto sin traducir UUIDs.

Acceptance criteria:

1. THE SYSTEM SHALL mostrar `internal_code` y `name` de la vivienda resolviendo
   `property_id` contra `usePropertyDirectory()` (R3.5), y NO mostrar el `property_id` crudo
   como identidad — la respuesta de `GET /cleaning-tasks/{task_id}` no expone esos campos
   (verificado 2026-09-17 contra `backend/openapi.json`), así que la resolución por catálogo
   es la única vía sin tocar el backend.
2. IF `reservation_id` no es `null` y la reserva es visible para el usuario, THEN THE SYSTEM
   SHALL mostrar el código de la reserva (mismo criterio que `IncidentDetailView` aplica a su
   `reservationId`); IF el usuario no puede verla (`404` en la resolución), THEN THE SYSTEM
   SHALL degradar a un indicador traducido de "reserva no disponible" y continuar.
3. WHERE la tarea tiene `assigned_cleaner_id`, THE SYSTEM SHALL mostrar el nombre de la
   limpiadora resuelto contra `useCleanerDirectory()` (ya cacheado por `useCleaningData`,
   sin petición nueva por fila — R2.5 de `cleaning-manager-view`); IF la limpiadora está
   desactivada o no aparece en la página consultada, THEN THE SYSTEM SHALL degradar a
   "asignada (nombre no disponible)" sin romper la página.
4. IF `assigned_cleaner_id` es `null`, THEN THE SYSTEM SHALL mostrar de forma explícita y
   traducida "Sin asignar", distinguible de "limpiadora no disponible" (R3 de
   `cleaning-manager-view`).
5. THE SYSTEM SHALL resolver vivienda y limpiadora con los hooks existentes
   (`usePropertyDirectory()`, `useCleanerDirectory()`), sin emitir una petición nueva por la
   sola apertura del detalle — la caché de TanStack Query lo cubre si el usuario ya abrió
   `/cleaning` (mismo invalidation prefix `cleaningKeys.tasksPrefix(tenantId)`); IF el
   usuario entra directamente a `/cleaning/[id]` por enlace profundo (deep link), THEN THE
   SYSTEM SHALL disparar la consulta del directorio en paralelo a la de la tarea y pintarla
   cuando llegue, sin bloquear el render del resto.

### R4 — Fila de "ir al contexto" sin salir del detalle

**As a** manager, **I want** saltar desde `/cleaning/[id]` a la ficha de la vivienda y al
listado, **so that** pueda ver el contexto operativo (estado, próximas estancias, historial)
sin tener que volver atrás y clicar de nuevo.

Acceptance criteria:

1. THE SYSTEM SHALL mostrar un enlace "Ver vivienda" que apunte a `/properties/[property_id]`
   sólo si `useHasPermission("READ_PROPERTIES")` — manager y owner lo tienen; el enlace abre
   en la misma pestaña.
2. THE SYSTEM SHALL mostrar un enlace "Volver al listado" en la cabecera (junto al título) que
   apunte a `/cleaning`, accesible por teclado y operable por lector de pantalla.
3. WHERE `reservation_id` no es `null` y el usuario tiene `READ_RESERVATIONS`, THE SYSTEM
   SHALL mostrar un enlace "Ver reserva" que apunte a `/reservations/[reservation_id]`,
   siguiendo la misma forma que R4.1; IF la reserva existe pero el usuario no tiene permiso
   para verla, THEN THE SYSTEM SHALL ocultar el enlace, NO degradar a texto plano, porque
   R3.2 ya mostró el código de la reserva como dato.

### R5 — Acciones del manager: asignar, validar, cancelar (mismas tres que el listado)

**As a** `PROPERTY_MANAGER`, **I want** operar la tarea desde su detalle igual que desde el
listado, **so that** el cambio de contexto entre lista y detalle no me haga perder el control
que ya tenía.

Acceptance criteria:

1. THE SYSTEM SHALL mostrar los tres controles (`AssignCleanerControl`,
   `ValidateCleaningControl`, `CancelCleaningTaskDialog`) sólo si
   `useHasPermission("MANAGE_CLEANING_TASKS")` — para `TENANT_OWNER` no se renderiza ninguno
   (R4.3 de `cleaning-manager-view`, mismo gate que el listado).
2. THE SYSTEM SHALL reusar **los componentes existentes** en `features/cleaning/components/`:
   `AssignCleanerControl` (listado, R4 de `cleaning-manager-view`),
   `ValidateCleaningControl` (D6 de `cleaning-task-manage-web`),
   `CancelCleaningTaskDialog` (D5 de `cleaning-task-manage-web`). Sin variantes propias del
   detalle — la operación es la misma y la región viva única de la página (R5.5) anuncia el
   resultado exactamente igual que en el listado.
3. THE SYSTEM SHALL invalidar `cleaningKeys.tasksPrefix(tenantId)` y la clave específica
   `cleaningKeys.task(taskId)` (nueva, sección 1 de tareas) tras el éxito de cualquier
   mutación, de modo que el encabezado refleje el nuevo estado sin recarga y, si el usuario
   vuelve al listado, la fila ya esté actualizada — sin invalidar `cleaningKeys.tasks`
   (filtro/página concretos del listado).
4. WHEN una mutación termina con `403`/`404`/`409`/`422`, THE SYSTEM SHALL mostrar el error
   traducido correspondiente por la región viva de la página y, para `403` y `404`,
   refetchear la tarea (para que un `404` no deje el detalle mostrando un estado que ya no
   es válido, exactamente la convención que R4 de `staff-messaging-web` declara para los
   `404`).
5. THE SYSTEM SHALL declarar una **única región viva** `role="status" aria-live="polite"`
   para los anuncios de las tres mutaciones, siguiendo D11 de `cleaning-manager-view` y
   D4/D11 de `cleaning-task-manage-web`. Los diálogos (`CancelCleaningTaskDialog`) siguen
   siendo la excepción declarada: pintan su propio `role="alert"` mientras el Sheet está
   abierto, igual que en el listado.

### R6 — i18n, accesibilidad y mobile-first

**As a** propietaria que opera desde el móvil, **I want** la página en mi idioma y operable
en 320 px, **so that** revise limpiezas sin abrir el portátil.

Acceptance criteria:

1. THE SYSTEM SHALL declarar toda string visible nueva (cabecera, etiquetas de bloque, enlaces,
   estados vacío/error/carga, mensajes de las acciones, el título del breadcrumb
   `cleaning-detail` en `locales/es/navigation.json` y `locales/en/navigation.json`) en
   `locales/es/` y `locales/en/`, sin cadenas incrustadas en los componentes — gateado por
   `steering/frontend.md` y la regla del panel i18n.
2. THE SYSTEM SHALL renderizar la página de forma legible y operable desde 320 px de ancho,
   sin scroll horizontal; los seis bloques se apilan en una columna, los controles se
   mantienen accesibles (objetivo táctil ≥ 44×44 px) y el encabezado no recorta texto.
3. THE SYSTEM SHALL exponer los tres controles (R5) con etiqueta accesible, foco visible y
   orden de tabulación lógico (encabezado → bloques informativos → controles → enlaces de
   contexto).
4. WHEN una acción de las tres mutaciones termina, THE SYSTEM SHALL anunciar el resultado
   por la región viva única de la página (R5.5), de modo que un lector de pantalla lo
   perciba sin depender del color.
5. WHERE el ancho de viewport es 360 px, THE SYSTEM SHALL mostrar la página sin overflow ni
   recorte (steering/frontend.md, *Responsive verificable*).

## Out of scope

- **Galería de fotos de la limpieza** (`GET /cleaning-tasks/{task_id}/photos`). El backend
  ya la sirve con `READ_CLEANING_TASKS` (mismo permiso que esta página usa para leer), pero
  pintarla aquí abriría un componente de visor y un paginado que esta entrada no mide ni
  declara. Es exactamente el hueco que `photo-storage-manager-view` promete cerrar, y esta
  entrada es su prerrequisito. Si al implementar se observa que ambos cambios van a tocar
  los mismos seis bloques del detalle, se eleva el solapamiento a `design.md` antes de
  fusionar.
- **Hilo de mensajes limpiadora↔manager** (`GET/POST /cleaning-tasks/{id}/messages`).
  `staff-messaging` lo autoriza a `PROPERTY_MANAGER` (D3) y `staff-messaging-web` recortó
  explícitamente la vista del manager sobre el hilo. Es exactamente el hueco que
  `staff-messaging-manager-view` promete cerrar, y esta entrada es su prerrequisito
  simétrico.
- **Renderizado del checklist** (`GET /cleaning-tasks/{id}/checklist`). El backend lo
  publica, pero pintarlo aquí abre una superficie interactiva (ítems, fotos por ítem, cierre
  de ítem) que es del rol `CLEANER` en `/cleaner/tasks/[id]` (`cleaner-app`); replicarla
  para el manager duplica lógica y entra en colisión con la app móvil.
- **Cierre de una limpieza desde el detalle** (`POST /cleaning-tasks/{id}/complete`,
  `accept`, `reject`, `start`). Son las cinco transiciones del ciclo de vida de la limpiadora
  (`cleaning` change, design D-cleaning), y la pantalla de la limpiadora
  (`/cleaner/tasks/[id]`) las posee ya; el manager no las dispara, las **supervisa**.
- **Edición de la ventana programada** (`PATCH /cleaning-tasks/{id}`). El backend acepta
  `assigned_cleaner_id` y nada más (D13 de `cleaning`); reprogramar no existe como
  operación. Si surge, va a una entrada propia.
- **Vista del técnico sobre la misma tarea**. La tarea puede derivar en una incidencia
  (`POST /cleaning-tasks/{task_id}/incidents`, `cleaner-incident-report`), pero la vista
  del técnico es `/tech/incidents/[id]`, sobre la incidencia resultante, no sobre la tarea.
- **Crear / validar / cancelar / asignar sin recargar**: ya está resuelto por las tres
  mutaciones del listado y se reusa tal cual en R5.
- **Cambios en el backend**. `CleaningTaskResponse` ya expone los campos que la vista
  consume; los nombres legibles de la vivienda (`property_internal_code`, `property_name`)
  vienen del catálogo (`usePropertyDirectory()`), no de la respuesta de la tarea. Si al
  implementar se descubre un campo nuevo indispensable, esa decisión es un change aparte y
  vuelve esta entrada a `design.md` para reescribir el alcance.

## Affected specs

- `sdd/specs/cleaning-manager-task-detail.md` *(no existe aún — se creará al archivar)*: el
  comportamiento de la vista `/cleaning/[id]`.
- `sdd/specs/cleaning-manager-view.md`: su §Out of scope deja de ser cierto (la entrada
  prometió que "/cleaning/[id]" sería una entrada propia — esa entrada es esta). Pasa a
  referenciar este change como su cierre natural.
- `sdd/specs/cleaning.md`: sin cambio de comportamiento del backend; el contrato
  `CleaningTaskResponse` no se modifica.
- `sdd/specs/staff-messaging.md`: el §Out of scope de `staff-messaging-web` cita esta
  entrada como el prerrequisito que desbloquea `staff-messaging-manager-view`. Al archivar
  esta entrada, ese §Out of scope deja de bloquear a la siguiente.
- `frontend/app/route-coverage.test.ts`: añadir `(workspace)/cleaning/[id]/page.tsx` →
  `cleaning-detail` a la tabla `REAL_PAGE_ROUTE_IDS`. Sin esto el test falla en CI desde
  que esta página exista en disco (R1.5, gate del panel de cobertura del frontend).
- `frontend/features/shell/navigation/route-registry.ts`: añadir la entrada
  `cleaning-detail` (pattern `/cleaning/[id]`, profile `workspace`, match `exact`,
  `breadcrumbKeys: crumbs("cleaning", "cleaning-detail")`).
- `frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json`: añadir
  `routes.cleaning-detail.{title,description}` (R1.5, R6.1) — `cleaning-task-manage-web` no
  las añadió porque no declaró la página; esta entrada las declara y las materializa.
- `sdd/specs/frontend-foundation.md`: su inventario de «18 placeholder pages plus three
  functional surfaces» se queda otra vez desincronizado — pasa a **17 placeholders y cinco
  superficies funcionales** al añadir `/cleaning/[id]`. Revisar al archivar que el censo
  coincida con el conteo vivo de `frontend/app/route-coverage.test.ts` (R1.5) y con
  `route-surface-counts-have-an-authoritative-source`.
