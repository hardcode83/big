# Design: sim-advance

## Context

Los tres jobs de reloj (`check_checkin_windows`, `mark_occupied_estimated`,
`process_checkouts`) sólo se ejecutan desde `beat` con su `now = datetime.now(UTC)`
(`backend/app/scheduler/runner.py:176` y `backend/app/scheduler/tasks.py:494`). El caso de
uso que aplican (`AdvancePropertyStatesUseCase`,
`backend/app/properties/application/use_cases.py:122-195`) ya recibe `now` como parámetro, y
`seed_demo._advance_states` (`backend/app/cli/seed_demo.py:1600-1638`) ya lo invoca con
instrucciones históricas. Lo que falta es un punto de entrada para un operador que quiera
avanzar el reloj **sin** esperar a `beat` y **sin** corromper las fechas de la reserva — que
es exactamente lo que hace hoy el heredoc de `RUNBOOK-seed-demo.md` §5:316-322 con un
`docker compose exec … python - <<'JOBS' … JOBS`.

`Settings` (`backend/app/core/config.py:20`) **no** tiene hoy un campo que distinga dev/local de
deploy; los demás CLIs (`bootstrap`, `seed_demo`, `demo_reset`) viven en la misma incertidumbre
y se defienden por el nombre del tenant o por la presencia de las variables de bootstrap. La
guardia de R2 necesita un valor canónico que leer — eso es una decisión, y se llama D1.

`AdvancePropertyStatesUseCase` ya devuelve un `AdvanceReport` con los cinco cubos del
proposal (`properties/application/use_cases.py:149`); el wiring del provisioner de limpieza
para `CHECKOUT_TIME_REACHED` ya está aislado en `_advance` (`scheduler/tasks.py:143-157`) y
`seed_demo._advance_states` (`seed_demo.py:1615-1628`). Lo nuevo es la **función `main`**,
el **argumento `--at`**, la **guardia de entorno** y la **presentación línea-por-job**.

## Decisions

### D1 — Añadir `settings.environment` como `Literal["local", "dev", "staging", "production"]`, default `"local"`

**Chosen**: extender `Settings` con un campo `environment: Literal["local", "dev", "staging", "production"] = "local"`,
leído de la variable `APP_ENVIRONMENT` (con guión bajo conservado al estilo del resto de la
tabla de `Settings`). El default `local` significa que **un dev que olvide declararla sigue
obteniendo el comportamiento seguro**: el comando corre. En el `.env.example` se documenta con
un comentario que dice «en deploy se debe poner a `production` o `staging`». El guard del
comando acepta **sólo** `local` o `dev`; el resto levanta `SimAdvanceEnvironmentError` antes
de tocar nada. La validación se hace con `Literal[...]` en el `Settings` (Pydantic rechaza
cualquier valor fuera de la enumeración al instanciar), por lo que el guard es comparación
directa sobre `settings.environment in {"local", "dev"}`.

**Por qué**: la propuesta R2.4 dice «no introducir variable nueva si la Settings ya distingue».
`Settings` no distingue hoy; el heredoc de RUNBOOK §5 sí lo hace implícitamente (sólo
funciona porque el `.env` de dev lleva `BOOTSTRAP_TENANT_NAME`, que el deploy no
necesariamente lleva), pero eso es por accidente, no por diseño. Una variable explícita es
la única forma de que un comando ejecutado por error en deploy falle ruidosamente en
lugar de avanzar un reloj que el principio 1 de `steering/product.md` declara como verdad
auditable. El default `local` mantiene la regla de oro de la regla 8 de `steering/security.md`
(«el secreto que falla rápido debe hacerlo por el mecanismo que le corresponde a su forma de
uso»): la vía por la que falla es una comparación contra `settings.environment`, no un
`${VAR:?...}` en el compose.

