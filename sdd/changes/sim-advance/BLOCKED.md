# BLOCKED — sim-advance

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Verificación manual 6.4: sim-advance contra stack local con seed-demo

- **phase**: run
- **type**: deferred
- **tasks**: 6.4
- **what & why**: Requiere el stack docker-compose levantado y make seed-demo corrido contra una BD con datos; un run de /sdd:auto no levanta el stack real ni siembra datos de demo. La verificación automática (suite completa, rule11, typecheck) ya cubre el camino de código.
- **exact resume command**: /sdd:run sim-advance 6.4

## D1: nuevo campo Settings.environment / variable APP_ENVIRONMENT

- **phase**: design
- **type**: assumed
- **what & why**: R2.4 prohibía introducir una variable de entorno nueva SOLO SI Settings ya distinguía los entornos; no lo hacía, así que la prohibición no aplicaba. Opción tomada: Literal["local","dev","staging","production"] con default "local" (D1, design.md). Alternativas rechazadas: (a) usar BOOTSTRAP_TENANT_NAME como proxy de dev — circunstancial y frágil; (b) usar app_name o el tipo de storage — irrelevantes y opacos; (c) detectar por hostname/cgroup — no testeable. Recomendación tomada porque respeta el proposal y la steering; el veto humano sigue abierto en el PR.
- **exact resume command**: /sdd:review sim-advance

## docker-compose.deploy.yml's migrate service is missing the APP_ENVIRONMENT guard that backend/worker/beat now require

- **phase**: review
- **type**: decision
- **what & why**: Feature-scale review round 3 (receipt 4e26c43b, sha 9cf7212c): sdd-security FAIL. The round-1 fix added `APP_ENVIRONMENT: ${APP_ENVIRONMENT:?...}` to backend/worker/beat in docker-compose.deploy.yml so the R2/D5 environment guard can never silently fall back to Settings' permissive 'local' default in a deployed environment. The migrate service in the same file builds from the identical prod backend image but was not given that mapping. 'docker compose -f docker-compose.deploy.yml run --rm --no-deps -T migrate python -m app.cli.sim_advance --tenant <uuid> --at <instant>' against a deployed host would therefore see Settings.environment default to 'local', pass the D5 guard, and inject an operator-chosen clock into a real database -- exactly what R2's guard exists to prevent. This is not part of any design.md decision (D1-D6 name only backend/worker/beat), and fixing it would be this review's third fix round after round-1 and round-2 already landed (tasks.md Implementation Notes), which the review skill's two-round cap says to stop and hand to a human instead of auto-iterating again. A human should decide whether to add the same APP_ENVIRONMENT mapping to migrate (matching backend/worker/beat) or record why migrate is an accepted exception, and update design.md's Risk R5 accordingly.
- **exact resume command**: /sdd:review sim-advance
