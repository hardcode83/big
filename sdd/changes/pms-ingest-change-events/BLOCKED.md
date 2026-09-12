# BLOCKED — pms-ingest-change-events

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual smoke: make pms-sync against demo tenant, verify /timeline event and property state

- **phase**: run
- **type**: deferred
- **tasks**: 4.6
- **what & why**: Requires a running stack with a browseable /timeline UI and manual fixture editing (moving SEED-AIRBNB-1's dates in the mock adapter) — not a command this worktree can verify unattended; automated coverage already proves the same scenario in tests/integrations/test_sync.py, test_pms_sync_cli.py and test_ingest_updates.py.
- **exact resume command**: /sdd:run pms-ingest-change-events 4.6
