# Proposal: cleaner-app

## Why

`/cleaner` y `/cleaner/tasks/[id]` existen como `RoutePlaceholder` desde `frontend-foundation`,
con `CleanerShell` y `AuthGuard allow={["CLEANER"]}` ya puestos. El rol `CLEANER` es el único
del PRD que queda sin superficie funcional propia: hoy una limpiadora que entra ve
«En preparación» en ambas rutas.

La entrada se abrió y se cerró **sin proposal el 2026-08-23**, porque de las nueve cosas que
PRD §11 «UI de limpiadora» enumera ninguna tenía backend servido con permisos del rol.
De ahí salieron tres entradas `[BE]` —`cleaner-task-context` (archivada 2026-08-19),
`cleaner-incident-report` (archivada 2026-08-22) y `cleaner-photo-requirements`
(archivada 2026-08-24)—, las **tres archivadas**. El censo de `sdd/roadmap/cleaner-app.md`
ya no tiene ningún ❌ y se ha vuelto a medir contra el código para este proposal: las nueve
peticiones de PRD §11 están servidas por rutas que el rol `CLEANER` puede llamar.

Fuentes: PRD §11 (UI de limpiadora), §24 (páginas), §26.19 (orden de desarrollo);
`sdd/roadmap/cleaner-app.md` (censo y precisiones); y los contratos vivos en `sdd/specs/cleaning.md`,
`sdd/specs/cleaner-task-context.md`, `sdd/specs/cleaner-incident-report.md` y
`sdd/specs/cleaner-photo-requirements.md`.

## What changes

Las dos páginas del segmento `(field)/cleaner` dejan de ser placeholders y pasan a ser
superficies funcionales sobre la API de limpieza que ya existe: una lista «mis tareas» con
la vivienda y la ventana de cada fila, y un detalle que reúne el piso, el contexto temporal,
el checklist ítem a ítem con progreso, las categorías de foto que pide la tarea con su
estado de cobertura, la galería de fotos subidas y los seis botones del ciclo (aceptar /
rechazar / iniciar / completar / marcar checklist / reportar incidencia), con la regla de
validación de tres cláusulas del cierre aplicada tal como el backend la resuelve.

**Es un change de frontend en su totalidad**: no toca esquema, ni migraciones, ni el
contrato publicado. El cliente tipado generado (`frontend/lib/api/generated/openapi.d.ts`)
ya conoce las once rutas implicadas — verificado contra `backend/openapi.json`:
`GET /cleaning-tasks`, `GET /cleaning-tasks/{id}`, `GET /cleaning-tasks/{id}/context`,
`GET /cleaning-tasks/{id}/checklist`, `POST /cleaning-tasks/{id}/checklist/{item_id}/complete`,
`GET /cleaning-tasks/{id}/photo-requirements`, `GET /cleaning-tasks/{id}/photos`,
`POST /cleaning-tasks/{id}/photos`, `POST /cleaning-tasks/{id}/incidents`,
`POST /cleaning-tasks/{id}/accept`, `POST /cleaning-tasks/{id}/reject`, `POST /cleaning-tasks/{id}/start`,
`POST /cleaning-tasks/{id}/complete`.

**Permisos, contados contra `backend/app/auth/domain/policy.py`.** `CLEANER` es
`_SELF_SERVICE | _CLEANING_EXECUTE` = `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`, `READ_CLEANING_TASKS`, `EXECUTE_CLEANING_TASKS`. Cruzado con
las dependencias declaradas en `app/cleaning/api/tasks_router.py`, puede llamar exactamente
a: `GET /cleaning-tasks` (ReadDep), `GET /cleaning-tasks/{id}` (ReadDep),
`GET /cleaning-tasks/{id}/context`, `GET /cleaning-tasks/{id}/checklist`,
`GET /cleaning-tasks/{id}/photo-requirements`, `GET /cleaning-tasks/{id}/photos`
(ReadDep); `POST /cleaning-tasks/{id}/checklist/{item_id}/complete`,
`POST /cleaning-tasks/{id}/photos`, `POST /cleaning-tasks/{id}/incidents`,
`POST /cleaning-tasks/{id}/accept`, `POST /cleaning-tasks/{id}/reject`,
`POST /cleaning-tasks/{id}/start`, `POST /cleaning-tasks/{id}/complete` (ExecuteDep).
**No** puede llamar a `POST /cleaning-tasks/{id}/cancel` (ManageDep), ni a
`POST /api/v1/cleaning-tasks` (gestión de plantilla). Toda la pantalla cabe dentro de esa lista.

