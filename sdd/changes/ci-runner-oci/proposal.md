# Proposal: ci-runner-oci

## Why

El runner self-hosted con labels `[self-hosted, dev]` lleva corriendo en la VM de Oracle desde `app-deploy-dev` (2026-07-29) y hoy solo lo aprovechan dos workflows: el job `deploy` de `deploy-dev.yml` y el `demo-reset.yml` nocturno. Los otros **ocho** workflows y los tres jobs `ubuntu-latest` que aún viven dentro de `deploy-dev.yml` siguen consumiendo minutos de GitHub-hosted en cada push/PR. El presupuesto del repo se está yendo en eso (gates de suite del backend ~7m, suite del frontend, plan/apply de Terraform, contrato de API, multiarch check, etc.), y `infra.md` ya consagra que **toda** la ejecución de CI corre en herramientas declaradas — el runner ya existe, solo falta adoptarlo.

Este change adopta el runner para los 10 workflows (incluidos los builds de `deploy-dev` y el `multiarch-build-check`, sujeto a la salvedad de QEMU del R4), deja documentado un procedimiento de rollback versionado (`git revert` + runbook en `docs/`) para cuando se quiera volver a GitHub-hosted, y no adelgaza gates: eso queda para "otras fases" como el propio pidió.

**ASSUMPTION** (a confirmar en `/sdd:design`): el runner VM (`[self-hosted, dev]`, 4 OCPU/24 GB/200 GB AD-3) tiene instalados `docker buildx`, `docker login` vía la GitHub App, `terraform` con el provider `integrations/github` y `qemu-user-static` (al menos el binario, si no se monta). Si la auditoría lo desmiente, R3 y R4 marcan el camino de vuelta: esos jobs a `ubuntu-latest` y documentado en el runbook.

## What changes

Cada uno de los 10 workflows bajo `.github/workflows/` declara el runner `[self-hosted, dev]` en todos sus jobs, cesando el consumo de minutos GitHub-hosted para la CI del proyecto (R1). Las definiciones de `concurrency`/`on.paths`/`on.pull_request.branches` se preservan exactas (R2) para que el comportamiento de merge/PR siga siendo idéntico. Los jobs que dependían de tooling preinstalado en `ubuntu-latest` sin declararlo lo declaran ahora por job (`backend/.python-version`, `actions/setup-node`, `actions/setup-python`; R2.3 y design D11) — la verificación R7 del 2026-09-03 los dejó en rojo en el runner y ese fue el único fallo de la migración. Los jobs de build de `deploy-dev.yml` también migran; `demo-reset.yml` se queda como está (R1 punto de partida). `multiarch-build-check.yml` migra salvo que su camino QEMU no sea viable en la VM — si no lo es, el workflow queda en `ubuntu-latest` y el runbook lo declara (R4). Las credenciales se siguen leyendo de OCI Vault y de Actions secrets/variables sin nuevos secretos (R5). Se añade `docs/ci-runner-rollback.md` como runbook versionado: enumera los workflows migrados, sus `runs-on` previos, el SHA del commit de la migración y los pasos de `git revert` + verificación; el rollback operativo es `git revert` del PR (R6). Antes de mergear, cada workflow ha corrido al menos una vez verde en el runner (R7).

## Requirements

### R1 — Runner self-hosted para los 10 workflows

**As a** mantenedor del repo, **I want** que los 10 workflows bajo `.github/workflows/` ejecuten sus jobs en `runs-on: [self-hosted, dev]`, **so that** el proyecto no consuma minutos de GitHub-hosted y el runner VM existente rinda a su capacidad.

Acceptance criteria:

1. WHEN se dispare cualquiera de los 10 workflows (`api-contract.yml`, `backend-tests.yml`, `compose-ports.yml`, `demo-reset.yml`, `deploy-dev.yml`, `frontend-api-contract.yml`, `frontend-tests.yml`, `infra-dev.yml`, `multiarch-build-check.yml`, `rule11-ownership.yml`), THE SYSTEM SHALL ejecutar cada job migrable en `runs-on: [self-hosted, dev]` (o `[self-hosted, dev, <label>]` cuando añada labels de pool específicos — p. ej. `[self-hosted, dev, buildx]` si se demuestra que el aislamiento ayuda).
2. THE SYSTEM SHALL NOT mantener ningún job `runs-on: ubuntu-latest` en los workflows migrados, salvo la salvedad explícita de R4.
3. `demo-reset.yml` permanece en `[self-hosted, dev]` como hoy — la migración lo confirma y no lo altera (es nuestro caso base de "ya estaba").

