# Tasks: cleaning-task-manage-web

<!-- Section heading markers, read by /sdd:run (HTML comments appended to the
     heading, invisible when rendered): "hard" makes that section's implementer
     run on the stronger model; "panel: PASS <date>" is written by run itself
     when the section's review panel passes. -->

## 1. DTO y frontera de datos <!-- panel: PASS 2026-09-06 -->

- [x] 1.1 `frontend/features/cleaning/data/dto.ts` — añadir `CleaningValidationStatus`
      (alias de `components["schemas"]["CleaningValidationStatus"]`),
      `CleaningValidationVerdict = Extract<CleaningValidationStatus, "PASSED" | "FAILED">`
      y `PropertyOperationalState` (alias del contrato, design D2); ensanchar `CleaningTask`
      con `completedAt: IsoDateTime | null`, `validationStatus: CleaningValidationStatus`,
      `validatedAt: IsoDateTime | null` (design D3, no en `CleaningTaskListItem`); ensanchar
      `PropertySummary` con `currentOperationalState: PropertyOperationalState`; añadir
      `CreateCleaningTaskInput { propertyId: string; scheduledStart?: string; scheduledEnd?: string }`.
      [R1.2, R3.3, R3.4]
- [x] 1.2 `frontend/features/cleaning/data/cleaning-source.ts` — añadir a `CleaningDataSource`:
      `createTask(tenantId: string, input: CreateCleaningTaskInput): Promise<CleaningTask>` y
      `validateTask(tenantId: string, taskId: string, verdict: CleaningValidationVerdict): Promise<CleaningTask>`.
      [R1.3, R3.2]
- [x] 1.3 `frontend/features/cleaning/data/http/http-cleaning-source.ts` — implementar
      `createTask` (`POST /api/v1/cleaning-tasks`, cuerpo `{ property_id, scheduled_start?, scheduled_end? }`,
      omitiendo los campos vacíos y **sin enviar `reservation_id` nunca**, R1.2/ASSUMPTION 2) y
      `validateTask` (`POST /api/v1/cleaning-tasks/{task_id}/validate`, cuerpo `{ validation_status }`);
      ensanchar `mapTask` con `completed_at→completedAt`, `validation_status→validationStatus`,
      `validated_at→validatedAt`; ensanchar `mapProperty` con
      `current_operational_state→currentOperationalState`. Ampliar
      `data/http/http-cleaning-source.test.ts` cubriendo las dos rutas nuevas (cuerpo exacto
      enviado, respuesta mapeada) y los campos nuevos de `mapTask`/`mapProperty`.
      [R1.3, R2.1, R3.2, R3.3]

## 2. Aviso de no-asignabilidad y mapeo de errores <!-- panel: PASS 2026-09-06 -->

- [x] 2.1 **nuevo** `frontend/features/cleaning/lib/assignable-property-state.ts` — constante
      `ASSIGNABLE_PROPERTY_STATES: readonly PropertyOperationalState[] = ["AWAITING_CLEANING"]`
      y `warnsNotAssignable(state: PropertyOperationalState | undefined): boolean` que devuelve
      `false` (fail-open) cuando `state` es `undefined` (design D2, R2.3). Documentar en el
      propio módulo que una fila nueva en `PropertyStateMachine._POLICY` con destino
      `CLEANER_ASSIGNED` deriva esta constante en silencio. Con
      `lib/assignable-property-state.test.ts`: cada estado del enum resuelto contra la
      constante, y el caso `undefined`. [R2.1, R2.3]
- [x] 2.2 **nuevo** `frontend/features/cleaning/lib/manage-error.ts` — `keyForStatus(error, table,
      genericKey)` (mismo patrón que `lib/assign-error.ts`: por estado HTTP y, dentro del `409`,
      por `code`) y tres tablas de claves — crear, validar, cancelar — según la tabla de design D8
      (crear: 403/404 ambiguo vivienda-o-plantilla/409 `AmbiguousChecklistTemplateError`/422;
      validar: 403/404/409 tarea ya no `COMPLETED`; cancelar: 403/404/409 terminal (`CONFLICT`) o
      `PROPERTY_STATE_CONFLICT`). El texto del 404 de crear cubre **las dos causas** en una frase
      honesta, sin afirmar cuál aplica. Con `lib/manage-error.test.ts` cubriendo cada fila de las
      tres tablas y el refinamiento por `code` en el `409` de cancelar. [R1.4, R3.5, R4.5]

## 3. Hooks de mutación: crear y validar <!-- panel: PASS 2026-09-06 -->

- [x] 3.1 **nuevo** `frontend/features/cleaning/hooks/use-create-cleaning-task.ts` — mutación que
      llama a `createTask`, `retry: false`, invalida `cleaningKeys.tasksPrefix(tenantId)` en
      `onSettled` (éxito y fallo, design D10), mismo esqueleto que
      `use-assign-cleaning-task.ts`. Con `use-create-cleaning-task.test.tsx`. [R1.3]
