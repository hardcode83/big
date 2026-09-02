# App de la limpiadora (`/cleaner`)

## Purpose

Las dos superficies web sobre las que un `CLEANER` **opera** el ciclo de una tarea de limpieza
(PRD §11, §24): `/cleaner` lista sus tareas asignadas con la vivienda de cada fila, y
`/cleaner/tasks/[id]` reúne el contexto de la propiedad (dirección y ventana horaria), el
checklist por ítem, los requisitos de foto por categoría, la galería, el reporte de incidencia y
los botones del ciclo, con el cierre de tres cláusulas mostrado tal como el backend lo resuelve.
Es una capa de presentación pura sobre los contratos que ya describen
[`cleaning.md`](cleaning.md), [`cleaner-task-context.md`](cleaner-task-context.md),
[`cleaner-photo-requirements.md`](cleaner-photo-requirements.md) y
[`cleaner-incident-report.md`](cleaner-incident-report.md) — **no añade ni relaja ninguna regla
de negocio ni de acceso**: el backend sigue siendo la única autoridad sobre las transiciones, el
acotamiento por limpiadora y la validación de cierre. Es mobile-first porque su usuaria trabaja
de pie, dentro de la propiedad y con una mano.

El rol alcanza exactamente lo que la pantalla usa. `CLEANER` tiene
`READ_CLEANING_TASKS`, `EXECUTE_CLEANING_TASKS`, `CREATE_INCIDENTS` y
`READ_OWN_NOTIFICATIONS` (`backend/app/auth/domain/policy.py`) — **no** `READ_PROPERTIES`,
`READ_RESERVATIONS`, `READ_INCIDENTS` ni `READ_ACCESS_RECORDS`. La pantalla no oculta ningún
botón por permiso propio: `lib/auth/permissions.ts` mantiene `CLEANER: []`, y el `AuthGuard
allow={["CLEANER"]}` del layout es el único escudo de UX.

## Requirements

### R1 — Mis tareas en `/cleaner`

- WHEN un usuario autenticado con rol `CLEANER` abre `/cleaner`, THE SYSTEM SHALL renderizar la
  lista servida por `GET /api/v1/cleaning-tasks` en lugar del `RoutePlaceholder`, y SHALL NOT
  enviar ningún parámetro que identifique a la limpiadora: el acotamiento por fila lo deriva el
  backend del token (`CleaningActor.restrict_to_cleaner_id`) y no existe parámetro de consulta
  para él.
- THE SYSTEM SHALL ofrecer siete chips de estado de selección única —`ASSIGNED`, `ACCEPTED`,
  `IN_PROGRESS`, `PENDING_REVIEW`, `COMPLETED`, `REJECTED`, `CANCELLED`—; un segundo clic sobre
  el chip activo SHALL volver a la lista sin filtro. `CREATED` y `FAILED` quedan fuera del chip
  —el primero porque `restrict_to_cleaner_id` lo vacía por construcción para `CLEANER`, el
  segundo porque solo lo escribe el manager— pero SHALL seguir pintándose en una fila si llega
  con ese estado.
- WHERE no hay ningún filtro seleccionado, THE SYSTEM SHALL pedir la página sin `status` y
  presentarla en el orden que sirve el backend (`created_at` descendente) SIN reordenar en
  cliente.
- WHEN la lista se renderiza, THE SYSTEM SHALL mostrar por fila el estado y las fechas de
  `CleaningTaskListItem`, más el `property_name` y el `property_internal_code` obtenidos de
  `GET /api/v1/cleaning-tasks/{id}/context` para esa fila, bajo la **misma clave de query
  tenant-scoped** que consume el detalle, de modo que abrir una fila no vuelva a pedir su
  contexto.
- IF el contexto de una fila falla, THEN THE SYSTEM SHALL degradar esa fila a `—` en los campos
  de propiedad sin tumbar el resto de la lista: el fallo del contexto no es el fallo del
  listado.