### R2 — Concurrencia y disparadores preservados

**As a** revisor de PR, **I want** que el comportamiento de merge (dedupe, cancel-in-progress, paths filter, branches filter) sea idéntico al actual tras la migración, **so that** ni los tiempos de espera ni el tráfico de jobs cambien por el cambio de runner.

Acceptance criteria:

1. WHEN un workflow migra, THE SYSTEM SHALL preservar sus `concurrency.group` y `concurrency.cancel-in-progress` exactos.
2. WHEN un workflow migra, THE SYSTEM SHALL preservar sus `on.push.branches`, `on.push.paths`, `on.pull_request.branches` y `on.pull_request.paths` exactos.
3. WHEN un workflow migra, THE SYSTEM SHALL preservar sus `permissions`, `timeout-minutes`, `env` y `concurrency` exactos a nivel de job. Solo cambia el `runs-on` y, WHERE el job usaba tooling que `ubuntu-latest` preinstala sin declararlo (`node`, un `python3` ≥ 3.12), THE SYSTEM SHALL añadir el paso que lo declara con el mismo pin que ya usa el repo (design D11, enmienda del 2026-09-03 tras la verificación R7). WHERE el job escribe una credencial a fichero en el runner (`infra-dev.yml`: `OCI_PRIVATE_KEY`), THE SYSTEM SHALL preceder la escritura con `umask 077` (enmienda del 2026-09-03 tras el panel de seguridad de `/sdd:review`, ver `design.md` Risks & mitigations — el `printf` original no restringía el modo del fichero en el runner persistente). Ninguno de los dos pasos altera qué tests corren ni qué scripts se ejecutan.
4. THE SYSTEM SHALL NOT añadir `paths` filtros que hoy no existan para "saltarse" jobs en migrar.

### R3 — Builds de imágenes en `deploy-dev.yml` migran al runner

**As a** operador de CD, **I want** que los jobs `provenance`, `build-backend` y `build-frontend` (hoy `ubuntu-latest`) corran también en el runner, **so that** el CD completo (build + push GHCR + deploy) viva dentro del runner sin que ningún minuto pague GH.

Acceptance criteria:

1. WHEN el runner VM tiene `docker buildx` con `docker-container` driver y la credencial de GHCR ya inyectada (por la GitHub App del runner, ver `specs/app-deploy-dev.md`), THE SYSTEM SHALL ejecutar `provenance`, `build-backend` y `build-frontend` en `runs-on: [self-hosted, dev]` con `docker/setup-buildx-action` y `docker/login-action` equivalentes.
2. WHEN el job `deploy` cambia de runner a `[self-hosted, dev]`, THE SYSTEM SHALL publicar las imágenes `prod` de backend y frontend en GHCR desde la VM con los tags por SHA y `dev` exactamente iguales a los de hoy.
3. THE SYSTEM SHALL NOT añadir un Actions secret `GHCR_TOKEN` ni equivalente: la autenticación con GHCR es la que la GitHub App del runner ya provee.
4. IF la suite demuestra que `docker buildx` o el `docker/login-action` fallan en la VM, THEN THE SYSTEM SHALL marcar R3 como **bloqueado** en `tasks.md` y posponer los jobs de build — el PR no abre hasta que el runner tenga el toolchain o se decida conservarlos en `ubuntu-latest`. **El IF nunca se ejercitó antes de mergear** (enmienda del 2026-09-03, `sdd-qa` octava pasada, mismo patrón que R4.2): `build-backend`/`build-frontend` llevan `if: github.ref == 'refs/heads/main'`, así que ambos quedan `skipped` en las dos pasadas de R7 (`r7-evidence.md`) — solo `provenance` (que no invoca `buildx`/`login-action`) corrió verde en el runner. R3.1/R3.2 no están verificados runner-side antes de mergear; es el mismo riesgo aceptado que R7.1 ya nombra para estos dos jobs, repetido aquí para que no haga falta leer R7 para saberlo desde R3.

