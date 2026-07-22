# Design: infra-dev-hardening

## Context

La infra dev vive en `infra/environments/dev/` (`main.tf`, `variables.tf`, `outputs.tf`, `backend.tf`) sobre `oracle/oci`, con el pipeline en `.github/workflows/infra-dev.yml` (jobs `check` en PR y `plan-apply` en `workflow_dispatch`). Hoy: `plan-apply` es **un solo job** sin restricción de rama, sin aprobación, sin `concurrency`/`timeout`, con actions por tag (`actions/checkout@v4`, `hashicorp/setup-terraform@v3`). El cómputo se define con una única `var.ssh_public_key` (string) y un único `var.allowed_ssh_cidr` (string, /32). El cloud-init instala `docker.io` + `docker-compose-plugin` vía `packages:` — el plugin no está en los repos por defecto de Ubuntu 22.04, así que en la VM real Docker quedó activo pero `docker compose` **ausente** (confirmado en vivo). El bucket del state (`autohostai-tfstate-dev`) se crea a mano fuera de Terraform. El budget quedó con drift (borrado manual en consola).

## Decisions

### D1 — Split `plan`/`apply` + gate del apply (R1)

**Chosen:** dividir el job `plan-apply` en dos jobs: **`plan`** (init→validate→plan, sube `tfplan` como artifact) y **`apply`** (descarga el artifact y aplica). El `apply` lleva:
- `environment: dev-apply` → la *required reviewers* del Environment (configurada en Settings del repo) **pausa el run** pidiendo aprobación manual antes de aplicar. **Reviewers: Jose + Marta** (cualquiera aprueba).
- `if: github.ref == 'refs/heads/main'` → solo aplica si el dispatch se lanzó sobre `main` (workflow_dispatch permite lanzar desde cualquier rama; el guard va en el job, no en el trigger).
- `concurrency: { group: infra-dev-apply, cancel-in-progress: false }` → serializa applies, nunca dos sobre el mismo state.
- `timeout-minutes` acotado (p. ej. 15) en ambos jobs.

Todas las actions (`actions/checkout`, `hashicorp/setup-terraform`, `actions/upload-artifact`, `actions/download-artifact`) fijadas por **SHA de commit** con el tag en comentario.

Rejected: mantener un solo job — un Environment protege un *job* entero, así que no se puede pausar solo el paso de apply sin separar. · Restringir la rama en el `on: workflow_dispatch` — GitHub no filtra el ref del dispatch; el `if` a nivel de job es el control real.

### D2 — SSH multi-operador declarativo (R2)

**Chosen:** convertir las variables a listas:
- `ssh_public_key: string` → `ssh_authorized_keys: list(string)` — el cloud-init inyecta todas al `authorized_keys` del usuario `ubuntu` (una por línea). **Por ahora solo la clave de Jose**; la lista deja añadir operadores futuros sin recrear. El acceso de Marta se cubre recuperando la clave del Vault (D7), no con una clave propia.
- `allowed_ssh_cidr: string` → `allowed_ssh_cidrs: list(string)` — el security list genera una `ingress_security_rules` por CIDR con un `dynamic` block. Validación por elemento (IPv4, prefijo ≥ /24), rechazando rangos abiertos.
- **Los puertos 8000 (backend) y 3000 (frontend) dejan de estar abiertos a `0.0.0.0/0`** y se acotan a los mismos CIDR de operadores (decisión del gate) — mismo `dynamic` sobre la lista, aplicado a los tres puertos.

Rejected: una sola clave + edición manual de `authorized_keys` en la VM — no declarativo ni reproducible, y no revocable por Terraform. · Un `/32` único — bloquearía a Marta.

### D3 — cloud-init con repo APT oficial de Docker + remediación de la VM viva (R3)

**Chosen:** en el cloud-init, **añadir el repositorio APT oficial de Docker** (clave GPG + source `download.docker.com/linux/ubuntu jammy stable` para `arch=arm64`) e instalar `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`; añadir `ubuntu` al grupo `docker`. **Ambas cosas** (decisión del gate): (a) se corrige el cloud-init para que una máquina nueva desde 0 arranque bien, y (b) la **VM ya desplegada** se remedia **en caliente por SSH** (añadir repo Docker + instalar el plugin) verificando `docker compose version`, ya que el cloud-init no re-ejecuta.