- THE SYSTEM SHALL ofrecer paginación prev/next con «página X de Y», sin acumulador de páginas.
- IF la respuesta está vacía, THEN THE SYSTEM SHALL renderizar el `EmptyState` compartido; IF la
  petición falla, THEN THE SYSTEM SHALL renderizar el `ErrorState` compartido sin exponer el
  detalle del error y sin reintento en `4xx`.

### R2 — Detalle: a qué propiedad voy, qué falta y qué subí

- WHEN una limpiadora abre `/cleaner/tasks/[id]`, THE SYSTEM SHALL sustituir el
  `RoutePlaceholder` y montar en paralelo `GET /api/v1/cleaning-tasks/{id}`,
  `GET .../context`, `GET .../checklist`, `GET .../photo-requirements` y
  `GET .../photos`.
- THE SYSTEM SHALL mostrar de `CleaningTaskContext`: `property_name`, `property_internal_code`,
  la dirección completa (`address_line1`, `address_line2`, `city`, `province`, `postal_code`,
  `country`), el `timezone` y los dos instantes (`checkout_at`, `next_checkin_deadline`)
  formateados con `formatDateTime(iso, locale)` en ese timezone.
- WHEN un campo nulo de esos DTOs se renderiza en línea dentro de una fila poblada, THE SYSTEM
  SHALL mostrar el em-dash `—` (U+2014) como marca tipográfica, conforme a la convención de
  [`frontend-foundation.md`](frontend-foundation.md), y SHALL NOT concatenarlo con su unidad ni
  usar `?? ""`.
- THE SYSTEM SHALL NOT llamar a ninguna ruta de `/api/v1/properties/…`, `/api/v1/reservations/…`
  ni construir URLs de almacenamiento en el cliente: el rol no tiene los permisos de lectura
  correspondientes y las proyecciones de contexto existen precisamente para eso.
- IF cualquiera de las cinco peticiones responde `404`, THEN THE SYSTEM SHALL tratarlo como
  «tarea no disponible» sin distinguir las tres causas que el backend colapsa, y ofrecer la
  vuelta a `/cleaner`.

### R3 — El ciclo de la limpiadora: aceptar, rechazar, iniciar

- THE SYSTEM SHALL ofrecer exactamente las acciones que el estado admite, según la tabla
  `CLEANER_ACTIONS` de `frontend/features/cleaner/lib/cleaner-actions.ts` — un `Record`
  exhaustivo sobre `CleaningTaskStatus` (el enum del contrato generado), acotado a las
  operaciones que alcanza `EXECUTE_CLEANING_TASKS`: `ASSIGNED` → «Aceptar» (`POST accept`) y
  «Rechazar» (`POST reject`); `ACCEPTED` → «Iniciar» (`POST start`); `IN_PROGRESS` → «Cerrar
  limpieza» (R7) y «Reportar incidencia» (R6), con el checklist (R4) y la subida de fotos (R5)
  como controles de la misma pantalla y no del header.
- THE SYSTEM SHALL consultar la tabla con `Object.hasOwn`, devolviendo «ninguna acción» ante un
  estado que el frontend compilado no conozca en lugar de fallar en el render.
- WHERE el estado no ofrece ninguna acción de ciclo, THE SYSTEM SHALL explicar el motivo:
  `PENDING_REVIEW` es «a la espera de validación», `COMPLETED` es «cerrada», `REJECTED` es
  «rechazada», `CANCELLED` es «cancelada», y `CREATED`/`FAILED` son «no accionable».
- WHEN `POST reject` responde `200`, THE SYSTEM SHALL invocar `removeQueries` sobre el detalle y
  el contexto de esa tarea (una tarea rechazada responde `404` a quien rechazó) y navegar a
  `/cleaner`.
- WHEN `accept` o `start` responden `200`, THE SYSTEM SHALL invalidar el detalle y el prefijo de
  la lista, sin recomponer el estado en el cliente.
- IF una mutación del ciclo responde `409`, THEN THE SYSTEM SHALL mostrar un mensaje localizado
  vía `mapCleanerError`, refrescar la tarea y SHALL NOT reintentar automáticamente.