### R4 — `multiarch-build-check.yml` con salvedad de QEMU

**As a** mantenedor de los Dockerfiles, **I want** que la verificación multiarch siga protegiendo los Dockerfiles de backend y frontend, **so that** un cambio de base image no rompa la imagen de producción en silencio.

Acceptance criteria:

1. WHEN se migra `multiarch-build-check.yml`, THE SYSTEM SHALL ejecutarlo en `runs-on: [self-hosted, dev]` si el runner VM tiene QEMU (`qemu-user-static` y registro `binfmt`) y `docker buildx` con `platforms: linux/arm64,linux/amd64` funciona.
2. IF QEMU no está disponible en la VM (verificable con `docker buildx build --platform linux/amd64` fallando en una imagen trivial), THEN THE SYSTEM SHALL mantener `multiarch-build-check.yml` en `runs-on: ubuntu-latest` y documentar la excepción como "9 de 10 migrados, 1 excepción deliberada" en `docs/ci-runner-rollback.md`. **El IF nunca se ejercitó** (enmienda del 2026-09-03, `sdd-qa` sexta pasada): el probe de la tarea 1.2 no llegó a correr (VM IP no reachable desde el worktree), así que el fallback a `ubuntu-latest` se adoptó sin demostrar que QEMU falla — el resultado (`ubuntu-latest`, "9 de 10... 1 excepción deliberada") coincide con lo que el THEN pide, pero por una razón distinta a la que el IF describe. Ver `STATE.md.qemu_verification` (mientras existió) y `tasks.md` §1.2/§9.17 para el detalle; misma naturaleza que la enmienda ya hecha en R4.3.
3. THE SYSTEM SHALL NOT ejecutar la emulación QEMU en el runner si la verificación nativa `linux/arm64` (la plataforma real de la VM y del CD) ya cubre lo que la protección busca — un QEMU que valida arm64 sobre amd64 no añade garantía real. ASSUMPTION (a confirmar en design): la verificación nativa arm64 es suficiente para los Dockerfiles actuales; si las imágenes finales se usan en otra arquitectura en staging/prod, este requisito se reabre. **Cerrada como moot, no confirmada** (enmienda del 2026-09-03, `sdd-qa` review): el fallback de R4.2/D5 se activó y `multiarch-build-check.yml` nunca se migró, así que esta rama de R4.3 no llegó a ejercitarse en este change — la ASSUMPTION sigue abierta para el día que un follow-up migre ese workflow (ver `tasks.md` §6 y §9).

### R5 — Secretos y credenciales sin cambios de nombre ni de valor

**As a** operador de secretos, **I want** que los secretos que ya funcionan para los workflows sigan siendo los mismos (Actions secrets/variables + OCI Vault), **so that** la migración no introduzca un nuevo radio de exposición ni un nuevo flujo de provisioning.

Acceptance criteria:

1. WHEN un workflow corre en el runner, THE SYSTEM SHALL leer sus secretos (`OCI_*`, variables TF_VAR_*, `GITHUB_TOKEN`, app credentials si las hubiera) del mismo `Actions secrets`/`Actions variables`/Vault que hoy.
2. THE SYSTEM SHALL NOT crear nuevos `secrets.*` ni `vars.*` para satisfacer la migración.
3. WHERE `infra-dev.yml` lee credenciales de OCI para `terraform plan`/`apply`, THE SYSTEM SHALL seguir usando el OIDC / federated token que el runner o el secret hoy ya exponen — sin un `OCI_API_KEY` nuevo en GitHub.

### R6 — Runbook versionado de rollback

**As a** operador al que se le rompe el runner VM, **I want** un procedimiento de rollback versionado en el repo, **so that** volver a `ubuntu-latest` cuando haga falta sea un comando de git, no una operación de consola.

Acceptance criteria:

1. THE SYSTEM SHALL incluir el fichero `docs/ci-runner-rollback.md` con: (a) la tabla de los 10 workflows y su `runs-on` previo y posterior a la migración; (b) el SHA del commit de migración; (c) el comando exacto `git revert <sha>` o `git revert -m 1 <merge-sha>` si el PR fue merge commit; (d) cómo restaurar manualmente un workflow a `runs-on: ubuntu-latest` cuando `git revert` no basta (runner VM caída); (e) los pasos de validación que demuestran que el rollback devuelve el proyecto a la línea base de CI previa.
2. THE SYSTEM SHALL enlazar el runbook desde el `README.md` raíz (sección "CI / runner self-hosted") y desde el comentario inicial de cada workflow migrado (cabecera del fichero `.yml`), de forma que abra desde la consola de GitHub.
3. THE SYSTEM SHALL mantener el runbook sincronizado con la realidad del repo en cada archive posterior que toque `runs-on:`: `pr-review-cicd` debe verificar la coherencia. **Sin implementar en este change** (enmienda del 2026-09-03, `sdd-qa` sexta pasada): `.claude/agents/sdd-review-cicd.md` no tiene hoy ningún chequeo de coherencia `runs-on:`/runbook — el mecanismo de enforcement que este criterio promete no existe todavía en el repo. Queda como trabajo futuro (un follow-up que amplíe el reviewer `sdd-review-cicd`), no como algo que este change entrega; hasta entonces la sincronización depende de que cada `/sdd:archive` posterior lo haga a mano.

### R7 — Verificación de la migración antes de merge

**As a** revisor del PR, **I want** evidencia de que cada workflow migrado corre verde en el runner, **so that** la migración no llegue a `main` con un workflow que pasa en GH-hosted pero falla en el runner.

Acceptance criteria:

1. WHEN el PR de la migración se abre, THE SYSTEM SHALL incluir un run verde por cada uno de los workflows migrados en el runner (adjunto del PR o `gh run list --workflow=<name>` en la descripción). `workflow_dispatch` se usa cuando el workflow no se dispara solo en push. WHERE un job lleva `if: github.ref == 'refs/heads/main'` (`deploy-dev`: `build-backend`, `build-frontend`, `deploy`; `infra-dev`: `plan`, `apply`), THE SYSTEM SHALL NOT poder cumplir este criterio antes de mergear — ni un `workflow_dispatch` sobre la rama del PR los alcanza (enmienda del 2026-09-03 tras el panel de seguridad/qa de `/sdd:review`, ver `design.md` Risks & mitigations). WHERE un job es `pull_request`-triggered pero su `paths` filter no matchea el diff de *este* PR de migración (`infra-dev`: `check`, filtrado a `infra/environments/dev/**`, que este PR no toca), THE SYSTEM SHALL NOT poder cumplir este criterio tampoco — GitHub no lo dispara en absoluto sobre este PR (enmienda del 2026-09-03, `sdd-qa` review, tercera pasada). Para esos 6 jobs (los 5 gateados a `main` + `infra-dev/check`), la primera evidencia runner-side real llega con el primer run que sí los dispare (el primer push a `main` tras el merge para los 5; el primer PR futuro que toque `infra/environments/dev/**` para `check`), y `/sdd:ship`/el operador lo tratan como gate vigilado explícito (rollback inmediato si fallan por algo que `ubuntu-latest` no habría revelado).
2. WHEN el runner VM está caído durante la verificación, THE SYSTEM SHALL abortar la apertura del PR y notificarlo en `STATE.md` `BLOCKED.md` — no se abre con runs parciales.
3. THE SYSTEM SHALL NOT abrir el PR basándose solo en checks de GH-hosted; cada check debe ser su contraparte runner-side, salvo los 6 jobs de R7.1 sin evidencia posible antes de mergear.

## Out of scope

