# Detalle operativo de una limpieza (`/cleaning/[id]`)

## Purpose

`/cleaning/[id]` es la superficie de **lectura** que un `PROPERTY_MANAGER` o un `TENANT_OWNER`
abre desde una fila del listado (`cleaning-manager-view.md`) para ver el detalle completo de una
tarea de limpieza — estado, ciclo de vida, vivienda, reserva y limpiadora asignada — y, si tiene
permiso, operar sobre ella con los mismos tres controles del listado (asignar, validar, cancelar).
Es una capa de presentación pura sobre `GET /api/v1/cleaning-tasks/{task_id}`, que ya describe
`cleaning.md`: no añade reglas de negocio ni de acceso nuevas, y es el prerrequisito compartido
que desbloquea las dos entradas que montarán su propio bloque sobre esta página —
`photo-storage-manager-view` (galería de fotos) y `staff-messaging-manager-view` (hilo de
mensajería) — ninguna de las dos está entregada todavía y esta página no las anticipa.

## Requirements

### Acceso y ciclo de vida de la página

- WHEN un usuario autenticado abre `/cleaning/[id]`, THE SYSTEM SHALL solicitar
  `GET /api/v1/cleaning-tasks/{task_id}` y renderizar el detalle con la tarea que devuelve, y NO
  un `RoutePlaceholder` — la ruta es una superficie funcional, montada bajo el mismo `AuthGuard`
  del grupo `(workspace)` que `/cleaning` (solo comprueba sesión).
- WHILE la consulta está en vuelo, THE SYSTEM SHALL mostrar el `LoadingState` común
  (`role="status"`, `aria-busy`, `aria-live="polite"`).
- IF la tarea no existe o pertenece a otro tenant (`404`), THEN THE SYSTEM SHALL mostrar
  `EmptyState` con un enlace de regreso a `/cleaning`, distinguible del error genérico y de la
  carga. El backend no puede distinguir "no existe" de "es de otro tenant" — ambos casos comparten
  el mismo `404` y la misma copia.
- IF el usuario no tiene `READ_CLEANING_TASKS` (`403`), THEN THE SYSTEM SHALL mostrar un texto
  plano indicando que la tarea no está disponible para su rol, sin `role="alert"` — no debería
  ocurrir para `PROPERTY_MANAGER`/`TENANT_OWNER`, y el caso cubre asimetría de despliegue.
- IF el identificador de la tarea es inválido (`422`), THEN THE SYSTEM SHALL mostrar un texto
  plano de identificador inválido.
- IF la consulta falla por cualquier otro motivo (`5xx`, red, `4xx` no mapeado), THEN THE SYSTEM
  SHALL mostrar `ErrorState` con `role="alert"` y una acción de reintento que relanza la consulta,
  sin recargar la página.
- THE SYSTEM SHALL no reintentar automáticamente ninguna respuesta de esta consulta (`retry:
  false`): un `404` no es transitorio.
- THE SYSTEM SHALL resolver el `tenantId` de la sesión del propio hook de detalle, sin depender de
  que el listado se haya montado antes — la página admite entrar por enlace directo.

### Encabezado: estado, validación, programación y ciclo de vida

- WHEN la tarea carga, THE SYSTEM SHALL mostrar en el encabezado el `status` de la tarea con la
  misma insignia coloreada por grupo que usa el listado (`CREATED`/`ASSIGNED`/`PENDING_REVIEW` en
  ámbar, `ACCEPTED`/`IN_PROGRESS` en azul, `COMPLETED` en verde, `REJECTED`/`FAILED` en rojo,
  `CANCELLED` en gris) y NUNCA el identificador crudo del enum.
- THE SYSTEM SHALL mostrar el `validation_status` vigente de la tarea como etiqueta traducida,
  sin insignia de color.
- THE SYSTEM SHALL mostrar la ventana programada (`scheduled_start`–`scheduled_end`) formateada
  con `Intl.DateTimeFormat` en el idioma activo; un extremo ausente se compone igualmente en la
  misma cadena interpolada.
- WHERE `completed_at` no es nulo O `validation_status` es distinto de `PENDING`, THE SYSTEM SHALL
  mostrar además la fecha de finalización y, si `validated_at` no es nulo, la fecha de validación
  (con una etiqueta distinta —"Validación rechazada"— cuando el veredicto es `FAILED`). En
  cualquier otro caso THE SYSTEM SHALL NOT pintar esas dos fechas: "Pendiente de validación" sobre
  una tarea que nadie ha limpiado todavía se leería como una tarea atascada.

### Identificación: vivienda y reserva

- WHEN la tarea carga, THE SYSTEM SHALL identificar su vivienda por `internal_code` y `name`
  resueltos contra el mismo catálogo cacheado que usa el listado (`usePropertyDirectory()`), y NO
  por el `property_id` crudo.
