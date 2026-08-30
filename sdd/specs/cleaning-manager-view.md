# Vista de limpiezas del manager (`/cleaning`)

## Purpose

La superficie web desde la que un `PROPERTY_MANAGER` **opera** el backend de limpieza (PRD §6, §24):
`/cleaning` lista las tareas de limpieza del tenant con su estado, su vivienda y su limpiadora
identificadas por nombre, las acota por propiedad y por estado, y permite asignar o reasignar una
tarea a una limpiadora activa. Es una capa de presentación pura sobre la API que ya describe
`cleaning.md` — **no añade ni relaja ninguna regla de negocio ni de acceso**: el backend sigue siendo
la única autoridad. Un `TENANT_OWNER` ve la misma lista sin el control de asignación.

## Requirements

### La lista real de tareas

- WHEN un usuario autenticado abre `/cleaning`, THE SYSTEM SHALL renderizar la lista de tareas que
  devuelve `GET /api/v1/cleaning-tasks`, en el orden y la página que decide el backend, y NO el
  `RoutePlaceholder` — la ruta dejó de ser un módulo en preparación.
- THE SYSTEM SHALL montar la vista bajo el `AuthGuard` del grupo `(workspace)`, cuya única
  comprobación es que haya sesión: redirige a `/login?returnTo=…` a quien no la tenga.
- WHILE la consulta está en vuelo, THE SYSTEM SHALL mostrar el `LoadingState` común
  (`role="status"`, `aria-busy`, `aria-live="polite"`, esqueletos `aria-hidden`), sin estado de carga
  propio.
- IF la consulta de tareas falla, THEN THE SYSTEM SHALL mostrar `ErrorState` con `role="alert"` y una
  acción de reintento que relanza la consulta.
- IF ninguna tarea coincide con los filtros activos, THEN THE SYSTEM SHALL mostrar `EmptyState`,
  distinguible del estado de error y del de carga.
- THE SYSTEM SHALL no reintentar ninguna respuesta 4xx y reintentar hasta dos veces el resto, por la
  política de reintentos compartida del frontend.
- WHERE la lista muestra el estado de una tarea, THE SYSTEM SHALL pintar una etiqueta traducida con
  color consistente para cada uno de los nueve valores de `CleaningTaskStatus` — `CREATED` y
  `ASSIGNED` y `PENDING_REVIEW` en ámbar, `ACCEPTED` e `IN_PROGRESS` en azul, `COMPLETED` en verde,
  `REJECTED` y `FAILED` en rojo, `CANCELLED` en gris — y NUNCA el identificador crudo del enum.
- THE SYSTEM SHALL derivar el tipo de estado del contrato generado
  (`components["schemas"]["CleaningTaskStatus"]`) en vez de recopiar la lista, de modo que un valor
  nuevo en el backend rompa el typecheck; y SHALL degradar a gris un estado desconocido en runtime,
  para que una asimetría de despliegue no tumbe la vista.
- THE SYSTEM SHALL renderizar la lista como tarjetas `ul`/`li` —cada `li` etiquetada por el
  encabezado de su tarea— y NO como tabla, porque las seis columnas de una tarea no caben sin scroll
  horizontal en un móvil.

### Identidad legible: vivienda y limpiadora por nombre

- WHEN la lista muestra una tarea, THE SYSTEM SHALL identificar su vivienda por el `internal_code` y
  el `name` que devuelve `GET /api/v1/properties`, y NO por el `property_id` crudo de la tarea.
- WHEN una tarea tiene `assigned_cleaner_id`, THE SYSTEM SHALL mostrar el nombre de esa usuaria
  resuelto contra `GET /api/v1/users?role=CLEANER`, y NO el UUID. Ningún UUID es visible en ninguna
  rama del renderizado.
- THE SYSTEM SHALL resolver ambos catálogos con **una consulta propia cacheada cada uno**, cuya clave
  no lleva filtros ni página, de modo que una sola copia sirva a todas las filas, todas las páginas y
  todas las combinaciones de filtro — nunca una petición por fila.
- THE SYSTEM SHALL distinguir cuatro situaciones de identidad y darle a cada una su texto traducido:
  **sin asignar** (`assigned_cleaner_id` nulo), **cargando** (catálogo en vuelo: guion `aria-hidden`
  más texto `sr-only`), **no disponible** (el id no está en el catálogo) y **resuelta**.
