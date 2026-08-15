# Entorno: dev

**Propósito:** entorno remoto de desarrollo/integración — el primero en recibir despliegues automáticos, para probar cambios de infra o de aplicación fuera del stack local antes de `staging`/`prod`.

**Estado:** código y pipeline listos y verificados (`terraform validate`/`fmt`, un `terraform plan` real contra la cuenta, y build multi-arch en CI). El `apply` real y la primera puesta en marcha de la app quedan como paso explícito, confirmado por el usuario — no se ejecutan solos como parte de este change. Ver `docs/adr/0001-dev-hosting-provider.md` para la decisión de proveedor (Oracle Cloud, Ampere A1 Always Free + docker-compose) y `sdd/steering/infra.md` para la convención completa.

**Operación:** procedimientos de mantenimiento y recuperación (acceso SSH y gestión de claves, backup/recuperación de la clave en OCI Vault, recuperación del state, destroy, diagnóstico de cloud-init) en [`RUNBOOK.md`](./RUNBOOK.md). Los cambios de infra se aplican **solo por el pipeline** (`workflow_dispatch`), con el gate de aprobación = **review del PR + `apply` manual desde `main`** (repo privado + plan Free, sin Environments con required reviewers — ver RUNBOOK §0).

## Qué aprovisiona el Terraform

- Red: una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- Security list: **solo SSH (22)**, acotado a los CIDRs de operadores (`var.allowed_ssh_cidrs`, lista), sin ningún `0.0.0.0/0` de entrada. Los puertos 8000 (backend) y 3000 (frontend) **ya no se abren**: desde el change `ingress-https-dev` el acceso público llega por un Cloudflare Tunnel (conexión saliente) y esos puertos solo se publican en el `127.0.0.1` de la VM como puerta de depuración por reenvío SSH.
- Una instancia `VM.Standard.A1.Flex` (2 OCPU/12 GB, cupo Always Free completo) con una imagen Ubuntu 22.04 ARM64 resuelta dinámicamente (nunca un OCID hardcodeado), con `cloud-init` que instala Docker + el plugin de Compose.
- Una IP pública reservada (no efímera) asociada a la instancia.
- Un presupuesto (`oci_budget_budget` + `oci_budget_alert_rule`) que avisa por email si el gasto real supera un umbral — mitigación del riesgo de facturación documentado en el ADR.
- **El almacén de objetos de las fotos** (change `object-storage-provisioning`): un bucket **privado** `autohostai-<env>-media` (`NoPublicAccess` — todo objeto se entrega por URL prefirmada de caducidad acotada), su usuario IAM propio con una policy acotada a ese bucket y a cuatro permisos de objeto, su Customer Secret Key, y cuatro `oci_vault_secret` con lo que la VM necesita. El backend le habla por la API **compatible con S3** con boto3 apuntado por `endpoint_url`, sin SDK de OCI: cambiar a AWS S3, R2 o MinIO es configuración, no código. Elección de proveedor y matriz de equivalencias en [`docs/adr/0008-object-storage-provider-dev.md`](../../../docs/adr/0008-object-storage-provider-dev.md); rotación de la clave y conversión de un tenant a `S3`, en RUNBOOK §9.

  Sus outputs son los tres valores que el backend configura —`media_bucket_name`, `media_region`, `media_s3_endpoint`— más los **nombres** (nunca los valores) de los cuatro secretos: `media_access_key_secret_name`, `media_secret_key_secret_name`, `media_endpoint_secret_name`, `media_region_secret_name`. El endpoint no se escribe a mano: se deriva del namespace de la tenancy (`data "oci_objectstorage_namespace"`) y de la región.

El despliegue de la aplicación en sí (`docker compose pull && up -d` dentro de la VM) lo hace el change `app-deploy-dev` vía `.github/workflows/deploy-dev.yml` — build a GHCR + deploy local en un runner self-hosted que corre en la VM (ver RUNBOOK §6). Este Terraform sí aprovisiona **el runner** (en el `cloud-init`), sus **secrets de runtime** (generados por TF → Vault) y su **instance principal** (dynamic group + policy de mínimo privilegio para leer del Vault la clave de la GitHub App y los secrets de runtime).

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
| `ALLOWED_SSH_CIDRS` | **Varios operadores.** Array JSON de CIDRs IPv4 (`>= /24`, nunca abierto) permitidos para SSH, tal cual: `["1.2.3.4/32","5.6.7.8/32"]`. Es el que hay que usar. |
| `ALLOWED_SSH_CIDR` | *(histórico, un solo operador)* CIDR suelto que el workflow envuelve en lista. Solo se lee **si `ALLOWED_SSH_CIDRS` está vacío o no existe**. |
| `SSH_PUBLIC_KEYS` | **Varios operadores.** Array JSON con las claves **públicas** SSH, una por operador. |
| `SSH_PUBLIC_KEY` | *(histórico, una sola clave)* Igual que arriba: solo se lee si el plural está vacío. La privada nunca sale de tu máquina (copia recuperable en el Vault). |