### R4 — Checklist por ítem

- WHERE el estado es `IN_PROGRESS`, THE SYSTEM SHALL renderizar cada ítem del checklist en el
  orden que sirve el backend, con su `label`, su marca `required` y un control para marcarlo
  completado vía `POST .../checklist/{item_id}/complete`, sin cuerpo.
- WHEN la mutación responde `200`, THE SYSTEM SHALL invalidar la clave del checklist.
- IF la mutación responde `404`, THEN THE SYSTEM SHALL refrescar el checklist en silencio; IF
  responde `409`, THEN THE SYSTEM SHALL mostrar un mensaje localizado vía `mapCleanerError` y
  refrescar la tarea, sin reintento automático.
- IN cualquier otro estado, THE SYSTEM SHALL seguir mostrando los ítems, pero SHALL NOT
  renderizar el control de completar.

### R5 — Requisitos de foto y subida por categoría

- THE SYSTEM SHALL renderizar cada categoría de `PhotoRequirementsResponse` en el orden
  declarado, con su `label`, su marca `required` y un indicador «cubierta» / «pendiente» según
  `uploaded`.
- WHERE el estado es `IN_PROGRESS`, THE SYSTEM SHALL ofrecer un botón de subida por cada entrada
  con `uploaded: false`, que abre un selector nativo
  (`accept="image/jpeg,image/png,image/webp" capture="environment"`, una ayuda y no una
  validación) y emite `POST .../photos` en `multipart/form-data` con `photo_type` —tomado de la
  entrada tocada, nunca de un campo libre— y `file`. En cualquier otro estado la subida SHALL NOT
  ofrecerse.
- THE SYSTEM SHALL emitir esa subida por el campo `formData` del cliente compartido
  (`lib/api/client.ts`), sin fijar `Content-Type` propio y sin `JSON.stringify`, conservando la
  cabecera de sesión y el reintento único ante `401` que el transporte ya provee.
- WHEN la subida responde `201`, THE SYSTEM SHALL invalidar los requisitos de foto y la galería
  de esa tarea.
- IF la subida responde `409` (razón de `conflictReason`), `413` (tamaño), `422` (formato) o
  `502` (almacenamiento), THEN THE SYSTEM SHALL mostrar un mensaje distinto para cada uno, con
  el `422` nombrando JPEG/PNG/WebP, y SHALL NOT reintentar automáticamente.
- THE SYSTEM SHALL NOT ofrecer borrar una foto ni presentarla como requisito del cierre: la API
  no expone ningún borrado y el veredicto de cierre vive en el backend.

### R6 — Reporte de incidencia desde la tarea

- WHERE el estado de la tarea ∈ `{ASSIGNED, ACCEPTED, IN_PROGRESS}`, THE SYSTEM SHALL ofrecer un
  panel inline (no modal, no navegación) con dos campos nativos — `title`
  (`<input maxLength={300}>`) y `description` (`<textarea maxLength={5000}>`) — y SHALL NOT
  mostrar el disparador en `PENDING_REVIEW` ni en ningún estado terminal.
- THE SYSTEM SHALL validar localmente antes de emitir: `title` no vacío, sin caracteres de
  control y con los límites de longitud del backend; `description` dentro de sus límites,
  admitiendo tabuladores y saltos de línea.
- WHEN el envío responde `201`, THE SYSTEM SHALL cerrar el panel y mostrar solo el acuse de tres
  campos (`id`, `status`, `created_at`) — SHALL NOT volver a renderizar el `title` ni la
  `description` enviados.
- IF el envío responde `409` (la tarea pasó a un estado terminal entre el `GET` y el `POST`),
  THEN THE SYSTEM SHALL mostrar un mensaje localizado vía `mapCleanerError`, refrescar la tarea
  y SHALL NOT reintentar automáticamente.
- THE SYSTEM SHALL NOT listar, leer, clasificar ni resolver incidencias desde esta pantalla: el
  botón de reporte es el único consumidor de `reportIncident` en esta feature.

