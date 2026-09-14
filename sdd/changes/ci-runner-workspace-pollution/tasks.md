# Tasks: ci-runner-workspace-pollution

## 1. El stack local deja de escribir en el árbol <!-- panel: PASS 2026-09-14 receipt:9e5e9eaf -->

- [x] 1.1 Declarar `PYTHONDONTWRITEBYTECODE: "1"` en el `environment:` de `migrate`, `backend`, `worker` y `beat` — `docker-compose.yml`. Comentario corto que diga por qué (bind mount del árbol + `_work/` del runner), no qué. [R1.1]
- [x] 1.2 Crear `[tool.pytest.ini_options]` en `backend/pyproject.toml` con `cache_dir` fuera del árbol (p. ej. `/tmp/pytest_cache`) — `backend/pyproject.toml`. [R2.1]
- [x] 1.3 Verificar en el worktree que el ciclo real no ensucia: `make up`, correr la suite dentro del contenedor, y comprobar que `find backend -name __pycache__ -o -name .pytest_cache` sale vacío y que el árbol de trabajo no tiene entradas nuevas sin rastrear. Dejar la evidencia (comandos y salida) en Implementation Notes. [R1.2, R1.3, R2.2]
- [x] 1.4 Comprobar que la suite sigue corriendo con la caché en una ruta no escribible (p. ej. `cache_dir` apuntando a un directorio sin permiso): `pytest` debe degradar sin fallar. Si fallara, reajustar la ruta elegida en 1.2. [R2.3]

## 2. Guard: la regla no depende de que alguien la recuerde <!-- panel: PASS 2026-09-14 receipt:a24cdfcb -->

- [x] 2.1 Escribir `scripts/compose-bytecode.py`: deriva de la composición **resuelta** los servicios que montan el árbol del repositorio por bind mount y exige que declaren `PYTHONDONTWRITEBYTECODE`. Reutiliza la invocación de `scripts/compose-ports.py` (`config --no-interpolate --no-env-resolution` y el suelo Compose 2.35.0) — `config` desnudo vuelca el `.env` entero. Falla nombrando el servicio incumplidor. [R5.1, R5.2, R5.3]
- [x] 2.2 Tests del guard en `scripts/test_compose_bytecode.py`, con al menos: servicio con bind mount y sin la variable → falla nombrándolo; todos conformes → pasa; **servicio nuevo con bind mount que no está en ninguna lista del propio guard → falla** (es el caso que distingue el guard de una lista de nombres); servicio sin bind mount y sin la variable → no se exige. [R5.2, R5.4]
- [x] 2.3 Añadir el target `check-compose-bytecode` al `Makefile`, junto a `check-compose-ports` y con la misma forma. [R5.1]
- [x] 2.4 Engancharlo como paso del workflow `compose-ports` existente — `.github/workflows/compose-ports.yml`. No crear workflow nuevo (design D8); respetar el patrón detect/suite/gate que ese fichero ya tiene y no tocar su `on:`, `concurrency`, `permissions` ni `timeout-minutes`. [R5.1]

## 3. El hook del runner

- [ ] 3.1 Crear `infra/environments/dev/runner-job-started.sh`: valida que la ruta de trabajo es absoluta, existe y termina en `/_work` antes de usarla; si la validación falla, no actúa. [R3.1, R3.6]
- [ ] 3.2 Short-circuit: buscar el primer fichero cuyo dueño no sea el usuario del agente (`find … ! -user … -print -quit`) y terminar con éxito sin escribir nada si no hay ninguno. [R3.4]
- [ ] 3.3 Cuando sí hay ficheros ajenos, `chown -R` del `_work/` propio al usuario del agente, y registrar en stdout qué encontró y qué hizo. El hook devuelve 0 salvo que el `chown` falle de verdad — su código de salida distinto de cero falla el job. [R3.3, R3.5]
- [ ] 3.4 Tests del hook en `infra/environments/dev/test_runner_job_started.sh` (o equivalente ejecutable desde la suite del repo), sobre directorios temporales: caso limpio → sin escrituras y salida 0; caso con fichero ajeno → lo deja accesible; ruta inválida (relativa, inexistente, sin sufijo `/_work`) → no actúa y lo dice; fallo del `chown` → salida distinta de cero con el `RUNNER_HOME` en el mensaje. [R3.3, R3.4, R3.5, R3.6]

## 4. El bootstrap instala, declara y hace efectivo el hook <!-- hard -->

