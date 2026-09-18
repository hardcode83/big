# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## feature not in frontier (depends on cleaning-manager-task-detail which is PR_OPEN)

- **phase**: new
- **type**: decision
- **what & why**: Precondition 2 of /sdd:auto requires the named feature to be in the roadmap frontier. staff-messaging-manager-view declares needs: cleaning-manager-task-detail, which the report shows at status PR_OPEN. Auto never invents scope and never overrides a declared dependency.
- **exact resume command**: /sdd:auto staff-messaging-manager-view