Rejected: (a) Usar `BOOTSTRAP_TENANT_NAME` como proxy de dev — su ausencia en deploy es
circunstancial y cualquier día cambia, así que la guardia no puede depender de eso. (b) Usar
`settings.app_name` o el nombre del bucket de storage — irrelevantes y opacos. (c) Detectar
por `os.uname().nodename` o por la presencia de `/proc/1/cgroup` — imposible de testear y
opaco en el flujo de ejecución.

### D2 — Reutilizar `run_in_marked_session` con `now` congelado, sin levantar `run_for_every_tenant`

**Chosen**: el comando importa `run_in_marked_session` y `_advance` directamente desde
`app.scheduler.tasks` (lo segundo sólo como wiring, no para registrar `@celery_app.task`),
abre una sesión marcada por el `tenant_id` del argumento, y ejecuta los tres
`AdvancePropertyStatesUseCase.execute(tenant_id=…, trigger=…, now=at)` **en serie, cada uno
con su propia sesión y su propio commit**. La razón de NO usar `run_for_every_tenant`:
acepta un único callable y aplica `run_sync` (`asyncio.run`) por encima — eso no encaja con
«una sesión por job, tres commits, un mismo `now`». El comando abre las tres sesiones
manualmente y las cierra al terminar, replicando la disciplina del runner
(`runner.py:151-166`): una sesión marcada por tenant, `bind_session_to_tenant` por sesión,
rollback si la excepción sube, traza con `logger.exception` y `task=<nombre>`, `tenant_id`.

**Por qué**: la asimetría «mismo `now`, tres commits» es lo que la propuesta R1.4 exige, y
no se puede conseguir limpiamente reusando un helper pensado para un único commit por
ejecución. Importar `_advance` desde `scheduler/tasks.py` arrastra Celery por el grafo de
imports (es lo que `seed_demo._advance_states` evita copiando el wiring); lo hacemos copiando
ese wiring, igual que `_advance_states`, **pero** la copia va a `app/cli/sim_advance.py`
encabezada por un comentario que dice exactamente «copied from scheduler/tasks.py:143-157»,
de modo que el próximo que mire los dos sitios sepa que es deliberado.

Rejected: (a) Refactorizar `_advance` en un helper compartido `domain/clock_runner.py` —
es trabajo de un change posterior; no es lo que el proposal pide y abre una costura sin
ganancia observable. (b) Usar `run_for_every_tenant` con un `work` que ejecute los tres
disparadores dentro — viola la regla de «transacciones separadas» y pierde el informe
separado por job que R1.7 exige.

### D3 — `now` siempre UTC, interpretación de zona en la propiedad (sin cambio de invariante)

**Chosen**: el `--at` se parsea con `datetime.fromisoformat` y se exige `tzinfo=UTC`. Si el
operador pasa un instante naive, el comando rechaza con error legible. Si no se pasa, el
comando hace `datetime.now(UTC)` **una sola vez** al inicio, lo pasa por valor a los tres
jobs y lo imprime como `now = <iso>` en la primera línea. La interpretación de la zona de
la propiedad es la de `PropertyOperationalState` y `opens_checkin_window`
(`properties/domain/clock_triggers.py:94-122`), invariante del proyecto, **no se toca**.

**Por qué**: la propuesta R1.4 exige un único instante para los tres jobs; la regla 8 de
`steering/security.md` (timezone handling) ya nombra UTC como la zona del runner
(`runner.py:30`). Mezclar naive y aware aquí abre un bug en el filo del DST exactamente
cuando un operador está depurando el reloj — peor que el bug que estamos cerrando.

Rejected: (a) Aceptar naive y asumir UTC — abre el filo DST silenciosamente. (b) Aceptar la
zona del tenant y aplicar — son tres `now` distintos en tres zonas distintas según la
propiedad; ya lo hace la lógica interna, hacerlo fuera duplica.

### D4 — Informe por línea, una por job, en el orden de R1.2

**Chosen**: tras cada `await use_case.execute(…)`, el comando imprime **una sola línea**
con el formato fijo:

```
sim-advance: tenant=<uuid> trigger=<trigger.value> candidates=<n> transitioned=<n> blocked=<n> ambiguous=<n> unresolvable_time=<n> transitioned_without_task=<n>
```

Cuando el informe trae `not_eligible` (no es un cubo de `AdvanceReport` actual; lo añade el
contador interno del caso de uso para `CHECKIN_WINDOW_OPENED` con la ventana del operador),
se añade como campo extra. Sin campo `not_eligible`, la línea lo omite — la forma del
informe crece con cada `trigger`, no se fija en esta entrada. Si un job lanza excepción,
se imprime `sim-advance: <trigger.value> FAILED: <class>: <msg>` y el comando continúa con
el siguiente; el código de salida es 1 si los tres fallaron, 2 si falló alguno pero no
todos, 0 en otro caso. Los nombres de las claves coinciden con los atributos del dataclass
`AdvanceReport` (`properties/application/use_cases.py`, import indirecto vía el caso de
uso) para que un futuro cambio que añada un cubo obligue a actualizar este formato a la
vez.

**Por qué**: el RUNBOOK §5 ya imprime `transitioned`, `transitioned_without_task` y
`not_eligible` ad-hoc desde el shell del operador; el output del comando tiene que poder
sustituir esa lectura sin que el operador pierda información. Y el «2 si falló alguno pero
no todos» distingue el caso «el reloj funcionó pero la BD se cayó en el checkout» (no es
un éxito total, pero tampoco un fallo del operador) del «los tres fallaron, hay un problema
de fondo» (sí lo es).

Rejected: (a) Imprimir JSON — peor de leer en terminal, mejor para `jq` pero el RUNBOOK no
lo pide. (b) Un único informe agregado al final — pierde la atribución por job y obliga al
operador a correr tres veces si uno falla. (c) Exit code 1 ante cualquier fallo — confunde
«el reloj corrió y dos tercios avanzaron» con «nada funcionó».

### D5 — Guardia de entorno: `Literal` en `Settings` + check al inicio de `main`

**Chosen**: el campo `environment` de D1 es `Literal["local", "dev", "staging", "production"]`
con default `"local"`. Pydantic rechaza cualquier valor fuera de la enumeración al
instanciar `Settings`, lo que cierra la guardia por construcción para typos y valores
arbitrarios. La guardia **del comando** vive en el cuerpo de `main()`, **antes** de tocar
la base de datos:

```python
if settings.environment not in {"local", "dev"}:
    print(f"sim-advance: refusing to run in environment={settings.environment!r}; "
          f"allowed values: local, dev.", file=sys.stderr)
    return 1
```

El test de R4.4 verifica este path con un `Settings` parcheado a `staging` (vía
`monkeypatch.setattr(settings, "environment", "staging")`, que es lo que el resto de la
suite ya hace con `bootstrap_tenant_name`). No se introduce ninguna variable de entorno
nueva sólo para esto: es la misma `APP_ENVIRONMENT`, leída por el resto del backend
cuando lo necesite, sin obligar a nadie.

**Por qué**: el principio 1 de `steering/product.md` exige un timeline auditable, y un
reloj inyectable en deploy falsifica ese timeline. Una guardia al inicio, antes de la BD,
es la única forma de que un error en deploy no produzca mutaciones difíciles de revertir.
La Literal en `Settings` cierra por construcción la posibilidad de un valor vacío, typo o
arbitrario; la comparación en `main()` cierra por política la posibilidad de ejecutar en
`staging`/`production`. Las dos son necesarias: la primera porque sin ella un typo pasa
silencioso, la segunda porque un valor válido en `Literal` puede no serlo para este
comando.

