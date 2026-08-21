# Design: cleaning-manager-view

## Context

El frontend ya tiene la ruta `/cleaning` apuntada en el `route-registry.ts:146-156` con icono `Sparkles` y grupo `work`, pero su `page.tsx` (`frontend/app/(workspace)/cleaning/page.tsx:11`) renderiza un `RoutePlaceholder`; no existe `(workspace)/cleaning/[id]/page.tsx` ni descriptor de detalle en el registro. El backend ya expone `GET /api/v1/cleaning-tasks` y `GET /api/v1/cleaning-tasks/{task_id}` con sobre `CleaningTaskPageResponse = { data, page, per_page, total, total_pages }` (`frontend/lib/api/generated/openapi.d.ts:1011-1023`) y un `CleaningTaskResponse` de **dieciséis** campos sin `notes` (D13 de `specs/cleaning.md`, `openapi.d.ts:1026-1074`). El precedente más cercano es `incidents-web` (archivado 2026-08-20): misma forma — feature en `frontend/features/incidents/`, source HTTP con mapping snake→camel, hooks TanStack Query v5 con query keys tenant-scoped, error mapper discriminador de 6 variantes, view components con estados localizados, y `route-registry.test.ts` con la lista `PRD_24_SURFACES` que hay que extender. La diferencia operacional con `incidents-web` es que aquí el sobre **sí expone `total_pages`** y por tanto la derivación client-side que `incidents-web` documentó en su R2.5 no aplica.

El código que se reutiliza sin modificar: `frontend/lib/query/query-keys.ts` (`tenantScopedKey`), `frontend/lib/api/retry-policy.ts` (`retryPolicy`), `frontend/lib/api/authenticated-client.ts` (`createAuthenticatedClients`), `frontend/features/dashboard/lib/format.ts` (`formatDateTime`/`formatDate`), `frontend/features/shell/navigation/route-registry.ts` (`keysFor`, `crumbs`).

## Decisions

### D1 — Módulo FE nuevo `frontend/features/cleaning/`

**Chosen:** crear un feature module paralelo a `frontend/features/incidents/`, con la misma estructura: `data/{dto.ts, http/http-cleaning-tasks-source.ts, index.ts}`, `hooks/{query-keys.ts, use-cleaning-tasks.ts}`, `lib/error-mapping.ts`, `components/list/{cleaning-tasks-view.tsx, cleaning-tasks-filters.tsx}`, `components/detail/{cleaning-task-detail-view.tsx, cleaning-task-detail-sections.tsx}`, `index.ts` (barrel). Replica exactamente la silueta de `incidents`, que es el precedente más reciente y más cercano.

Rejected: meter el código en `frontend/features/dashboard/` porque `/cleaning` no es una vista agregada sino una lista primaria de un recurso. Rejected: no crear el módulo y vivir dentro de `frontend/app/(workspace)/cleaning/` directamente, porque rompe la separación ruta (App Router) ↔ dominio (features) que el resto del workspace respeta.

### D2 — DTOs con separación list-row ↔ detail (16 ↔ 7)

**Chosen:** `CleaningTaskSummaryDto` con siete campos pensados para una fila de tabla — `id`, `status`, `validation_status`, `property_id`, `scheduled_start`, `scheduled_end`, `assigned_cleaner_id`— y `CleaningTaskDetailDto` con los **dieciséis** campos de `CleaningTaskResponse` en `camelCase`. El mapping snake→camel vive **solo** en `HttpCleaningTasksSource`; los componentes y los hooks nunca tocan `components["schemas"]`.

Rejected: servir el `IncidentResponse` completo como `IncidentSummaryDto` también, que era el patrón temprano antes de que `incidents-web` lo separara (D3/D5 de su design). Rejected: derivar un tipo derivado computado del sobre (`IncidentList` con `items`, `total`, `page`, `perPage`, `lastPage` derivado). Aquí el sobre ya tiene `total_pages`, así que el derivado se llama `totalPages` y se queda tal cual llega del backend — sin `lastPage` calculado en el cliente (precedente directo de `incidents-web` D5 sobre el mismo punto).

### D3 — Sobre `CleaningTaskList` con `data` (no `items`) y `totalPages` del backend