> **Añadir un operador se hace SIEMPRE por el secret plural, nunca por la consola de OCI.** Una regla de ingress añadida a mano sobrevive hasta el siguiente `apply` y entonces desaparece sin avisar: el `plan` del 2026-08-15 destapó dos (`Marta`, `SSH HOTEL AMA`) que llevaban tiempo puestas y que ningún fichero de este repositorio explicaba. Si tu IP cambia, actualiza el secret y re-aplica (RUNBOOK §0).
>
> Se conservan las dos formas —singular y plural— a propósito: migrar de golpe habría dejado una ventana en la que el `apply` falla porque el plural aún no existe y el singular ya no se lee, con un JSON inválido en un `TF_VAR` como único síntoma.

> Nota: `BUDGET_ALERT_EMAIL` ya **no** se usa — las alertas de presupuesto van a `budget_alert_recipients` (default Jose+Marta en `variables.tf`).

## Ejecutar el pipeline

- **En cualquier PR** que toque `infra/environments/dev/**`: el job `check` corre `fmt`/`validate` automáticamente, sin credenciales.
- **Para `plan`/`apply` reales**: pestaña Actions → workflow `infra-dev` → **Run workflow** → elegir `plan` o `apply`. `apply` solo se ejecuta si el `plan` previo del mismo run fue exitoso.
- **Ya verificado en vivo**: un `workflow_dispatch` con `action: plan` corrió contra la cuenta real — `init`/`validate`/`plan` en verde, 9 recursos a crear, 0 errores ([run 29728765058](https://github.com/autohostai-labs/AutoHostAI/actions/runs/29728765058)).

## Despliegue de la app (CD — `app-deploy-dev`)

Workflow `deploy-dev` (`.github/workflows/deploy-dev.yml`): push a `main` sobre `backend/**`/`frontend/**` → build `prod` arm64 → GHCR → deploy **local** en el runner self-hosted de la VM (sin SSH). Flujo, provisión/recuperación del runner, GitHub App (permisos, `GH_APP_PRIVATE_KEY`, rotación) y rollback en [`RUNBOOK.md`](./RUNBOOK.md) §6.

Variables/secret del repo que consume el CD (además de los de `infra-dev`). **No hay secrets de app de runtime en GitHub** — los genera Terraform y viven en el Vault; el deploy los lee de ahí por instance principal:

| Nombre | Tipo | Para qué |
|---|---|---|
| `GH_APP_ID`, `GH_APP_INSTALLATION_ID` | **variable** | Identifican la GitHub App que mintea el token de **registro del runner** (el pull de GHCR lo hace el `GITHUB_TOKEN` del job, no la App). No sensibles. |
| `GH_APP_PRIVATE_KEY` | **secret** | Clave privada (`.pem`) de la App. Único secret-zero; Terraform la escribe al Vault de cada entorno (`TF_VAR_github_app_private_key`). |
| `NEXT_PUBLIC_APP_ENV` | **variable** | Var pública del frontend — se **hornea en build** (Next standalone) como `build-arg`, no en el `.env` de runtime. |

Los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) los **genera Terraform** (`random_*`) → `oci_vault_secret`. `POSTGRES_DB`/`POSTGRES_USER` son variables Terraform con default. `github_app_id`/`github_app_installation_id` van también en `dev.tfvars`. Ver RUNBOOK §6.

## Pendiente (no automatizable por este change)

- **`terraform apply` inicial** e infra: ya verificado y aplicado en changes previos; el `apply` con la IAM del runner (dynamic group + policy) y los secrets del Vault se dispara por el pipeline con confirmación explícita.
- Ops del CD (a tu cargo, ver RUNBOOK §6): crear la GitHub App (variables `GH_APP_*` + secret `GH_APP_PRIVATE_KEY`), aplicar por el pipeline (crea IAM + secrets del Vault), provisionar el runner en la VM viva, y el primer deploy.
