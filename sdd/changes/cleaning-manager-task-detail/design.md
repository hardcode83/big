# Design: cleaning-manager-task-detail

## Context

`/cleaning` ya está implementado como lista (`cleaning-manager-view`, archivado
2026-08-22): `frontend/app/(workspace)/cleaning/page.tsx` renderiza `CleaningView`
(`features/cleaning/components/cleaning-view.tsx`), que orquesta tres consultas de TanStack
Query —`useCleaningTasks`, `useCleanerDirectory`, `usePropertyDirectory`— sobre una frontera
`CleaningDataSource` (`features/cleaning/data/cleaning-source.ts`) con una única
implementación `HttpCleaningSource`. Las tres mutaciones que la lista posee hoy (`assign`,
`cancel` y, desde `cleaning-task-manage-web`, `validate`/`create`) viven en sus propios hooks
(`hooks/use-*.ts`) y reusan la misma región viva `role="status" aria-live="polite"`.

El detalle operativo del workspace existe **solo** para incidencias:
`frontend/app/(workspace)/incidents/[id]/page.tsx` monta `IncidentDetailView`
(`features/incidents/components/detail/incident-detail-view.tsx`), que sigue un patrón de
composición por bloques de lectura —`DetailHeader`, `DetailIdentifyingBlock`,
`DetailAssignedTechnicianBlock`, `DetailDescriptionBlock`, `DetailCostsBlock`,
`DetailMetadataBlock`— más `ManagerIncidentActions` montado tras
`useHasPermission("MANAGE_INCIDENTS")`. El registro de rutas en
`frontend/features/shell/navigation/route-registry.ts` ya conoce
`incident-detail`/`reservation-detail`/`property-detail` pero **no** la ruta
`cleaning-detail` que esta entrada estrena, y `frontend/app/route-coverage.test.ts:31-57`
la declara como la fuente autoritativa del censo de superficies funcionales (regla 11 del
proyecto, gate `route-surface-counts-have-an-authoritative-source`).

El backend expone `GET /api/v1/cleaning-tasks/{task_id}` (`backend/openapi.json`, ruta
`get_cleaning_task_api_v1_cleaning_tasks__task_id__get`) con respuesta
`CleaningTaskResponse` y, **en la práctica**, los códigos `403` (sin permiso), `404` (la
tarea es de otro tenant o no existe — declarado en el `description` del operation, no en
el bloque `responses`) y `422` (cuerpo inválido). El DTO `CleaningTask`
(`features/cleaning/data/dto.ts`) ya mapea 10 campos de los 16 que la respuesta publica y
que esta vista consume —incluidos los tres que `cleaning-task-manage-web` añadió
(`completedAt`, `validationStatus`, `validatedAt`)— vía `mapTask` en
`features/cleaning/data/http/http-cleaning-source.ts`. **Lo que falta en el DTO hoy**:
`reservation_id`, que `CleaningTaskResponse` publica y que R3.2/R4.3 necesitan para mostrar
el código de reserva y enlazar a `/reservations/[id]` — se añade a `CleaningTask` y a
`mapTask` como parte de esta entrada (D11).

El mapa de permisos (`backend/app/auth/domain/policy.py`, regla 2 de
`steering/security.md`) ya dice: `PROPERTY_MANAGER` y `TENANT_OWNER` tienen
`READ_CLEANING_TASKS`; sólo `PROPERTY_MANAGER` tiene `MANAGE_CLEANING_TASKS`. La pantalla
lee con el primero y opera con el segundo, gateado por `useHasPermission`.

## Decisions

### D1 — Composición por bloques de lectura, no una página monolítica

**Chosen:** `CleaningTaskDetailView` compone los seis bloques del proposal
(R2: encabezado; R3.1-R3.4: identificación con vivienda y reserva; R3.5: bloque de
asignación con limpiadora por nombre; R2: ciclo de vida y validación; R4.1-R4.3: enlaces de
contexto; R5.1-R5.5: controles del manager) en componentes pequeños en
`features/cleaning/components/detail/`, **uno por bloque**, siguiendo el precedente de
`features/incidents/components/detail/incident-detail-sections.tsx` (cada bloque con su
propio test y su propio namespace i18n). El detalle del workspace sobre `IncidentDetailView`
es la guía directa: los seis bloques son del mismo tamaño conceptual que los suyos, y la
forma ya pasa los chequeos del panel del 2026-09-17 sobre `IncidentDetailView`.