- [ ] 4.1 `runner-bootstrap.sh`: instalar el hook en `$RUNNER_HOME/hooks/` con dueño y modo correctos, por agente `i ∈ [1..RUNNER_COUNT]` — `infra/environments/dev/runner-bootstrap.sh`. Mantener la idempotencia del script. [R3.2]
- [ ] 4.2 Escribir `$RUNNER_HOME/.env` con `ACTIONS_RUNNER_HOOK_JOB_STARTED` apuntando a la ruta absoluta del hook instalado, preservando cualquier otra clave que el fichero ya tuviera. [R3.2]
- [ ] 4.3 Reinicio condicional: si el `.env` cambió respecto al anterior, reiniciar el servicio de ese agente; sólo si el agente no tiene un job en vuelo, con la misma guardia de liveness (`systemctl is-active`) que usa la fase de baja. Sin esto el hook se instala y **ningún runner lo relee** (design D4) — es el fallo silencioso más probable del change. [R3.2]
- [ ] 4.4 Hacer que el hook viaje a una VM nueva igual que el bootstrap: `runner_job_started = file(...)` en `infra/environments/dev/main.tf` y su `write_files` en `infra/environments/dev/cloud-init.yaml.tftpl`. No tocar `source_id` ni la forma de `metadata` — es ForceNew y un cambio ahí reemplaza el disco de la VM viva. [R3.2]

## 5. Documentación

- [ ] 5.1 `RUNBOOK.md §6.2`: añadir la copia del hook al procedimiento de la VM viva, la nota de que el `.env` exige reiniciar el agente, y el despliegue escalonado (primero `actions-runner-2`, observar, luego el resto — design D9). Incluir cómo verificar que la variable está en el proceso vivo, no sólo en disco. [R4.1]
- [ ] 5.2 `docs/ci-runner-rollback.md`: cómo desactivar el hook sin desaprovisionar el pool. [R4.1]
- [ ] 5.3 README raíz: el guard nuevo en la sección de comandos/tests, junto a los checks de composición que ya se listan (lo exige `steering/documentation.md`: comando de Makefile nuevo → README al día). [R4.2]
- [ ] 5.4 Dejar escrito, donde se lee al tocar un workflow, que un fallo de `actions/checkout` **no es mitigable desde ningún paso del workflow** y por eso la defensa vive en el hook; y el incidente del 2026-09-14 con sus identificadores de run (`34836602502`, `34840316768`, `34824905559`) como evidencia. [R4.1, R4.3]

## 6. Verification

- [ ] 6.1 Suite del backend completa: `docker compose exec backend uv run pytest`. [R1, R2]
- [ ] 6.2 Guards del repo en verde: `make check-compose-bytecode`, `make check-compose-ports`, `make check-rule11-ownership`, y `python3 scripts/check-detect-surface.py` para `compose`, `e2e`, `frontend` y `rule11`. [R5]
- [ ] 6.3 Tests de los scripts nuevos: `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/test_compose_bytecode.py -q` y los del hook (3.4). [R3, R5]
- [ ] 6.4 Aplicar el bootstrap en la VM `dev` siguiendo `RUNBOOK.md §6.2`, **sólo sobre `actions-runner-2`** primero; comprobar que la variable está en el proceso vivo del runner, lanzar varios jobs reales contra ese agente y confirmar que pasan. [R3.2] <!-- manual -->
- [ ] 6.5 Extender el hook a los tres agentes restantes y confirmar los cuatro `online` con jobs pasando. [R3.2] <!-- manual -->
- [ ] 6.6 Comprobación de regresión del incidente: en un agente con el hook, dejar un fichero de root dentro de su `_work/` y verificar que el siguiente job supera el `actions/checkout` en vez de morir con `EACCES`. [R3.3] <!-- manual -->

## Implementation Notes

