# BLOCKED — reservation-create-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Auto bloqueado por límite semanal del runtime

- **phase**: auto
- **type**: deferred
- **what & why**: La receta oficial sdd_auto_outcome.py falló dos veces antes de iniciar cualquier fase por límite semanal de API; el runtime indica reset el 14 de septiembre a las 00:00 Europe/Madrid. No hay design, tasks ni implementación generados por auto.
- **exact resume command**: /sdd:auto reservation-create-web
