# Tasks: ci-runner-pool-oci

<!-- "hard" on a section heading escalates its implementer to the stronger model;
     "panel: PASS <date>" is written by /sdd:run when a section's review panel passes. -->

## 1. Terraform: variable `runner_count` y cableado al cloud-init

- [ ] 1.1 `infra/environments/dev/variables.tf` — añadir `variable "runner_count"` (default 2, validation 1..4). Cubre R1 (default), R6 (rango). Sin esto D2 no se puede cablear.
- [ ] 1.2 `infra/environments/dev/main.tf` — pasar `runner_count` al `templatefile()` que renderiza `cloud-init.yaml.tftpl`. Cubre R1 (cómo llega al bootstrap), R3 (reaprovisionamiento declarativo).
- [ ] 1.3 `infra/environments/dev/cloud-init.yaml.tftpl` — añadir `runner_count = ${runner_count}` como variable del template y pasarlo al `runcmd` que invoca `bootstrap-runner.sh` (`RUNNER_COUNT=<n> sudo bash /opt/bootstrap-runner.sh "$RUNNER_COUNT"`). Cubre R3.

## 2. `runner-bootstrap.sh`: pool parametrizado, migración del legado y baja con guardia de liveness <!-- hard -->

<!-- hard: la baja condicionada a `systemctl is-active` + API de jobs en vuelo, y la
     migración del legado `autohostai-dev-vm`, tienen variantes reales (orden de
     retirada, qué hacer si GitHub rechaza el registration-token a mitad del bucle). -->

- [ ] 2.1 `infra/environments/dev/runner-bootstrap.sh` — reescribir el bloque de configuración del runner como bucle `for i in $(seq 1 "$RUNNER_COUNT"); do … done` con `./config.sh --unattended --replace --url … --token … --labels "$ENV" --name "autohostai-${ENV}-vm-<i>"`, `./svc.sh install <user>`/`start` solo si `systemctl is-active` devuelve `inactive`/`failed`/`unknown`. Cubre R1 (N agentes), R2 (un usuario por agente), R3 (alta idempotente), R4 (toolchain compartido), R6 (default y rango).
- [ ] 2.2 `infra/environments/dev/runner-bootstrap.sh` — añadir fase previa al bucle que migra el legado: si `gh api ... /repos/{owner}/{repo}/actions/runners` lista un agente con nombre `autohostai-${ENV}-vm` (sin sufijo numérico), `./config.sh remove --token ... && ./svc.sh uninstall actions.runner.<org>-<repo>.autohostai-${ENV}-vm.service`. Cubre R5 (rollback a N=1 deja un único agente).
- [ ] 2.3 `infra/environments/dev/runner-bootstrap.sh` — añadir fase previa al bucle que baja agentes sobrantes cuando `RUNNER_COUNT` es menor que la lista en `/var/lib/autohostai-runner/agents.list`. Para cada sobrante: `./config.sh remove --token ... && ./svc.sh uninstall` **solo si** `systemctl is-active` devuelve `inactive`/`failed`/`unknown`; si está `active`, `set -e` aborta con un mensaje que nombre al agente y al job en vuelo (vía `gh api ... /actions/runs?status=in_progress` filtrando por `runner.name`). Cubre R3 (baja explícita), R5 (rollback).
- [ ] 2.4 `infra/environments/dev/runner-bootstrap.sh` — escribir `/var/lib/autohostai-runner/agents.list` con los nombres de los agentes numerados tras cada `./config.sh --replace`, atómico (`mv` desde un temporal). Fuente de verdad para la fase de baja (2.3). Cubre R3 (service discovery).
- [ ] 2.5 `infra/environments/dev/runner-bootstrap.sh` — capturar errores por iteración con nombre (`agent <i>/<N>: <acción>: <error>`) y dejar a los agentes 1..k-1 reconciliados si el agente k falla. Cubre R3 (reporte de error por agente).

## 3. Runbooks y README

- [ ] 3.1 `docs/ci-runner-rollback.md` — añadir sección "Subir N" (`runner_count++` en `variables.tf` o `dev.tfvars`, `terraform apply`, `sudo bash /opt/bootstrap-runner.sh "$RUNNER_COUNT"`, verificación con `gh api ... /actions/runners`). Cubre R5.
- [ ] 3.2 `docs/ci-runner-rollback.md` — añadir sección "Bajar N" (pasos inversos, con la fase de baja condicionada a `is-active == inactive`; si falla con "agente activo, jobs en vuelo: <url>", esperar a que terminen o cancelar el PR y reaplicar). Cubre R5.
- [ ] 3.3 `infra/environments/dev/RUNBOOK.md` — actualizar §6.2 para mencionar el parámetro `RUNNER_COUNT` en el comando de reaprovisionamiento y la lista esperada de `N` agentes tras reaplicar. Cubre R5.
- [ ] 3.4 `infra/environments/dev/README.md` — añadir nota sobre el rango razonable de `runner_count` (1–3 con la métrica que lo sostiene: 4 OCPU/24 GB AD-3 PAYG, app conviviendo) y la exigencia de nota de medición para `runner_count > 3`. Cubre R6.

## 4. Spec `ci-runner-self-hosted.md`: pool en lugar de runner único

- [ ] 4.1 `sdd/specs/ci-runner-self-hosted.md` — reescribir el Purpose (líneas 5–10) para hablar de **pool de N agentes** con label `dev` en lugar de runner único; añadir al final de cada sección de Requirements los SHALL que cubren R1 (N agentes), R2 (un usuario por agente), R3 (idempotencia y baja con guardia), R4 (toolchain compartido), R5 (runbook subir/bajar N) y R6 (rango y nota de medición). Cubre R1 (canonical), R5.

## 5. Verification

- [ ] 5.1 `terraform -chdir=infra/environments/dev fmt -check -recursive && terraform -chdir=infra/environments/dev validate` — formato y validación estática sin estado remoto.
- [ ] 5.2 `git diff origin/main -- .github/workflows/` — confirmar que los 10 workflows siguen declarando `runs-on: [self-hosted, dev]` y que ningún `runs-on:` ha cambiado. Cubre R1 (workflows intactos).
- [ ] 5.3 **(BLOCKED)** `terraform -chdir=infra/environments/dev apply` sobre la VM viva + reaplicar bootstrap + `gh api ... /actions/runners` muestra N entradas `autohostai-dev-vm-<i>` online + sin legado. Sin acceso a la VM desde el worktree de implementación — aplazar al gate final.
- [ ] 5.4 **(BLOCKED)** matriz de verificación (D7): `workflow_dispatch` secuencial con `sleep 60` entre cada uno de `api-contract.yml` desde la rama del PR; para cada `actions_run_id`, `gh api ... /actions/runs/<id>` devuelve un `runner.name` distinto; los N jobs acaban en `success`. Sin runners reales — aplazar al gate final.

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one. -->