Rejected: (a) Hacer la guardia en `app/main.py` o en una fixture global — acopla el resto
del backend a un comando que no se va a usar en deploy. (b) Hacerla en
`bootstrap.apply_plan` o similar — confunde «este tenant no es demo» con «este comando no
debe correr aquí». (c) Usar `os.getenv("APP_ENVIRONMENT")` directamente — fuera del sistema
de `Settings`, no se puede testear con monkeypatch y rompe el patrón del proyecto.

### D6 — `--at` se propaga al `now` del caso de uso; `created_at` y auditoría siguen del reloj de BD

**Chosen**: el comando pasa `at` como `now` a cada `AdvancePropertyStatesUseCase.execute`,
**sin tocar** nada más. `TimelineEvent.occurred_at` y `property_state_transitions.metadata`
salen del `now` del caso de uso (verificado: el caso de uso construye el
`PropertyStateChangeRequest` con `reference_instant=now` y eso cae en `occurred_at` del
evento, `use_cases.py:399-411`). Los `created_at`/`updated_at` de filas pre-existentes son
del reloj de BD — **no** se tocan — porque ningún caso de uso los escribe. El test R4.3
verifica la asimetría: el `TimelineEvent` escrito lleva `occurred_at == at` y la reserva
original conserva sus `created_at`.

**Por qué**: la propuesta R3.3 ya advertía de la asimetría; el seed la acepta. Cambiarla
aquí introduce una invariante nueva que `seed_demo` no respeta, y rompería la consistencia
entre los dos llamantes del mismo caso de uso. Es justo lo que la propuesta dice NO hacer.

Rejected: (a) Pasar `--at` también a `created_at` — introduce un atributo que ningún caso
de uso acepta, fuera del contrato. (b) Reescribir `occurred_at` después del commit — es
una edición retroactiva del timeline, prohibida por la decisión firme de
`steering/architecture.md` («Timeline inmutable»).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Settings | `backend/app/core/config.py` | Añadir `environment: Literal["local","dev","staging","production"] = "local"` (D1). |
| Settings doc | `backend/.env.example` | Añadir `APP_ENVIRONMENT` con comentario sobre cuándo poner `production`. |
| CLI | `backend/app/cli/sim_advance.py` (nuevo) | `main()` con `--tenant`, `--at`, guardia de D5, bucle de D2/D3, formato de D4, exit codes de D4. |
| Makefile | `Makefile` | Añadir target `sim-advance` que invoca `python -m app.cli.sim_advance` con `TENANT` y `AT` opcionales (R5.1). |
| Deploy | `docker-compose.deploy.yml` | Declara `APP_ENVIRONMENT` como variable **obligatoria** (`${APP_ENVIRONMENT:?...}`) en `backend`/`worker`/`beat` **y `migrate`** (los cuatro servicios que comparten la imagen de producción): es lo que arma la guardia de D5 en todo entorno desplegado, presente y futuro (ver Riesgo **R5**). El comando en sí no llega al deploy: la guardia de D5 + la ausencia del target `sim-advance` en el Makefile del contenedor siguen cubriendo R2.3. |
| Docs | `docs/celery-jobs.md` | Sustituir la frase de «nueve jobs» por la cifra vigente al archivar; añadir sección «Avanzar el reloj a mano en dev» con un ejemplo real y las dos trampas de ventana (R5.2/3). |
| RUNBOOK | `infra/environments/dev/RUNBOOK-seed-demo.md` §5 | Sustituir el heredoc de `:316-322` por `make sim-advance TENANT=…` (R5.4). |
| Tests | `backend/tests/test_sim_advance_cli.py` (nuevo) | R4.1-R4.4: tres tests de escenario + uno de la guardia. |

## Data & interfaces

**Schema changes**: ninguno.

**API contracts**: ninguno (es CLI, no HTTP).

**Events**: el caso de uso ya escribe `PROPERTY_STATE_CHANGED` con `occurred_at = now` —
no se introduce un evento nuevo.

**Config / env vars**: una variable nueva, `APP_ENVIRONMENT`, leída por `Settings.environment`
(D1). Aparece en `.env.example` con sufijo de comentario; su default en código es `"local"`.

