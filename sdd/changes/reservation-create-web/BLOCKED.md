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

## Ejecutar harness browser de accesibilidad y responsive

- **phase**: review
- **type**: deferred
- **tasks**: 6.5
- **what & why**: La cobertura browser para keyboard/focus, contraste y clipping responsive está implementada en frontend/features/reservations/components/reservation-create-web.browser.test.tsx y usa el proyecto Vitest browser existente. La ejecución real quedó impedida porque el entorno no tiene el ejecutable Chromium de Playwright instalado: npm run test:layout termina antes de ejecutar tests con browserType.launch: Executable doesn't exist en ~/Library/Caches/ms-playwright. No se ha fabricado un resultado; instalar Chromium y repetir el harness es necesario.
- **exact resume command**: /sdd:run reservation-create-web 6.5
