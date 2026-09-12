# BLOCKED — properties-create-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual E2E pass (create/edit/retire, both roles) needs the stack up

- **phase**: run
- **type**: deferred
- **tasks**: 7.4
- **what & why**: Task 7.4 requires 'make up' with a live browser session as PROPERTY_MANAGER and TENANT_OWNER; auto cannot drive an interactive browser session. Automated coverage (2914 tests across node+browser projects) verifies every documented behavior; this task verifies the real assembled UI end-to-end before shipping.
- **exact resume command**: /sdd:run properties-create-web 7.4
