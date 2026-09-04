# Runner self-hosted de CI/CD

## Purpose

Esta capacidad describe el runner self-hosted de GitHub Actions (VM `dev`, label `[self-hosted,
dev]`) como recurso compartido por los 10 workflows de `.github/workflows/`, y el contrato que
un workflow debe cumplir para vivir en él sin romper a los demás ni asumir tooling que solo
`ubuntu-latest` preinstala. El runner en sí (aprovisionamiento, credenciales, convivencia
deploy↔reset) ya está especificado en `app-deploy-dev`; esta spec cubre la adopción del runner
por el resto de la CI (change `ci-runner-oci`, 2026-09-04) y el procedimiento de vuelta atrás.

## Requirements

### Workflows que corren en el runner

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
  del runner, el puntero a `docs/ci-runner-rollback.md` y el change que introdujo la migración.

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
- No instala tooling en el runner mismo (`runner-bootstrap.sh` no cambia): la fuente de verdad de
  cada versión sigue siendo el lockfile o el pin de la acción, no el aprovisionamiento de la VM.

### Convivencia entre workflows en un runner persistente

- Al ser un runner persistente compartido (no una VM efímera por job), THE SYSTEM SHALL evitar
  que el checkout de un workflow borre estado que otro necesita: todos los workflows usan el
  checkout por defecto (`clean: true`); el `.env` de `deploy-dev.yml` vive fuera del workspace,
  en `$HOME/.autohostai-dev-runtime.env` (ver `app-deploy-dev`), precisamente porque 7 workflows
  `pull_request`-triggered más comparten el mismo disco desde esta migración.
- THE SYSTEM SHALL publicar los puertos de los `services` de `backend-tests.yml`
  (`postgres`/`redis`) únicamente en `127.0.0.1` (`127.0.0.1:5432:5432`,
  `127.0.0.1:6379:6379`): en un runner con IP pública, publicar a `0.0.0.0` expondría esos
  servicios innecesariamente, a diferencia de la VM efímera de `ubuntu-latest`.
- THE SYSTEM SHALL preceder con `umask 077` cualquier escritura de una credencial a fichero en el
  runner (p. ej. `infra-dev.yml` escribiendo `OCI_PRIVATE_KEY` a `$RUNNER_TEMP`) y SHALL borrarla
  explícitamente con un paso `if: always()`: `$RUNNER_TEMP` se limpia al iniciar el *siguiente*
  job, no al terminar el actual, así que sin borrado explícito el fichero sobrevive entre jobs en
  el runner persistente.
- THE SYSTEM SHALL cerrar sesión del registro de contenedores (`docker logout ghcr.io`,
  `if: always()`) al final de cualquier job que haga `docker login` (`deploy-dev.yml`:
  `build-backend`, `build-frontend`, `deploy`): la credencial de GHCR no debe sobrevivir al job en
  un runner que no se recicla entre ejecuciones.

### Riesgo aceptado: ampliación del radio de confianza

- El runner persistente comparte host entre jobs `pull_request`-triggered (código de un PR no
  fusionado) y jobs que manejan credenciales de producción de `dev` (Vault, GHCR, `terraform
  apply`, el stack desplegado públicamente en `autohostai.digitalsec.work`). Antes de esta
  migración, esos jobs `pull_request` corrían en runners GH-hosted efímeros sin ninguna
  credencial de OCI y sin compartir host con el deploy real.
- THE SYSTEM SHALL considerar este riesgo **aceptado explícitamente** (no mitigado técnicamente
  en este change): el repo es privado, los colaboradores con permiso de abrir PR son de
  confianza, y no se justificó un segundo runner o una política IAM/Docker más restrictiva solo
  por esta migración. Se reevalúa si se añade un secreto nuevo a la policy del runner, si el repo
  acepta colaboradores externos, o si el coste de un pool dedicado a `pull_request` deja de ser
  desproporcionado.

### Verificación antes de mergear y su límite

- THE SYSTEM SHALL exigir, antes de abrir el PR de una migración de workflow al runner, un run
  verde runner-side de cada job migrable disparable desde la rama del PR (push, `pull_request` o
  `workflow_dispatch`).
- WHERE un job está gateado a `main` (`if: github.ref == 'refs/heads/main'`) o su filtro
  `paths` no matchea el diff de la migración, THE SYSTEM SHALL NOT poder producir esa evidencia
  antes de mergear — GitHub no dispara el job en absoluto sobre ese PR. La primera evidencia
  runner-side real de esos jobs (`deploy-dev`: `build-backend`, `build-frontend`, `deploy`;
  `infra-dev`: `plan`, `apply`, `check`) llega con la primera ejecución que sí los dispare tras el
  merge, y se trata como gate vigilado explícito con rollback inmediato si falla por algo que
  `ubuntu-latest` no habría revelado.

### Rollback

- THE SYSTEM SHALL mantener `docs/ci-runner-rollback.md` como procedimiento versionado de vuelta
  a `ubuntu-latest`: tabla de los 10 workflows con su `runs-on` previo/actual, el SHA de la
  migración, el comando `git revert` (global) y el patch mínimo de un solo workflow (manual, para
  cuando la VM del runner está caída y `git revert` global no es suficientemente quirúrgico).
- THE SYSTEM SHALL enlazar el runbook desde `README.md` (sección "CI / runner self-hosted") y
  desde la cabecera de cada workflow migrado.

## Key files

- `.github/workflows/*.yml` — los 10 workflows; 9 declaran `runs-on: [self-hosted, dev]`,
  `multiarch-build-check.yml` queda en `ubuntu-latest`.
- `backend/.python-version` — ancla de versión de Python para `uv` en el runner.
- `docs/ci-runner-rollback.md` — runbook de rollback (tabla de workflows, comando `git revert`,
  patch manual de un solo workflow).
- `infra/environments/dev/runner-bootstrap.sh` — aprovisionamiento del runner (sin cambios por
  esta migración; ver `app-deploy-dev` para su contrato completo).
