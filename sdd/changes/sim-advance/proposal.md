# Proposal: sim-advance

## Why

El MVP operable (auditoría 2026-09-04) tiene un **callejón sin salida al alcance de la UI**:
una estancia de dos noches tarda dos días en recorrerse por la herramienta, porque
`check_checkin_windows`, `mark_occupied_estimated` y `process_checkouts` sólo se ejecutan
desde `beat`, y `beat` no se puede acelerar. La receta vigente
(`infra/environments/dev/RUNBOOK-seed-demo.md` §5, `docker compose exec … <<'JOBS' … JOBS`)
parchea la reserva un día hacia atrás, la pone en `CONFIRMED` y lanza los tres jobs — **funciona
pero corrompe el dato**: las fechas de la reserva dejan de ser las que el manager escribió y el
timeline dice que el check-in ocurrió un día antes del de la estancia. Con
`reservation-create-web` y `property-detail` delante, esa receta se convierte en la forma
normal de probar, y no debe.

La primitiva que falta ya existe: `AdvancePropertyStatesUseCase` recibe `now` como parámetro
(`backend/app/properties/application/use_cases.py:122-195`) y `seed_demo._advance_states`
(`backend/app/cli/seed_demo.py:1600-1638`) ya la ejecuta con `now` histórico. Lo que falta es
un punto de entrada para un operador que quiera avanzar el reloj **sin** mover fechas de la
reserva.

Fuente: `sdd/roadmap/sim-advance.md` (hito «MVP operable» 1). Principio 1 de
`sdd/steering/product.md`: una vivienda es una máquina de estados — pero eso no significa que
podamos inyectar reloj en producción.

## What changes

Existirá un comando CLI `python -m app.cli.sim_advance` y un target de Makefile
`make sim-advance TENANT=<uuid> [AT=<instante ISO>]`, ambos **sólo en dev/local**, que ejecute
los tres jobs de reloj (`check_checkin_windows`, `mark_occupied_estimated`, `process_checkouts`)
en orden y en transacciones separadas, pasando el instante dado como `now`, e imprima el
informe de cada uno (`transitioned`, `blocked`, `ambiguous`, `unresolvable_time`,
`transitioned_without_task`). Sin `AT`, usa el `now` real: entonces es «no esperes a beat», que
es lo que RUNBOOK §5 ya hace — pero sin el heredoc y sin corromper fechas.

Y la documentación de `docs/celery-jobs.md`, que dice «nueve jobs» y va por doce, deja de
mentir. La sección §5 de `RUNBOOK-seed-demo.md` deja de pedir el heredoc de tres llamadas y
pasa a pedir `make sim-advance`.

## Requirements

### R1 — Comando CLI que avanza el reloj de un tenant

**As a** operador de `dev` o `local`, **quiero** un comando que ejecute los tres jobs de reloj
sobre un tenant en orden y con un instante dado, **para que** una estancia de dos noches se
pueda recorrer desde el navegador sin esperar a `beat` y sin corromper las fechas de la
reserva.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer el comando como `python -m app.cli.sim_advance` (el patrón de
   `bootstrap`, `seed_demo`, `demo_reset`, `openapi`; nunca `uv run` —
   `Makefile:257-260` lo fija para que funcione igual contra la imagen de producción).
2. WHEN se invoca con `--tenant <uuid>` y `--at <instante ISO>` opcionales, THE SYSTEM SHALL
   ejecutar en este orden: `check_checkin_windows` (`PropertyStateTrigger.CHECKIN_WINDOW_OPENED`),
   `mark_occupied_estimated` (`CHECKIN_TIME_REACHED`) y `process_checkouts`
   (`CHECKOUT_TIME_REACHED`), cada uno en su propia transacción y usando el mismo `now`.
3. WHEN no se indica `--at`, THE SYSTEM SHALL usar `datetime.now(UTC)` — el `now` por defecto
   del runner (`backend/app/scheduler/runner.py:176`) — y SHALL imprimir al menos una línea
   diciendo que se ha usado el `now` real.
4. THE SYSTEM SHALL resolver el `now` como un único instante al inicio del comando, pasado por
   valor a los tres jobs: **no** SHALL releer `datetime.now(UTC)` entre jobs, para que un
   comando con `--at` tenga un reloj consistente en las tres ejecuciones.
5. WHEN un tenant no existe o `--tenant` no es un UUID válido, THE SYSTEM SHALL imprimir un
   error legible y devolver código de salida no-cero, sin haber ejecutado ningún job.