**El aterrizaje por rol tras el login ya está implementado.** `frontend-auth-session.md`
R1 fija la redirección por rol (`CLEANER → /cleaner`, `TECHNICIAN → /tech`,
`TENANT_OWNER/PROPERTY_MANAGER → /dashboard`) vía `roleHome(user.role)` con el
interstitial `/welcome?role=<rol>` para roles de campo. Esa spec se consolidó en
`frontend-auth-role-routing` (archivado 2026-08-27), así que esta entrada **no**
reabre ese trabajo y se queda en las dos pantallas.

## Requirements

### R1 — Mis tareas en `/cleaner`

**Como** limpiadora, **quiero** ver mis tareas asignadas con el piso y la ventana, **para**
saber qué tengo pendiente sin llamar al manager.

Criterios de aceptación:

1. WHEN una usuaria autenticada con rol `CLEANER` abre `/cleaner`, THE SYSTEM SHALL sustituir el
   `RoutePlaceholder` actual por la lista servida por `GET /api/v1/cleaning-tasks`, y SHALL NOT
   enviar ningún parámetro que identifique a la limpiadora: el acotamiento por fila lo deriva el
   backend del token (`CleaningActor.restrict_to_cleaner_id`) y no existe parámetro de consulta
   para él. La paginación respeta los parámetros `page` y `per_page` que el contrato publica.
2. WHEN la lista se renderiza, THE SYSTEM SHALL mostrar por fila, además de los dieciséis campos
   de `CleaningTaskListItemResponse` (incluido `assignment_blocked_by`), el `property_name` y el
   `property_internal_code` obtenidos de `GET /api/v1/cleaning-tasks/{id}/context` para esa fila,
   junto con la `checkout_at` y el `next_checkin_deadline` formateados en el `timezone` de la
   propiedad que devuelve `/context`.
3. THE SYSTEM SHALL emitir la consulta de contexto de cada fila bajo la **misma clave de query
   tenant-scoped** que usará el detalle, de modo que abrir una fila no vuelva a pedir su contexto.
   El número de peticiones paralelas está acotado por el tamaño de página (`per_page`), y con el
   MVP de 2 viviendas el cardinal real es 1-3 —verificado en `sdd/roadmap/cleaner-app.md` §1—.
4. WHERE el `property_id` de una tarea no resuelve dentro del tenant, THE SYSTEM SHALL mostrar
   la fila con el em-dash `—` (U+2014) en lugar del nombre y SHALL NOT abortar la lista por una
   sola tarea inalcanzable: el resto de la página debe seguir siendo visible.
