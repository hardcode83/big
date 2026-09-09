# ci-pr-gates-optimization

[INFRA] **generalizar el patrón de conditional gate al resto de los gates de PR**. Precedente directo: [`ci-backend-tests-conditional-gate`](./ci-backend-tests-conditional-gate.md) (2026-08-03), que demostró que mover la decisión de área del disparador `on:` al interior del job elimina el coste de pagar suites que el diff no puede afectar, sin romper el invariante de que un check requerido se reporta en todo PR. Hoy solo `backend-tests` aplica ese patrón; este change lo extiende a `frontend-tests`, `compose-ports` y `rule11-ownership`, añade caché de Playwright keyed por lockfile, caché de capas Buildx en `multiarch-build-check` y `deploy-dev`, y consolida el `npm ci` redundante dentro de `frontend-tests.yml`. Sale también `pytest-cov` del grupo dev de `backend/pyproject.toml` como dependencia muerta (declarada, instalada, nunca invocada en CI).

## Por qué ahora

Una auditoría READ-ONLY sobre `origin/main` @ `888edfa4` midió costes reales (jobs-seg agregados vía `gh api ... actions/runs/{id}/jobs` sobre runs visibles entre `33657682515` y `33677211113`):

- **PR backend + frontend**: ~1.166 s jobs-seg = ~19 min agregados. Wall-clock del job más lento ~11 min.
- **PR de solo prosa** (la forma de todo commit de `/sdd:archive`): ~564 s = ~9 min agregados, dominados por `frontend-tests` (~390 s) + `provenance-contract` (~65 s) ejecutándose sobre un diff que no puede afectarlos.
- **`backend-tests-suite`** cuando corre: 508-712 s (peor caso 709 s en `run 33657682677`, PR #147); se salta legítimamente cuando el diff no toca `backend/**` y entonces el camino corto cuesta ~10 s.

El patrón ya existe y está probado en producción desde 2026-08-03. Lo que cambia es que la asimetría es cara y ya duele: `frontend-tests` carga Vitest + ESLint + typecheck + Playwright/Chromium en cada PR, y el comentario de cabecera del propio workflow dice literalmente *"si el frontend crece hasta doler, backend-tests.yml es el precedente a copiar"*. Ya duele. La salida no es inventar un modelo nuevo: copiarlo.

## Lo que esto cierra (y lo que NO)

**Cierra**:
- El `frontend-tests` deja de pagar su suite en PRs que no tocan frontend (`R1`).
- `compose-ports` y `rule11-ownership` aplican el mismo principio sobre sus áreas (`R5`).
- Playwright/Chromium se cachea por hash de `frontend/package-lock.json` (`R2`).
- Docker Buildx cachea capas por workflow en `multiarch-build-check` y `deploy-dev` (`R4`).
- `npm ci` corre una sola vez por ejecución de `frontend-tests` (`R3`).
- `pytest-cov` sale del grafo de dependencias (`R6`).
- Métricas before/after se publican (`R7`).
- Las invariantes de regresión demostrada se preservan: gate `alembic heads`, sonda de ingress, posture de red, fail-safe, SHAs pinneados, concurrency/timeouts (`R8`).

**NO cierra** (explícito, fuera de scope por decisión del usuario):
- Re-baselinar `BACKEND_SUITE_BUDGET_SECONDS` / `CEILING_SECONDS`. Cambiar esos umbrales no reduce minutos y podría ocultar la regresión histórica del runtime de la suite backend (205 → 424 → 709 s). Queda como follow-up de `backend-suite-runtime`.
- Investigar o resolver la regresión histórica de `backend-tests-suite`.
- Bajar coverage thresholds — no hay coverage threshold en CI; pytest-cov es dependencia muerta y se retira.
- Introducir nightly ni mover validaciones críticas a nightly.
- Cachear `node_modules` keyed por lockfile. La regla actual ("`npm ci` limpio, no `node_modules`") se preserva; R3 solo consolida el `npm ci` redundante.
- Detección de área para `api-contract` ni `frontend-api-contract`.
- Cambios en `infra-dev.yml`, `demo-reset.yml`, ni en la suite del backend (shape ni contenido).
- Cambios funcionales de AutoHostAI.

## Decisiones del usuario tras aprobar el proposal

1. **Registro en el roadmap**: sí, como entrada ad-hoc `[INFRA]` citando `ci-backend-tests-conditional-gate` como precedente y `backend-suite-runtime` como referencia adyacente (no dependencia).
2. **Caché de capas en `deploy-dev`** además de en `multiarch-build-check`: sí, dentro de R4, condicionada a preservar estrictamente las invariantes existentes de provenance/identidad de imagen. El design debe aclarar qué significa preservar identidad según las specs existentes y no exigir digest byte-identical si esa no es la invariante real.
3. **Cachear `node_modules`**: no. R3 se mantiene con `npm ci` limpio.
4. **Detección de área para `api-contract` y `frontend-api-contract`**: no en este change.

## Relación con entradas adyacentes

- **`ci-backend-tests-conditional-gate`** (cerrado, 2026-08-03): precedente directo. El patrón de tres jobs (`*-detect` / `*-suite` / check consolidador) que se replica.
- **`backend-suite-runtime`** (cerrado, 2026-08-10): referente adyacente. NO es dependencia — ataca la optimización del runtime de la suite del backend, lo que queda fuera de scope aquí. El runtime actual (~424-709 s vs. el peor caso histórico de 375 s documentado en `backend-suite-runtime`) sigue sin investigarse en este change.
- **`infra-github-iac`** (abierto, INFRA): candidato a futuro para gestionar GitHub-side como código; no es dependencia ni solapa con este change.

## Riesgo principal

El cambio toca **seis** workflows (frontend-tests, compose-ports, rule11-ownership, multiarch-build-check, deploy-dev, y el nuevo version-parity) y **retira** una dependencia. La superficie es amplia pero las decisiones son mecánicas (replicar el patrón de `backend-tests-detect`); el riesgo real es que la consolidación de jobs de `frontend-tests.yml` oculte alguna de las cinco señales que `provenance-contract` produce hoy. R3.3 lo previene con criterio explícito.

## Tamaño y categoría

- **size**: M — toca workflows y dependencias, sin migraciones ni cambios de modelo.
- **kind**: infra — es CI/CD.
- **plantilla**: sigue el patrón de `ci-backend-tests-conditional-gate` y `backend-suite-runtime`, con un alcance mayor pero una familia de decisiones ya probada.
