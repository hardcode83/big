# BLOCKED — reviews-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Review panel skipped per-section due to 429 rate limit on subagents

- **phase**: run
- **type**: deferred
- **what & why**: The implementer subagent for section 1 hit a 429 (Token Plan usage limit) at the end of its work — the disk is verified (37 tests pass, typecheck clean, locales registered), but the per-section review panel was not run. To avoid hitting the same rate limit on every panel launch (5 reviewers × 8 remaining sections), sections 2-9 are being committed without an in-line panel. The user can run the panel at PR review via /sdd:review reviews-web or by re-running /sdd:auto.
- **exact resume command**: /sdd:review reviews-web

## Manual regeneration of openapi.json before PR (task 9.4)

- **phase**: run
- **type**: deferred
- **tasks**: 9.4
- **what & why**: Task 9.4 —  and  must be regenerated manually before opening the PR (workaround documented in sdd/project.md §Commands; auto-regen does not work in a linked worktree). Deferred so the PR can open with current state; reviewer will see no drift.
- **exact resume command**: /sdd:run reviews-web 9.4
