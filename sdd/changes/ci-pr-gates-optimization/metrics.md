# Metrics — ci-pr-gates-optimization

## Playwright cache verification (R2.4)

**Estado: pendiente de medición E2E.** No se simula localmente — requiere dos ejecuciones reales del workflow `frontend-tests.yml` sobre un PR real, lo que queda fuera del alcance de `/sdd:run` (ver sección 7/8 de `tasks.md`). Se ejecuta durante el pase E2E de `/sdd:ship` (sección 8 de `tasks.md`).

### Escenarios a verificar

**(a) Mismo lockfile → cache hit esperado.**
Dos ejecuciones consecutivas del workflow sobre el mismo SHA sin tocar `frontend/package-lock.json`. Resultado esperado: el log del step `Restore Playwright browser cache` (`id: cache-restore`) de la segunda ejecución muestra `cache-hit: true`, y el step `Save Playwright browser cache` se salta (`skipped`).

**(b) Lockfile distinto → cache miss esperado.**
Regenerar `frontend/package-lock.json` (p. ej. `npm install <paquete>@<nueva-versión>`, o borrar y reinstalar) para forzar un hash de key nuevo (`playwright-${{ hashFiles('frontend/package-lock.json') }}`). Resultado esperado: el siguiente run muestra `cache-hit: false` en `cache-restore`, el browser binary de Playwright se descarga de nuevo (el step de install corre siempre, con o sin cache — D3), y el step `Save Playwright browser cache` se ejecuta (`success`).

### Pasos exactos para la ejecución E2E (sección 8 de `tasks.md`)

1. Sobre el PR real abierto por `/sdd:ship`, empujar (push) dos veces sin tocar `frontend/package-lock.json`. Confirmar que el `cache-restore` de la segunda ejecución de `frontend-tests` muestra `cache-hit: true`.
2. A continuación, empujar un commit que regenere `frontend/package-lock.json` (p. ej. bump de versión de un paquete). Confirmar que la siguiente ejecución muestra `cache-hit: false` en `cache-restore` y que el binario del browser se descarga de nuevo.
3. Registrar ambos resultados (hit y miss) como entrada de baseline de cache hit rate en este archivo, en la sección de Baseline que añade la tarea 6.3.

**No** se usan cambios únicamente en `frontend/package.json` para demostrar cache miss: la key depende de `hashFiles('frontend/package-lock.json')`, no de `package.json`.

## Baseline (R7.1)

**Capturada el 2026-09-03**, antes del merge de este change, sobre la rama `sdd/ci-pr-gates-optimization`. `gh` está autenticado en esta sesión (`gh auth status` → `github.com` / `mreyesojeda`, scopes `repo`, `workflow`), así que la captura es de runs reales, no un placeholder.

**Método exacto de captura** (repetible, `autohostai-labs/AutoHostAI`):

```bash
# Lista de runs por workflow, últimos 15, solo eventos pull_request:
gh run list --workflow=<workflow>.yml --limit 15 -e pull_request \
  --json databaseId,conclusion,createdAt,headBranch,displayTitle

# Lista de runs por workflow, últimos 15, todos los eventos (para el ratio de fallos):
gh run list --workflow=<workflow>.yml --limit 15 \
  --json conclusion -q '.[].conclusion' | sort | uniq -c

# Duración por job de un run concreto:
gh run view <run-id> --json jobs \
  -q '.jobs[] | "\(.name) \(.conclusion) \(.startedAt) \(.completedAt)"'
```

Job-segundos por PR = suma de `completedAt - startedAt` de todos los jobs de un run. Wall-clock del job más lento = el máximo de esas duraciones dentro del mismo run. Los cinco workflows tienen `concurrency: cancel-in-progress: true`, así que los runs `cancelled` de la lista son *supersedidos* por un push posterior sobre la misma referencia, no fallos — se excluyen del cálculo de duración y se cuentan aparte.

**⚠️ Punto de partida asimétrico, y por qué importa para leer esta baseline.** En el momento de la captura, **solo `backend-tests.yml`** implementaba ya el patrón de tres jobs (`*-detect`/`*-suite`/`*-tests`) que este change replica a `frontend-tests.yml`, `compose-ports.yml` y `rule11-ownership.yml` — es el precedente real que este change generaliza. `multiarch-build-check.yml` **no** tenía caché de Buildx en el baseline: `git show HEAD:.github/workflows/multiarch-build-check.yml | grep -c cache` sobre `888edfa4` devuelve `0` — los scopes disjuntos con `mode=max` los **introduce** este change (§5/D4), igual que introduce el patrón de tres jobs en frontend/compose/rule11. Es decir: `frontend-tests.yml`, `compose-ports.yml`, `rule11-ownership.yml` **y `multiarch-build-check.yml`** estaban los cuatro en su forma pre-change en el momento de la captura (los tres primeros sin puerta de área condicional; `multiarch-build-check.yml` sin caché de Buildx) — la baseline de los cuatro mide el estado que este change reemplaza o extiende, no una muestra a medio migrar. Los tiempos crudos (job-segundos, wall-clock) de las cuatro tablas siguen siendo baseline pre-change válida (sin puerta de área / sin caché); solo cambia a qué grupo narrativo pertenece cada workflow. **Nota sobre los run IDs de muestra de `multiarch-build-check`:** `BLOCKED.md` ya registra que `origin/main` avanzó más allá de `888edfa4` tocando este mismo workflow (añadidos posteriores de `ci-runner-oci`/SMTP, ajenos a este change); los IDs de la tabla de abajo se capturaron el 2026-09-03 sobre la rama de este change y reflejan el estado sin caché de ese momento — no se re-etiquetan porque el diff propio de este change sobre ese fichero sigue siendo, verificado en `BLOCKED.md`, únicamente las 4 líneas `cache-from`/`cache-to`.

