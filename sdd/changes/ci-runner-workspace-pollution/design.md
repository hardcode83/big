# Design: ci-runner-workspace-pollution

## Context

`docker-compose.yml` (raíz) declara cuatro servicios que montan el árbol por bind mount
(`./backend:/app`): `migrate`, `backend`, `worker` y `beat`. Ninguno declara `user:`, así que el
proceso del contenedor es `root` y todo lo que escribe en `/app` aparece en el host con ese dueño.
`backend/devops/Dockerfile` declara `ENV UV_COMPILE_BYTECODE=1` en su etapa `base`, que afecta a lo
que `uv` compila **dentro del venv** (`/app/.venv`, un volumen con nombre) y no al árbol montado;
no hay ningún ajuste que gobierne el bytecode del código fuente. `backend/pyproject.toml` tiene sólo
`[project]` y `[dependency-groups]`: no existe configuración de `pytest`, así que su caché cae en el
rootdir por defecto (`backend/.pytest_cache`, dentro del bind mount).

En la VM `dev`, `infra/environments/dev/runner-bootstrap.sh` crea N agentes, cada uno con usuario
`actions-runner-<i>`, `RUNNER_HOME=/opt/actions-runner-<i>` y su `_work/` propio, todos en el grupo
`ci-agents` que `/etc/sudoers.d/91-actions-runner-pool` dota de `NOPASSWD:ALL`. El script llega a la
VM incrustado en `cloud-init.yaml.tftpl` mediante
`runner_bootstrap = file("${path.module}/runner-bootstrap.sh")` (`main.tf:171`), y el `metadata` de
la instancia es ForceNew con `ignore_changes`: **cloud-init no se re-ejecuta sobre la VM viva**, por
lo que el procedimiento real de aplicación es el de `RUNBOOK.md §6.2` (copiar el script y ejecutarlo
a mano, es idempotente).

## Decisions

### D1 — El hook devuelve la propiedad del `_work/`, no borra lo que encuentra

**Chosen:** el hook hace `chown -R` del `_work/` del agente a su propio usuario, dejando que
`actions/checkout` haga la limpieza que ya sabe hacer. Ataca la clase entera del problema —
*cualquier* fichero de otro dueño, no sólo el `__pycache__` que conocemos hoy — y no destruye nada:
cambia metadatos, no contenido, así que un error de alcance no pierde trabajo.

Rejected: borrar los directorios de caché conocidos (`__pycache__`, `.pytest_cache`) — es una lista
de nombres prohibidos, y el siguiente escritor de root que no esté en la lista reproduce el incidente
entero; además borra contenido, que es un daño mayor si el alcance falla.
Rejected: `git clean -ffdx` desde el hook — destruye ficheros no rastreados legítimos y no resuelve
el caso, porque tampoco puede borrar lo que no le pertenece.

### D2 — El hook no hace nada si no hay nada que hacer

**Chosen:** antes del `chown`, el hook busca el primer fichero cuyo dueño no sea el usuario del
agente (`find "$WORK" ! -user "$RUNNER_USER" -print -quit`) y termina en silencio si no hay ninguno.
El caso normal —el 100 % de los jobs en un pool sano— cuesta un recorrido de sólo lectura y ninguna
escritura, que es lo que pide R3.4.

Rejected: `chown -R` incondicional en cada job — reescribe metadatos de decenas de miles de ficheros
en cada arranque sin motivo, y hace indistinguible en el log un agente sano de uno contaminado.

### D3 — La declaración va en `$RUNNER_HOME/.env`, y obliga a reiniciar el agente

**Chosen:** `ACTIONS_RUNNER_HOOK_JOB_STARTED` se declara en `/opt/actions-runner-<i>/.env`, que es
el mecanismo que documenta GitHub para este hook (*«add them to a file named `.env` within the
self-hosted runner application directory»*). Lo escribe `runner-bootstrap.sh` por agente.

Verificado durante el diseño, porque la ruta no era evidente: ni
`src/Misc/layoutbin/runsvc.sh` (que sólo lee `.path`) ni la plantilla del unit
`actions.runner.service.template` (que no tiene `EnvironmentFile`) cargan ese fichero — lo lee el
propio proceso del runner. De ahí se sigue lo que la documentación dice explícitamente: **«any
change to the `.env` file will require restarting the runner»**, y por tanto D4.

Rejected: un drop-in de systemd con `Environment=` — funcionaría y sobrevive a `svc.sh install`,
pero pone la configuración del runner en dos sitios y se aparta del mecanismo documentado.
Rejected: exportar la variable en el entorno del sistema — alcance mucho mayor que el agente y sin
forma de acotarla por agente.

