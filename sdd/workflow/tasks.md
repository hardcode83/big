# Phase: tasks

Produce the implementation checklist. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

## Steps

1. **Load context.** Read `sdd/project.md`, the change's `proposal.md`, and `design.md` if it exists. If there is no proposal, stop and point to the new phase.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `tasks` and whose `applies_to` (if present) matches the change's scope.
2. **Write** `sdd/changes/<feature>/tasks.md` using `sdd/workflow/templates/tasks-template.md`. Rules:
   - Tasks are grouped in numbered sections, ordered so the system stays working after each section when possible.
   - Each task is a checkbox, small enough to complete and verify in one sitting, and states **which files** it touches and **which requirement(s)** it satisfies (`[R1]`).
   - Testing is part of the task that introduces the behavior, not a separate "write tests" section at the end. A final section covers integration/verification using the exact commands from `sdd/project.md`.
   - Only coding/verification activities — no "deploy to prod", "get approval" or meeting-shaped tasks.
   - Every requirement must be covered by at least one task; check this before finishing.
   - **Adopted in-flight work**: if part of the change is already implemented, include those tasks anyway and pre-check them `[x]` — but only after verifying each against the actual code (and its tests), noting `(preexistente)`. Never pre-check on the user's word alone.
3. **Gate.** Present the task list summary (sections + count), wait for approval, then suggest the run phase.