- 1.2: `cache_dir` chosen = `/tmp/pytest_cache` (as suggested by the task), declared in `backend/pyproject.toml` under `[tool.pytest.ini_options]`.
- 1.1: comment used in `docker-compose.yml`, verbatim on each of the four services (`migrate`, `backend`, `worker`, `beat`): `# ./backend:/app is a bind mount onto this tree, which on the CI VM is the runner's` / `# persistent _work/ — a stray .pyc there survives the container and, root-owned,` / `# blocks the next job's checkout.`
- 1.3 evidence — commands run and results:
  - `docker compose config --no-interpolate --no-env-resolution --quiet` → exit 0 (compose file parses after 1.1).
  - `python3 -c "import tomllib; tomllib.load(open('backend/pyproject.toml','rb'))"` → parses OK (after 1.2).
  - `cp .env.example .env` (no `.env` existed in this worktree), then `make up` → full stack up (`postgres`, `redis` healthy; `migrate` exited 0; `backend`, `worker`, `beat`, `frontend` started).
  - `docker compose exec backend uv run pytest` → `1 failed, 11156 passed, 44 skipped in 642.18s`. The one failure, `tests/messaging/test_repositories.py::test_two_concurrent_callers_end_with_one_thread_and_both_see_it`, asserts a specific lock-contention race (`the loser never blocked on the winner's row`) and is a known host-contention flake, not a regression from this section — re-run in isolation (`docker compose exec backend uv run pytest tests/messaging/test_repositories.py::test_two_concurrent_callers_end_with_one_thread_and_both_see_it -q`) → `1 passed in 0.75s`.
  - `find backend -name __pycache__ -o -name .pytest_cache` → empty, both right after the full suite run and after the isolated re-run.
  - `git status --porcelain` → only the three files this section modified (`backend/pyproject.toml`, `docker-compose.yml`, `sdd/changes/ci-runner-workspace-pollution/tasks.md`); no untracked entries from the container runs.
- 1.4 evidence: pointed `cache_dir` at a genuinely read-only mount (`-v /tmp/pytest_cache_ro_test:/tmp/pytest_cache:ro` via `docker compose run --rm --no-deps`, since the container runs as root and `chmod 000` alone does not block root) and ran the same single test: `Bytecode compiled 3059 files in 286ms` / `PytestCacheWarning: could not create cache path /tmp/pytest_cache/v/cache/nodeids: [Errno 30] Read-only file system` / `1 passed, 1 warning in 0.65s`. Confirms R2.3: pytest degrades to a warning and does not fail; `cache_dir` from 1.2 did not need to change. Post-hoc `find`/`git status --porcelain` were clean again after this run.
- **R5.1/D8 amended before 2.1** (see `proposal.md`/`design.md`, commit `809e1519`): the approved text had no "Python" qualifier and, checked against the real resolved model, `frontend` also has a writable bind mount of its own tree (`./frontend:/app`, `read_only` absent) — would have pulled it into the guard for a var that's a no-op on Node, and would have reopened section 1 (already panel-PASSed). Resolved with the user before writing any guard code: scope is "Python service" via `build.context` resolving to `backend/` — the same structural signal the compose file already uses to tell the four Python services from `frontend`.
- 2.1: `scripts/compose-bytecode.py` derives scope with two structural checks on the resolved model (`docker compose config --no-interpolate --no-env-resolution --format json`), no service-name list: `is_python_service` (`build.context` realpath == `<repo_root>/backend`) and `writable_tree_bind` (a `volumes` entry with `type: bind`, no `read_only`, `source` under the repo root). `declares_var` accepts any non-empty string — matches CPython's actual semantics for `PYTHONDONTWRITEBYTECODE`, not just the literal `"1"`. Verified both paths for real: ran clean against the actual repo compose (4/4, `frontend` excluded), then temporarily stripped the var from `migrate` in `docker-compose.yml` to confirm a genuine red before restoring it (`git status --porcelain` clean afterward).
- 2.2: 16 tests, pure-fixture style like `test_compose_ports.py` (no real Docker for the unit cases; one `@pytest.mark.skipif`-guarded integration test does call real `docker compose config` against the actual repo file). The R5.4-distinguishing case (`test_a_new_python_service_not_named_anywhere_here_is_in_scope`) uses a service named `mailer-worker`, which appears nowhere else in the test file or the guard.
- 2.3/2.4: `check-compose-bytecode` target added right after `check-compose-ports` in the `Makefile`, same "outside `$(COMPOSE)`" reasoning (bare `docker compose config`, not through the worktree port-overlay). Hooked into `compose-ports-suite` in `.github/workflows/compose-ports.yml` as a new step right after the existing `make check-compose-ports` step; `on:`/`concurrency`/`permissions`/`timeout-minutes` untouched. No detect-job or `check-detect-surface.py` changes needed: `compose-ports-detect`'s `case` already matches `scripts/*` and `Makefile`, and `compose_surface()` in `check-detect-surface.py` already walks all of `scripts/` — both cover the two new files automatically. `pytest scripts/ -q` (already run by `compose-ports-suite`) picks up `test_compose_bytecode.py` without any change to that step. Verified: `python3 scripts/check-detect-surface.py compose` → OK; `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q` → 288 passed (up from 272, i.e. exactly the 16 new tests).
