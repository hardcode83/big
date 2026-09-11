# BLOCKED — tenant-settings-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual E2E browser check of /settings across roles

- **phase**: run
- **type**: deferred
- **tasks**: 6.4
- **what & why**: Task 6.4 requires a running stack and a browser to exercise TENANT_OWNER/PROPERTY_MANAGER/CLEANER/TECHNICIAN flows on /settings; auto has no browser access in this worktree run.
- **exact resume command**: /sdd:run tenant-settings-web 6.4
