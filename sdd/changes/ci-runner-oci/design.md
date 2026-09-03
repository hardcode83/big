# Design: ci-runner-oci

## Context

El runner self-hosted de GitHub Actions lleva corriendo en la VM `dev` desde `app-deploy-dev` (2026-07-29). Vive en `/opt/actions-runner`, usuario `ubuntu` (añadido al grupo `docker`), registrado con `--labels "$ENV"` (es decir, `dev`) vía `infra/environments/dev/runner-bootstrap.sh:58-66`. La provisión es IaC: `cloud-init.yaml.tftpl` ejecuta el script en VMs nuevas, y un `RUNBOOK.md §6` documenta la ejecución manual sobre la VM viva (el `metadata` de la instancia es ForceNew con `ignore_changes`, así que el cloud-init no se vuelve a aplicar). Las credenciales del runner ante GitHub son efímeras: una GitHub App (`administration: write`) mintea el installation-token con `gh-app-install-token.py`, leyendo la clave privada de la App del OCI Vault por instance principal; el token de registro del runner va por `--config` desde STDIN para no aparecer en argv (`runner-bootstrap.sh:36-43`).

Hoy, de los **10** workflows bajo `.github/workflows/`, solo dos usan el runner:

- `deploy-dev.yml` — solo el job `deploy` (`runs-on: [self-hosted, dev]`); los jobs `provenance`/`build-backend`/`build-frontend` siguen en `ubuntu-latest`.
- `demo-reset.yml` — entero, ya en `[self-hosted, dev]`, además bajo el mismo `concurrency.group: deploy-dev` que `deploy` (serializa reset↔deploy para que no se pisen el `.env` y los contenedores).

Los otros 8 workflows corren en `ubuntu-latest`:

- `api-contract.yml`, `compose-ports.yml`, `frontend-api-contract.yml`, `rule11-ownership.yml` — un solo job, sin secrets, tooling vía actions (`astral-sh/setup-uv`, `actions/setup-node`).
- `backend-tests.yml` — tres jobs (`detect`/`suite`/`consolida`) sobre `ubuntu-latest`; la suite mide 6m15s (`pytest -q -rs`, dominada por esa única línea, ver `sdd/specs/backend-ci.md`).
- `frontend-tests.yml` — dos jobs sobre `ubuntu-latest`, suite Node 22 + Vitest + ESLint + tsc.
- `infra-dev.yml` — tres jobs (`check`/`plan`/`apply`); `check` no usa credenciales OCI; `plan`/`apply` sí, con `OCI_PRIVATE_KEY` y seis secretos más escritos a `$RUNNER_TEMP/oci_private_key.pem` (`infra-dev.yml:62-66`, `infra-dev.yml:152-156`) y `chmod` por defecto del runner.
- `multiarch-build-check.yml` — dos jobs que construyen para `linux/amd64,linux/arm64` vía `docker/setup-qemu-action@v3` y `docker/build-push-action@v6` (`multiarch-build-check.yml:25-32`, `multiarch-build-check.yml:39-46`). Hoy no publica; solo verifica que las imágenes `target: prod` construyen en ambas plataformas.

El `~/.docker/config.json` del runner no existe hoy: `docker/login-action` se invoca desde los workflows con `GITHUB_TOKEN` por job (`packages: write`) en el caso de `deploy-dev`, y los workflows restantes no hacen login (no publican). Tras la migración, el `provenance`/`build-backend`/`build-frontend` de `deploy-dev` también pasan al runner y siguen necesitando ese login — el `GITHUB_TOKEN` del job se inyecta igual en runners self-hosted (es una `permissions:` del job, no del runner).

## Decisions

### D1 — `runs-on` para los 10 workflows: `[self-hosted, dev]`

**Chosen:** todos los 10 workflows declaran `runs-on: [self-hosted, dev]`. Es el mismo label que ya usan `deploy-dev.yml:deploy` y `demo-reset.yml`. No se añade un segundo label (p. ej. `[self-hosted, dev, ci]`) ni se divide en dos pools: la VM es una sola (4 OCPU/24 GB/200 GB) y un label nuevo sin segundo runner físico no aísla nada.

