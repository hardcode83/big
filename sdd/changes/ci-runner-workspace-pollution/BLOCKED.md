# BLOCKED — ci-runner-workspace-pollution

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Aplicar el bootstrap en actions-runner-2 y verificar jobs reales

- **phase**: run
- **type**: deferred
- **tasks**: 6.4
- **what & why**: Necesita root en la VM dev real, systemd real y jobs reales de GitHub aterrizando en ese agente — inalcanzable desde este worktree
- **exact resume command**: /sdd:run ci-runner-workspace-pollution 6.4

## Extender el hook a los tres agentes restantes

- **phase**: run
- **type**: deferred
- **tasks**: 6.5
- **what & why**: Solo tiene sentido después de 6.4, y necesita la misma VM real
- **exact resume command**: /sdd:run ci-runner-workspace-pollution 6.5

## Comprobación de regresión del incidente original en un agente real

- **phase**: run
- **type**: deferred
- **tasks**: 6.6
- **what & why**: Requiere dejar un fichero de root en el _work/ real de un agente con el hook instalado y observar que actions/checkout ya no falla con EACCES — solo reproducible en la VM real
- **exact resume command**: /sdd:run ci-runner-workspace-pollution 6.6