Rejected: `docker.io` + `docker-compose-plugin` de repos Ubuntu (el bug — el plugin no existe ahí). · Snap docker (no estándar, problemas de socket/permisos). · Script `get.docker.com` por `runcmd` (funciona, pero menos declarativo y reproducible que `apt.sources` de cloud-init).

### D4 — State backend: IAM mínimo, versioning y recuperación (R4)

**Chosen:** documentar/aplicar tres cosas, ninguna gestionable por este propio Terraform (el bucket contiene su propio state → dependencia circular):
- **Versioning** activado en el bucket `autohostai-tfstate-dev` (OCI CLI/consola, una vez), documentado.
- **Policy IAM de mínimo privilegio creada y aplicada** (decisión del gate): un grupo `autohostai-dev-terraform` + policy acotada al compartment de dev — `manage` de instance-family, virtual-network-family, budgets, object-family (solo el bucket del state) y los verbos de Vault/keys/secrets que exige R7. La crea un **admin de la tenancy** (el usuario de TF no puede auto-otorgarse IAM, y darle `manage` de IAM contradiría el mínimo privilegio) — fuera del root module de dev, como config de admin/manual. Se **verifica con un `plan` (y apply) usando el usuario acotado** antes de retirar permisos amplios, derivando la lista exacta de verbos de los recursos reales del `main.tf` para no romper el apply.
- **Procedimiento de recuperación** del state (listar versiones del objeto `dev.tfstate` y restaurar una previa vía OCI CLI), en el runbook.

Rejected: gestionar el bucket en este Terraform — dependencia circular. · Migrar el state a otro backend (S3-compat) — innecesario, el `oci` nativo funciona.

### D5 — Runbook operativo (R5)

**Chosen:** crear `infra/environments/dev/RUNBOOK.md` (fichero dedicado, enlazado desde el README), con: `destroy` controlado, recuperación del state, acceso SSH (usuario, IP, clave por persona, alta/rotación/revocación de claves y CIDRs), y diagnóstico de cloud-init (`/var/log/cloud-init-output.log`, `cloud-init status`, cómo reintentar).

Rejected: meterlo todo en el README — el README es "cómo usar"; el runbook es "cómo operar/recuperar". Mantenerlos separados.

### D6 — Budget €1 con alertas ACTUAL + FORECAST (R6)

**Chosen:** en `main.tf`/`variables.tf`:
- `budget_amount` default → **1**.
- `budget_alert_email: string` → `budget_alert_recipients: list(string)` (default `["josegascon@gmail.com","mreyesojeda@gmail.com"]`), unido con `join(",", ...)` para el campo `recipients` de OCI.
- Configurar la `oci_budget_alert_rule` **ACTUAL** con `threshold_type = ABSOLUTE`, `threshold = 1` (100% de €1) y **añadir** una segunda **FORECAST** con `threshold_type = ABSOLUTE`, `threshold = 1`.
- Reconciliar el drift: la alerta/budget manual creada en consola se elimina antes del apply (paso operativo), y Terraform vuelve a ser el dueño.

Rejected: gestionar el budget a mano fuera de IaC — pierde versionado y reproducibilidad. · Dejar `recipients` como string con comas a pelo — menos legible/validable que una lista.

### D7 — Backup de la clave SSH en OCI Vault, out-of-band (R7)

