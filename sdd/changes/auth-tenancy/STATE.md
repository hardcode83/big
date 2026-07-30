---
schema: 1
state: PR_OPEN
local_review: APPROVED
repository: autohostai-labs/AutoHostAI
base_branch: main
head_branch: sdd/auth-tenancy
implementation_sha: dee1a4c39c631913ff34b0cbeb85e10ad8d7e769
pr_number: 25
pr_url: https://github.com/autohostai-labs/AutoHostAI/pull/25
pr_state: OPEN
merge_evidence: 
merge_sha: 
---

# Change lifecycle

Managed by the SDD lifecycle commands. Do not infer remote state without
checking the associated Pull Request.

## Condición de archivado impuesta en la revisión del PR (2026-07-30)

`auth-tenancy` **no se archiva** hasta que el estado de `timeline-state-machine` sea
coherente. Lo repara y archiva Marta **fuera** de este PR, y esa reparación no se mezcla
aquí. Es decir: aunque el PR #25 se mergee y `verify-merge` dé evidencia objetiva,
`/sdd:archive auth-tenancy` espera a que `sdd/changes/timeline-state-machine/` esté
archivado o con su estado corregido.

Motivo: `timeline-state-machine` está mergeado en `main` pero su change sigue en
`sdd/changes/` sin archivar, así que archivar este por delante dejaría las specs vivas
describiendo un orden de hechos que no ocurrió.

## Revisión humana aplicada (2026-07-30)

Los seis bloques de la revisión de Marta sobre el PR #25 están aplicados y registrados en
la tanda 11.10 de `tasks.md`. Tres de ellos cambiaron el alcance del change: R4.3 y la
matriz de R4.4 trasladados a `user-management` (design D15), bcrypt fuera del event loop
(D21 nueva) y el email como identidad global (ADR 0005). `local_review: APPROVED` se
refiere a la revisión local anterior; **la revisión humana de este PR sigue abierta** —
Marta vuelve a revisar la 11.9 y el conjunto.
