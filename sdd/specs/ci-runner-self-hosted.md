# Runner self-hosted de CI/CD

## Purpose

Esta capacidad describe el **pool de N agentes self-hosted** de GitHub Actions que viven en la VM `dev`
(uno por proceso systemd, label `[self-hosted, dev]`, nombres `autohostai-${ENV}-vm-<i>` para
`i ∈ [1..N]`) como recurso compartido por los 10 workflows de `.github/workflows/`, y el contrato
que un workflow debe cumplir para vivir en él sin romper a los demás ni asumir tooling que solo
`ubuntu-latest` preinstala. El pool en sí (aprovisionamiento de los N agentes, credenciales,
convivencia deploy↔reset) ya está especificado en `app-deploy-dev`; esta spec cubre la adopción
del pool por el resto de la CI (changes `ci-runner-oci` 2026-09-04 y `ci-runner-pool-oci`
2026-09-04) y los procedimientos de subir/bajar N y de vuelta atrás.

## Requirements

### Workflows que corren en el pool

- THE SYSTEM SHALL ejecutar en `runs-on: [self-hosted, dev]` todos los jobs de 9 de los 10
  workflows: `api-contract.yml`, `backend-tests.yml` (3 jobs), `compose-ports.yml`,
  `demo-reset.yml`, `deploy-dev.yml` (4 jobs), `frontend-api-contract.yml`, `frontend-tests.yml`
  (2 jobs), `infra-dev.yml` (3 jobs) y `rule11-ownership.yml`.
- THE SYSTEM SHALL mantener `multiarch-build-check.yml` en `runs-on: ubuntu-latest` como
  excepción deliberada: la verificación de que `docker/setup-qemu-action@v3` registra
  `binfmt_misc` en la VM (self-hosted) no llegó a ejecutarse antes de mergear esta migración
  (IP de la VM no alcanzable desde el worktree de implementación) — la excepción documentada es
  "QEMU no verificado", no un fallo confirmado. Migrar este workflow queda como trabajo futuro
  que primero corra esa verificación.
- THE SYSTEM SHALL preservar en cada workflow migrado su `concurrency.group`,
  `concurrency.cancel-in-progress`, `permissions`, `timeout-minutes`, `env` y disparadores
  (`on.push`/`on.pull_request`, `paths`, `branches`) exactos: la migración cambia únicamente el
  runner y el tooling declarado por job (siguiente sección), nunca la lógica de qué corre ni
  cuándo.
- THE SYSTEM SHALL declarar en la cabecera de cada workflow migrado un comentario con el label
  del pool (`[self-hosted, dev]`), el puntero a `docs/ci-runner-rollback.md` y los changes que
  introdujeron la migración (`ci-runner-oci`, `ci-runner-pool-oci`).
- WHERE la variable de Terraform `runner_count` toma el valor `N`, THE SYSTEM SHALL registrar
  exactamente N agentes en GitHub con label `dev` y nombre `autohostai-${ENV}-vm-<i>` para
  `i ∈ [1..N]`, todos en la misma VM, de modo que GitHub Actions pueda repartir los jobs entre
  ellos en paralelo y la cola no se serialice tras un único agente (R1).
- WHEN dos jobs `pull_request`-triggered coinciden con label `[self-hosted, dev]`, THE SYSTEM
  SHALL permitir que GitHub los asigne a dos agentes distintos y corran en paralelo, sujeto a la
  holgura CPU/memoria de la VM (ver R6).
- THE SYSTEM SHALL NOT introducir un label nuevo (`[self-hosted, dev, buildx]`,
  `[self-hosted, dev, terraform]`, etc.) ni un pool por dominio: el particionado es por capacidad
  física dentro de la misma VM, no por dominio de trabajo (R1).

### Aislamiento por usuario Linux y servicio systemd

**Alcance de este "aislamiento": separa workspaces y servicios entre agentes, no es un límite
de confianza entre ellos.** Los N usuarios comparten grupo `docker` (root-equivalente sobre el
socket) y, por construcción, el mismo alcance de instance principal que la VM — un agente
comprometido puede alcanzar lo mismo que cualquier otro. Lo que esta separación evita es que un
`git clean -ffdx` o un fallo de un agente pisoteen el `_work/` o el servicio de otro (D1); no es
una defensa contra un agente que actúa con intención hostil dentro de la misma VM. Ver "Riesgo
aceptado" más abajo, que enumera explícitamente este radio.

