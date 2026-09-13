# BLOCKED — guest-scheduled-comms

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual end-to-end email verification (4.4)

- **phase**: run
- **type**: deferred
- **tasks**: 4.4
- **what & why**: Requires the dev stack up with seed/demo data giving a reservation inside each of the 24h/2h/checkout windows and an AccessRecord with a masked code, triggering each of the three new Celery tasks and confirming real emails arrive via the dev SMTP relay — an environment/manual-observation step the automated run cannot perform from this worktree.
- **exact resume command**: /sdd:run guest-scheduled-comms 4.4