### D4 — El bootstrap reinicia el agente sólo si su `.env` cambió, y sólo si está ocioso

**Chosen:** tras escribir el `.env`, el bootstrap compara contra el contenido anterior; si cambió,
reinicia el servicio de ese agente. El reinicio se condiciona a que el agente no tenga un job en
vuelo, con la misma guardia de liveness que el script ya usa en la fase de baja.

Esto existe porque `start_named_agent()` hoy **no toca un servicio que ya está `active`** (su `case`
lo dice: *«ya activo: no tocar»*). Sin este cambio, re-ejecutar el bootstrap sobre la VM viva
instalaría el hook y el `.env` y **no surtiría efecto**, porque ningún runner los releería — el
fallo más probable de este change, y silencioso.

Rejected: reiniciar siempre — aborta jobs en vuelo en cada re-ejecución del bootstrap, que es un
procedimiento de operación normal.
Rejected: no reiniciar y documentar que el operador lo haga — convierte en manual justo el paso del
que depende que todo lo demás funcione.

**Enmienda 2026-09-15** (panel de `/sdd:review`, feature-scale, rounds 3-5: `sdd-security` ×2,
`sdd-qa`, `sdd-review-cicd`): la "guardia de liveness" de arriba resultó tener un fallo propio —
`gh_in_progress_url_for_runner`, la consulta a la API de GitHub que confirma si el agente tiene un
job en vuelo, fallaba **abierto**: un `|| true` sobre un rechazo de la API, una lista de runs (o de
jobs de un run) truncada por paginación, o un `html_url` ausente en la respuesta, todos colapsaban
al mismo "no hay job en vuelo" que el caso genuinamente ocioso — y el D4 original habría reiniciado
(`systemctl restart`) un agente con un job real en marcha ante cualquiera de esos fallos, matándolo
en silencio. Corregido para fallar **cerrado**: cualquier incertidumbre de la API (rechazo,
paginación truncada en cualquiera de las dos llamadas, un job encontrado sin `html_url`) hace que
el helper salga `!=0`, tratado como "no sé" y nunca como "confirmado ocioso". Como consecuencia,
`start_named_agent()` distingue ahora **dos** motivos de diferimiento con dos códigos de salida —
2 = job en vuelo CONFIRMADO por la API, 3 = la API no respondió (estado DESCONOCIDO) — y el bucle
de la Fase 2 los clasifica en dos arrays separados (`deferred_restart` / `deferred_restart_unknown`)
para que el resumen final le diga al operador qué investigar en cada caso (esperar al job vs.
revisar el token/la API), en vez del mismo mensaje "job en vuelo" para los dos. Ningún cambio de
alcance: sigue siendo el mismo "no reiniciar si no estamos seguros" de la decisión original, solo
que "seguros" ahora exige una confirmación positiva de la API, no la ausencia de una negativa.

### D5 — `PYTHONDONTWRITEBYTECODE` en el compose, no en el Dockerfile

**Chosen:** se declara en el `environment:` de los cuatro servicios de `docker-compose.yml`. El
problema es exclusivo del bind mount, que es una propiedad de la composición local y no de la
imagen.

Rejected: declararlo en `backend/devops/Dockerfile` — alcanzaría también a la etapa `prod`, donde no
hay bind mount y el bytecode precompilado es deseable (arranque más rápido); apagarlo ahí sería
pagar una regresión de arranque en el entorno desplegado para arreglar un problema que allí no
existe.

### D6 — La caché de `pytest` se configura en `pyproject.toml`

**Chosen:** se crea `[tool.pytest.ini_options]` en `backend/pyproject.toml` con `cache_dir`
apuntando fuera del árbol. Es configuración versionada, se aplica igual dentro del contenedor y en
cualquier otra forma de correr la suite, y no depende de que quien invoque recuerde una bandera.

Rejected: `PYTEST_ADDOPTS=-p no:cacheprovider` en el compose — apaga la caché en vez de reubicarla
(pierde `--lf`/`--ff`) y sólo aplica a quien herede esa variable.

### D7 — Aplicar en la VM viva es un paso manual, y así queda declarado

**Chosen:** el change entrega el código; la aplicación sobre la VM viva es la ejecución de
`RUNBOOK.md §6.2`, que se amplía con el paso nuevo. Se declara como tarea `<!-- manual -->` y viaja
como entrada `deferred` en `BLOCKED.md`, porque nadie puede ejecutarla desde aquí.

No hay alternativa disponible: `metadata` es ForceNew con `ignore_changes` (`main.tf`), de modo que
cambiar el `user_data` **no** re-ejecuta cloud-init sobre la instancia viva. Forzarlo recrearía la
VM, con pérdida de datos y ruleta de capacidad de OCI — explícitamente descartado por el comentario
del propio `main.tf`.