- THE SYSTEM SHALL crear un usuario Linux por agente (`actions-runner-1`/`actions-runner-2`/…),
  añadido al grupo `docker` (igual que hoy `ubuntu`), con
  `RUNNER_HOME=/opt/actions-runner-<i>` y `_work/` propio (R2).
- THE SYSTEM SHALL instalar `actions-runner` en cada `RUNNER_HOME` y registrarlo con
  `./svc.sh install <user> && ./svc.sh start`, generando el servicio systemd
  `actions.runner.<org>-<repo>.autohostai-${ENV}-vm-<i>.service` (R2).
- THE SYSTEM SHALL ejecutar el `./config.sh` de cada agente con `--unattended --replace` para
  que reaprovisionar la VM viva sea idempotente — el `--replace` reescribe la URL/token de un
  agente preexistente sin retirarlo, así que reejecutar el bootstrap deja a los agentes
  correctos intactos (R2, R3).

### Tooling declarado por job, no asumido del runner base

- WHERE un job usaba una herramienta que `ubuntu-latest` preinstala sin que el workflow la
  declarase (`node`, un `python3` ≥ 3.11/3.12), THE SYSTEM SHALL añadir el paso de setup
  correspondiente (acción pineada por SHA, con el mismo pin que el resto del repo) o el fichero
  de versión del proyecto — nunca asumir que el runner self-hosted trae una versión concreta sin
  declararla. El runner de la VM trae `python3` 3.10 del sistema; sin este paso, `uv sync`
  resuelve un intérprete distinto al de `ubuntu-latest` (medido: CPython 3.14.7 vs 3.12.3) y
  puede introducir fallos de compatibilidad que `ubuntu-latest` nunca hubiera mostrado.
- THE SYSTEM SHALL declarar `backend/.python-version` = `3.12` como ancla de `uv` para el
  backend, alineado con `python:3.12-slim` (la imagen de producción).
- THE SYSTEM SHALL usar `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4` con
  `node-version: "22"` en el job `provenance` de `deploy-dev.yml` (invoca
  `frontend/scripts/build-identity.mjs` sin runtime de Node propio).
- THE SYSTEM SHALL usar `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0`
  con `python-version: "3.12"` en `frontend-tests.yml` (job `provenance-contract`, antes de
  `make check-version-parity`) y en `rule11-ownership.yml` (antes de
  `make check-rule11-ownership`) — ambos scripts invocan `python3` fuera del árbol de
  dependencias de `uv` y dependen de sintaxis ≥ 3.11 (`tomllib`, `enum.StrEnum`).
- No instala tooling en los agentes mismos: la fuente de verdad de cada versión sigue siendo el
  lockfile o el pin de la acción, no el aprovisionamiento de la VM. El cloud-init instala
  Docker, Compose, `oci-cli` y Python del sistema **una vez por VM**, no una vez por agente (R4).
- THE SYSTEM SHALL declarar en `infra/environments/dev/runner-bootstrap.sh` solo los pasos que
  varían por agente: alta de usuario, descarga/instalación de `actions-runner-<i>` en su
  `$RUNNER_HOME`, `./config.sh --labels dev --name autohostai-${ENV}-vm-<i>`, y
  `./svc.sh install <user> && ./svc.sh start` (R4).

### Convivencia entre workflows en un pool persistente

- Al ser un pool persistente compartido (no una VM efímera por job), THE SYSTEM SHALL evitar
  que el checkout de un workflow borre estado que otro necesita: todos los workflows usan el
  checkout por defecto (`clean: true`); el `.env` de `deploy-dev.yml` vive fuera del workspace,
  en `/opt/autohostai-dev-runtime/dev-runtime.env` (ver `app-deploy-dev`), precisamente porque 7
  workflows `pull_request`-triggered más comparten el mismo disco desde esta migración.
- **Corregido** (fix rápido 2026-09-05, fuera del flujo SDD): la ruta original de esta migración
  era `$HOME/.autohostai-dev-runtime.env`, pero `$HOME` es por-agente (cada `actions-runner-<i>`
  tiene el suyo) y GitHub reparte los jobs `deploy`/`demo-reset` entre los N agentes sin garantizar
  que caigan en el mismo — el `demo-reset` programado de un día cayó en un agente que nunca vio el
  `.env` escrito por el `deploy` del día anterior en otro agente (run 33953115006). THE SYSTEM
  SHALL escribir y leer ese `.env` en una ruta fuera de `$HOME`, con el directorio contenedor
  `chmod 2770` (setgid) y `chown root:ci-agents`, para que cualquier agente del pool (todos
  miembros de `ci-agents`) pueda crearlo, leerlo y sobrescribirlo — esto no amplía el radio de
  confianza descrito más abajo ("Riesgo aceptado"), porque `ci-agents` ya tiene sudo NOPASSWD
  sobre toda la VM.