- IF un `property_id` o un `assigned_cleaner_id` no se resuelve contra su catálogo, THEN THE SYSTEM
  SHALL mostrar el indicador traducido de identidad no disponible y renderizar igualmente el resto de
  la fila, sin romper la lista.
- IF una tarea no tiene `scheduled_start` o `scheduled_end`, THEN THE SYSTEM SHALL mostrar el texto
  traducido de «sin programar» en vez de una fecha vacía.
- THE SYSTEM SHALL formatear las fechas con `Intl.DateTimeFormat` en el idioma activo.
- **Techo conocido y asumido**: THE SYSTEM SHALL pedir cada catálogo con `per_page: 100`, el
  `MAX_PER_PAGE` del backend, y en una sola página. `ASSUMPTION`: a partir de la propiedad o la
  limpiadora 101 del tenant, esa identidad degrada a «no disponible» y el filtro de propiedad no la
  ofrece. Superar ese techo exige paginar los catálogos o desnormalizar nombres en la respuesta de
  tareas, y ninguna de las dos cosas está hecha.
- **Un fallo de catálogo no es un error de la vista**: THE SYSTEM SHALL seguir renderizando la lista
  cuando `/properties` o `/users` fallan, con todas las identidades en «no disponible» y el filtro de
  propiedad vacío. No ofrece reintento para ese caso; la única recuperación es recargar.

### Filtros por vivienda y por estado

- THE SYSTEM SHALL ofrecer exactamente dos filtros —vivienda y estado— y enviarlos al backend en los
  parámetros `property_id` y `status` de `GET /api/v1/cleaning-tasks`, NUNCA filtrando en el cliente
  una página ya descargada.
- WHEN los dos filtros están activos, THE SYSTEM SHALL combinarlos en la misma petición, respetando
  el AND que aplica el backend; y SHALL omitir del query-string el parámetro que no esté definido.
- WHEN cualquier filtro cambia, THE SYSTEM SHALL volver a la página 1. El reinicio vive **dentro** de
  la acción del store, no en quien la llama, así que ninguna ruta de cambio de filtro puede olvidarlo.
- THE SYSTEM SHALL ofrecer una forma explícita de limpiar cada filtro —un botón que solo aparece
  cuando ese filtro está puesto, más la opción «todas/todos» del propio desplegable— y ambas SHALL
  volver también a la página 1.
- THE SYSTEM SHALL renderizar los filtros de forma incondicional, por encima del cuerpo de la vista,
  de modo que sigan operables durante la carga, el error y el vacío.
- **Los filtros no cruzan de tenant**: THE SYSTEM SHALL guardar en el store el tenant al que
  pertenecen y descartar propiedad, estado y página cuando el tenant cambia, ignorándolos ya en el
  primer render y no solo tras el efecto que los adopta. El store es un singleton de módulo que
  sobrevive a la sesión, y sin esto un `property_id` del tenant anterior viajaría en la petición.

### Asignar y reasignar

- WHEN un usuario con `MANAGE_CLEANING_TASKS` confirma una limpiadora, THE SYSTEM SHALL solicitar
  `PATCH /api/v1/cleaning-tasks/{task_id}` con **`assigned_cleaner_id` como único campo del cuerpo**,
  sin intentar mover el estado de la tarea desde esta vista.
- THE SYSTEM SHALL ofrecer como candidatas únicamente las usuarias del catálogo `role=CLEANER` cuyo
  `status` es `ACTIVE`, y SHALL seguir resolviendo el **nombre** de una limpiadora ya inactiva en las
  filas que la tengan asignada — se estrecha la lista de candidatas, no la de nombres.
- THE SYSTEM SHALL exigir una selección explícita: el desplegable no viene preseleccionado con la
  limpiadora actual, y SHALL impedir confirmar cuando no hay selección o cuando la seleccionada ya es
  la asignada, de modo que no se emita un PATCH que no cambia nada.
- WHERE el listado marca una tarea como no asignable ahora, THE SYSTEM SHALL deshabilitar además el
  botón de confirmación de esa fila y SHALL mostrar bajo él el motivo localizado —la vivienda o el
  estado de la tarea—, referenciado desde el botón con `aria-describedby` y renderizado **solo**
  cuando existe, para que un lector de pantalla no anuncie una descripción vacía.
