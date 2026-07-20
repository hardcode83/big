# Proposal: infra-dev-terraform

## Why

`docs/adr/0001-dev-hosting-provider.md` cerró la decisión de proveedor para el entorno `dev`: Oracle Cloud Infrastructure, VM única Ampere A1 (Always Free) + `docker-compose`. El ADR es explícito en que **no** escribe Terraform real y deja dos tareas de seguimiento obligatorias para "el change que escriba el `.tf` real": (1) verificar/añadir build multi-arch (`linux/arm64`) en CI para las imágenes de `backend`/`frontend`, y (2) configurar alertas de presupuesto en la tenancy desde el primer día, dado el riesgo de facturación si la cuenta deja de ser Always Free pura. `infra/environments/dev/README.md` (spec `infra-scaffold`) sigue siendo un placeholder ("sin Terraform real todavía"). Este change cierra esa deuda: pasa de la decisión (ADR) a la infraestructura real, dejando el entorno `dev` desplegable.

## What changes

Se añade Terraform real bajo `infra/environments/dev/` (red/VCN, security list, instancia de cómputo Ampere A1, alerta de presupuesto) usando el provider `oracle/oci`, más un workflow de GitHub Actions que ejecuta `terraform plan`/`apply` contra ese root module con disparo manual (`workflow_dispatch`). Se verifica/añade soporte multi-arch (`linux/arm64`) en los `Dockerfile` de `backend` y `frontend`. `infra/environments/dev/README.md` deja de ser un placeholder y documenta cómo aplicar el módulo.

**Fuera del alcance de la verificación automática de este change**: el `terraform apply` contra una cuenta real y el despliegue efectivo de la app. La tenancy de Oracle Cloud **no existe todavía** (`EXTERNAL_DEPENDENCY`, por crear por el usuario) — ninguna tarea de este change puede ejecutar `apply` contra un backend/cuenta reales; toda verificación se hace con `terraform validate`/`fmt`/`plan` (sin credenciales, o con credenciales dummy donde el provider lo permita) y con revisión estática del workflow. El `apply` real y la configuración de secretos de GitHub Actions quedan como pasos manuales explícitos, documentados en el README del entorno, para cuando el usuario tenga la tenancy creada.

## Requirements

### R1 — Red y cómputo de `dev` según ADR 0001

**As a** equipo de infraestructura, **I want** el Terraform real de `infra/environments/dev/` que aprovisiona la topología decidida en el ADR, **so that** el entorno dev pueda desplegarse sin decisiones de diseño pendientes sobre red/cómputo.

Acceptance criteria:

1. WHEN se inspecciona `infra/environments/dev/`, THE SYSTEM SHALL contener un root module de Terraform (`main.tf`, `variables.tf`, `outputs.tf`) que usa el provider `oracle/oci` para aprovisionar: una VCN con subred pública, una security list acorde al stack (puertos de `docker-compose.yml`: backend 8000, frontend 3000, y SSH), y una instancia de cómputo shape `VM.Standard.A1.Flex` (Ampere A1) dentro del cupo Always Free (2 OCPU/12GB) con IP pública reservada.
2. WHEN se ejecuta `terraform validate` y `terraform fmt -check` sobre `infra/environments/dev/` (sin credenciales reales), THE SYSTEM SHALL completar sin errores.
3. IF el tamaño de instancia o la topología de red se desvía de lo decidido en el ADR (modelo VM único, no Kubernetes/PaaS), THEN THE SYSTEM SHALL rechazarse en revisión — el ADR es la fuente de verdad, no se reabre aquí.
4. WHERE existan variables sensibles (tenancy OCID, user OCID, fingerprint, private key, región), THE SYSTEM SHALL declararlas como `variable` sin valores por defecto ni secretos hardcodeados, documentando su origen esperado (GitHub Actions secrets) en `variables.tf`/README.

### R2 — Backend de state remoto para `dev`

**As a** equipo de infraestructura, **I want** que el state de Terraform de `dev` se guarde en un backend remoto y no en disco local, **so that** el state sobreviva a la pérdida de cualquier máquina/runner individual y sea seguro para colaborar.

Acceptance criteria:

1. WHEN se aplica el Terraform de `dev` desde cualquier máquina o runner de CI autorizado, THE SYSTEM SHALL recuperar el mismo state remoto — ninguna máquina individual es la única portadora del `.tfstate`.
2. WHERE el `backend.tf` de `dev` declara un backend concreto, THE SYSTEM SHALL documentar en el diseño la alternativa elegida (p. ej. Terraform Cloud vs. backend `s3`-compatible contra OCI Object Storage vs. otra) con su justificación de coste/límites — **decisión abierta a resolver en diseño, no asumida en esta propuesta**.
3. IF la opción elegida tiene un límite de capa gratuita, THEN THE SYSTEM SHALL documentar ese límite explícitamente (igual que el ADR 0001 distinguió always-free permanente de crédito con caducidad).

### R3 — Pipeline de GitHub Actions (`plan`/`apply` manual)

**As a** equipo de infraestructura, **I want** un workflow de GitHub Actions que ejecute `terraform plan`/`apply` contra `infra/environments/dev/`, **so that** el aprovisionamiento no dependa de ejecutar Terraform manualmente desde un portátil.

Acceptance criteria:

1. WHEN se dispara manualmente (`workflow_dispatch`) el workflow, THE SYSTEM SHALL ejecutar `terraform init`/`validate`/`plan` contra `infra/environments/dev/`, y `apply` solo si el `plan` se aprueba explícitamente (input o environment protection de GitHub).
2. WHERE el trigger automático por rama/evento no está decidido (steering `infra.md` lo deja abierto), THE SYSTEM SHALL usar `workflow_dispatch` como único disparador de este change — no se introduce auto-apply en push/merge; ampliar el disparador es una decisión de un change futuro.
3. WHEN el workflow se ejecuta en un PR de este change (sin secretos de OCI configurados), THE SYSTEM SHALL seguir completando `init`/`validate`/`fmt -check` con éxito — el paso `plan`/`apply` que requiere credenciales reales se permite fallar o saltarse explícitamente hasta que el usuario configure los secretos.

### R4 — Build multi-arch (`linux/arm64`) verificado en CI

**As a** equipo de infraestructura, **I want** que las imágenes de `backend` y `frontend` construyan para `linux/arm64` además de `linux/amd64`, **so that** puedan ejecutarse en la instancia Ampere A1 (ARM) sin descubrir el problema en el primer despliegue real.

Acceptance criteria:

1. WHEN se construye la imagen `prod` de `backend` (`backend/devops/Dockerfile`) para la plataforma `linux/arm64`, THE SYSTEM SHALL completar el build sin error, dado que las imágenes base (`python:3.12-slim`, binario de `astral-sh/uv`) publican manifiestos `arm64` (riesgo ya identificado en el ADR).
2. WHEN se construye la imagen `prod` de `frontend` (`frontend/devops/Dockerfile`) para `linux/arm64`, THE SYSTEM SHALL completar el build sin error (`node:22-slim` publica manifiesto `arm64`).
3. THE SYSTEM SHALL verificar esto en CI (build multi-plataforma con `docker buildx`, sin publicar necesariamente a un registry en este change) — no basta con verificarlo manualmente una vez.

### R5 — Alerta de presupuesto gestionada por Terraform

**As a** propietaria del proyecto, **I want** una alerta de presupuesto configurada vía Terraform en la tenancy de Oracle, **so that** un exceso de cuota bajo una tenancy Pay-As-You-Go no pase inadvertido (riesgo ya documentado en el ADR).

Acceptance criteria:

1. WHEN se aplica el Terraform de `dev` contra una tenancy real, THE SYSTEM SHALL crear un recurso de presupuesto (`oci_budget_budget` + `oci_budget_alert_rule` o equivalente) con un umbral configurable por variable y una acción de notificación (email).
2. IF no se configura un destinatario de notificación, THEN THE SYSTEM SHALL fallar la validación de variables (variable obligatoria, sin default), no desplegar una alerta silenciosa sin destinatario.

### R6 — Documentación del entorno

**As a** cualquier persona del equipo, **I want** que `infra/environments/dev/README.md` refleje el estado real (Terraform existente, cómo aplicarlo, qué falta), **so that** no queden placeholders obsoletos una vez exista `.tf` real.

Acceptance criteria:

1. WHEN se lee `infra/environments/dev/README.md`, THE SYSTEM SHALL describir: qué aprovisiona el Terraform, cómo ejecutar `plan`/`apply` (local y vía el workflow), qué variables/secretos requiere, y que el `apply` real requiere una tenancy de Oracle Cloud creada por el usuario (`EXTERNAL_DEPENDENCY`, con enlace al ADR).
2. WHEN se lee el mismo README, THE SYSTEM SHALL indicar explícitamente que ni el `apply` inicial ni la carga de secretos de GitHub Actions se han ejecutado todavía — evita que el README declare como hecho algo no verificado.

## Out of scope

- Entornos `staging` y `prod` — tendrán su propio ADR/change cuando el negocio lo requiera (ya establecido en el ADR 0001).
- Ejecutar `terraform apply` real contra una cuenta de Oracle Cloud, y cualquier verificación que dependa de infraestructura desplegada de verdad (smoke test contra una IP pública real, etc.) — bloqueado por la falta de tenancy (`EXTERNAL_DEPENDENCY`); es trabajo manual del usuario una vez tenga cuenta y secretos configurados.
- Configurar los secretos de GitHub Actions (OCID/fingerprint/private key) — paso manual del usuario, documentado pero no ejecutado aquí.
- Decidir el disparador automático del workflow por rama/evento (push/merge a `main`) — se mantiene solo `workflow_dispatch`; el disparador automático es una decisión de un change futuro (ya señalado como abierto en `steering/infra.md`).
- Publicar las imágenes multi-arch a un registry remoto — este change solo verifica que el build multi-arch funciona en CI, no añade un paso de publish/push a ghcr.io o similar.
- Cambiar la topología de `docker-compose.yml` — se reutiliza tal cual, según decidió el ADR.

## Affected specs

- `sdd/specs/infra-scaffold.md` — pasa de "sin IaC real" a documentar el Terraform real de `dev` (los placeholders de `staging`/`prod` se mantienen).
- `sdd/specs/infra-dev-terraform.md` *(no existe aún — se creará al archivar)* — spec propio del entorno `dev` real: topología aprovisionada, backend de state elegido, pipeline de CI.
