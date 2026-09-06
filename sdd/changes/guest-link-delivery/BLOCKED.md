# BLOCKED — guest-link-delivery

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual end-to-end pass (task 6.5)

- **phase**: run
- **type**: deferred
- **tasks**: 6.5
- **what & why**: Requires a browser with two concurrent contexts (operator dashboard + guest portal) and a reachable dev SMTP relay/ConsoleEmailAdapter log — this orchestrator session has no browser access from the CLI/agent environment.
- **exact resume command**: /sdd:run guest-link-delivery 6.5