### R7 — Cerrar la limpieza y el `409` de tres cláusulas

- WHERE el estado es `IN_PROGRESS`, THE SYSTEM SHALL ofrecer «Cerrar limpieza»
  (`POST .../complete`, sin cuerpo).
- WHEN la respuesta llega con `200`, THE SYSTEM SHALL renderizar un panel de cierre reversible
  con «Volver a mis tareas» (`router.replace("/cleaner")`), sin auto-descarte.
- IF la respuesta llega con `409`, THEN THE SYSTEM SHALL releer el estado refrescado
  **después** de la invalidación que la mutación ya dispara y traducirlo a una de tres razones,
  en el orden en que el backend las evalúa: `missing-required-items` (resalta los ítems
  `required` con `pending: true`), `missing-required-photos` (resalta las entradas
  `required` con `uploaded: false`), o `critical-incident` (mensaje que SHALL NOT nombrar
  identificador, título ni descripción de la incidencia — `CLEANER` no tiene `READ_INCIDENTS`).
- THE SYSTEM SHALL NOT leer el `message` técnico del sobre de error para decidir la razón: los
  tres `409` de cierre comparten `code: "CONFLICT"` y se diferencian solo por ese texto en
  inglés, que la pantalla no renderiza.

### R8 — Postura mobile-first, estados e i18n

- THE SYSTEM SHALL pasar toda cadena visible por `frontend/locales/es/cleaner.json` y
  `frontend/locales/en/cleaner.json`, registrados en `frontend/lib/i18n/resources.ts` y
  cubiertos por `lib/i18n/catalog-parity.test.ts`. El em-dash de R2 es la excepción declarada:
  es un signo tipográfico idéntico en los dos idiomas, va inline en el JSX y SHALL NOT tener
  clave de catálogo. Los rótulos de estado (`status.*`) se toman del namespace `cleaning`
  existente y SHALL NOT duplicarse en una segunda tabla.
- THE SYSTEM SHALL construir los estados de carga, vacío y error sobre los primitivos
  compartidos (`LoadingState` con `role="status"`/`aria-busy`, `EmptyState`, `ErrorState` con
  `role="alert"`), y SHALL NOT renderizar el detalle crudo de ningún error.
- THE SYSTEM SHALL disponer ambas pantallas en una sola columna (`mx-auto w-full max-w-md`) sin
  desplazamiento horizontal a 360 px, con la lista como tarjetas pulsables (no tabla) y la barra
  de acciones del detalle como último elemento del flujo vertical, visible tras el scroll sin
  `position: fixed`.
- THE SYSTEM SHALL pintar el badge de estado con `TONE_BADGE_CLASS[statusColorGroup(status)]` de
  `features/cleaning/lib/task-status.ts` — un solo mapa de clases en todo el árbol — y SHALL NOT
  introducir una segunda tabla de colores.
- THE SYSTEM SHALL formatear fechas con `formatDateTime(iso, locale)` propio de la feature, que
  recibe el `locale` de i18next como **parámetro** —nunca `undefined`, que resolvería al del
  navegador.
- THE SYSTEM SHALL confiar la autorización al backend: el `AuthGuard allow={["CLEANER"]}` que
  monta el layout es un escudo de UX, y ninguna decisión de negocio SHALL derivarse del rol en
  el cliente.

## Known limitations

- **N+1 de contextos en la lista.** Cada fila pide su propio
  `GET /api/v1/cleaning-tasks/{id}/context`, hasta `per_page` peticiones extra por página.
  Mitigado —TanStack deduplica por clave, el detalle reaprovecha lo que la lista trajo y un
  fallo por fila degrada a `—` sin tumbar la pantalla— pero no resuelto: la salida es que
  `GET /api/v1/cleaning-tasks` proyecte `property_name` y `property_internal_code` en cada fila,
  entrada de roadmap `cleaner-list-property-projection`. A diferencia de `tech-app`, el contexto
  de limpieza no lleva `access_notes`, así que esta caché no guarda instrucciones de acceso.
