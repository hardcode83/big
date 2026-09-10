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

## 1. Settings — campo `environment` y `.env.example`

- [ ] 1.1 Añadir `environment: Literal["local","dev","staging","production"] = "local"` a `backend/app/core/config.py`, leída de la variable `APP_ENVIRONMENT`, con docstring que cite a D1 (la guardia de R2) y a un consumidor futuro plausible. [R2]
- [ ] 1.2 Añadir `APP_ENVIRONMENT` a `backend/.env.example` con el comentario «en deploy se debe poner a `production` o `staging`», sin valor por defecto (el default vive en código). [R2]
- [ ] 1.3 Test unitario en `backend/tests/test_settings_environment.py` (o se añade a `tests/test_config.py` si existe esa convención) que verifique que `settings.environment` rechaza valores fuera de la `Literal` al instanciar. [R2, R4]

## 2. CLI `sim_advance` — argumentos, parseo, guardia, bucle

<!-- hard: el cableado importa el orden de los tres jobs, el manejo de `now`, la disciplina de sesión marcada y el exit code; cualquier desviación rompe la idempotencia que ya tienen los jobs por separado. -->

- [ ] 2.1 Crear `backend/app/cli/sim_advance.py` con `main()` que parsea `--tenant` (UUID, requerido) y `--at` (ISO 8601 con `tzinfo=UTC`, opcional) vía `argparse`. Refused `--at` naive con mensaje legible y exit code 1. Imprime el `now` resuelto en la primera línea, con el formato `sim-advance: now = <iso>`. [R1]
- [ ] 2.2 Implementar en `sim_advance.py` la guardia de entorno de D5: si `settings.environment not in {"local","dev"}`, imprimir mensaje con el valor leído y los valores aceptados, exit code 1, **antes** de tocar la base de datos. [R2]
- [ ] 2.3 Implementar el bucle de los tres disparadores en orden `CHECKIN_WINDOW_OPENED` → `CHECKIN_TIME_REACHED` → `CHECKOUT_TIME_REACHED`, cada uno con su propia sesión marcada por `bind_session_to_tenant`, su propia `UnitOfWork` (`SqlAlchemyUnitOfWork(session)`) y su propio `commit`, replicando el wiring de `scheduler/tasks.py::_advance` (con `provisioner=ProvisionCleaningTaskUseCase(...)` sólo para `CHECKOUT_TIME_REACHED`, copiando `seed_demo._advance_states:1615-1628` literal). Comentario al inicio de la función que apunte a la fuente. [R1, R3]
- [ ] 2.4 Formato de salida de D4: una línea por job con `tenant=<uuid> trigger=<value> candidates=<n> transitioned=<n> blocked=<n> ambiguous=<n> unresolvable_time=<n> transitioned_without_task=<n>`; añadir `not_eligible=<n>` cuando el caso de uso lo emita. Exit codes de D4 (0 todos bien, 1 todos fallaron, 2 alguno pero no todos). Capturar excepciones por job con `logger.exception("sim_advance.job_failed", extra={"task": ..., "tenant_id": str(...)})`. [R1]

## 3. Tests del CLI — los cuatro escenarios de R4

- [ ] 3.1 Test R4.1 en `backend/tests/test_sim_advance_cli.py`: crear una reserva `CONFIRMED` con `check_in_date` hoy y `check_out_date` hoy+2 en `Europe/Madrid`; invocar el CLI con `--at` igual al instante del check-in + 1 min; verificar `property.current_operational_state == OCCUPIED_ESTIMATED` e informe `transitioned: 1`. [R4]
- [ ] 3.2 Test R4.2 en el mismo fichero: sobre la reserva ya `CHECKED_IN_ESTIMATED`, invocar CLI con `--at` igual al instante del check-out; verificar `AWAITING_CLEANING`, `transitioned: 1`, `transitioned_without_task: 0`; verificar que `reservation.check_in_date` y `reservation.check_out_date` no cambian. [R4]
- [ ] 3.3 Test R4.3 en el mismo fichero: invocar CLI con `--at` 3 horas antes del check-in; verificar que la vivienda **no** transiciona y el informe del primer job incluye `not_eligible: 1` (o el cubo equivalente que el caso de uso emita para «la hora aún no ha llegado»). [R4]
- [ ] 3.4 Test R4.4 en el mismo fichero: parchear `settings.environment` a `"staging"` con `monkeypatch.setattr`, invocar CLI; verificar exit code 1 y mensaje de guardia en stderr; verificar que **no** se ha creado ninguna fila de `property_state_transitions` ni de `TimelineEvent`. [R2, R4]

