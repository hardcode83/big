# BLOCKED — whatsapp-dev-credentials-render

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Verify Vault secrets and rendered .env live in dev

- **phase**: run
- **type**: deferred
- **tasks**: 5.4
- **what & why**: Task 5.4 requires a real 'infra-dev' apply and 'deploy-dev' run against the live OCI/GitHub environment (setting the four new Actions secrets with real Meta App values, running terraform apply, then confirming the four Vault secrets and the VM's rendered .env) — none of that is reachable from this worktree/session.
- **exact resume command**: /sdd:run whatsapp-dev-credentials-render 5.4