- THE SYSTEM SHALL derivar esa condición del campo `assignment_blocked_by` que **ya viene en la
  respuesta del listado**, sin petición adicional por fila y **sin calcular nada en el componente**:
  la vista no conoce la matriz de estados de la vivienda y no debe aprenderla.
- THE SYSTEM SHALL mantener el `<select>` habilitado aunque el botón esté deshabilitado por ese
  motivo —solo lo deshabilita la mutación en vuelo de su propia fila—, porque deshabilitar un
  elemento que tiene el foco lo manda al `<body>`.
- THE SYSTEM SHALL mostrar el motivo como **texto estático** y no como `title` ni tooltip: la vista
  es mobile-first y donde se opera no hay hover.
- **La guarda es cortesía, no permiso**: IF la condición cambia entre la carga de la lista y la
  confirmación, THEN THE SYSTEM SHALL tratar el rechazo del backend como la autoridad. Un indicador
  ausente o `null` deja el botón vivo a propósito —falla abierto— y el `409` que llegue se anuncia
  ya con el mensaje correcto.
- WHILE una asignación está en vuelo, THE SYSTEM SHALL impedir confirmar otra en cualquier fila, y
  SHALL deshabilitar el desplegable **solo** de la fila que la lanzó, para no robar el foco a quien
  navega por teclado.
- WHEN la mutación termina —con éxito o con fallo—, THE SYSTEM SHALL invalidar el prefijo de clave de
  las tareas, alcanzando de una vez todas las páginas y combinaciones de filtro, y refrescar la lista
  sin recarga completa de la página.
- THE SYSTEM SHALL no aplicar ninguna actualización optimista: la celda de la limpiadora se pinta
  siempre desde los datos del servidor. **Una respuesta 403 NUNCA se interpreta como éxito** y la
  fila conserva la asignación que el backend sigue teniendo por buena.
- THE SYSTEM SHALL traducir el fallo **por el estado HTTP y, dentro del `409`, por el código del
  sobre — nunca por el texto del mensaje del backend**, que es técnico y está en inglés: `403` sin
  permiso, `404` tarea inexistente, `422` persona que ya no es limpiadora activa del tenant, y un
  mensaje genérico para cualquier otro estado o para un fallo que no sea de la API.
- THE SYSTEM SHALL distinguir los **dos** `409` que la asignación puede recibir:
  `PROPERTY_STATE_CONFLICT` atribuye el bloqueo **a la vivienda** («la vivienda todavía no está
  pendiente de limpieza») y SHALL NOT afirmar que la tarea no admite un cambio de asignación;
  cualquier otro código con `409` —`CONFLICT` incluido— conserva el mensaje del ciclo de vida de la
  tarea.
- IF el `409` llega con un código que esta compilación no conoce, THEN THE SYSTEM SHALL caer en el
  mensaje del ciclo de vida de la tarea, el que se servía antes de la distinción. Es la ventana de
  asimetría de despliegue: un frontend más viejo que su backend degrada al texto de ayer en vez de
  no decir nada, por el mismo razonamiento con que un estado de tarea desconocido degrada a gris.
- THE SYSTEM SHALL no reintentar la mutación.

### Permisos: el frontend oculta, el backend decide

- THE SYSTEM SHALL declarar en el frontend un único permiso de UI, `MANAGE_CLEANING_TASKS`, concedido
  **solo** a `PROPERTY_MANAGER`; `SUPER_ADMIN`, `TENANT_OWNER`, `CLEANER` y `TECHNICIAN` no lo tienen.
- IF el usuario autenticado no tiene `MANAGE_CLEANING_TASKS`, THEN THE SYSTEM SHALL ocultar el control
  de asignación y mostrar la asignación como texto de solo lectura, conservando el resto de la fila.
- THE SYSTEM SHALL tratar ese mapa como **pista de UX deliberadamente parcial y nunca como control de
  acceso**: el backend emite su `403` igual ante una petición directa, y ocultar el control no
  autoriza nada.