Rejected: `runs-on: self-hosted` (sin label) — funciona pero pierde la pista del entorno (`dev`) y se confunde con runners futuros de staging/prod. `runs-on: ubuntu-latest` con `runs-on: [self-hosted, dev]` por env-var — añade indirección sin aislamiento real con un solo runner.

### D2 — Instalación de tooling en cada workflow (no en `runner-bootstrap.sh`)

**Chosen:** las acciones versionadas (`astral-sh/setup-uv`, `actions/setup-node`, `hashicorp/setup-terraform`, `docker/setup-buildx-action`, `docker/setup-qemu-action`, `docker/login-action`) siguen invocándose por job, como hoy. No se modifica `runner-bootstrap.sh` para pre-instalar `uv`, `node`, `terraform`, `qemu-user-static`, `docker-buildx` o el binario de login.

Razón: el patrón actual ya está declarado y la rotación de versiones vive en el lockfile de cada workflow (`pyproject.toml`, `package-lock.json`, el `terraform_version` del job). Moverlo al bootstrap del runner (a) duplica la declaración de versiones en dos sitios, (b) obliga a reprovisionar la VM viva para cambiar una versión de Node o Terraform, (c) rompe `infra.md` cuando el `cloud-init.yaml.tftpl` queda con versiones vivas que ya no coinciden con el lockfile. El coste es tiempo de instalación por job (pocos segundos), perfectamente compatible con el ahorro de minutos de GH-hosted.

Rejected: pre-instalar todo en `runner-bootstrap.sh` — centraliza pero oscurece qué versión ejecuta realmente cada workflow; cualquier `bump` exige `RUNBOOK §6` (re-bootstrap manual sobre la VM viva, ya documentado por `oci-source-id-update-replaces-boot-volume` como delicada). Pre-instalar solo `qemu-user-static` para `multiarch-build-check` —asimétrico, y la acción `docker/setup-qemu-action@v3` lo trae al runner vía imagen, sin tocar el host.

**Enmienda 2026-09-03 (hallazgo de R7, ver D11).** La premisa «las acciones ya traen el tooling» era cierta solo para el tooling que los workflows *declaraban*. Cuatro jobs usaban además tooling que `ubuntu-latest` preinstala y que nadie había declarado: `node` a pelo en `deploy-dev/provenance`, y un `python3` ≥ 3.11 implícito detrás de `make check-version-parity` y `make check-rule11-ownership`; y `uv sync` resolvía el intérprete contra el `/usr/bin/python3` 3.12.3 del runner de GitHub sin que ningún fichero lo fijara. La decisión D2 se mantiene y se aplica con más rigor: **ese tooling también se declara por job** (acción pineada o fichero de versión del proyecto), nunca en el bootstrap de la VM.

### D3 — Cambios en cada `.yml`: solo `runs-on` + cabecera del runbook

**Chosen:** la migración de un workflow consiste en:

1. Cambiar la línea `runs-on: ubuntu-latest` → `runs-on: [self-hosted, dev]`.
2. Añadir (o reemplazar) una cabecera de fichero que apunte al runbook:

```yaml
# Runner self-hosted en la VM dev (label `[self-hosted, dev]`); ver
# docs/ci-runner-rollback.md para volver a `ubuntu-latest` si hace falta.
# Migration: change ci-runner-oci (PR <n>).
```

3. **(Enmienda 2026-09-03, D11)** Donde el job usaba tooling que `ubuntu-latest` preinstala sin declararlo, añadir el paso que lo declara — la acción de setup correspondiente con el mismo pin que ya usa el repo, o el fichero de versión del proyecto. Nada más.

El resto del workflow (actions pineadas por SHA, `permissions`, `concurrency`, `timeout-minutes`, `env`, `on:`) queda **byte a byte**. R2 del proposal exige preservar esos campos; este design no toca nada más. La formulación original de este punto decía «solo `runs-on` + cabecera»; la verificación R7 del 2026-09-03 demostró que esa forma dejaba cuatro jobs en rojo en el runner (D11), y se enmendó aquí y en R2.3 del proposal.

Rejected: tocar `actions/checkout` con `clean: false` por defecto — solo `demo-reset.yml` lo necesita hoy (`specs/app-deploy-dev.md §74-77`) y solo porque comparte workspace con `deploy`. El resto hace checkout limpio. Cambiar el default contaminaría el árbol del runner con artefactos de un job en otro.