**Chosen:** `CleaningTaskList = { data: CleaningTaskSummaryDto[], total: number, page: number, perPage: number, totalPages: number }`. El `HttpCleaningTasksSource` mapea `CleaningTaskPageResponse.data` (clave del sobre) a `data`, y `total_pages` (snake) a `totalPages` (camel). Los tests del source **deben** assertar sobre la forma exacta del sobre recibida del cliente y sobre la forma exacta que sale del mapping (R5.6 de la proposal).

Rejected: normalizar el sobre a `{items, ...}` en el cliente para coincidir con `incidents-web` (que tiene `{items, total, page, per_page}`). Lo evitamos porque **son contratos distintos** entre módulos del backend y normalizar en el cliente introduce un mapeo que se rompe si uno de los dos cambia.

### D4 — Query keys tenant-scoped vía `tenantScopedKey`

**Chosen:** `cleaningTasksKeys = { list(tenantId, filters), detail(tenantId, taskId) }`, ambos construidos con `tenantScopedKey(tenantId, "cleaning-list", filters)` y `tenantScopedKey(tenantId, "cleaning-detail", taskId)`. `filters` se pasa como objeto en orden estable (`status`, `page`, `perPage`) — el caller del hook es responsable de mantener esa estabilidad, y la página (controlada) lo hace en `buildNext` (mismo patrón que `IncidentsFilters` de `incidents-web`).

Rejected: serializar el filtro con `JSON.stringify`. Rompe el cache de TanStack Query ante la misma forma lógica y se documentó como antipatrón en `incidents-web` R2.7.

### D5 — Hooks `useCleaningTasks` (lista) y `useCleaningTask` (detalle)

**Chosen:** nombres `useCleaningTasks` y `useCleaningTask` (paralelo a `useIncidents`/`useIncident`). El tenant se obtiene con un `useTenantId()` interno que lanza si no hay sesión — mismo helper que `use-incidents.ts:31-37`. `retry: retryPolicy` reusado. **No** se introduce un `useCleaningTasksList` para evitar colisión semántica con `useCleaningTasks`.

Rejected: nombres `useCleaningTasksList`/`useCleaningTaskDetail` por considerarlos más explícitos — la asimetría con el resto de hooks del workspace pesó más (todas las features usan `<recurso>s` para lista).

### D6 — Mapping de color semántico (R3.4)

**Chosen:** paleta exacta por valor de cada enum, replicando el patrón completo de `frontend/features/dashboard/components/property-card.tsx:21-25` (con variantes `dark:`):

| Enum | Valor | Clases Tailwind |
|---|---|---|
| `CleaningValidationStatus` | `PENDING` | `bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-950 dark:text-gray-200 dark:border-gray-800` |
| `CleaningValidationStatus` | `PASSED` | `bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800` |
| `CleaningValidationStatus` | `FAILED` | `bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800` |
| `CleaningValidationStatus` | `WAIVED` | `bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800` |
| `CleaningTaskStatus` | `CREATED` | gray (mismas clases que PENDING) |
| `CleaningTaskStatus` | `ASSIGNED` | `bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800` |
| `CleaningTaskStatus` | `ACCEPTED` | blue (mismas clases que ASSIGNED) |
| `CleaningTaskStatus` | `REJECTED` | red (mismas clases que FAILED) |
| `CleaningTaskStatus` | `IN_PROGRESS` | amber (mismas clases que WAIVED) |
| `CleaningTaskStatus` | `PENDING_REVIEW` | amber |
| `CleaningTaskStatus` | `COMPLETED` | emerald (mismas clases que PASSED) |
| `CleaningTaskStatus` | `FAILED` | red |
| `CleaningTaskStatus` | `CANCELLED` | gray (mismas clases que PENDING — terminal-cancelled, neutral) |

