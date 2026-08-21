# Proposal: cleaning-manager-view

## Why

`/cleaning` es hoy un `RoutePlaceholder`: la ruta existe en el registro tipado, aparece en la
navegación y muestra «En preparación». El backend de limpieza está completo desde el change
`cleaning` — listado paginado con filtros, asignación, ciclo de vida, checklist, fotos y contexto —
y `cleaner-task-context` acaba de cerrar la parte que faltaba del lado de la limpiadora. Lo que no
existe es la superficie por la que el manager **opera** ese backend: PRD §6 le da «gestionar
limpiezas: asignar, reasignar, validar» y PRD §24 declara `/cleaning` como «lista de tareas de
limpieza», pero hoy la única forma de asignar una limpiadora es una llamada HTTP a mano.

Sin esta vista, el flujo de PRD §11 se rompe en su segundo paso: cuando la asignación automática no
encuentra limpiadora activa, la tarea «queda pendiente» y nadie tiene dónde recogerla. Entrada de
roadmap: `cleaning-manager-view` (`needs: cleaning, dashboard-web`, ambas archivadas; talla S,
tercera de la frontera).

## What changes

Después de este change, `/cleaning` deja de ser un placeholder y pasa a ser la lista real de tareas
de limpieza del tenant: una tabla/lista mobile-first, paginada contra `GET /api/v1/cleaning-tasks`,
con filtros por propiedad y por estado, en la que cada fila identifica su propiedad y su limpiadora
**por nombre** en vez de por UUID, y desde la que un `PROPERTY_MANAGER` puede asignar o reasignar la
tarea a una limpiadora del tenant (`PATCH /api/v1/cleaning-tasks/{id}`). Un `TENANT_OWNER` ve
exactamente la misma lista sin el control de asignación, porque no tiene
`MANAGE_CLEANING_TASKS`.

**No se toca el backend.** Los cuatro endpoints que consume ya existen y ya son alcanzables por
manager y owner: `GET /cleaning-tasks` (`READ_CLEANING_TASKS`), `PATCH /cleaning-tasks/{id}`
(`MANAGE_CLEANING_TASKS`), `GET /users?role=CLEANER` (`READ_USERS`) y `GET /properties`
(`READ_PROPERTIES`). Al no cambiar el contrato, `backend/openapi.json` y
`frontend/lib/api/generated/openapi.d.ts` no se regeneran — solo se consumen los tipos que ya
declaran.

## Requirements

### R1 — La lista real de tareas de limpieza

**As a** `PROPERTY_MANAGER` o `TENANT_OWNER`, **I want** ver en `/cleaning` las tareas de limpieza de
mi tenant con su estado, **so that** sepa qué limpiezas hay pendientes sin llamar a la API a mano.

Acceptance criteria:

1. WHEN un usuario autenticado con `READ_CLEANING_TASKS` abre `/cleaning`, THE SYSTEM SHALL renderizar
   la lista de tareas devuelta por `GET /api/v1/cleaning-tasks`, en el orden y la página que devuelve
   el backend, y NO el `RoutePlaceholder`.
2. WHEN la petición está en vuelo, THE SYSTEM SHALL mostrar el estado de carga accesible ya definido
   en `frontend-foundation` (`LoadingState`, `aria-busy`), sin inventar uno nuevo.
3. IF la petición falla, THEN THE SYSTEM SHALL mostrar `ErrorState` con `role="alert"` y una acción de
   reintento que vuelve a lanzar la consulta.
4. IF el tenant no tiene ninguna tarea que coincida con los filtros activos, THEN THE SYSTEM SHALL
   mostrar `EmptyState` distinguible del estado de error y del de carga.
5. WHEN el total de tareas supera una página, THE SYSTEM SHALL ofrecer navegación de páginas que use
   los parámetros `page`/`per_page` del endpoint y refleje `total`/`total_pages` de la respuesta.