- **Reducir el número de gates** (lo que el usuario llama "los adelgazare en otras fases"): este change solo cambia el runner, no añade ni quita workflows. Las conversaciones sobre cuántos gates son demasiados van en sus propios changes.
- **Adoptar el provider `integrations/github`** para IaC de GitHub-side: ese es el change `infra-github-iac` ya en el roadmap (`sdd/roadmap.md`). Si la migración introduce un paso codificable con `integrations/github` (p. ej. el label del runner, los Secrets/Variables que él lee), queda como *candidato* a extraer a `infra-github-iac`, no como requisito de este change.
- **Añadir un segundo pool de runners** (p. ej. `[self-hosted, buildx]` o `[self-hosted, terraform]`): si una etiqueta extra ayuda al aislamiento, R1.1 lo permite como decisión por workflow, pero crear un segundo runner físico queda fuera.
- **Cambios en la lógica de los workflows** (qué tests corren, qué versiones, qué `actions/checkout@vX`): solo cambia el `runs-on`. Los bumps de versiones son cambios aparte. **Excepción autorizada, `deploy-dev.yml`/`demo-reset.yml`** (enmienda del 2026-09-03, `sdd-security` sexta pasada, con el usuario): la migración en sí rompía el mecanismo por el que `demo-reset.yml` lee el `.env` de `deploy` (compartir workspace con 7 workflows `pull_request`-triggered más hace que el checkout por defecto de cualquiera de ellos lo borre) — no un caso de "cambiar lógica porque conviene", sino de arreglar una rotura que la propia migración introducía. Ver R2.3 y `design.md` D3 (enmienda 4) / Risks & mitigations.
- **Multi-región / multi-runner**: hoy hay un runner; añadir redundancia geográfica es otro change.

## Affected specs

- `sdd/specs/app-deploy-dev.md` — el `.yml` cambia; la salida y el orden de los pasos puede variar al ejecutarse en la VM (verificación: idempotencia del `docker compose pull && up -d`). **`app-deploy-dev.md:88-91`** tiene un SHALL de `checkout` con `clean: false` y su rationale (el `.env` sin versionar vive en el workspace compartido) — ambos falsos tras la enmienda 4 de `design.md` D3 (sexta pasada de `sdd-security`): el checkout vuelve al default y el `.env` vive en `$HOME/.autohostai-dev-runtime.env`. Archivar debe reescribir ese SHALL, no dejarlo describiendo el mecanismo viejo (hallazgo `sdd-review-cicd`, séptima pasada).
- `sdd/specs/infra-dev-terraform.md` — `infra-dev.yml` cambia de runner; el job `apply` que tocaba recursos reales sigue necesitando el mismo `terraform apply` y los mismos `TF_VAR_*`.
- `sdd/specs/backend-ci.md` — `backend-tests.yml` cambia. Reglas EARS de `paths_filter`/`backend/**` no se tocan, pero **§"Coste"** (`backend-ci.md:174-178`) justifica `pytest -n 2` con "el runner tiene 2 vCPU, no 4" — falso tras la migración (VM `[self-hosted, dev]`, 4 OCPU compartidas entre 9 workflows): archivar debe o re-medir `-n` en el runner real o marcar la cifra como pendiente de re-medición (hallazgo `sdd-review-cicd`, tercera pasada).
- `sdd/specs/frontend-ci.md` — `frontend-tests.yml`, `frontend-api-contract.yml`, `api-contract.yml` cambian de runner. **§"Entorno e instalación reproducible"** (`frontend-ci.md:25`) tiene un SHALL literal de `runs-on: ubuntu-latest`: archivar debe reescribirlo a `[self-hosted, dev]` con puntero al runbook, no dejarlo describiendo el runner viejo (hallazgo `sdd-review-cicd`, tercera pasada).
- `sdd/specs/local-environment.md` — `compose-ports.yml` cambia.
- `sdd/specs/rule11-ownership-guard.md` — `rule11-ownership.yml` cambia. Su rationale (`rule11-ownership-guard.md:78-83`) dice "CI no está afectado: `ubuntu-latest` trae 3.12" — falso tras D11 (el runner trae `python3` 3.10 del sistema; CI cumple ahora por el `actions/setup-python` explícito, no por el runner base): archivar debe corregir esa cláusula (hallazgo `sdd-review-cicd`, tercera pasada).
- *(no existe aún — se creará al archivar)* `sdd/specs/ci-runner-self-hosted.md`: contrato del runner (qué tiene instalado, qué label acepta, cómo se reunextiende si se rompe) y lista de los 10 workflows que lo consumen.

## Outside-the-proposal

- `docs/ci-runner-rollback.md` vive fuera de `sdd/specs/` (es un runbook operativo, no una spec de contrato).
- `README.md` raíz debe enlazar al runbook desde la sección "Infra / CI".
