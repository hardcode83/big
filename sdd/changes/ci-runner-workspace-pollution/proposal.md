# Proposal: ci-runner-workspace-pollution

## Why

El stack local monta el árbol del repositorio dentro de los contenedores (`./backend:/app` en
`migrate`, `backend`, `worker` y `beat`) y **ninguno de los cuatro declara `user:`**, así que corren
como `root`. Al importar código Python, el intérprete escribe `__pycache__/*.pyc` **propiedad de
root sobre el árbol del host**. En la VM `dev` ese árbol es el `_work/` persistente de un agente de
Actions, y el usuario del agente no puede borrar esos ficheros: `actions/checkout` (que corre con
`clean: true`) falla con `EACCES` **en el paso 0** y mata el job antes de que ejecute nada suyo.

El 2026-09-14 esto tumbó, con el mismo fichero
(`backend/alembic/__pycache__/env.cpython-312.pyc`) en los tres casos: el `deploy-dev` del PR #197
(run `34836602502`) y el del PR #196 (run `34840316768`) — dejando dev congelado en el deploy del
PR #194, del 2026-09-13 —, los checks `api-contract`, `e2e-tests` y `backend-tests-detect` del
PR #196, y el `demo-reset` programado (run `34824905559`). Tres de los cuatro agentes estaban
contaminados: `actions-runner-2` con 25 directorios, `-3` con 2, y `-1` con el que disparó el
diagnóstico; sólo `-4` quedaba limpio, y es donde los jobs pasaban.

Dos hechos fijan la forma de la solución:

1. **Ningún paso del workflow puede mitigarlo.** El fallo ocurre en `actions/checkout`, antes de que
   exista un paso propio. Esto lo distingue del `EACCES` gemelo de `frontend/node_modules` que
   `hardening-release` resolvió el mismo día moviendo un bloque *dentro* del job: aquella forma no
   sirve aquí, y su propio comentario ya anticipaba este caso («¿propiedad de otro usuario, p. ej.
   root de un contenedor? necesita intervención en el runner»).
2. **La mitigación que desatascó el incidente fue manual** (`sudo find … -delete` por SSH sobre los
   cuatro `RUNNER_HOME`). `steering/infra.md` lo prohíbe como estado final: *«cualquier paso que hoy
   no puedas codificar debe quedar como script versionado … nunca configuración ad-hoc que solo viva
   en una consola»*.

Verificado empíricamente durante el diagnóstico: un contenedor sobre un bind mount genera el `.pyc`,
y con `PYTHONDONTWRITEBYTECODE=1` no genera ninguno.

Y el journal de `actions-runner-2` fecha la cadena causal dentro de un mismo agente, que es la
evidencia más directa de quién contamina a quién: `api-contract` (10:19:33) y `backend-tests`
(10:19:57) **pasan**; a las 10:20:05 corre `e2e-tests-suite`, que es el workflow que levanta el
stack con `make up`; y a partir de ahí **falla todo lo que aterriza en ese agente**, sea del
workflow que sea — `e2e-tests` (10:21:42), `compose-ports-detect` (10:23:52), `compose-ports`
(10:24:06), `rule11-ownership-detect` (10:30:44), `frontend-api-contract` (10:30:53),
`e2e-tests-detect` (10:31:02) y `compose-ports-suite` (10:31:09). El sembrador es el workflow que
levanta el stack; la víctima es cualquier job posterior del agente.

## What changes

Después de este change, el stack local deja de escribir ficheros en el árbol del repositorio, y el
pool de agentes deja de ser vulnerable a que alguien lo haga de todos modos. Son **dos capas
deliberadamente redundantes**: la primera cierra la causa conocida (los `.pyc` y la caché de
`pytest`); la segunda — un `ACTIONS_RUNNER_HOOK_JOB_STARTED` versionado que `runner-bootstrap.sh`
instala en cada agente — garantiza que el workspace sea siempre borrable por `actions/checkout`,
que es la única defensa posible contra un fichero de root **futuro** de otra fuente (otro servicio,
otro lenguaje, un script nuevo), porque ese fallo ocurre antes de cualquier paso propio.

## Requirements

### R1 — El stack local no deja bytecode en el árbol

**As a** desarrolladora que levanta el stack, **I want** que los contenedores no escriban
`__pycache__` en el repositorio, **so that** el árbol de trabajo no acumule ficheros que no son
míos ni, en la VM de CI, ficheros que el agente no pueda borrar.

Acceptance criteria:

1. WHERE un servicio de `docker-compose.yml` monta el árbol del repositorio por bind mount y
   ejecuta Python (`migrate`, `backend`, `worker`, `beat`), THE SYSTEM SHALL declarar
   `PYTHONDONTWRITEBYTECODE` con valor verdadero en su entorno.
2. WHEN el stack se levanta y se ejercita (arranque de los servicios y ejecución de la suite del
   backend), THE SYSTEM SHALL dejar cero directorios `__pycache__` bajo `backend/` en el árbol del
   host.
3. WHEN el stack se levanta y se ejercita, THE SYSTEM SHALL dejar `git status --porcelain` sin
   ninguna entrada no rastreada atribuible a la ejecución de los contenedores.

### R2 — La caché de pytest vive fuera del árbol

**As a** desarrolladora, **I want** que `pytest` escriba su caché fuera del bind mount, **so that**
el único otro directorio que los contenedores creaban en el árbol deje de aparecer.

Acceptance criteria:

1. THE SYSTEM SHALL configurar el directorio de caché de `pytest` en una ruta fuera del árbol del
   repositorio, declarada en la configuración versionada del backend.