6. WHEN un job falla, THE SYSTEM SHALL registrar la traza por `logger.exception` con el
   `tenant_id` y el nombre del job, imprimir el fallo, continuar con el siguiente, y devolver
   código de salida no-cero sólo si **todos** los jobs fallaron; si al menos uno tuvo éxito
   entre los tres, devolver cero y dejar la lista de fallos al final.
7. WHEN un job termina, THE SYSTEM SHALL imprimir su informe (`AdvanceReport`) como una
   línea-resumen con `tenant_id`, `trigger`, `candidates`, `transitioned`, `blocked`,
   `ambiguous`, `unresolvable_time`, `transitioned_without_task` y, cuando exista, el
   `not_eligible`. La forma concreta se define en el design, pero SHALL ser una línea por job,
   en el orden de R1.2.
8. THE SYSTEM SHALL imprimir `--help` con la trampa de las ventanas: `--at` 30 días atrás /
   2 adelante (`clock_triggers.py:42,52,55`) y «hoy en la zona de la vivienda»
   (`clock_triggers.py:94-122`) — sin eso, un operador que pase el día equivocado recibe
   silenciosamente `candidates: 0`.

### R2 — Guard de entorno: dev/local únicamente

**As a** mantenedor de la postura auditable, **quiero** que este comando no se pueda ejecutar
contra un entorno desplegado, **para que** un reloj inyectable no falsifique el timeline que
el principio 1 de `steering/product.md` declara como verdad.

Criterios de aceptación:

1. WHEN el comando arranca, THE SYSTEM SHALL leer `Settings.environment` (o el campo que la
   `Settings` ya use para distinguir dev/local de deploy) y SHALL negarse a ejecutarse si
   está en un valor distinto del conjunto declarado como dev/local.
2. THE SYSTEM SHALL negarse con un mensaje que diga literalmente el valor leído y los valores
   aceptados, y SHALL devolver código de salida no-cero antes de ejecutar cualquier job.
3. THE SYSTEM SHALL aparecer **sólo** en el `Makefile` local y en `docker-compose.yml`; SHALL
   **no** estar declarado en `docker-compose.deploy.yml`. El design describe cómo se prueba
   en rojo la ausencia.
4. THE SYSTEM SHALL **no** introducir una variable de entorno nueva sólo para esta guardia si
   la `Settings` ya distingue los entornos; el valor que ya existe es la palanca.

### R3 — Idempotencia frente a `beat` y consistencia de `now` con el dato creado

**As a** operador, **quiero** que correr este comando no rompa el ciclo normal de `beat`, **para
que** pueda usarlo como atajo sin temer pisar el scheduler.

Criterios de aceptación:

1. WHEN `beat` corre después de un `sim-advance` con `--at` futuro o presente, THE SYSTEM SHALL
   no repetir la transición que `sim-advance` aplicó: la prueba viva es `property_state_transitions`
   con `trigger` y `reservation_id` en `metadata`, que `applied_clock_triggers`
   (`properties/domain/repositories.py`) lee como texto.
2. WHEN `--at` cae en el pasado de una transición ya aplicada, THE SYSTEM SHALL contarlo como
   `not_eligible` (no como `blocked`, ni como un error): el reloj no retrocede transiciones,
   pero el informe tiene que decirlo para que el operador no crea que el job no corrió.
3. WHERE `TimelineEvent.occurred_at` o `property_state_transitions.created_at` salen del
   `now` del caso de uso, THE SYSTEM SHALL pasarles el `--at` para que el timeline sea
   coherente con el reloj que el operador nombró; WHERE salen del reloj de BD, THE SYSTEM
   SHALL **no** tocarlos. El design declara qué rama aplica — el seed ya vive con esa
   asimetría y la acepta — y los tests del change la verifican contra una fila escrita.
4. THE SYSTEM SHALL **no** mover `created_at`, `updated_at`, ni ninguna fila de auditoría de
   un objeto existente; sólo las filas que el caso de uso escribe en su única transacción.

### R4 — Verificación de extremo a extremo

**As a** revisor del PR, **quiero** un test que recorra los tres saltos con un solo comando,
**para que** el caso de éxito y los casos de «no es tu ventana» queden certificados a la vez
que el cableado del CLI.

Criterios de aceptación:

1. THE SYSTEM SHALL incluir un test que cree una reserva `CONFIRMED` con `check_in_date` =
   hoy, `check_out_date` = hoy + 2 (en la zona del tenant, `Europe/Madrid`), y que tras
   invocar el CLI con `--at` igual al instante del check-in (más un minuto, para abrir
   ventana), la vivienda pase a `OCCUPIED_ESTIMATED` con `transitioned: 1`.
