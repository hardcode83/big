# BLOCKED — reservation-confirm-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Browser flow E2E (manager create → confirm → sim-advance → payment_status PARTIALLY_PAID, ES/EN, mutation error path)

- **phase**: run
- **type**: deferred
- **tasks**: 5.5
- **what & why**: Manual task: browser flow needs a running stack and a human operator with manager credentials; cannot be performed from the orchestrator session. Travels with the PR per ADR 0006; archive still requires it done.
- **exact resume command**: /sdd:run reservation-confirm-web 5.5