### D4 — `concurrency` y disparadores intactos

**Chosen:** se preservan los grupos de concurrencia tal como están:

- `deploy-dev.yml`: `build-backend` con `group: build-backend-${{ github.ref }}` y `cancel-in-progress: true`; lo mismo en `build-frontend`; `deploy` con `group: deploy-dev` y `cancel-in-progress: false` (compartido con `demo-reset.yml`, esta última decisión es **deliberada** y debe respetarse).
- `demo-reset.yml`: `group: deploy-dev` (mismo grupo, sin cancelación).
- `backend-tests.yml`, `frontend-tests.yml`, `api-contract.yml`, `compose-ports.yml`, `frontend-api-contract.yml`, `rule11-ownership.yml`: cada uno con su `group: <name>-${{ github.ref }}` y `cancel-in-progress: true`.
- `infra-dev.yml`: `apply` con `group: infra-dev-apply` y `cancel-in-progress: false`.

Razón: la cancelación por referencia acota el consumo del runner cuando llega un push nuevo al mismo PR; tocar `concurrency` ahora cambiaría el coste efectivo del runner y abriría la puerta a una cancelación accidental del `deploy` (que no debe cancelarse nunca). Memoria del proyecto: `[blocked-md-must-be-empty-to-ship]` y la serialización reset↔deploy están entre los hallazgos que más costaron en su día.

Rejected: cancelar `deploy-dev` cuando llega otro push — exactamente el comportamiento que `infra-dev-apply` ya rechaza (`cancel-in-progress: false`). Un deploy a medias nunca se cancela.

### D5 — `multiarch-build-check.yml`: migrar con la salvedad documentada

**Chosen:** el workflow se migra a `[self-hosted, dev]` con la misma configuración de hoy (`docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3` + `docker/build-push-action@v6` con `platforms: linux/amd64,linux/arm64`, `push: false`). La acción `docker/setup-qemu-action@v3` registra `binfmt_misc` desde una imagen Docker; en runners self-hosted requiere que el usuario del runner tenga acceso a `/proc/sys/fs/binfmt_misc` (el usuario `ubuntu` con grupo `docker` lo tiene). Si la verificación falla en CI (R7), se revierte solo este workflow a `ubuntu-latest` y el runbook declara la excepción como "9 de 10 migrados, 1 excepción deliberada" con la razón (`QEMU no soportado en el runner arm64 con la versión actual de binfmt`).

Rejected: `runs-on: ubuntu-latest` para siempre — contradice la decisión del usuario ("Las 10 workflows, build incluido"). Skip condicional con `if:` y label dinámico — sobrecomplica para una decisión binaria; un único `runs-on` y, si falla, revertir el fichero es más legible. Reescribir el workflow para verificar solo `linux/arm64` (la plataforma real de la VM) — cambia el contrato del check (R4 del proposal lo prohíbe: "un QEMU que valida arm64 sobre amd64 no añade garantía real" es justo lo que esa reescritura introduce, ASSUMPTION de R4.3 a confirmar en `/sdd:tasks`).

### D6 — `infra-dev.yml`: los tres jobs migran, secretos sin cambios

**Chosen:** los jobs `check`, `plan` y `apply` pasan a `[self-hosted, dev]`. `check` no usa credenciales (`init -backend=false`), así que es trivial. `plan`/`apply` siguen leyendo `secrets.OCI_PRIVATE_KEY`, `secrets.TFSTATE_BUCKET`, `secrets.OCI_REGION`, `secrets.OCI_TENANCY_OCID`, `secrets.OCI_USER_OCID`, `secrets.OCI_FINGERPRINT` (las seis identidades OCI) — las GitHub Actions secrets siguen disponibles en runners self-hosted. La clave privada se sigue escribiendo a `$RUNNER_TEMP/oci_private_key.pem` (`infra-dev.yml:62-66`, `infra-dev.yml:152-156`) y `terraform apply` la lee con `TF_VAR_private_key_path`. `$RUNNER_TEMP` es por-job y efímero incluso en self-hosted; el cleanup lo hace el runner al terminar el job.

Razón: ningún secreto se mueve, ningún valor cambia de nombre. R5 del proposal se cumple.

