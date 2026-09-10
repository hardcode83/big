# Tasks: sim-advance

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     the task item, not only the checkbox line. -->

## 1. Settings — campo `environment` y `.env.example` <!-- panel: PASS 2026-09-10 receipt:db36aed1 -->

- [x] 1.1 Añadir `environment: Literal["local","dev","staging","production"] = "local"` a `backend/app/core/config.py`, leída de la variable `APP_ENVIRONMENT`, con docstring que cite a D1 (la guardia de R2) y a un consumidor futuro plausible. [R2]
- [x] 1.2 Añadir `APP_ENVIRONMENT` a `backend/.env.example` con el comentario «en deploy se debe poner a `production` o `staging`», sin valor por defecto (el default vive en código). [R2]
- [x] 1.3 Test unitario en `backend/tests/test_settings_environment.py` (o se añade a `tests/test_config.py` si existe esa convención) que verifique que `settings.environment` rechaza valores fuera de la `Literal` al instanciar. [R2, R4]

## 2. CLI `sim_advance` — argumentos, parseo, guardia, bucle <!-- panel: PASS 2026-09-10 receipt:92c4fd29 -->

<!-- hard: el cableado importa el orden de los tres jobs, el manejo de `now`, la disciplina de sesión marcada y el exit code; cualquier desviación rompe la idempotencia que ya tienen los jobs por separado. -->

- [x] 2.1 Crear `backend/app/cli/sim_advance.py` con `main()` que parsea `--tenant` (UUID, requerido) y `--at` (ISO 8601 con `tzinfo=UTC`, opcional) vía `argparse`. Refused `--at` naive con mensaje legible y exit code 1. Imprime el `now` resuelto en la primera línea, con el formato `sim-advance: now = <iso>`. [R1]
- [x] 2.2 Implementar en `sim_advance.py` la guardia de entorno de D5: si `settings.environment not in {"local","dev"}`, imprimir mensaje con el valor leído y los valores aceptados, exit code 1, **antes** de tocar la base de datos. [R2]
- [x] 2.3 Implementar el bucle de los tres disparadores en orden `CHECKIN_WINDOW_OPENED` → `CHECKIN_TIME_REACHED` → `CHECKOUT_TIME_REACHED`, cada uno con su propia sesión marcada por `bind_session_to_tenant`, su propia `UnitOfWork` (`SqlAlchemyUnitOfWork(session)`) y su propio `commit`, replicando el wiring de `scheduler/tasks.py::_advance` (con `provisioner=ProvisionCleaningTaskUseCase(...)` sólo para `CHECKOUT_TIME_REACHED`, copiando `seed_demo._advance_states:1615-1628` literal). Comentario al inicio de la función que apunte a la fuente. [R1, R3]
- [x] 2.4 Formato de salida de D4: una línea por job con `tenant=<uuid> trigger=<value> candidates=<n> transitioned=<n> blocked=<n> ambiguous=<n> unresolvable_time=<n> transitioned_without_task=<n>`; añadir `not_eligible=<n>` cuando el caso de uso lo emita. Exit codes de D4 (0 todos bien, 1 todos fallaron, 2 alguno pero no todos). Capturar excepciones por job con `logger.exception("sim_advance.job_failed", extra={"task": ..., "tenant_id": str(...)})`. [R1]

## 3. Tests del CLI — los cuatro escenarios de R4 <!-- panel: PASS 2026-09-10 receipt:b249292d -->

