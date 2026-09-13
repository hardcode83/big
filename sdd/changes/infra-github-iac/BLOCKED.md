# BLOCKED — infra-github-iac

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## DESIGN-CONFLICT resolution (D11): App installation como bootstrap irreducible

- **phase**: run
- **type**: assumed
- **what & why**: El usuario dio autorización genérica ('no sabría decirte a o b, aplica el que consideres mejor opción') sobre el DESIGN-CONFLICT registrado antes. Opción elegida: (b) mover github_app_installation_repositories a bootstrap irreducible. Rationale: (a) introduce un PAT como excepción a D2 (D2 ya rechazó PAT por radio de daño + ADR 0002) — un fine-grained PAT con repo:write sobre un solo repo es menos dañino pero igualmente requiere rotación, secret store y monitorización. (b) no introduce credenciales nuevas, mantiene D2 limpia, y la instalación de la App es una acción one-time (no es un recurso sujeto a drift significativo); el job verify-ghcr de la sección 6 detecta en runtime si la App pierde los permisos que el CD necesita. Materializado como D11 en design.md. Documentos a actualizar por el round-1 fix: proposal.md §R4.1, design.md §D11 + tabla 'Changes by area', tasks.md §2.3, main.tf (remove github_app_installation_repositories; add merge flags). El merge flags finding (qa+architect) se aborda en el mismo round-1 fix: añadir allow_merge_commit, allow_squash_merge, allow_rebase_merge, allow_auto_merge, delete_branch_on_merge a github_repository.this.
- **exact resume command**: /sdd:run infra-github-iac