5. WHERE no hay ningún filtro seleccionado, THE SYSTEM SHALL pedir la página sin `status` y
   presentarla en el orden que sirve el backend (`created_at` descendente) SIN reordenar en
   cliente. Los chips de estado cubren los siete estados visibles para una limpiadora sobre sus
   propias filas (`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `PENDING_REVIEW`, `COMPLETED`,
   `REJECTED`, `CANCELLED`): `CREATED` no se ofrece porque su filtro devolvería siempre vacío
   para un rol `CLEANER` —no hay tareas `CREATED` asignadas—.
6. WHEN la usuaria selecciona un chip de estado, THE SYSTEM SHALL re-consultar con un **único**
   valor `status` —el contrato no admite varios— y reflejar la selección en la clave de query; un
   segundo clic sobre el chip activo SHALL volver al estado sin filtro.
7. IF la respuesta está vacía, THEN THE SYSTEM SHALL renderizar el `EmptyState` compartido con un
   texto localizado que invite a esperar la próxima asignación; IF la petición falla, THEN THE
   SYSTEM SHALL renderizar el `ErrorState` compartido sin exponer el detalle del error, sin
   reintento en `4xx`.

> `ASSUMPTION`: el cambio de página se hace con el paginador estándar del shell (mismo patrón
> que `incidents-web` archivado 2026-08-20), y el conjunto de chips se decide en `/sdd:design`
> cuando el componente concreto esté delante.

### R2 — Detalle de tarea en `/cleaner/tasks/[id]`: piso, ventana, checklist, fotos

**Como** limpiadora, **quiero** abrir una tarea y ver el piso, su dirección, la ventana de
trabajo, el checklist y los botones de foto por categoría, **para** planificar la limpieza
sin tener que recordar lo que vi en la lista.

Criterios de aceptación:

1. WHEN una limpiadora abre `/cleaner/tasks/[id]`, THE SYSTEM SHALL sustituir el `RoutePlaceholder`
   actual y componer la pantalla con `GET /api/v1/cleaning-tasks/{id}` y las cuatro proyecciones
   hermanas —`GET /api/v1/cleaning-tasks/{id}/context`, `/checklist`, `/photo-requirements`,
   `/photos`— emitidas en paralelo bajo claves tenant-scoped distintas.
2. THE SYSTEM SHALL mostrar de `CleaningTaskResponse`: `id`, `status`, `property_id`,
   `reservation_id`, `scheduled_start`, `scheduled_end`, `accepted_at`, `started_at`,
   `completed_at`, `validation_status`, y SHALL mostrar de `CleaningTaskContextResponse`:
   `property_name`, `property_internal_code`, los seis campos de dirección postal
   (`address_line1`, `address_line2`, `city`, `province`, `postal_code`, `country`), `timezone`,
   `checkout_at` y `next_checkin_deadline` con su `description` documentada del contrato.
3. THE SYSTEM SHALL mostrar el checklist con los ítems servidos por
   `GET /api/v1/cleaning-tasks/{id}/checklist` en el orden que devuelve el backend (el de la
   plantilla), cada uno con su `item_id`, su `label`, su `required` y su estado de completado
   (`pending` / `completed_at` con el instante y la autora).
4. THE SYSTEM SHALL mostrar las categorías de foto servidas por
   `GET /api/v1/cleaning-tasks/{id}/photo-requirements` en el orden declarado en la plantilla
   —no en el orden de iteración de un `frozenset`—, cada una con su `photo_type`, su `label`,
   su `required` y su `uploaded`. Una categoría con `uploaded: true` se pinta como «cubierta» y
   una con `required: true` y `uploaded: false` se pinta como pendiente.
5. THE SYSTEM SHALL mostrar la galería de `GET /api/v1/cleaning-tasks/{id}/photos` con cada
   `CleaningPhotoResponse.url` en el `src` de la imagen, **tal cual**, en el orden que sirve el
   backend (de la más antigua a la más reciente), y SHALL NOT persistir, reescribir ni
   reconstruir esa URL: es una firma acuñada para esa respuesta con caducidad acotada, y la
   recuperación SHALL ser volver a listar.
6. WHEN un campo escalar nullable (`string | null`) de los DTOs anteriores se renderiza en línea
   dentro de una fila poblada, THE SYSTEM SHALL mostrar el em-dash `—` (U+2014) como marca
   tipográfica, conforme a la convención de `sdd/specs/frontend-foundation.md`, y SHALL NOT
   concatenarlo con su unidad ni usar `?? ""`.
7. THE SYSTEM SHALL NOT llamar a ninguna ruta de `/api/v1/properties/…` ni de
   `/api/v1/reservations/…`, ni construir URLs de almacenamiento en el cliente: el rol no tiene
   `READ_PROPERTIES` ni `READ_RESERVATIONS`, y las cuatro proyecciones de solo lectura existen
   precisamente para resolver nombres, direcciones y ventanas con `READ_CLEANING_TASKS` solo.
8. IF cualquiera de las cinco peticiones responde `404`, THEN THE SYSTEM SHALL tratarlo como
   «tarea no disponible» sin distinguir si no existe, es de otro tenant o está asignada a otra
   limpiadora —el backend los hace deliberadamente indistinguibles— y SHALL ofrecer la vuelta a
   `/cleaner`.

### R3 — Acciones del ciclo: aceptar, rechazar, iniciar

**Como** limpiadora, **quiero** mover la tarea por su ciclo desde el móvil, **para** que
el manager y la propietaria vean dónde está sin tener que avisar.

Criterios de aceptación:

1. THE SYSTEM SHALL ofrecer exactamente las acciones que el estado actual admite, según la
   tabla de transiciones vigente en `sdd/specs/cleaning.md`:
   - `ASSIGNED` → «Aceptar» (`POST /accept`) y «Rechazar» (`POST /reject`);
   - `ACCEPTED` → «Iniciar» (`POST /start`);
   - `IN_PROGRESS` → cierre de R7;
   - cualquier otro estado → ninguna acción de ciclo, con un mensaje localizado que explique
     por qué (en `PENDING_REVIEW` a la espera de validación, en `COMPLETED`/`REJECTED`/
     `CANCELLED` cerrada).
2. WHEN la limpiadora ejecuta «Aceptar», «Rechazar» o «Iniciar», THE SYSTEM SHALL emitir el
   `POST` correspondiente sin cuerpo —el contrato no publica campos para estas operaciones— y
   SHALL refrescar la tarea y la lista invalidando sus claves en TanStack Query.
3. WHEN `POST reject` responde `200`, THE SYSTEM SHALL devolver a la limpiadora a `/cleaner` y
   SHALL invalidar la lista: el rechazo es terminal y conserva `assigned_cleaner_id` como
   registro, de modo que un GET posterior seguiría resolviendo la fila pero ya sin acciones.
4. IF una mutación responde `409` (estado inválido), THEN THE SYSTEM SHALL mostrar el mensaje
   que sirve el backend sin reintentar automáticamente y SHALL refrescar la tarea para que la
   usuaria vea el estado real.
5. THE SYSTEM SHALL NO ofrecer `cancel` en ninguna pantalla: `POST /cancel` exige
   `MANAGE_CLEANING_TASKS` y la limpiadora no lo tiene.

### R4 — Marcar ítems del checklist

**Como** limpiadora, **quiero** marcar los ítems del checklist según los voy haciendo,
**para** ver mi progreso y desbloquear el cierre al terminar.

Criterios de aceptación:

1. WHERE la tarea está `IN_PROGRESS`, THE SYSTEM SHALL permitir marcar cada ítem individual
   mediante `POST /api/v1/cleaning-tasks/{id}/checklist/{item_id}/complete`, sin cuerpo, y SHALL
   invalidar la clave de `/checklist` al recibir `200` para que el ítem se pinte como completado
   con su `completed_at` y su `completed_by`.
2. THE SYSTEM SHALL confiar la idempotencia al backend —`specs/cleaning.md` §Checklist fija la
   escritura como `INSERT ... ON CONFLICT DO UPDATE`—, de modo que un doble clic no duplica
   completions: el segundo `POST` resuelve al mismo estado sin error y el cliente no muestra
   error.
3. IF la API responde `404` (el `item_id` ya no pertenece a la plantilla de la tarea —caso de
   una plantilla editada mientras se ejecuta—), THEN THE SYSTEM SHALL refrescar el checklist
   para que el ítem desaparecido deje de aparecer, sin reintento.
4. IF la API responde `409` (la tarea no está `IN_PROGRESS`), THEN THE SYSTEM SHALL mostrar el
   mensaje del backend y SHALL refrescar la tarea para que la UI pinte el estado real; no SHALL
   reintentar automáticamente.

### R5 — Subir fotos por categoría

**Como** limpiadora, **quiero** subir una foto por cada categoría que la plantilla pide,
**para** desbloquear el cierre y dejar constancia del trabajo.

Criterios de aceptación:

1. WHERE la tarea está `IN_PROGRESS`, THE SYSTEM SHALL ofrecer un botón por cada entrada de
   `GET /api/v1/cleaning-tasks/{id}/photo-requirements` que tenga `uploaded: false`, etiquetado
   con su `label` y marcado como obligatorio si `required: true`. Una entrada con
   `uploaded: true` SHALL mostrar el estado «cubierta» y SHALL NO ofrecer el botón de subida.
2. WHEN la limpiadora selecciona una foto, THE SYSTEM SHALL emitir
   `POST /api/v1/cleaning-tasks/{id}/photos` con `multipart/form-data` y dos campos —
   `photo_type` (el de la entrada seleccionada) y `file` (los bytes)— por un camino que
   **no** imponga `Content-Type: application/json` ni serialice el cuerpo con `JSON.stringify`.
   El `createApiClient` actual hace ambas cosas incondicionalmente, así que esta es la primera
   petición `multipart` del frontal `cleaner` y necesita una vía explícita que conserve la
   cabecera de sesión, el reintento único ante `401` y el mapeo de errores del cliente
   compartido —el mismo patrón ya tiene `tech-app` R5.4 documentado—.
3. THE SYSTEM SHALL emitir esa subida con el `photo_type` **derivado de la entrada que la
   usuaria tocó**, no de un campo de texto libre: el contrato acepta solo los tipos declarados
   por la plantilla, y un `photo_type` no declarado responde `404` por construcción.
4. WHEN la subida responde `201`, THE SYSTEM SHALL invalidar las claves de `/photo-requirements`
   y `/photos` de esa tarea para que la pantalla pinte la nueva cobertura y la nueva foto en la
   galería sin un `router.refresh()` manual.
5. IF la subida responde `404` (tipo ya no declarado), `409` (la tarea no está `IN_PROGRESS`),
   `413` (tamaño), `422` (los bytes no son JPEG, PNG o WebP) o `502` (fallo del almacenamiento),
   THEN THE SYSTEM SHALL mostrar un mensaje distinto para cada uno y SHALL NOT reintentar
   automáticamente. El mensaje del `422` SHALL nombrar los formatos admitidos porque la causa
   frecuente en un móvil es un HEIC de iPhone y la acción que lo resuelve es cambiar el formato,
   no reintentar.

### R6 — Reportar una incidencia desde la tarea

**Como** limpiadora, **quiero** abrir una incidencia de mantenimiento desde la tarea que estoy
haciendo, **para** avisar al manager de algo que se rompió o falta, sin tener que llamarle.

Criterios de aceptación:

1. WHERE la tarea está en `ASSIGNED`, `ACCEPTED` o `IN_PROGRESS`
   (`INCIDENT_REPORTABLE_STATUSES`), THE SYSTEM SHALL ofrecer un botón «Reportar incidencia»
   que abre un formulario con exactamente dos campos: `title` (obligatorio) y `description`
   (obligatorio). SHALL NOT ofrecer este botón en estados terminales (`COMPLETED`, `REJECTED`,
   `CANCELLED`) ni en `PENDING_REVIEW`.
2. THE SYSTEM SHALL aplicar localmente las cotas que el backend revalidará: `title` entre 1 y
   `MAX_INCIDENT_TITLE` (300) caracteres, sin caracteres de control (espacio al borde recortado);
   `description` entre 1 y `MAX_INCIDENT_DESCRIPTION` (5000) caracteres, con tabulador y saltos
   de línea admitidos. IF el formulario no cumple, THEN THE SYSTEM SHALL no emitir la petición.
3. WHEN la limpiadora envía el formulario válido, THE SYSTEM SHALL emitir
   `POST /api/v1/cleaning-tasks/{id}/incidents` con cuerpo `{title, description}` —`extra="forbid"`
   cierra cualquier otro campo—, y SHALL mostrar el acuse de tres campos (`id`, `status`,
   `created_at`) sin volver a pintar el `title` ni la `description`.
4. THE SYSTEM SHALL NO leer, listar, clasificar ni resolver incidencias: las quince rutas de
   `/api/v1/incidents` están cerradas al rol. El botón de R6.1 es el **único** camino que
   produce una fila de incidencia desde esta pantalla, y el cierre del modal tras el `201` cierra
   también cualquier expectativa de más información.
5. IF la API responde `409` (la tarea pasó a estado terminal entre el GET y el POST), THEN THE
   SYSTEM SHALL mostrar el mensaje del backend, refrescar la tarea para que la UI pinte el
   estado real, y SHALL NOT reintentar automáticamente.

### R7 — Cerrar la limpieza con la regla de validación de tres cláusulas

**Como** limpiadora, **quiero** cerrar la tarea cuando he terminado, **para** que la vivienda
avance al siguiente estado y el manager sepa que tiene algo que validar.

Criterios de aceptación:

1. WHERE la tarea está `IN_PROGRESS`, THE SYSTEM SHALL ofrecer un botón «Cerrar limpieza» que
   ejecuta `POST /api/v1/cleaning-tasks/{id}/complete` sin cuerpo.
2. WHEN el cierre responde `200`, THE SYSTEM SHALL refrescar la tarea y la lista, presentar la
   tarea como cerrada con su `completed_at` y `validation_status`, y volver a `/cleaner` tras
   una confirmación local de la limpiadora —el equivalente del `toast` «limpieza cerrada» que ya
   tiene `tech-app` para su cierre, pero como acción reversible de salida, no como notificación
   que se desvanece—.
3. IF el cierre responde `409` con cualquiera de las tres cláusulas de PRD §11, THE SYSTEM
   SHALL mostrar el mensaje del backend distinguiendo las tres causas por el código que el
   backend publica, sin reinventar el vocabulario:
   - **faltan ítems `required`** → la pantalla debe señalar qué ítems del checklist siguen
     `pending`, resaltando los afectados;
   - **faltan fotos `required`** → la pantalla debe señalar qué entradas de
     `/photo-requirements` siguen con `uploaded: false`;
   - **hay una incidencia `CRITICAL` sin resolver en la propiedad** → la pantalla NO nombra
     identificador, título ni descripción de la incidencia que bloquea: `CLEANER` no tiene
     `READ_INCIDENTS` y un cuerpo que los incluyera sería la lectura que se le niega
     (`sdd/specs/cleaner-incident-report.md` §La incidencia que le bloquea su propio cierre).
4. THE SYSTEM SHALL NOT derivar de `/photo-requirements` un veredicto propio sobre si la tarea
   puede cerrarse: `uploaded` es un hecho, y la regla de validación —las tres cláusulas— vive
   **dentro de `CleaningTask.complete()` y en ningún otro sitio** (`sdd/specs/cleaning.md`
   §Cierre y validación). Lo que esta pantalla muestra es qué hay y qué falta, no si la suma
   aprueba.

### R8 — Postura mobile-first, estados e i18n

**Como** limpiadora que trabaja de pie y con una mano, **quiero** una pantalla legible en el
móvil y en mi idioma, **para** poder operarla en el rellano de un piso.

Criterios de aceptación:

1. THE SYSTEM SHALL pasar toda cadena visible por `frontend/locales/es/` y `frontend/locales/en/`
   bajo un nuevo namespace `cleaner`, registrado en `frontend/lib/i18n/resources.ts` (el
   `import`, el array `NAMESPACES` y ambas tablas de recursos), sin ninguna literal en los
   componentes. La excepción que `sdd/specs/frontend-foundation.md` ya consiente para el em-dash
   `—` aplica igual aquí.
2. THE SYSTEM SHALL construir los estados de carga, vacío y error sobre los primitivos
   compartidos (`StatePanel`, `LoadingState`, `EmptyState`, `ErrorState`), con `aria-busy` en la
   carga y `role="alert"` en el error, y SHALL NOT renderizar el detalle crudo de ningún error.
3. THE SYSTEM SHALL disponer ambas pantallas en una sola columna con objetivos táctiles
   cómodos y sin desplazamiento horizontal a 360 px de ancho en lo que esta pantalla gobierna.
4. THE SYSTEM SHALL reutilizar la paleta existente —`features/cleaning/lib/task-status.ts`
   sobre `lib/ui/status-tone.ts`— para el estado de la tarea, y SHALL NOT introducir una
   segunda tabla de colores. La severidad no se pinta aquí: la pantalla no la muestra.
5. THE SYSTEM SHALL confiar la autorización al backend: el `AuthGuard allow={["CLEANER"]}` que
   ya monta el layout es un escudo de UX, y ninguna decisión de negocio SHALL derivarse del rol
   en el cliente.

## Out of scope

- **Cualquier cambio de backend**: esquema, migraciones, permisos del rol, o el contrato
  publicado. Si algo de PRD §11 resultara no estar servido, se para y se abre una entrada `[BE]`,
  como ya se hizo el 2026-08-19.
- **El aterrizaje por rol tras el login**: ya está implementado en `frontend-auth-session.md`
  R1 (`roleHome(user.role)`) y consolidado en `frontend-auth-role-routing` (archivado
  2026-08-27). Esta entrada NO reabre ese trabajo y NO toca `login-form.tsx`.
- **Las pantallas del workspace** (`/cleaning`): la vista del manager vive en
  `sdd/specs/cleaning-manager-view.md` y no cambia su presentación con esta entrada. El botón
  de cancelar (`POST /cancel`) no se ofrece en esta pantalla porque exige
  `MANAGE_CLEANING_TASKS`.
- **`/tech` y `tech-app`**: la app del técnico es su propia entrada del roadmap y no comparte
  pantallas con ésta. Lo único que las relaciona es el criterio con el que ambas se partieron
  el 2026-08-18.
- **`access_records.notes` y la decisión de la regla 11 que
  `sdd/roadmap/cleaner-app.md` tenía aparcada.** La verificación del 2026-08-23 midió que el
  disparador original nunca se cumple —PRD §11 y §6 no conceden accesos al rol y `policy.py`
  le niega `READ_ACCESS_RECORDS` por escrito—, así que esa decisión se queda **sin change
  asignado** (es decir, no se decide aquí). Lo único que entra en el scope de archive son las
  dos frases de spec viva que la nombran como propia de esta entrada —se listan en §Trabajo
  pendiente para `/sdd:archive`—. Su mitad de cifrado en reposo sigue viva y con dueño, en
  `plaintext-sink-encryption-at-rest`.
- **Notificaciones a la limpiadora**: `CLEANER` tiene `READ_OWN_NOTIFICATIONS` y el
  `NotificationBell` del `Topbar` ya le entrega `CLEANING_TASK_ASSIGNED` y `CLEANING_FAILED`
  (entrega `access-notifications`, archivado 2026-08-15). Una bandeja dedicada para
  `cleaner-app` queda como entrada propia si se considera útil.
- **El hilo de personal con el manager** (`/cleaner/tasks/[id]` ↔ manager): vive en
  `sdd/roadmap.md:187` como `staff-messaging-web` y va detrás de `cleaner-app` y `tech-app`.
- **E2E con Playwright**: la suite E2E completa es de `hardening-release` (PRD §26.27,
  DoD §28). Esta entrada deja la verificación visual en manos del smoke que ya miden los
  changes del campo (medido en `tech-app`, 2026-08-29: la app hidrata en `next dev` con
  `PORT_OFFSET` y el ciclo entero es operable desde un navegador a 360×780).

## Affected specs

- `sdd/specs/cleaner-app.md` — *(no existe aún — se creará al archivar)*. La capacidad
  completa: las dos superficies, el ciclo de la limpiadora en la web, el checklist por ítem,
  la subida de fotos por categoría y el reporte de incidencia, con la regla de validación de
  tres cláusulas del cierre aplicada tal como el backend la resuelve.
- `sdd/specs/frontend-foundation.md` — el inventario de superficies deja de contar `/cleaner` y
  `/cleaner/tasks/[id]` como placeholders (de nueve a siete) y los suma a las funcionales (de
  diecisiete a diecinueve), en las líneas 25 y 99. La frase que cuenta `/tech/incidents/[id]`
  en línea 25 es hermana y se queda como modelo.
- `sdd/specs/cleaning.md`, `sdd/specs/cleaner-task-context.md`,
  `sdd/specs/cleaner-incident-report.md`, `sdd/specs/cleaner-photo-requirements.md` —
  **no se modifican**. Son los contratos que esta pantalla consume; se citan como fuente, no se
  tocan. `cleaner-task-context.md` y `access-notifications.md` SI se modifican, pero sólo para
  corregir las dos frases que el roadmap del 2026-08-23 dejó como «archive-time cleanup» —
  se enumeran abajo.

### Trabajo pendiente para `/sdd:archive`

Levantado del `sdd/roadmap/cleaner-app.md` (sección 4, 2026-08-23). Ninguno es editable desde
esta fase: los cuatro viven en ficheros que sólo `/sdd:archive` escribe —`sdd/specs/`, por la
regla 1.

1. `sdd/specs/cleaner-task-context.md:159, 167-168` — la frase *«y `access_records.notes`, que
   sigue siendo de `cleaner-app`»* deja de ser cierta al verificarse el 2026-08-23 que la app
   de la limpiadora no amplía el público de `notes` (PRD §11 y §6 no dan accesos a `CLEANER`
   y `policy.py` le niega `READ_ACCESS_RECORDS` por escrito). El cambio es borrar la frase y
   dejarla en el nuevo estado: la decisión está aparcada sin disparador, no asignada a este
   change.
2. `sdd/specs/access-notifications.md:131-134` — *«Anotado en la entrada de roadmap de
   `cleaner-app`, que es quien ampliará la superficie de `notes`»* pasa a *«Anotado en
   `sdd/roadmap/cleaner-app.md` §4: el disparador original no se cumple, y la decisión queda
   sin change asignado. Su mitad de cifrado en reposo sigue en
   `plaintext-sink-encryption-at-rest`»*.

   Ambos son de archive porque tocan `sdd/specs/`, que sólo esa fase escribe. La regla 1 de
   SDD los tiene ahí: la prosa de spec es una sola verdad, y este proposal NO la corrige
   porque la capacidad que describe no cambia.

## Coordinación

`shell-topbar-overflow-360` está en vuelo en otro worktree (medido el 2026-08-29 al verificar
`tech-app`: el `Topbar` compartido produce `scrollWidth` 433 sobre un viewport de 360, en
todas las superficies autenticadas). La cabecera la montan `WorkspaceShell`, `CleanerShell`
y `TechnicianShell` por construcción (`features/shell/components/topbar.tsx`), así que esta
entrada **hereda** ese residual y R8.3 lo declara satisfecho para lo que estas dos pantallas
gobiernan, no para el shell. Merece una comprobación de conflictos al abrir el PR contra ese
cambio, no una dependencia declarada.

`staff-messaging-web` (`sdd/roadmap.md:187`) declara `needs: staff-messaging, cleaner-app,
tech-app`, así que este PR queda como uno de sus dos prerequisites al lado de `tech-app`. No
hay superposición de ficheros, pero la barra de chat de `/cleaner/tasks/[id]` que esa entrada
añadirá convive con el botón «Reportar incidencia» de R6.