- THE SYSTEM SHALL publicar los puertos de los `services` de `backend-tests.yml`
  (`postgres`/`redis`) únicamente en `127.0.0.1` (`127.0.0.1:5432:5432`,
  `127.0.0.1:6379:6379`): en un agente con IP pública, publicar a `0.0.0.0` expondría esos
  servicios innecesariamente, a diferencia de la VM efímera de `ubuntu-latest`.
- THE SYSTEM SHALL preceder con `umask 077` cualquier escritura de una credencial a fichero en el
  runner (p. ej. `infra-dev.yml` escribiendo `OCI_PRIVATE_KEY` a `$RUNNER_TEMP`) y SHALL borrarla
  explícitamente con un paso `if: always()`: `$RUNNER_TEMP` se limpia al iniciar el *siguiente*
  job, no al terminar el actual, así que sin borrado explícito el fichero sobrevive entre jobs en
  el pool persistente.
- THE SYSTEM SHALL cerrar sesión del registro de contenedores (`docker logout ghcr.io`,
  `if: always()`) al final de cualquier job que haga `docker login` (`deploy-dev.yml`:
  `build-backend`, `build-frontend`, `deploy`): la credencial de GHCR no debe sobrevivir al job en
  un agente que no se recicla entre ejecuciones.

### Reaprovisionamiento declarativo e idempotente del pool

- WHEN el operador reaplica `runner-bootstrap.sh` sobre la VM viva (procedimiento documentado
  en `infra/environments/dev/RUNBOOK.md §6.2`) con un `RUNNER_COUNT` dado, THE SYSTEM SHALL
  crear los agentes que falten para alcanzar el valor y SHALL NOT tocar los que ya están
  registrados correctamente — `./config.sh --replace` por nombre es idempotente (R3).
- WHEN `RUNNER_COUNT` baja entre reaprovisionamientos, THE SYSTEM SHALL dar de baja
  explícitamente los agentes sobrantes (`./config.sh remove --token ... && ./svc.sh
  uninstall`) y SHALL NOT recolectar automáticamente: lo opuesto a `--replace` no es
  recuperable de un fallo, así que la baja es código separado y explícito (R3, R5).
- WHERE un agente a retirar está `active` (`systemctl is-active` devuelve `active`) o tiene
  jobs `in_progress` (consulta `gh api ... /actions/runs?status=in_progress` filtrando por
  `runner.name == autohostai-${ENV}-vm-<i>`), THE SYSTEM SHALL abortar el reaprovisionamiento
  con `set -e` y un mensaje que nombre al agente y al job en vuelo (vía la URL del run); el
  reaprovisionamiento SHALL NOT retirar un agente en vuelo (R3).
- THE SYSTEM SHALL escribir `/var/lib/autohostai-runner/agents.list` con los nombres
  `autohostai-${ENV}-vm-<i>` registrados, atómico (`mv` desde un `mktemp`), como fuente de
  verdad para la fase de baja del próximo reaprovisionamiento (R3).
- WHERE el operador reaplica el bootstrap sobre una VM provisionada por `ci-runner-oci` (un
  agente con el nombre legado `autohostai-${ENV}-vm` sin sufijo numérico), THE SYSTEM SHALL
  retirar el agente legado antes del bucle (`./config.sh remove --token ... && ./svc.sh
  uninstall actions.runner.<org>-<repo>.autohostai-${ENV}-vm.service`) detectándolo por nombre
  vía `gh api ... /repos/{owner}/{repo}/actions/runners`. Sin esta migración, un rollback a
  `runner_count = 1` dejaría dos agentes vivos (legado + agente-1) y rompería R5 (R3, R5).
