# Design: ci-pr-gates-optimization

## Context

`origin/main` @ `888edfa4` mantiene 10 workflows en `.github/workflows/` que, juntos, ejecutan **≈ 1.166 jobs-segundos = ~19 min agregados** por Pull Request que toca `backend/**` y `frontend/**`, y **≈ 564 jobs-segundos = ~9 min** por PR de solo prosa (la forma de todo commit de `/sdd:archive`). El wall-clock del job más lento ronda **~11 min** (`backend-tests-suite` ~712 s en PR #147, run `33657682677`; `frontend-tests` ~322-423 s). Solo `backend-tests` aplica el patrón de conditional gate (change `ci-backend-tests-conditional-gate`, 2026-08-03): tres jobs (`*-detect` decide área, `*-suite` ejecuta si toca, `*-tests` consolida y reporta siempre). Tres dependencias/áreas (`frontend-tests`, `compose-ports`, `rule11-ownership`) replican trabajo aunque el diff no pueda afectarlas. `multiarch-build-check` y `deploy-dev` construyen imágenes Docker sin `cache-from: type=gha` documentado. `pytest-cov` está declarado en `backend/pyproject.toml:66` pero no se invoca en ningún workflow — es dependencia muerta.

La auditoría READ-ONLY (sesión actual) recogió estos hechos vía `gh api repos/autohostai-labs/AutoHostAI/actions/runs/{id}/jobs` sobre runs visibles entre `33657682515` y `33677211113`. El proposal `proposal.md` los convierte en ocho requisitos verificables (R1-R8) y deja explícito lo que queda fuera (incluido el re-baseline de `BACKEND_SUITE_BUDGET_SECONDS`/`CEILING_SECONDS`, que el usuario decidió sacar).

Este design decide el **cómo** de cada palanca —fail-safe pattern, consolidación de jobs, caché de Playwright, caché de Buildx con scope correcto, retirada de pytest-cov, métricas— y aclarea qué significa "preservar identidad de imagen" según las specs existentes (R1.5 de `app-deploy-dev.md`).

## Decisions

### D1 — Patrón fail-safe de detección por área (R1, R5)

**Chosen:** Replicar literalmente la lógica de `backend-tests-detect` (`.github/workflows/backend-tests.yml:106-260`) como un **job `*-detect` separado por workflow**, con el mismo `outputs: <area>: ${{ steps.decide.outputs.<area> }}`, la misma lectura del diff con `git -c core.quotePath=false diff -z --no-renames --name-only`, la misma evaluación por `case "$f" in` (no regex sobre el conjunto pegado, para no escapar el punto de `.github`), el mismo arranque en `true` y bajada solo con afirmación positiva, y la misma consolidación con `if: always()` y `if: needs.*.outputs.<area> == 'true'`. La detección se **delega al job detect** en vez de hacer `if: contains(needs.*.outputs.changed-files, 'frontend/')` en cada paso — el patrón actual ya lo hizo así por motivos que el comentario del workflow documenta (defensa contra `core.quotePath`, `--no-renames`, inyección de comandos en log).

**Replicación por workflow:**

| Workflow | Jobs (`*-detect` → `*-suite` → `*-tests` consolidador) | Anclas del `case` (literal, no regex) — área que dispara `*-suite` |
|---|---|---|
| `frontend-tests` | `frontend-tests-detect` → `frontend-tests-suite` → `frontend-tests` | `frontend/*`, `frontend/devops/Dockerfile`, `frontend/package.json`, `frontend/package-lock.json`, `scripts/*`, `.github/scripts/*`, `Makefile`, `.github/workflows/frontend-tests.yml` (§13-A: `scripts/*` en bloque, no dos scripts `.py` nombrados) |
| `compose-ports` | `compose-ports-detect` → `compose-ports-suite` → `compose-ports` | `compose.yaml`, `compose.yml`, `compose.override.yaml`, `compose.override.yml`, `docker-compose*.yml`, `docker-compose*.yaml`, `docker-compose.worktree.yml`, `scripts/*`, `Makefile`, `.github/workflows/compose-ports.yml` (§11/D1.1.b: familia de descubrimiento por defecto de Compose — los `compose.*` con precedencia sobre `docker-compose.yml`) |
| `rule11-ownership` | `rule11-ownership-detect` → `rule11-ownership-suite` → `rule11-ownership` | `sdd/steering/*`, `sdd/specs/*`, `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md`, `docs/*`, `backend/app/*`, `backend/alembic/versions/*`, `backend/tests/*`, `scripts/*`, `Makefile`, `.github/workflows/rule11-ownership.yml` |

> **Nota sobre `*` vs `**`:** las anclas usan un solo `*` porque en un `case` de shell (no *pathname expansion*) `*` casa cualquier profundidad, incluidos los `/` — `docs/*` casa `docs/a/b/c.md` (verificado; ver notas de implementación de §4). El YAML de los tres workflows usa `*`; esta tabla lo refleja literalmente.

**D1.1 — Invariante de superficie: `detect surface ⊇ suite dependency surface`.**

La corrección de un `*-detect` no es "una lista de rutas plausible del área", sino un **superconjunto de la superficie de dependencias de su `*-suite`**. Superficie de dependencias = el conjunto de ficheros cuya modificación puede cambiar el veredicto de la suite. Si el detect ancla **menos** que eso, un PR que toca solo una dependencia omitida se juzga «no toca el área», la suite se salta y el consolidador reporta verde `**OMITIDA**` sin haber verificado el fichero que sí podía romperla — que es el mismo defecto de disparador-disjunto-del-entry-point que el run `33409418091` documenta como incidente fundacional de `rule11-ownership.yml`, reintroducido una capa más abajo. El panel de `/sdd:review` lo detectó (architect + security, 2026-09-04); esta sección deriva la superficie explícitamente para que las anclas no vuelvan a ser un subconjunto.

La superficie de dependencias de una suite se descompone en dos partes, y el detect debe cubrir **ambas**:

1. **El código de guard/verificación que la suite EJECUTA** — no solo el corpus que inspecciona, sino los scripts entry-point, sus targets de Makefile y los harnesses `--self-test`. Un PR que debilita la guardia (encoge su `SCOPE`, no-opea su target de Make, rompe un self-test) debe ejecutar esa misma guardia: es su única red.
2. **El corpus del que la suite es el ÚNICO gate designado** — las rutas que la guardia recorre y que ningún otro required check cubre.

Derivación por workflow (cada ancla mapea a algo que la suite ejecuta o recorre):

| Workflow | Lo que la `*-suite` ejecuta / recorre | Anclas derivadas |
|---|---|---|
| `rule11-ownership` | `make check-rule11-ownership` → `scripts/rule11-ownership.py`; `pytest scripts/test_rule11_ownership.py`; y el guard **camina su `SCOPE`** (`scripts/rule11-ownership.py:136-230`): census prose `sdd` (menos `sdd/changes`, `sdd/roadmap*`) y `docs`; census code `backend/app`, `backend/alembic/versions`, `backend/tests` y **`scripts`** | `sdd/steering/*`, `sdd/specs/*`, `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md`, `docs/*`, `backend/app/*`, `backend/alembic/versions/*`, `backend/tests/*`, `scripts/*` (impl + test + census code), `Makefile` (target), workflow |
| `compose-ports` | `make check-compose-ports` → `scripts/compose-ports.py`; **`pytest scripts/ -q`** (el árbol de tests de scripts **entero**, no solo compose) | `docker-compose*.yml/.yaml`, `docker-compose.worktree.yml` (input del guard), `scripts/*` (todo el árbol que `pytest scripts/` ejecuta), `Makefile` (target), workflow |
| `frontend-tests` | `make check-version-parity` → `scripts/check-version-parity.py`; `bash .github/scripts/extract-pr.sh --self-test`; `python3 scripts/validate-provenance-contract.py --self-test`; y toda la suite de `frontend/**` | `frontend/*` (+ Dockerfile/manifest/lockfile explícitos), **`scripts/*`** (el árbol entero — §13-A/D1.1.d; supersede los dos scripts `.py` nombrados `check-version-parity.py`/`validate-provenance-contract.py`, ya subsumidos), `.github/scripts/*` (extract-pr), `Makefile` (target `check-version-parity`), workflow |

**Frontera deliberada — inputs de datos cross-area que NO se anclan** (y por qué no es un falso negativo): la superficie se acota al **código de guard ejecutado** y al **corpus de gate único**, no a los inputs de datos transitivos que esos guards leen de otra área con su propio required check. En concreto, en `frontend-tests-detect` se decide NO anclar:

- `backend/pyproject.toml` y `VERSION` — inputs de `check-version-parity`. Anclar `backend/**` desde un detector de *frontend* sería la ampliación indiscriminada que este design prohíbe, y dispararía la suite de frontend en cada bump de dependencia del backend (coste contra R7). **Resuelto (SEC-2, §11):** en vez de acoplar el detector de frontend al backend, `check-version-parity` pasa a tener su **gate always-run propio** (`.github/workflows/version-parity.yml`, análogo a `frontend-api-contract.yml`): corre `make check-version-parity` (stdlib, sin `uv`) sobre `pull_request: {}` sin `paths:` ni detect gate, en cada PR. Así un bump de `VERSION` o `backend/pyproject.toml` sin tocar frontend **sí** re-verifica la paridad (como antes de este change, cuando `frontend-tests` corría siempre), sin erosionar R7 (el job es de segundos, no la suite de frontend). La copia de `check-version-parity` dentro de `frontend-tests-suite` queda como belt-and-suspenders (igual que `api:check` vive en la suite y en `frontend-api-contract.yml`). `VERSION`/`backend/pyproject.toml` siguen SIN anclarse en `frontend-tests-detect` — su gate designado es `version-parity.yml`, no el detector de frontend.
- `backend/app/provenance/contract.py` — importado por `validate-provenance-contract.py --self-test`. Ese fichero **ya tiene gate designado**: `backend-tests` corre sobre `backend/*` y ejercita `backend/tests/provenance/`. Re-anclarlo desde frontend sería cobertura cross-gate redundante, no una red que falte.
- `backend/openapi.json` — leído por `npm run api:check` (paso `provenance_suite` de `frontend-tests-suite`, vía `frontend/scripts/generate-api-types.mjs`), que falla si `frontend/lib/api/generated/openapi.d.ts` deja de ser su salida. Ese fichero **ya tiene un gate designado que corre SIEMPRE**: el workflow independiente **`frontend-api-contract.yml`** ejecuta `npm run api:check` sobre `pull_request: {}` **sin `paths:` y sin detect gate** — es decir, incondicionalmente en cada PR (`.github/workflows/frontend-api-contract.yml:6-10,39-41`). Así que la deriva `backend/openapi.json → tipos generados` la caza `frontend-api-contract` aunque `frontend-tests-suite` se salte; anclar `backend/openapi.json` en `frontend-tests-detect` dispararía toda la suite de frontend en cada regeneración del contrato del backend **de forma redundante con un check que ya corre siempre**, erosionando R7 sin cerrar ninguna red que falte. La copia de `api:check` dentro de `frontend-tests-suite` es belt-and-suspenders, no el gate designado de esa deriva.

El criterio que separa "ancla" de "frontera" es único: **si la modificación de un fichero puede cambiar el veredicto de la suite Y ningún otro required check lo cubre, se ancla; si otro gate ya lo cubre, o cubrirlo aquí exigiría acoplar el detector a otra área entera, se documenta como frontera.**

**D1.1.d — `frontend-tests-detect` ancla `scripts/*` en bloque (§13-A, decisión de usuario 2026-09-07).** La versión original anclaba solo los dos scripts `.py` *nombrados* que la suite ejecuta (`scripts/validate-provenance-contract.py`, `scripts/check-version-parity.py`), para acotar el disparo (objetivo R7). Esa elección obligaba a `frontend_surface()` (`scripts/check-detect-surface.py`) a modelar textualmente **cómo** se escribe cada referencia a script en los `run:` de la suite y a distinguir un prefijo virtual de ruta-a-raíz (`./`, `$VAR/`, `"$ROOT"/`, `$(…)/`, …) de un subdirectorio real — una distinción irreducible en texto que reabrió la clase fail-open de superficie de detección **cuatro veces** (round-5 allow-list; §13 fix-round-1 dir real `lib/scripts/`; fix-round-1b sufijo-hermano `notfrontend/`; fix-round-2 anidado `a/frontend/scripts/`), cada una latente pero real. **Resolución de raíz:** anclar `scripts/*` en bloque, como ya hacen `compose-ports-detect` y `rule11-ownership-detect`. Con ello, **cualquier** fichero bajo `scripts/**` que la suite ejecute queda gateado por el propio `case` del detector sobre las rutas cambiadas del diff, con independencia del parser textual — la clase se **disuelve** en lugar de perseguir grafías. Coste R7 aceptado (explícito por el usuario): un PR que toca solo `scripts/**` dispara ahora también la suite de frontend (además de compose/rule11, que ya la anclaban); `scripts/**` se toca con poca frecuencia y el ahorro dominante (PRs que no tocan `frontend/**` ni `scripts/**` ni los otros anclas) se conserva. `frontend_surface()` se simplifica en consecuencia: reporta cada referencia `scripts/…` por su **ruta real** (quita solo prefijos virtuales reconocidos, conserva segmentos de directorio reales), de modo que un `scripts/…` de raíz queda cubierto por `scripts/*`, `frontend/scripts/…` por `frontend/*`, `.github/scripts/…` por `.github/scripts/*`, y una ruta anidada no anclada se reporta descubierta (fail-closed). Esto **supersede** la parte de D1.1 que llamaba "frontera" a anclar `scripts/*`: los dos scripts nombrados ya no son la frontera — `scripts/*` es ancla. Las fronteras de datos cross-area (`backend/pyproject.toml`, `VERSION`, `backend/app/provenance/contract.py`, `backend/openapi.json`) siguen intactas (no están bajo `scripts/`; sus gates designados son `version-parity.yml`, `backend-tests`, `frontend-api-contract.yml`).

**D1.1.a — La invariante de `rule11-ownership-detect` es machine-checked, no acordada.** El `SCOPE` de la guardia (`scripts/rule11-ownership.py:136-230`) declara `ScopeEntry("sdd", Kind.CENSUS_PROSE)`: una raíz **recursiva**, la guardia camina *todo* `.md` bajo `sdd/` salvo las exclusiones `OUT_OF_CENSUS` (`sdd/changes`, `sdd/roadmap.md`, `sdd/roadmap`). El detector, en cambio, **enumera** las rutas de `sdd/` que hoy contienen esa prosa (`sdd/steering/*`, `sdd/specs/*`, `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md`) **a propósito**: anclar `sdd/*` recursivo dispararía la suite en cada PR que toca `sdd/changes/**` (la forma de casi todo commit de flujo SDD), reintroduciendo el coste que R7 quita — y esas rutas ya las excluye la guardia, así que el trabajo sería siempre verde en vacío. Enumerar preserva el ahorro, pero deja una brecha latente: si mañana alguien añade un `.md` directamente bajo `sdd/`, o un subárbol nuevo (`sdd/adr/`, `sdd/decisions/`…), la guardia lo caminaría y el detector no lo anclaría → un PR que solo tocara ese fichero recibiría `**OMITIDA**` verde sobre una atribución que la regla 11 prohíbe (el mismo fail-open disparador-disjunto-del-corpus que §9 cerró para los ficheros-guard). Para que la elección "anclas explícitas" sea **segura frente al crecimiento del `SCOPE` sin acoplar el detector a `sdd/*`**, la relación se hace comprobable: un test en `scripts/test_rule11_ownership.py` afirma la invariante

> **`relevant-SCOPE-walked-surface(rule11) ⊆ detect-anchor-surface(rule11)`**

usando la propia lógica de recorrido de la guardia (`prose_files` + `code_files` sobre `SCOPE`, que ya aplica las exclusiones `OUT_OF_CENSUS`) para el lado izquierdo y las anclas del `case` on-disk del workflow para el derecho: **todo fichero que la guardia recorrería debe casar con alguna ancla del detector**. Si aparece una ruta relevante nueva bajo `sdd/` (p. ej. `sdd/adr/x.md`) que la guardia inspecciona pero ninguna ancla activa, el test **FALLA** — no se permite el fail-open en silencio. El test NO puede hacerse pasar ampliando el detector a `sdd/*` ni recortando el `SCOPE`; la resolución correcta ante un FALLO es añadir la ancla explícita que corresponda (o, si la ruta nueva pertenece a las exclusiones deliberadas, declararla `OUT_OF_CENSUS` en `SCOPE`, que es donde vive esa decisión).

**D1.1.b — La superficie de entrada de `compose-ports-suite` es el conjunto de descubrimiento por defecto de Docker Compose, no solo `docker-compose*` (SEC-1).** `scripts/compose-ports.py` invoca `docker compose config` **sin `-f`** (`config_command()` construye solo `("docker","compose") + profiles + CONFIG_BASE`), así que Compose aplica su **descubrimiento por defecto**: elige el primero de `compose.yaml` > `compose.yml` > `docker-compose.yaml` > `docker-compose.yml` y auto-carga los `*.override.{yaml,yml}` que existan. Los nombres modernos `compose.yaml`/`compose.yml` **tienen precedencia** sobre `docker-compose.yml`. Que la guardia use descubrimiento por defecto es deliberado —comprueba el fichero de compose que de verdad se resolvería en local— así que el arreglo **no** es fijar `-f` (eso haría que la guardia dejara de mirar un `compose.yaml` real), sino **anclar toda la familia de descubrimiento** en `compose-ports-detect`. La mitad `docker-compose.*` ya la cubre `docker-compose*`; se añade la mitad `compose.*`: `compose.yaml | compose.yml | compose.override.yaml | compose.override.yml`. Invariante: **detect-surface(compose) ⊇ familia-de-descubrimiento-de-Compose ∪ {`scripts/*`, `Makefile`}**. Se hace machine-checked (D1.1.c).

**D1.1.c — Invariante temporal: el guard que detecta ampliaciones de superficie debe correr ANTES de que el detector pueda omitirlo (SEC-3).** Un test que verifica `SCOPE ⊆ detect-surface` no sirve de nada si vive **dentro** de la suite condicional que el propio detector puede saltarse: el PR que abre la brecha (p. ej. añade `sdd/adr/x.md`, que no casa ninguna ancla) hace que el detector decida `skip`, la suite no corre, el test no se ejecuta, y el fail-open pasa verde — el rojo solo aparece un PR más tarde, sobre un diff que sí toca un área anclada. La regla F4/D1.1.a exige lo contrario: **el test debe FALLAR en el PR que introduce la brecha.** Por tanto los checks de superficie de detección se ejecutan **always-run, en el propio job `*-detect`** (que corre siempre y es donde se toma la decisión de skip), no en la suite condicional:

- Un CLI stdlib `scripts/check-detect-surface.py <workflow>` computa, para el detector nombrado, el conjunto de no-cubiertos y sale con código ≠ 0 (nombrándolos) si la superficie de entrada excede las anclas. Reusa la lógica de recorrido de la guardia (`prose_files`/`code_files` para rule11) y la familia de descubrimiento de Compose (D1.1.b) como lados izquierdos; parsea el `case` on-disk del workflow como lado derecho. Es stdlib puro (sin `uv`).
- Cada `*-detect` (rule11, compose, frontend) corre `python3 scripts/check-detect-surface.py <wf>` como **paso always-run** antes de publicar su decisión. Un fallo aborta el job `*-detect`; el consolidador lo trata como `DETECT_RESULT != success` → **fail-closed** (rojo), no fail-open — una superficie de detección incompleta es un error de configuración del gate que debe bloquear, distinto del fail-open ante diff ambiguo (que sí ejecuta la suite). Esto cierra SEC-3 y generaliza la invariante F4 a los tres detectores.

Los tests pytest de `scripts/test_*.py` (que sí corren en las suites condicionales) conservan las aserciones específicas y los casos que prueban el rojo (belt-and-suspenders + uso local); el enforcement always-run que satisface la invariante temporal es el paso de `*-detect`.

**Patrón invariante en los tres workflows:** `*-detect` corre siempre; `*-suite` corre solo si `*-detect.outputs.<area> == 'true'` y `if: always()` se aplica al check que reporta (consolidador). El nombre del check estable es el del consolidador: `frontend-tests`, `compose-ports`, `rule11-ownership`. R1.1/R5.3 dependen de que el consolidador exista como identidad separada; sin él, un required check sin área tocada quedaría `skipped` y bloquearía el PR.

**Outputs publicadas por `*-detect`:** `<area>` (bool) y `reason` (literal del conjunto cerrado del script: `diff-touches-<area>`, `no-<area>-changes`, `pr-shas-missing`, `pr-base-unreachable`, `git-diff-failed`, `push-before-is-zero`, `push-before-unreachable`, `workflow-dispatch-runs-full-suite`, `unknown-event-defaults-to-full-suite`). La razón se imprime en `GITHUB_STEP_SUMMARY` y en una `::notice::` en el log, exactamente como `backend-tests-detect`.

**Worked example del flujo para `frontend-tests`** sobre un PR que solo toca `docs/foo.md`:
1. `frontend-tests-detect` corre (~9 s). `evaluate()` itera `files=("docs/foo.md")`, no casa con `frontend/*` ni con las anclas del Dockerfile/lockfile/workflow, publica `frontend=false` y `reason=no-frontend-changes`.
2. `frontend-tests-suite` se salta porque `if: needs.frontend-tests-detect.outputs.frontend == 'true'`.
3. `frontend-tests` (consolidador) corre con `if: always()` y publica el check en verde con la línea `**OMITIDA** (no ejecutada)` y la razón.
4. El check `frontend-tests` aparece en el PR como **success**, no como **skipped** — invariante de R1.1.

**Por qué no `paths:` en `on:`** (R1.1/R5.3): un required check con `paths:` en el disparador no produce check alguno en PRs que no tocan esas rutas, y GitHub deja el PR bloqueado esperando un check que nunca llegará (decisión documentada en `specs/backend-ci.md:21-29` y replicada en los comentarios de cabecera de los tres workflows candidatos). El filtrado ocurre **dentro** del workflow, no en su disparador.

**Por qué un job `*-detect` separado y no un step inline dentro del consolidador**: el consolidador necesita los `<area>` y `reason` como `needs.*.outputs.*` para decidir; un step inline no expone esos outputs. Además, `backend-tests-detect` ya está midiendo ~9 s y termina antes que el resto del workflow; el patrón "detect primero, suite condicional, consolidador al final" es la forma que ya pasó la prueba de fuego (run `33663822125` skip legítimo por push de `docs(revenue-statements)`).

Rejected:
- **Detección inline en el consolidador con `if: contains(...)`** — pierde el motivo legible y la trazabilidad que el workflow actual exige (ver comentario de cabecera de `backend-tests.yml:31-44`).
- **`dorny/paths-filter` u otra acción externa** — el proyecto ya hace la detección en bash por motivos documentados (`specs/backend-ci.md` R2.4 fail-open, `core.quotePath`, `--no-renames`, defensa contra inyección de comandos en log vía `%q` y `::notice::`). Sustituirla sería una regresión de supply-chain y de auditabilidad (Out of scope explícito del proposal).
- **Detección por `dorny/changed-files` v2** con `--no-renames` — sería válido, pero introduce una dependencia nueva y el patrón actual ya funciona. Migración futura, no ahora.

### D2 — Tres jobs para `frontend-tests.yml`: `detect` + `suite` condicional + consolidador (R3)

**Chosen:** Adoptar el patrón de **tres jobs** que ya usan `backend-tests.yml` y `backend-tests` (precedente `ci-backend-tests-conditional-gate`, 2026-08-03): un job `*-detect` que decide, un job `*-suite` que ejecuta, y un job consolidador que reporta el check estable. El workflow `frontend-tests` queda con tres identidades:

| Job | Trigger | Responsabilidad |
|---|---|---|
| `frontend-tests-detect` | siempre (~9 s) | Lee el diff, publica `outputs.frontend` (`true`/`false`) y `outputs.reason` (D1). |
| `frontend-tests-suite` | condicional: `if: needs.frontend-tests-detect.outputs.frontend == 'true'` | Ejecuta las nueve señales A–I con un único `npm ci` y publica los outcomes por señal como `outputs`. |
| `frontend-tests` | `if: always()` (siempre corre) | Consolidador: lee `needs.frontend-tests-detect.outputs.*` y `needs.frontend-tests-suite.outputs.*`, publica la tabla markdown en `GITHUB_STEP_SUMMARY`, falla el check si alguna señal terminada en estado distinto de `success` o `skipped`-legítimo. **Es el check estable** que aparece como `success` o `failure` en el PR. |

**Por qué tres jobs y no dos** (R1.1): sin consolidador separado, cuando el área no se toca, el job que publica el check sería el mismo que la suite condicional. Ese job quedaría con `result: skipped` y el required check saldría **skipped**, no **success** — que es exactamente el bug que el patrón `backend-tests` ya documentó como *"un required check sin check run queda el PR bloqueado esperando para siempre"* (`specs/backend-ci.md:21-29`). El consolidador garantiza R1.1/R5.3: el check `frontend-tests` (el de nombre estable, requerido en PR) **siempre** termina con un veredicto explícito.

**Estructura interna del job `frontend-tests-suite` (condicional):**

1. `actions/setup-node@v4` con `node-version: "22"` + `cache: npm` keyed por `frontend/package-lock.json` (sin cambios respecto al workflow actual).
2. **Un único `npm ci`** (R3.1; preserva la regla *"npm ci sigue siendo limpio"* de `frontend-tests.yml:78-81`).
3. `actions/cache@v4` para Playwright (D3) — restore + install (always) + save (solo en cache miss), dentro de este mismo job.
4. **Señales que no requieren `npm ci`** (al principio del job, antes del `npm ci` cuando es posible, en paralelo donde no; corren en orden por legibilidad):
   - `make check-version-parity`
   - `bash .github/scripts/extract-pr.sh --self-test`
   - `python3 scripts/validate-provenance-contract.py --self-test`
5. **Señales que requieren `npm ci`** (en este orden, conservando el flujo actual):
   - `npm run api:check && npm test -- --run features/provenance`
   - `npm run build` con APP_PROVENANCE_* rellenadas (de `provenance-contract` original)
   - `npm run test:public-artifacts` (de `provenance-contract` original)
   - `npm test` (Vitest node project, F)
   - `npm run test:layout` (Vitest browser project con Chromium, G)
   - `npm run lint` (H)
   - `npm run typecheck` (I)
6. **Publicación de outcomes por señal** como `outputs.<señal>: ${{ steps.<id>.outputs.outcome }}` (`success`/`failure`/`skipped`). El consolidador los lee vía `needs.frontend-tests-suite.outputs.*`.

**Estructura interna del job `frontend-tests` (consolidador, `if: always()`):**

1. Lee `DETECT_RESULT`, `DETECT_FRONTEND`, `DETECT_REASON` de `needs.frontend-tests-detect.*`.
2. Lee `SUITE_RESULT` y los outcomes por señal de `needs.frontend-tests-suite.*`.
3. Construye una tabla markdown en `GITHUB_STEP_SUMMARY` con un renglón por señal.
4. **Lógica del veredicto** (misma forma que `backend-tests`, líneas 449-577 del workflow actual):
   - Si `DETECT_RESULT != success` → **fail** (gate inconsistente).
   - Si `SUITE_RESULT == success` → **pass** (suite ejecutada y verde).
   - Si `SUITE_RESULT == skipped` y `DETECT_FRONTEND == false` → **pass** con la línea `**OMITIDA** (no ejecutada)` y el motivo legible (R1.3).
   - Si `SUITE_RESULT == skipped` y `DETECT_FRONTEND == true` → **fail** (incoherencia: si el área toca, no debería saltarse).
   - Si cualquier outcome de señal != `success` → **fail** con la señal que falló.
5. Emite `::error::` o `::notice::` con el detalle del veredicto y sale con `exit 0` (pass) o `exit 1` (fail). **El check estable `frontend-tests` se reporta siempre.**

**Ahorro esperado de R3:** las cinco señales que vivían en el job original `provenance-contract` (A–E) se ejecutan ahora dentro del job `frontend-tests-suite`, junto con las cuatro del antiguo `frontend-tests` (F–I). **Se elimina el `npm ci` redundante** que el workflow original corría dos veces (uno en `provenance-contract`, otro en `frontend-tests`). El diseño final ejecuta **un único `npm ci`** por ejecución de la suite. Ahorro: ~30-60 s por PR. El ahorro total del change viene de **D1 (conditional execution)** + **D3 (caché de Playwright)** + **D4 (caché Buildx)**; R3 aporta una pieza más, no la principal.

**Lo que cambia de `frontend-tests.yml` original (resumen):**
- Pasa de dos jobs (`provenance-contract` + `frontend-tests`) a tres jobs (`frontend-tests-detect` + `frontend-tests-suite` + `frontend-tests` consolidador).
- El job `provenance-contract` desaparece como identidad separada; sus cinco señales (A–E) se ejecutan dentro de `frontend-tests-suite` en orden, antes de las señales F–I. La identidad estable del check sigue siendo `frontend-tests` (R1.1).
- Las nueve señales con outcome (A–E + F–I) y las tres precondiciones (B+C+A sin outcome propio) se preservan todas.
- Los outcomes por señal se exponen como `outputs` del job `frontend-tests-suite` para que el consolidador los lea; los SHAs pinneados de `actions/checkout` y `actions/setup-node` se preservan (R8.5).

**Lo que NO cambia** (R3.2):
- Las cinco señales originales de `provenance-contract` (A: `check-version-parity`, B: `extract-pr.sh --self-test`, C: `validate-provenance-contract.py --self-test`, D: `api:check` + `npm test -- --run features/provenance`, E: `npm run build` + `npm run test:public-artifacts`).
- Las cuatro señales originales de `frontend-tests` (F: `npm test`, G: `npm run test:layout`, H: `npm run lint`, I: `npm run typecheck`).
- El comportamiento `continue-on-error: true` en cada verificación individual + consolidación final con `if: always()` que falla si alguna no es `success`.
- No se cachea `node_modules` keyed por lockfile (decisión del usuario); no se transporta `node_modules` entre jobs.

**Aplicación del mismo patrón a `compose-ports.yml` y `rule11-ownership.yml`** (R5):
- `compose-ports-detect` (decide `compose`) → `compose-ports-suite` (corre `make check-compose-ports` + `pytest scripts/ -q`) → `compose-ports` (consolidador con tabla y veredicto).
- `rule11-ownership-detect` (decide `rule11`) → `rule11-ownership-suite` (corre `make check-rule11-ownership` + `pytest scripts/test_rule11_ownership.py -q`) → `rule11-ownership` (consolidador análogo).
- Mismo invariante R1.1 / R5.3: el check estable aparece siempre, ya sea success o failure explícito.

Rejected:
- **Fusionar `suite` y consolidador en un solo job** (la versión anterior del design) — **rechazado explícitamente** porque rompe R1.1 cuando el área no se toca: el job único quedaría `skipped` y el required check aparecería como `skipped` en vez de `success`, bloqueando PRs que no tocan el área. Es exactamente la clase de bug que `backend-tests` ya documentó y que este change generaliza.
- **Transportar `node_modules` vía `actions/upload-artifact@v4` + `download-artifact@v4`** — rechazado por el usuario explícitamente. Empaquetar/subir/descargar 150-350 MiB introduce complejidad (red de artefactos, compresión, dependencia de orden) y puede costar tanto o más que el segundo `npm ci`. Esta era la opción de la primera versión del design.
- **Cachear `node_modules` keyed por hash del lockfile** — explícitamente rechazado por el usuario (R3 / node_modules cache: NO); introduce flakiness por binarios nativos y rompe la regla actual del workflow. Adicionalmente, sería la única caché que cambia el contenido de `node_modules/` entre PRs.
- **Ejecutar las señales que no requieren npm (`check-version-parity`, `extract-pr.sh --self-test`, `validate-provenance-contract.py --self-test`) en el job `frontend-tests-detect`** — son verificaciones de precondición y no de área. Mezclarlas con la detección difumina la responsabilidad del job `detect` (cuya única misión es decidir área) e introduce dependencias de runtime (Python para `validate-provenance-contract.py`) en un job que hoy solo necesita `git`.

### D3 — Caché de Playwright sin `npx`, con estrategia única para binary + system deps (R2)

**Problema que D3 resuelve (contradicción de la primera versión):** la versión anterior afirmaba a la vez "en cache hit no se ejecuta `playwright install --with-deps chromium`" y "`--with-deps` debe seguir ejecutándose para asegurar las dependencias de sistema". Esas dos afirmaciones son incompatibles: si el install **no se ejecuta en cache hit**, las system deps no se comprueban; si **sí se ejecuta**, no estamos saltándolo en cache hit. D3 define **una única estrategia consistente**.

**Estrategia única (chosen):**

Tres pasos, siempre en este orden, sin condicionales sobre `cache-hit`:

1. **Restore** — `actions/cache@v4` con `path: ~/.cache/ms-playwright` y `key: playwright-${{ hashFiles('frontend/package-lock.json') }}`. **Cache exacta**: la key es el hash completo del lockfile, sin `restore-keys`. La consecuencia es dura y deliberada: cuando el lockfile cambia (o es la primera ejecución, o expiró el TTL), el cache miss **no** restaura nada y el binario se descarga entero en el paso 2. **No** se cae al browser de un lockfile anterior, aunque sea del mismo paquete Playwright: una versión distinta de Chromium podría dejar tests verdes con vulnerabilidades conocidas. Esto **solo** afecta al binario del navegador; las system deps (librerías `apt-get`) son independientes y se manejan en el paso 2.

2. **Install (always)** — `npm exec --no -- playwright install --with-deps chromium`. Esta línea se ejecuta **siempre**, en cache hit y en cache miss. Comportamiento interno:
   - Playwright detecta si el binario para la versión pedida existe en `~/.cache/ms-playwright/`. Si la cache hit lo dejó ahí, Playwright verifica el SHA del binario y **sale sin descargar** (no-op para el binary).
   - Independientemente, `--with-deps` ejecuta `apt-get update` y `apt-get install` para las system libs (`libnss3`, `libatk1.0-0`, `libcups2`, `libxkbcommon0`, etc.). `apt-get install` es **idempotente**: si las libs ya están instaladas, sale sin tocarlas en <1 s; si no, las instala en ~5-10 s. **Esto es la pieza que la versión anterior confundía**: el `--with-deps` no es opcional, pero su coste es dominado por la idempotencia de `apt-get`, no por el binario.

3. **Save** — `actions/cache@v4` con la misma key, gated por `if: steps.cache-restore.outputs.cache-hit != 'true'`. Solo escribe cuando no había cache hit (en hit, no hay nada nuevo que persistir).

**Forma del step block (sustituye al pseudocódigo anterior, que se elimina):**

```yaml
- name: Restore Playwright browser cache
  id: cache-restore
  uses: actions/cache@v4
  with:
    path: ~/.cache/ms-playwright
    # Cache EXACTA: una key nueva (lockfile cambiado) produce miss y restaura
    # en vacío; NO se usa `restore-keys:` para evitar restaurar silenciosamente
    # browsers de otro lockfile (riesgo de binario desactualizado).
    key: playwright-${{ hashFiles('frontend/package-lock.json') }}

- name: Install Playwright Chromium (cache-aware)
  working-directory: frontend
  run: npm exec --no -- playwright install --with-deps chromium

- name: Save Playwright browser cache
  if: steps.cache-restore.outputs.cache-hit != 'true'
  uses: actions/cache@v4
  with:
    path: ~/.cache/ms-playwright
    key: playwright-${{ hashFiles('frontend/package-lock.json') }}
```

**Comportamiento cache-hit vs cache-miss, derivado de la estrategia única:**

| Estado | Restore (paso 1) | Install (paso 2) | Save (paso 3) | Coste dominante |
|---|---|---|---|---|
| **Cache hit** (lockfile no cambió desde la última ejecución) | Restaura binarios en `~/.cache/ms-playwright/` | `playwright install` ve el binario, no descarga. `apt-get` idempotente, <1 s | No persiste nada (cache-hit = true) | `apt-get update + install` idempotente: ~1-2 s |
| **Cache miss** (lockfile cambió o primera ejecución) | No restaura nada | `playwright install` descarga el binario (~30-40 s). `apt-get` instala system deps la primera vez (~5-10 s) | Persiste el binario a GHA cache | Descarga del binario: ~30-40 s |
| **Lockfile cambia** (PR que bumpea `playwright@x.y.z`) | Key distinta a la cacheada → miss | Descarga la versión nueva del binario | Persiste bajo la nueva key | Igual a cache miss |

**Verificabilidad post-merge (R2.4, no se difiere a `/sdd:run`):**
- El output `steps.cache-restore.outputs.cache-hit` queda en el log del step; verificable por inspección.
- El path `~/.cache/ms-playwright/chromium-*/chrome-linux/chrome` existe tras el install; verificable por un step de aserción opcional (`ls` con `if: failure()`).
- En PRs donde el lockfile no cambia, el log muestra `cache-hit: true` y el step de install termina en <2 s sobre la rama principal del tiempo.

**Preservación de `npm exec --no --`** (R2.3): la línea permanece exactamente como `npm exec --no -- playwright install --with-deps chromium`. `npm exec --no --` rechaza instalar nada del registro cuando el paquete está en `node_modules`; usa el binario que `npm ci` dejó desde el lockfile, o falla. El comentario `frontend-tests.yml:131-139` documenta este riesgo y se preserva sin cambios.

**Ahorro esperado:** ~30-40 s por PR en cache hit (vs. ~30-40 s del binario + 5-10 s de system deps en cache miss). El system deps install es idempotente y barato en ambos casos; lo que cambia es la descarga del binario.

**Por qué `actions/cache@v4` y no la caché integrada de `setup-node`**: `setup-node` cachea `~/.npm` (descargas), no binarios de Playwright. Playwright guarda sus binarios en `~/.cache/ms-playwright/`, fuera del ámbito que `setup-node` controla.

**Por qué no `npx playwright install`** (R2.3): `npx` puede descargar del registro una versión no pinneada cuando `playwright` no está en `node_modules`. Un PR que quite `playwright` del manifiesto convertiría esa línea en *"baja del registro la versión del día y ejecútala con `--with-deps`"* bajo el sudo del runner. El comentario `frontend-tests.yml:131-139` documenta este riesgo y la elección de `npm exec --no --`. El cache no introduce ese riesgo porque la key es el hash del lockfile, no `latest`.

Rejected (estrategia final, no se re-evalúa en `/sdd:tasks`):
- **Saltar el install entero en cache hit** (`if: steps.cache-restore.outputs.cache-hit != 'true'`) — esto era lo que decía R2.4 en la versión original. **Rechazado** porque rompe la verificación de system deps: un runner sin `libnss3` fallaría con `chromium: error while loading shared libraries` en `vitest run --project browser`, sin que el workflow lo detecte como fallo de Playwright (es un fallo del browser, que es opaco al runner). Mantener el install siempre ejecuta la garantía de deps.
- **`restore-keys: playwright-`** (D3, primera versión) — **rechazado** por la misma razón que el anterior, pero al revés: `restore-keys` permite que el cache **hit** con un prefijo parcial restaure un browser que corresponde a otro lockfile. Es la versión silenciosa del mismo riesgo: tests verdes con un binario desactualizado (CVEs) sin que el workflow lo registre como fallo. La cache tiene que ser **exacta** o no ser.
- **`setup-node` con `cache: 'playwright'`** — esa key no existe; `setup-node@v4` solo cachea `~/.npm`. Las caches integradas no cubren `~/.cache/ms-playwright/`.
- **Dividir en dos pasos: install system deps explícitamente (apt-get) + install binary sin `--with-deps`** — introduce una lista hardcodeada de paquetes que puede divergir de lo que Playwright sabe. `playwright install --with-deps` es la fuente autoritativa de esa lista y se mantiene.
- **Docker container con Chromium pre-instalado** — requiere cambiar el job a uno `container:`, lo que introduce otra dependencia. Fuera de scope.
- **`npx playwright install ...`** (R2.3) — `npx` puede descargar del registro una versión no pinneada cuando `playwright` no está en `node_modules`. Riesgo ya documentado en `frontend-tests.yml:131-139`.


### D4 — Caché de Buildx con scopes separados, sin alterar provenance (R4)

**Chosen:** Activar `cache-from: type=gha,scope=<workflow>` y `cache-to: type=gha,mode=max,scope=<workflow>` en cada `docker/build-push-action@v6` de los workflows `multiarch-build-check` (build-backend, build-frontend) y `deploy-dev` (build-backend, build-frontend), con tres scopes disjuntos:

| Workflow | Build | `cache-from` scope | `cache-to` scope |
|---|---|---|---|
| `multiarch-build-check` | `build-backend` | `multiarch-backend` | `multiarch-backend` |
| `multiarch-build-check` | `build-frontend` | `multiarch-frontend` | `multiarch-frontend` |
| `deploy-dev` | `build-backend` | `deploy-backend` | `deploy-backend` |
| `deploy-dev` | `build-frontend` | `deploy-frontend` | `deploy-frontend` |

La forma de la invocación:

```yaml
- uses: docker/build-push-action@v6
  with:
    context: backend
    file: backend/devops/Dockerfile
    target: prod
    platforms: linux/amd64,linux/arm64   # multiarch-check
    # platforms: linux/arm64            # deploy-dev
    push: ${{ github.event_name == 'push' }}
    tags: …                              # sin cambios
    labels: …                            # sin cambios
    cache-from: type=gha,scope=multiarch-backend
    cache-to: type=gha,mode=max,scope=multiarch-backend
```

**Lo que la caché NO toca** (la invariante real, clarificada abajo en D5):
- Los inputs del build: contexto (`backend/` o `frontend/`), Dockerfile (`backend/devops/Dockerfile` o `frontend/devops/Dockerfile`), build-args (`NEXT_PUBLIC_APP_ENV`, `NEXT_PUBLIC_APP_VERSION`, `NEXT_PUBLIC_BUILD_COMMIT_SHORT`, los `APP_PROVENANCE_*` que ya no se pasan como build-args), target (`prod`), platforma.
- Los outputs declarados: etiquetas (`ghcr.io/<owner>/autohostai-backend:sha-<sha>`, `:dev`) y labels OCI (`org.opencontainers.image.source`, `org.opencontainers.image.revision`, `org.opencontainers.image.version`, `org.opencontainers.image.created`).
- El job `provenance` de `deploy-dev`, que produce `version`, `commit_short`, `built_at`, `repository_url`, `pull_request_number`, `commit_sha`, `actions_run_id` antes de que los builds empiecen (R1.5 de `app-deploy-dev.md`).

**Scopes disjuntos — por qué importa**: el cache de GitHub Actions es **por scope dentro de un repo** (`gha` con `scope` lo separa). Un PR de `multiarch-build-check` nunca debería leer la cache de `deploy-dev`, porque esa cache puede tener capas de una imagen que ya no es la del SHA actual (deploy-dev publica `arm64` solamente; multiarch-check publica `amd64+arm64`; los targets coinciden pero los platforms no). Con cuatro scopes, un fallo de cache solo afecta a su workflow.

**Modo `max`** — por qué, y dónde aplica:
- En `multiarch-build-check`: las imágenes no se publican (`push: false`). `cache-to: type=gha,mode=max` escribe las capas intermedias (no el manifest final) a la cache, que es lo que queremos: la siguiente ejecución restaura capas para evitar reconstruirlas, pero la cache no contiene manifests antiguos que un consumidor externo pueda confundir con imágenes válidas.
- En `deploy-dev`: las imágenes sí se publican a GHCR. La cache de GitHub Actions es interna al repo (no pública), así que `mode=max` es seguro aquí también. Las imágenes publicadas son las que el `push: true` del job produce, y la cache solo interviene en la velocidad del build.

**No se introduce caché en el workflow `multiarch-build-check` para `push: false`** (matiz): aunque no se publique, el build sigue produciendo capas; cachearlas acelera el siguiente PR sin afectar a las imágenes producidas.

**Por qué no `type=registry`** (caché en GHCR): introduce un namespace de imágenes adicional en GHCR que tendría que limpiarse. `type=gha` es interno al repo y se limpia solo cuando el cache expira.

**Verificación de la invariante tras el change** (post-merge, durante 30 días): se aplican las **seis verificaciones de D5** sobre la imagen cacheada y la imagen pre-change para el mismo SHA. **D4 no exige ni verifica reproducibilidad bit-a-bit** (digest de manifest, digest de capas, `Id`, `RepoDigests`); eso es un work-item separado y queda fuera del alcance del change. Las seis verificaciones son la única vara para confirmar que la cache Buildx no altera el comportamiento requerido:
1. **SHA/revision** igual al SHA del commit que disparó el build.
2. **Version canónica** `X.Y.Z+YYYY-MM-DD.<7 hex>` en `org.opencontainers.image.version`.
3. **Labels OCI** completas (cuatro para backend; tres para frontend) sin sobreescritura ni etiquetas inesperadas.
4. **Provenance** end-to-end (extractor de PR + validador + suite `provenance-contract`) verde para los mismos sujetos.
5. **Build inputs** sin cambios: contexto, Dockerfile, build-args, target, platforma.
6. **Imagen funcionalmente correcta**: el job `deploy` de `deploy-dev` levanta la imagen, los healthchecks pasan, y la sonda de origen desde la red de ingress responde.

Si alguna de las seis verificaciones falla en una imagen construida con cache hit/miss respecto a la imagen pre-change del mismo SHA, hay regresión y se roolea R4 — pero el criterio de rollback **no** es *"digest difiere"*, sino *"algún elemento de la invariante de D5 falla"*.

Rejected:
- **Modo `min`** — solo persiste las capas finales, no las intermedias; cache hit es menos eficaz.
- **Scope compartido `autohostai`** — mezclaría `multiarch-check` con `deploy-dev` y con cualquier futuro workflow de build; pierde la propiedad de "un fallo de cache solo afecta a su workflow".
- **Caché por `branch`** (modo `branch` en `docker/build-push-action@v6`) — apropiada para PRs (no contamina main), pero `gha,scope=...` ya cubre el caso con la granularidad que necesitamos.

### D5 — Qué significa preservar la identidad de imagen (R1.5 de `app-deploy-dev.md`)

**Chosen:** La invariante real de R1.5 **NO es "digest byte-identical"**, y este change **NO** introduce ni verifica byte-identicalidad de capas, manifest, config, Id ni RepoDigests. La invariante del proyecto es la conjunción de seis elementos verificables, todos declarados en `app-deploy-dev.md` y en `deploy-dev.yml`:

1. **SHA/revision**: `org.opencontainers.image.revision` es el SHA del commit (`deploy-dev.yml:94, 138`); verificable comparando contra `github.sha`.
2. **Version canónica**: el campo `version` producido por el job `provenance` cumple `X.Y.Z+YYYY-MM-DD.<7 hex minúsculos>`, con fecha UTC válida y `commit_short` igual al sufijo, validado en el workflow antes de publicar (`app-deploy-dev.md:15-21`). Verificable leyendo `org.opencontainers.image.version` de la imagen.
3. **Labels OCI**: el manifest de la imagen lleva los labels declarados en `deploy-dev.yml:92-96` (backend: `source`, `revision`, `version`, `created`) y `deploy-dev.yml:137-140` (frontend: `revision`, `version`, `created`). **Inmutables** porque vienen de `provenance.outputs.*` y del SHA del commit.
4. **Provenance**: los campos `repository_url`, `pull_request_number`, `commit_sha`, `actions_run_id` publicados como outputs del job `provenance` (`app-deploy-dev.md:30-40`) y escritos al `.env` de la VM. Verificable en runtime vía los endpoints que `frontend-tests › provenance-contract` ya ejercita.
5. **Build inputs**: el contexto (`backend/` o `frontend/`), el Dockerfile (`backend/devops/Dockerfile` o `frontend/devops/Dockerfile`), los build-args (`NEXT_PUBLIC_APP_ENV`, `NEXT_PUBLIC_APP_VERSION`, `NEXT_PUBLIC_BUILD_COMMIT_SHORT`), target (`prod`), y platforma son los declarados en `deploy-dev.yml`. **Este change no los modifica.**
6. **Imagen funcionalmente correcta**: el deploy job de `deploy-dev` la levanta, `up -d --wait` la considera healthy, y la sonda de origen desde la red de ingress responde correctamente. La imagen no es "válida" si no se puede desplegar y servir tráfico.

**Qué SÍ cambia con `cache-from: type=gha`**:
- El **camino** que BuildKit toma para producir las capas. Una cache hit reutiliza una capa ya construida; una cache miss la reconstruye. **El cambio solo afecta al tiempo de build**, no a ninguno de los seis elementos de la invariante.

**Lo que el change verifica, en este orden** (no la forma — el orden; las verificaciones se hacen post-merge durante 30 días):

1. **SHA/revision** en la imagen publicada: `org.opencontainers.image.revision` igual al SHA del commit que la disparó. Verificable con `docker inspect ghcr.io/<owner>/autohostai-{backend,frontend}:sha-<sha> --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'`.
2. **Version canónica** en la imagen publicada: `org.opencontainers.image.version` cumple `X.Y.Z+YYYY-MM-DD.<7 hex>`. Verificable con el mismo `docker inspect`.
3. **Labels OCI** completas (los cuatro del backend; los tres del frontend): `docker inspect` lista los esperados sin sobreescritura ni etiquetas inesperadas.
4. **Provenance**: el `extract-pr.sh` extractor y el `validate-provenance-contract.py` siguen pasando para los mismos sujetos de commit; verificable corriendo la suite `provenance-contract` (parte del job `frontend-tests`, conservada por D2).
5. **Build inputs**: el `Dockerfile`, el contexto y los build-args son los declarados en el workflow — verificable leyendo el log del job `build-backend`/`build-frontend`.
6. **Imagen funcionalmente correcta**: el job `deploy` de `deploy-dev` se ejecuta sobre la imagen cacheada con el mismo resultado funcional (healthchecks pasan, sonda de ingress OK). Si `deploy-dev` falla post-cambio con la misma imagen pre-cambio, hay regresión y se roolea R4.

**Lo que el cambio NO exige ni verifica**:
- ~~Layer digest byte-identical entre cache hit y cache miss~~ — no es la invariante, y construir reproducible builds queda fuera del alcance del change.
- ~~Manifest/config digest byte-identical~~ —idem.
- ~~`Id`/`RepoDigests` byte-by-byte~~ —idem.
- ~~Que el binario del navegador sea idéntico entre ejecuciones~~ — el binario de Playwright vive en el runner, no en la imagen.

**Si alguna de las seis verificaciones falla**, el cache está mintiendo capas o algo cambió sin querer. R8.1+R8.4+R8.5 del proposal (preservar invariantes) cubren esto: el cache no altera ninguno de los seis elementos de la invariante — solo cambia el camino de producción de capas — y si lo hiciera, las seis verificaciones lo detectarían.

**Por qué se eliminó toda mención a byte-identical digests** (decisión del usuario, registrada en la revisión del design): la primera versión del design hacía afirmaciones del tipo *"el digest de cada capa es byte-identical con o sin cache hit"*. Esas afirmaciones eran una **garantía técnica más fuerte que la invariante del proyecto** y dependían de la hipótesis adicional de que el build es bit-reproducible — algo que este change **no** verifica ni necesita verificar. Construir reproducible builds es un work-item separado que excede el alcance de R4. La verificación de R4 se limita a los seis elementos de arriba.

Rejected:
- **Forzar reproducible builds (byte-identical entre cache hit y cache miss)** — fuera de scope. Es un work-item propio con su propio panel; el coste de auditar bit-reproducibilidad es desproporcionado para el ahorro que R4 ya produce.
- **Hashing manual del árbol de fuentes antes del build** — overkill; el SHA del commit ya lo da el job `provenance`.
- **Comparar `docker inspect` byte-a-byte** — eso era la verificación anterior y confundía "imagen equivalente" con "imagen bit-idéntica". Se sustituye por las seis verificaciones de arriba, que cubren lo que R1.5 declara.

### D6 — Retirada de `pytest-cov` como dependencia muerta (R6)

**Chosen:**
- Quitar la línea `"pytest-cov>=7.0.0"` del array `[dependency-groups].dev` en `backend/pyproject.toml:59-68`.
- Regenerar `backend/uv.lock` con `uv lock` para que el lockfile deje de listar `pytest-cov` como dependencia transitiva del grupo dev.
- Verificar que el grafo de CI **no cambia** (no hay workflow que invoque `--cov`; grep antes y después da cero resultados).
- Documentar en `sdd/specs/backend-ci.md` (afectado por el change) que **no se introduce cobertura real en este change**; queda como follow-up, y un change futuro que la introduzca deberá aportar su propia evidencia.

**Por qué pytest-cov es dependencia muerta** (R6.1): `grep -rn "pytest.*cov\|--cov" .github/workflows/` devuelve cero resultados. Está declarado en `pyproject.toml:66` y referenciado en `backend/uv.lock:132, 163, 1219`, pero ningún workflow lo invoca. El coste de incluirlo en el grafo es ~1 s por `uv sync`, invisible individualmente; el principio de "no meter dependencias que no usas" gana por higiene, no por minutos.

**Lo que NO cambia** (R6.4): `pytest>=9.1.1`, `pytest-asyncio>=1.4.0`, `pytest-xdist>=3.6.1`, los flags de invocación (`uv run pytest -q -rs -n 2`), las fixtures (`tests/conftest.py`), el shape de la suite.

**Por qué no introducir cobertura real en este change** (Out of scope): el change optimiza CI por la vía probada (conditional gates + cachés + trabajo redundante), no por la vía no probada (umbral de cobertura). El umbral vendría con su propia decisión de diseño (qué módulos cubrir, qué threshold, qué gate aplicar), y mezclarlo con este change inflaría el scope. Cuando llegue ese work-item, lo hará con su propio proposal.

Rejected:
- **Mantener `pytest-cov` declarado por si acaso** — el coste es trivial pero la señal de "dependencia declarada y no usada" es ruido en `pyproject.toml`. Mejor limpiar.
- **Pasar `pytest-cov` a `[project]` runtime** — no es runtime; pytest-cov solo tiene sentido como plugin de pytest, y pytest es dev dependency. No hay razón para declararlo en runtime.

### D7 — Métricas before/after (R7)

**Chosen:** Crear `sdd/changes/ci-pr-gates-optimization/metrics.md` (mencionado en Affected specs del proposal) durante `/sdd:tasks`, con dos secciones: **Baseline** (antes del merge) y **Targets** (a 30 días post-merge). LaBaseline se construye copiando los runs observados durante la auditoría y durante `/sdd:run` (cuando aplique); los Targets se copian del R7.2 del proposal.

**Métricas concretas a registrar:**

| Métrica | Baseline observado (2026-09-02) | Target (30 días) |
|---|---|---|
| Minutos jobs-seg/PR solo-prosa | ~564 s | ≤ 120 s |
| Minutos jobs-seg/PR backend+frontend | ~1.166 s | ≤ 800 s |
| Wall-clock del job más lento en PR promedio | ~11 min | ≤ 9 min |
| Suites ejecutadas por detect condicional | 1 (backend-tests) | ≥ 4 (+frontend-tests, compose-ports, rule11-ownership) |
| Descarga del browser binary de Playwright/PR | 1 por ejecución (~30-40 s) | 0 cuando existe cache hit para el mismo lockfile |
| Capas Buildx restauradas por `cache-from: type=gha` | 0 | hit rate ≥ 80 % en lockfile estable |

**Forma de medición durante `/sdd:run`**:
- Antes de tocar workflows: `gh run list --limit 30 --json databaseId,workflowName,event,conclusion` y snapshot del último mes por workflow.
- Después del merge: igual durante 30 días.
- El snapshot pre-cambio se conserva como `metrics-baseline.md` en `sdd/changes/ci-pr-gates-optimization/` durante la fase de tasks.

**Por qué métricas como `cache hit rate`** (no las propuso el proposal original pero R8.4 las hace necesarias): si la caché de Playwright y la de Buildx no se usan, la métrica de wall-clock no se mueve. Medir el hit rate separa "el change no funciona" de "el change funciona pero la cache nunca hit".

Rejected:
- **Medir cobertura como métrica de éxito** (R7.3) — explícitamente excluido por el proposal.
- **Medir satisfacción del desarrollador** (encuesta) — fuera del alcance del change; eso es feedback del proceso, no de CI.

### D8 — Diagramas y referencias visuales

No se generan diagramas nuevos. El flujo de tres jobs (detect / suite / consolidador) ya está descrito en `sdd/specs/backend-ci.md` y replicado por el comentario de cabecera de `backend-tests.yml:31-44`. La decisión de no producir un diagrama es deliberada: la asimetría con diagramas en otros changes no aporta; el patrón ya está probado y referenciado.

Si `/sdd:design` lo juzga útil más adelante, se puede añadir un diagrama de flujo (Mermaid) que muestre los tres jobs de `frontend-tests` con flechas condicionales — pero no es necesario para entender el diseño.

## Changes by area

| Area | Files | Change |
|---|---|---|
| `.github/workflows/frontend-tests.yml` | reestructurar de dos jobs (`provenance-contract` + `frontend-tests`) a **tres jobs** siguiendo el patrón de `backend-tests.yml`: `frontend-tests-detect` (siempre, ~9 s) + `frontend-tests-suite` (condicional con `if: needs.frontend-tests-detect.outputs.frontend == 'true'`) + `frontend-tests` (consolidador con `if: always()`). Las cinco señales de `provenance-contract` y las cuatro de `frontend-tests` (total 9 gates) se ejecutan dentro del job `frontend-tests-suite` con un único `npm ci` (D2); `actions/cache@v4` para `~/.cache/ms-playwright` (D3). El check estable `frontend-tests` es el del consolidador (R1.1). | Modificar |
| `.github/workflows/compose-ports.yml` | reestructurar a **tres jobs**: `compose-ports-detect` (decide `compose` bool + `reason`) + `compose-ports-suite` (condicional, corre `make check-compose-ports` + `pytest scripts/ -q`) + `compose-ports` (consolidador `if: always()`, publica motivo de skip legítimo). El check estable `compose-ports` es el del consolidador. | Modificar |
| `.github/workflows/rule11-ownership.yml` | reestructurar a **tres jobs**: `rule11-ownership-detect` (decide `rule11` bool + `reason`) + `rule11-ownership-suite` (condicional, corre `make check-rule11-ownership` + `pytest scripts/test_rule11_ownership.py -q`) + `rule11-ownership` (consolidador `if: always()`, publica motivo de skip legítimo). El check estable `rule11-ownership` es del consolidador. | Modificar |
| `.github/workflows/multiarch-build-check.yml` | añadir `cache-from: type=gha,scope=multiarch-{backend,frontend}` y `cache-to: type=gha,mode=max,scope=multiarch-{backend,frontend}` en cada `docker/build-push-action@v6`. | Modificar |
| `.github/workflows/deploy-dev.yml` | añadir `cache-from: type=gha,scope=deploy-{backend,frontend}` y `cache-to: type=gha,mode=max,scope=deploy-{backend,frontend}` en cada `docker/build-push-action@v6`. **Sin cambios** en `provenance`, `deploy`, ni en las labels OCI. | Modificar |
| `backend/pyproject.toml` | quitar `"pytest-cov>=7.0.0"` del array `[dependency-groups].dev`. | Modificar |
| `backend/uv.lock` | regenerar con `uv lock` para reflejar la retirada. | Regenerar |
| `sdd/specs/backend-ci.md` | añadir nota sobre el patrón ya replicado; nota explícita de que pytest-cov no se invoca y que no se introduce cobertura en este change. | Modificar |
| `sdd/specs/frontend-ci.md` | añadir R sobre detección de área para `frontend-tests`; documentar la caché de Playwright; documentar la consolidación del `npm ci`; preservar el resto. | Modificar |
| `sdd/specs/multiarch-build-check.md` | *(no existe aún — crear al archivar)* documentar la caché de capas Buildx con scope por workflow; referenciar R1.5 de `app-deploy-dev.md` para la invariante de identidad. | Crear |
| `sdd/specs/compose-ports.md` | verificar existencia; añadir R de detección de área; preservar la postura de red. | Crear o modificar |
| `sdd/specs/rule11-ownership-guard.md` | añadir R de detección de área; preservar el censo y la regla de scope. | Modificar |
| `sdd/changes/ci-pr-gates-optimization/metrics.md` | baseline + targets (R7). | Crear |

## Data & interfaces

**Schema changes:** ninguna.

**API contracts:** ninguno. Este change no toca el backend ni el frontend en su superficie pública.

**Events:** ninguno. Los workflows siguen disparándose por `pull_request`, `push: branches: [main]`, `workflow_dispatch` y `schedule` (los que apliquen), sin cambios.

**Config / env vars:**
- `BACKEND_SUITE_BUDGET_SECONDS` y `BACKEND_SUITE_CEILING_SECONDS` **NO** se modifican (R7 fuera de scope).
- `concurrency` y `timeout-minutes` de cada job se preservan.
- Nuevos `outputs` por `*-detect` job: `<area>` (bool, "true"|"false") y `reason` (literal cerrado).
- Nuevos secrets: ninguno.
- Nuevas variables de repo: ninguna.

**Cachés de GitHub Actions**: dos namespaces nuevos — `playwright-${{ hashFiles('frontend/package-lock.json') }}` (gestionado por `actions/cache@v4`) y los `gha` scopes de Buildx (`multiarch-backend`, `multiarch-frontend`, `deploy-backend`, `deploy-frontend`). Los primeros se purgan automáticamente por TTL de GitHub (7 días sin hit). Los segundos también (cache de GHA).

## Risks & mitigations

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| La detección de área omite un path legítimo y la suite se salta cuando debería correr | Baja (mismo patrón probado en `backend-tests-detect`) | Alto (falso verde) | R1.5/R5.4: arranco en `true`, baja solo con afirmación positiva. La case es literal, no regex. `core.quotePath=false` y `--no-renames` ya documentados. Verificación post-merge: 5 PRs de cada área tocada y comprobar que la suite corre. |
| Cache de Playwright sirve un binario desactualizado si el lockfile cambia sin bump de versión | Muy baja | Alto (Chromium desactualizado puede tener CVEs) | Key = `hashFiles('frontend/package-lock.json')`. Cualquier cambio en el lockfile genera nueva key; el binario cacheado anterior queda huérfano y expira por TTL. Verificación: el cache miss en el PR que actualiza `playwright@x.y.z` baja el binario nuevo. |
| Cache de Buildx sirve capas de un SHA anterior | Baja (los scopes son disjuntos y la cache es por repo+branch) | Medio (reproducibilidad comprometida) | Scopes disjuntos entre workflows. `cache-from` no es `cache-to: mode=max` automático: se persiste solo lo que el job actual construye. Verificación D5: confirmar que la imagen del mismo SHA se publica con los seis elementos de la invariante (SHA/revision, version canónica, labels OCI, provenance, build inputs, imagen funcionalmente correcta) y que el deploy job termina OK. |
| `pytest-cov` retirado rompe un test que lo invocaba por reflexión | Muy baja | Bajo | `grep -rn "pytest.*cov\|--cov\|pytest-cov" backend/ .github/` debe dar cero. La línea en `backend/pyproject.toml:66` es el único uso declarativo. |
| El `cache-from: type=gha` introduce variabilidad entre runners (cache hit/miss asimétrico) | Baja | Muy bajo | La invariante del change (D5) no exige reproducibilidad bit-a-bit; cache hit/miss solo afecta al tiempo de build. La métrica cache hit rate (D7) detecta si el cache se está usando. |
| `multiarch-build-check` cache污染 (R4): un PR introduce una capa maliciosa que termina en la cache de `multiarch-backend` | Muy baja | Alto | El cache de `gha` se purga por TTL (7 días) y solo el repo tiene acceso. GHA **aísla las caches por `ref`** (coherente con la fila §12 de abajo): una cache escrita desde `refs/pull/N/merge` no es restaurable desde otro PR — solo desde ese mismo `ref` (y sus descendientes) y desde la rama base —, así que un PR **no** puede envenenar la cache que consume otro PR. Además `multiarch-build-check` no publica (`push: false`), con lo que la superficie de impacto es nula. Para `deploy-dev` (que sí publica), el cache hit solo afecta velocidad, no al contenido final; una capa maliciosa en la cache produciría una imagen que no satisface los seis elementos de la invariante de D5 (SHA/revision, version canónica, labels OCI, provenance, build inputs, funcionalmente correcta), y el job `deploy` con su preflight + healthchecks + sonda de ingress lo detecta. |
| **Riesgo aceptado (§12, SEC-low):** este change añade un canal de escritura persistente (`cache-to: type=gha,mode=max`) al workflow `multiarch-build-check.yml`, que sigue usando acciones con tags flotantes (`actions/checkout@v4`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/build-push-action@v6`) y sin bloque `permissions:`. Un tag upstream movido/comprometido ejecutaría en un job que ahora también escribe a la cache de Actions. | Muy baja | Medio (cadena de suministro) | **Aceptado, no remediado en este change.** El pinneo por SHA + `permissions: contents: read` de `multiarch-build-check.yml` fue **diferido por decisión explícita del usuario** (tasks.md:189) como work-item pre-existente fuera del alcance. El blast radius está acotado: GHA aísla las caches por `ref`, el workflow dispara solo en `pull_request` con `paths:`, y `push: false` (no publica). La única novedad de este change es el `cache-to`; queda registrado aquí como riesgo aceptado hasta que se aborde el pinneo en un change dedicado. |

## Open questions

Ninguna para este change. Las cuatro decisiones del usuario tras aprobar el proposal ya están incorporadas como D2 (no node_modules cache), D4 (sí deploy-dev cache, scope separado), D1/D5 (no api-contract ni frontend-api-contract detection — quedan fuera), y la retirada del R7 (re-baseline). El design se entrega cerrado sobre esas decisiones; el resto lo decide `/sdd:tasks`.

**Decisiones que necesitan verificación durante `/sdd:run`**, no en este design:
- Si el `cache-from: type=gha,scope=multiarch-frontend` produce hit rates aceptables desde el primer PR (algunas caches tardan 1-2 ejecuciones en popularse). Si el primer PR sigue frío, no es un fallo del change — es la primera ejecución sin historial.
- Si el `npm ci` único dentro del job `frontend-tests-suite` se vuelve dominante cuando la suite frontend crezca. Plan B (si la métrica no se mueve): aceptar el `npm ci` redundante y volver a la estructura de `frontend-tests.yml` original (dos jobs `provenance-contract` + `frontend-tests`, sin detect). Hoy la suite es ~330-400 s; el `npm ci` representa <10 % del job y no se considera un problema.