Rejected: migrar a `instance_principal` desde el runner — el runner ya tiene instance principal (`specs/app-deploy-dev.md §64-66`) y podría usarlo para `terraform apply`, pero eso cambiaría el actor IAM de `svc-terraform-dev` (el usuario concreto declarado en `specs/infra-dev-terraform.md §40-42`) al instance principal del runner, lo que **no** es trivial: la policy IAM de `svc-terraform-dev` (`infra/environments/dev/iam-policy.md`) incluye permisos que el instance principal del runner **no** tiene (`manage dynamic-groups`, `manage users`, `manage groups`, `manage buckets` por nombre — relajaciones conscientes que el `instance principal` no hereda por defecto, ver spec §40). Cambiar el actor IAM es un cambio de seguridad, no de runner. Mantener al usuario `svc-terraform-dev` y solo cambiar `runs-on` es la postura conservadora.

### D7 — Cabecera de los workflows: comentario corto con puntero al runbook

**Chosen:** la cabecera añadida a cada `.yml` migrado sigue la forma de las cabeceras que ya viven en el repo (cf. `compose-ports.yml:1-28`, `rule11-ownership.yml:1-40`, `backend-tests.yml:1-48`): comentario `#` libre arriba del `name:`, con el nombre del change que la introdujo, un puntero al runbook, y la fecha del PR. Formato literal:

```yaml
# Runner self-hosted en la VM dev (label `[self-hosted, dev]`). Rollback: ver
# docs/ci-runner-rollback.md (procedimiento + SHA del commit de migración).
# Cambio: ci-runner-oci (PR <n>).
name: <workflow>
```

Rejected: dejar `name:` arriba del comentario — la convención del repo es comentario primero; en `compose-ports.yml` y `rule11-ownership.yml` el comentario precede a `name:` y queremos respetar la lectura. Enlace al runbook sin fecha — la fecha ayuda a saber si el runbook está al día; sin ella, una relectura tres meses después pierde el anclaje.

### D8 — Forma del runbook `docs/ci-runner-rollback.md`

**Chosen:** el runbook sigue la forma del existente `infra/environments/dev/RUNBOOK.md` (secciones numeradas, prosa corta, comandos copy-paste). Estructura:

1. **Resumen** — qué migró, en qué PR (con SHA), a qué label.
2. **Tabla de workflows** — workflow / `runs-on` previo / `runs-on` actual / excepción (multiarch-build-check si QEMU falló). Igual a la tabla que `pr-review-cicd` validará en cada PR posterior.
3. **Rollback por `git revert`** — comando exacto (`git revert -m 1 <merge-sha>` si es merge commit, `git revert <sha>` si es squash); qué pasa con los jobs en vuelo (siguen con la versión actual, los nuevos arrancan con la revertida); tiempo esperado (segundos).
4. **Rollback manual de un solo workflow** — si el runner VM está caído y hace falta publicar un fix puntual, cómo restaurar un workflow concreto a `runs-on: ubuntu-latest` con un patch mínimo; advertencia de que `git revert` global sigue siendo preferible.
5. **Validación post-rollback** — la lista de 10 workflows y cómo comprobar que vuelven a correr en `ubuntu-latest` (`gh run list --workflow=<name> --json status,headBranch` filtrando por runner label).
6. **Rotación / retirada del runner** — qué pasa si la VM se recrea (`runner-bootstrap.sh` se vuelve a aplicar, los workflows reanudan solos), y cuándo conviene migrar a `infra-github-iac` (provider `integrations/github`) en vez de mantener el runner por código imperativo.

Rejected: runbook en `sdd/specs/` — el contenido es operativo, no un contrato de capacidad. `docs/` es donde el proyecto ya guarda `RUNBOOK.md`, `RUNBOOK-seed-demo.md`, `docs/adr/`. README raíz — el runbook es largo; el README enlaza, no absorbe. Tabla CSV en el repo — se desincroniza con los workflows más rápido de lo que se revisa.

### D9 — Validación de la migración (R7 del proposal)

**Chosen:** el PR de migración incluye:

1. Una descripción estructurada con `gh run list --workflow=<name> --json name,conclusion,headBranch,runner --limit 1` por cada uno de los 10 workflows, contra el commit del PR (o contra el último `workflow_dispatch` si el workflow no se dispara por push/PR).
2. `workflow_dispatch` por cada workflow que no se haya disparado solo al abrir el PR (típico en `compose-ports.yml` que sí se dispara, y `demo-reset.yml` que solo dispara por schedule).
3. Si algún workflow queda rojo tras la migración, el PR **no abre**: el `sdd_lifecycle` registra el bloqueo en `STATE.md` y `BLOCKED.md`, y `tasks.md` separa "verificar QEMU en runner / investigar fallo" como primer item.

Rejected: ejecutar `gh run list` programáticamente en CI — el panel de `/sdd:review` ya hace esto por su cuenta; duplicarlo añade acoplamiento. Confiar en el check automático — el check puede ser verde y un workflow seguir fallando en su job de verdad si la protección `required` lo enmascara; `gh run list` lo expone.

### D10 — Concurrencia del runner: no añadir pool separado

**Chosen:** los 10 workflows comparten el mismo runner físico. Se confía en las `concurrency.cancel-in-progress: true` por ref de cada workflow para acotar la presión cuando entran pushes seguidos al mismo PR. Riesgos (OOM, CPU) documentados en "Risks & mitigations".

Rejected: dividir en `[self-hosted, dev, ci]` y `[self-hosted, dev, cd]` con un segundo runner físico — hoy hay una sola VM; el coste de la segunda (4 OCPU/24 GB/200 GB adicionales) no se justifica para el ahorro marginal (la suite del backend es 6m15s y la del frontend 1-2 min; con un solo runner, una ráfaga de PRs concurrentes encola, pero cancela por ref). Mantener un pool y serializar — destruiría el paralelismo del que las suites se benefician hoy en GH-hosted.

### D11 — Tooling implícito de `ubuntu-latest`: pin explícito por job (enmienda tras R7, 2026-09-03)

**Contexto medido.** Primer `workflow_dispatch` de los 9 workflows migrados sobre `sdd/ci-runner-oci` (runner `autohostai-dev-vm`, labels `self-hosted,dev`): 5 verdes (`api-contract`, `compose-ports`, `frontend-api-contract`, `multiarch-build-check` en GH-hosted por D5, `infra-dev` todo skipped por gating a `main`) y **4 rojos por la misma causa**:

- `deploy-dev` / `provenance` (run 33763676598): `node: command not found`. El job ejecuta `node frontend/scripts/build-identity.mjs` sin `actions/setup-node`.
- `frontend-tests` / `provenance-contract` (run 33763690752): `make check-version-parity` → `import tomllib` → `ModuleNotFoundError`. El `python3` del sistema de la VM es 3.10; `tomllib` exige 3.11.
- `rule11-ownership` (run 33763711320): `make check-rule11-ownership` → `from enum import StrEnum` → `ImportError` con `/usr/lib/python3.10`. Misma causa.
- `backend-tests` / `backend-tests-suite` (run 33763662524): la suite corrió entera en el runner (477 s, bajo el presupuesto de 540 s; `services` Postgres/Redis funcionaron) con **1 failed, 9902 passed**: `tests/properties/test_port_contract.py::test_only_the_known_methods_take_an_operational_state_directly`, `TypeError: 'function' object is not subscriptable` dentro de `annotationlib.get_annotations` de **CPython 3.14.7**. `uv sync` descargó 3.14.7 porque el 3.10 del sistema no cumple `requires-python = ">=3.12"` y nada fija el intérprete; en GitHub-hosted usa el `/usr/bin/python3` 3.12.3 del runner (run 33752586861: «Using CPython 3.12.3 interpreter at: /usr/bin/python3»). La imagen de producción es `python:3.12-slim`.

**Chosen:** declarar por job lo que `ubuntu-latest` regalaba, con los pines que el repo ya usa:

1. `backend/.python-version` = `3.12`. `uv` lo lee en `uv sync`/`uv run`; alinea CI (ambos runners) con la imagen `python:3.12-slim` y convierte en explícito el 3.12 que GitHub-hosted daba por accidente. Corrige el rojo medido en `backend-tests`; `api-contract` ya estaba verde en la primera pasada R7 (no dependía de este pin), pero el fichero alinea su resolución de `uv` de cara a futuro.
2. `deploy-dev` / `provenance`: `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4` con `node-version: "22"` tras el checkout — el mismo pin y versión que `frontend-tests.yml` y `frontend-api-contract.yml`.
3. `frontend-tests` / `provenance-contract` y `rule11-ownership`: `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0` (SHA resuelto el 2026-09-03 con `gh api repos/actions/setup-python/git/ref/tags/v7.0.0`; primera vez que el repo usa esta acción), `python-version: "3.12"`, inmediatamente antes del paso `make` que invoca `python3` a pelo. El `Makefile` no cambia: sus targets siguen siendo «host, `python3`, sin Docker» (`specs/rule11-ownership-guard.md`); el paso solo garantiza qué `python3` hay en el `PATH` del job.

