# Proposal: ci-pr-gates-optimization

## Why

Una auditoría READ-ONLY sobre `origin/main` @ `888edfa4` (2026-09-02) midió el coste real de los gates de Pull Request en GitHub Actions y demostró tres hechos:

1. **No hay un coverage threshold de CI que debamos bajar.** `pytest-cov` está declarado como dependencia de desarrollo en `backend/pyproject.toml` (línea 66) pero **no se invoca en ningún workflow** (`grep -rn "pytest.*cov\|--cov" .github/workflows/` devuelve cero resultados). La cobertura no se calcula, no se acumula, no se compara contra umbral y no bloquea merges. Mover esa palanca no es una optimización posible — es optimizar algo que no existe. Lo que sí existe es la dependencia muerta (instalada en cada `uv sync` sin producir trabajo).

2. **El coste de PR está dominado por dos patrones reproducibles**: un PR que toca `backend/**` y `frontend/**` paga **≈ 1.166 segundos jobs-seg = ~19 min agregados**; un PR de solo prosa (`docs/**`, `sdd/changes/archive/...`, la forma de todo commit de `/sdd:archive`) paga **≈ 564 s = ~9 min agregados** sin que el diff pueda afectar a la suite que se ejecuta. La suite del backend es la excepción documentada — `ci-backend-tests-conditional-gate` ya movió la decisión de área del disparador al interior de la ejecución, con la regla "el check reporta siempre, el trabajo solo si toca el área"—, pero esa optimización **existe solo para el backend**.

3. **Hay palancas de bajo coste, ya identificadas por el propio repositorio, que el equipo no ha tirado**: el comentario de cabecera de `frontend-tests.yml` (líneas 4-13) declara literalmente *"si el frontend crece hasta doler, backend-tests.yml es el precedente a copiar"* — y ya duele (Vitest + Playwright + ESLint + typecheck suman ~390 s por PR); el mismo comentario (líneas 121-130) señala *"cachear `~/.cache/ms-playwright` por versión de playwright, o partir el job"*; `multiarch-build-check` y `deploy-dev` construyen imágenes de Docker sin `cache-from: type=gha` documentado. Cada una de estas palancas reduce minutos sin tocar tests, sin relajar cobertura y sin debilitar TDD.

El principio del change es uno que ya está declarado en `specs/backend-ci.md` (R2.4, *"la detección arranca en «sí toca» y solo una comprobación afirmativa la baja a «no toca»"*): **ejecutar el mismo nivel de validación cuando el área está afectada; evitar ejecutar trabajo caro cuando pueda demostrarse que el diff no puede afectarla; ante ambigüedad, ejecutar el gate.** Aplicarlo a los demás gates de PR cierra la asimetría actual sin inventar un modelo nuevo.

**Evidencia fuente** (auditoría completa, no se copia aquí para no duplicar):
- Tabla `A. Estado actual`, ranking `B. Top consumidores`, problemas `C.1-C.6`, métricas baseline `G`, propuesta arquitectónica `D`, quick wins `E`, riesgos `F` y scope `H` — recogidos durante esta misma sesión sobre `origin/main`.
- Ejecuciones observadas vía `gh api repos/autohostai-labs/AutoHostAI/actions/runs/{id}/jobs` (runs `33657682677`, `33663822125`, `33660426625`, `33677211027`, `33677211007`, `33677210989`, `33677210913`, `33677211084`, `33677211113`, `33657682515`, `33660426613`, etc.).

## What changes

Al cierre de este change existirá una sola capability observable: **un PR a AutoHostAI paga minutos de GitHub Actions proporcionales al área que su diff puede afectar**, sin que ningún gate crítico pierda señal sobre su área. Concretamente:

- `frontend-tests` adoptará el patrón de tres jobs (`*-detect` / `*-suite` / `*-tests`) ya usado por `backend-tests`, decidiendo dentro del job si el diff toca `frontend/**`, `frontend/devops/Dockerfile`, `frontend/package*.json` o el propio workflow. El check `frontend-tests` se seguirá reportando siempre.
- `frontend-tests` cacheará `~/.cache/ms-playwright` keyed por `frontend/package-lock.json`, evitando la descarga de ~180 MiB de Chromium en cada PR.
- `frontend-tests` reducirá trabajo redundante entre sus dos jobs actuales (`provenance-contract` y `frontend-tests`) consolidando `npm ci` (hoy corre dos veces por PR) y reusando el `next build` allí donde aporte señal.
- `multiarch-build-check` activará caché de capas de Docker Buildx (`cache-from: type=gha,scope=…`) para backend y frontend, con `cache-to: type=gha,mode=max` cuando proceda.
- `compose-ports` y `rule11-ownership` aplicarán la misma decisión de área dentro del job, con la misma forma *"arranca en sí, baja solo con afirmación positiva"*.
- `pytest-cov` dejará de declararse como dependencia de desarrollo (dependencia muerta que ya no se invoca en CI), con nota explícita en el design de que **no** se introduce cobertura real en este change — eso queda para el nightly o un change posterior, y no como gate.

Lo que **no** cambiará: el shape ni el contenido de la suite del backend; las versiones pinneadas de las actions (`actions/checkout@<sha>`, etc.); las invariantes de R1.5 (cadena de provenance idéntica en las dos imágenes) ni R1.6 (sonda de origen desde la red de ingress); la regla `no paths en on:` de `specs/backend-ci.md`; el TDD, las reglas de `steering/testing.md` ni las de `steering/security.md`.

## Requirements

### R1 — Detección de área para `frontend-tests`

**As a** mantenedor que abre un Pull Request que solo toca prosa (`docs/**`, `sdd/changes/**`),
**I want** que `frontend-tests` ejecute su suite solo cuando el diff puede afectarla,
**so that** mi PR no pague ~6 minutos de Vitest + Playwright + build de Next para verificar un árbol que no cambió.

Acceptance criteria:

1. WHEN se ejecuta el workflow `frontend-tests` sobre un Pull Request, THE SYSTEM SHALL reportar **siempre** un resultado del check `frontend-tests` (lo ejecute o lo salte), copiando el invariante declarado en `specs/backend-ci.md` (R1.3): un required check que no se ejecuta deja el PR bloqueado esperando indefinidamente.
2. WHEN se ejecuta el workflow sobre un Pull Request, THE SYSTEM SHALL decidir dentro del workflow (no en `on:paths:`) si el diff toca alguna dependencia de la suite: `frontend/**`, `frontend/devops/Dockerfile`, `frontend/package.json`, `frontend/package-lock.json`, **`scripts/**`** (el árbol de scripts entero — la suite ejecuta `scripts/validate-provenance-contract.py` y `scripts/check-version-parity.py`; se ancla en bloque, como hacen `compose-ports`/`rule11-ownership`, §13-A/design D1.1.d), `.github/scripts/**` (del que `extract-pr.sh --self-test` es señal), `Makefile` (que define el target `check-version-parity`) o `.github/workflows/frontend-tests.yml`. La superficie de detección SHALL ser un superconjunto de la superficie de dependencias de la suite (design D1.1): un PR que modifica solo un guard ejecutado por la suite no puede recibir un `**OMITIDA**` verde sin ejecutarlo.
3. WHEN el diff **no** toca ninguno de los anteriores, THE SYSTEM SHALL saltarse los pasos que ejecutan la suite del frontend (Vitest, Playwright, ESLint, typecheck, build de producción para divulgación) y publicar el check en verde con un motivo legible ("`no-frontend-changes`" o equivalente).
4. WHEN el diff **sí** toca cualquiera de los anteriores, THE SYSTEM SHALL ejecutar la verificación completa sin recortarla.
5. IF la detección no puede determinar el área (evento sin SHAs, force-push, fallo de `git diff`), THEN THE SYSTEM SHALL decidir **a favor de ejecutar la suite** — la decisión arranca en `true` y solo una comprobación afirmativa la baja.
6. THE SYSTEM SHALL usar `git -c core.quotePath=false diff -z --no-renames --name-only` para derivar el conjunto de ficheros cambiados, replicando la lógica ya probada de `backend-tests-detect` (mismo riesgo: rutas no ASCII escapadas y renombrados colapsados a destino).
7. THE SYSTEM SHALL emitir el veredicto del check en `GITHUB_STEP_SUMMARY` con: suite ejecutada u omitida, motivo, decisión de área, y (cuando aplique) duración de `npm test` y de `npm run test:layout`.
8. WHILE `frontend-tests` pasa a ser condicional por área, THE SYSTEM SHALL conservar la comprobación de paridad de versión (`make check-version-parity`, sobre `VERSION` + `backend/pyproject.toml` + `frontend/package.json`) como un check **always-run** en cada Pull Request — un gate propio `.github/workflows/version-parity.yml` sin `paths:` ni detect gate — porque antes de este change corría siempre dentro de `frontend-tests` y sus inputs (`VERSION`, `backend/pyproject.toml`) no los cubre ningún otro gate de PR; gatearla tras `frontend-tests-detect` la convertiría en un fail-open para un bump de versión que no toque `frontend/**` (design D1.1 SEC-2). La copia dentro de `frontend-tests-suite` se conserva como belt-and-suspenders.