El test (R5.5) verifica el mapping **mediante tests parametrizados explícitos** que enuncian, valor por valor, la **clase semántica esperada**: para cada enum (`CleaningValidationStatus` ×4, `CleaningTaskStatus` ×9), una tabla en el test fija valor → nombre de rol semántico (`pass` / `danger` / `warning` / `neutral` / `info` / `success`), y el assert compara el rol que devuelve `cleaningValidationStatusClass(value)` contra el rol declarado en la tabla — **no** contra la cadena cruda de clases Tailwind. **Adicionalmente**, un assert de no-colisión dentro de cada enum exige que dos valores distintos que tienen rol distinto devuelvan clases distintas (con tolerancia documentada para `PENDING`/`CANCELLED`/`CREATED` que comparten el rol `neutral`, y para `ASSIGNED`/`ACCEPTED` que comparten `info`). El snapshot del mapping puede existir como complemento opcional para detectar diffs accidentales, pero **no** es la fuente principal de evidencia: la primaria es la tabla explícita valor → rol, que sobrevive a un cambio cosmético de tokens siempre que el rol semántico no cambie. Esto cumple R3.4 ("mismo sistema visual") sin atar la propuesta a tokens concretos — la tabla anterior los fija en esta entrada como **decisión**, y los tests enuncian el mapping por rol semántico, que es lo que la propuesta promete.

Rejected: snapshot como fuente principal — congela tokens concretos y rompe ante cualquier reordenamiento cosmético sin que el cambio sea realmente semántico. Rejected: reusar `SEVERITY_COLOR` literal de `incidents-web` (sin variantes `dark:`, sin `border`). Inconsistente con `property-card.tsx`, que es el sistema visual del workspace. Rejected: congelar solo `gray`/`red` y delegar el resto a `/sdd:tasks`: convertiría la propuesta en ejecutable solo cuando el implementador decida tokens, y la decisión ya se documentó arriba como obligatoria.

### D7 — Formato de fechas vía `formatDateTime` ya existente

**Chosen:** importar `formatDateTime` de `frontend/features/dashboard/lib/format.ts` (que ya da `Intl.DateTimeFormat` con `dateStyle: "medium", timeStyle: "short"`) para `scheduled_start`, `scheduled_end`, `accepted_at`, `started_at`, `completed_at`, `validated_at`, `created_at`, `updated_at`. **No** se añade un nuevo helper de fechas.

Rejected: añadir `date-fns` (no está en el stack — el grep sobre `package.json` y los features devuelve cero usos; `dashboard/lib/format.ts` resuelve con `Intl` puro). Rejected: duplicar `formatDateTime` en `features/cleaning/lib/`. Rompe DRY sin motivo.

### D8 — Etiqueta de "snapshot del plan" (R3.3)

**Chosen:** `scheduled_start` se renderiza con etiqueta **"Inicio previsto"** (ES) / **"Scheduled start"** (EN); `scheduled_end` con **"Fin previsto"** / **"Scheduled end"**. Una nota localizada corta debajo del par aclara: «Fecha del plan original; no se actualiza en lecturas posteriores» / «Snapshot of the original plan; not refreshed on subsequent reads». La nota sale de `cleaning.json` (`schedule.note`) y aparece **una sola vez**, debajo del par — no se duplica por campo.

Rejected: tooltip en cada campo. Inconsistente con la nota de `assigned_cleaner_id` (R3.6) que se pidió inline. Rejected: prefijo "(plan)" en el valor. Rompe la separación etiqueta↔valor del resto del workspace.

### D9 — `null` como `—` con constante en locales

**Chosen:** los campos opcionales (`accepted_at`, `started_at`, `completed_at`, `validated_at`, `assigned_cleaner_id`, `scheduled_start`, `scheduled_end`, `reservation_id`) se renderizan con `value ?? t("fields.null")`, donde `t("fields.null")` devuelve `"—"` en ambos locales. La constante vive en `cleaning.json` (`fields.null`) en vez de estar hardcodeada en el JSX — un cambio futuro de glifo (por ejemplo a `"·"` o `"n/d"`) no requiere tocar código.

Rejected: `value ?? "—"` directo en JSX. Rompe R5.2 (todo string de UI en locales).

### D10 — Sección secundaria de `assigned_cleaner_id` (R3.6)

**Chosen:** la fila se renderiza en un componente `<DetailAssignedCleanerBlock>` separado del bloque principal (`DetailIdentifyingBlock`/`DetailHeader`/`DetailScheduleBlock`), bajo la sección "Asignación" / "Assignment". El UUID va sin tooltip de copia, sin botón de copiar y sin icono específico — solo el valor pelado y, debajo, la nota localizada «El id no se resuelve a nombre en esta versión» / «This id is not resolved to a name in this version». La nota aparece una sola vez en esta sección; no se duplica.