- [x] 3.1 Test R4.1 en `backend/tests/test_sim_advance_cli.py`: crear una reserva `CONFIRMED` con `check_in_date` hoy y `check_out_date` hoy+2 en `Europe/Madrid`; invocar el CLI con `--at` igual al instante del check-in + 1 min; verificar `property.current_operational_state == OCCUPIED_ESTIMATED` e informe `transitioned: 1`. [R4]
- [x] 3.2 Test R4.2 en el mismo fichero: sobre la reserva ya `CHECKED_IN_ESTIMATED`, invocar CLI con `--at` igual al instante del check-out; verificar `AWAITING_CLEANING`, `transitioned: 1`, `transitioned_without_task: 0`; verificar que `reservation.check_in_date` y `reservation.check_out_date` no cambian. [R4]
- [x] 3.3 Test R4.3 en el mismo fichero: invocar CLI con `--at` 3 horas antes del check-in; verificar que la vivienda **no** transiciona y el informe del primer job incluye `not_eligible: 1` (o el cubo equivalente que el caso de uso emita para «la hora aún no ha llegado»). [R4]
- [x] 3.4 Test R4.4 en el mismo fichero: parchear `settings.environment` a `"staging"` con `monkeypatch.setattr`, invocar CLI; verificar exit code 1 y mensaje de guardia en stderr; verificar que **no** se ha creado ninguna fila de `property_state_transitions` ni de `TimelineEvent`. [R2, R4]

## 4. Makefile y `docker-compose.deploy.yml` <!-- panel: PASS 2026-09-10 receipt:68085f9d -->

- [x] 4.1 Añadir target `sim-advance` al `Makefile` raíz (junto a `bootstrap`, `seed-demo`, `demo-reset`, `openapi`) que invoque `$(COMPOSE) exec -T backend python -m app.cli.sim_advance --tenant $(TENANT)` y, si `$(AT)` está definido, `--at $(AT)`. Comentario de cabecera que diga: «sólo dev/local; no se publica en `docker-compose.deploy.yml`». [R5]
- [x] 4.2 Verificar que `docker-compose.deploy.yml` NO contiene ningún target, servicio, ni entrypoint que invoque `app.cli.sim_advance` (grep cruzado contra el nombre del módulo). Si lo contiene, eliminarlo y documentar en `Implementation Notes`. Si no, escribir `Implementation Notes` que diga «verificado, no estaba». [R2, R5]

## 5. Documentación <!-- panel: PASS 2026-09-10 receipt:0f3f1992 -->

- [x] 5.1 Añadir a `docs/celery-jobs.md` una sección «Avanzar el reloj a mano en dev» con un ejemplo real (`make sim-advance TENANT=<uuid>` y `make sim-advance TENANT=<uuid> AT=<iso>`), las dos trampas de ventana (30 días atrás / 2 adelante, y «hoy en la zona de la vivienda»), y la nota de dev/local. [R5]
- [x] 5.2 Corregir el conteo «Los nueve jobs» de `docs/celery-jobs.md:7` por la cifra vigente al cierre del archivo (medir contra `scheduler/tasks.py` y `scheduler/schedule.py`; el número actual es **doce** jobs: los cuatro de PRD §8.3, los cuatro de los changes que llegaron después, el mensual `generate_owner_statements`, `process_webhook_events` y `classify_incidents`). Si la cifra ha cambiado al ejecutar la tarea, ajustar el encabezado de la tabla. [R5]
- [x] 5.3 Sustituir el bloque heredoc de `infra/environments/dev/RUNBOOK-seed-demo.md:316-322` por la invocación a `make sim-advance` con `TENANT` adecuado y el `AT` justo. Mantener el resto de §5 (segunda limpiadora, `channel=DIRECT`, `PATCH` de fechas para estancia de un día). Añadir nota de que la receta original «corrompía fechas» y por qué `sim-advance` no lo hace. [R5]

## 6. Verification

<!-- Use the commands recorded in the consumer project's project.md; this
     template does not prescribe a language, framework, or test runner. -->
