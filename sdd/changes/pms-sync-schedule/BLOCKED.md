# BLOCKED — pms-sync-schedule

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## 5.3 verificación manual del sync programado end-to-end

- **phase**: run
- **type**: deferred
- **tasks**: 5.3
- **what & why**: Requiere un tenant sembrado, levantar el stack, y observar el segundo ciclo de beat (o disparar make pms-sync) para confirmar paridad de informe con el CLI manual e idempotencia (skipped=N). Bajo /sdd:auto, las tareas <!-- manual --> nunca se intentan ni se marcan: viajan con el PR (ADR 0006), y /sdd:archive las sigue exigiendo hechas.
- **exact resume command**: /sdd:run pms-sync-schedule 5.3

## delegated /sdd:review killed twice by host OOM

- **phase**: review
- **type**: deferred
- **what & why**: sdd_auto_outcome.py run '/sdd:review pms-sync-schedule' was OOM-killed twice in a row (first attempt, then one immediate retry per the headless-recipe ERROR row) while 3 peer sessions (tenant-settings-web-5a, properties-create-web-24, reviews-web-1e) held their own docker stacks. Environment contention, not a code/design/decision question — nobody has to decide anything, the host has to free up. Round-1 review fix (README documentation gap, sdd-review-documentation FAIL) is already committed and ready to be re-reviewed once a session can run without OOM.
- **exact resume command**: /sdd:review pms-sync-schedule