Rejected: tooltip al pasar el ratón sobre el UUID. Oculta la limitación que la proposal exige documentar (R3.6). Rejected: render inline en el bloque de identificación principal. La proposal lo prohíbe explícitamente.

### D11 — `checklist_template_id` sin enlace (R3.8)

**Chosen:** render como texto plano (UUID), precedido por la etiqueta "Plantilla" / "Template". Sin `<Link>`. Si en una entrada futura el contrato expone un endpoint de lectura de plantilla por id, ese cambio retrofitará el enlace.

Rejected: dejar el campo fuera del detalle. Lo quita del shape visible al manager y haría falta rehacerlo. Rejected: `<a href>` sin endpoint. Enlace roto, peor que nada.

### D12 — Paginación prev/next usando `totalPages` del backend

**Chosen:** controles «Anterior» y «Siguiente», deshabilitados en los extremos con `page === 1` y `page === totalPages` respectivamente. **Sin** selector numérico de página: el sobre ya da `totalPages` y se renderiza como «Página X de Y», pero el cambio entre páginas explícitas (no 1↔last) no entra en `size: S` (el precedente de `reservations-web` R2.5 y `incidents-web` R2.5 ya documentó esa decisión).

Rejected: selector numérico. Sale de `size: S` y no aporta a la primera lectura.

### D13 — Descriptor de ruta `cleaning-detail` paralelo a `incident-detail`

**Chosen:** añadir a `frontend/features/shell/navigation/route-registry.ts` el descriptor `{ id: "cleaning-detail", pattern: "/cleaning/[id]", ...keysFor("cleaning-detail"), breadcrumbKeys: crumbs("cleaning", "cleaning-detail"), icon: "Sparkles", profile: "workspace", match: "exact" }`, ubicado **inmediatamente después** del descriptor `cleaning` existente (líneas 146-156) para que `incidents`/`incidents-detail`/`conversations`/`approvals` no se reagrupen. Sin `href`, sin `navigationGroup` (igual que `incident-detail`/`reservation-detail`/`property-detail`).

Rejected: reagrupar el bloque `work` con la posición de `cleaning-detail` entre `cleaning` e `incidents`. Reabriría el diff de `route-registry.test.ts` (que ordena alfabéticamente) sin valor.

### D14 — `PRD_24_SURFACES` extendido con `/cleaning/[id]`

**Chosen:** insertar `"/cleaning/[id]"` en `frontend/features/shell/navigation/route-registry.test.ts:10-33` después de `"/cleaning"` (línea 19), preservando el orden por superficie y dejando el `.sort()` del final intacto. El test ya cubre que `patterns` iguala `PRD_24_SURFACES` (líneas 61-64), así que extender la lista es la única edición necesaria para mantener la cobertura.

Rejected: dejar `"/cleaning"` y omitir el detalle. El test `covers exactly the PRD §24 surfaces (no more, no less)` fallaría.

### D15 — `cleaning.json` nuevo en `frontend/locales/{es,en}/`

**Chosen:** crear `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` con la estructura:

```jsonc
{
  "status": { /* 9 CleaningTaskStatus → etiqueta localizada */ },
  "validation_status": { /* 4 CleaningValidationStatus → etiqueta */ },
  "filters": { "status": "...", "clearFilters": "..." },
  "fields": {
    "id": "...",
    "property_id": "...",
    "reservation_id": "...",
    "checklist_template_id": "Plantilla",
    "status": "...",
    "validation_status": "...",
    "assigned_cleaner_id": "...",
    "scheduled_start": "Inicio previsto",
    "scheduled_end": "Fin previsto",
    "accepted_at": "Aceptada",
    "started_at": "Iniciada",
    "completed_at": "Cerrada",
    "validated_at": "Validada",
    "validated_by_user_id": "Validada por",
    "created_at": "Creada",
    "updated_at": "Actualizada",
    "null": "—",
    "loading": "...",
    "error": "...",
    "empty": "...",
    "notFound": "...",
    "validation": "...",
    "backToList": "Volver al listado",
    "previousPage": "Anterior",
    "nextPage": "Siguiente",
    "pageXofY": "Página {{page}} de {{total}}"
  },
  "sections": {
    "identifying": "Identificación",
    "schedule": "Planificación",
    "assignment": "Asignación",
    "validation": "Validación",
    "metadata": "Metadatos"
  },
  "schedule": { "note": "Fecha del plan original; no se actualiza en lecturas posteriores." },
  "assignment": { "note": "El id no se resuelve a nombre en esta versión." }
}
```