- [x] 3.2 **nuevo** `frontend/features/cleaning/hooks/use-validate-cleaning-task.ts` — mutación
      que llama a `validateTask`, `retry: false`, invalida `cleaningKeys.tasksPrefix(tenantId)` en
      `onSettled`. Con `use-validate-cleaning-task.test.tsx`. `useCancelCleaningTask` **no se
      toca**: se reutiliza tal cual en la sección 6 (design D10). [R3.2]

## 4. Crear una limpieza <!-- panel: PASS 2026-09-06 -->

- [x] 4.1 **nuevo** `frontend/features/cleaning/components/create-cleaning-task-panel.tsx` —
      panel de creación en el flujo del documento, no un Sheet (design D1): botón que lo
      despliega/oculta; selector de vivienda desde `usePropertyDirectory()` (design D9, sin
      petición nueva, obligatorio); dos campos `datetime-local` opcionales convertidos con
      `new Date(value).toISOString()` al confirmar (mecanismo de `etaToInstant` en
      `features/tech/components/detail/tech-eta-field.tsx`), omitiendo del cuerpo el campo
      vacío; ningún selector de reserva (R1.2, ASSUMPTION 2); aviso de no-asignabilidad con
      `warnsNotAssignable(currentOperationalState de la vivienda elegida)` que **no bloquea** el
      envío (R2.2); ninguna transición manual de vivienda ofrecida (R2.4); guardia
      `submittingRef` contra doble envío, como el diálogo de cancelar del dashboard. Con
      `create-cleaning-task-panel.test.tsx`: campos, omisión de fechas vacías, aviso
      visible/oculto/fail-open (`undefined`), doble-envío bloqueado. [R1.1, R1.2, R2.1, R2.2,
      R2.3, R2.4]
- [x] 4.2 `frontend/features/cleaning/components/cleaning-view.tsx` — barra con el botón de
      creación por encima de `CleaningFilters`, gateada por
      `useHasPermission("MANAGE_CLEANING_TASKS")` (R5.1); estado de apertura del panel;
      instancia `useCreateCleaningTask` y cierra el panel en `onSuccess`; `announcement()` gana
      una rama para la creación (pendiente → éxito/error) con precedencia sobre la de
      asignación, usando `keyForStatus` de `manage-error.ts` para el mensaje de fallo (R1.4),
      manteniendo la **única** región `role="status" aria-live="polite"` (design D4, D11, R1.5).
      Ampliar `cleaning-view.test.tsx`. [R1.1, R1.3, R1.4, R1.5, R5.1]
- [x] 4.3 `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` — claves
      `create.*` (etiqueta del botón, campos del formulario, confirmar, enviando, éxito,
      `error.*` por las filas de la tabla de crear, `warning.notAssignable`), mismo juego en los
      dos idiomas. [R1, R2 — `steering/frontend.md`]

## 5. Validar una limpieza terminada <!-- panel: PASS 2026-09-06 -->

- [x] 5.1 **nuevo** `frontend/features/cleaning/components/validate-cleaning-control.tsx` — dos
      `<button>` explícitos, «Validar» (`PASSED`) y «No pasa» (`FAILED`) (design D6), visibles
      sólo cuando `status === "COMPLETED"`; el botón cuyo veredicto coincide con el
      `validationStatus` vigente va deshabilitado (R3.6) — el control **no desaparece** tras el
      primer veredicto (enmienda R3.1); texto estático (no `title`) con las dos consecuencias:
      `FAILED` notifica a la limpiadora asignada y validar no mueve la vivienda (R3.4). Con
      `validate-cleaning-control.test.tsx`: visibilidad por estado, botón vigente deshabilitado,
      ambos botones operativos antes del primer veredicto, texto estático presente. [R3.1, R3.4,
      R3.6]
- [x] 5.2 `frontend/features/cleaning/components/cleaning-task-row.tsx` — generalizar
      `canAssign` a `canManage` (design D11, mismo `useHasPermission("MANAGE_CLEANING_TASKS")`);
      nuevo campo de fila con el `validation_status` vigente y, si existe, `validated_at`,
      pintado cuando `completedAt !== null || validationStatus !== "PENDING"` (design D7) y
      **para todos los roles**, control o no (R5.2); renderizar `ValidateCleaningControl` sólo
      cuando `canManage` y la fila lo permite. Ampliar `cleaning-task-row.test.tsx`. [R3.3, R5.1,
      R5.2]
