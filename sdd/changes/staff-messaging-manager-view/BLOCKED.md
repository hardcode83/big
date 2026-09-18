# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## worktree ENOENT copy workaround denied by auto-mode classifier

- **phase**: run
- **type**: deferred
- **what & why**: docker compose cp (project.md documented workaround for the 2 pre-existing worktree ENOENT test failures — provenance-contract.json and deploy-dev.yml, unrelated to this change's diff) was denied by the permission classifier as 'Modify Shared Resources'; the failures are pre-existing per project.md's own documentation and are not caused by this change's 3748/3749 passing frontend suite
- **exact resume command**: docker compose cp backend/openapi.json frontend:/backend/openapi.json (+ the other 8 cp commands documented in sdd/project.md Worktree bootstrap), then re-run npm test to confirm 3749/3749

## 4.6 manual browser verification not run

- **phase**: run
- **type**: deferred
- **tasks**: 4.6
- **what & why**: No PROPERTY_MANAGER demo credentials are available in this worktree's .env (SEED_CLEANER_PASSWORD/SEED_TECHNICIAN_PASSWORD are empty and no seed manager password variable exists) — the login flow needs a real credential, and the task is explicitly <!-- manual -->. Static verification (306 incidents tests, 701 cleaning/cleaner tests, panel review) already exercises the same code paths the browser would.
- **exact resume command**: seed a demo manager user (e.g. via backend/app/cli/seed_demo.py with SEED_*_PASSWORD set), then log in at http://localhost:3000/login and exercise /incidents/[id] and /cleaning/[id] Messages tabs per task 4.6

## 4.2 pyright not green (pre-existing, unrelated to this change)

- **phase**: run
- **type**: deferred
- **tasks**: 4.2
- **what & why**: uv run pyright . reports 963 errors, all in backend/tests/timeline/* (test-fixture typing, e.g. a datetime passed where TimelineEventType/TimelineSeverity is expected). This change is frontend-only and touches zero backend files, so these errors pre-date it; fixing them is out of scope per scope discipline (implement only what tasks describe). Backend pytest is fully green (11180 passed, 44 skipped) confirming no runtime regression.
- **exact resume command**: fix or triage the 963 pre-existing pyright errors in backend/tests/timeline/* as its own tech-debt change; not blocking for staff-messaging-manager-view