### D8 — Un guard de CI lee la composición resuelta, no una lista de servicios

**Chosen:** un check nuevo, en la línea de los que el repo ya tiene (`make check-compose-ports`,
`scripts/check-detect-surface.py`, `make check-rule11-ownership`), que lee la composición **resuelta**
y exige `PYTHONDONTWRITEBYTECODE` en todo servicio **Python** que monte el árbol del repositorio por
bind mount en escritura. Decidido con la usuaria; materializa R5.

**Enmendado el 2026-09-14, durante la implementación de la sección 2, antes de escribir el guard**:
la redacción original no llevaba el calificador «Python» (R1/R5 originales tampoco lo distinguían de
forma pareja) y, comprobado contra el modelo resuelto real, `frontend` también monta su árbol en
escritura (`./frontend:/app`, `read_only` ausente) — la habría metido en el guard para una variable
que en un contenedor Node no hace nada, y habría exigido reabrir la sección 1, ya con panel PASS.
Verificado con la usuaria (ver Open questions original de esta fase); R1.1 sí llevaba el calificador
Python desde el principio, y esta enmienda solo iguala R5 con él.

Lo que lo hace un guard y no un adorno es **qué lee**: la forma que se sortea sola es comprobar los
cuatro nombres de hoy, porque un quinto servicio Python con bind mount no la dispara. La señal
estructural para «es un servicio Python» es el `build.context` resuelto: apunta a `backend/` para
los cuatro de hoy y a `frontend/` para el único que no lo es — la misma distinción que ya existe en
`docker-compose.yml`, y no una lista de nombres de servicio en el guard.

**Dónde corre**: como paso del workflow `compose-ports` existente, que ya es el gate de
`docker-compose.yml` y ya paga el patrón detect/suite/gate. No se crea un décimo workflow: sería
repetir esa estructura entera —y `specs/backend-ci.md` R1.3 prohíbe `paths:` en su `on:`, así que un
workflow nuevo se ejecutaría en cada Pull Request— para vigilar el mismo fichero que aquél ya vigila.
El script sí es propio (`scripts/compose-bytecode.py`), para no engordar `compose-ports.py`, y
reutiliza su invocación (`config --no-interpolate --no-env-resolution`, suelo Compose 2.35.0), que
está resuelta ahí por un motivo medido: `config` desnudo vuelca el `.env` entero.

Rejected: comprobar por nombre `migrate`/`backend`/`worker`/`beat` — una lista de nombres que el
siguiente servicio esquiva sin darse cuenta.
Rejected: un workflow propio para el guard — duplica el patrón detect/suite/gate y, sin `paths:`,
corre en cada Pull Request para vigilar un fichero que ya tiene gate.
Rejected: sólo verificación puntual al implementar — cierra el incidente de hoy y deja la regla sin
dueño mañana.

### D9 — El hook entra agente a agente, empezando por uno

**Chosen:** se instala primero en `actions-runner-2`, se observan varios jobs reales, y sólo entonces
se extiende a los otros tres. Decidido con la usuaria.

El motivo es la asimetría del fallo: el contrato de GitHub dice que un código de salida distinto de
cero del hook **falla el job**, así que un hook defectuoso en los cuatro agentes deja la CI entera
inoperativa — y no se arregla por Pull Request, porque los workflows de ese Pull Request tampoco
correrían. Con tres agentes sin hook queda vía de escape. El escalonado es de procedimiento
(`RUNBOOK.md §6.2`) y no exige código condicional.

