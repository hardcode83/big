# BLOCKED — cleaning-manager-task-detail

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

`

## QA: Identificador block collapses pending and unavailable into a single string

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **severity**: low
- **referent**: R3.1
- **what & why**: `docs/cleaning.md:716` claims the Identificador block distinguishes a `cargando` (pending) marker from `Vivienda no disponible` (unavailable), but `detail-identifying-block.tsx:65-74` collapses both `pending` and `unavailable` into the single `detail.identifying.propertyNotFound` string. `lib/directory.ts` emits four Identity kinds (unassigned / pending / unavailable / resolved) and `detail-assigned-cleaner-block.tsx` distinguishes `pending` from `unavailable`; the identifying block does not.
- **fix**: Either implement the four-shape degradation in `detail-identifying-block.tsx` the same way `detail-assigned-cleaner-block.tsx` does (branch on `identity.kind === "pending"` → dash + sr-only `cargando`, `unavailable` → translated `propertyNotFound`), or rewrite the docs at `docs/cleaning.md:716` to drop the cargando branch.
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## QA: not-found back-link assertion is too loose to pin the round-1 F2 fix

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **severity**: low
- **referent**: R1.2
- **what & why**: `cleaning-task-detail-view.test.tsx:172` uses `expect(backLinks.length).toBeGreaterThanOrEqual(1)`. Reintroducing `description={t("detail.context.backToList")}` (the regression the round-1 fix removed) would still render exactly one `<a>` (the description becomes a `<p>`, the action remains the single anchor), so the duplicate-text defect would not be caught by this assertion.
- **fix**: Tighten to `expect(backLinks.length).toBe(1)` so any future regression that re-adds the duplicated text is caught.
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## QA: cancel-button disabled assertion does not pin the round-1 F4 CSS classes

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **severity**: low
- **referent**: R6.2
- **what & why**: `detail-manager-actions-block.test.tsx:132` uses `toBeDisabled()` only. A regression that strips the round-1 `disabled:opacity-50 disabled:cursor-not-allowed` classes from the raw `<button>` (`detail-manager-actions-block.tsx:145`) still passes — `toBeDisabled` checks the DOM `disabled` attribute, not the CSS classes that are the load-bearing piece of the F4 fix.
- **fix**: Add `expect(button).toHaveClass("disabled:opacity-50")` and `expect(button).toHaveClass("disabled:cursor-not-allowed")` (or `toHaveAttribute("class", expect.stringContaining("disabled:opacity-50"))`) so the visual disabled style is regression-protected.
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## QA: live region uses generic error copy regardless of HTTP status (R5.4)

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **severity**: medium
- **referent**: R5.4
- **what & why**: `cleaning-task-detail-view.tsx:189` (assign branch) and `:174` (validate branch) of `announcement()` always return `t("detail.error.unknown")` — the generic `'Ha ocurrido un error inesperado'` — for any failed mutation, regardless of HTTP status. The listing (`cleaning-view.tsx:342` uses `assignErrorKey(assign.error)`, `:315` uses `keyForStatus(validate.error, VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY)`) shows the status-specific message. Proposal R5.4 SHALL reads «WHEN una mutación termina con 403/404/409/422, THE SYSTEM SHALL mostrar el error traducido correspondiente por la región viva de la página»; `correspondiente` implies status-differentiated copy. The i18n keys `cleaning:assign.error.{forbidden,notFound,conflict,invalid,generic}` and the validate equivalents already exist in `locales/{es,en}/cleaning.json`. A user getting a 403 on assign currently sees the generic copy; a 422 likewise.
- **fix**: In `cleaning-task-detail-view.tsx announcement()`, import `assignErrorKey` from `../../lib/assign-error` and replace the assign error branch with `t(assignErrorKey(assign.error))`; import the matching helper for validate (`keyForStatus` + `VALIDATE_ERROR_TABLE` + `GENERIC_VALIDATE_ERROR_KEY`) and replace the validate error branch analogously. The cancel error path is exempt (already handled inside `CancelCleaningTaskDialog` per D7).
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## QA: validatedAt label is not status-specific (R2.3)

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **severity**: low
- **referent**: R2.3
- **what & why**: `detail-header-block.tsx:121-125` always renders `validatedAt` with the static label `t("detail.header.validatedAt")` (`'Fecha de validación'` / `'Validation date'`), regardless of `validation_status`. Proposal R2.3 SHALL reads «WHERE validation_status === "FAILED" y validated_at existe, THE SYSTEM SHALL mostrar, en todos los roles, la fecha y la etiqueta de "Validación rechazada"»; the implementation never paints the `'Validación rechazada'` label for FAILED tasks. The listing row (`cleaning-task-row.tsx:259`) shares the same gap, but the spec deliverable explicitly promised the FAILED-specific copy in the header.
- **fix**: In `detail-header-block.tsx`, accept `validationStatus` as a prop on the `validatedAt` branch (already on `DetailHeaderBlockProps`) and switch the label to a FAILED-specific key (e.g. `detail.header.validatedAtFailed` / `'Validación rechazada'` / `'Validation rejected'`) when `validationStatus === "FAILED"`; mirror in both `en` and `es`.
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## Manual browser pass of /cleaning/[id]

- **phase**: run
- **type**: deferred
- **tasks**: 7.4
- **what & why**: Task 7.4 requires a running dev stack (make up PORT_OFFSET=N + next dev), a real login (TENANT_OWNER + PROPERTY_MANAGER), and DevTools Rendering then Emulate CSS media to verify 320/360 px responsive behavior, the empty-state back link, owner-vs-manager control gating, and focus order. None of these can be exercised from a headless orchestrator session; they are gated for the user at PR time per /sdd:auto rule on manual tasks.
- **exact resume command**: /sdd:run cleaning-manager-task-detail 7.4