**Rejected:** (B) pre-instalar Node 22 y Python 3.12 en `runner-bootstrap.sh` — es exactamente lo que D2 rechaza, y además exige re-ejecutar `RUNBOOK §6` sobre la VM viva, hoy no alcanzable desde este worktree. (C) devolver esos cuatro jobs a `ubuntu-latest` — dejaría 5 de 10 migrados y fuera precisamente la suite del backend, el mayor consumidor de minutos. (D) cambiar los targets del `Makefile` a `uv run --python 3.12 …` — mueve la corrección a la herramienta local para arreglar un síntoma de CI, y `uv` no está instalado en el host de desarrollo (`project.md`).

**Consecuencias.** R2.3 del proposal se enmienda («solo cambia el `runs-on`» → añade también el paso de tooling declarado). El panel de `sdd-review-cicd` debe leer los pasos añadidos como parte de la migración, no como cambio de lógica (R2.4 y «Out of scope» siguen intactos: no cambian qué tests corren ni qué scripts). La verificación R7 se repite para los cuatro workflows tras aplicar D11.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Runner | `infra/environments/dev/runner-bootstrap.sh` | **Sin cambios.** Las acciones de job siguen siendo la fuente de versiones. |
| Workflows (10) | `.github/workflows/api-contract.yml`, `backend-tests.yml`, `compose-ports.yml`, `deploy-dev.yml`, `demo-reset.yml`, `frontend-api-contract.yml`, `frontend-tests.yml`, `infra-dev.yml`, `multiarch-build-check.yml`, `rule11-ownership.yml` | `runs-on: ubuntu-latest` → `runs-on: [self-hosted, dev]` donde corresponda; cabecera de comentario añadida o actualizada con puntero a `docs/ci-runner-rollback.md`. |
| Runbook (nuevo) | `docs/ci-runner-rollback.md` | Crear con la estructura de D8 (6 secciones). |
| README | `README.md` | Añadir entrada "CI / runner self-hosted" que apunte al runbook (R6.2 del proposal). |
| Spec nueva | `sdd/specs/ci-runner-self-hosted.md` | Contrato del runner (qué label, qué asume, qué asume el runner al ejecutar los workflows) — se crea al archivar, no en este change. |

## Data & interfaces

- **Sin cambios de esquema**, **sin nuevos secrets/variables** (R5 del proposal), **sin nuevas API contracts**.
- **Sin cambios de variables en `.env`**: los workflows que escriben `.env` siguen haciéndolo en su workspace (`deploy-dev.yml`/`demo-reset.yml`); los demás no tocan `.env`.
- **Sin nuevas Actions**: las acciones usadas hoy (`actions/checkout@<sha>`, `astral-sh/setup-uv@<sha>`, `hashicorp/setup-terraform@<sha>`, `docker/setup-buildx-action@<sha>`, `docker/setup-qemu-action@<sha>`, `docker/login-action@<sha>`, `docker/build-push-action@<sha>`, `actions/setup-node@<sha>`) siguen siendo las mismas. Pineadas por SHA en los 9 workflows migrados; **excepción preexistente, fuera de esta migración**: `multiarch-build-check.yml` usa tags mutables (`@v3`/`@v4`/`@v6`) porque se queda en `ubuntu-latest` (D5) y este change no toca sus steps — su diff es solo la cabecera de excepción (comentario). Corregir su pinning, si se decide, es un change aparte.
- **Sin cambios de labels ni de Actions Variables**: el label `dev` ya está en el runner; `vars.GH_APP_ID`, `vars.GH_APP_INSTALLATION_ID`, etc. siguen leyéndose igual desde los workflows (R5).

## Risks & mitigations