Rejected: un único `cleaning-task-detail-view.tsx` con todo inline — ilegible por encima de
150 líneas y rompe el precedente de `IncidentDetailView` que el panel de revisión ya midió
como acertado.
Rejected: una subcarpeta por bloque con su propio `index.ts` — peso muerto; los bloques se
consumen sólo desde aquí.

### D2 — Una sola ruta registrada con `pattern: "/cleaning/[id]"`, no dos

**Chosen:** la ruta es `cleaning-detail`, registrada en `routeRegistry` con
`pattern: "/cleaning/[id]"`, `profile: "workspace"`, `match: "exact"`,
`breadcrumbKeys: crumbs("cleaning", "cleaning-detail")`. El registro de claves sigue el
helper existente `keysFor("cleaning-detail")` y declara el icono `Sparkles`, el mismo del
listado (`route-registry.ts:155`), para que el breadcrumb use la misma señal visual.

Rejected: una segunda ruta `cleaning-task-detail` separada — duplica la noción del
breadcrumb (`cleaning.task.detail`) y confunde la métrica del panel de cobertura
(`route-surface-counts-have-an-authoritative-source` cuenta una superficie, no dos).

### D3 — `getTask(tenantId, taskId)` en `CleaningDataSource`, `useCleaningTask` en `hooks/`

**Chosen:** la frontera `CleaningDataSource` (`features/cleaning/data/cleaning-source.ts`)
gana un único método nuevo:

```ts
getTask(tenantId: string, taskId: string): Promise<CleaningTask>;
```

La implementación HTTP (`http-cleaning-source.ts`) llama a
`GET /api/v1/cleaning-tasks/{taskId}` con `params: { taskId }` y devuelve `mapTask` (ya
existente, ya cubre los 17 campos). El hook `useCleaningTask(taskId)` en
`features/cleaning/hooks/use-cleaning-task.ts` es un `useQuery` con clave
`cleaningKeys.task(tenantId, taskId)` —nueva clave de detalle—, `enabled: !!taskId`,
`retry: false` (un `404` no es transitorio, regla de cleaning-task-manage-web D10), y un
mapeador de error propio (`features/cleaning/lib/detail-error.ts`, ver D5). El hook se
exporta desde `features/cleaning/index.ts`.

Rejected: hacer la consulta directamente en la página con `apiClient` — rompe la frontera
de `CleaningDataSource` y hace que los tests del componente necesiten `msw`/`fetch` real;
rechazado por la misma razón que `cleaning-manager-view` D1.
Rejected: composición `useQuery` con clave `tasksPrefix` y filtro cliente — el endpoint
lista paginada ya está y nadie lo va a quitar, pero reusarlo para el detalle introduce una
petición que puede devolver una página sin la tarea pedida si los filtros están mal
sincronizados con el detalle.

### D4 — `cleaningKeys.task(tenantId, taskId)` se invalida con `tasksPrefix` al mutar

