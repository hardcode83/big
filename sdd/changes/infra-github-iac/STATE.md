---
schema: 1
state: CANCELLED
local_review: APPROVED
repository: autohostai-labs/AutoHostAI
base_branch: main
head_branch: sdd/infra-github-iac
implementation_sha: adfbc0a1627ce6359a64826352bbc3b66167ab3d
pr_number: 195
pr_url: https://github.com/autohostai-labs/AutoHostAI/pull/195
pr_state: CLOSED
merge_evidence:
merge_sha:
---

# Change lifecycle

Managed by the SDD lifecycle commands. Do not infer remote state without
checking the associated Pull Request.

## Cancellation (2026-09-13)

Closed PR #195 without merging. `verify-ghcr` (the job this change itself
added) ran for real against the GitHub App installation and failed minting
its installation token: `packages: write` is not actually granted to the
installation, contrary to what `infra/github/RUNBOOK.md` §1 assumes — the
push side of D9 never even ran. Given the doubt this raises about the App's
permission model, the decision is to shelve the change rather than deploy it.
The branch (`sdd/infra-github-iac`) and all work are kept as-is; no further
lifecycle command should run against this change unless it is explicitly
revived.