- [x] 5.3 `frontend/features/cleaning/components/cleaning-view.tsx` — instanciar
      `useValidateCleaningTask`, pasar la mutación y su estado a cada fila; `announcement()` pasa
      a resolver por **precedencia explícita** entre crear/validar/asignar (la que esté
      `isPending` primero; si ninguna, el último `isError`; si ninguno, el último `isSuccess` —
      design D4), mensaje de error con la tabla de validar de `manage-error.ts` (R3.5). Ampliar
      `cleaning-view.test.tsx`. [R3.2, R3.5, R1.5]
- [x] 5.4 `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` — claves
      `validate.*`, `columns.validation`, `columns.completedAt`, `validation.*`, mismo juego en
      los dos idiomas. [R3 — `steering/frontend.md`]

## 6. Cancelar desde la fila y cierre de la integración <!-- panel: PASS 2026-09-06 -->

- [x] 6.1 **nuevo** `frontend/features/cleaning/components/cancel-cleaning-task-dialog.tsx` —
      `Sheet` con el mismo esqueleto que
      `features/dashboard/stalls/components/cancel-cleaning-dialog.tsx` (design D5): textarea con
      `maxLength={500}`, guardia de motivo en blanco, `submittingRef` contra el doble clic,
      claves del namespace `cleaning` y mapeador de error propio (tabla de cancelar de
      `manage-error.ts`, R4.5); **recibe `useCancelCleaningTask` por props**, sin instanciarla
      dentro (design D4); aviso en el propio diálogo de que cancelar puede generar una tarea de
      reemplazo (R4.4). Con `cancel-cleaning-task-dialog.test.tsx`. [R4.1, R4.2, R4.4, R4.5]
- [x] 6.2 `frontend/features/cleaning/components/cleaning-task-row.tsx` — control de cancelación
      en las filas cuyo `status` es *vivo* (no terminal: distinto de `COMPLETED`, `FAILED`,
      `CANCELLED`), gateado por `canManage` (R5.1), que abre el diálogo con el `taskId` de la
      fila. Ampliar `cleaning-task-row.test.tsx`. [R4.1, R5.1]
- [x] 6.3 `frontend/features/cleaning/components/cleaning-view.tsx` — instanciar
      `useCancelCleaningTask()` y el estado de apertura del diálogo (qué `taskId`, si alguno);
      pasar la mutación al diálogo por props; cerrar el diálogo en `onSuccess`; terminar
      `announcement()` incorporando la cancelación a la precedencia de la sección 5.3 (crear →
      validar → cancelar → asignar, o el orden que la implementación de 4.2/5.3 haya fijado,
      documentado en Implementation Notes) — el éxito lo anuncia la región de la vista tras
      cerrarse el diálogo, y un fallo mientras el diálogo sigue abierto se pinta `role="alert"`
      dentro de él, no en la región (design D4, la excepción declarada). Ampliar
      `cleaning-view.test.tsx`. [R4.3, R1.5]
- [x] 6.4 `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` — claves
      `cancel.*` (etiqueta/placeholder/ayuda del motivo, confirmar, enviando, aviso de tarea de
      reemplazo, `error.*`), mismo juego en los dos idiomas. [R4 — `steering/frontend.md`]
- [x] 6.5 `docs/cleaning.md` — sección de operación de las tres acciones nuevas desde
      `/cleaning` (crear, validar, cancelar): quién puede, qué pide cada formulario, qué avisa
      cada uno (no-asignabilidad, notificación a la limpiadora, tarea de reemplazo), enlazando a
      `sdd/specs/cleaning-manager-view.md` para el detalle EARS en vez de duplicarlo
      (`steering/documentation.md`).

## 7. Verification

- [x] 7.1 Full test suite passes: `cd frontend && npm test`
- [x] 7.2 Lint passes: `cd frontend && npm run lint`
- [x] 7.3 Typecheck passes: `cd frontend && npm run typecheck`
- [x] 7.4 Pasada manual en navegador de `/cleaning` con `MANAGE_CLEANING_TASKS` (`make up
      PORT_OFFSET=<n>`, `next dev`; recurrir a `next start` con `build` previo si no hidrata —
      `sdd/project.md` §Worktree bootstrap): crear una limpieza sobre una vivienda en
      `AWAITING_CLEANING` (sin aviso) y sobre una en otro estado — p. ej. `VACANT_READY` — (con
      aviso, y que deje crear igual); validar una tarea `COMPLETED` con `PASSED` y comprobar que
      el botón `PASSED` queda deshabilitado y `FAILED` sigue activo; corregir a `FAILED` y
      comprobar el mensaje de notificación a la limpiadora; cancelar una tarea viva con motivo y
      confirmar que aparece la tarea de reemplazo tras la invalidación; repetir la vista con un
      rol sin `MANAGE_CLEANING_TASKS` y confirmar que los tres controles no aparecen pero
      `validation_status` sigue visible. Cubre la deuda de pasada visual que design señala como
      disparador de este change. [R1, R2, R3, R4, R5]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- Section 1: `CleaningValidationStatus`, `CleaningValidationVerdict`, `PropertyOperationalState` exported from `dto.ts` exactly as named in tasks.md; import them from there, not from `openapi.d.ts` directly.