- THE SYSTEM SHALL fallar el reaprovisionamiento con un mensaje que nombre al agente
  (`agent <i>/<N>: <acción>: <error>`) si GitHub rechaza el registro (credenciales, rate limit,
  etc.), sin dejar el estado a medias: un fallo en el agente `k` **no detiene el bucle** — los
  agentes `1..k-1` quedan reconciliados y `k+1..N` se siguen intentando en sus propias subshells
  aisladas (corrección 2026-09-04, panel de `/sdd:review`: la redacción anterior decía que
  `k+1..N` quedaban "sin tocar", contradiciendo el propio código), y el operador ve un informe
  completo por agente en una sola ejecución antes de reaplicar con la fix del error (R3).
- THE SYSTEM SHALL NOT introducir nuevos secrets ni nuevas sentencias IAM en el
  reaprovisionamiento: el installation-token de la GitHub App ya minteado por
  `gh-app-install-token.py` sirve para los N `./config.sh`, y el instance principal de la VM
  (que ya tiene `secret-bundle get` por OCID y por nombre) lo invoca `sudo` desde `ubuntu`
  leyendo `/etc/autohostai-deploy.env` (R3).

### Riesgo aceptado: ampliación del radio de confianza

- El pool persistente comparte host entre jobs `pull_request`-triggered (código de un PR no
  fusionado) y jobs que manejan credenciales de producción de `dev` (Vault, GHCR, `terraform
  apply`, el stack desplegado públicamente en `autohostai.digitalsec.work`). Antes de esta
  migración, esos jobs `pull_request` corrían en runners GH-hosted efímeros sin ninguna
  credencial de OCI y sin compartir host con el deploy real.
- **Extensión cuantitativa por `ci-runner-pool-oci` (2026-09-04, no cualitativa)**: el número de
  principales locales con acceso al socket de Docker (grupo `docker`) y al instance principal de
  la VM pasa de **1** (`ubuntu`, un único runner) a **N** (`actions-runner-1..N`, uno por agente
  del pool). La naturaleza del riesgo no cambia — sigue siendo "un PR no fusionado corre en un
  host con credenciales de producción de `dev`" — pero el número de cuentas que lo materializan
  sí, en proporción directa a `runner_count`.
- THE SYSTEM SHALL considerar este riesgo **aceptado explícitamente** (no mitigado técnicamente
  en este change): el repo es privado, los colaboradores con permiso de abrir PR son de
  confianza, y no se justificó un pool dedicado a `pull_request` o una política IAM/Docker más
  restrictiva solo por esta migración. Se reevalúa si se añade un secreto nuevo a la policy del
  pool, si el repo acepta colaboradores externos, si el coste de un pool dedicado a
  `pull_request` deja de ser desproporcionado, o **si `runner_count` sube** (cada incremento
  añade un principal más con el mismo alcance — la nota de medición de R6.3 cubre la contención
  CPU/memoria, no este radio de confianza, así que subir N por encima del default requiere
  releer esta sección, no solo la de rendimiento).

### Verificación antes de mergear y su límite

- THE SYSTEM SHALL exigir, antes de abrir el PR de una migración de workflow al pool, un run
  verde runner-side de cada job migrable disparable desde la rama del PR (push, `pull_request` o
  `workflow_dispatch`).
- WHERE un job está gateado a `main` (`if: github.ref == 'refs/heads/main'`) o su filtro
  `paths` no matchea el diff de la migración, THE SYSTEM SHALL NOT poder producir esa evidencia
  antes de mergear — GitHub no dispara el job en absoluto sobre ese PR. La primera evidencia
  runner-side real de esos jobs (`deploy-dev`: `build-backend`, `build-frontend`, `deploy`;
  `infra-dev`: `plan`, `apply`, `check`) llega con la primera ejecución que sí los dispare tras el
  merge, y se trata como gate vigilado explícito con rollback inmediato si falla por algo que
  `ubuntu-latest` no habría revelado.
- WHEN se modifica `runner_count` (terraform apply o reaprovisionamiento), THE SYSTEM SHALL
  verificar vía `gh api ... /repos/{owner}/{repo}/actions/runners` que existen exactamente N
  entradas con label `dev`, nombre `autohostai-${ENV}-vm-<i>` para `i ∈ [1..N]`, status
  `online`, y que **no** queda la entrada legada `autohostai-${ENV}-vm` (R1, R3).

### Rollback

- THE SYSTEM SHALL mantener `docs/ci-runner-rollback.md` como procedimiento versionado de vuelta
  a `ubuntu-latest`: tabla de los 10 workflows con su `runs-on` previo/actual, el SHA de la
  migración, el comando `git revert` (global) y el patch mínimo de un solo workflow (manual, para
  cuando la VM del pool está caída y `git revert` global no es suficientemente quirúrgico).
