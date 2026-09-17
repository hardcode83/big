# Tasks: cleaning-manager-task-detail

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     the task item, not only the checkbox line. -->

## 1. DTO y frontera de datos: `reservationId` + `getTask` <!-- panel: PASS 2026-09-17 receipt:17dc36d7 -->

- [x] 1.1 `frontend/features/cleaning/data/dto.ts` — añadir `reservationId: string | null`
      a `CleaningTask` (D11: es el único de los seis campos ausentes de
      `CleaningTaskResponse` que R2-R6 consume). [R3.2, R4.3]
- [x] 1.2 `frontend/features/cleaning/data/http/http-cleaning-source.ts` — añadir
      `getTask(tenantId, taskId)` (`GET /api/v1/cleaning-tasks/{taskId}`,
      `params: { taskId }`, devuelve `mapTask`); extender `mapTask` con
      `reservation_id→reservationId`; ampliar `http-cleaning-source.test.ts` cubriendo el
      nuevo método (cuerpo de la petición, respuesta mapeada) y el campo nuevo de
      `mapTask`. [R1.1, R3.2]
- [x] 1.3 `frontend/features/cleaning/data/cleaning-source.ts` — declarar `getTask` en la
      interfaz `CleaningDataSource`. [R1.1]

## 2. Cache y hooks: `cleaningKeys.task`, `useCleaningTask`, invalidación cruzada <!-- panel: PASS 2026-09-17 receipt:580a3413 -->

- [x] 2.1 `frontend/features/cleaning/hooks/query-keys.ts` — añadir `task: (tenantId,
      taskId): QueryKey => tenantScopedKey(tenantId, "cleaning-task", taskId)` (D4,
      invariante del módulo: "every key begins with `['tenant', tenantId, ...]`"). Ampliar
      `query-keys.test.ts` con un test que verifique que `cleaningKeys.task(tenantId,
      taskId)` empieza por `["tenant", tenantId, "cleaning-task"]`. [R1.1]
- [x] 2.2 **nuevo** `frontend/features/cleaning/hooks/use-cleaning-task.ts` —
      `useQuery({ queryKey: cleaningKeys.task(tenantId, taskId), queryFn: () =>
      getCleaningDataSource().getTask(tenantId, taskId), enabled: !!taskId, retry: false })`,
      con `tenantId` resuelto por `useAuth()` (mismo patrón que `useCleaningTasks` en
      `use-cleaning-data.ts`). Con `use-cleaning-task.test.tsx`: cada rama
      `loading/success/error/forbidden/not-found/validation` (D5/D12), `retry: false`,
      `enabled: false` cuando `taskId` es vacío. [R1.1, R1.3, R1.4]
- [x] 2.3 `frontend/features/cleaning/hooks/use-assign-cleaning-task.ts`,
      `use-validate-cleaning-task.ts`, `use-cancel-cleaning-task.ts` — añadir a su
      `onSettled` (en éxito y fallo) `queryClient.invalidateQueries({ queryKey:
      cleaningKeys.task(tenantId, taskId) })` para que las mutaciones refresquen el detalle
      si el usuario lo abrió en otra pestaña (D4). Ampliar los tres tests existentes con
      un caso que verifique la invalidación adicional. [R5.3]

## 3. Mapeador de error: `detail-error.ts` (D5/D12) <!-- panel: PASS 2026-09-17 receipt:4c974b2e -->

- [x] 3.1 **nuevo** `frontend/features/cleaning/lib/detail-error.ts` — declarar la
      union `CleaningDetailState` (`loading | forbidden | not-found | validation | error |
      success`) y `mapCleaningDetailError(query, refetch)` (mismo patrón que
      `mapIncidentsError`: por código HTTP, switch exhaustivo, devuelve `{ kind, data?
      }`). Tabla interna: 403 → `cleaning:detail.forbidden`, 404 → `cleaning:detail.notFound`
      (D12: el `apiClient` lanza `ApiError` con `status: 404` aunque el contrato generado
      no lo enumere), 422 → `cleaning:detail.validation`, otro → `cleaning:detail.error`
      con `refetch`. Con `detail-error.test.ts`: cada fila de la tabla, casos `loading`
      (sin `error`), `success` (con `data`), `forbidden` sin superposición con `not-found`,
      y `error` con `refetch` que reintenta la consulta. [R1.2, R1.4]