- **No hay puerta de lectura en el cliente**: THE SYSTEM SHALL dejar que la autorización de lectura la
  resuelva el backend. `READ_CLEANING_TASKS` no tiene representación en el frontend, así que un rol
  sin ese permiso que navegue a `/cleaning` pasa el `AuthGuard`, emite la petición y recibe el `403`
  del backend como `ErrorState`, en lugar de una superficie consciente del permiso.

### Paginación

- THE SYSTEM SHALL navegar páginas con el parámetro `page` y leer `total`, `page`, `per_page` y
  `total_pages` tal cual vienen en el envoltorio de la respuesta, sin recalcularlos.
- THE SYSTEM SHALL fijar `per_page` en 20 para las tareas. No hay control de usuario para cambiarlo:
  solo `page` es navegable.
- THE SYSTEM SHALL exponer la paginación como `nav` con nombre accesible, mostrar página y total y el
  número de tareas, y SHALL renderizarla siempre que la página traiga al menos una tarea —con ambos
  botones deshabilitados cuando no hay adonde ir.

### i18n, accesibilidad y mobile-first

- THE SYSTEM SHALL declarar toda string visible en el namespace `cleaning` de `locales/es/` y
  `locales/en/`, con **el mismo juego de claves en los dos idiomas** y las mismas interpolaciones, sin
  literales en los componentes. Los únicos caracteres literales que se pintan son el guion
  `aria-hidden` con su texto `sr-only` y los dos puntos de los prefijos `sr-only` de columna; el
  propio separador `·` es una clave.
- THE SYSTEM SHALL exponer los dos filtros y el control de asignación como `select` nativos con
  `label` asociada —visible en los filtros, `sr-only` en la asignación—, y las acciones como `button`
  nativos, operables por teclado. La confirmación es un botón aparte precisamente para que recorrer el
  desplegable con las flechas no envíe nada.
- THE SYSTEM SHALL anunciar el resultado de una asignación por **una sola región viva**
  (`role="status"`, `aria-live="polite"`), montada desde el primer render, que sirve el «enviando», el
  fallo con `role="alert"` y el éxito con el nombre de la limpiadora —o el texto de identidad no
  disponible si no se resuelve—, de modo que un lector de pantalla lo perciba sin depender del color.
- THE SYSTEM SHALL nombrar la lista y cada fila con nombre accesible, y SHALL prefijar con texto
  `sr-only` los campos de vivienda y estado en todos los anchos.
- THE SYSTEM SHALL ser legible y operable desde 320 px sin scroll horizontal de la página: una
  columna que se ensancha en `sm`/`xl`, `min-w-0` y `break-words` en cada nivel de anidamiento, y
  ningún contenedor con `overflow-x` ni ninguna tabla.
- THE SYSTEM SHALL dar a los tres desplegables un objetivo táctil de al menos 44×44 px.

### Frontera con el backend

- THE SYSTEM SHALL consumir únicamente endpoints que ya existían —`GET /cleaning-tasks`,
  `PATCH /cleaning-tasks/{task_id}`, `GET /users?role=CLEANER` y `GET /properties`—, sin estrenar
  ninguna ruta.
- **El contrato sí ha cambiado una vez, y por una necesidad de esta pantalla.** Esta capacidad se
  entregó sin tocarlo, pero `cleaning-assign-preconditions` amplió el item del listado con
  `assignment_blocked_by` precisamente para que la vista pudiera saber si una tarea es asignable
  ahora sin derivar reglas de negocio en el cliente. THE SYSTEM SHALL regenerar `backend/openapi.json`
  y `frontend/lib/api/generated/openapi.d.ts` en el mismo Pull Request que cambie esa forma —son las
  dos mitades del mismo puente, cada una con su workflow— y no SHALL declarar que esta capacidad
  vive sobre un contrato congelado.
- THE SYSTEM SHALL mantener las claves de consulta acotadas por tenant, aunque la fuente de datos no
  use el `tenantId` en la petición: la acotación real la hace el backend con el JWT verificado, y el
  parámetro existe para que la caché no cruce tenants.
- IF no hay tenant autenticado en el contexto, THEN THE SYSTEM SHALL fallar de forma explícita en vez
  de emitir una petición sin tenant.

## Estado