6. WHERE la lista muestra el estado de una tarea, THE SYSTEM SHALL mostrar cada uno de los nueve
   valores de `CleaningTaskStatus` (`CREATED`, `ASSIGNED`, `ACCEPTED`, `REJECTED`, `IN_PROGRESS`,
   `PENDING_REVIEW`, `COMPLETED`, `FAILED`, `CANCELLED`) con una etiqueta traducida y un color
   consistente, nunca el identificador crudo del enum.

### R2 — Identidad legible: propiedad y limpiadora por nombre

**As a** manager, **I want** leer en cada fila de qué vivienda y de qué limpiadora se trata, **so
that** pueda decidir sin traducir UUIDs de memoria.

Acceptance criteria:

1. WHEN la lista muestra una tarea, THE SYSTEM SHALL identificar su propiedad por el `internal_code` y
   el `name` que devuelve `GET /api/v1/properties`, y NO por el `property_id` crudo que trae
   `CleaningTaskResponse`.
2. WHEN una tarea tiene `assigned_cleaner_id`, THE SYSTEM SHALL mostrar el nombre de esa usuaria
   resolviéndolo contra `GET /api/v1/users?role=CLEANER`, y NO el UUID.
3. IF `assigned_cleaner_id` es `null`, THEN THE SYSTEM SHALL mostrar de forma explícita y traducida
   que la tarea está **sin asignar**, distinguible de un dato que no se ha podido cargar.
4. IF un `property_id` o un `assigned_cleaner_id` no se resuelve contra su listado (usuaria
   desactivada, propiedad fuera de la página consultada), THEN THE SYSTEM SHALL degradar a un
   indicador traducido de identidad no disponible y renderizar igualmente el resto de la fila, sin
   romper la lista.
5. THE SYSTEM SHALL resolver ambos catálogos con consultas propias cacheadas por TanStack Query, sin
   emitir una petición por fila.

### R3 — Filtros por propiedad y por estado

**As a** manager, **I want** acotar la lista a una vivienda o a un estado, **so that** encuentre las
tareas que requieren acción sin recorrer todo el histórico.

Acceptance criteria:

1. WHEN el usuario elige una propiedad en el filtro, THE SYSTEM SHALL enviar su id en el parámetro
   `property_id` de `GET /api/v1/cleaning-tasks` y NO filtrar en el cliente sobre una página ya
   descargada.
2. WHEN el usuario elige un estado, THE SYSTEM SHALL enviarlo en el parámetro `status` del mismo
   endpoint.
3. WHEN ambos filtros están activos, THE SYSTEM SHALL combinarlos en la misma petición, respetando el
   AND que aplica el backend.
4. WHEN cualquier filtro cambia, THE SYSTEM SHALL volver a la página 1, de modo que no se muestre una
   página vacía por un desplazamiento heredado del filtro anterior.
5. THE SYSTEM SHALL ofrecer una forma explícita de limpiar cada filtro y volver a la lista sin acotar.

### R4 — Asignar y reasignar desde la vista

**As a** `PROPERTY_MANAGER`, **I want** asignar o reasignar una tarea a una limpiadora desde la
propia lista, **so that** una tarea que la asignación automática dejó pendiente no se quede parada.

Acceptance criteria:

1. WHEN un usuario con `MANAGE_CLEANING_TASKS` confirma una limpiadora para una tarea, THE SYSTEM
   SHALL solicitar `PATCH /api/v1/cleaning-tasks/{id}` con `assigned_cleaner_id` y, al recibir la
   tarea actualizada, reflejar el nuevo estado y la nueva asignación en la lista sin recarga completa
   de la página.
2. THE SYSTEM SHALL ofrecer como candidatas únicamente las usuarias que `GET /api/v1/users` devuelve
   con `role=CLEANER` y estado activo.
3. IF el usuario autenticado no tiene `MANAGE_CLEANING_TASKS` — el caso del `TENANT_OWNER` —, THEN THE
   SYSTEM SHALL ocultar el control de asignación y mostrar la asignación como texto de solo lectura.