- **Firma caducada en una pantalla abierta mucho rato.** El `onError` de cada `<img>` invalida
  la clave de fotos, acotado a un reintento por foto (`useRef<Set<string>>` de ids ya
  reintentados), para que una foto realmente ilegible no entre en bucle de refetch.
- **Sin filtro multi-estado.** `GET /api/v1/cleaning-tasks` admite un solo valor de `status`, y
  por eso la pantalla ofrece chips de selección única.
- **`shared-datetime-formatter` sigue sin extraerse.** Sería la sexta copia del mismo
  formateador en el árbol; la extracción se aplaza como candidato de roadmap por alcance, no por
  técnica.

## Key files

- `frontend/app/(field)/cleaner/page.tsx` y `frontend/app/(field)/cleaner/tasks/[id]/page.tsx` —
  las dos rutas, ya no `RoutePlaceholder`, bajo el `CleanerShell` y el
  `AuthGuard allow={["CLEANER"]}` que monta el layout del grupo `(field)`.
- `frontend/features/cleaner/components/list/` — `cleaner-task-list-view.tsx` (orquestación +
  estados), `cleaner-task-list-row.tsx` (la fila con su vivienda o `—`),
  `cleaner-task-status-chips.tsx` (los siete chips), `cleaner-task-pagination.tsx`
  (prev/next).
- `frontend/features/cleaner/components/detail/` — `cleaner-task-detail-view.tsx`
  (composición), `cleaner-task-context-block.tsx`, `cleaner-task-checklist.tsx` +
  `cleaner-task-checklist-item.tsx` (R4), `cleaner-task-photo-requirements.tsx` +
  `cleaner-task-photo-upload-button.tsx` (R5), `cleaner-task-photo-gallery.tsx`,
  `cleaner-incident-report-panel.tsx` (R6), `cleaner-task-action-bar.tsx` (R3, R7),
  `cleaner-completion-panel.tsx` (R7).
- `frontend/features/cleaner/data/cleaner-source.ts` — la interfaz `CleanerDataSource` (once
  métodos: seis lecturas, seis mutaciones más el reporte de incidencia).
- `frontend/features/cleaner/data/http-cleaner-source.ts` y `data/dto.ts` — la implementación
  sobre `ApiClient` y los DTO, alias de `components["schemas"]`.
- `frontend/features/cleaner/data/index.ts` — `getCleanerDataSource()` sobre
  `createAuthenticatedClients`, el único punto de composición.
- `frontend/features/cleaner/hooks/query-keys.ts` — `cleanerKeys`, las siete claves bajo
  `tenantScopedKey`, con `context()` compartida entre lista y detalle.
- `frontend/features/cleaner/hooks/use-cleaner-tasks.ts` — las lecturas, con
  `useCleanerTaskContexts` como `useQueries` que degrada por fila.
- `frontend/features/cleaner/hooks/use-cleaner-cycle.ts` — las siete mutaciones, cada una
  `useMutation` con `retry: false` e invalidación en `onSettled`.
- `frontend/features/cleaner/lib/cleaner-actions.ts` — `CLEANER_ACTIONS`, `NO_ACTION_REASON` y
  las tablas `Record<CleaningTaskStatus, …>` que deciden qué ofrece cada estado.
- `frontend/features/cleaner/lib/conflict-reason.ts` — las tres razones del `409` de cierre
  (R7).
- `frontend/features/cleaner/lib/error-mapping.ts` — `mapCleanerError`, la tabla de ramas por
  código y `kind`.
- `frontend/features/cleaner/lib/format.ts` — `formatDateTime(iso, locale)`.
- `frontend/features/cleaner/index.ts` — exporta `CleanerTaskListView` y
  `CleanerTaskDetailView`.
- `frontend/locales/{es,en}/cleaner.json` — el catálogo, registrado en
  `frontend/lib/i18n/resources.ts`.
- `frontend/lib/api/client.ts` — el campo `formData` de `RequestOptions`, ya disponible desde
  `tech-app` (archivado 2026-08-30); esta entrada lo consume sin tocar el transporte.
