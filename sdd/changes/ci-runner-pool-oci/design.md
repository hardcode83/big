# Design: ci-runner-pool-oci

## Context

Hoy el runner de CI vive como **un único proceso** registrado contra GitHub desde `infra/environments/dev/runner-bootstrap.sh:58-66` (label `dev`, nombre `autohostai-${ENV}-vm`). El aprovisionamiento es IaC para VMs nuevas (`cloud-init.yaml.tftpl` → `runcmd` ejecuta `bootstrap-runner.sh`) y se reaplica a mano sobre la VM viva vía `RUNBOOK.md §6.2`, porque el `metadata` de la instancia es ForceNew con `ignore_changes`. Los 9 workflows `pull_request`-triggered declaran `runs-on: [self-hosted, dev]` desde `ci-runner-oci` (2026-09-04), así que cualquier coincidencia de jobs se serializa detrás del único agente. La VM es `VM.Standard.A1.Flex`, **4 OCPU / 24 GB / 200 GB / AD-3, PAYG** (ADR 0001 addendum 2026-07-21), con holgura suficiente para N=2-3 agentes además del stack `docker compose` que sirve `autohostai.digitalsec.work`.

Este change parametriza el bootstrap por `runner_count` (default 4, amend 2026-09-04) y crea N agentes en la misma VM: un usuario Linux por agente, su `actions-runner-N/` propio, su servicio systemd y su `--replace` ante GitHub — el patrón canónico de N runners en un host. Los 10 workflows no cambian; `docs/ci-runner-rollback.md` gana secciones de subir/bajar N; el reaprovisionamiento sobre la VM viva sigue `RUNBOOK.md §6.2`.

## Decisions

### D1 — Un usuario Linux por agente, no varias instancias bajo `ubuntu`

**Chosen:** cada agente corre como `actions-runner-<i>` (sufijo 1..N), añadido al grupo `docker`, con `RUNNER_HOME=/opt/actions-runner-<i>` y `_work/` propio. El servicio systemd se llama `actions.runner.<org>-<repo>.autohostai-dev-vm-<i>.service`.

Rejected: varios registros bajo el mismo usuario `ubuntu` con `_work/` separados — el `git clean -ffdx` del checkout por defecto (ci-runner-oci D3) borraría ficheros que el otro agente espera, exactamente la grieta que la enmienda 4 de `ci-runner-oci/design.md D3` cerró para `$HOME/.autohostai-dev-runtime.env`. Un usuario por agente es lo que garantiza que dos jobs no se pisan el workspace del otro.

Rejected: containers/Namespaces para aislar — innecesario: el aislamiento que el caso pide es de workspace y de servicio, no de red ni de PID. El grupo `docker` lo necesita cada agente para `docker buildx` / `docker login`.

### D2 — `runner_count` como variable de Terraform, default 4

**Chosen:** nueva `variable "runner_count"` (`type=number, default=4, validation: 1 ≤ runner_count ≤ 4`) en `infra/environments/dev/variables.tf`. El valor se inyecta al `cloud-init.yaml.tftpl` por `templatefile()` y al `runner-bootstrap.sh` por argumento (`RUNNER_COUNT=<n>` exportado en el `runcmd` o pasado al script por `sudo bash /opt/bootstrap-runner.sh "$RUNNER_COUNT"`). **Amend 2026-09-04**: default subido de 2 a 4 por decisión de producto tras observar la cola real con dos PRs simultáneos + reset nocturno; el techo 4 y la validación 1..4 se mantienen.

Rejected: leer `runner_count` de un fichero versionado en el repo — pierde la univocidad con el `terraform apply` (un `apply` con un valor distinto no tocaría la VM viva hasta el siguiente reaprovisionamiento manual). La variable de TF es la fuente.

Rejected: rango abierto (`runner_count ≥ 1` sin tope) — la VM tiene 4 OCPU y la app convive en ella; por encima de 4 la contención empieza a degradar el servicio público, que es la mitad que R6.3 vigila. El techo es operativo, no de capacidad nominal.

### D3 — Bootstrap paramétrico: alta idempotente, baja explícita

**Chosen:** `runner-bootstrap.sh` se reescribe como un bucle `for i in $(seq 1 "$RUNNER_COUNT"); do … done`. Cada iteración es **idempotente** — `./config.sh --unattended --replace` por nombre (las dos banderas son obligatorias: `--unattended` para que no abra el wizard interactivo, `--replace` para que reescriba la URL/token de un agente preexistente), y `./svc.sh install <user> && ./svc.sh start` solo si el servicio no está `active`. La verificación de liveness es por servicio (`systemctl is-active actions.runner.<org>-<repo>.autohostai-dev-vm-<i>.service`), no por presencia del unit file: un servicio instalado pero parado se reinicia (`./svc.sh start`), no se reescribe.

