# Proposal: infra-dev-hardening

## Why

Revisión de infraestructura (comentarios de Marta) antes de dar por cerrada la infra de `dev`. La base (`infra-dev-terraform`, archivado) y la reconciliación a PAYG (`infra-dev-payg`, PR #13) dejan la VM operativa, pero una lectura de seguridad/operación identifica huecos reales y **un bug probable**:

- El `workflow_dispatch` de `apply` no está acotado (cualquier rama puede lanzarlo, sin aprobación, sin `concurrency` ni `timeout`, con actions fijadas por tag y no por SHA).
- El acceso SSH inicial a la VM no está documentado.
- **cloud-init instala `docker-compose-plugin` vía `packages:`, pero ese paquete no está en los repos por defecto de Ubuntu 22.04** (viene del apt oficial de Docker) → la instalación fallaría y `docker compose` no estaría disponible. Bug que rompería el despliegue de la app.
- El backend de state (bucket manual) no tiene IAM mínimo, versioning ni procedimiento de recuperación documentados.
- No existe un runbook operativo (destroy, recuperación de state, acceso a la VM, diagnóstico de cloud-init).
- La alerta de presupuesto que gestionaba Terraform (€10, `ACTUAL`, 80%, un solo email) se borró a mano en la consola y se sustituyó por una manual — dejando **drift**: Terraform la recrearía con la config vieja en el próximo `apply`. Se quiere en su lugar un presupuesto de **€1/mes** con alerta `ACTUAL` **y** `FORECAST` (absoluta a €1), avisando a los correos de Jose y Marta, gestionado por IaC.

Este change endurece esos puntos. **Toca los mismos ficheros que `infra-dev-payg`** (`.github/workflows/infra-dev.yml`, `infra/environments/dev/main.tf`), así que su implementación debe rebasar sobre `main` una vez `infra-dev-payg` (PR #13) esté mergeado.

## What changes

Tras este change, el `apply` de infra solo es lanzable desde `main`, protegido por un GitHub Environment con aprobación manual, con `concurrency` y `timeout`, y con todas las GitHub Actions fijadas por SHA; el cloud-init instala Docker + Compose de forma verificada en Ubuntu 22.04 ARM64; el backend de state tiene IAM mínimo, versioning y un procedimiento de recuperación documentados; el acceso SSH está documentado; y existe un runbook operativo para las tareas de mantenimiento habituales.

## Requirements

### R1 — Endurecimiento del workflow de apply

**As a** responsable de infra, **I want** el camino de `apply` acotado, aprobado y reproducible, **so that** nadie aplica infra real por accidente, desde una rama arbitraria o con acciones no verificadas.

Acceptance criteria:

1. WHEN se dispara `workflow_dispatch` con `action=apply` desde una rama distinta de `main`, THE SYSTEM SHALL rechazar/omitir el job de `apply`.
2. THE SYSTEM SHALL exigir la aprobación manual de un GitHub Environment (required reviewers) antes de ejecutar el `apply`.
3. THE SYSTEM SHALL declarar `concurrency` en el workflow de forma que dos `apply` no se ejecuten en paralelo sobre el mismo state, y un `timeout-minutes` acotado en los jobs.
4. THE SYSTEM SHALL fijar todas las GitHub Actions usadas (p. ej. `actions/checkout`, `hashicorp/setup-terraform`) por **SHA de commit**, no por tag, con el tag anotado en comentario.

### R2 — Acceso SSH multi-operador (claves y orígenes por persona)

**As a** operador, **I want** que cada persona del equipo (p. ej. Jose y Marta) acceda con su **propia** clave y desde su propia IP, **so that** el acceso es individual, revocable por persona y sin compartir ninguna clave privada.

Acceptance criteria:

1. THE SYSTEM SHALL soportar **una lista** de claves públicas SSH autorizadas (variable de lista inyectada a `authorized_keys` vía cloud-init) que define el arranque de una VM nueva. Por ahora se puebla **solo la clave de Jose**; el acceso de Marta se resuelve recuperando la clave del Vault (R7), no con una clave propia en la VM. NOTA (verificada en implementación): el `metadata` de la instancia es ForceNew en el provider `oci`, así que sobre la **instancia viva** las altas/rotaciones de clave se hacen **out-of-band por SSH** (no vía Terraform, que recrearía la VM); el `lifecycle ignore_changes = [metadata]` protege la instancia existente.
2. THE SYSTEM SHALL permitir SSH desde **varios orígenes CIDR** (la IP de cada operador), no un único `/32`, manteniendo la validación de cada CIDR (IPv4, prefijo ≥ /24, sin rangos abiertos) — porque con un solo `/32` la clave de Marta no bastaría, su IP quedaría bloqueada por el security list.
3. THE SYSTEM SHALL documentar el procedimiento de acceso (usuario `ubuntu`, IP de la VM, clave por persona) y **cómo añadir/rotar/revocar una clave o una IP sin recrear la instancia**.
4. WHERE la clave privada solo la necesita el pipeline de CI/CD (no un humano), THE SYSTEM SHALL indicar que ese secreto vive en GitHub Actions Secrets (write-only, no recuperable por personas) — el acceso humano se resuelve con la clave propia de cada operador, no recuperando un secreto compartido.

### R3 — cloud-init y Docker Compose operativos en Ubuntu 22.04 ARM64 (bug confirmado)

**As a** operador, **I want** que Docker y Docker Compose queden instalados y operativos, tanto en arranques futuros como en la VM ya desplegada, **so that** el despliegue de la app no falle por una instalación rota.

Diagnóstico en vivo (2026-07-22): en la VM actual Docker está instalado y activo (v29.1.3), **pero `docker compose` (plugin v2) NO existe** (`docker: unknown command: docker compose`); el log de cloud-init muestra `Failure when attempting to install packages: ['docker.io','docker-compose-plugin']` — el paquete `docker-compose-plugin` no está en los repos por defecto de Ubuntu 22.04.

Acceptance criteria:

1. THE SYSTEM SHALL instalar Docker Engine y el plugin de Compose por un método válido en Ubuntu 22.04 ARM64 (añadiendo el repositorio APT oficial de Docker, o método equivalente verificado), no asumiendo que `docker-compose-plugin` está en los repos por defecto.
2. WHEN una VM nueva termina el arranque (cloud-init), THE SYSTEM SHALL tener `docker` y `docker compose` disponibles y el servicio Docker activo, verificado en la arquitectura ARM64 real.
3. WHERE la instancia ya desplegada arrancó con el cloud-init roto (cloud-init solo corre en el primer boot), THE SYSTEM SHALL dejar `docker compose` instalado y verificado en esa VM (`docker compose version` responde), no solo corregido el template para VMs futuras.

### R4 — Backend de state: IAM mínimo, versioning y recuperación

**As a** responsable de infra, **I want** el almacén del state protegido y recuperable, **so that** una corrupción o borrado accidental del state no bloquea la gestión de la infra.

Acceptance criteria:

1. THE SYSTEM SHALL crear y aplicar una **policy IAM de mínimo privilegio** (grupo + policy acotados al compartment de `dev`) para el usuario de Terraform, cubriendo exactamente los recursos que gestiona (compute, red, budgets, object storage del state y Vault de R7) y **verificando que `plan`/`apply` siguen funcionando** con esos permisos acotados.
2. THE SYSTEM SHALL tener activado el versioning en el bucket de Object Storage del state.
3. THE SYSTEM SHALL documentar el procedimiento de recuperación del state (restaurar una versión previa del objeto de state).

### R5 — Runbook operativo

**As a** operador, **I want** un procedimiento operativo breve, **so that** las tareas de mantenimiento habituales no dependen de memoria o de esta conversación.

Acceptance criteria:

1. THE SYSTEM SHALL documentar (en `infra/environments/dev/README.md` o un `RUNBOOK.md`) al menos: `destroy` controlado, recuperación del state, acceso a la VM por SSH, y diagnóstico de cloud-init (dónde ver sus logs, cómo reintentar).

### R6 — Presupuesto de €1 con alertas ACTUAL + FORECAST, gestionado por IaC

**As a** responsable de coste, **I want** un presupuesto ajustado con alertas actual y de previsión a los dos responsables, **so that** cualquier cargo bajo PAYG se detecta al instante y el budget vuelve a estar bajo control de Terraform (no manual).

Acceptance criteria:

1. THE SYSTEM SHALL definir el `oci_budget_budget` con importe **1** (€1/mes) en lugar del valor anterior.
2. THE SYSTEM SHALL desplegar **dos** `oci_budget_alert_rule`: una de tipo `ACTUAL` (se mantiene) y otra de tipo `FORECAST` con `threshold_type = ABSOLUTE` y `threshold = 1`.
3. THE SYSTEM SHALL enviar ambas alertas a los destinatarios `josegascon@gmail.com` y `mreyesojeda@gmail.com`.
4. WHEN se aplique este change por el pipeline, THE SYSTEM SHALL reconciliar el drift dejado por el borrado manual (la alerta manual se elimina previamente en la consola), quedando el presupuesto de nuevo bajo Terraform sin duplicados.

### R7 — Backup recuperable de la clave SSH en OCI Vault (Always Free, €0)

**As a** operador, **I want** una copia recuperable de la clave privada SSH (la de deploy/break-glass) en un baúl del que el equipo pueda sacarla, **so that** si se pierde localmente se recupera, sin depender de GitHub Secrets (que es write-only y no permite recuperación por personas).

Acceptance criteria:

1. THE SYSTEM SHALL almacenar la clave privada SSH como un secret en **OCI Vault** usando una master key **software-protected** y un secret dentro del cupo **Always Free** (coste €0), recuperable por las personas autorizadas del equipo (Jose, Marta).
2. THE SYSTEM SHALL mantener además la clave en **GitHub Secrets** (write-only) para el consumo del pipeline de CD — el Vault es la copia recuperable, GitHub el consumidor de CI.
3. WHERE el secret se sube al Vault, THE SYSTEM SHALL hacerlo sin que el valor en claro quede en el repositorio ni en el `tfstate` (subida out-of-band, no como recurso Terraform con el contenido inline).

## Out of scope

- **Staging/prod**: este change es solo `dev`.
- **Despliegue de la app / CD hacia la VM** (build → registry → SSH `docker compose pull && up -d`, y la estrategia de trigger): capability nueva, va en el change **`app-deploy-dev`**. R3 la desbloquea (deja `docker compose` operativo) pero no la monta.
- **Cambio de proveedor**: se mantiene Oracle (ver ADR 0001 y su addendum).
- **La reconciliación a PAYG y el resize 4/24/200**: ya cubiertos por `infra-dev-payg` (PR #13); este change no los repite.

## Affected specs

- `sdd/specs/infra-dev-terraform.md` — modificar (endurecimiento del workflow de apply, cloud-init corregido, backend de state con versioning/IAM/recuperación, runbook).
- `sdd/steering/security.md` — posible actualización si se fija una regla estándar (apply solo en main + aprobación) reutilizable por staging/prod.