- **Deuda con disparador: la pasada visual de `/cleaning` no se ha hecho contra un entorno
  desplegado.** El bloqueo de fila que `cleaning-assign-preconditions` añadió está fijado por tests
  de componente con aserciones de DOM reales, y ningún criterio de aceptación depende de mirarlo —
  es acabado, no cobertura. Lo que falta es verlo: la fila bloqueada con el botón deshabilitado y el
  `<select>` vivo, el `409` de la carrera anunciándose con el mensaje de la vivienda, los dos
  idiomas, 320 px sin scroll horizontal y la consola limpia.

  **La razón que se dio para no hacerlo en el worktree ya no vale.** Esta deuda se apoyaba en que
  «`next dev` con `PORT_OFFSET` sirve la página sin hidratarla», y `tech-app` midió esa premisa
  falsa para su propio caso el 2026-08-29: con `PORT_OFFSET=10` la app hidrata y es completamente
  interactiva. `sdd/project.md` recoge la reconciliación completa — el fallo es real **sólo para
  `next dev`** cuando Next 15+ bloquea el origen cruzado del puerto desplazado, y aun entonces hay
  salida (servir el build de producción en un contenedor aparte, con su `npm run build` delante).
  Un worktree enlazado es, por tanto, un sitio válido para dar esta pasada.

  Lo que **sigue** en pie del bloqueo original es lo otro: `AWAITING_CLEANING` no es alcanzable por
  el camino real en un mismo día. **Disparador**: el primer despliegue de este change en `dev` —que
  es además donde se midió el fallo original el 2026-08-22— o cualquier worktree en el que se pueda
  llevar una tarea hasta ese estado.

## Key files

- `frontend/app/(workspace)/cleaning/page.tsx` — página servidor: metadata de la ruta y montaje de
  `CleaningView`. Ya no importa `RoutePlaceholder`.
- `frontend/features/cleaning/index.ts` — única exportación pública de la capacidad (`CleaningView`).
- `frontend/features/cleaning/components/` — `cleaning-view.tsx` (orquesta consultas, filtros,
  paginación, región viva), `cleaning-task-row.tsx` (tarjeta de tarea, `IdentityValue`, badge de
  estado), `cleaning-filters.tsx`, `cleaning-pagination.tsx`, `assign-cleaner-control.tsx`.
- `frontend/features/cleaning/data/` — `cleaning-source.ts` (interfaz `CleaningDataSource`), `dto.ts`
  (tipos, con `CleaningTaskStatus` aliasado al contrato generado, y `CleaningTaskListItem` sobre
  `CleaningTask` con `assignmentBlockedBy`), `http/http-cleaning-source.ts`
  (endpoints, parámetros y mapeo snake_case→camelCase con `mapTask`/`mapListItem`,
  `TASKS_PER_PAGE`/`CATALOG_PER_PAGE`), `index.ts` (composición de la fuente única).
  **Cuidado al propagar un campo nuevo del listado**: `CleaningTaskListItem` es un supertipo por
  ampliación y TypeScript es estructural, así que el typecheck se rompe en el mapeador y **solo
  ahí**; un consumidor que siga anotado con el tipo base compila igual aunque nunca lea el campo.
  Lo que cubre ese tramo son los tests que fijan que la fila bloqueada deshabilita el botón, no el
  compilador.
- `frontend/features/cleaning/hooks/` — `query-keys.ts` (claves acotadas por tenant),
  `use-cleaning-data.ts` (tareas + los dos catálogos cacheados), `use-assign-cleaning-task.ts`
  (mutación, `retry: false`, invalidación en `onSettled`).
- `frontend/features/cleaning/lib/` — `task-status.ts` (mapa exhaustivo estado→color y clases de
  badge), `directory.ts` (índice de catálogo y las cuatro formas de identidad), `assign-error.ts`
  (estado HTTP→clave de traducción, más la tabla por código consultada solo dentro del `409`).
- `frontend/features/cleaning/state/use-cleaning-filters-store.ts` — store Zustand de filtros, página
  y tenant adoptado.
- `frontend/lib/auth/permissions.ts` — `Permission`, `ROLE_UI_PERMISSIONS`, `useHasPermission`;
  reexportados en `frontend/lib/auth/index.ts`.
- `frontend/locales/{es,en}/cleaning.json` — catálogo de la vista, registrado en
  `frontend/lib/i18n/resources.ts`.
- Comportamiento del backend que consume: `cleaning.md`. Cómo se opera: `docs/cleaning.md`.