2. WHEN la suite del backend se ejecuta dentro del contenedor, THE SYSTEM SHALL NOT crear
   `backend/.pytest_cache` en el árbol del host.
3. IF la ejecución de la suite no puede escribir en la ruta de caché configurada, THEN THE SYSTEM
   SHALL ejecutar la suite igualmente, sin fallar por ese motivo.

### R3 — Cada agente garantiza un workspace borrable antes de cada job

**As a** responsable de la CI, **I want** que el agente deje su `_work/` en un estado que
`actions/checkout` pueda limpiar, **so that** un fichero que otro proceso haya dejado con otra
propiedad no vuelva a matar todos los workflows a la vez en el paso 0.

Acceptance criteria:

1. THE SYSTEM SHALL versionar en el repositorio un script de hook de inicio de job, bajo
   `infra/environments/dev/`.
2. WHERE `runner-bootstrap.sh` aprovisiona el agente `i`, THE SYSTEM SHALL instalar ese script en su
   `RUNNER_HOME` y declararlo como `ACTIONS_RUNNER_HOOK_JOB_STARTED` del servicio de ese agente,
   para los `i ∈ [1..RUNNER_COUNT]`.
3. WHEN un job comienza en un agente cuyo `_work/` contiene ficheros que el usuario del agente no
   puede borrar, THE SYSTEM SHALL dejarlos borrables por ese usuario antes de que `actions/checkout`
   se ejecute.
4. WHEN el hook se ejecuta sobre un `_work/` que ya está limpio, THE SYSTEM SHALL terminar con éxito
   sin modificar nada.
5. IF el hook falla, THEN THE SYSTEM SHALL registrar en el log del job qué ocurrió, con el
   `RUNNER_HOME` afectado.
6. THE SYSTEM SHALL acotar la actuación del hook al `_work/` del agente que lo ejecuta, y NOT
   actuar sobre el de otro agente ni sobre rutas fuera de él.

### R4 — La causa y su contrato quedan documentados donde se leen

**As a** quien toque un workflow o el compose en el futuro, **I want** encontrar escrito por qué un
contenedor no puede escribir en el árbol y por qué el hook existe, **so that** nadie reintroduzca el
fallo ni intente mitigarlo con un paso dentro del job, que es lo que no funciona.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en la spec del pool de agentes que un fallo de `actions/checkout` no
   es mitigable desde ningún paso del workflow, y que por eso la defensa vive en el hook.
2. THE SYSTEM SHALL documentar en la spec del entorno local la regla de que ningún servicio con bind
   mount del árbol escribe en él, nombrando los ajustes que lo garantizan.
3. THE SYSTEM SHALL registrar el incidente del 2026-09-14 con sus identificadores de run como
   evidencia de la regla, no como relato.

### R5 — La regla tiene un guard que la sostiene

**As a** quien mantenga el stack, **I want** que añadir un servicio que monte el árbol sin el ajuste
falle en CI, **so that** la regla de R1 no dependa de que cada persona la recuerde.

Acceptance criteria:

1. THE SYSTEM SHALL verificar en CI que todo servicio que monta el árbol del repositorio por bind
   mount declara `PYTHONDONTWRITEBYTECODE`.
2. WHERE el guard determina qué servicios están en alcance, THE SYSTEM SHALL derivarlos de la
   composición resuelta, y NOT de una lista de nombres de servicio fijada en el propio guard.
3. WHEN un servicio con bind mount del árbol no declara el ajuste, THE SYSTEM SHALL fallar el check
   nombrando el servicio.
4. WHEN todos los servicios en alcance lo declaran, THE SYSTEM SHALL pasar sin intervención.

## Out of scope

- **Hacer que los contenedores corran con el UID/GID del host (`user:`).** Sería la defensa completa
  por construcción — nada de lo que escriban quedaría de root —, pero toca la propiedad de los
  volúmenes con nombre (`backend_venv`, `backend_media`, `frontend_node_modules`) y arriesga romper
  el arranque local para todo el mundo. Evaluado y descartado para este change; si R1/R2 resultan
  insuficientes porque aparece otro escritor, su sitio es una entrada propia de roadmap.
- **El `EACCES` de `frontend/node_modules`.** Ya lo trató `hardening-release` (PR #197) con un paso
  dentro del job de `e2e-tests`. Este change no lo revisa ni lo reescribe.
- **`autohostai-dev-vm-2`, que estaba `offline` durante el incidente.** Investigado el 2026-09-14 y
  **descartado como parte de esta causa**: el agente no se cayó, lo pararon limpiamente
  (`Stopping…` → `Deactivated successfully`, `status=0/SUCCESS`) a las 10:44:05 UTC, con el servicio
  `enabled`, el disco al 22 % y los inodos al 5 %. Se volvió a arrancar como operación aparte.
- **La limpieza manual ya aplicada por SSH el 2026-09-14.** Fue la mitigación del incidente, no el
  entregable; este change la sustituye por código y no la documenta como procedimiento.
- **El recuento de tareas del scheduler en `README.md`**, que el merge del PR #196 dejó diciendo
  «doce» con dieciséis en el código. Es un defecto real del mismo día pero de otra causa (una
  resolución de conflicto que descartó un lado); su sitio es una entrada propia.

## Affected specs

- `sdd/specs/ci-runner-self-hosted.md` — contrato del pool: añade el hook y la regla de que el paso 0
  no es mitigable desde el workflow.
- `sdd/specs/local-environment.md` — el stack local no escribe en el árbol del repositorio, y el
  guard de CI que lo sostiene (R5), junto a los checks de composición que esa spec ya describe.
- `sdd/specs/infra-dev-terraform.md` — `runner-bootstrap.sh` instala y declara el hook por agente.