**Migración desde el runner único preexistente.** El bootstrap, antes del bucle, detecta si existe un agente con el nombre legado `autohostai-dev-vm` (sin sufijo numérico) en `gh api ... /repos/{owner}/{repo}/actions/runners` y, si lo encuentra, lo retira explícitamente (`./config.sh remove --token ... && ./svc.sh uninstall actions.runner.<org>-<repo>.autohostai-dev-vm.service`). Sin esa migración, una VM provisionada por `ci-runner-oci` y re-aprovisionada con `runner_count = 2` deja 3 agentes vivos (el legado + los dos numerados), y un rollback a `runner_count = 1` deja 2 (el legado + agente-1) — ambos rompen R5.2 ("`runner_count = 1` deja un único agente funcional"). El fichero `/var/lib/autohostai-runner/agents.list` (véase más abajo) se siembra con los agentes numerados 1..N; el legado, si está presente, se considera **fuera de banda** y se retira una sola vez.

**Bajar N es explícito.** Antes del bucle, una fase compara `RUNNER_COUNT` con la lista de agentes numerados del fichero `/var/lib/autohostai-runner/agents.list` y, para los que sobren, llama `./config.sh remove --token … && ./svc.sh uninstall actions.runner.<org>-<repo>.autohostai-dev-vm-<i>.service` **solo si el agente está inactivo** (`systemctl is-active` devuelve `inactive`/`failed`/`unknown`); si está activo y `RUNNER_COUNT` bajó, el script aborta con `set -e` y un mensaje que nombre al agente y al job en vuelo (sacado de `gh api ... /repos/{owner}/{repo}/actions/runs?status=in_progress` filtrado por `runner.name == autohostai-dev-vm-<i>`).

Rejected: alta y baja en una sola pasada con `--replace` global — `--replace` solo cambia el token y la URL de un agente ya existente; no retira agentes sobrantes. La baja tiene que ser código separado.

Rejected: omitir la baja y documentar que el operador la hace a mano — exactamente la clase de paso a mano que `infra.md` prohíbe para el reaprovisionamiento. Si reaplicar con N=2 deja 4 agentes vivos, el reaprovisionamiento está roto.

Rejected: baja no condicionada a `is-active == inactive` — retiraría un agente con un job en vuelo, dejando el job a medias.

### D4 — Toolchain (Docker, Compose, `oci-cli`, Python) compartido, no por agente

**Chosen:** el `cloud-init.yaml.tftpl` sigue siendo el único sitio que instala Docker/Compose/`oci-cli`/`python3-pip` (igual que hoy). El bootstrap del runner **solo** crea usuario, clona `actions-runner`, ejecuta `./config.sh --labels dev --name autohostai-dev-vm-<i>` y arranca el servicio.

Rejected: instalar tooling por agente — duplica declaración de versiones, exige reaprovisionar agentes (no la VM) para bumpear Node/Terraform, contradice `infra.md` ("prohibido configurar a mano... cualquier paso que hoy no puedas codificar debe quedar como script versionado"). La fuente de verdad del toolchain es la imagen APT de la VM, no `runner-bootstrap.sh`.

### D5 — Sin nuevos secrets ni nuevas policies IAM

**Chosen:** el reaprovisionamiento reusa el mismo installation-token de la GitHub App que hoy mintea `gh-app-install-token.py` (un token sirve para N registros). El instance principal de la VM ya tiene `secret-bundle get` por OCID y por nombre; los N agentes heredan esa capacidad porque corren como usuarios locales que invocan el script a través de `sudo` o de un binario con `setuid` mínimo — pero, más simple, **el bootstrap lo invoca `ubuntu` con `sudo`**, lee `/etc/autohostai-deploy.env` (que ya existe) y usa el mismo installation-token para los N `./config.sh`. Sin nuevas sentencias IAM, sin nuevos OCIDs en el `cloud-init`.

Rejected: dar a cada agente su propio OCID de la App o una segunda GitHub App — la App ya es de "Administración: read/write" sobre el repo y su installation-token es válido para N registros simultáneos. Multiplicar Apps es superficie de secreto sin beneficio.

Rejected: usar la `GITHUB_TOKEN` del job para registrar el runner — el registration-token de `./config.sh` es independiente del job-token (que es efímero por job); el registration-token lo mintea la App vía REST. Mezclar los dos flujos cambia el modelo de credenciales sin necesidad.

### D6 — El reaprovisionamiento sobre la VM viva no toca el `.env` ni el stack