### backend-tests (ya con el patrón de 3 jobs — referencia de lo que el patrón cuesta)

Muestra de 5 runs `pull_request` con `conclusion=success` (ids `33788109392`, `33784004223`, `33767495153`, `33763207595`, `33677211027`):

| Métrica | Valor |
|---|---|
| Job-segundos/PR (detect + suite + consolidador) | 724s, 702s, 582s, 550s, 686s — media **648,8s** |
| Wall-clock del job más lento (`backend-tests-suite`) | 714s, 690s, 570s, 539s, 672s — media **637s (~10,6 min)** |
| Legit-skip/PR (suite `skipped` por detección de área) | **0/15** en la muestra de eventos `pull_request` — ningún PR de la muestra dejó de tocar `backend/**` |
| Fallos en `backend-tests` (últimos 15 runs, todos los eventos) | **0** `failure` — 9 `success`, 6 `cancelled` (supersedidos por concurrencia) |

### frontend-tests (pre-change: 2 jobs, sin puerta de área — lo que este change reemplaza)

Muestra de 5 runs `pull_request` con `conclusion=success` (ids `33788109436`, `33784004395`, `33767495475`, `33763207365`, `33677211007`):

| Métrica | Valor |
|---|---|
| Job-segundos/PR (`provenance-contract` + `frontend-tests`) | 431s, 461s, 480s, 470s, 467s — media **461,8s** |
| Wall-clock del job más lento (`frontend-tests`) | 374s, 405s, 412s, 402s, 398s — media **398,2s (~6,6 min)** |
| Legit-skip/PR | **no aplica** — el workflow pre-change no tiene puerta de área; corre siempre entero |
| Fallos en `frontend-tests` (últimos 15 runs de eventos `pull_request`) | **2** `failure` (ids `33762514148`, `33755114694`, rama `hardcode83/staff-messaging`) de 15 |

### compose-ports (pre-change: 1 job, sin puerta de área)

Últimos 15 runs, todos los eventos: **12 `success`, 3 `cancelled`, 0 `failure`**. No se capturó duración por job individual (el workflow pre-change no distingue detect/suite); el coste completo hoy es el de un solo job de `make check-compose-ports` + `pytest scripts/ -q`.

### rule11-ownership (pre-change: 1 job, sin puerta de área — deliberado, ver `specs/rule11-ownership-guard.md`)

Muestra de 5 runs `pull_request` con `conclusion=success` (ids `33788109376`, `33784004251`, `33767495059`, `33763207844`, `33755114805`):

| Métrica | Valor |
|---|---|
| Job-segundos/PR (job único) | 21s, 22s, 21s, 18s, 24s — media **21,2s** |
| Fallos (últimos 15 runs, todos los eventos) | **0** `failure` — 11 `success`, 4 `cancelled` |

### multiarch-build-check (pre-change: sin caché Buildx — baseline que este change reemplaza con scopes disjuntos `mode=max`, §5/D4)

Muestra de 5 runs con `conclusion=success` (ids `33788109370`, `33788076721`, `33763704150`, `33657682515`, `33638273161`):

| Métrica | Valor |
|---|---|
| Job-segundos/PR (`build-backend` + `build-frontend`) | 694s, 730s, 629s, 694s, 522s — media **653,8s** |
| Wall-clock del job más lento (`build-frontend`, siempre el más lento en la muestra) | 530s, 565s, 491s, 554s, 389s — media **505,8s (~8,4 min)** |
| Fallos (últimos 15 runs, todos los eventos) | **2** `failure` de 15 (13 `success`, 0 `cancelled`) |

### deploy-dev (referenciado por R7.1, no es uno de los cinco workflows afectados por este change — se dispara solo por `push` a `main`/`workflow_dispatch`, sin runs de evento `pull_request`)

Últimos 15 runs, todos los eventos: **4 `failure`, 2 `cancelled`, 9 `success`** — tasa de fallo **4/15 ≈ 26,7 %** en la ventana capturada. No se desglosa por job: `deploy-dev` no forma parte de los cinco workflows que este change modifica, se registra aquí solo porque R7.1 lo nombra explícitamente junto a `backend-tests`.

