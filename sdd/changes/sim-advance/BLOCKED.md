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