**Chosen:** el script `runner-bootstrap.sh` solo crea/retira usuarios y servicios de runner; **no** reescribe `/etc/autohostai-deploy.env` (eso lo hace el cloud-init en VMs nuevas y queda fuera del reaprovisionamiento de runners) y **no** toca `docker compose`. El operador que reaplica el bootstrap lo hace con `sudo bash /opt/bootstrap-runner.sh "$RUNNER_COUNT"`, sin afectar al deploy ni a los contenedores.

Rejected: que el bootstrap toque el stack — el reaprovisionamiento del runner y el deploy son operaciones distintas que pueden coincidir en el tiempo (`demo-reset.yml` y `deploy-dev.yml` comparten la `concurrency.group: deploy-dev`, pero el bootstrap no entra en ese grupo). Mezclar las dos cosas acopla reaprovisionamiento a disponibilidad de la app.

### D7 — Verificación runner-side antes de mergear

**Chosen:** la sección Verification de `tasks.md` exige (a) `gh api ... /repos/{owner}/{repo}/actions/runners` listando exactamente N entradas con label `dev`, nombre `autohostai-dev-vm-<i>` para `i ∈ [1..N]`, y status `online`, **sin** la entrada legada `autohostai-dev-vm`; y (b) N jobs de `api-contract.yml` lanzados por `workflow_dispatch` desde la rama del PR, **no simultáneos**, espaciados 60s entre cada uno (la API de GitHub no permite seleccionar un runner por nombre desde `runs-on:`; solo por label). Cada job se rastrea por su `actions_run_id`; para cada uno, `gh api ... /repos/{owner}/{repo}/actions/runs/<id>` devuelve el campo `runner.name`, y la verificación acepta solo si los N jobs acabaron en `success` **y** cada uno corrió en un `runner.name` distinto (un solo job no puede agotar el pool: si todos van al agente 1, GitHub no rotará por sí mismo si los demás están `online`/`idle`, así que se inserta el `sleep 60` para que el primero termine antes de lanzar el segundo). El resultado es una matriz (job → runner.name) que prueba que GitHub repartió entre los N agentes.

Rejected: probar los N agentes con la suite del backend (6m15s) — caro y serializa la verificación a 6m por agente. Un job corto (`api-contract.yml`) ejercita checkout + OCI CLI + Docker + GitHub token, que es todo lo que el runner hace, en ~30s, y los N secuenciales caben en ~3 min.

Rejected: asumir que `runs-on: [self-hosted, dev]` con label único reparte round-robin — no lo hace; reparte por disponibilidad y orden de cola. Sin la matriz (job → runner.name) no se puede probar que los N agentes realmente corrieron jobs.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Terraform | `infra/environments/dev/variables.tf` | nueva `variable "runner_count"` (default 4, validation 1..4, **amend 2026-09-04**) |
| Terraform | `infra/environments/dev/main.tf` | pasar `runner_count` al `templatefile` de `cloud-init.yaml.tftpl` (variable `${runner_count}`) |
| IaC | `infra/environments/dev/cloud-init.yaml.tftpl` | añadir `runner_count: ${runner_count}` al `templatefile()` y pasarlo al `runcmd` que invoca `bootstrap-runner.sh` |
| IaC | `infra/environments/dev/runner-bootstrap.sh` | reescribir como bucle parametrizado: alta idempotente de `actions-runner-<i>` para `i ∈ [1..runner_count]`; baja explícita de agentes sobrantes antes del bucle si `runner_count` baja |
| Spec | `sdd/specs/ci-runner-self-hosted.md` | reescribir el Purpose (líneas 5-10) y los Requirements para hablar de **pool** de N agentes; añadir SHALL de R1/R2/R3/R4/R5/R6 |
| Runbook | `docs/ci-runner-rollback.md` | añadir secciones "Subir N" y "Bajar N" (R5.1) |
| Runbook | `infra/environments/dev/RUNBOOK.md` | actualizar §6.2 con el parámetro `runner_count` y la lista esperada de N agentes |
| README | `infra/environments/dev/README.md` | nota sobre rango razonable de `runner_count` y la métrica que lo sostiene (R6.1) |

## Data & interfaces

**Sin cambios de esquema, sin cambios de API, sin cambios de contrato.** La superficie hacia GitHub Actions es idéntica: `runs-on: [self-hosted, dev]` resuelve igual con 1 o N agentes. La superficie hacia Terraform es nueva: `var.runner_count` (entero, 1..4, default 4, **amend 2026-09-04**). La superficie hacia la VM es nueva: `/etc/systemd/system/actions.runner.<org>-<repo>.autohostai-dev-vm-<i>.service` para cada `i`.

## Risks & mitigations

