# Proposal: ci-runner-pool-oci

## Why

El runner self-hosted con label `[self-hosted, dev]` (`infra/environments/dev/runner-bootstrap.sh:58-66`) lleva una sola instancia desde `ci-runner-oci` (2026-09-04). Los 9 workflows `pull_request`-triggered declaran `runs-on: [self-hosted, dev]`, así que cuando coinciden dos jobs (un PR + un push a `main`, dos PRs, el reset programado y un PR) el segundo **se serializa** detrás del primero en la cola de GitHub Actions: la suite del backend mide 6m15s y la del frontend ~3m, así que dos PRs simultáneos son ~10m por PR en vez de correr en paralelo. El ahorro de minutos GitHub-hosted que `ci-runner-oci` cerró se paga con esperas serializadas que un pool de N agentes evita.

## What changes

`infra/environments/dev/runner-bootstrap.sh` se parametriza por `runner_count` (default 4, amend 2026-09-04) y crea N agentes en la misma VM: un usuario Linux por agente, su `actions-runner-N/` propio, su servicio systemd y su registro ante GitHub con label `dev` — el patrón canónico de N runners en un host. Los 10 workflows no cambian (`runs-on: [self-hosted, dev]` ya los matchea a todos); `docs/ci-runner-rollback.md` gana sección "subir/bajar N"; reaprovisionar la VM viva sigue el `RUNBOOK.md §6` que `ci-runner-oci` ya documentó.

## Requirements

### R1 — Pool de N agentes con label `dev`

**As a** mantenedor con PRs simultáneos, **I want** que el runner de OCI exponga N agentes registrados con label `dev`, **so that** GitHub Actions reparta los jobs en paralelo y la cola no se serialice.

Acceptance criteria:

1. WHERE `runner_count = N`, THE SYSTEM SHALL registrar exactamente N agentes en GitHub con label `dev` y nombre `autohostai-dev-vm-<i>` para `i ∈ [1..N]`, todos en la misma VM.
2. WHEN dos jobs `pull_request`-triggered coinciden con label `[self-hosted, dev]`, THE SYSTEM SHALL permitir que GitHub los asigne a dos agentes distintos y corran en paralelo, sujeto a la holgura CPU/memoria de la VM (ver R6).
3. THE SYSTEM SHALL NOT introducir un label nuevo (`[self-hosted, dev, buildx]`, `[self-hosted, dev, terraform]`, etc.): el particionado es por capacidad física, no por dominio de trabajo.

### R2 — Aislamiento por usuario Linux y servicio systemd

**As a** operador del runner, **I want** que cada agente corra bajo su propio usuario Linux con su propio `_work/` y su propio servicio systemd, **so that** dos jobs no se pisen el `git clean -ffdx` del checkout del otro y se preserve el aislamiento de `$HOME/.autohostai-dev-runtime.env` (enmienda 4 de `ci-runner-oci/design.md D3`).

Acceptance criteria:

1. THE SYSTEM SHALL crear un usuario Linux por agente (`actions-runner-1`/`actions-runner-2`/...), añadido al grupo `docker` (igual que hoy `ubuntu`), con `RUNNER_HOME=/opt/actions-runner-<i>`.
2. THE SYSTEM SHALL instalar `actions-runner` en cada `RUNNER_HOME` y registrarlo con `./svc.sh install <user> && ./svc.sh start`, generando el servicio systemd `actions.runner.<org>-<repo>.autohostai-dev-vm-<i>.service`.
3. THE SYSTEM SHALL ejecutar el `./config.sh` de cada agente con `--unattended --replace` para que reaprovisionar la VM viva sea idempotente.

### R3 — Reaprovisionamiento declarativo e idempotente

**As a** operador al que se le rompe un agente, **I want** reaplicar el bootstrap sobre la VM viva con un único comando y ver N agentes funcionando, **so that** el reaprovisionamiento no exija manipular a mano cada `./config.sh`.

Acceptance criteria:

1. WHEN el operador reaplica `runner-bootstrap.sh` sobre la VM viva (procedimiento documentado en `RUNBOOK.md §6`), THE SYSTEM SHALL crear los agentes que falten para alcanzar `runner_count` y SHALL NOT tocar los que ya están registrados correctamente (`./config.sh --replace` por nombre es idempotente).
2. WHEN `runner_count` baja entre reaprovisionamientos, THE SYSTEM SHALL dar de baja explícitamente los agentes sobrantes (`./config.sh remove --token ... && ./svc.sh uninstall`), y el reaprovisionamiento SHALL NOT recolectar automáticamente (lo opuesto a `--replace` no es recuperable de un fallo).
3. THE SYSTEM SHALL fallar el reaprovisionamiento con un mensaje que nombre al agente si GitHub rechaza el registro (credenciales, rate limit, etc.), sin dejar el estado a medias.

### R4 — Tooling compartido, no duplicado por agente

**As a** mantenedor de la VM, **I want** que Docker, Compose, `oci-cli` y Python del sistema los instale el cloud-init **una vez por VM**, **so that** cambiar una versión de toolchain siga siendo reaprovisionar la VM y no reaplicar el bootstrap del runner.

Acceptance criteria:

1. THE SYSTEM SHALL instalar Docker/Compose/`oci-cli`/Python del sistema en el `cloud-init.yaml.tftpl` (igual que hoy) y SHALL NOT duplicarlos por agente.
2. THE SYSTEM SHALL declarar en `infra/environments/dev/runner-bootstrap.sh` solo los pasos que varían por agente: alta de usuario, descarga/instalación de `actions-runner-<i>` en `$RUNNER_HOME`, `./config.sh --labels dev --name autohostai-dev-vm-<i>`, `./svc.sh install <user> && ./svc.sh start`.

### R5 — Runbook con subir N, bajar N y rollback al runner único

**As a** operador, **I want** un procedimiento versionado para cambiar `runner_count` y volver al runner único, **so that** ni subir ni bajar N exija conocimientos tácitos del runner ni git surgery.

Acceptance criteria:

1. THE SYSTEM SHALL ampliar `docs/ci-runner-rollback.md` con dos secciones: "Subir N" (`runner_count++` + reaprovisionar, sin parar la app) y "Bajar N" (lista explícita de agentes a retirar por nombre + reaprovisionar, con verificación previa de que ningún job en vuelo usa los agentes a retirar).
2. THE SYSTEM SHALL mantener `runner_count = 1` como estado de rollback válido: reaprovisionar con N=1 deja un único agente funcional, idéntico al estado post-`ci-runner-oci`.
3. THE SYSTEM SHALL actualizar `infra/environments/dev/RUNBOOK.md §6` para que el procedimiento de reaprovisionamiento mencione el parámetro `runner_count` y la lista de agentes que el operador debe esperar ver.

### R6 — Holgura CPU/memoria de la VM y contención con la app

**As a** operador, **I want** saber hasta qué `runner_count` la VM aguanta sin que la app desplegada (docker-compose de deploy) sufra, **so that** subir N no degrade el servicio público `autohostai.digitalsec.work`.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en `infra/environments/dev/README.md` el rango razonable de `runner_count` (1–4) con la métrica observada que lo sostiene: VM `VM.Standard.A1.Flex`, 4 OCPU/24 GB/200 GB, AD-3, PAYG (ADR 0001 addendum 2026-07-21). **Amend 2026-09-04**: el rango original era 1-3 con default 2; al subir el default a 4 el rango razonable se alinea con el `validation 1..4` de la variable. La nota de medición (R6.3) opera sobre `> default`, no sobre el rango entero.
2. THE SYSTEM SHALL fijar `runner_count = 4` como default y SHALL NOT auto-escalar: subir N es decisión del operador, no del runner. **Amend 2026-09-04**: el default original era 2 (cola asumida de dos jobs coincidentes); la observación real tras dos PRs simultáneos + reset nocturno dejó la cola al límite, y la decisión de producto es absorber con cuatro agentes sin nota de medición previa.
3. WHERE el operador quiera subir `runner_count > 4`, THE SYSTEM SHALL exigir una nota de medición explícita (tiempo de suite del backend cuando otro agente corre la del frontend en paralelo, latencia p50 del frontend público) que archive en `RUNBOOK.md §6` antes de aceptar el cambio. **Amend 2026-09-04**: el umbral original (>3) pasaba a un default de 4 sin nota de medición previa; el cambio lo deja en `> default`, que es la única cota con sentido (la nota se exige al subir sobre el valor que ya asumimos validado).

## Out of scope

- **Segunda VM** con su propio `runner_count`: si la contención con N=3 resulta intolerable, esta entrada se reabre como "pool multi-VM"; `runs-on:` no cambiaría.
- **Adoptir el provider `integrations/github`** de Terraform para gestionar el registro de los N agentes (candidato `infra-github-iac`).
- **Adelgazar gates** (workflows que no se traducen en señal) — quedó fuera de `ci-runner-oci` y sigue fuera.
- **Reescribir workflows** para que ejecuten en pools con labels distintos (`[self-hosted, dev, buildx]`, etc.). El particionado es por número de agentes, no por dominio.
- **Métricas automáticas de uso de runner** (jobs en cola, tiempo de espera por PR). Es un candidato aparte si la observabilidad demuestra que la cola vuelve a doler.

## Affected specs

- `sdd/specs/ci-runner-self-hosted.md` — añadir al Purpose y a los Requirements: "el runner es un **pool** de N agentes registrados con label `dev`, no un único proceso" y los SHALL de R1/R2/R3/R4/R5/R6. Hoy la spec describe un runner único (líneas 5-10 y 116); archivar debe reescribir ese punto.
- `docs/ci-runner-rollback.md` — añadir las secciones de R5.1.
- `infra/environments/dev/README.md` — añadir la nota de R6.1.
- `infra/environments/dev/RUNBOOK.md` — actualizar §6 (R5.3).
- `infra/environments/dev/{runner-bootstrap.sh, cloud-init.yaml.tftpl, main.tf, variables.tf}` — parametrización por `runner_count`. `cloud-init` lo lee del Terraform; el bootstrap crea los N agentes.
- `infra/environments/dev/iam-policy.md` — sin cambios esperados: instance principal del runner ya tiene los permisos que necesita; cada agente hijo hereda el bootstrap del usuario.
