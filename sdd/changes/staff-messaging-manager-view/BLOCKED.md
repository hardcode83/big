# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## 4.6 manual browser verification not run

- **phase**: run
- **type**: deferred
- **tasks**: 4.6
- **what & why**: No PROPERTY_MANAGER demo credentials are available in this worktree's .env (SEED_CLEANER_PASSWORD/SEED_TECHNICIAN_PASSWORD are empty and no seed manager password variable exists) — the login flow needs a real credential, and the task is explicitly <!-- manual -->. Static verification (306 incidents tests, 701 cleaning/cleaner tests, panel review) already exercises the same code paths the browser would.
- **exact resume command**: seed a demo manager user (e.g. via backend/app/cli/seed_demo.py with SEED_*_PASSWORD set), then log in at http://localhost:3000/login and exercise /incidents/[id] and /cleaning/[id] Messages tabs per task 4.6

