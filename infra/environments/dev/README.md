# Entorno: dev

**Propósito:** entorno remoto de desarrollo/integración — el primero en recibir despliegues automáticos, para probar cambios de infra o de aplicación fuera del stack local antes de `staging`/`prod`.

**Estado:** código y pipeline listos y verificados (`terraform validate`/`fmt`, un `terraform plan` real contra la cuenta, y build multi-arch en CI). El `apply` real y la primera puesta en marcha de la app quedan como paso explícito, confirmado por el usuario — no se ejecutan solos como parte de este change. Ver `docs/adr/0001-dev-hosting-provider.md` para la decisión de proveedor (Oracle Cloud, Ampere A1 Always Free + docker-compose) y `sdd/steering/infra.md` para la convención completa.

**Operación:** procedimientos de mantenimiento y recuperación (acceso SSH y gestión de claves, backup/recuperación de la clave en OCI Vault, recuperación del state, destroy, diagnóstico de cloud-init) en [`RUNBOOK.md`](./RUNBOOK.md). Los cambios de infra se aplican **solo por el pipeline** (`workflow_dispatch`), con el gate de aprobación = **review del PR + `apply` manual desde `main`** (repo privado + plan Free, sin Environments con required reviewers — ver RUNBOOK §0).

## Qué aprovisiona el Terraform

- Red: una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- Security list: SSH (22), 8000 (backend) y 3000 (frontend) — los puertos que `docker-compose.yml` publica — todos **acotados a los CIDRs de operadores** (`var.allowed_ssh_cidrs`, lista), sin ningún `0.0.0.0/0` de entrada.
- Una instancia `VM.Standard.A1.Flex` (2 OCPU/12 GB, cupo Always Free completo) con una imagen Ubuntu 22.04 ARM64 resuelta dinámicamente (nunca un OCID hardcodeado), con `cloud-init` que instala Docker + el plugin de Compose.
- Una IP pública reservada (no efímera) asociada a la instancia.
- Un presupuesto (`oci_budget_budget` + `oci_budget_alert_rule`) que avisa por email si el gasto real supera un umbral — mitigación del riesgo de facturación documentado en el ADR.

El despliegue de la aplicación en sí (`docker compose pull && up -d` dentro de la VM) lo hace el change `app-deploy-dev` vía `.github/workflows/deploy-dev.yml` — build a GHCR + deploy local en un runner self-hosted que corre en la VM (ver RUNBOOK §6). Este Terraform sí aprovisiona **el runner** (en el `cloud-init`) y su **instance principal** (dynamic group + policy de mínimo privilegio para leer el PAT del Vault).

## Acceso SSH a la instancia