2. THE SYSTEM SHALL incluir un test que, sobre la misma reserva ya `CHECKED_IN_ESTIMATED`,
   invoque el CLI con `--at` igual al instante del check-out, y la vivienda pase a
   `AWAITING_CLEANING` con `transitioned: 1` y `transitioned_without_task: 0` (con
   `auto_create_cleaning_task` por defecto). La reserva conserva sus fechas originales: ni
   `check_in_date` ni `check_out_date` se mueven.
3. THE SYSTEM SHALL incluir un test que invoque el CLI con `--at` tres horas antes del
   check-in: la vivienda permanece en su estado anterior y el informe dice `not_eligible: 1`
   (o el cubo que el design decida para «la hora aún no ha llegado»).
4. THE SYSTEM SHALL incluir un test que invoque el CLI con `environment = "staging"`
   (o el valor de deploy que la `Settings` ya use) y SHALL recibir código de salida no-cero
   por la guardia de R2, **sin** que se haya ejecutado ningún job.

### R5 — `make sim-advance` y documentación

**As a** operador, **quiero** un target de `Makefile` y una página de docs que digan cómo
usar el comando, **para que** el heredoc de RUNBOOK §5 deje de ser el camino normal.

Criterios de aceptación:

1. THE SYSTEM SHALL añadir al `Makefile` un target `sim-advance` que invoque
   `$(COMPOSE) exec -T backend python -m app.cli.sim_advance --tenant $(TENANT)` con `$(AT)`
   pasado como `--at` cuando esté definido. El target NO se publica en `docker-compose.deploy.yml`.
2. THE SYSTEM SHALL documentar el comando en `docs/celery-jobs.md` con un ejemplo real, las dos
   trampas de la ventana (R1.8) y la nota de que el comando es dev/local y **no** debe usarse
   contra deploy.
3. WHEN esta entrada se archive, THE SYSTEM SHALL corregir el conteo «Los nueve jobs» de
   `docs/celery-jobs.md` al número vigente en ese momento, si ha quedado desfasado.
4. THE SYSTEM SHALL sustituir el heredoc de RUNBOOK-seed-demo §5 por una llamada a
   `make sim-advance` con los argumentos correspondientes, manteniendo la nota de que el
   resto de §5 (segunda limpiadora, `channel=DIRECT`, `PATCH` de fechas si la estancia es de
   un día, etc.) sigue aplicando.

## Out of scope

- Mover `beat`, cambiar cadencias, o modificar `scheduler/tasks.py` o `scheduler/schedule.py`.
  El comando reusa los mismos `AdvancePropertyStatesUseCase`, `run_for_every_tenant` y
  `run_in_marked_session` que ya existen; lo que cambia es **cómo se les invoca**.
- Fingir el reloj para `dispatch_notifications`, `check_sla_breaches`, `provision_access_records`,
  `process_webhook_events`, `classify_incidents`, `generate_price_recommendations` o
  `generate_owner_statements`. Cada uno tiene su propia semántica de tiempo (SLA, hora del
  día, cola, plazo legal de acceso); entrarían por cambios separados si alguien los necesita.
- Cualquier ruta HTTP, CLI de FastAPI, o endpoint. El comando es un sub-comando de
  `python -m`, no un router.
- Reintroducir la receta del heredoc como atajo «alternativo» en RUNBOOK-seed-demo §5.
  §5 sigue valiendo para los cuatro pasos previos al lanzamiento de los jobs, pero los
  tres `python -m` desaparecen.
- Crear una variable de entorno nueva para «dev/local» si la `Settings` ya distingue
  entornos. Si no la distingue hoy, ese hueco es un cambio separado y se declara en
  BLOCKED.

## Affected specs

- `sdd/specs/celery-jobs.md` — sin cambio normativo (los tres jobs no cambian); se anotará
  al archivar que el comando `sim-advance` es un llamante **adicional** del mismo caso de
  uso, sumándose a `seed_demo._advance_states` y `beat`/`tasks.py`.
- `sdd/specs/local-environment.md` — la nota sobre cómo arrancar un comando de
  `python -m app.cli.*` se reescribirá para incluir `sim_advance` (corre contra el backend
  ya levantado, igual que los otros).
- `docs/celery-jobs.md` — la página operativa: añadir sección «Cómo avanzar el reloj a
  mano en dev» y corregir el conteo de jobs (R5.3).
- `infra/environments/dev/RUNBOOK-seed-demo.md` §5 — sustituir el heredoc de tres
  `python -m …` por `make sim-advance` (R5.4).
- `Makefile` — añadir el target `sim-advance` (R5.1).
- `docker-compose.yml` / `docker-compose.deploy.yml` — sólo la ausencia del target en
  `deploy` (R2.3); no se añade servicio nuevo.