- THE SYSTEM SHALL ampliar `docs/ci-runner-rollback.md` con dos secciones operativas: «Subir N»
  (`runner_count++` en `variables.tf` o `dev.tfvars`, `terraform apply`,
  `sudo bash /opt/bootstrap-runner.sh "$RUNNER_COUNT"`, verificación con `gh api ... /actions/runners`
  que muestre N entradas `autohostai-${ENV}-vm-<i>` online y sin legado) y «Bajar N» (camino
  inverso, condicionando la fase de baja a `is-active == inactive`; si aborta con
  «agente activo, jobs en vuelo: <run-url>», esperar a que termine el job o cancelar el PR y
  reaplicar) (R5).
- THE SYSTEM SHALL mantener `runner_count = 1` como estado de rollback válido: reaprovisionar
  con N=1 deja un único agente `autohostai-${ENV}-vm-1` funcional, idéntico al estado
  post-`ci-runner-oci` (R5).
- THE SYSTEM SHALL enlazar el runbook desde `README.md` (sección "CI / runner self-hosted") y
  desde la cabecera de cada workflow migrado.
- THE SYSTEM SHALL actualizar `infra/environments/dev/RUNBOOK.md §6.2` para que el
  procedimiento de reaprovisionamiento mencione el parámetro `RUNNER_COUNT` (pasado al script
  como `"$RUNNER_COUNT"`, con fallback interno a `RUNNER_COUNT=4`) y la lista esperada de N
  entradas `autohostai-dev-vm-<i>` (`i ∈ [1..N]`) Idle tras reaplicar (R5).

### Holgura CPU/memoria y contención con la app

- THE SYSTEM SHALL validar `runner_count` en `infra/environments/dev/variables.tf` en el rango
  `1 ≤ runner_count ≤ 4`, con `default = 4`, alineado con la capacidad de la VM (`VM.Standard.A1.Flex`,
  4 OCPU/24 GB/200 GB, AD-3, PAYG — ADR 0001 addendum 2026-07-21) y la convivencia con el
  stack `docker compose` que sirve `autohostai.digitalsec.work` (R6).
- WHERE el operador quiera subir `runner_count > default` (i.e. `> 4`), THE SYSTEM SHALL
  exigir una nota de medición explícita (tiempo de suite del backend con otro agente corriendo
  la del frontend en paralelo, latencia p50 del frontend público) archivada en
  `infra/environments/dev/RUNBOOK.md §6.2` antes de aceptar el `terraform apply`. La nota se
  exige al subir sobre el valor que ya se asume validado, no sobre el rango entero (R6).
- THE SYSTEM SHALL documentar en `infra/environments/dev/README.md` el rango razonable de
  `runner_count` (1–4) sostenido por la métrica observada y la exigencia de nota de medición
  para valores por encima del default (R6).
- THE SYSTEM SHALL NOT auto-escalar `runner_count`: subir o bajar N es decisión del operador,
  no del pool (R6).

## Key files

- `.github/workflows/*.yml` — los 10 workflows; 9 declaran `runs-on: [self-hosted, dev]`,
  `multiarch-build-check.yml` queda en `ubuntu-latest`.
- `backend/.python-version` — ancla de versión de Python para `uv` en el runner.
- `docs/ci-runner-rollback.md` — runbook de rollback (tabla de workflows, comando `git revert`,
  patch manual de un solo workflow, secciones «Subir N» / «Bajar N»).
- `infra/environments/dev/runner-bootstrap.sh` — aprovisionamiento del pool de N agentes:
  migración del legado `autohostai-${ENV}-vm`, bucle `for i in 1..RUNNER_COUNT` con
  `./config.sh --unattended --replace` y baja condicionada a `is-active != active` (ver
  `app-deploy-dev` para el contrato completo del bootstrap base).
- `infra/environments/dev/{variables.tf,main.tf,cloud-init.yaml.tftpl}` — fuente del
  parámetro `runner_count` (default 4, validación 1..4) cableado al bootstrap vía `templatefile()`
  y `runcmd`.
- `infra/environments/dev/RUNBOOK.md §6.2` — reaprovisionamiento idempotente del pool con
  `RUNNER_COUNT` explícito y verificación de N agentes Idle.
- `infra/environments/dev/README.md` — nota sobre el rango razonable de `runner_count`, la
  métrica que lo sostiene y la exigencia de nota de medición para `runner_count > default`.