# BLOCKED — infra-github-iac

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Run interrupted at section 1/8 — sections 2-8 pending

- **phase**: run
- **type**: deferred
- **what & why**: Section 1 (bootstrap & module scaffolding) is complete and panel PASS'd (commit ca36120d), con D3 amend posterior (`autohostai-tfstate-dev` compartido, key `github.tfstate`). Context budget exhausted mid-run; remaining sections not implemented: 2 (repository settings + App installation), 3 (Actions secrets import — hard), 4 (Actions variables + branch protection), 5 (RUNBOOK + first apply — hard, requires real GitHub App + credentials), 6 (CI workflow + GHCR verification job), 7 (specs + steering amendment), 8 (deploy-from-zero end-to-end verification — hard, requires credentials). Pre-requisito de sección 2: confirmar que el bucket `autohostai-tfstate-dev` existe con `versioning = enabled` (tarea 1.1 reconvertida a verificación).
- **exact resume command**: /sdd:run infra-github-iac
- **cómo reanudar en una sesión nueva**: `/clear` primero (libera el contexto del run anterior) y luego `/sdd:run infra-github-iac`. El orquestador detecta que la sección 1 está `[x]` con `panel: PASS` y empieza por la 2.

## DESIGN-CONFLICT: D2 + R4.1 incompatibles con provider v5.45.0

- **phase**: run
- **type**: decision
- **what & why**: El arquitecto del panel (revisión de sección 2) cita la doc oficial del provider v5.45.0: el recurso github_app_installation_repositories está marcado como 'not compatible with the GitHub App Installation authentication method'. D2 (design.md §D2) eligió autenticación del provider por la misma GitHub App del runner (app_auth), y R4.1 (proposal.md §R4.1) exige declarar la instalación de esa misma App con github_app_installation_repositories — los dos son incompatibles en la versión pinada. QA confirma también que R2.1 enumera 'los flags de merge que el repo enforce hoy' (allow_merge_commit, allow_squash_merge, allow_rebase_merge, allow_auto_merge), todos atributos válidos de github_repository v5.45.0, y los cuatro se han omitido en silencio (sin nota en Implementation Notes). El cambio no puede mergear sin una decisión sobre cómo resolver el conflicto de auth (las dos opciones que el arquitecto nombra — partir el provider en dos bloques con un PAT para un solo recurso, o reescribir R4.1 — tocan D2/R4.1 que son decisiones aprobadas por el humano; auto no puede adivinar). Pregunta concreta al humano: ¿(a) admitir un PAT scoped como única excepción a D2, declarado en un segundo provider block para github_app_installation_repositories únicamente (mantiene R4.1), o (b) sacar github_app_installation_repositories de Terraform y declararlo bootstrap irreducible en RUNBOOK.md (amenda R4.1 para reflejar 'App installation ya está gestionada por import de la instalación existente vía API, no como recurso Terraform')?
- **exact resume command**: /clear && /sdd:run infra-github-iac

## DESIGN-CONFLICT resolution (D11): App installation como bootstrap irreducible

- **phase**: run
- **type**: assumed
- **what & why**: El usuario dio autorización genérica ('no sabría decirte a o b, aplica el que consideres mejor opción') sobre el DESIGN-CONFLICT registrado antes. Opción elegida: (b) mover github_app_installation_repositories a bootstrap irreducible. Rationale: (a) introduce un PAT como excepción a D2 (D2 ya rechazó PAT por radio de daño + ADR 0002) — un fine-grained PAT con repo:write sobre un solo repo es menos dañino pero igualmente requiere rotación, secret store y monitorización. (b) no introduce credenciales nuevas, mantiene D2 limpia, y la instalación de la App es una acción one-time (no es un recurso sujeto a drift significativo); el job verify-ghcr de la sección 6 detecta en runtime si la App pierde los permisos que el CD necesita. Materializado como D11 en design.md. Documentos a actualizar por el round-1 fix: proposal.md §R4.1, design.md §D11 + tabla 'Changes by area', tasks.md §2.3, main.tf (remove github_app_installation_repositories; add merge flags). El merge flags finding (qa+architect) se aborda en el mismo round-1 fix: añadir allow_merge_commit, allow_squash_merge, allow_rebase_merge, allow_auto_merge, delete_branch_on_merge a github_repository.this.
- **exact resume command**: /sdd:run infra-github-iac
