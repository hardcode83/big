# BLOCKED — cleaner-list-property-projection

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Backfilled missing STATE.md (lifecycle bootstrap was skipped)

- **phase**: review
- **type**: assumed
- **what & why**: sdd/changes/cleaner-list-property-projection/STATE.md did not exist at all — the /sdd:new step-4 'sdd_lifecycle.py start' call was skipped when this change was created, even though proposal.md, tasks.md, and both implementation-section commits already existed and had valid panel receipts. record-review requires a committed parent STATE.md to transition from, so /sdd:review wrote the same initial ACTIVE state /sdd:new would have written (commit 4a8c5e44) and proceeded. No proposal/steering conflict: the change was clearly already active and mid-flight, so ACTIVE is the only state that fits.
- **exact resume command**: /sdd:review cleaner-list-property-projection
