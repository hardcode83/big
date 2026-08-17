---
schema: 1
state: ACTIVE
local_review: PENDING
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

## Pendiente para `/sdd:archive` (no tocar en este PR)

El **quinto** sitio de R4.1, `sdd/specs/local-environment.md`, se corrige al archivar por
propiedad del archivado (design D13): líneas 141-148 (la afirmación de retención de puertos),
el matiz de la R de la línea 155 (`make compose-stacks` es host-side y deliberadamente fuera
de `$(COMPOSE)`, así que siguen siendo nueve los targets que hablan con Compose), una
sub-sección nueva de comportamiento del diagnóstico, y `scripts/compose-stacks.py` en Key
files. Con ella corregida, el grep de R4.3 —`grep -rniE 'retendiendo|reteniendo|quién
retiene|choca de puertos' --include='*.md' .`— debe quedarse sin ese acierto.
