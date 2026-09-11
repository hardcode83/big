# BLOCKED — reservation-create-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Auto bloqueado por límite semanal del runtime

- **phase**: auto
- **type**: deferred
- **what & why**: La receta oficial sdd_auto_outcome.py falló dos veces antes de iniciar cualquier fase por límite semanal de API; el runtime indica reset el 14 de septiembre a las 00:00 Europe/Madrid. No hay design, tasks ni implementación generados por auto.
- **exact resume command**: /sdd:auto reservation-create-web

## 6.5 Browser create/edit/cancel flow

- **phase**: run
- **type**: deferred
- **tasks**: 6.5
- **what & why**: Manual browser verification requires a running app plus manager/owner accounts and a mutation error path; this environment has no authenticated browser session.
- **exact resume command**: /sdd:run reservation-create-web 6.5

## Revisar contrato de catálogo i18n y referencia de change

- **phase**: review
- **type**: decision
- **what & why**: Tras dos rondas de correcciones y una tercera revisión completa, el panel sigue sin pasar: frontend/features/reservations/locales/reservations-locale.test.ts:91 espera 176 claves hoja pero ambos catálogos contienen 177, por lo que falla la suite enfocada; además README.md:397 conserva el identificador histórico reservations-web. La política auto limita el fix ladder a dos rondas y no permite una tercera edición automática. Decidir si se actualiza la aserción a 177 o se sustituye por una invariancia de paridad, y corregir/eliminar la referencia stale del README.
- **exact resume command**: /sdd:auto reservation-create-web