### R2 — Caché de Playwright en `frontend-tests`

**As a** mantenedor que abre cualquier Pull Request,
**I want** que `frontend-tests` reuse el binario de Chromium entre ejecuciones,
**so that** la instalación no domine el wall-clock del job.

Acceptance criteria:

1. WHEN `frontend-tests` prepara el binario de Chromium para `npm run test:layout`, THE SYSTEM SHALL restaurar la caché `~/.cache/ms-playwright` desde un cache hit keyed por el hash de `frontend/package-lock.json` (no por `latest`, para no exponer el binario a cambios fuera del lockfile).
2. WHEN el cache hit no existe, THE SYSTEM SHALL ejecutar `npm exec --no -- playwright install --with-deps chromium` y guardar el resultado en la caché keyed por el mismo hash.
3. THE SYSTEM SHALL **no** invocar `npx playwright install …`: `npx` puede descargar del registro una versión no pinneada por el lockfile cuando el binario no está en `node_modules`, lo que un PR que quite `playwright` del manifiesto convertiría en *"baja del registro la versión del día y ejecútala con `--with-deps`"* bajo el sudo del runner (riesgo ya documentado en `frontend-tests.yml:131-139`).
4. WHILE la caché esté disponible, THE SYSTEM SHALL NOT **volver a descargar el binario** de Playwright: el paso de install se ejecuta **siempre** (en cache hit y en cache miss) pero es un **no-op sobre el binario** en cache hit —Playwright verifica el SHA del binario en `~/.cache/ms-playwright` y sale sin descargar, y `apt-get --with-deps` es idempotente—. El instalador NO se condiciona a `cache-hit` (design D3, rechazado explícitamente saltarlo entero: eso omitiría la verificación de librerías de sistema `--with-deps`, un fallo opaco al runner). *(Enmendado tras QA-review 2026-09-05 para que el criterio describa el comportamiento razonado en D3 e implementado en `tasks.md` 2.2, en vez del literal anterior "SHALL NOT volver a invocar el instalador", que el código deliberadamente no cumple.)*

### R3 — Eliminación de trabajo redundante dentro de `frontend-tests`

**As a** mantenedor,
**I want** que `frontend-tests` ejecute `npm ci` una sola vez por PR y reuse su resultado entre sus pasos,
**so that** los ~30-60 s de la segunda instalación desaparezcan del wall-clock.

Acceptance criteria:

1. WHEN `frontend-tests` prepara el entorno del frontend, THE SYSTEM SHALL ejecutar `npm ci` **una sola vez** por ejecución (hoy corre dos veces: una en `provenance-contract`, otra en el job `frontend-tests`).
2. WHEN los pasos siguientes necesiten el árbol de `node_modules`, THE SYSTEM SHALL SHALL NOT volver a invocar `npm ci`.
3. THE SYSTEM SHALL SHALL NOT cambiar el contenido de `provenance-contract` (las cinco señales que produce: version-parity, extractor de PR, validador de provenance, suite de provenance, divulgación de artefactos públicos): si se mueven pasos entre jobs, las cinco señales se conservan.