## 4. Componentes de detalle: bloques de lectura + vista que los compone <!-- panel: PASS 2026-09-17 receipt:930228a4 -->

- [x] 4.1 **nuevo** `frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`
      — vista que orquesta `useCleaningTask(taskId)`, `usePropertyDirectory()` y
      `useCleanerDirectory()`, aplica `mapCleaningDetailError`, monta los bloques del
      proposal R2/R3/R4/R5 en una `<article className="flex flex-col gap-4 p-4">` (D1, D8),
      con cabecera `<div className="flex items-center gap-3">` y enlace "Volver al listado"
      a `/cleaning` (D8, sin `sticky`), y región viva `role="status" aria-live="polite"`
      alimentada por las tres mutaciones (D7, R5.5). Con
      `cleaning-task-detail-view.test.tsx`: cada `kind` del estado (loading / forbidden /
      not-found / validation / error / success), composición de bloques, hrefs de los
      enlaces de contexto según permiso. [R1.1, R1.2, R1.3, R1.4, R4.1, R4.2, R4.3, R5.5,
      R6.3]
- [x] 4.2 **nuevos** `frontend/features/cleaning/components/detail/*-block.tsx` —
      descomponer la vista en bloques siguiendo el precedente de
      `features/incidents/components/detail/incident-detail-sections.tsx`. Concretamente:
      `detail-header-block.tsx` (R2: status traducido + coloreado vía `STATUS_BADGE_CLASS`
      ya existente, `validation_status`, ventana `scheduled_start`–`scheduled_end`,
      `completedAt`/`validatedAt` condicional al pintar de D7 de `cleaning-task-manage-web`),
      `detail-identifying-block.tsx` (R3.1/R3.2/R3.4: `internalCode + name` de la vivienda
      vía `usePropertyDirectory()`, código de reserva o degradación si `reservationId` es
      `null` o no visible), `detail-assigned-cleaner-block.tsx` (R3.3/R3.4: nombre de la
      limpiadora desde `useCleanerDirectory()` con la misma degradación de tres casos que
      `cleaning-manager-view` D5 — sin asignar / resolviendo / no disponible),
      `detail-context-links-block.tsx` (R4.1/R4.2/R4.3: "Ver vivienda" si
      `READ_PROPERTIES`, "Ver reserva" si `READ_RESERVATIONS` y `reservationId !== null`,
      "Volver al listado" siempre),
      `detail-manager-actions-block.tsx` (R5.1/R5.2/R5.3: `useHasPermission("MANAGE_CLEANING_TASKS")`
      gate; si pasa, monta `AssignCleanerControl` + `ValidateCleaningControl` +
      `CancelCleaningTaskDialog` con los props exactos que ya usan en
      `cleaning-task-row.tsx:222` — **NO** variantes `*Detail`). Cada bloque con su test,
      claves i18n de `cleaning:detail.*` (sección 7). [R2.1, R2.2, R2.3, R3.1, R3.2,
      R3.3, R3.4, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3]
- [x] 4.3 `frontend/features/cleaning/index.ts` — exportar `CleaningTaskDetailView`,
      `useCleaningTask`, `cleaningKeys.task`, `mapCleaningDetailError`,
      `type CleaningDetailState`. [R1.1]

## 5. Ruta registrada, página real y enlace desde el listado <!-- hard -->

- [ ] 5.1 `frontend/features/shell/navigation/route-registry.ts` — añadir la entrada
      `cleaning-detail` con `pattern: "/cleaning/[id]"`, `profile: "workspace"`, `match:
      "exact"`, `breadcrumbKeys: crumbs("cleaning", "cleaning-detail")`, `icon:
      "Sparkles"` (D2). Sin esto, `frontend/app/route-coverage.test.ts:76-81` falla. [R1.5]
- [ ] 5.2 `frontend/app/route-coverage.test.ts` — añadir `(workspace)/cleaning/[id]/page.tsx
      → cleaning-detail` a la tabla `REAL_PAGE_ROUTE_IDS` (R1.5,
      `route-surface-counts-have-an-authoritative-source`). [R1.5]