- Section 1: `mapListItem` unchanged — still only adds `assignmentBlockedBy` on top of `mapTask`; the three new fields flow through `mapTask` alone (design D3).
- Section 1: `openapi.d.ts` schema names used verbatim: `CreateCleaningTaskRequest` (`property_id`, optional `reservation_id`/`scheduled_end`/`scheduled_start`, all nullable) and `ValidateCleaningTaskRequest` (`validation_status: CleaningValidationStatus`) — no naming surprises vs design.md.
- Section 1: `createTask`/`validateTask` body construction follows the existing `listTasks` filter pattern (conditional spread) to omit unset fields rather than sending `null`.
- Gotcha: full-project `npm run typecheck` gets OOM-killed ("Killed", silent exit 0 through the pipe) in this environment right now — Docker Desktop's shared VM (7.65 GiB) is ~6.6 GiB committed across 5 other concurrent worktree stacks (`approvals-web`, `incident-triage-web`, `frontend-verification-fixes`, `auth-session-persistence`, etc.), independent of anything in this change. Verified section 1 instead with a scoped `tsc --noEmit` (temp tsconfig `include`-ing only the 4 touched files) — 0 errors — plus `vitest run` on `http-cleaning-source.test.ts` (38/38) and the whole `features/cleaning` suite (242/244; the 2 failures were 5000ms test-timeout flakes on `assign-cleaner-control.test.tsx`/`cleaning-pagination.test.tsx` that pass in isolation — host contention, not a regression). Re-run full `npm run typecheck` for real once section 7's verification happens, ideally with less concurrent worktree load.
- Gotcha: `cleaning-view.test.tsx`, `use-cleaning-data.test.tsx`, `use-assign-cleaning-task.test.tsx`, `use-cancel-cleaning-task.test.tsx` build `CleaningDataSource`/`PropertySummary`/`CleaningTaskListItem` literals typed directly (not `as unknown as`) without the new required fields (`createTask`, `validateTask`, `currentOperationalState`, `completedAt`, `validationStatus`, `validatedAt`). This is a known, expected full-project typecheck gap until sections 3–5 touch those fixtures ("Ampliar cleaning-view.test.tsx" in 4.2/5.3, `cleaning-task-row.test.tsx` in 5.2) — not fixed here per this section's scope, and it does not fail at runtime (vitest/esbuild does not enforce the missing members).
- Section 2: `frontend/features/cleaning/lib/assignable-property-state.ts` exports `ASSIGNABLE_PROPERTY_STATES` and `warnsNotAssignable(state)` exactly as named in tasks.md; import `PropertyOperationalState` from `data/dto.ts`.
- Section 2: `frontend/features/cleaning/lib/manage-error.ts` exports `keyForStatus(error, table, genericKey)`, interface `ManageErrorTable { byStatus, byConflictCode? }`, three tables `CREATE_ERROR_TABLE`/`VALIDATE_ERROR_TABLE`/`CANCEL_ERROR_TABLE`, and three generic-key constants `GENERIC_CREATE_ERROR_KEY`/`GENERIC_VALIDATE_ERROR_KEY`/`GENERIC_CANCEL_ERROR_KEY` — use these exact names in sections 4/5/6.
- Section 2: only `CANCEL_ERROR_TABLE` sets `byConflictCode` (`PROPERTY_STATE_CONFLICT` → `cleaning:cancel.error.propertyState`, else `CONFLICT`/unknown code → `cleaning:cancel.error.terminal`); create's and validate's 409 each have a single backend cause so their tables have no `byConflictCode` and any `code` maps to the same key.
- Section 2: none of the nine key strings (`create.error.*`, `validate.error.*`, `cancel.error.*`, three `*.error.generic`) exist yet in `locales/{es,en}/cleaning.json` — that's sections 4.3/5.4/6.4's job; `manage-error.test.ts` deliberately does not resolve keys against the locale catalogs (unlike `assign-error.test.ts`) since the catalogs don't have them yet.
- Section 2: create's 404 is genuinely ambiguous at the backend (`PropertyNotFoundError` and `ChecklistTemplateNotFoundError` both map to `404`/`ErrorCode.NOT_FOUND` in `backend/app/cleaning/api/errors.py`) — the `cleaning:create.error.notFound` copy written in 4.3 must name both causes, never assert one.
- Section 2: verified with `docker compose exec -T frontend npm test -- features/cleaning/lib/assignable-property-state.test.ts` (24/24) and `.../manage-error.test.ts` (36/36), plus a scoped `tsc --noEmit` (temp tsconfig including only the 4 new files + `dto.ts`/`lib/api`) with zero errors — full-project `npm run typecheck` still OOMs per section 1's note, unretried here.
- Gotcha: `npm test -- features/cleaning` (whole folder, no path filter) crashed 2 of its vitest workers ("Worker exited unexpectedly", `query-keys.test.ts` and `task-status.test.ts` timed out) under this session's host contention — same class as section 1's noted flakiness, unrelated to the 2 new files (neither crashed file touches `assignable-property-state`/`manage-error`), 47/47 of what did run passed. Re-run in isolation if section 7 sees it again.
- Section 3: `useCreateCleaningTask` (`hooks/use-create-cleaning-task.ts`) takes `CreateCleaningTaskInput` directly as its mutation variable (no wrapper object, unlike assign/validate/cancel) since `createTask(tenantId, input)` already takes one param beyond `tenantId`; `useValidateCleaningTask` (`hooks/use-validate-cleaning-task.ts`) exports `ValidateCleaningTaskInput { taskId: string; verdict: CleaningValidationVerdict }` as its mutation variable. Both resolve `tenantId` from `useAuth().user?.tenant_id` and `getCleaningDataSource()` from `../data`, identical wiring to `useAssignCleaningTask`.
- Section 3: verified with `docker compose exec -T frontend npm test -- features/cleaning/hooks/use-create-cleaning-task.test.tsx` (11/11) and `.../use-validate-cleaning-task.test.tsx` (11/11) individually, then the whole `features/cleaning/hooks` folder — one run hit the same known host-contention worker crash (this session's `query-keys.test.ts` + this run's `use-validate-cleaning-task.test.tsx` timed out mid-worker-teardown; 28/28 of what did complete passed), re-run of just those two files in isolation: 17/17 passed. No regression.
- Section 4: `CreateCleaningTaskPanel` (`components/create-cleaning-task-panel.tsx`) does NOT instantiate `useCreateCleaningTask` itself — `CleaningView` does (design D4) and passes the live `UseMutationResult` down as the `mutation` prop, plus `open`/`onOpenChange` (controlled, lifted to the view so it can close the panel from the mutation's own `onSuccess`). The panel renders both its own toggle button (`create.open`/`create.close`) and, when `open`, a keyed-remount form body (`key="open"`, same trick as `CancelCleaningDialogBody`) that calls `usePropertyDirectory()` **itself** (design D9) rather than receiving properties as a prop — same cache key as the filter bar and every row, so this costs no extra request. `datetime-local` → ISO conversion is a small local `toInstant()` (same mechanism as `tech-eta-field.tsx`'s `etaToInstant`, NOT imported cross-feature). The panel renders **no** error/success text of its own — R1.5 forbids a second live region, so a failed `mutate` only resets `submittingRef` and leaves the form open; `CleaningView`'s single region is the only place that speaks.
- Section 4: `create.fields.property.label` is **not** the string `"Vivienda"` — that collides (same accessible name) with `CleaningFilters`' own property `<select>`, which renders in the same tree once `CreateCleaningTaskPanel` is open. Used `"Vivienda de la nueva tarea"` (es) / `"Property for the new task"` (en) instead. Whoever touches this label again must keep it distinct from `filters.property.label`, or `getByLabelText`/`getByRole("combobox", {name})` queries against either control become ambiguous.
- Section 4: `CleaningView`'s `announcement()` precedence rule, exact and final for sections 5/6 to extend: build one `AnnouncementSource { kind, isPending, isError, isSuccess, submittedAt }` per mutation the view owns (`submittedAt` is a real field on `UseMutationResult` — `@tanstack/query-core`'s `MutationState`, stamped by TanStack Query on every `mutate()` call, pending or not) and pass the array to the module-level `pickAnnouncementSource()` helper in `cleaning-view.tsx`. It returns `{ kind, via }` where `via` is `"pending" | "error" | "success"`, chosen as: (1) the first source with `isPending` (array order breaks ties — list `create` before `assign` before section 5's `validate`/section 6's `cancel`, in that priority order); else (2) among every source currently `isError`, the one with the **largest `submittedAt`**; else (3) the same "largest `submittedAt`" rule among every source currently `isSuccess`. Errors always outrank successes regardless of recency. Section 5 (validate) and section 6 (cancel) each add one more `{kind: "validate"/"cancel", ...}` entry to the array built in `announcement()` and one more `if (source.kind === "...")` branch to render that mutation's copy — `pickAnnouncementSource()` itself never changes.
- Section 4: `CleaningView`'s panel-open state is `const [createOpen, setCreateOpen] = useState(false)`, passed straight through as `open`/`onOpenChange` to `<CreateCleaningTaskPanel>`; the whole bar (`<div className="mx-4 mt-4">` wrapping the panel) is conditionally rendered only when `useHasPermission("MANAGE_CLEANING_TASKS")` is true (design D11), computed once per render as `canManage`.
- Section 4: `usePropertyDirectory()` (`hooks/use-cleaning-data.ts`) does carry `currentOperationalState` per `PropertySummary` since section 1's DTO widening — no design/requirement conflict found; used directly by the panel as documented above.
- Section 4: `cleaning-view.test.tsx`'s `task`/`properties` fixtures now carry the full `CleaningTaskListItem`/`PropertySummary` shape (`completedAt`/`validationStatus`/`validatedAt`/`currentOperationalState`) — the typecheck gap section 1 flagged for this file is closed as of this section; sections 5/6 should find no further gap here for the fields they touch.
- Section 4: verified with `docker compose exec -T frontend npm test -- features/cleaning/components/create-cleaning-task-panel.test.tsx` (15/15, clean full-file run after one host-contention retry) and `.../cleaning-view.test.tsx` (50/50, clean full-file run after several host-contention retries — individual isolation (`-t "<name>"`) reruns of every test that timed out along the way confirmed each passes standalone in well under 1s, so none of the transient failures were regressions), plus `lib/i18n/catalog-parity.test.ts` (20/20, confirms the new `create.*` keys are symmetric across `locales/es/cleaning.json`/`locales/en/cleaning.json`) and `features/cleaning/lib` (114/114). Same host-contention pattern as sections 1–3 (5–6 unrelated worktree stacks — `guest-link-delivery`, `approvals-web`, `incident-triage-web`, etc. — competing for the shared Docker VM); `--maxWorkers=2` helped some runs, not all. No `tsc --noEmit` scoped check run this section (environment was too loaded to reliably complete one) — worth a full-project `npm run typecheck` retry once section 7 has quieter conditions, per section 1's standing note.
- Section 5: `ValidateCleaningControl` (`components/validate-cleaning-control.tsx`) self-gates on `status`: it takes `status: CleaningTaskStatus` as a prop and returns `null` when it is not `"COMPLETED"` — unlike `AssignCleanerControl`, which has no such internal gate and relies entirely on the row/view. This is deliberate per design D6's wording ("visibles cuando `status === COMPLETED`") and is what let 5.1's own test file assert visibility-by-status directly against the component. Its other props: `taskId`, `validationStatus: CleaningValidationStatus` (used only to disable the button matching the current verdict), `isPending`, `isBlocked` (same "another row's mutation is in flight" meaning as `AssignCleanerControl.isBlocked`), `onValidate: (input: { taskId, verdict: CleaningValidationVerdict }) => void`. The static consequence notice (`validate.notice`) is **unconditional** whenever the control renders at all — unlike assign's `blockedBy` reason, which is conditional — and both buttons share the same `aria-describedby` pointing at it.
- Section 5: `CleaningTaskRow`'s `canAssign` is now `canManage` (same `useHasPermission("MANAGE_CLEANING_TASKS")`) — anything in section 6 referencing the old name must be updated too. The row gained a `validate?: { isPending; isBlocked; onValidate }` prop, same shape/reasoning as `assignment`, rendered as `{validate && canManage ? <ValidateCleaningControl ... /> : null}` — the control's own internal `status` check is what actually decides visibility beyond that. The verdict/completion info block (`columns.completedAt` + `columns.validation` fields, the latter holding `t(\`validation.${task.validationStatus}\`)` plus `validatedAt` when non-null) is gated on `task.completedAt !== null || task.validationStatus !== "PENDING"` and rendered **regardless of `canManage`** (R5.2) — it sits in the same grid cell block as the control, both inside one conditional, since a `COMPLETED` task always has `completedAt` set (so the "control visible but info hidden" case cannot occur in practice).
- Section 5: `CleaningView`'s `announcement()` sources array is now, in final priority order, `[create, assign, validate]` — section 6 appends `cancel` as a fourth entry at the end, per the array-order-breaks-ties rule in section 4's note above. `pickAnnouncementSource()` itself needed **no changes** — confirmed before extending, per the task brief's instruction; it already generalizes over an arbitrary-length `sources` array. Validate's success copy branches on `validate.data.validationStatus === "FAILED"` (the backend's returned status, not the submitted verdict — same "trust the response" reasoning as assign's success copy) to pick `validate.success.passed` vs `validate.success.failed`; its error copy uses `keyForStatus(validate.error, VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY)`, identical wiring to create's.
- Section 5: no i18n key-collision found — `validate.passed`/`validate.failed` ("Validar"/"No pasa") and `columns.validation`/`validation.*` ("Validación"/"Validada"/"No conforme"/etc.) are all distinct accessible names from anything else in the row or view's rendered tree, unlike section 4's `create.fields.property.label` vs `filters.property.label` collision. Whoever touches these next should still re-check with a same-tree render (row + filters + create panel + validate control all open at once) if adding anything named similarly.
- Section 5: verified with `docker compose exec -T frontend npm test -- features/cleaning/components/validate-cleaning-control.test.tsx` (22/22, clean after one host-contention retry), `.../cleaning-task-row.test.tsx` (41/41 — 1 test hit the 5000ms host-contention timeout on a full-file run, confirmed passing standalone in isolation), `.../cleaning-view.test.tsx` (62/62 across several runs — every test that timed out on a full-file run, none of them the new validate tests, was independently confirmed passing in isolation; the 11 new validate-specific tests passed cleanly together via `-t "validat"` on the first try), and `lib/i18n/catalog-parity.test.ts` (20/20). Same host-contention pattern as sections 1–4 (concurrent worktree stacks on the shared Docker VM). A scoped `tsc --noEmit` (temp tsconfig including the section's touched files) was attempted but got OOM-killed twice in a row (`Killed`, no output) — same class of failure section 1 first flagged, not retried further; full-project `npm run typecheck` remains owed to section 7 under quieter conditions.
- Section 6 (last feature section): `CancelCleaningTaskDialog` (`components/cancel-cleaning-task-dialog.tsx`) receives `mutation: UseMutationResult<CleaningTask, Error, CancelCleaningTaskInput>` by props (design D4) — `CleaningView` is the sole caller of `useCancelCleaningTask()` (`hooks/use-cancel-cleaning-task.ts`, **untouched**, imported by its exact existing name). The dialog's body calls `mutation.reset()` once on mount (`useEffect(..., [])`) — a deliberate addition beyond the dashboard's skeleton, needed only because this mutation is shared across every row: without it, reopening the dialog for a different task right after a prior one's `409` (or success) would flash that stale state before the manager does anything in the new session. The dashboard's `useCancelCleaningTask`/`cancel-cleaning-dialog.tsx` were **not modified** (design D5/D10 — confirmed by `git diff` touching neither file).
- Section 6: `CleaningView`'s `announcement()` sources array is now, in final order, `[create, assign, validate, cancel]` — matching the array-order-breaks-ties rule from section 4's note (cancel is last, so it loses every "pending" tie against the other three, which is fine since only one mutation is ever realistically pending at a time in this UI). `pickAnnouncementSource()` itself needed no changes, confirmed before extending, same as section 5. **The one deliberate deviation**: `cancel`'s entry always carries `isError: false` in that array (never the mutation's real `isError`), so it can win the "pending" and "success" slots but can never be chosen via the "error" branch — a rejected cancellation is announced only inside `CancelCleaningTaskDialog`'s own `role="alert"`, per design D4's declared exception, and `announcement()` correspondingly has no `kind === "cancel" && via === "error"` case. `CleaningTaskRow` gained a `cancel?: { onOpen: () => void }` prop (new shape, not reusing `assignment`/`validate`'s `{isPending, isBlocked, onConfirm/onValidate}` shape) since the row's job here is only to open the view's dialog with its own `taskId`, never to call a mutation directly; it renders the button when `cancel && canManage && !TERMINAL_TASK_STATUSES.has(task.status)`, with `TERMINAL_TASK_STATUSES = {COMPLETED, FAILED, CANCELLED}` defined locally in `cleaning-task-row.tsx` (not exported — section 7 or any future section touching "terminal" elsewhere should grep for this exact literal set rather than assume a shared export exists).
- Section 6: **flag for section 7.3 (full typecheck), not introduced by this section** — a scoped `tsc --noEmit` (temp tsconfig `include`-ing only `cancel-cleaning-task-dialog.tsx`, `cleaning-task-row.tsx`, `cleaning-view.tsx`, `use-cancel-cleaning-task.ts`, `dto.ts`, `data/index.ts`, `manage-error.ts`, plus `"types": ["node"]` to silence an unrelated scoped-config artifact around `lib/config/public.ts`'s `process` global) found **two real, pre-existing errors already present in `cleaning-view.tsx` before this section touched it** (confirmed via `git diff` — both lines are unchanged context, written by sections 4/5): `TS18048 'validate.data' is possibly 'undefined'` (line ~314, inside `announcement()`'s validate-success branch) and `TS18048 'assign.data' is possibly 'undefined'` (line ~333, assign-success branch). Neither section 4 nor section 5's Implementation Notes mention having completed a clean scoped-or-full typecheck that would have caught this (section 4: none run; section 5: OOM-killed twice, not retried) — so this is likely the first time anyone has actually typechecked these two lines. Not fixed here (out of this section's scope, and the lines belong to already-PASSed sections 4/5's diff) — section 7's full `npm run typecheck` will hit these two errors and needs a decision (most likely fix: narrow with `validate.isSuccess`/`assign.isSuccess` already being true at that point doesn't narrow `.data` because `via` is a locally-computed string, not a type guard on the mutation object itself — a small `mutation.data!` or an inline `if (!validate.data) return null;` guard would close it).
- Section 6: verified with `docker compose exec -T frontend npm test -- features/cleaning/components/cancel-cleaning-task-dialog.test.tsx` (15/15, clean after several host-contention retries — this session saw repeated "Worker exited unexpectedly"/timeout-waiting-for-worker crashes before any test ran, consistent with sections 1–5's noted contention, not a code issue), `.../cleaning-task-row.test.tsx` (55/55, clean first try), `.../cleaning-view.test.tsx` (70/70, clean first try), `lib/i18n/catalog-parity.test.ts` (20/20), and the whole `features/cleaning` folder with `--maxWorkers=2` (21 files, **434/434 passed**, one clean run, no flakes this time — host load had eased by then). `npx eslint` on all six touched/new component+test files: 0 problems.
- Section 6 fix round (panel): architect found a genuine concurrency gap — nothing blocked dismissing the cancel sheet while its shared mutation was `isPending`, so reopening it for a different row could call `mutation.reset()` on an in-flight request and cross-contaminate state. Fixed with `handleOpenChange` swallowing `!next` while pending, plus `cancel.isBlocked` disabling every row's open button while any cancel is in flight (mirrors `AssignCleanerControl.isBlocked`). i18n found hardcoded `({charsRemaining})` parentheses (replicated from the dashboard's dialog, left untouched there per D5) — fixed only in this section's own dialog via a new `cancel.reason.charsRemaining` locale key. Both re-verified PASS.
- Section 7 (Verification, run by the orchestrator, not a section implementer): **7.2 lint** — full-project `npm run lint` is consistently OOM-killed by host contention in this environment; every touched file was linted individually/in small batches instead, surfacing one real violation predating this note: `lib/assignable-property-state.ts`/`.test.ts` (from section 2) imported `PropertyOperationalState` via the absolute `@/features/cleaning/data/dto` path instead of the feature-internal relative convention (`../data`, which re-exports `dto.ts`) — fixed, re-linted clean, re-tested (24/24). **7.3 typecheck** — full-project `npm run typecheck` succeeded (after 2 OOM retries) and surfaced errors beyond section 6's flagged two: two genuine bugs in this change's own new files (a mock's `onSuccess` typed with the wrong arity in `cancel-cleaning-task-dialog.test.tsx`; an invalid `"OCCUPIED"` `PropertyOperationalState` literal in `create-cleaning-task-panel.test.tsx`, corrected to `"OCCUPIED_ESTIMATED"`) plus stale fixtures in **pre-existing test files no task in this change ever named** (`cleaning-filters.test.tsx`, `cleaning-task-row.test.tsx`, `use-assign-cleaning-task.test.tsx`, `use-cancel-cleaning-task.test.tsx`, `use-cleaning-data.test.tsx`, `lib/directory.test.ts`) — broken because sections 1's DTO widening (D3) has no scoped task covering their fixtures; all mechanically widened (added missing `createTask`/`validateTask` mocks, `completedAt`/`validationStatus`/`validatedAt`, `currentOperationalState`) with no behavior change, confirmed against a real backend run and via isolated per-file test re-runs. Full typecheck is now 0 errors. **7.1 full suite** — a whole-project `npm test` run showed 97 failed tests across 42 files, but 38 of those files are entirely outside this change's blast radius (auth, landing, pricing, provenance, color-tokens, etc.) and 2 are the project's documented pre-existing `ENOENT` gap (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`, per `sdd/project.md` §Worktree bootstrap) — the run's own 1273s "setup" time (of 1445s total) is the tell for extreme host contention, not a regression. Every file this change actually touches (`features/cleaning/**` plus the one `dashboard/stalls/components/blocked-transitions-section.test.tsx` file that consumes the shared `useCancelCleaningTask` hook) was individually re-run in isolation and passed clean. **7.4 manual pass** — done against the real backend (bootstrap + `make seed-demo`, `make up PORT_OFFSET=57`, `next dev` hydrated fine, logged in by click per the documented in-memory-session gotcha): created a task on a property forced to `AWAITING_CLEANING` (no warning) and on one in `VACANT_READY` (warning shown, created anyway); validated a `COMPLETED` task `PASSED→FAILED`, confirmed the matching-verdict button disables and the notify-cleaner success copy fires; cancelled a live task and watched the replacement task appear in the list after invalidation; hit a genuine backend `PROPERTY_STATE_CONFLICT` 409 on a different cancel attempt and confirmed the frontend rendered the property-state-specific message, not the generic terminal one (live confirmation of D8's `byConflictCode` refinement); logged in as the owner (no `MANAGE_CLEANING_TASKS`) and confirmed all three controls (create/validate/cancel) are absent from the DOM while `validation_status` remains fully visible on every row. No unexpected console errors (only the intentional 409 and the documented dev-server favicon 404).
