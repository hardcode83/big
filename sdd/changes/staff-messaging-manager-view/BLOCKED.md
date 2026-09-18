# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## 4.6 manual browser verification not run

- **phase**: run
- **type**: deferred
- **tasks**: 4.6
- **what & why**: No PROPERTY_MANAGER demo credentials are available in this worktree's .env (SEED_CLEANER_PASSWORD/SEED_TECHNICIAN_PASSWORD are empty and no seed manager password variable exists) — the login flow needs a real credential, and the task is explicitly <!-- manual -->. Static verification (306 incidents tests, 701 cleaning/cleaner tests, panel review) already exercises the same code paths the browser would.
- **exact resume command**: seed a demo manager user (e.g. via backend/app/cli/seed_demo.py with SEED_*_PASSWORD set), then log in at http://localhost:3000/login and exercise /incidents/[id] and /cleaning/[id] Messages tabs per task 4.6

## 4.2 pyright not green — deferral needs a human call

- **phase**: review
- **type**: decision
- **tasks**: 4.2
- **what & why**: uv run pyright . reports 963 pre-existing errors, all in backend/tests/timeline/* (test-fixture typing, e.g. a datetime passed where TimelineEventType/TimelineSeverity is expected). This change is frontend-only and touches zero backend files (verified: git diff main..HEAD -- . ':!frontend' ':!sdd' is empty), so these errors pre-date it. Backend pytest is fully green (11180 passed, 44 skipped). Task 4.2 requires pyright to be green and carries no <!-- manual --> marker, so sdd_lifecycle.py's own task-completion gate refuses record-review regardless of the existing 'deferred' BLOCKED entry for 4.2 (only a <!-- manual --> task can stay open via a deferred entry per the review skill's own rule). A human must choose how to unblock this: (a) accept the pre-existing backend/tests/timeline debt as out of scope for this frontend-only change and either check 4.2 or add a <!-- manual --> marker to it so the gate can pass, or (b) fix the 963 pre-existing pyright errors as their own tech-debt change before this one can reach READY_FOR_PR.
- **exact resume command**: Human decides: (a) authorize checking task 4.2 (or marking it <!-- manual -->) in sdd/changes/staff-messaging-manager-view/tasks.md as accepted pre-existing debt, then re-run /sdd:review staff-messaging-manager-view; or (b) fix backend/tests/timeline/* pyright errors as a separate tech-debt change first.