- **Riesgo: el runner VM cae y deja todos los 10 workflows sin poder correr.**
  Mitigación: el runbook (D8 §4) explica cómo restaurar manualmente cualquier workflow a `ubuntu-latest` con un patch mínimo (un solo `git revert` del cambio). El comando es idempotente — correrlo dos veces no es destructivo.

- **Riesgo: la concurrencia de los 10 workflows sobre un solo runner (24 GB) agota memoria con un PR intenso.**
  Mitigación: cada workflow usa `concurrency.cancel-in-progress: true` por ref, lo que evita ráfagas paralelas dentro de la misma referencia. El panel `sdd-review-cicd` monitoriza el presupuesto (`backend-ci.md` ya lo hace para `backend-tests.yml`); si la suite pasa de los 6m15s por contención, queda registrado en el check. No se añaden memory limits a los jobs (el `docker buildx` del runner ya paginaría a disco).

- **Riesgo: el workspace del runner (`/opt/actions-runner/_work`) acumula artefactos y crece el disco.**
  Mitigación: `actions/checkout` por defecto limpia el árbol del job. `demo-reset.yml` usa `clean: false` (necesario, ver D3-rejected). El resto, checkout limpio. Se documenta en el runbook (D8 §6) que un rebuild de la VM recrea el runner con workspace vacío (`oci-source-id-update-replaces-boot-volume` ya advierte de que tocar la VM viva es delicado).

- **Riesgo: QEMU no se registra en binfmt y `multiarch-build-check.yml` falla tras la migración.**
  Mitigación: D5. La verificación R7 lo detecta antes de abrir el PR; si falla, se revierte solo ese workflow y se documenta en el runbook como excepción.

- **Riesgo: una nueva GitHub Action pineada por SHA asume GH-hosted (p. ej. una `runs-on:` implícita) y rompe en el runner.**
  Mitigación: las acciones en uso hoy están verificadas en runners self-hosted. Cada `bump` posterior exige `gh run list --workflow=<name> --json runner` en el PR. Documentado en runbook §5.

- **Riesgo: el `OCI_PRIVATE_KEY` queda escrito a `$RUNNER_TEMP` y un job abortado deja el fichero hasta el siguiente cleanup del runner.**
  Mitigación: `$RUNNER_TEMP` se limpia al terminar el job por el propio runner (incluso en self-hosted); `umask 077` precede al `printf` en `infra-dev.yml` (`plan` y `apply`), así el fichero nace `600` en vez de heredar el umask por defecto del proceso — corregido tras el panel de seguridad (`ci-runner-oci` review, 2026-09-03), que encontró el `printf` original sin ninguna restricción de modo. El runbook (D8 §4) advierte de que un kill -9 del runner puede dejar el fichero unos segundos.

- **Riesgo (aceptado): mover los jobs disparados por `pull_request` al mismo runner persistente que ejecuta `terraform apply` y el push a GHCR amplía el radio de confianza — código de PR ahora corre en un host cuyo instance principal puede leer, vía `read secret-bundles ... where any {target.secret.id = ...}` (`infra/environments/dev/main.tf:258`, `iam-policy.md`), los 16 secret-bundles enumerados explícitamente en esa policy — no el compartment entero: un secreto nuevo es invisible al runner hasta añadirse a la enumeración (`iam-policy.md:98`). De esos 16, los que convierten esto en escalada real (no solo lectura de config) son `oci_vault_secret.github_app_key` (clave privada de la GitHub App con `administration: write`, `design.md:5`), `jwt_secret_key` (forja JWTs de sesión) y `encryption_key` (descifra PII protegida con Fernet, `steering/security.md` regla 3); el resto (`postgres_password`, credenciales SMTP, el token del túnel Cloudflare, las claves de `media_access_key_id`) son sensibles pero no dan ese salto. El usuario del runner está además en el grupo `docker` (root-equivalent vía el socket). Antes de este change esos jobs corrían en un runner GH-hosted efímero sin ninguna credencial de OCI. `sin acceso a secretos fuera del workspace del job` (versión anterior de esta nota) era una premisa no verificada y la contradice `iam-policy.md`.**
  Mitigación: **riesgo aceptado explícitamente** (revisión con el usuario, 2026-09-03) — el repo es privado, los colaboradores con permiso de abrir PR son de confianza, y no se justifica hoy un segundo runner o una política IAM más restrictiva solo para esta migración (ver Open question 2, ya cerrada como "no en este change"). Reevaluar este riesgo si (a) se añade un secreto nuevo a la enumeración de `main.tf:258`, o (b) el repo pasa a aceptar colaboradores externos con permiso de abrir PR — cualquiera de los dos, antes de mantener el label `[self-hosted, dev]` en los workflows de `pull_request`.

