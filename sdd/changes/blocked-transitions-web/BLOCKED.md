# Blocked entries — blocked-transitions-web

## Section 5 — mutation hooks and dialogs

- **phase**: run
- **type**: deferred
- **what & why**: Section 5 (tasks 5.1-5.7) requires `BlockedTransitionResponse` to
  carry `cleaning_task_id` and `incident_id` so the cancel-cleaning and
  resolve-incident mutations can target a specific resource. The backend
  PR that adds those fields (design OQ1, approved at gate 2026-08-24) is not
  yet merged in `main` — verified 2026-08-24 by reading
  `frontend/lib/api/generated/openapi.d.ts:970`, which still declares only the
  six original fields. Without those ids:
  - `useCancelCleaningTask({ taskId })` is typed against a field the
    generated `openapi.d.ts` does not yet carry → typecheck red;
  - `useResolveIncident({ incidentId })` is typed against a field the
    generated `openapi.d.ts` does not yet carry → typecheck red;
  - the per-section test 5.6 (action buttons under each role's
    `useHasPermission`) fails to compose for the same reason.
  Sections 1-4 are unaffected: they ship the read path and the action map
  without mutation, so the card already shows stalls with informational rows
  (no buttons yet), matching what `cleaning-stall-blocks-next-stay` already
  promised.

  **Lifecycle-gate collision (surfaced 2026-08-24 during the run re-invocation
  that committed sections 1-4, 6 and 7.1-7.3):** the proposal's premise — that
  section 5 stays deferred while sections 1-4, 6 and 7.1-7.3 ship as a first
  PR — does not survive `sdd_lifecycle.py:ensure_local_gates` (line 332). That
  gate checks BOTH `tasks.md` (any `- [ ]` is a fail) AND `BLOCKED.md`
  (non-empty is a fail), so neither `mark-local-verified` nor `mark-ready`
  can fire while section 5 (and 7.4) are unchecked. The change as designed
  cannot reach `READY_FOR_PR` until section 5 is implemented. Two ways out:
  1. **Wait-and-resume**: hold this change until the OQ1 backend PR lands in
     `main`, then resume section 5 in the same PR. Matches the proposal's
     "flujo se parte y luego se reúne" wording.
  2. **Split**: cancel section 5 from this change, start a new
     `blocked-transitions-web-mutations` change once the OQ1 backend PR
     lands, ship sections 1-4, 6 and 7.1-7.3 as the first PR. Lets the
     read-only path reach `READY_FOR_PR` now.
  Both are explicit user decisions; the run phase has no way to pick between
  them. Task 7.4 (manual visual check) has the same gate collision but is
  scoped to dev, not to the OQ1 backend — it is the second unchecked task
  that blocks `READY_FOR_PR` under either option.
- **exact resume command**: depends on the recovery decision above.
  - *Wait-and-resume*: once the backend PR is merged in `main` and the
    regenerated `frontend/lib/api/generated/openapi.d.ts` carries
    `cleaning_task_id` / `incident_id`, run `/sdd:tasks blocked-transitions-web`
    (the tasks are already enumerated; the run skill will pick them up) and
    then `/sdd:run blocked-transitions-web` from section 5 onward, plus a
    manual pass for 7.4 in `dev`.
  - *Split*: send section 5 to `/sdd:new blocked-transitions-web-mutations`
    with a fresh proposal that scopes only tasks 5.1-5.7; archive this change
    once its read-only PR merges.

## Resolution procedure

- The `mark-ready` gate will reject any non-empty `BLOCKED.md` (rule from
  memory [[blocked-md-must-be-empty-to-ship]]); this file must be gone before
  `READY_FOR_PR`. Once the user picks a recovery path above and section 5 (and
  7.4) land — or section 5 is split into a new change — this file can be
  deleted.
