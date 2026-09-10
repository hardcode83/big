# BLOCKED — sim-advance

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Verificación manual 6.4: sim-advance contra stack local con seed-demo

- **phase**: run
- **type**: deferred
- **tasks**: 6.4
- **what & why**: Requiere el stack docker-compose levantado y make seed-demo corrido contra una BD con datos; un run de /sdd:auto no levanta el stack real ni siembra datos de demo. La verificación automática (suite completa, rule11, typecheck) ya cubre el camino de código.
- **exact resume command**: /sdd:run sim-advance 6.4