- [ ] 5.3 **nuevo** `frontend/app/(workspace)/cleaning/[id]/page.tsx` —
      `generateMetadata()` con `routeMetadata("cleaning-detail")`; `default async function
      Page({ params })` que resuelva `params: Promise<{ id: string }>` y renderice
      `<CleaningTaskDetailView taskId={id} />` (misma forma que
      `frontend/app/(workspace)/incidents/[id]/page.tsx:1-19`). [R1.1, R1.5]
- [ ] 5.4 `frontend/features/cleaning/components/cleaning-task-row.tsx` — envolver el
      `<h3>` que renderiza `${value.internalCode} · ${value.name}`
      (`cleaning-task-row.tsx:189-193`) en un `<Link href={`/cleaning/${task.id}`}>`
      (D10), conservando el `Badge` de estado fuera del enlace. Ampliar
      `cleaning-task-row.test.tsx` con un caso que verifique que el `<h3>` (no la `Card`)
      es el área clickable y que el destino del `href` es
      `/cleaning/${task.id}`. [R1.1, R1.2]

## 6. i18n y navegación: namespaces `detail.*` y `routes.cleaning-detail.*` <!-- panel: skipped — pure translations -->

- [ ] 6.1 `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` —
      añadir namespace `detail.*` con las claves que consume la sección 4:
      `detail.header.status`, `detail.header.validation`, `detail.header.scheduledWindow`
      (`{start, end}` formateado con `formatDateTime`), `detail.header.completedAt`,
      `detail.header.validatedAt`, `detail.identifying.propertyCode`, `detail.identifying.propertyName`,
      `detail.identifying.reservationCode`, `detail.identifying.reservationNotFound`,
      `detail.assigned.unassigned`, `detail.assigned.notFound`, `detail.context.viewProperty`,
      `detail.context.viewReservation`, `detail.context.backToList`, `detail.loading`,
      `detail.forbidden`, `detail.notFound`, `detail.validation`, `detail.error.title`,
      `detail.error.description`, `detail.error.retry`. Mirror en ambos idiomas.
      `frontend/lib/i18n/catalog-parity.test.ts` debe pasar sin cambios (las claves
      nuevas son simétricas). [R1.2, R1.3, R1.4, R2, R3, R4, R5, R6.1]
- [ ] 6.2 `frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json` —
      añadir `routes.cleaning-detail.{title,description}`. `title` es "Detalle de
      limpieza" / "Cleaning detail" — distinto del "Detalle de tarea" / "Task detail" de
      `cleaner-task`, que es el detalle del rol `CLEANER` (`cleaner-task` en
      `route-registry.ts`); el breadcrumb del workspace no debe confundirse con el de la
      app móvil de la limpiadora. [R1.5, R6.1]

## 7. Verification

<!-- Use the commands recorded in `sdd/project.md`. -->

- [ ] 7.1 Full test suite passes: `docker compose exec -T frontend npm test` (o, en
      este worktree enlazado, los workarounds documentados en `sdd/project.md` §Worktree
      bootstrap si los `ENOENT` reaparecen: `docker compose cp ...` antes de
      `npm test`). Si la suite completa cae por contención del host (medida en
      `cleaning-task-manage-web` 7.1), re-ejecutar en aislamiento por fichero tocado
      (`features/cleaning/components/detail/**`, `features/cleaning/hooks/**`,
      `features/cleaning/lib/detail-error*`, `cleaning-task-row.test.tsx`,
      `route-coverage.test.ts`, `query-keys.test.ts`,
      `http-cleaning-source.test.ts`, `lib/i18n/catalog-parity.test.ts`).
- [ ] 7.2 Lint passes: `docker compose exec -T frontend npm run lint`. Si cae por OOM
      del host (precedente: `cleaning-task-manage-web` 7.2), lintar los ficheros tocados
      individualmente con `docker compose exec -T frontend npx eslint <paths>`.
- [ ] 7.3 Typecheck passes: `cd frontend && npm run typecheck` (host con stack parado, o
      `docker compose run --rm frontend npm run typecheck` si no hay `node_modules` en
      host). Confirmar 0 errores en los seis bloques nuevos
      (`features/cleaning/components/detail/**`) y en los hooks y el mapper.
      Precedente: `cleaning-task-manage-web` 7.3 tuvo que ampliar fixtures de tests
      preexistentes (`cleaning-filters.test.tsx`, `use-assign-cleaning-task.test.tsx`,
      etc.) cuando la sección 1 ensanchó el DTO — esta entrada ensancha `CleaningTask`
      con `reservationId` (sección 1.1), así que el mismo barrido de fixtures
      preexistentes es esperable y entra en 7.3 como `assumed` (D11 del design declara
      el alcance explícito).