## Risks & mitigations

- **R1 — Drift entre el wiring de `scheduler/tasks.py::_advance` y la copia en `cli/sim_advance.py`.**
  Mitigación: la copia se encabeza con un comentario que apunta a la fuente y alinea los
  nombres de los colaboradores uno a uno. El test de R4.1-2 ejercita el caso de éxito, que
  es donde el drift se manifiesta (un campo nuevo en el caso de uso o un colaborador renombrado
  reventaría el test). Si en el futuro los dos divergen, el panel de revisión del run lo
  cazará.

- **R2 — Un `Settings.environment` añadido y nunca usado por el resto del backend se lee como
  «variable muerta» y alguien la borra en una limpieza.** Mitigación: el campo aparece en
  `Settings` con un docstring que nombra al menos dos consumidores futuros plausibles (la
  propia guardia de D5, y el logging de tareas de larga duración que ya se menciona en la
  propuesta de `audit-log-driver`). Si ningún change posterior lo usa, la siguiente entrada
  que necesite un guard de entorno lo levantará — y un campo no usado es preferible a un
  guard implícito.

- **R3 — El test de R4.4 monkeypatcha `settings.environment` directamente; si en el futuro
  el resto de la suite cambia a un fixture, este test se queda atrás.** Mitigación: el test
  importa `settings` de `app.core.config` igual que el resto de la suite (verificado: el
  patrón ya está en `tests/test_bootstrap.py` para `bootstrap_tenant_name`), así que un
  cambio de fixture le afectaría igual que al resto — no introduce una dependencia propia.

- **R4 — `seed_demo._advance_states` y `cli/sim_advance.py` duplican la construcción del caso
  de uso.** Aceptado: la duplicación está acotada al wiring, no a la lógica (los dos llaman
  al mismo `AdvancePropertyStatesUseCase`). Refactorizarla es trabajo de un change
  posterior; este se limita a abrir la segunda puerta y dejar la nota de D2.

- **R5 — Un futuro `deploy-staging.yml`/`deploy-prod.yml` podría olvidar fijar
  `APP_ENVIRONMENT`, dejando que el guard evalúe el default permisivo de `Settings`
  (`"local"`) en un entorno real.** Mitigación: `docker-compose.deploy.yml` declara
  `APP_ENVIRONMENT` como variable **obligatoria** (`:?`) en **los cuatro servicios que
  comparten la imagen de producción** — `backend`/`worker`/`beat` y también `migrate`
  (decisión registrada en `BLOCKED.md` tras el hallazgo de la tercera pasada del panel de
  revisión: `migrate` corre la misma imagen y un `docker compose -f
  docker-compose.deploy.yml run migrate python -m app.cli.sim_advance ...` contra un
  despliegue real habría visto el default permisivo sin este requisito, aun sin ser el
  camino previsto para invocar el comando) — el mismo fichero de compose que cualquier
  entorno futuro reutilizará (steering/infra.md, módulos Terraform por entorno) — así que
  un pipeline que no la fije no despliega silenciosamente en modo permisivo: el contenedor
  se niega a arrancar. El riesgo residual queda acotado a que ese futuro pipeline recuerde
  poner el valor correcto (`staging`, `production`, fuera de `{local, dev}`) en su propio
  paso de render, siguiendo el patrón que `deploy-dev.yml` ya establece con el literal
  `dev`.

## Open questions

Ninguna. Las decisiones D1-D6 son las que el design skill dice resolver con recomendación y
materializar como D#; todas respetan el proposal y la steering, y cada `Rejected:` nombra la
alternativa. `D1` introduce la variable que R2.4 sólo prohibía si `Settings` ya distinguía —
`Settings` no distingue hoy, así que la prohibición cae por su前提. Lo registro como
`assumed` en el BLOCKED para que quede a la vista del revisor en el PR, y el veto humano
sigue siendo posible.
