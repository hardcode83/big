# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## 4.6 manual browser verification not run

- **phase**: run
- **type**: deferred
- **tasks**: 4.6
- **what & why**: No PROPERTY_MANAGER demo credentials are available in this worktree's .env (SEED_CLEANER_PASSWORD/SEED_TECHNICIAN_PASSWORD are empty and no seed manager password variable exists) — the login flow needs a real credential, and the task is explicitly <!-- manual -->. Static verification (306 incidents tests, 701 cleaning/cleaner tests, panel review) already exercises the same code paths the browser would.
- **exact resume command**: seed a demo manager user (e.g. via backend/app/cli/seed_demo.py with SEED_*_PASSWORD set), then log in at http://localhost:3000/login and exercise /incidents/[id] and /cleaning/[id] Messages tabs per task 4.6

## 4.2 pyright not green (accepted pre-existing debt)

- **phase**: review
- **type**: deferred
- **tasks**: 4.2
- **what & why**: User decision 2026-09-18: uv run pyright . reports 963 pre-existing errors, all in backend/tests/timeline/* (test-fixture typing), unrelated to this frontend-only change (git diff main..HEAD -- . ':!frontend' ':!sdd' is empty). Backend pytest is fully green (11180 passed, 44 skipped). Accepted as out-of-scope debt; task 4.2 marked <!-- manual --> in tasks.md on that basis.
- **exact resume command**: fix or triage the 963 pre-existing pyright errors in backend/tests/timeline/* as its own tech-debt change; not blocking for staff-messaging-manager-view