**Par de claves dedicado a la VM** — nunca la API key de OCI que usa Terraform para hablar con la cuenta, son cosas distintas:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/autohostai_dev_vm -C "autohostai-dev-vm"
```

Las claves públicas van en la variable **`ssh_authorized_keys`** (una `list(string)`; Terraform las inyecta vía `cloud-init` al usuario por defecto de la imagen Ubuntu). La privada se queda en tu máquina (con copia recuperable en el Vault, ver [`RUNBOOK.md`](./RUNBOOK.md) §2). **Ojo:** el `metadata` de la instancia es ForceNew en el provider `oci`, así que sobre la **VM viva** las altas/rotaciones de clave se hacen **out-of-band por SSH** (RUNBOOK §1), no cambiando la variable (recrearía la VM); la lista define el arranque de una VM nueva.

Una vez aplicado y con la IP pública (`terraform output instance_public_ip`):

```bash
ssh -i ~/.ssh/autohostai_dev_vm ubuntu@<instance_public_ip>
```

## Backend de state: `oci` nativo

El state vive en un bucket de OCI Object Storage (backend nativo `oci` de Terraform, no el shim S3-compatible). Requiere **Terraform >= 1.12**.

**Límite Always Free**: 20 GB de Object Storage estándar + 20 GB de Archive Storage, siempre gratis, más un cupo de peticiones API/mes también gratis — un `.tfstate` de este módulo pesa unos pocos cientos de KB, muy por debajo. Oracle ya ha recortado cupos Always Free sin aviso previo (ver ADR 0001) — verifica el cupo vigente en la consola (`Governance & Administration → Tenancy Management → Always Free Resources`) en vez de asumir esta cifra indefinidamente.

### Bootstrap manual (una sola vez, ya hecho)

El bucket no lo crea este Terraform — es un paso manual previo, porque no se puede usar Terraform para crear el almacén de su propio state:

1. Consola OCI → **Storage → Object Storage & Archive Storage → Buckets**.
2. **Create Bucket** → nombre `autohostai-tfstate-dev`, tier Standard.
3. Anotar el **namespace** de la tenancy (aparece en la propia consola) y el nombre del bucket.

### Inicializar localmente

```bash
cp backend.hcl.example backend.hcl   # rellenar con tus valores reales, NO versionar
terraform init -backend-config=backend.hcl
```

### Variables del módulo

```bash
cp dev.tfvars.example dev.tfvars     # rellenar con tus valores reales, NO versionar
terraform plan -var-file=dev.tfvars
```

## Secrets de GitHub Actions esperados

El workflow `infra-dev` (jobs `plan`/`apply`, disparo manual `workflow_dispatch`) necesita estos secrets del repo (Settings → Secrets and variables → Actions). Verifícalos con `gh secret list`. Las credenciales de OCI corresponden al usuario de servicio **`svc-terraform-dev`** (IAM mínima), no a un usuario amplio:

| Secret | Para qué |
|---|---|
| `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_REGION` | Autenticación del provider **y** del backend (el backend `oci` necesita sus propias credenciales, no puede leer `var.*`). |
| `OCI_PRIVATE_KEY` | Contenido del `.pem` privado. El workflow lo escribe a un fichero en `$RUNNER_TEMP` y pasa la **ruta** (`private_key_path`) a Terraform — nunca el contenido inline en un string/heredoc HCL (más frágil, ver `design.md` D2). |
| `OCI_COMPARTMENT_OCID` | Compartment donde se crean los recursos. |
| `TFSTATE_NAMESPACE`, `TFSTATE_BUCKET` | Config del backend de state (paso de bootstrap de arriba). |
| `ALLOWED_SSH_CIDR` | CIDR IPv4 de operador (`>= /24`, nunca abierto) permitido para SSH/app — el workflow lo envuelve en lista JSON para `TF_VAR_allowed_ssh_cidrs`. Si tu IP cambia, actualiza el secret y re-aplica. |
| `SSH_PUBLIC_KEY` | Contenido de la clave **pública** SSH de la VM — el workflow lo envuelve en lista JSON para `TF_VAR_ssh_authorized_keys`. La privada nunca sale de tu máquina (copia recuperable en el Vault). |

> Nota: `BUDGET_ALERT_EMAIL` ya **no** se usa — las alertas de presupuesto van a `budget_alert_recipients` (default Jose+Marta en `variables.tf`). Para varios operadores, convierte `ALLOWED_SSH_CIDR`/`SSH_PUBLIC_KEY` en arrays JSON y pásalos tal cual.

## Ejecutar el pipeline

- **En cualquier PR** que toque `infra/environments/dev/**`: el job `check` corre `fmt`/`validate` automáticamente, sin credenciales.
- **Para `plan`/`apply` reales**: pestaña Actions → workflow `infra-dev` → **Run workflow** → elegir `plan` o `apply`. `apply` solo se ejecuta si el `plan` previo del mismo run fue exitoso.
- **Ya verificado en vivo**: un `workflow_dispatch` con `action: plan` corrió contra la cuenta real — `init`/`validate`/`plan` en verde, 9 recursos a crear, 0 errores ([run 29728765058](https://github.com/mreyesojeda/AutoHostAI/actions/runs/29728765058)).

## Despliegue de la app (CD — `app-deploy-dev`)

Workflow `deploy-dev` (`.github/workflows/deploy-dev.yml`): push a `main` sobre `backend/**`/`frontend/**` → build `prod` arm64 → GHCR → deploy **local** en el runner self-hosted de la VM (sin SSH). Flujo, provisión/recuperación del runner, rotación del PAT y rollback en [`RUNBOOK.md`](./RUNBOOK.md) §6.

Secrets/vars adicionales del repo que consume `deploy-dev` (además de los de `infra-dev` de arriba):

| Secret/Var | Para qué |
|---|---|
| `GHCR_PULL_TOKEN` | Token GHCR **read-only** (`read:packages`) con el que la VM hace `docker login` para tirar de las imágenes privadas; se hace `logout` al terminar. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Credenciales de la DB de runtime (Postgres solo en la red interna del compose, sin puerto publicado). |
| `JWT_SECRET_KEY`, `ENCRYPTION_KEY` | Secretos de app (backend). El deploy falla nombrando la clave si falta alguna. |
| `BACKEND_INTERNAL_URL` | Opcional; default `http://backend:8000`. |
| `NEXT_PUBLIC_APP_ENV` (build-arg) | Var pública del frontend — se **hornea en build** (Next standalone), se pasa como `build-arg`, NO en el `.env` de runtime. |

El PAT de GitHub que el runner usa para registrarse **no** es un secret de GitHub: vive en el **OCI Vault** (subido out-of-band) y su OCID va en `dev.tfvars` (`runner_pat_secret_ocid`). Ver RUNBOOK §6.2.

## Pendiente (no automatizable por este change)

- **`terraform apply` inicial** e infra: ya verificado y aplicado en changes previos; el `apply` con la IAM del runner (dynamic group + policy) se dispara por el pipeline con confirmación explícita.
- Ops del CD (a tu cargo, ver RUNBOOK §6): subir el PAT al Vault, aplicar la IAM del runner, provisionar el runner en la VM viva, y el primer deploy.