Rejected: los cuatro en una sola pasada del bootstrap — es el procedimiento normal de §6.2 y el más
rápido, pero sin vía de recuperación si el hook falla.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Stack local | `docker-compose.yml` | `PYTHONDONTWRITEBYTECODE: "1"` en `environment:` de `migrate`, `backend`, `worker`, `beat` (R1.1) |
| Backend | `backend/pyproject.toml` | Nueva sección `[tool.pytest.ini_options]` con `cache_dir` fuera del árbol (R2.1) |
| Infra dev | `infra/environments/dev/runner-job-started.sh` | **Nuevo.** El hook: short-circuit si no hay ficheros ajenos, si no `chown -R` acotado al `_work/` propio (R3.1, R3.3, R3.4, R3.6) |
| Infra dev | `infra/environments/dev/runner-bootstrap.sh` | Instala el hook en `$RUNNER_HOME/hooks/`, escribe `$RUNNER_HOME/.env`, y reinicia el agente si el `.env` cambió y está ocioso (R3.2, D4). **Enmienda 2026-09-15**: la comprobación de liveness contra la API de GitHub (`gh_in_progress_url_for_runner`) falla cerrada ante cualquier incertidumbre, y el reinicio diferido distingue "job confirmado" (rc=2) de "API no respondió" (rc=3) — ver D4 |
| Infra dev | `infra/environments/dev/cloud-init.yaml.tftpl`, `main.tf` | El hook viaja a la VM nueva igual que el bootstrap: `file()` en `main.tf` + `write_files` en el cloud-init |
| Infra dev | `infra/environments/dev/RUNBOOK.md` | §6.2 gana el paso de copiar el hook y la nota del reinicio (D7) |
| CI | `scripts/` + `Makefile` + workflow de gates | **Nuevo.** Guard que lee la composición resuelta y exige la variable en todo servicio con bind mount del árbol (R5, D8) |
| Docs | `docs/ci-runner-rollback.md` | Cómo desactivar el hook sin desaprovisionar el pool |
| Infra dev / CI | `.github/workflows/infra-dev.yml` | **Enmienda 2026-09-15** (panel de `/sdd:review`, `sdd-security` + `sdd-review-cicd`, feature-scale): el job `check` gana un paso `astral-sh/setup-uv` + `pytest` sobre `infra/environments/dev/`, para que las suites de las secciones 3-4 (792 líneas: `test_runner_job_started.py`, `test_runner_bootstrap_env.py`) no corran solo a mano — mismo patrón/SHA que el paso equivalente de `compose-ports.yml` para `scripts/`. Sin tocar `on:`/`concurrency`/`timeout-minutes`. **Segunda enmienda, misma fecha** (`sdd-security`, feature-scale, round 6): la frase original de esta fila ("el `check` job ya corría sin credenciales de OCI") describe el *entorno* del job, no el *host* — el pool ya es root-equivalente vía `%ci-agents ALL=(ALL) NOPASSWD:ALL` y alcanza el Vault por instance principal, así que este paso hereda la postura de aceptar código de PR que el pool ya tenía (ver `ci-runner-self-hosted.md` §«Riesgo aceptado»), no una excepción credential-free nueva. Añadido `permissions: contents: read` a nivel de workflow (el fichero no declaraba ninguno; mismo patrón que `compose-ports.yml`/`backend-tests.yml`/`rule11-ownership.yml`) — mínimo privilegio explícito en vez del default del token del repo. |

## Data & interfaces

Ninguna interfaz de aplicación cambia. Sí hay dos ajustes de configuración nuevos:

- `PYTHONDONTWRITEBYTECODE=1` — entorno de cuatro servicios de compose (sólo stack local).
- `ACTIONS_RUNNER_HOOK_JOB_STARTED` — en `/opt/actions-runner-<i>/.env` de cada agente, con la ruta
  absoluta del hook instalado. Contrato del hook (lo fija GitHub): se ejecuta como el usuario del
  agente antes de cada job; un código de salida distinto de cero **falla el job**.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **El hook falla y tumba todos los jobs del pool.** Su salida distinta de cero falla el job, así que un hook roto es peor que el problema que arregla. | El hook no aborta por sí mismo: registra y devuelve 0 salvo que el `chown` falle de verdad (R3.5). Se prueba en un agente antes de extenderlo (ver plan de despliegue en tasks). |
| **`chown -R` con `sudo` sobre una ruta mal construida.** Los agentes tienen `NOPASSWD:ALL`. | La ruta se deriva de `$RUNNER_HOME` y se valida antes de usarla: debe ser absoluta, existir, y terminar en `/_work`; si no, el hook no actúa (R3.6). |
| **Se aplica el bootstrap y nada cambia**, porque el agente no releyó el `.env`. Es el fallo silencioso más probable. | D4 lo automatiza; la verificación de §6.2 comprueba la variable en el proceso vivo, no sólo el fichero en disco. |
| **El reinicio aborta un job en vuelo.** | Guardia de liveness antes de reiniciar (D4), igual que la fase de baja. |
| **La regla se erosiona**: alguien añade un quinto servicio con bind mount y sin la variable, y el incidente vuelve. | El guard de D8/R5, que deriva los servicios en alcance del propio compose en vez de fijar una lista. |
| **`cache_dir` en una ruta no escribible** deja la suite sin caché o la rompe. | R2.3 lo cubre: `pytest` degrada sin fallar si no puede escribir la caché; la verificación lo comprueba explícitamente. |

## Open questions

Ninguna pendiente: las dos que tenía este diseño se resolvieron con la usuaria el 2026-09-14 y están
recogidas como D8 y D9.
