# BLOCKED — pms-sync-schedule

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## delegated /sdd:review killed twice by host OOM

- **phase**: review
- **type**: deferred
- **what & why**: sdd_auto_outcome.py run '/sdd:review pms-sync-schedule' was OOM-killed twice in a row (first attempt, then one immediate retry per the headless-recipe ERROR row) while 3 peer sessions (tenant-settings-web-5a, properties-create-web-24, reviews-web-1e) held their own docker stacks. Environment contention, not a code/design/decision question — nobody has to decide anything, the host has to free up. Round-1 review fix (README documentation gap, sdd-review-documentation FAIL) is already committed and ready to be re-reviewed once a session can run without OOM.
- **exact resume command**: /sdd:review pms-sync-schedule