## Targets (R7.2, R7.3, R7.4)

**No bloquean `/sdd:run`, `/sdd:review`, `/sdd:ship` ni `/sdd:archive`.** Son métricas de efectividad a 30 días post-merge; este archivo existe para fijar la baseline de arriba al cierre del change y comparar después. `/sdd:archive` es quien, si procede, publica estos targets en `sdd/specs/backend-ci.md` y/o `sdd/specs/frontend-ci.md` (R7.4) — no se hace desde `/sdd:run`.

| Métrica | Target | Contraste con la baseline |
|---|---|---|
| Job-segundos/PR, PR solo-prosa (ningún workflow ejecuta su suite) | **≤ 120 s** | Ninguno de los cuatro `*-detect` (`backend-tests`, `frontend-tests`, `compose-ports`, `rule11-ownership`) mide hoy más de 25s aislado (rule11-ownership pre-change: 21,2s de media, job único); el target cubre la suma de los cuatro `*-detect` corriendo en paralelo sobre un PR de sola prosa. `multiarch-build-check` no tiene `*-detect` (mantiene `paths:`, D7). |
| Job-segundos/PR, PR que toca backend **y** frontend | **≤ 800 s** | Baseline: backend-tests solo ya promedia 648,8s; frontend-tests pre-change promedia 461,8s. La suma pre-change (sin condicionar) sería ~1.110s; el target exige que el patrón condicional y el único `npm ci` bajen el agregado por debajo de 800s en el caso que sí ejecuta ambas suites |
| Wall-clock del job más lento | **≤ 9 min** | Baseline: `backend-tests-suite` promedia 637s (~10,6 min), **por encima** del target — es la brecha más grande que revela esta baseline y el candidato más probable a necesitar ajuste de paralelismo (`-n`) o de alcance tras el merge |
| Suites por detect condicional | **≥ 4** | Los cuatro workflows con patrón `*-detect`/`*-suite` deben tener al menos 4 suites/señales agrupadas bajo su `*-suite` condicional; `frontend-tests-suite` ya agrupa 9-10 señales, `backend-tests-suite` corre la suite completa de pytest (docenas de tests), `compose-ports-suite` y `rule11-ownership-suite` agrupan guardia + pytest de scripts (2 señales cada uno hoy — candidato a revisar si el criterio se aplica por señal reportada y no por comando) |
| Descarga del browser binary de Playwright/PR en cache hit | **→ 0** | Verificación E2E diferida a `/sdd:ship` (sección "Playwright cache verification (R2.4)" arriba); esta baseline no mide descargas porque `frontend-tests.yml` pre-change no tenía caché de Playwright — el contraste real solo existe post-merge |
| Cache hit rate de Buildx en lockfile estable | **≥ 80 %** | Este change **introduce** `cache-from`/`cache-to` con scopes disjuntos (`multiarch-backend`, `multiarch-frontend`) en `multiarch-build-check` (§5/D4) — no existían en el baseline (`git show HEAD:.github/workflows/multiarch-build-check.yml | grep -c cache` = `0` sobre `888edfa4`); no se midió hit/miss por run en esta captura porque la caché aún no existía en el momento de la captura (`gh run view --json jobs` tampoco expone el estado de la cache de Buildx, a diferencia de `actions/cache` que sí publica `cache-hit` en sus outputs) — la medición real de este target requiere inspeccionar el log del step `docker/build-push-action` (`CACHED` vs. reconstrucción de capa) en runs post-merge, una vez la caché exista |

**R7.3 — sin métricas de cobertura.** Ninguna fila de esta tabla, ni de la sección Baseline, usa `pytest-cov` ni ningún dato de cobertura como criterio: este change retira `pytest-cov` de `backend/pyproject.toml` (tareas 1.1/1.2) precisamente porque no se invocaba en CI, y las métricas de éxito de este change son de tiempo de pipeline y de superficie de detección de área, no de cobertura de código.
## Registro de uso del toolkit (auto-generado)

> Estas filas las **añade automáticamente** `usage-phase.sh` del toolkit SDD: `sdd/changes/<feature>/metrics.md` es el *ledger* de uso que ese script escribe (una fila por fase). **No forma parte de las tablas Baseline/Targets de R7** — es telemetría de coste del change (tokens/coste por fase), separada aquí para que no se confunda con la evidencia de R7.1. Cada `/sdd:run`, `/sdd:review`, etc. añade una fila más al final de esta tabla.

| Fecha | Fase | Modelos | Tokens in | Tokens out | Cache | Coste (USD) | Nota |
|---|---|---|---|---|---|---|---|
| 2026-09-07 | run | claude-haiku-4-5-20251001 claude-opus-4-8 claude-opus-5 claude-sonnet-5 | 581501 | 939181 | 116619598 | 87.2357 | incl. subagents |
| 2026-09-07 | ship | claude-opus-4-8 claude-sonnet-5 | 34 | 13835 | 1861788 | 0.9545 | incl. subagents |