### R4 — Caché de capas Docker Buildx para `multiarch-build-check` y `deploy-dev`

**As a** mantenedor,
**I want** que las imágenes `prod` de backend y frontend reusen capas entre ejecuciones,
**so that** el build no reconstruya desde cero lo que el lockfile no cambió.

Acceptance criteria:

1. WHEN `multiarch-build-check` ejecuta `docker build-push-action@v6` para `build-backend` o `build-frontend`, THE SYSTEM SHALL restaurar capas desde `cache-from: type=gha,scope=<workflow>` antes de empezar el build.
2. WHEN termina el build, THE SYSTEM SHALL SHALL persistir las nuevas capas a `cache-to: type=gha,mode=max,scope=<workflow>` (modo `max` en CI público y privado con `mode=max` documentado).
3. WHEN `deploy-dev` ejecuta sus builds de producción, THE SYSTEM SHALL aplicar la misma caché con scope dedicado (`deploy-dev`).
4. THE SYSTEM SHALL SHALL NOT cambiar las etiquetas OCI ni la cadena de provenance (R1.5): el `org.opencontainers.image.revision` debe seguir siendo el SHA del PR, y la identidad legible con `docker inspect` debe coincidir bit-a-bit con la imagen de antes del cambio para el mismo SHA (verificable comparando `docker inspect` de la misma etiqueta).
5. THE SYSTEM SHALL SHALL NOT habilitar el cache de capas para builds que produzcan imágenes **distintas** del SHA actual — la identidad no se negocia.

### R5 — Detección de área para `compose-ports` y `rule11-ownership`

**As a** mantenedor,
**I want** que `compose-ports` y `rule11-ownership` ejecuten su trabajo solo cuando el diff puede afectarlas,
**so that** un PR que no toca la prosa de seguridad ni la configuración de compose no pague su coste.

Acceptance criteria:

1. WHEN se ejecuta `compose-ports`, THE SYSTEM SHALL decidir dentro del workflow si el diff toca **toda la familia de descubrimiento por defecto de Docker Compose** — `compose.yaml`, `compose.yml`, `compose.override.yaml`, `compose.override.yml`, `docker-compose*.yml`, `docker-compose*.yaml`, `docker-compose.worktree.yml` — porque `scripts/compose-ports.py` corre `docker compose config` **sin `-f`** y Compose resuelve esos nombres (los `compose.*` con precedencia sobre `docker-compose.yml`); más **`scripts/**`** (la suite corre `pytest scripts/ -q` sobre el árbol entero, además de `make check-compose-ports` → `scripts/compose-ports.py`), **`Makefile`** (define el target `check-compose-ports`) o `.github/workflows/compose-ports.yml`. La superficie de detección SHALL ser un superconjunto de la superficie de dependencias de la suite (design D1.1/D1.1.b), y esa cobertura SHALL verificarse always-run (D1.1.c).
2. WHEN se ejecuta `rule11-ownership`, THE SYSTEM SHALL decidir dentro del workflow si el diff toca la superficie de dependencias de la suite, que es la unión de (a) el corpus que la guardia recorre —todo su `SCOPE` en `scripts/rule11-ownership.py:136-230`: census prose `sdd` menos las exclusiones (`sdd/steering/**`, `sdd/specs/**`, `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md`; NO `sdd/changes/**` ni `sdd/roadmap*`, que la guardia excluye) y `docs/**`; census code `backend/app/**`, **`backend/alembic/versions/**`**, `backend/tests/**` y **`scripts/**`**— y (b) el código que la suite ejecuta: `scripts/rule11-ownership.py` + `scripts/test_rule11_ownership.py` (dentro de `scripts/**`) y **`Makefile`** (target `check-rule11-ownership`); más `.github/workflows/rule11-ownership.yml`. El `SCOPE` de la guardia acota lo que *mira*, pero la superficie de detección debe anclar **también los ficheros que la ejecutan**: anclar solo un subconjunto de `SCOPE` deja fail-open a un PR que solo toca `scripts/rule11-ownership.py` o una migración en `backend/alembic/versions/**` (design D1.1). La superficie de detección SHALL ser un superconjunto de la superficie de dependencias de la suite. Como el detector **enumera** las rutas de prosa de `sdd/` (en vez de anclar `sdd/*` recursivo, para preservar el ahorro de R7 excluyendo `sdd/changes/**` y `sdd/roadmap*`), THE SYSTEM SHALL mantener un test automatizado (`scripts/test_rule11_ownership.py`) que verifique la invariante `relevant-SCOPE-walked-surface(rule11) ⊆ detect-anchor-surface(rule11)` — respetando las exclusiones deliberadas — de modo que una ruta relevante nueva bajo `sdd/` que la guardia recorrería pero el detector no activaría haga **FALLAR** el test en vez de permitir un fail-open silencioso (design D1.1.a).
3. BOTH workflows SHALL reportar siempre un resultado del check (mismo invariante que R1.1 y que R1.3 de `backend-tests`).
4. IF la detección no puede determinar el área, THEN THE SYSTEM SHALL ejecutar el trabajo (arranca en sí).
5. THE SYSTEM SHALL verificar, **always-run y antes de que el detector publique su decisión de skip** (como paso del propio job `*-detect`, que corre siempre), la invariante `detect-surface ⊇ superficie-de-entrada-de-la-suite` para `frontend-tests`, `compose-ports` y `rule11-ownership`; un incumplimiento SHALL abortar el job `*-detect` y hacer que el consolidador reporte **fail-closed** (rojo), no fail-open. Ningún guard destinado a detectar una ampliación futura de superficie SHALL vivir únicamente dentro de la suite condicional que el propio detector puede omitir (invariante temporal, design D1.1.c). THE SYSTEM SHALL incluir tests que **fallen** si en el futuro: (a) una suite crece su superficie de entrada sin ampliar su detector; (b) se añade una ruta Compose reconocida por el descubrimiento por defecto pero no anclada; (c) un check de invariante se mueve detrás de una suite condicional; (d) un detector devuelve `skip` ante un input que altera el resultado del gate.

### R6 — Retirada de `pytest-cov` como dependencia muerta

**As a** mantenedor,
**I want** que `pytest-cov` deje de figurar como dependencia de desarrollo,
**so that** el grafo de `uv sync` no incluya un paquete que CI no invoca.

Acceptance criteria:

1. THE SYSTEM SHALL SHALL NOT invocar `pytest --cov` ni ningún flag de cobertura en ningún workflow (verificado por `grep -rn "pytest.*cov\|--cov" .github/workflows/`).
2. THE SYSTEM SHALL SHALL NOT introducir un umbral de cobertura en este change — eso queda para un change posterior que lo justifique con evidencia.
3. THE SYSTEM SHALL retirar `"pytest-cov>=7.0.0"` de `[dependency-groups].dev` en `backend/pyproject.toml` y reflejarlo en `backend/uv.lock`.
4. THE SYSTEM SHALL SHALL NOT tocar `pytest>=9.1.1`, `pytest-asyncio>=1.4.0`, `pytest-xdist>=3.6.1` ni los flags de invocación actuales (`uv run pytest -q -rs -n 2`).

### R7 — Métricas before/after demostrables

**As a** mantenedor,
**I want** que la reducción de minutos sea medible antes y después del change,
**so that** se pueda demostrar que el change cumplió sus objetivos sin recurrir a la intuición.

Acceptance criteria:

1. THE SYSTEM SHALL registrar, en una sección del design o de las tareas, los valores baseline de los últimos 5-15 runs visibles de cada workflow afectado (job-seconds agregados por PR, wall-clock del job más lento, ratio skip-legítimo/PR, fallos en `backend-tests` y `deploy-dev`).
2. THE SYSTEM SHALL definir objetivos medibles para 30 días post-merge, entre ellos como mínimo:
   - **Minutos jobs-seg por PR de solo-prosa ≤ 120 s** (baseline ≈ 564 s).
   - **Minutos jobs-seg por PR backend + frontend ≤ 800 s = 13 min** (baseline ≈ 1.166 s).
   - **Wall-clock del job más lento en PR promedio ≤ 9 min** (baseline ≈ 11 min).
   - **Suites ejecutadas por detect condicional ≥ 4** (backend + frontend + compose-ports + rule11-ownership; baseline = 1).
3. THE SYSTEM SHALL SHALL NOT usar métricas de cobertura como criterio de éxito de este change — la cobertura no se calcula ni antes ni después.
4. THE SYSTEM SHALL publicar los objetivos y la baseline en `sdd/specs/backend-ci.md` y/o `sdd/specs/frontend-ci.md` durante `/sdd:archive`, no en este proposal.

### R8 — Preservación de invariantes de regresión demostrada

**As a** mantenedor,
**I want** que las optimizaciones no relajen la detección de regresiones que ya funcionan,
**so that** sigamos cazando las clases de bug que los gates actuales ya cazan.

Acceptance criteria:

