# BLOCKED — cleaning-manager-task-detail

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Documentation: add `Detalle operativo del manager` to docs/cleaning.md

- **phase**: review
- **type**: decision
- **reviewer**: sdd-review-documentation
- **severity**: high
- **referent**: `sdd/steering/documentation.md` — «docs/ — documentación extendida por capability… crear o actualizar su página `docs/<capability>.md` — orientada a *cómo se usa/opera*» + `design.md` §Changes by area (línea 307) que declara explícitamente como obligación de este change añadir la sección «Detalle operativo del manager» referenciando `/cleaning/[id]`.
- **what & why**: `git diff main..HEAD -- docs/` está vacío y un grep en `docs/cleaning.md` por «Detalle operativo», «cleaning-detail» o «/cleaning/[id]» no produce ningún resultado; la página de detalle operativa queda sin documentar para quien opere el módulo.
- **fix**: Añadir en `docs/cleaning.md` la sección «Detalle operativo del manager» que cubra cómo se usa `/cleaning/[id]` (lectura, tres controles del manager, región viva, errores por código HTTP), enlace al `CleaningTaskDetailView` ya construido, y un link a la futura `sdd/specs/cleaning-manager-task-detail.md` para no duplicar el contrato EARS.
- **exact resume command**: re-run `/sdd:review cleaning-manager-task-detail`

## Documentation: rewrite obsolete «no abre el detalle» in docs/cleaning.md:502-504

- **phase**: review
- **type**: decision
- **reviewer**: sdd-review-documentation
- **severity**: medium
- **referent**: `sdd/steering/documentation.md` §Checklist de archivado: «Ninguna doc referencia comportamiento eliminado por el change.»
- **what & why**: `docs/cleaning.md:502-504` dice «Lo que sigue sin ser: no abre el detalle de una tarea (checklist, fotos) ni edita plantillas.», describiendo la lista como algo que no lleva al detalle; este change añade el `<Link href={`/cleaning/${task.id}`}>` y la página `/cleaning/[id]`, así que el comportamiento «el listado no abre el detalle» deja de existir y la frase queda describiendo algo que el change eliminó.
- **fix**: Reescribir el cierre de §«Operar las limpiezas desde `/cleaning`» para indicar que cada fila enlaza a `/cleaning/[id]` y remitir a la nueva sección «Detalle operativo del manager»; reservar, si se considera, la mención de «checklist y fotos» como explícitamente diferidas a `photo-storage-manager-view` y `staff-messaging-manager-view`.
- **exact resume command**: re-run `/sdd:review cleaning-manager-task-detail`

## UI/UX: EmptyState description duplicates action link text (cleaning-task-detail-view.tsx:94)

- **phase**: review
- **type**: decision
- **reviewer**: sdd-review-ui-ux
- **severity**: medium
- **referent**: R1.2 + `sdd/steering/frontend.md`: Estados UI («Los elementos interactivos y de datos representan explícitamente loading, empty, error, disabled, hover y focus»)
- **what & why**: The not-found EmptyState passes both `description={t("detail.context.backToList")}` and `action={<Link>{t("detail.context.backToList")}</Link>}`; StatePanel renders the same localized string twice — once as a `<p>` after the title and once as the link — screen-reader duplicate and UX defect, does not match the «EmptyState title tarea no disponible + return link» shape R1.2 calls for.
- **fix**: Pass a separate descriptive sentence as `description` (e.g. an explanation of why the task is unavailable) and keep the localized back-to-list copy on the action link alone.
- **exact resume command**: re-run `/sdd:review cleaning-manager-task-detail`

## UI/UX: focus-visible suppression makes focus indistinguishable from hover (cleaning-task-row.tsx:197)

- **phase**: review
- **type**: decision
- **reviewer**: sdd-review-ui-ux
- **severity**: medium
- **referent**: `sdd/steering/frontend.md`: UI/UX baseline — «Focus visible: todo control interactivo tiene un estado de foco visible y distinguible del estado por defecto y hover; no se suprime `:focus-visible` sin una sustitución equivalente.»
- **what & why**: The Link wrapping the `<h3>` applies `focus-visible:underline focus-visible:outline-none`; outline is removed and the substitute (underline) is identical to the hover state (`hover:underline`), so focus is not distinguishable from hover. Also diverges from D10 / `incidents-view.tsx:139-145` precedent, which keeps the default focus ring without `focus-visible:outline-none`.
- **fix**: Drop `focus-visible:outline-none` (and either rely on the default focus-visible ring or pair the underline with a distinct visual cue such as a background tint) so the focus state is visibly different from hover.
- **exact resume command**: re-run `/sdd:review cleaning-manager-task-detail`

## UI/UX: CancelOpenButton missing visible disabled style (detail-manager-actions-block.tsx:142)

- **phase**: review
- **type**: decision
- **reviewer**: sdd-review-ui-ux
- **severity**: low
- **referent**: `sdd/steering/frontend.md`: Estados UI («disabled, hover y focus» explícito) + R6.2 mobile-first
- **what & why**: CancelOpenButton is a raw `<button>` with `disabled={isPending}` but no `disabled:opacity-50`/`disabled:pointer-events-none` style; the disabled state is visually indistinguishable from the enabled state. The shared `Button` used by the listing's cancel-open (`cleaning-task-row.tsx:289-296`) supplies that, and reusing it keeps the detail consistent with the listing pattern that R5.2/D7 require.
- **fix**: Use the shared `Button` (variant outline) like the listing row does, or add an explicit `disabled:opacity-50 disabled:pointer-events-none` to the raw element.
- **exact resume command**: re-run `/sdd:review cleaning-manager-task-detail`

## QA reviewer stalled mid-review

- **phase**: review
- **type**: deferred
- **reviewer**: sdd:sdd-qa
- **what & why**: The QA reviewer (`sdd:sdd-qa`) was interrupted mid-flight by the user (status: failed — `Agent stalled: no progress for 600s` per the watchdog), so it did not deliver a verdict on the change. The four completed lenses (architecture, security, i18n, documentation, ui-ux) are recorded above; QA is the missing sixth. Re-running `/sdd:review` will relaunch the QA reviewer alongside the others.
- **exact resume command**: /sdd:review cleaning-manager-task-detail

## Manual browser pass of /cleaning/[id]

- **phase**: run
- **type**: deferred
- **tasks**: 7.4
- **what & why**: Task 7.4 requires a running dev stack (make up PORT_OFFSET=N + next dev), a real login (TENANT_OWNER + PROPERTY_MANAGER), and DevTools Rendering then Emulate CSS media to verify 320/360 px responsive behavior, the empty-state back link, owner-vs-manager control gating, and focus order. None of these can be exercised from a headless orchestrator session; they are gated for the user at PR time per /sdd:auto rule on manual tasks.
- **exact resume command**: /sdd:run cleaning-manager-task-detail 7.4