**Chosen:** `features/cleaning/hooks/query-keys.ts` gana un nuevo export construido con
`tenantScopedKey` (la única vía para producir una clave que respete el invariante que el
docblock del módulo declara: "every key begins with `['tenant', tenantId, ...]` y a
cross-tenant key cannot be produced by accident"):

```ts
task: (tenantId: string, taskId: string): QueryKey =>
  tenantScopedKey(tenantId, "cleaning-task", taskId);
```

`useAssignCleaningTask`, `useValidateCleaningTask` y `useCancelCleaningTask` extienden su
`onSettled` para invalidar también `cleaningKeys.task(tenantId, taskId)` cuando la mutación
opera sobre una tarea concreta (las tres, hoy). El listado ya invalida
`tasksPrefix(tenantId)`; añadir la clave de detalle mantiene simetría con `useIncident` /
`incidentsKeys.detail` que el incidente ya hace así.

Rejected: una sola clave de detalle y dejar el listado como está — entonces una asignación
hecha desde el listado no refresca el detalle si el usuario lo abrió en otra pestaña, y
el `404`/`409` de la pantalla detalle mostraría el estado previo.
Rejected: una sola clave compartida `cleaningKeys.tasks` — acoplaría el caché de lista y
detalle y provocaría refetchs masivos.
Rejected: construir la clave como `["cleaning", "task", tenantId, taskId]` literal — un
tuple literal salta `tenantScopedKey` y rompe el invariante del módulo; un test de
`query-keys.test.ts` ya verifica que ningún `cleaningKeys` lo hace.

### D5 — Mapeador de error nuevo en `features/cleaning/lib/detail-error.ts`

**Chosen:** `detail-error.ts` declara la tabla de mapeo por código HTTP para
`GET /cleaning-tasks/{task_id}`:

| Estado | Clave i18n | Caso |
|---|---|---|
| `403` | `cleaning:detail.forbidden` | `READ_CLEANING_TASKS` ausente (no debería pasar con manager/owner) |
| `404` | `cleaning:detail.notFound` | tarea no existe o pertenece a otro tenant — **D12** documenta por qué el contrato abierto no bloquea este mapeador |
| `422` | `cleaning:detail.validation` | id malformado (UUID inválido) |
| otro | `cleaning:detail.error` | error genérico con reintento |

`CleaningTaskDetailView` consume el `state` que produce este mapeador (mismo patrón que
`IncidentDetailView` consume `mapIncidentsError`), y el componente no necesita distinguir
los tres casos no-`200` por código: el mapeador lo reduce a `loading | forbidden |
not-found | validation | error | success`, igual que la spec vigente de incidents.

Rejected: reutilizar `assign-error.ts` o `manage-error.ts` — sus tablas son de mutaciones
(403/404/409/422 específicos de asignar/crear/validar/cancelar); la lectura tiene un perfil
más estrecho y meter las claves de mutación aquí cruzaría los namespaces i18n.
Rejected: comprobar `error.message` — la regla 8 del proyecto lo prohíbe (es i18n del
backend, no del cliente).

### D6 — Resolución de vivienda por `usePropertyDirectory()` y de limpiadora por `useCleanerDirectory()`

**Chosen:** el bloque de identificación (D1, R3.1/R3.4) consume `usePropertyDirectory()`
y el bloque de asignación (R3.3) consume `useCleanerDirectory()`, ambos exportados por
`features/cleaning/hooks/use-cleaning-data.ts`. Los dos son `useQuery` independientes con
claves `cleaningKeys.properties(tenantId)` y `cleaningKeys.cleaners(tenantId)`, cacheados
por TanStack Query y compartidos con el listado — la página los instancia directamente
porque puede entrar por deep link sin que `CleaningView` esté montado, y los hooks
resuelven `tenantId` por sí mismos vía `useAuth()` (no se les pasa). La identificación
degrada a "vivienda no disponible" si el id no aparece en la página consultada,
exactamente la misma degradación que `cleaning-manager-view` R2.4 ya declara para el
listado.

Rejected: extender `CleaningTaskResponse` con `property_name`/`property_internal_code` —
rompe el «sin backend» del proposal (R3.1 lo verifica contra
`backend/openapi.json:1-3000`); rechazable por construcción.
Rejected: `GET /properties/{id}` por tarea — N+1, prohibido por D3 de
`cleaning-manager-view`.

### D7 — Los tres controles reusan los componentes del listado, sin variantes de detalle

**Chosen:** `CleaningTaskDetailView` monta `AssignCleanerControl`,
`ValidateCleaningControl` y `CancelCleaningTaskDialog` (`features/cleaning/components/*`)
directamente, sin envoltorios. La forma de los props es **exactamente la misma que el
listado ya usa** en `cleaning-task-row.tsx:222` (AssignCleanerControl) y siguientes — los
controles reciben el `taskId` más el estado de la mutación correspondiente, **NO** un
`CleaningTask` entero ni un `tenantId`. La integración con las mutaciones se hace del
mismo modo que en `cleaning-view.tsx`: el `tenantId` lo resuelve cada hook de mutación
(`useAuth()`), no se propaga por props. La región viva `role="status" aria-live="polite"`
vive en `CleaningTaskDetailView`, **una por página**, y las tres mutaciones la usan por
precedencia (mutación `isPending` > último `isError` > último `isSuccess`),
exactamente como `cleaning-manager-view` D11 + `cleaning-task-manage-web` D4. La
excepción declarada: el Sheet de cancelar conserva su `role="alert"` propio mientras
está abierto.

Rejected: variantes `*Detail` de los tres controles — duplica superficie y abre la puerta
a divergencia (R5.2 lo prohíbe explícitamente).
Rejected: controles nuevos en `components/detail/` — ya tienen tests y nombres; duplicar
rompe el precedente y abre tres sitios donde arreglar el mismo bug.

### D8 — Layout mobile-first en una columna, bloques apilados

**Chosen:** la página es un `<article>` con un grid `flex flex-col gap-4 p-4` y los bloques
apilados en el orden Encabezado → Identificación → Asignación → Programación → Validación →
Metadatos → Controles del manager → Enlaces de contexto. A 320 px no hay scroll horizontal;
a 360 px los controles y los enlaces mantienen objetivo táctil ≥ 44×44 px. La cabecera es
un `<div>` con el título `navigation:routes.cleaning-detail.title` y un enlace "Volver al
listado" a `/cleaning`, con la misma forma (`flex items-center gap-3`) que la cabecera de
`IncidentDetailView` (`features/incidents/components/detail/incident-detail-view.tsx:84-92`).
**No se aplica `sticky`/`position-sticky`** a la cabecera: el precedente de `IncidentDetailView`
no es sticky (sólo `<div className="flex items-center gap-3">`) y no se introduce aquí sin
una razón medida — la página de detalle tiene una altura razonable para un scroll completo,
y fijar la cabecera competiría con el shell superior por el viewport a 320 px.

Rejected: grid de dos columnas — al menos a 360 px las dos se vuelven ilegibles; rechazado
por R6.2 del proposal y por la regla «Responsive verificable» de
`steering/frontend.md`.
Rejected: tabs (Información / Controles) — los controles son tres botones y datos, no
secciones extensas; tabs sería sobre-ingeniería y obligaría a la región viva por tab (D7).

### D9 — Sin pestaña "Mensajes" ni galería de fotos — son las dos entradas que desbloquea

**Chosen:** la página no incluye pestaña de mensajería ni galería, **deliberadamente**.
`staff-messaging-manager-view` y `photo-storage-manager-view` son las dos entradas que el
proposal nombra como consumidores de esta página, y ninguna de las dos está entregada. Si
esta entrada las montara, asumiría el alcance de las dos (R-§Out of scope del proposal).
Cuando lleguen, **ellas** añadirán su bloque/sección al detalle —no al revés— y serán las
responsables de invalidar la query key del detalle cuando el sub-recurso cambie.

Rejected:预留 una pestaña vacía «Mensajes (próximamente)» — mete una affordance falsa en
el detalle y rompe la cuenta de `EmptyState`/`ErrorState` del panel del 2026-09-17.
Rejected: montar ya la pestaña como en `cleaner-app` — duplica el trabajo de
`staff-messaging-manager-view`, que es su dueña legítima.

### D10 — El Link desde el listado envuelve el `<h3>` con `internalCode + name` de la vivienda

**Chosen:** `cleaning-task-row.tsx:189-193` renderiza el `<h3>` con la forma
`${value.internalCode} · ${value.name}`. La sección 6 de `/sdd:tasks` lo envuelve en
`<Link href={`/cleaning/${task.id}`}>` y aplica las clases de hover/foco del mismo modo
que ya hace `incidents-view.tsx:139-145` para su `row.title`. El `Badge` de estado se queda
fuera del enlace para que el área clickable sea inequívoca.

Rejected: envolver la `Card` completa — `cleaner-task-list-row.tsx:49-88` lo hace así pero
su fila es una `<button>` accesible con sus propios handlers; aquí no hay handler, sólo
navegación, y envolver la `Card` haría clickable también el control de asignación y el
botón de validación, lo que viola `staff-messaging-web` R3 y duplica destinos de teclado.
Rejected: un icono de "ver detalle" aparte — mete un segundo affordance visual donde la fila
ya tiene `id` textual; el precedente de incidents y el patrón de detail-view son una sola
identidad textual clickable, no un icono añadido.

### D11 — `CleaningTask` se ensancha con `reservationId: string | null`

**Chosen:** `features/cleaning/data/dto.ts` añade `reservationId: string | null` a
`CleaningTask`, y `mapTask` en `http-cleaning-source.ts:59-72` extrae `value.reservation_id`
de `CleaningTaskResponse` (que ya lo publica). El campo es el único ausente de los seis
que el backend expone y R2-R6 consume: `accepted_at`, `checklist_template_id`,
`started_at`, `updated_at`, `validated_by_user_id` quedan fuera porque esta vista no los
pinta (R2 muestra `completed_at`/`validated_at` y el status por separado; los demás son
internos al ciclo de la limpiadora, no de la supervisión del manager). El test de
`http-cleaning-source.test.ts` extiende su fila para cubrir el nuevo mapeo.

Rejected: hacer una segunda petición a `GET /reservations/{reservation_id}` cuando la tarea
lo trae — duplica una llamada que ya está resuelta en otra pantalla
(`IncidentDetailView` lo hace así y la spec de incidents lo declara); aquí la tarea trae
el id, no el código, así que el catálogo de reservas se necesitaría igualmente y abriría
una segunda fuente de "reserva no disponible".
Rejected: omitir el campo y degradar a "sin reserva asociada" en todos los casos — perdería
la mitad del valor de R3.2 y R4.3, que es justamente mostrar/enlazar la reserva cuando
existe.

### D12 — El `404` se acepta por número en `detail-error.ts`, sin tocar el contrato

**Chosen:** el mapeador `detail-error.ts` declara `404` en su tabla aunque el operation
`get_cleaning_task_api_v1_cleaning_tasks__task_id__get` no lo incluya en su bloque
`responses` (`openapi.json:11357-11398`, sólo `200/401/403/422`). El backend lo devuelve en
la práctica (lo dice el `description`), pero el tipo generado por `api-contract-export`
(`openapi.d.ts:6162-6193`) no lo enumera. **El mapper intercepta por número**, no por clave
del sobre; el `apiClient` lanza `ApiError` con `status: 404` y el switch lo enruta a la
clave i18n correcta. Esta elección queda explícita y es la única vía de tener R1.2 sin
modificar el contrato del backend en esta entrada.

**El arreglo del contrato queda como candidato de `api-contract-export`** (regenerar
`backend/openapi.json` con `responses.404` añadido, lo que también arreglará `401` →
`responses.401` ya existente en el operation pero no emitido por el cliente generado, y
cualquier otro endpoint con el mismo gap). No es bloqueante aquí; sin este candidato, el
mapper sigue funcionando, y la deuda se documenta en el módulo `detail-error.ts` y en la
spec que escribirá `/sdd:archive`.

Rejected: añadir `404` al operation `responses` en esta entrada — extiende el alcance
más allá del frontend y abre una renegociación del contrato backend; el cambio es legítimo
pero no es de esta capacidad.
Rejected: tratar cualquier `4xx` distinto de `403`/`422` como `error` genérico — perdería
R1.2 ("mostrar `EmptyState` 'tarea no disponible'") y entregaría una experiencia peor que
la que la app móvil ya tiene (`cleaner-app` distingue `404` desde 2026-08-19).

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| App Router | **nuevo** `frontend/app/(workspace)/cleaning/[id]/page.tsx` | `generateMetadata()` con `routeMetadata("cleaning-detail")`; render de `CleaningTaskDetailView` con el `id` de `params` (misma forma que `frontend/app/(workspace)/incidents/[id]/page.tsx:1-19`) |
| Feature | **nuevo** `features/cleaning/components/detail/cleaning-task-detail-view.tsx` | Vista que compone los bloques, instancia `useCleaningTask`, `usePropertyDirectory`, `useCleanerDirectory`, y la región viva |
| Feature | **nuevos** `features/cleaning/components/detail/*-block.tsx` | Un componente por bloque del proposal (header, identifying, assigned, schedule, validation, metadata, context-links, manager-actions), cada uno con su test |
| Feature | **nuevo** `features/cleaning/hooks/use-cleaning-task.ts` | `useQuery` con `cleaningKeys.task(tenantId, taskId)`, `retry: false`, mapeador `detail-error.ts` |
| Feature | `features/cleaning/data/cleaning-source.ts`, `data/http/http-cleaning-source.ts` | Añadir `getTask(tenantId, taskId)`; **ensanchar `CleaningTask` con `reservationId: string \| null`** y mapear `value.reservation_id` en `mapTask` (D11: el DTO actual tiene 10 campos; esta entrada añade reservationId, el único de los seis campos ausentes que R2-R6 consume); tests del nuevo método y del campo nuevo en `http-cleaning-source.test.ts` |
| Feature | `features/cleaning/hooks/query-keys.ts` | Nuevo export `task(tenantId, taskId)` |
| Feature | `features/cleaning/hooks/use-assign-cleaning-task.ts`, `use-validate-cleaning-task.ts`, `use-cancel-cleaning-task.ts` | `onSettled` añade `queryClient.invalidateQueries({ queryKey: cleaningKeys.task(tenantId, taskId) })` cuando aplica |
| Feature | **nuevo** `features/cleaning/lib/detail-error.ts` | Tabla `keyForStatus(error)` con cinco entradas (403/404/422/error/loading), test propio |
| Feature | `features/cleaning/index.ts` | Exportar `CleaningTaskDetailView`, `useCleaningTask`, `cleaningKeys.task` |
| i18n | `frontend/locales/es/cleaning.json`, `frontend/locales/en/cleaning.json` | Namespace `detail.*` con los seis bloques, los enlaces, los `EmptyState`/`ErrorState`/`LoadingState`, las claves de `keyForStatus`; mirror de `incidents.json:detail.*` |
| i18n | `frontend/locales/es/navigation.json`, `frontend/locales/en/navigation.json` | Nuevas claves `routes.cleaning-detail.{title,description}` (R1.5, R6.1) |
| Navegación | `frontend/features/shell/navigation/route-registry.ts` | Entrada `cleaning-detail` con `pattern: "/cleaning/[id]"`, `profile: "workspace"`, `match: "exact"`, `breadcrumbKeys: crumbs("cleaning", "cleaning-detail")`, icono `Sparkles` |
| Cobertura | `frontend/app/route-coverage.test.ts` | Añadir `(workspace)/cleaning/[id]/page.tsx → cleaning-detail` a `REAL_PAGE_ROUTE_IDS` (R1.5, `route-surface-counts-have-an-authoritative-source`) |
| Listado | `frontend/features/cleaning/components/cleaning-task-row.tsx` | Envolver el `<h3>` que renderiza `internalCode + name` (`cleaning-task-row.tsx:189-193`) en un `<Link href={`/cleaning/${task.id}`}>` (D10). El detalle operativo del workspace no tiene precedente de fila-enlazable así: `incidents-view.tsx:139-145` linkea por `row.title` (no por identificador de vivienda) y `cleaner-task-list-row.tsx:49-88` envuelve la `Card` completa; ninguna de las dos por `internalCode + name` de la vivienda, que es la elección de D10. |
| Spec | `sdd/specs/cleaning-manager-task-detail.md` | La escribe `/sdd:archive` (no existe aún — fuera del alcance de esta entrada) |
| Docs | `docs/cleaning.md` | Sección «Detalle operativo del manager» referenciando `/cleaning/[id]`, sin duplicar lo que la spec declarará |

## Data & interfaces

**Sin cambios de backend, sin migración, sin regenerar el contrato.**

`backend/openapi.json` ya publica `GET /api/v1/cleaning-tasks/{task_id}` →
`CleaningTaskResponse`. Los códigos que el operation declara en `responses` son
`200/401/403/422`; el `404` lo devuelve en la práctica (lo dice el `description`) y D5 lo
mapea en consecuencia, aunque el contrato no lo enumera formalmente — ver **Risks &
mitigations** para la nota sobre el gap. `frontend/lib/api/generated/openapi.d.ts` no se
regenera.

Interfaz que esta entrada estrena:

```ts
// features/cleaning/data/cleaning-source.ts
interface CleaningDataSource {
  // ... (existentes)
  getTask(tenantId: string, taskId: string): Promise<CleaningTask>;
}

// features/cleaning/hooks/query-keys.ts
export const cleaningKeys = {
  // ... (existentes)
  task: (tenantId: string, taskId: string) =>
    ["cleaning", "task", tenantId, taskId] as const,
};

// features/cleaning/lib/detail-error.ts
export type CleaningDetailState =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "error"; refetch: () => void }
  | { kind: "success"; data: CleaningTask };

export function mapCleaningDetailError(query: UseQueryResult<...>): CleaningDetailState;
```

Las mutaciones que ya existen extienden su invalidación (sin firma nueva):

```ts
// use-assign-cleaning-task.ts (y análogas)
const taskKey = cleaningKeys.task(tenantId, taskId);
useMutation({
  // ...
  onSettled: () => {
    void queryClient.invalidateQueries({ queryKey: cleaningKeys.tasksPrefix(tenantId) });
    void queryClient.invalidateQueries({ queryKey: taskKey });
  },
});
```

## Risks & mitigations

- **El listado no enlaza al detalle hasta que la sección 6 modifique
  `cleaning-task-row.tsx`.** Mitigación: la tarea 6.1 del catálogo de tareas es
  *literalmente* añadir el `Link` en la fila, sin condicionales; está en el scope del
  change, no como mejora.
- **`usePropertyDirectory()` con `per_page: 100`** (ASSUMPTION de `cleaning-manager-view`
  D3): un tenant con más de 100 propiedades verá la vivienda como «no disponible» desde
  el detalle. Mitigación: la degradación es la misma que el listado, declarada en la
  spec, y el rango MVP (2 viviendas) hace que la `ASSUMPTION` no se materialice.
- **El `404` ambiguo de `GET /cleaning-tasks/{task_id}`** entre «no existe» y «de otro
  tenant» (precedente de backend, idéntico al de `incident-detail`): la pantalla no puede
  distinguirlos sin un `ErrorCode` nuevo, y la spec de cleaning ya lo declara así. La
  copia es la misma que `IncidentDetailView` usa para su `notFound` y no rompe ninguna
  invariante.
- **Las tres mutaciones invalidan claves adicionales en `onSettled`** — un `404`/`409` de
  la pantalla detalle (R5.4) necesita refetchear la query de la tarea. Mitigación: D5 ya
  distingue el `404` y dispara `refetch()` desde el botón de reintento del `ErrorState`,
  no en el `onSettled` (que invalida sin refetch).
- **Deep link a `/cleaning/[id]` sin haber pasado por `/cleaning`**: los dos catálogos
  se piden en paralelo a la tarea, así que la página no se queda esperando al directorio.
  Mitigación: R3.5 ya declara que los hooks de directorio se disparan en paralelo.
- **Una futura pestaña de mensajería o galería de fotos añadida por
  `staff-messaging-manager-view` o `photo-storage-manager-view`** debe invalidar
  `cleaningKeys.task(tenantId, taskId)` en su `onSettled` propio. Mitigación: se deja
  escrito explícitamente como nota para esas dos entradas, en su `design.md` cuando
  lleguen — no en esta.

## Open questions

Ninguna abierta que bloquee la implementación. Las dos que el proposal levantó y que este
diseño resuelve:

1. **Pestaña vs sección** para mensajes y fotos (las dos entradas que desbloquea esta):
   **sección o bloque añadido por cada entry dueña**, no por esta. La forma de la página
   (columna única apilada, D8) admite un bloque más sin cambio de layout. **Confirmado en
   R-§Out of scope del proposal**, no como decisión de diseño.
2. **Breadcrumb de la ruta**: `cleaning → cleaning-detail` (mismo shape que
   `incidents → incident-detail`). **Confirmado en D2**, no como ambigüedad.
