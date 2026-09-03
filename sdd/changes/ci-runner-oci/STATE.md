---
schema: 1
state: ACTIVE
local_review: PENDING
qemu_verification: fallback — 2026-09-03 — QEMU no verificado en la VM (sin IP reachable, OCI CLI expirada, sin tfstate en este worktree). Adoptado el fallback explícito R4.2 / D5: `multiarch-build-check.yml` queda en `runs-on: ubuntu-latest`, runbook §2 declara "9 de 10 migrados, 1 excepción deliberada — QEMU no verificado". Ver `tasks.md` §1.2 y la nota en `## Implementation Notes`.
repository:
  base_branch:
  head_branch:
  implementation_sha:
  pr_number:
  pr_url:
  pr_state:
  merge_evidence:
  merge_sha:
---

# Change lifecycle

Managed by the SDD lifecycle commands. Do not infer remote state without
checking the associated Pull Request.  