La estructura replica `frontend/locales/es/incidents.json` (ya verificado en formato y profundidad) con dos adiciones: las claves de sección (`sections.*`) para los `<h2>` de cada bloque del detalle, y las dos notas (`schedule.note`, `assignment.note`) que viven separadas de `fields.*` para no contaminar el namespace de campos.

Rejected: poner las notas dentro de `fields.*`. Contamina la separación campo↔metadata y dificulta i18n (las notas son prosa, los campos son etiquetas concisas).

### D16 — Barrel `features/cleaning/index.ts`

**Chosen:** replicar `frontend/features/incidents/index.ts`: re-export de `CleaningTasksView`, `CleaningTasksFilters`, `CleaningTaskDetailView`, `useCleaningTasks`, `useCleaningTask`, `cleaningTasksKeys`, `mapCleaningTasksError`, `getCleaningTasksDataSource`, `type * from "./data"`. Una sola importación `@/features/cleaning` trae toda la feature — el `page.tsx` del App Router importa solo `CleaningTasksView` y `CleaningTaskDetailView`.

Rejected: barrel por capa (uno para data, otro para components). Sobre-ingeniería para esta feature.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Feature module (nuevo) | `frontend/features/cleaning/data/dto.ts` | **NEW**. Tipos `CleaningTaskStatus`, `CleaningValidationStatus`, `CleaningTaskSummaryDto`, `CleaningTaskDetailDto`, `CleaningTaskList`, `CleaningFilters`. |
| Feature module (nuevo) | `frontend/features/cleaning/data/http/http-cleaning-tasks-source.ts` | **NEW**. `HttpCleaningTasksSource` con `listCleaningTasks`, `getCleaningTask`; mapping snake→camel. |
| Feature module (nuevo) | `frontend/features/cleaning/data/http/http-cleaning-tasks-source.test.ts` | **NEW**. Tests del mapping y del shape del sobre recibido. |
| Feature module (nuevo) | `frontend/features/cleaning/data/index.ts` | **NEW**. `getCleaningTasksDataSource()` (composition point) + `export type *`. |
| Feature module (nuevo) | `frontend/features/cleaning/hooks/query-keys.ts` | **NEW**. `cleaningTasksKeys = { list, detail }`. |
| Feature module (nuevo) | `frontend/features/cleaning/hooks/use-cleaning-tasks.ts` | **NEW**. `useCleaningTasks`, `useCleaningTask`, `useTenantId`. |
| Feature module (nuevo) | `frontend/features/cleaning/hooks/use-cleaning-tasks.test.tsx` | **NEW**. Tests de query key stability y wiring del `retryPolicy`. |
| Feature module (nuevo) | `frontend/features/cleaning/lib/error-mapping.ts` | **NEW**. `CleaningTasksErrorState<T>` + `mapCleaningTasksError`. |
| Feature module (nuevo) | `frontend/features/cleaning/lib/error-mapping.test.ts` | **NEW**. Tests del discriminador. |
| Feature module (nuevo) | `frontend/features/cleaning/lib/status-color.ts` | **NEW**. `STATUS_COLOR` (9 valores), `VALIDATION_STATUS_COLOR` (4 valores), `cleaningStatusClass(status)` y `cleaningValidationStatusClass(status)`. Tabla exacta de D6. |
| Feature module (nuevo) | `frontend/features/cleaning/lib/status-color.test.ts` | **NEW**. Tests parametrizados: para cada enum, una tabla explícita valor → rol semántico esperado (`pass` / `danger` / `warning` / `neutral` / `info` / `success`); assert principal compara el rol devuelto por `cleaningValidationStatusClass(value)` / `cleaningStatusClass(value)` contra el de la tabla. Assert secundario de no-colisión entre valores con rol distinto del mismo enum (con tolerancia documentada para los pares `PENDING`/`CANCELLED`/`CREATED` y `ASSIGNED`/`ACCEPTED`). Snapshot opcional como detector de diffs cosméticos, no como fuente primaria. |
| Feature module (nuevo) | `frontend/features/cleaning/components/list/cleaning-tasks-filters.tsx` | **NEW**. Dropdown de status + botón "Limpiar filtros". |
| Feature module (nuevo) | `frontend/features/cleaning/components/list/cleaning-tasks-filters.test.tsx` | **NEW**. |
| Feature module (nuevo) | `frontend/features/cleaning/components/list/cleaning-tasks-view.tsx` | **NEW**. Lista paginada con estados loading/empty/error/data. |
| Feature module (nuevo) | `frontend/features/cleaning/components/list/cleaning-tasks-view.test.tsx` | **NEW**. |
| Feature module (nuevo) | `frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx` | **NEW**. Compone las secciones. |
| Feature module (nuevo) | `frontend/features/cleaning/components/detail/cleaning-task-detail-view.test.tsx` | **NEW**. |
| Feature module (nuevo) | `frontend/features/cleaning/components/detail/cleaning-task-detail-sections.tsx` | **NEW**. `<DetailHeader>`, `<DetailIdentifyingBlock>`, `<DetailScheduleBlock>`, `<DetailAssignedCleanerBlock>`, `<DetailValidationBlock>`, `<DetailMetadataBlock>`. |
| Feature module (nuevo) | `frontend/features/cleaning/index.ts` | **NEW**. Barrel. |
| App Router | `frontend/app/(workspace)/cleaning/page.tsx` | **MODIFIED**. Sustituye `RoutePlaceholder` por `<CleaningTasksView />`. |
| App Router | `frontend/app/(workspace)/cleaning/[id]/page.tsx` | **NEW**. `generateMetadata` + `<CleaningTaskDetailView taskId={params.id} />`. |
| Shell | `frontend/features/shell/navigation/route-registry.ts` | **MODIFIED**. Añade descriptor `cleaning-detail` después del bloque `cleaning` (línea 156). |
| Shell | `frontend/features/shell/navigation/route-registry.test.ts` | **MODIFIED**. Inserta `"/cleaning/[id]"` en `PRD_24_SURFACES` (línea 19). |
| i18n — navigation | `frontend/locales/es/navigation.json` | **MODIFIED**. Añade `routes.cleaning-detail.{title,description}`. |
| i18n — navigation | `frontend/locales/en/navigation.json` | **MODIFIED**. Idem. |
| i18n — cleaning (nuevo) | `frontend/locales/es/cleaning.json` | **NEW**. Estructura D16. |
| i18n — cleaning (nuevo) | `frontend/locales/en/cleaning.json` | **NEW**. Idem. |