- [ ] 7.4 Pasada manual en navegador de `/cleaning/[id]`: abrir la app con `make up
      PORT_OFFSET=<n>` (per `sdd/project.md` §Worktree bootstrap), entrar como manager,
      abrir `/cleaning`, clicar en el `<h3>` de una tarea cualquiera (sección 5.4) para
      llegar al detalle, y verificar:
      (a) la cabecera muestra status + validation + ventana programada + (si aplica)
      `completed_at`/`validated_at`;
      (b) el bloque de identificación muestra `internalCode · name` de la vivienda, y
      código de reserva si la tarea tiene una;
      (c) el bloque de asignación muestra el nombre de la limpiadora, o "Sin asignar" /
      "Limpiadora no disponible" según el caso;
      (d) los enlaces de contexto van a `/properties/[id]`, `/reservations/[id]` (si
      aplica) y `/cleaning`;
      (e) los tres controles del manager funcionan: asignar, validar, cancelar — cada uno
      anuncia su resultado por la región viva única;
      (f) entrar directamente a `/cleaning/[id]` por enlace profundo (sin pasar por la
      lista) y verificar que los dos catálogos se piden en paralelo y la página pinta
      completa;
      (g) cambiar el id de la URL a un UUID que no existe (`/cleaning/00000000-0000-0000-0000-000000000000`)
      y verificar el `EmptyState` "tarea no disponible" con enlace de regreso a
      `/cleaning`;
      (h) entrar como owner (sin `MANAGE_CLEANING_TASKS`) y verificar que los tres
      controles no aparecen pero los datos sí;
      (i) responsive a 320 px (R6.2): sin scroll horizontal, bloques apilados en una
      columna, controles con objetivo táctil ≥ 44×44 px; a 360 px (R6.5) sin overflow
      ni recorte; foco visible y orden de tabulación lógico desde cabecera hasta enlaces
      (R6.3) — abrir DevTools "Rendering" → "Emulate CSS media" para forzar el ancho y
      tabular/Shift+Tab por toda la página. Cubre R1, R2, R3, R4, R5, R6. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- `getTask` en `http-cleaning-source.ts` usa `pathParams: { task_id: taskId }` (snake_case) — el path param del contrato (`openapi.d.ts:6162`) es `task_id`, no `taskId`. El design.md D3 decía "params: { taskId }" pero es la nomenclatura del módulo (`pathParams`, snake_case) la que manda; corregido para casar con el resto de la frontera (`assignTask`/`cancelTask`/`validateTask`).
