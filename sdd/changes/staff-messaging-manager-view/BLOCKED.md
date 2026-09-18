# BLOCKED — staff-messaging-manager-view

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## worktree ENOENT copy workaround denied by auto-mode classifier

- **phase**: run
- **type**: deferred
- **what & why**: docker compose cp (project.md documented workaround for the 2 pre-existing worktree ENOENT test failures — provenance-contract.json and deploy-dev.yml, unrelated to this change's diff) was denied by the permission classifier as 'Modify Shared Resources'; the failures are pre-existing per project.md's own documentation and are not caused by this change's 3748/3749 passing frontend suite
- **exact resume command**: docker compose cp backend/openapi.json frontend:/backend/openapi.json (+ the other 8 cp commands documented in sdd/project.md Worktree bootstrap), then re-run npm test to confirm 3749/3749