- [x] 6.1 Suite backend pasa: `docker compose exec backend uv run pytest` (atajo del `Makefile`, ejecutado desde la raíz del repo con el stack levantado). Si el stack no está levantado: `docker compose run --rm backend uv run pytest`. [R4]
- [x] 6.2 `make check-rule11-ownership` pasa: guardia de la regla 11 con la nueva copia de wiring del CLI, que sigue siendo una atribución a `AdvancePropertyStatesUseCase` y por tanto no añade columna. [R2]
- [x] 6.3 Typecheck del backend: desde `backend`, `uv sync --frozen && uv run pyright .`. Cualquier finding se reporta en `Implementation Notes`, no en este checklist. [R4]
- [ ] 6.4 Manual: ejecutar `make sim-advance TENANT=<uuid>` contra el stack local con la reserva sembrada por `make seed-demo`, verificar que la vivienda `REDES11` (en `AWAITING_CHECKIN` tras el seed) avanza a `OCCUPIED_ESTIMATED` con `transitioned: 1`. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- Sección 6 (Verification): suite completa `docker compose run --rm backend uv run pytest` → **10955 passed, 44 skipped, 0 failed** (exit 0, 10:27). Los 4 tests de `test_sim_advance_cli.py` incluidos y en verde.
- `make check-rule11-ownership` → PASS, sin regresión: la copia del wiring en `sim_advance.py` es una atribución adicional a `AdvancePropertyStatesUseCase`, no una columna nueva del censo.
- Typecheck (`uv run pyright .`, host y contenedor, idéntico): **979 errores preexistentes**, cero de ellos en `backend/app/cli/sim_advance.py` ni en `backend/tests/test_sim_advance_cli.py` — ambos ficheros nuevos de este change están limpios. El patrón dominante (`No parameter named "_env_file"`, ~cientos de apariciones) ya existía en `backend/tests/test_config.py` antes de esta entrada (46 de las 49 apariciones actuales de `_env_file` son preexistentes, verificado contra el commit del proposal); es un desajuste conocido entre el stub de `pydantic-settings` y pyright, no una regresión de `sim-advance`. Se reporta aquí, aparte de los fallos de arranque, tal como pide `sdd/project.md`.
- 6.4 (manual) queda sin marcar y se registra como `deferred` en BLOCKED.md: requiere el stack levantado y `make seed-demo` corrido, que un run de `/sdd:auto` no ejecuta contra un stack real.

