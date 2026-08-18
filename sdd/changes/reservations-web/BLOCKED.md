# BLOCKED — reservations-web

> Per shared rule 5: no pending work lives only in the conversation. Every
> unresolved item from this phase is recorded here before the phase ends,
> exactly as the rule requires. `/sdd:status` surfaces this queue first;
> `/sdd:archive` refuses to close a change with an unresolved entry.

## 1. Manual smoke test against the local stack (task 11.4)

- **phase**: review
- **type**: deferred
- **what & why**: `tasks.md:73` (task 11.4) is the manual verification of
  the `/reservations` and `/reservations/<id>` screens against a running
  stack (`make up` + login with a seed user + the 10 cases a–j). It is
  the only unchecked task in `tasks.md` and the lifecycle script
  (`mark-local-verified`) refuses to advance the change while it is open.
  The worktree has no stack and no browser — `sdd/project.md` §Worktree
  bootstrap documents this as a structural limitation of the worktree,
  not a defect. The QA reviewer flagged the same condition in the
  panel report ("no local stack in this environment"). The implementation
  is verified by the automated suite (469/469 tests, tsc, lint, build,
  api:check), the panel + re-review, and the fix of F1–F13; what remains
  is the human-in-the-loop smoke test against a live stack.
- **exact resume command**: `/sdd:review <feature>` after the user
  finishes the manual 10 cases and toggles `tasks.md:73` to `[x]`. The
  transition that follows is `mark-local-verified → mark-ready →
  validate-ship` (or `/sdd:ship reservations-web` if the user prefers
  to skip the typed transition).
- **also valid**: the user can run the 10 cases against a stack
  **outside the worktree** (the project's main checkout, or dev), and
  then mark the task complete in this worktree before re-launching
  `/sdd:review`.