## 4. Makefile y `docker-compose.deploy.yml`

- [ ] 4.1 Añadir target `sim-advance` al `Makefile` raíz (junto a `bootstrap`, `seed-demo`, `demo-reset`, `openapi`) que invoque `$(COMPOSE) exec -T backend python -m app.cli.sim_advance --tenant $(TENANT)` y, si `$(AT)` está definido, `--at $(AT)`. Comentario de cabecera que diga: «sólo dev/local; no se publica en `docker-compose.deploy.yml`». [R5]
- [ ] 4.2 Verificar que `docker-compose.deploy.yml` NO contiene ningún target, servicio, ni entrypoint que invoque `app.cli.sim_advance` (grep cruzado contra el nombre del módulo). Si lo contiene, eliminarlo y documentar en `Implementation Notes`. Si no, escribir `Implementation Notes` que diga «verificado, no estaba». [R2, R5]

## 5. Documentación

- [ ] 5.1 Añadir a `docs/celery-jobs.md` una sección «Avanzar el reloj a mano en dev» con un ejemplo real (`make sim-advance TENANT=<uuid>` y `make sim-advance TENANT=<uuid> AT=<iso>`), las dos trampas de ventana (30 días atrás / 2 adelante, y «hoy en la zona de la vivienda»), y la nota de dev/local. [R5]
- [ ] 5.2 Corregir el conteo «Los nueve jobs» de `docs/celery-jobs.md:7` por la cifra vigente al cierre del archivo (medir contra `scheduler/tasks.py` y `scheduler/schedule.py`; el número actual es **doce** jobs: los cuatro de PRD §8.3, los cuatro de los changes que llegaron después, el mensual `generate_owner_statements`, `process_webhook_events` y `classify_incidents`). Si la cifra ha cambiado al ejecutar la tarea, ajustar el encabezado de la tabla. [R5]
- [ ] 5.3 Sustituir el bloque heredoc de `infra/environments/dev/RUNBOOK-seed-demo.md:316-322` por la invocación a `make sim-advance` con `TENANT` adecuado y el `AT` justo. Mantener el resto de §5 (segunda limpiadora, `channel=DIRECT`, `PATCH` de fechas para estancia de un día). Añadir nota de que la receta original «corrompía fechas» y por qué `sim-advance` no lo hace. [R5]

## 6. Verification

<!-- Use the commands recorded in the consumer project's project.md; this
     template does not prescribe a language, framework, or test runner. -->
- [ ] 6.1 Suite backend pasa: `docker compose exec backend uv run pytest` (atajo del `Makefile`, ejecutado desde la raíz del repo con el stack levantado). Si el stack no está levantado: `docker compose run --rm backend uv run pytest`. [R4]
- [ ] 6.2 `make check-rule11-ownership` pasa: guardia de la regla 11 con la nueva copia de wiring del CLI, que sigue siendo una atribución a `AdvancePropertyStatesUseCase` y por tanto no añade columna. [R2]
- [ ] 6.3 Typecheck del backend: desde `backend`, `uv sync --frozen && uv run pyright .`. Cualquier finding se reporta en `Implementation Notes`, no en este checklist. [R4]
- [ ] 6.4 Manual: ejecutar `make sim-advance TENANT=<uuid>` contra el stack local con la reserva sembrada por `make seed-demo`, verificar que la vivienda `REDES11` (en `AWAITING_CHECKIN` tras el seed) avanza a `OCCUPIED_ESTIMATED` con `transitioned: 1`. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