- **Superficie de confianza ampliada (Docker socket, instance principal, `.env` persistente).** Cada agente corre como un usuario Linux local con grupo `docker` (root-equivalente sobre el socket, como ya documenta el riesgo aceptado de `ci-runner-oci/design.md` §D3), y los N usuarios pueden leer `$HOME/.autohostai-dev-runtime.env` (mismo grupo `docker`, mismo `chmod 600` que el deploy escribe). El número de **principales con acceso al socket de Docker y al instance principal del runner** pasa de 1 (`ubuntu`) a N (`actions-runner-<1..N>`). Esto **no es un cambio cualitativo** — el riesgo ya estaba aceptado en `ci-runner-oci` y este change lo extiende en número, no en naturaleza — pero queda explícito en este design para que el próximo archivado no lo redescubra: el radio sigue siendo el de un repo privado con colaboradores de confianza, y la mitigación estructural (pool dedicado a `pull_request`) sigue siendo el mismo trade-off ya rechazado en `ci-runner-oci` (cuesta un runner adicional para una superficie que no lo exige).
- **Contención CPU con la app.** N agentes corriendo jobs pesados (suite del backend, build multiarch) sobre una VM de 4 OCPU/24 GB puede degradar la latencia del frontend público. Mitigación: R6.3 (amend 2026-09-04) exige una nota de medición (tiempo de suite del backend con otro agente corriendo la del frontend en paralelo + latencia p50 del frontend público) antes de aceptar `runner_count > default` (= `> 4`). La métrica se archiva en `RUNBOOK.md §6.2`.
- **Workspace contention entre agentes.** La fase de baja (D3) **aborta con `set -e`** si algún agente a retirar está `active` o tiene jobs `in_progress` (consulta `gh api ... /repos/{owner}/{repo}/actions/runs?status=in_progress` filtrando por `runner.name`). El operador ve el nombre del agente, el run URL y la instrucción de esperar a que termine (o cancelar el PR) antes de reaplicar. **No hay banner + sleep** (la versión anterior dependía de Ctrl-C, que es consola interactiva y choca con la norma IaC-first de `infra.md`).
- **Service discovery de agentes sobrantes.** Detectar cuántos agentes existen hoy en la VM viva requiere parsear systemd o leer un fichero de estado; las dos son frágiles ante una VM provisionada parcialmente. Mitigación: el bootstrap escribe `/var/lib/autohostai-runner/agents.list` con los nombres registrados, atómico (`mv` desde un temporal), y la fase de baja lo lee como fuente de verdad. La **migración del legado** (D3) detecta `autohostai-dev-vm` por nombre en el output de `gh api ... /repos/{owner}/{repo}/actions/runners` y lo retira una vez antes de empezar el bucle.
- **Idempotencia de la baja.** `./config.sh remove --token ...` requiere un token fresco (vive 1h). Mitigación: el bootstrap lo mintea al vuelo con la misma GitHub App (mismo `gh-app-install-token.py`); el token no se loguea.
- **Rotación de la App / pérdida de credenciales.** Si la clave de la App se rota y `runner-bootstrap.sh` corre sin haber reescrito `/etc/autohostai-deploy.env`, el minteo del installation-token falla y los N `./config.sh` fallan con el mismo error. Mitigación: el script falla rápido (`set -e`) en la primera iteración, **nombra al agente que ha fallado** (`agent <i> of N: <gh error>`), y deja los agentes existentes intactos; el operador arregla `/etc/autohostai-deploy.env` (procedimiento ya documentado en `RUNBOOK.md §6.2`) y reaplica.
- **Reporte de error por agente.** Cada iteración del bucle atrapa su propio error con nombre del agente (`agent <i>/<N>: <acción>: <error>`); un fallo en el agente `k` **no detiene el bucle**: los agentes `1..k-1` quedan reconciliados y el bucle sigue intentando `k+1..N` en sus propias subshells aisladas, en vez de abortar en el primer fallo (**corrección 2026-09-04, panel de `/sdd:review`, `sdd-qa`**: la redacción original decía que `k+1..N` quedaban "sin tocar", pero el código siempre los intenta — la afirmación era falsa y contradecía la propia filosofía de la Fase 1, que recolecta todos los bloqueados en una sola pasada en vez de abortar en el primero). El operador ve un informe completo (qué agentes quedaron bien, cuáles fallaron y por qué) en una sola ejecución, y reaplica solo con la fix del error — no tiene que empezar de cero ni reaplicar N veces.

## Open questions

Ninguna que bloquee el `/sdd:tasks`. La decisión de `runner_count = 4` como default y el rango 1..4 son del operador y se revisan en cada reaprovisionamiento; la nota de medición para `runner_count > default` (R6.3 amend 2026-09-04) es la única decisión que requiere datos del entorno desplegado, y se hace **antes** de aceptar el cambio, no durante.
