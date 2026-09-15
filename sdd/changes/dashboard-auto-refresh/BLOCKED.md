# BLOCKED — dashboard-auto-refresh

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Auto headless no autenticado

- **phase**: auto
- **type**: deferred
- **what & why**: Los dos intentos de sdd_auto_outcome.py fallaron antes de iniciar el pipeline con terminal_reason=api_error: Not logged in. Hay que autenticar claude y reanudar el mismo auto.
- **exact resume command**: /sdd:auto dashboard-auto-refresh
