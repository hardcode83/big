# BLOCKED — dashboard-auto-refresh

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## RESOLVED — Auto headless no autenticado

- **phase**: auto
- **type**: deferred
- **what & why**: Los dos intentos de sdd_auto_outcome.py fallaron antes de iniciar el pipeline con terminal_reason=api_error: Not logged in. Hay que autenticar claude y reanudar el mismo auto.
- **exact resume command**: /sdd:auto dashboard-auto-refresh
- **resolution**: Superseded por decisión deliberada de continuar mediante las fases canónicas directas del toolkit en Codex; no es una dependencia técnica ni una decisión pendiente del change.

## 3.2 Suite frontend completa

- **phase**: run
- **type**: deferred
- **tasks**: 3.2
- **what & why**: La ejecución Docker de `cd frontend && npm test` queda sin resultado tras >8 min y termina con exit 137 (`Killed`). Reintentado el 2026-09-16: misma ventana, mismo exit 137, sin resumen de vitest; los tests focales de dashboard (`use-dashboard-data`, `dashboard-view`) salen en verde en la salida parcial, los 5 fallos parciales visibles son en `features/reviews/components/reviews-view.test.tsx`, `features/dashboard/components/property-card.test.tsx`, `features/pricing/components/pricing-pagination.test.tsx` y `features/landing/components/marketing-nav.test.tsx` — ninguno relacionado con `dashboard-auto-refresh`. El contenedor llega a ~700 % CPU y ~1,8 GiB RSS.
- **exact resume command**: /sdd:run dashboard-auto-refresh 3.2

## 3.3 Typecheck frontend

- **phase**: run
- **type**: deferred
- **tasks**: 3.3
- **what & why**: La ejecución Docker de `cd frontend && npm run typecheck` queda sin resultado tras >8 min y termina con exit 137 (`Killed`). Reintentado el 2026-09-16: misma ventana, mismo exit 137, sin diagnósticos de `tsc --noEmit`; el contenedor llega a ~1174 % CPU y ~1,8 GiB RSS durante la ejecución.
- **exact resume command**: /sdd:run dashboard-auto-refresh 3.3

## 3.4 Lint frontend

- **phase**: run
- **type**: deferred
- **tasks**: 3.4
- **what & why**: La ejecución Docker de `cd frontend && npm run lint -- features/dashboard` queda sin resultado tras >11 min y termina con exit 137 (`Killed`). Reintentado el 2026-09-16: misma ventana, mismo exit 137, sin diagnósticos de eslint; el contenedor llega a ~1100 % CPU. NOTA: `npm run lint` ejecuta `eslint .`, así que `-- features/dashboard` añade el directorio como **segundo target** y eslint analiza la raíz completa más `features/dashboard` por duplicado — usar `cd frontend && npx eslint features/dashboard` si se reintenta.
- **exact resume command**: /sdd:run dashboard-auto-refresh 3.4 (con la corrección de comando del "what & why")
