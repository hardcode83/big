# BLOCKED — pms-sync-schedule

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## 5.3 verificación manual del sync programado end-to-end

- **phase**: run
- **type**: deferred
- **tasks**: 5.3
- **what & why**: Requiere un tenant sembrado, levantar el stack, y observar el segundo ciclo de beat (o disparar make pms-sync) para confirmar paridad de informe con el CLI manual e idempotencia (skipped=N). Bajo /sdd:auto, las tareas <!-- manual --> nunca se intentan ni se marcan: viajan con el PR (ADR 0006), y /sdd:archive las sigue exigiendo hechas.
- **exact resume command**: /sdd:run pms-sync-schedule 5.3