## Data & interfaces

**Schema changes:** ninguna. El backend ya publica `CleaningTaskResponse` (16 campos) y `CleaningTaskPageResponse` (`{ data, page, per_page, total, total_pages }`) en `backend/openapi.json`. Este change no toca `backend/`, no regenera `backend/openapi.json`, y no regenera `frontend/lib/api/generated/openapi.d.ts` (el contrato no cambia).

**API contracts consumidas:**
- `GET /api/v1/cleaning-tasks?status=&page=&per_page=` → `CleaningTaskPageResponse`.
- `GET /api/v1/cleaning-tasks/{task_id}` → `CleaningTaskResponse`.

**New env vars / config:** ninguna.

**New types exported desde `frontend/features/cleaning`:**
- `CleaningTaskStatus`, `CleaningValidationStatus` (re-exports del openapi).
- `CleaningTaskSummaryDto`, `CleaningTaskDetailDto`, `CleaningTaskList`, `CleaningFilters`.
- `CleaningTasksErrorState<T>`, `STATUS_COLOR`, `VALIDATION_STATUS_COLOR`.
- `cleaningStatusClass(status)`, `cleaningValidationStatusClass(status)` — devuelven el nombre del **rol semántico** (`'pass' | 'danger' | 'warning' | 'neutral' | 'info' | 'success'`), no las clases Tailwind. Los componentes resuelven el rol a clases vía un mapa interno en `lib/status-color.ts`; los tests enuncian el rol esperado, no la clase cruda (D6).

