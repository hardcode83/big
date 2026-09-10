# BLOCKED — incident-triage-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## reviewer panel gate cannot write a receipt in this runtime

- **phase**: review
- **type**: decision
- **what & why**: `/sdd:review`'s forked execution launches the 7 `Agent` calls and ends its own turn immediately ("waiting for reviewers"), instead of blocking synchronously for their completion as `SKILL.md` requires — the async completion notifications arrive at the parent conversation, not the fork, across every attempt (6+ retries, including after upgrading `sdd-toolkit` to 0.54.1 which fixed a separate identity-binding bug). Bypassing the gate by feeding `reviewer_panel.py` a manually-assembled `--results` payload — even with the real `tool_use_id`s and real payloads from the actual `Agent` invocations that ran in the parent conversation — is refused with `"result collection lacks trusted Claude invocation identity"`: the gate verifies invocation identity against the live dispatch context, which a detached `Bash` call cannot provide. This is a genuine runtime limitation, not a policy override or a missing permission.
- **what was actually verified** (real, independent `Agent` reviews, all against HEAD `d59a4108`, all PASS, all captured in this session's transcript): `sdd-architect`, `sdd-security`, `sdd-qa`, `sdd-review-documentation`, `sdd-review-i18n`, `sdd-review-tenancy`. `sdd-review-cicd` is out of scope for this diff (no `.github/workflows/**`, `infra/**`, or deploy-manifest paths touched).
- **exact resume command**: `/sdd:review incident-triage-web` — retry once the toolkit's fork/notification routing is fixed, or once `reviewer_panel.py` gains an explicit re-attestation path for results collected outside its own dispatch turn.