- IF la vivienda no está en el catálogo resuelto, THEN THE SYSTEM SHALL mostrar el indicador
  traducido de "vivienda no disponible" y seguir renderizando el resto del bloque.
- WHILE el catálogo de viviendas está en vuelo, THE SYSTEM SHALL mostrar un marcador neutro
  (`aria-hidden`) con texto `sr-only` de "cargando", en vez del código o el nombre.
- WHEN la tarea tiene `reservation_id` no nulo, THE SYSTEM SHALL mostrar ese identificador como el
  código de la reserva. IF `reservation_id` es nulo, THEN THE SYSTEM SHALL mostrar el indicador
  traducido de "reserva no disponible".

### Limpiadora asignada

- WHEN la tarea tiene `assigned_cleaner_id` no nulo, THE SYSTEM SHALL mostrar el nombre de esa
  usuaria resuelto contra el mismo catálogo cacheado que usa el listado (`useCleanerDirectory()`),
  y NO el UUID.
- IF `assigned_cleaner_id` es nulo, THEN THE SYSTEM SHALL mostrar el texto traducido de "sin
  asignar", distinto del texto de "no disponible" que se usa cuando el id no resuelve contra el
  catálogo.
- THE SYSTEM SHALL mostrar este bloque incondicionalmente, sin gatearlo por
  `MANAGE_CLEANING_TASKS`: un `TENANT_OWNER` sin ese permiso también ve quién tiene la tarea
  asignada.

### Controles del manager: asignar, validar, cancelar

- THE SYSTEM SHALL condicionar el bloque de controles del manager (asignar, validar, cancelar) a
  `useHasPermission("MANAGE_CLEANING_TASKS")`, oculto por completo para quien no lo tiene —mismo
  gate que el listado.
- WHERE el bloque de controles es visible, THE SYSTEM SHALL montar los mismos componentes que usa
  el listado (`AssignCleanerControl`, `ValidateCleaningControl`, `CancelCleaningTaskDialog`) con la
  misma forma de props, sin variantes `*Detail` — cualquier corrección a un control se hace en un
  solo sitio, no en dos.
- THE SYSTEM SHALL ofrecer el botón de cancelar solo cuando el estado de la tarea no es terminal
  (`COMPLETED`, `FAILED`, `CANCELLED` son terminales) y deshabilitarlo mientras la cancelación está
  en vuelo.
- THE SYSTEM SHALL anunciar el resultado de las tres mutaciones por una única región viva
  (`role="status"`, `aria-live="polite"`) montada en la página, con la misma precedencia que el
  listado ya declara (mutación en curso > último error > último éxito), y el mensaje de éxito de
  asignar resuelve el nombre de la limpiadora contra el mismo catálogo del bloque de identidad.
- THE SYSTEM SHALL invalidar la clave de consulta del detalle (`cleaningKeys.task(tenantId,
  taskId)`) cuando cualquiera de las tres mutaciones (asignar, validar, cancelar) se asienta,
  además de la clave de listado que ya invalidaban — de modo que reabrir o refrescar el detalle
  refleje el cambio sin depender de haber pasado por `/cleaning`.

### Enlaces de contexto

- THE SYSTEM SHALL ofrecer siempre un enlace de regreso a `/cleaning`, sin condición de permiso.
- WHERE el usuario tiene `READ_PROPERTIES`, THE SYSTEM SHALL ofrecer un enlace a
  `/properties/{property_id}`; concedido a `PROPERTY_MANAGER` y `TENANT_OWNER`, ausente en
  `CLEANER`/`TECHNICIAN`.
- WHERE el usuario tiene `READ_RESERVATIONS` Y la tarea tiene `reservation_id` no nulo, THE SYSTEM
  SHALL ofrecer un enlace a `/reservations/{reservation_id}`. IF el usuario no tiene el permiso o
  la tarea no tiene reserva asociada, THEN THE SYSTEM SHALL ocultar el enlace — no degradarlo a
  texto plano ni ofrecer una acción que el backend rechazaría con `403`.

### Enlace de entrada desde el listado

- WHEN el listado (`/cleaning`) renderiza una fila, THE SYSTEM SHALL envolver el `<h3>` de
  `internalCode · name` de la vivienda en un enlace a `/cleaning/{task.id}`, con estilos de
  hover/foco visibles. La insignia de estado y los controles de la fila quedan fuera del enlace,
  para que el área clickable sea inequívoca y no dispare accidentalmente asignar/validar/cancelar.

### Frontera con el backend

- THE SYSTEM SHALL consumir únicamente `GET /api/v1/cleaning-tasks/{task_id}` para el detalle,
  sin estrenar ninguna ruta backend. El contrato no se ha tocado en esta entrada.