## Resolved decisions

Las cinco preguntas abiertas quedaron resueltas durante la revisión del gate:

- **Q1 (nombres de hooks)** → `useCleaningTasks` / `useCleaningTask` (D5 tal cual).
- **Q2 (nota del snapshot)** → inline debajo del par `scheduled_start` / `scheduled_end` (D8 tal cual).
- **Q3 (layout del detalle)** → `DetailIdentifyingBlock` contiene `id`, `property_id`, `reservation_id`; `DetailMetadataBlock` contiene los timestamps (`accepted_at`, `started_at`, `completed_at`, `validated_at`, `created_at`, `updated_at`, `validated_by_user_id`); `assigned_cleaner_id` **no** entra en ninguno de los dos — vive en su propio `DetailAssignedCleanerBlock` (D10 ya lo decía). El `checklist_template_id` entra en `DetailMetadataBlock` como texto plano (D11).
- **Q4 (test de status-color)** → tests parametrizados explícitos por mapping `valor → rol semántico`, con no-colisión secundaria. Snapshot opcional como detector de diffs cosméticos, no como fuente primaria (D6 actualizado, entrada correspondiente en Changes y en Risks).
- **Q5 (ubicación de `status-color.ts`)** → `frontend/features/cleaning/lib/` (D16 tal cual). La promoción a `features/shell/` queda como entrada propia cuando otra feature lo necesite.

No quedan preguntas abiertas al cierre de este phase.

## Risks & mitigations

1. **Regresión del shape del sobre (R2.3)**: si el backend añade `items` o renombra `data` en una release futura sin actualizar el FE, el mapping rompe en silencio. **Mitigación**: el test `http-cleaning-tasks-source.test.ts` asserta que el sobre recibido contiene `data: [...]` (no `items`), y `use-cleaning-tasks.test.tsx` cubre la query key. Si el contrato cambia, el workflow `api-contract` del CI rompe antes de mergear.

2. **Colisión de tokens semánticos entre `cleaning` e `incidents`**: si dos features usan el mismo color para valores distintos (por ejemplo `PASSED` verde y `RESOLVED` rojo vs verde), el sistema visual se contradice. **Mitigación**: `status-color.ts` centraliza la tabla por enum; `cleaningValidationStatusClass` / `cleaningStatusClass` exponen el rol semántico (`pass`/`danger`/`warning`/`neutral`/`info`/`success`), y el test `status-color.test.ts` verifica el mapping por rol parametrizado (D6) — no contra tokens crudos — así que dos features con el mismo rol semántico pueden compartir paleta sin que el test diga nada, y un cambio cosmético de tokens dentro de un rol no rompe la suite. Tests cross-feature no entran aquí (no es problema de este change), pero se documenta la convención para que el siguiente PR la herede.

3. **`total_pages` cambia a derivado client-side en una release futura**: si el backend decide mover la responsabilidad, el `totalPages` del mapping queda `undefined`. **Mitigación**: el componente trata `totalPages` como `number` y el TS del openapi lo tipa. Si llega `undefined`, el caller verá el control "Siguiente" siempre habilitado — UX rota pero no rompe runtime. Es un escenario que el propio `incidents-web` ya vivió (R2.5) y la mitigación allí fue la misma: aceptar el campo del backend y derivar solo si falta.

4. **Doble render del `RoutePlaceholder` durante la transición**: si `cleaning/page.tsx` se commitea antes que el barrel `features/cleaning/index.ts`, el build falla. **Mitigación**: el orden de los commits y del PR importa; se sube todo en un solo PR (precedente de `incidents-web`).

5. **i18n incompleto**: si una clave de `cleaning.json` no se traduce a `en` o viceversa, `react-i18next` cae al idioma por defecto. **Mitigación**: los dos `cleaning.json` se generan en pares, con las mismas claves en el mismo orden; el script `steering/frontend.md` (regla i18n) ya exige cobertura simétrica.

## Open questions

Ninguna. Ver **Resolved decisions** arriba — las cinco preguntas abiertas se cerraron durante la revisión del gate sin ampliar scope.