1. THE SYSTEM SHALL SHALL NOT modificar la lógica del gate `alembic heads` (que detectó la regresión multi-head en PRs #146/#151 a los 40 s en `backend-tests-suite`) ni el preflight de `alembic heads` en `deploy-dev`.
2. THE SYSTEM SHALL SHALL NOT modificar la sonda de origen desde la red de ingress (`deploy-dev › Verificar que el origen es alcanzable…`, R1.6).
3. THE SYSTEM SHALL SHALL NOT relajar la verificación de posture de red del compose (`compose-ports`, sostiene la exención de `POSTGRES_PASSWORD` de `steering/security.md` regla 8).
4. THE SYSTEM SHALL SHALL NOT cambiar el comportamiento fail-safe: si la detección de área es ambigua, se ejecuta el trabajo (R1.5, R5.4).
5. THE SYSTEM SHALL SHALL NOT cambiar los SHAs pinneados de actions (`actions/checkout@11d5960a326750d5838078e36cf38b85af677262`, `docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8`, `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9`, etc.).
6. THE SYSTEM SHALL SHALL NOT relajar `concurrency.cancel-in-progress` ni los timeouts de los jobs.

## Out of scope

- **Bajar coverage thresholds** — no hay coverage threshold en CI; pytest-cov es dependencia muerta y se retira (R6). Introducir cobertura real con umbral duro queda para un change posterior con su propia evidencia.
- **Eliminar tests para ahorrar minutos** — TDD se mantiene; los tests existentes se preservan.
- **Abandonar o debilitar TDD** — `steering/testing.md` permanece vinculante.
- **Modificar el shape o el contenido de la backend test suite** — `pytest -q -rs -n 2`, bases desechables por worker, fixtures actuales; no se tocan.
- **Investigar o resolver la regresión histórica de rendimiento de `backend-tests-suite`** (205 s → 424 s → 709 s) — registrada en la cabecera del workflow como decisión explícita del usuario; pertenece a un work-item separado.
- **Re-baselinar `BACKEND_SUITE_BUDGET_SECONDS` / `BACKEND_SUITE_CEILING_SECONDS`** — explícitamente fuera de este change por decisión del usuario. Cambiar esos umbrales no reduce minutos y podría ocultar la regresión histórica de runtime; queda como follow-up de `backend-suite-runtime`.
- **Mover validaciones críticas de Docker/multiarch exclusivamente a nightly** — siguen siendo gates de PR y push a main; el nightly podría añadirse en otro change, no aquí.
- **Añadir un nuevo nightly/full-suite** — fuera de scope; este change se limita a PR + push. Un nightly se considerará en `/sdd:design` solo si el PR es insuficiente, y siempre como capa adicional, no como sustitución.
- **Cambios en `infra-dev.yml`** — no entra en el perfil de coste de PR (runs raros, ~21 s cuando corre).
- **Cambios en `demo-reset.yml`** — nightly, 17 s, no compite por minutos.
- **Cambios funcionales de AutoHostAI** — esto es exclusivamente un change de CI.
- **Cambiar `dorny/paths-filter` u otra acción externa** — el proyecto ya hace la detección en bash por motivos documentados en `specs/backend-ci.md` (R2.4 fail-open, `core.quotePath`, `--no-renames`); sustituirla sería una regresión de supply-chain y de auditabilidad.
- **Fusionar workflows en un mega-workflow** — aumentaría el lock-in con GitHub Actions y haría el path filtering fino más difícil.
- **Migrar de `actions/cache@v4` al `setup-node` con `cache: npm`** — ya está en uso y se mantiene; el cambio se limita a Playwright y Buildx, donde no hay alternativa integrada equivalente.

## Affected specs

- `sdd/specs/backend-ci.md` — actualizar R2.4 (preservar invariante de detección); añadir nota sobre el patrón ya replicado a otros workflows; re-baselinar presupuesto si el design lo declara aquí.
- `sdd/specs/frontend-ci.md` — añadir R sobre detección de área para `frontend-tests`, equivalentes a R1-R2 de `backend-ci.md`; documentar la caché de Playwright y la consolidación de `npm ci`; preservar el resto del contrato (versionado, pinneado de actions, comportamiento de señales).
- `sdd/specs/multiarch-build-check.md` *(no existe aún — se creará al archivar)* — documentar la caché de capas Buildx, el scope por workflow, y la invariante de identidad de imagen (R1.5).
- `sdd/specs/compose-ports.md` *(verificar existencia; si no existe, crear al archivar)* — añadir R de detección de área; preservar la postura de red documentada.
- `sdd/specs/rule11-ownership-guard.md` — añadir R de detección de área; preservar el censo y la regla de scope.
- `sdd/specs/version-parity.md` *(no existe aún — se creará al archivar; gate añadido en §11/SEC-2 tras la aprobación de este proposal, ver R1.8)* — documentar el gate always-run `version-parity.yml` (sin `paths:` ni detect), sus tres fuentes (`VERSION` + `backend/pyproject.toml` + `frontend/package.json`) y la copia belt-and-suspenders dentro de `frontend-tests-suite`.
- `sdd/changes/ci-pr-gates-optimization/metrics.md` *(no existe aún — se creará durante `/sdd:tasks` o `/sdd:run`)* — baseline y objetivos post-merge, derivados de R7.

## Decisiones del usuario tras la aprobación (registradas, no resueltas en el proposal)

Estas cuatro decisiones se tomaron en la revisión del proposal y se aplican tal cual en `/sdd:design`:

1. **Registro ad-hoc en el roadmap.** **Sí**, como entrada `[INFRA]` citando `ci-backend-tests-conditional-gate` como precedente directo y `backend-suite-runtime` como referencia adyacente (no dependencia). Reflejado en `sdd/roadmap.md` y `sdd/roadmap/ci-pr-gates-optimization.md` durante la fase de diseño.
2. **Caché de capas en `deploy-dev`.** **Sí**, dentro de R4. Condicionado a preservar estrictamente las invariantes existentes de provenance/identidad de imagen. El design debe aclarar exactamente qué significa preservar identidad de imagen según las specs existentes (R1.5) y no exigir digest byte-identical si esa no es la invariante real — el design decide la forma de la verificación.
3. **Cachear `node_modules` keyed por hash del lockfile.** **No**. R3 se mantiene con `npm ci` limpio (la regla actual de `frontend-tests.yml` ya declarada: *"cachea descargas de npm, nunca node_modules; npm ci sigue siendo limpio"*). El change solo debe consolidar instalaciones redundantes, no cachear el árbol.
4. **Detección de área para `api-contract` y `frontend-api-contract`.** **No** en este change. Quedan fuera de R5 tal como se propuso.