- Section 1: field is declared with `Field(alias="APP_ENVIRONMENT")`; the default pydantic-settings mapping would otherwise bind `environment` to `ENVIRONMENT` and silently ignore the prefixed name.
- Section 1: `APP_ENVIRONMENT=` is documented in `.env.example` as commented-out (`# APP_ENVIRONMENT=`) rather than uncommented-empty, because the `Literal` rejects `""` and there is no normalization validator like the one `_blank_whatsapp_provider_falls_back_to_default` provides; matching the form of other default-bearing settings (CORS allowlist, password recovery).
- Section 1: tests live in `backend/tests/test_config.py` per the convention there; the standalone `backend/tests/test_settings_environment.py` file proposed in the task does not exist.
- Section 1: the 13 reject cases include `""` and `"   "` deliberately — proves the `Literal` validation happens at instantiation and there is no blank-value escape hatch for a deploy that ships an empty env.
- Section 2: `_Parser` (subclass of `argparse.ArgumentParser`) overrides `error()` to `raise SystemExit(1)`; the default exits 2, which the verification commands for section 2 reject (`--tenant bad`, naive `--at`, env guard). pyright demands `-> NoReturn` on the override (base is `NoReturn`), so `typing.NoReturn` is imported.
- Section 2: the now line `sim-advance: now = <iso>` is printed BEFORE the env guard, BEFORE the tenant existence check — the verification expects an env-guard failure to still print the would-be now, so the order is parse → print now → guard → tenant-exists → jobs.
- Section 2: `--at` is parsed with `datetime.fromisoformat` and normalised via `.astimezone(UTC)`. Naive datetimes (`tzinfo is None`) raise `ArgumentTypeError`. Any tz-aware input (e.g. `+02:00`, `Z`) is accepted and converted to UTC, so the contract is "tz-aware, normalised to UTC" rather than the stricter "the offset must be UTC".
- Section 2: the three jobs reuse the Celery job names (`check_checkin_windows`, `mark_occupied_estimated`, `process_checkouts`) as `task_name`, and the report line's `trigger=` is the enum value (`CHECKIN_WINDOW_OPENED`/`CHECKIN_TIME_REACHED`/`CHECKOUT_TIME_REACHED`). The `AdvanceReport.trigger` field already carries the enum value; no remap is needed.
- Section 2: the `_advance` local copy wires `SqlAlchemyUnitOfWork(session)` per task 2.3 — NOT `CallerOwnedUnitOfWork()` like `seed_demo._advance_states:1635`. The provisioner block (8 repositories + the `if trigger is CHECKOUT_TIME_REACHED else None` ternary) is the literal copy of `seed_demo._advance_states:1615-1628`.
- Section 2 (review fix R1, finding R1.6 + D4): `_run_one_job` now returns `AdvanceReport | tuple[str, str]` instead of `AdvanceReport | None`; on failure it captures `(type(exc).__name__, str(exc))` after `logger.exception` and the for-loop prints `sim-advance: <trigger.value> FAILED: <cls>: <msg>` to stderr. The `isinstance(result, tuple)` discriminator keeps the success path untouched.
- Section 3: tests live at `backend/tests/test_sim_advance_cli.py` (top-level `tests/`, not `tests/cli/`) because the CLI test conftest at `tests/cli/conftest.py` pins the bootstrapped-tenant shape that R4 does not exercise — every test here inserts its own tenant via `tests.auth.conftest.insert_tenant`, which already creates the `TenantConfigModel` the use case's `get_or_create` expects.
- Section 3: the CLI's `worker_session_factory` is patched in the CLI module (`app.cli.sim_advance`), not on `app.scheduler.runner`, because `from app.scheduler.runner import worker_session_factory` binds the name into the CLI namespace; patching the binding where it was imported is what the `tests/auth/test_reset_password_cli.py` precedent does for the same reason.
- Section 3: the `not_eligible` cubo verified in R4.3 is the field `AdvanceReport.not_eligible` (design D7 in `use_cases.py:355-356`); `not_eligible=1` is the only bucket incremented when `opens_checkin_window` returns False — no other pre-judgement triggers this path for `CHECKIN_WINDOW_OPENED`.
- Section 3: for R4.1's `transitioned: 1` assertion the report line is filtered to `trigger=CHECKIN_TIME_REACHED` (not just a substring search); without scoping, "transitioned=1" also matches the `CHECKIN_WINDOW_OPENED` line that fires first (window opens 2 h before, and `now = check-in + 1 min` is inside it), and a regression in the second job is invisible.
- Section 3: for R4.2 the test seeds the property in `OCCUPIED_ESTIMATED` and the reservation in `CHECKED_IN_ESTIMATED` directly via `db_session`, then seeds a `CleaningChecklistTemplateModel`; without the template the provisioner's `resolve_template` raises `ChecklistTemplateNotFoundError`, returns `None`, and `transitioned_without_task` increments to `1` — the failure path of R2.4, not what R4.2 certifies.
- Section 3: row counts in R4.4 are taken on a fresh `AsyncSession(test_engine, expire_on_commit=False)` (the `db_session` fixture shares one transaction for the whole test, and a row written by the CLI's other session needs that fresh eye to be visible); `_count_rows` is local to the test, not a fixture, because the count is tenant-scoped to a row that only exists in this test.
- Section 3: the conftest's per-test vacuum (`_WIPE_EVERY_TABLE`) runs before every test, so `0` is the truth at the start of R4.4's count; the assertion `transitions_before == 0` is what makes the test self-checking against that vacuum and not against any other test's residue.
- Section 4: el target se inserta entre `demo-reset` y `openapi`, y `sim-advance` se añade a `.PHONY` justo después de `demo-reset` (no antes de `openapi`), para que el orden PHONY refleje el orden del recetario.
- Section 4: la guarda de `AT` se hace con `$(if $(AT),--at $(AT),)` y no con un `AT_ARG` separado: con `AT` vacío la función de `make` produce cadena vacía y deja un solo espacio entre `--tenant $(TENANT)` y el final; `docker compose exec` lo acepta como argumento vacío. La forma con variable auxiliar añadiría una variable sin valor añadido.
- Section 4: verificado, no estaba: `grep -nE 'sim[_-]advance' docker-compose.deploy.yml` sale en blanco (rc=1), así que la guardia de R2.3 se cumple sin tocar el fichero.
- Section 5: nuevo `## Avanzar el reloj a mano en dev` en `docs/celery-jobs.md` va entre `## Arrancar y mirar` y `## Cómo leer el informe`; cita `clock_triggers.py:42,52,55` (ventana) y `:94-122` (día local) — líneas verificadas contra el árbol, no reescribir sin recontar.
- Section 5: el conteo de `docs/celery-jobs.md:7` pasó de nueve a **doce**: 10 entradas en `CADENCES` + 1 en `DAILY_JOBS` + 1 en `MONTHLY_JOBS`, igual a los 12 `@celery_app.task` de `tasks.py`. La tabla ganó tres filas (`reconcile_owner_approvals_for_expenses`, `classify_reviews`, `generate_owner_statements`) y el párrafo de "dos tablas" pasó a "tres tablas" (`CADENCES`/`DAILY_JOBS`/`MONTHLY_JOBS`); "Seis son de PRD §8.3" ahora incluye el mensual (`PRD_8_3_MONTHLY` en `test_schedule.py`).
- Section 5: `RUNBOOK-seed-demo.md` §5 ya no usa `PATCH` de fechas ni el heredoc `python -m app.scheduler.tasks`; el paso 1 crea la reserva con fechas reales y las dos invocaciones de `sim_advance` (check-in, luego check-out) sustituyen a los tres jobs a mano.
- Section 5: verificado en `docker-compose.deploy.yml` / `.github/workflows/deploy-dev.yml` que `dev-runtime.env` NUNCA escribe `APP_ENVIRONMENT` — la guarda D5 en la VM cae al default `"local"` de `Settings`, que está permitido; el comando NO queda bloqueado allí (documentado explícitamente en el runbook, no asumido).
- Round-1 fix (finding 1, BLOCKED.md): entrada `assumed` de D1 añadida vía `sdd_lifecycle.py block` — el `deferred` 6.4 preexistente queda intacto.
- Round-1 fix (finding 2, docker-compose.deploy.yml / deploy-dev.yml / RUNBOOK-seed-demo.md): `APP_ENVIRONMENT` ahora obligatorio (`:?`) en `backend`/`worker`/`beat`; `deploy-dev.yml` lo escribe como literal `dev`; el RUNBOOK ya no dice que la VM nunca lo fija.
- Round-1 fix (finding 3, design.md): nuevo bullet R5 en "Risks & mitigations" documentando que el `:?` de docker-compose.deploy.yml es lo que cierra el riesgo de un futuro staging/prod sin `APP_ENVIRONMENT`.
- Round-1 fix (finding 4, sim_advance.py + test): `_build_parser` gana `epilog=` con los dos trampas de `--at` (ventana 30d/2d, huso horario local); nuevo test `test_help_names_the_window_clamp_and_local_timezone_traps`.
- Round-1 fix (finding 5, test_sim_advance_cli.py): R4.1 ahora asserta `TimelineEvent.created_at == at` (R3.3/D6) y `Reservation.created_at` sin cambios (R3.4).
- Round-1 fix (finding 6, test_sim_advance_cli.py): nuevo test `test_one_failing_job_exits_2_and_the_other_two_still_commit` cubre el exit code 2 y `logger.exception`.
- Round-1 fix (finding 7, test_sim_advance_cli.py): nuevo test `test_nonexistent_tenant_uuid_exits_1_and_runs_no_job` cubre R1.5.
- Round-1 fix (finding 8, test_sim_advance_cli.py): nuevo test `test_a_tenant_never_sees_another_tenants_rows`, mismo patrón que `tests/scheduler/test_runner.py`.
- Round-1 fix (finding 9, README.md): "diez tareas" → "doce tareas"; se nombran `reconcile_owner_approvals_for_expenses` y `generate_owner_statements`.
- Round-1 fix (finding 10, sim_advance.py): la línea `now =` ahora distingue `(--at)` de `(live clock)`.