**Chosen:** Terraform provisiona el **OCI Vault + una master key software-protected** (ambos Always Free, €0) y una IAM policy que permite a Jose/Marta leer el secret; el **valor del secret (la clave privada) se sube out-of-band con OCI CLI** (`oci vault secret create-base64 …`), **nunca como recurso Terraform con el contenido inline** — así el plaintext no toca el `tfstate` (respeta `security.md` #8). GitHub Secrets sigue siendo el consumidor del CD; el Vault es la copia recuperable por humanos.

Rejected: `oci_vault_secret` con `secret_content` inline en Terraform → el plaintext acabaría en el `tfstate`. · Solo GitHub Secrets → write-only, no recuperable por personas. · HSM key / Virtual Private Vault → coste innecesario (la software key cubre el caso a €0).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Pipeline apply | `.github/workflows/infra-dev.yml` | Split `plan`/`apply`, `environment: dev-apply`, `if` main-only, `concurrency`, `timeout-minutes`, actions por SHA |
| SSH multi-operador | `infra/environments/dev/{variables.tf,main.tf,dev.tfvars.example}` | `ssh_authorized_keys` y `allowed_ssh_cidrs` como listas; `dynamic` ingress; cloud-init multi-clave |
| cloud-init Docker | `infra/environments/dev/main.tf` | Repo APT oficial de Docker + `docker-ce`/`docker-compose-plugin` (arm64) |
| VM viva | (operación, sin fichero) | Instalar compose plugin por SSH una vez + verificar |
| State backend | bucket OCI (op.) + `RUNBOOK.md` + doc IAM | Versioning on; policy IAM mínima documentada; recuperación documentada |
| Runbook | `infra/environments/dev/RUNBOOK.md` (nuevo), `README.md` | Procedimiento operativo + enlace |
| Budget | `infra/environments/dev/{main.tf,variables.tf,dev.tfvars.example}` | Importe 1, recipients lista, 2ª alert rule FORECAST/ABSOLUTE |
| Vault backup | `infra/environments/dev/main.tf` (vault+key+policy) + subida por OCI CLI (op.) | OCI Vault + software key (Always Free) + IAM read; secret subido out-of-band |

## Data & interfaces

Variables Terraform (breaking renames — actualizar `dev.tfvars` local y secrets/inputs de CI):
- `ssh_public_key` (string) → `ssh_authorized_keys` (list(string))
- `allowed_ssh_cidr` (string) → `allowed_ssh_cidrs` (list(string))
- `budget_alert_email` (string) → `budget_alert_recipients` (list(string))
- `budget_amount` default 10 → 1

CI: el workflow pasa estas vars como `TF_VAR_*` desde secrets; los secrets multi-valor (claves, CIDRs, emails) pasan a formato lista (p. ej. JSON o multilínea → `jsonencode`/`split`). GitHub **Environment `dev-apply`** con required reviewers configurado en Settings (fuera del YAML). Nuevo secreto para la clave SSH de deploy vive en `app-deploy-dev`, no aquí.

## Risks & mitigations

- **Rename de variables rompe el `apply` de CI** si no se actualizan los secrets/inputs a la vez → coordinar el cambio del YAML + secrets + `dev.tfvars` en el mismo change; el job `check` (validate) lo pilla antes del apply.
- **IAM demasiado restrictiva rompe el `apply` actual** → derivar los permisos de los recursos reales del `main.tf` y probar un `plan` con el usuario acotado antes de retirar permisos amplios.
- **`dynamic` de ingress podría reordenar reglas** y marcar diff cosmético → verificar que el `plan` post-cambio no destruye/recrea el security list (idealmente update in-place).
- **cloud-init solo afecta VMs futuras** → la remediación de la VM viva es un paso operativo explícito (D3), sin él `docker compose` sigue ausente en la máquina actual.
- **El Environment con reviewers es config de repo, no de código** → si no se configura en Settings, el gate de aprobación no existe aunque el YAML lo referencie.

## Open questions

Resueltas en el gate: **(1)** Environment `dev-apply`, reviewers **Jose + Marta**. · **(2)** Alerta ACTUAL → **ABSOLUTE €1**. · **(4)** Remediación de la VM viva → **ejecutada por SSH ahora** + cloud-init corregido para máquinas nuevas. · **(6)** Puertos 8000/3000 → **acotados por CIDR** como el 22.

Pendientes (implementación):
3. **Policy IAM** (decidido: aplicar de verdad — D4): pendiente solo el detalle de implementación — la aplica un admin de la tenancy, derivando los verbos de los recursos reales del `main.tf` y probando `plan`/`apply` con el usuario acotado antes de retirar permisos amplios.
5. **Valores**: por ahora solo la clave/CIDR de Jose (ya conocidos). La clave/CIDR propios de Marta quedan **fuera del plan** (accede recuperando la clave del Vault); se añaden a las listas cuando haga falta, sin recrear.
