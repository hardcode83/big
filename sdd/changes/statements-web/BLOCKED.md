# BLOCKED — statements-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Revisión arquitectónica automática no disponible

- **phase**: design
- **type**: deferred
- **what & why**: El reviewer sdd-architect no pudo iniciar: claude está instalado, pero la sesión headless responde «Not logged in · Please run /login». El gate obligatorio no puede cerrarse de forma segura sin ese reviewer.
- **exact resume command**: /sdd:auto statements-web
