# demo-tenant-audit-retention — BLOCKED queue

## Panel for the final close

- **phase**: run
- **type**: deferred (the flow can resume it)
- **what & why**: The full review panel (architect, security, qa, tenancy, cicd, documentation, i18n) was launched at the close of the run, but four agents failed with `Token Plan usage limit reached (2056)` and three were blocked at the classifier stage by the same upstream rate limit. Per the run skill, "a degraded panel beats a blocked run" — the implementation is in place and the test suite (366 tests) is green, but the panel's findings on the final close were not collected.
- **exact resume command**: `/sdd:review demo-tenant-audit-retention` (which can be re-launched once the rate-limit window resets; the run-time evidence is preserved in the test suite and the manual end-to-end run).

## Findings from `/sdd:review demo-tenant-audit-retention` (2026-08-26, verdict FAIL)

- **phase**: review
- **type**: decision (needs a human)
- **what & why**: The review panel surfaced a real conflict between the proposal R3.2 ("escribir esa fila **antes** del `DELETE`, de modo que sobreviva a un fallo del propio purgado") and the actual design + spec + test (atomic — the audit row only persists if the DELETE also persists, via the single `session.commit()` at `backend/app/cli/demo_reset.py:804`). The implementation comment at `:777-782` explicitly justifies the atomic choice ("the trail never describes a purge that did not actually happen"). The spec at `sdd/specs/demo-tenant.md:150` only requires temporal order; the proposal adds the survival requirement that nothing else enforces. A second finding flags the design D5 prose at `sdd/changes/demo-tenant-audit-retention/design.md:122-131` as factually wrong about the listener providing defense-in-depth for raw `text()` SQL — the listener at `backend/app/core/db.py` is ORM-only and does not cover `text(...)`; the actual defense is `require_session_bound_to` plus the explicit `WHERE tenant_id = :tenant_id` in the SQL.
- **exact resume command**: pick the resolution path before any `/sdd:ship` can run:
  - **Option A (drop survival from the proposal):** amend `proposal.md` R3.2 to remove "de modo que sobreviva a un fallo del propio purgado", keep `specs/demo-tenant.md` and the implementation as-is, and refresh the test to assert "atomic semantics" rather than "survival on failure". Re-run `sdd-review-security` and `sdd-architect` scoped to the change. `/sdd:review demo-tenant-audit-retention`
  - **Option B (make the audit row survive a failed DELETE):** amend `design.md` D6 + the implementation to `await session.commit()` after `audit.add(...)` and BEFORE `purge_old_audit_logs(...)`; add a test asserting the audit row is committed and persisted even when the DELETE raises. Re-run `sdd-review-tenancy`, `sdd-review-security`, and `sdd-architect`. `/sdd:review demo-tenant-audit-retention`
  - In both options also fix the D5 prose at `design.md:122-131` (the listener does NOT cover raw `text()` SQL) and the index-prefix claim at `design.md:246-248` (the covering prefix is `(tenant_id)`, not `(tenant_id, created_at)`).

## Resolution

- Delete this file once `/sdd:review demo-tenant-audit-retention` returns PASS.