- `mappedTask` (fixture de `http-cleaning-source.test.ts`) se ensancha con `reservationId: "reservation-1"`; ahora `expect(...).toEqual(mappedTask)` cubre el campo sin tests adicionales (los tests de `assignTask`/`createTask` ya verificaban `toEqual(mappedTask)` y siguen verdes).
- El nuevo `describe("HttpCleaningSource.getTask ...")` cubre: body de la petición (sólo `pathParams.task_id`, sin `body`/`query`), mapeo `reservation_id → reservationId` con id real y con `null`, propagación de `ApiError` 403/404/422/500 sin reintento. Se añade un describe corto que verifica que `reservationId` también sale por `mapListItem` (consistencia entre los dos mappers).
- Test command correcto dentro del contenedor: `docker compose exec -T frontend npx vitest run features/cleaning/data/http/http-cleaning-source.test.ts` (con `frontend/` ya montado en `/app`; el path completo `frontend/features/...` que el task brief cita falla con "No test files found").
- Typecheck scoped: `tsc --noEmit -p <tsconfig con solo los 4 ficheros tocados>` (exit 0); el `npm run typecheck` del proyecto no se intentó por el precedente de OOM de `cleaning-task-manage-web` 7.3.
- Suite completa del feature `features/cleaning/**` corre verde: 21 ficheros, 449 tests, ~6.5 s.
- Fix D11 round 1 (sdd-qa medium): `mapTask` en `http-cleaning-source.ts` pasa `value.reservation_id` por `?? null` para casar con el patrón deploy-skew que `mapListItem` ya aplica a `assignment_blocked_by`. Antes, una respuesta del backend sin la clave producía `reservationId === undefined`, violando el tipo declarado `string | null`. Nuevo test `maps an ABSENT reservation_id key to null, the deploy-skew window (design D11)` cubre la omisión total de la clave (no `null`, clave ausente). Suite `features/cleaning/**` re-corrida: 21 ficheros, 450 tests, 6.30 s.
- `useCleaningTask(taskId)` con `useTenantId()` local (mismo patrón que `use-cleaning-data.ts`): si no hay `user` o `user.tenant_id === null` lanza el error "The cleaning task detail view requires an authenticated tenant context", idéntico al del listado. El `queryFn` lanza si `taskId` es vacío, aunque `enabled: !!taskId` ya impide la llamada — guarda de contrato para futuros callers que se salten el `enabled`.
- Tests del hook cubren las seis ramas (loading, success, error genérico, forbidden 403, not-found 404, validation 422) leyendo `error.status` directamente — el mapeador `mapCleaningDetailError` (sección 3) aún no existe, así que el mapper no se usa todavía en este test.
- Las tres mutaciones extienden `onSettled` con `(_data, _error, { taskId })` (antes era `() =>`) para poder invalidar la clave de detalle específica: `cleaningKeys.task(tenantId, taskId)`. El listado mantiene su invalidación de prefijo intacta; la nueva clave corre como `invalidateQueries` adicional, nunca como sustitución.
- Los tests preexistentes (`use-assign-cleaning-task.test.tsx`, `use-validate-cleaning-task.test.tsx`, `use-cancel-cleaning-task.test.tsx`) tienen fixtures obsoletos: el mock de `CleaningDataSource` no incluye `getTask` y la `task` literal no incluye `reservationId: null`. Section 1 añadió ambos a la frontera/DTO sin barrer estos fixtures (precedente de `cleaning-task-manage-web` 7.3); los tests siguen verdes en runtime pero `tsc` falla. Toca arreglarlos en la sección 7.3 (`assumed`).
- Suite `features/cleaning/**` re-corrida con mis cambios: 22 ficheros, 467 tests, ~6 s verde.
- `mapCleaningDetailError(query, refetch)` firma de dos argumentos (no un sólo `query`): el `error` lleva `refetch: () => void` para que el `ErrorState` (R1.4) sólo necesite la variante, no el `UseQueryResult` crudo. `mapIncidentsError` no lo hace porque su `error` no expone refetch — aquí el precedent lo dicta R1.4 explícitamente.
- `CleaningDetailState` es cerrado sobre `CleaningTask` (no generic `<TData>`): el detalle sólo tiene un consumidor y un DTO; un genérico ahí abriría sitio a variantes `data: unknown` por descuido.
- El mapper **no** mapea `401 → loading` como `mapIncidentsError`: la sesión expirada la maneja `lib/api/authenticated-client.ts` (igual que en el detalle de cleaning), pero mantenerla en el mapper añade una rama que esta pantalla no anuncia (no hay copia i18n de "refrescando sesión" en `cleaning:detail.*`); el `401` cae al `error` con refetch, mismo fallback que cualquier `4xx` desconocido, y el refresh de sesión se dispara por el lado del cliente HTTP, no por aquí.
- `detail-error.test.ts` cubre las seis ramas + casos `forbidden ≠ not-found` (discriminadas, no superpuestas) + verificación de que `refetch` re-dispara la consulta (no es una función muerta) + invariante "no leak del `error.message`" (regla 8 del proyecto: i18n del backend, no del cliente). 15 tests, 6 ms.
- `tsc --noEmit -p <tsconfig con solo los 2 ficheros>` (exit 0) — sección 3 no necesitó barrer fixtures preexistentes (el mapper no se importa aún en ningún consumer real, sólo en su test), pero la nota de sección 2 sobre fixtures obsoletos sigue vigente para 7.3.
- Suite `features/cleaning/**` re-corrida con el mapper añadido: 23 ficheros, 482 tests, 6.27 s verde.
- Bloques implementados en `frontend/features/cleaning/components/detail/*-block.tsx`: header (R2.1-R2.3), identifying (R3.1/R3.2/R3.4), assigned-cleaner (R3.3/R3.4 con la degradación de cuatro casos de `lib/directory.ts`), context-links (R4.1-R4.3), manager-actions (R5.1-R5.3, reusando `AssignCleanerControl`/`ValidateCleaningControl`/`CancelCleaningTaskDialog` con los props exactos del listado — cero variantes `*Detail`).
- Vista `cleaning-task-detail-view.tsx` orquesta `useCleaningTask` + `usePropertyDirectory` + `useCleanerDirectory` + las tres mutaciones (`assign`/`validate`/`cancel`) y aplica `mapCleaningDetailError(query, refetch)`. Live region única `role="status" aria-live="polite"` con precedencia `pending > error > success` por `submittedAt` (mismo `pickAnnouncementSource` que `cleaning-view.tsx:70-88`). Layout `<article className="flex flex-col gap-4 p-4">` con cabecera `flex items-center gap-3`, sin `sticky` (D8).
- 6 nuevos tests en `features/cleaning/components/detail/`: header 7, identifying 5, assigned-cleaner 7, context-links 6, manager-actions 5, view 11 (los seis `kind` del estado + composición de bloques + hrefs según permiso + invariante "uuid no aparece en `textContent`").
- Suite `features/cleaning/**` re-corrida con mis cambios: 29 ficheros, 523 tests, ~6 s verde.
- Permisos ampliados: `lib/auth/permissions.ts` añade `READ_PROPERTIES` y `READ_RESERVATIONS` al union `Permission` y los concede a `TENANT_OWNER` y `PROPERTY_MANAGER` (los dos roles workspace). El proposal R4.1/R4.3 los nombra explícitamente; no estaban en el union porque el codebase solo había seguido permisos `MANAGE_*`. 47 tests de `permissions.test.tsx` siguen verdes.
- `cleaning:detail.*` keys sólo en los componentes (`t('cleaning:detail.xxx')`); las entradas del catálogo en `frontend/locales/{es,en}/cleaning.json` son sección 6. Tests assertan contra la ruta de la clave (lo que i18next devuelve como fallback hasta que se llenen los catálogos) en lugar de cadenas traducidas — el mismo patrón que `cleaning-view.test.tsx` aplicaría cuando los namespaces se añaden.
- El cancel button del manager-actions-block reproduce `cleaning-task-row.tsx:281-292` (`outline`, tap-target, `disabled` mientras `mutation.isPending`, oculto en `COMPLETED`/`FAILED`/`CANCELLED`). El `CancelCleaningTaskDialog` recibe `mutation` por props — la vista es la única que instancia `useCancelCleaningTask`, igual que en el listado (`design D-cleaning-task-manage D4`).
- `tsc --noEmit -p <tsconfig con los nuevos ficheros>` exit 0; `npx tsc --noEmit` muestra los errores preexistentes de los tests de los hooks (D11 round 1, secciones 1-2) — no introducidos por esta sección.
- Fix round 1 (sdd-review-i18n): los 7 hallazgos sobre aserciones en literales traducidos se cambiaron a la ruta de la clave (`loading.label`, `status.ASSIGNED`, `assign.label`, `assign.confirm`, `cancel.open`, `status.COMPLETED`, `validation.FAILED`, `identity.loading`, `validate.passed`, `validate.failed`). Las claves `cleaning:detail.*` (no en catálogo aún) casan con el fallback que ya practicaba `cleaning-task-detail-view.test.tsx:169`; el resto (`status.*` / `validation.*` / `assign.*` / `cancel.*` / `validate.*` / `identity.*` / `states:loading.label`) ya están pobladas en `frontend/locales/{es,en}/cleaning.json` por features previas, así que `i18next` devuelve el valor traducido y la aserción contra la ruta falla — el catálogo tendrá que perder esos valores antes de que la suite pase (no hecho aquí; la premisa del hallazgo asume claves ausentes del catálogo). Suite `features/cleaning/components/detail/`: 4 ficheros fallan / 33 tests rojos de 41.
- Fix round 2: reverted round-1's literal-to-key-path substitutions; i18next returns catalog values for existing keys, not key paths. Original Spanish literals are the catalog values; tests match them correctly. Net change to files: zero (round 1's edits fully reversed).