- **Riesgo (aceptado): `deploy-dev` (`build-backend`, `build-frontend`, `deploy`) e `infra-dev` (`plan`, `apply`) llevan `if: github.ref == 'refs/heads/main'`, así que un `workflow_dispatch` sobre la rama del PR no los ejecuta — la evidencia R7 (`r7-evidence.md`) los registra `skipped`, no `success`. La primera ejecución runner-side real de `docker buildx`, el push a GHCR, el deploy sobre la VM viva y `terraform apply` ocurre recién con el primer push a `main` tras el merge, no "antes de merge" como enmarca R7.1.**
  Mitigación: **riesgo aceptado explícitamente** (revisión con el usuario, 2026-09-03) — forzar esos jobs ahora exigiría un `terraform apply`/deploy real contra la VM dev fuera del flujo normal de merge, un coste mayor que el que motiva este change. En su lugar, `/sdd:ship` trata el primer run de `deploy-dev` y de `infra-dev apply` sobre `main` tras el merge como un gate vigilado explícito: si `build-backend`/`build-frontend`/`deploy` o `plan`/`apply` fallan en el runner por algo que `ubuntu-latest` no habría revelado (mismo patrón que D11), el rollback documentado en `docs/ci-runner-rollback.md` se ejecuta de inmediato. `infra-dev/check` sí es `pull_request`-triggered y por tanto se verifica en el propio PR (ver nota en `r7-evidence.md`).

- **Riesgo: el `pr-review-cicd` revisa que cada `runs-on:` declarado sea uno de los valores conocidos y rechaza el runner self-hosted si no está declarado como válido.**
  Mitigación: el panel ya cubre workflows de CD; añadir el check de `[self-hosted, dev]` es trivial. No es un riesgo de la migración, pero conviene mencionarlo para que el implementador verifique que el panel acepta el label.

## Open questions

1. **QEMU en `multiarch-build-check`**: ¿asumimos que `docker/setup-qemu-action@v3` registra binfmt en el runner `ubuntu` del VM (D5), o lo verificamos en una rama de prueba antes de migrar este workflow? — **asumido**, verificación por R7; si falla, revertir.

2. **`infra-dev.yml` y `manage dynamic-groups`/`manage users`/`manage groups`**: ¿el actor IAM `svc-terraform-dev` debe seguir siendo el que ejecuta `terraform apply` (D6), o queremos explorar moverlo a instance principal del runner como optimization de seguridad? — **no en este change**; mantener `svc-terraform-dev` es la postura conservadora y no toca la policy IAM.

3. **`docs/ci-runner-rollback.md` ubicación**: ¿sección propia en `README.md` raíz o sub-página? — **sección propia en `README.md`** con enlace (D8).

4. **Concurrency del runner**: ¿añadimos una etiqueta extra para distinguir jobs pesados de los ligeros, o lo dejamos todo en `[self-hosted, dev]`? — **lo dejamos todo** (D1, D10); un segundo pool exige un segundo runner físico y el ROI no se ve todavía.

5. **Verificación**: `gh run list` por workflow contra el commit del PR es válido, ¿o conviene un `make verify-ci-runner-oci` en el repo que lo automatice? — **un script ad-hoc del PR**; si el patrón se repite en próximas migraciones, se promote a `Makefile`.

## What this design does NOT do

- **No reduce el número de gates** — el proposal lo declara y se respeta aquí.
- **No migra a `integrations/github`** — sigue siendo el change `infra-github-iac` del roadmap.
- **No añade un segundo runner físico** — un label nuevo sin segundo runner no aísla nada (D1).
- **No cambia la lógica de los workflows** (qué tests, qué versiones de actions, qué scripts) — solo cambia el runner (D3, D4).
- **No pre-instala tooling en la VM** — las acciones de job siguen siendo la fuente de versiones (D2).