- **Gap de contrato conocido**: `get_cleaning_task_api_v1_cleaning_tasks__task_id__get` no declara
  `404` en su bloque `responses` de `backend/openapi.json` (solo `200/401/403/422`), aunque el
  backend lo devuelve en la práctica (documentado en el `description` del operation). El mapeador
  de errores del frontend intercepta el `404` **por número de estado HTTP**, no por el tipo
  generado. El arreglo del contrato (añadir `responses.404`, y de paso `responses.401` que el
  operation ya declara pero el cliente generado no emite) queda como candidato de
  `api-contract-export`; no bloquea esta capacidad.
- THE SYSTEM SHALL ampliar el DTO `CleaningTask` con `reservationId: string | null`, mapeado desde
  `reservation_id` de `CleaningTaskResponse` — el único de los campos que el backend publica y que
  esta vista necesita y que el DTO no traía todavía.

### i18n, accesibilidad y mobile-first

- THE SYSTEM SHALL declarar toda string visible en el namespace `cleaning` bajo la clave
  `detail.*` de `locales/es/` y `locales/en/`, con el mismo juego de claves e interpolaciones en
  los dos idiomas.
- THE SYSTEM SHALL declarar las claves `routes.cleaning-detail.{title,description}` en el
  namespace `navigation` de los dos idiomas.
- THE SYSTEM SHALL renderizar la página como una sola columna apilada (`<article>` con
  `flex flex-col gap-4 p-4`), legible y operable desde 320 px sin scroll horizontal, con objetivo
  táctil de al menos 44×44 px en los controles.
- THE SYSTEM SHALL NOT aplicar `sticky`/`position-sticky` al encabezado de la página.

## Estado

Sin deuda declarada. La pasada manual en navegador (tarea 7.4 del change) se completó y se marcó
como `assumed`/manual en `tasks.md` antes de archivar.

## Key files

- `frontend/app/(workspace)/cleaning/[id]/page.tsx` — página servidor: `generateMetadata()` con
  `routeMetadata("cleaning-detail")`, monta `CleaningTaskDetailView` con el `id` de `params`.
- `frontend/features/cleaning/components/detail/` — `cleaning-task-detail-view.tsx` (orquesta la
  consulta, los dos catálogos, las tres mutaciones y la región viva única), y un componente por
  bloque: `detail-header-block.tsx` (estado, validación, ventana, fechas de ciclo de vida),
  `detail-identifying-block.tsx` (vivienda y reserva), `detail-assigned-cleaner-block.tsx`
  (limpiadora), `detail-manager-actions-block.tsx` (los tres controles, gateado por
  `MANAGE_CLEANING_TASKS`), `detail-context-links-block.tsx` (enlaces a listado/vivienda/reserva).
- `frontend/features/cleaning/hooks/use-cleaning-task.ts` — `useQuery` con
  `cleaningKeys.task(tenantId, taskId)`, `retry: false`, `enabled: !!taskId`.
- `frontend/features/cleaning/hooks/query-keys.ts` — export `task(tenantId, taskId)` construido
  con `tenantScopedKey`.
- `frontend/features/cleaning/lib/detail-error.ts` — `mapCleaningDetailError`, mapeador puro
  `UseQueryResult` → `CleaningDetailState` (`loading | forbidden | not-found | validation | error |
  success`), por código HTTP (403/404/422, D12 documenta el gap del 404).
- `frontend/features/cleaning/data/cleaning-source.ts`, `data/http/http-cleaning-source.ts` —
  `getTask(tenantId, taskId)` y el mapeo de `reservation_id` → `reservationId` en `mapTask`.
- `frontend/features/cleaning/data/dto.ts` — `CleaningTask.reservationId: string | null`.
- `frontend/features/cleaning/hooks/use-assign-cleaning-task.ts`,
  `use-validate-cleaning-task.ts`, `use-cancel-cleaning-task.ts` — invalidan también
  `cleaningKeys.task(tenantId, taskId)` en `onSettled`.
- `frontend/features/cleaning/components/cleaning-task-row.tsx` — el `<h3>` de la fila envuelto en
  `<Link href={`/cleaning/${task.id}`}>`.
- `frontend/features/shell/navigation/route-registry.ts` — entrada `cleaning-detail`
  (`pattern: "/cleaning/[id]"`, `profile: "workspace"`, `match: "exact"`, icono `Sparkles`).
- `frontend/app/route-coverage.test.ts` — `(workspace)/cleaning/[id]/page.tsx` → `cleaning-detail`
  en `REAL_PAGE_ROUTE_IDS`.
- `frontend/locales/{es,en}/cleaning.json` — namespace `detail.*`.
- `frontend/locales/{es,en}/navigation.json` — `routes.cleaning-detail.*`.
- `frontend/lib/auth/permissions.ts` — `READ_PROPERTIES`/`READ_RESERVATIONS` concedidos a
  `PROPERTY_MANAGER` y `TENANT_OWNER`.
- Comportamiento del backend que consume: `cleaning.md`. Cómo se opera: `docs/cleaning.md` §«Detalle
  operativo del manager».