4. IF el backend responde `403`, THEN THE SYSTEM SHALL mostrar un error traducido y dejar la fila con
   la asignación que el backend sigue teniendo por buena — el frontend oculta, el backend decide, y
   una respuesta `403` NUNCA se interpreta como éxito optimista.
5. IF el backend responde `404` o `409`, THEN THE SYSTEM SHALL mostrar el mensaje traducido que
   corresponde a cada caso y refrescar la lista, sin dejar en pantalla una asignación que el servidor
   no aceptó.
6. THE SYSTEM SHALL enviar el `assigned_cleaner_id` como único campo mutable de esa petición, sin
   intentar mover el estado de la tarea desde esta vista.

### R5 — i18n, accesibilidad y mobile-first

**As a** propietaria que opera desde el móvil, **I want** la vista en mi idioma y usable en una
pantalla pequeña, **so that** pueda revisar las limpiezas sin abrir el portátil.

Acceptance criteria:

1. THE SYSTEM SHALL declarar toda string visible de esta vista — cabeceras, etiquetas de estado,
   filtros, estados vacío/error, textos del control de asignación — en `locales/es/` y en
   `locales/en/`, sin ninguna cadena literal en los componentes.
2. THE SYSTEM SHALL renderizar la lista de forma legible y operable desde 320 px de ancho, sin scroll
   horizontal de la página.
3. THE SYSTEM SHALL exponer los filtros y el control de asignación como controles con etiqueta
   accesible y operables por teclado.
4. WHEN una acción de asignación termina, THE SYSTEM SHALL anunciar el resultado por una región viva,
   de modo que un lector de pantalla lo perciba sin depender del color.

## Out of scope

- **Validar una limpieza terminada** (`POST /api/v1/cleaning-tasks/{id}/validate`, PRD §6 «validar»).
  Decidido fuera en `/sdd:new`: validar a ciegas, sin ver el checklist ni las fotos, no es un veredicto
  informado, y el detalle que lo haría informado no está en el alcance de esta entrada. Va a una
  entrada propia del roadmap cuando exista la superficie de detalle.
- **Detalle de una tarea** (`/cleaning/[id]`, checklist, fotos, contexto). PRD §24 no declara esa ruta;
  el detalle operativo de una limpieza vive hoy en la app de la limpiadora (`cleaner-app`) y en la
  ficha de propiedad (`/properties/[id]`, ya entregada por `dashboard-web`).
- **Crear una tarea a mano** (`POST /api/v1/cleaning-tasks`). El camino normal es `process_checkouts`;
  la creación manual es un caso de excepción que no bloquea la operativa diaria.
- **Plantillas de checklist** (`/api/v1/cleaning-checklist-templates`). Superficie de configuración,
  no de operación; encaja en `settings`.
- **Cualquier cambio en el backend**, incluidos ampliar `CleaningTaskResponse` con nombres
  desnormalizados y regenerar `backend/openapi.json` o el `openapi.d.ts` del frontend.
- **La app móvil de la limpiadora** (`/cleaner`) y el rol `CLEANER` en el frontend: son `cleaner-app`.
- **Notificaciones y SLA de la asignación** (PRD §11): ya los emite el backend en `cleaning`; esta
  vista no los reimplementa ni los muestra.

## Affected specs

- `sdd/specs/cleaning-manager-view.md` *(no existe aún — se creará al archivar)*: el comportamiento de
  la vista `/cleaning`.
- `sdd/specs/frontend-foundation.md`: su inventario de superficies («18 placeholder pages plus three
  functional surfaces») deja de ser cierto — pasa a 17 placeholders y cuatro superficies funcionales.
- `sdd/specs/cleaning.md`: sin cambio de comportamiento del backend; se revisará al archivar si alguna
  regla de RBAC merece anotar que ya tiene consumidor de frontend.
