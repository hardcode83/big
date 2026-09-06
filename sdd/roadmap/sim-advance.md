# sim-advance

[TECH] **avanzar el reloj de los jobs de estado en dev sin tocar el calendario**:
`make sim-advance TENANT=<uuid> AT=<instante ISO>` ejecuta `check_checkin_windows`,
`mark_occupied_estimated` y `process_checkouts` síncronamente con un `now` sintético.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04). Sin esto una estancia de dos noches tarda dos días en recorrerse.

**El hecho medido (2026-09-04)**: no hay avance de reloj de ningún tipo. `now` es
`datetime.now(UTC)` en el runner (`backend/app/scheduler/runner.py:176`, `at = now or
datetime.now(UTC)`) y en el job de webhooks (`tasks.py:494`); no existe flag de CLI, variable de
entorno ni fixture que lo cambie. **La primitiva sí existe**: `AdvancePropertyStatesUseCase`
recibe `now` como parámetro (`properties/application/use_cases.py:388-410`, `_request_for`), y
`seed_demo._advance_the_clock` (`cli/seed_demo.py:856-1000`) la usa con **instantes históricos**
tomados de `effective_bounds` (:900-903) para rebobinar la historia de las tres estancias
sembradas sin escribir ningún estado a mano. Lo que no existe es un punto de entrada para un
operador.

**La receta vigente, y por qué no vale**: RUNBOOK-seed-demo §5 (`infra/environments/dev/RUNBOOK-seed-demo.md:276-333`)
crea la estancia para hoy→mañana, **parchea las fechas un día hacia atrás**, la pasa a
`CONFIRMED` y lanza los tres jobs con un heredoc de Python por `docker compose exec` (:311-322).
Funciona y está probado, pero **corrompe el dato**: la reserva acaba con fechas que no son las
que el manager escribió, y el timeline dice que el check-in ocurrió en una fecha que no es la de
la estancia. Con `reservation-create-web` delante, esa receta se convertiría en la forma normal
de probar, y no debe.

**Alcance**: un target de `make` que invoque un comando (`python -m app.cli.sim_advance`, el
patrón de `bootstrap`/`seed_demo`/`demo_reset`: `python -m`, nunca `uv run`, `Makefile:257-260`)
con dos argumentos —tenant e instante— y ejecute los tres jobs de reloj **en orden y en
transacciones separadas**, pasando el instante como `now`, e imprima el informe de cada uno
(`transitioned`, `blocked`, `ambiguous`, `unresolvable_time`, `transitioned_without_task`). Sin
`AT`, usa el `now` real: entonces es sólo «no esperes a beat», que es lo que RUNBOOK §5 ya hace.

**Lo que decide y no es cosmético**:

1. **Sólo dev/local.** Guardado por entorno (`ENVIRONMENT`/`APP_ENV`, lo que `Settings` ya use),
   y **nunca** montado en `docker-compose.deploy.yml`. Un reloj inyectable en producción es una
   forma de falsificar el timeline auditable (principio 1 de `steering/product.md`). El design
   dice cómo se prueba en rojo que la guardia existe.
2. **Un `now` sintético sólo para los jobs de reloj.** `created_at` de filas, notificaciones,
   auditoría y `occurred_at` de los eventos siguen con la hora que el runner ponga — hay que
   medir si `TimelineEvent.occurred_at` sale del `now` del caso de uso o del reloj de BD, y
   declararlo. El seed ya vive con esa asimetría y está aceptada.
3. **Idempotencia frente a `beat`.** `beat` sigue corriendo cada 5 min en dev; una transición
   aplicada con `now` sintético queda registrada por reserva (`applied_clock_triggers`), así que
   el `beat` real no la repite. Pero un `AT` en el pasado respecto a una transición ya aplicada
   es un no-op silencioso: el informe lo tiene que decir (`blocked`/`not_eligible`).
4. **`opens_checkin_window` exige que la fecha local de la estancia sea «hoy»**
   (`properties/domain/clock_triggers.py:94-122`), y «hoy» se deriva de `now` en la zona de la
   propiedad. Un `AT` a las 15:05 del día del check-in abre la ventana; uno a las 23:00 del día
   anterior no. Documentarlo en el `--help`, porque es la trampa más probable.
5. **Ventana de candidatos**: 30 días atrás, 2 adelante (`clock_triggers.py:42,52,55`). Un `AT`
   más de dos días por delante de las fechas de la reserva no la encuentra. Mismo aviso.
6. **Dónde vive**: `backend/app/cli/` con los demás comandos; el target en `Makefile`. La
   documentación va a `docs/celery-jobs.md` (que además está desfasada: dice nueve jobs y hay
   doce) y sustituye el heredoc de RUNBOOK-seed-demo §5.

**Fuera de alcance**: fingir el reloj para `dispatch_notifications`, `check_sla_breaches` o el
job de webhooks (tienen su propia semántica de tiempo); mover `beat`; cualquier ruta HTTP.

**Verificación**: crear una reserva pasado mañana desde `/reservations`, `sim-advance` al
check-in → `AWAITING_CHECKIN`/`OCCUPIED_ESTIMATED`, `sim-advance` al checkout →
`AWAITING_CLEANING` con `transitioned: 1 / transitioned_without_task: 0`, y la reserva conserva
sus fechas originales.
