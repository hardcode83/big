# BLOCKED — photo-storage-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual browser check of both photo galleries

- **phase**: run
- **type**: deferred
- **tasks**: 5.6
- **what & why**: Task 5.6 requires a running dev stack (make up PORT_OFFSET=N), real logins as TECHNICIAN/CLEANER to upload a photo and as PROPERTY_MANAGER/TENANT_OWNER to verify the two new read-only galleries render it on /incidents/[id] and /cleaning/[id], with no upload/delete control visible and the empty state correct. None of this is exercisable from a headless orchestrator session; gated for the user at PR time per the /sdd:auto rule on manual tasks.
- **exact resume command**: /sdd:run photo-storage-manager-view 5.6
