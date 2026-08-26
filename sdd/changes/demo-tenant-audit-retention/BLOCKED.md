# demo-tenant-audit-retention — BLOCKED queue

## Panel for the final close

- **phase**: run
- **type**: deferred (the flow can resume it)
- **what & why**: The full review panel (architect, security, qa, tenancy, cicd, documentation, i18n) was launched at the close of the run, but four agents failed with `Token Plan usage limit reached (2056)` and three were blocked at the classifier stage by the same upstream rate limit. Per the run skill, "a degraded panel beats a blocked run" — the implementation is in place and the test suite (366 tests) is green, but the panel's findings on the final close were not collected.
- **exact resume command**: `/sdd:review demo-tenant-audit-retention` (which can be re-launched once the rate-limit window resets; the run-time evidence is preserved in the test suite and the manual end-to-end run).

## Findings from `/sdd:review demo-tenant-audit-retention` (2026-08-26, verdict FAIL → addressed)

- **phase**: review
- **type**: decision (now resolved by the two fix rounds — `589d98a` and `b10696b`; the only outstanding step is the user's call on whether to re-review or ship)
- **what & why**: Round 1 surfaced two blocking findings (R3.2 conflict between proposal text and design/spec/test; D5 prose wrongly attributed defense-in-depth to the ORM listener) plus two doc-precision fixes (index prefix, type hint). Both were resolved by the user choosing Option A in round 2: amend `proposal.md` R3.2 to drop the survival clause, rewrite D5 to name `require_session_bound_to` as the real guard with the explicit `WHERE` as visible redundant defense, fix the index prefix and the type hint. Round 2 (architect re-review) found 5 sites where code comments and test docstrings still propagated the OLD R3.2 wording — all 5 sites were rewritten to match the amendment (commit `b10696b`). The behavior was always correct; only the prose is now consistent.
- **exact resume command**: at this point the only thing left is to pick between two options:
  - **Option I — re-review to certify:** run `/sdd:review demo-tenant-audit-retention` once more. If the re-review passes, `mark-local-verified` → `mark-ready` → `/sdd:ship`. Cost: ~1 review round (≈ $9 + ~$45 for the underlying work, dominated by the panel).
  - **Option II — ship anyway:** the implementation is correct (verified by 366 tests in QA round 1), all known findings are addressed, and only docstring/comment precision is at stake. Per `blocked-md-must-be-empty-to-ship.md` the BLOCKED.md must be empty before `/sdd:ship`; deleting this file would lose the historical context but unblock ship.
  - Both options also fix the D5 prose at `design.md:122-131` (the listener does NOT cover raw `text()` SQL) and the index-prefix claim at `design.md:246-248` (the covering prefix is `(tenant_id)`, not `(tenant_id, created_at)`).

## Resolution

- Delete this file once `/sdd:review demo-tenant-audit-retention` returns PASS (Option I) or once the user explicitly accepts Option II.