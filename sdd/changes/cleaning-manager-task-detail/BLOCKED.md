# BLOCKED — cleaning-manager-task-detail

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual browser pass of /cleaning/[id]

- **phase**: run
- **type**: deferred
- **tasks**: 7.4
- **what & why**: Task 7.4 requires a running dev stack (make up PORT_OFFSET=N + next dev), a real login (TENANT_OWNER + PROPERTY_MANAGER), and DevTools Rendering then Emulate CSS media to verify 320/360 px responsive behavior, the empty-state back link, owner-vs-manager control gating, and focus order. None of these can be exercised from a headless orchestrator session; they are gated for the user at PR time per /sdd:auto rule on manual tasks.
- **exact resume command**: /sdd:run cleaning-manager-task-detail 7.4
