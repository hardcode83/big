# Entorno: dev

**Propósito:** entorno remoto de desarrollo/integración — el primero en recibir despliegues automáticos, para probar cambios de infra o de aplicación fuera del stack local antes de `staging`/`prod`.

**Estado:** código y pipeline listos y verificados (`terraform validate`/`fmt`, un `terraform plan` real contra la cuenta, y build multi-arch en CI). El `apply` real y la primera puesta en marcha de la app quedan como paso explícito, confirmado por el usuario — no se ejecutan solos como parte de este change. Ver `docs/adr/0001-dev-hosting-provider.md` para la decisión de proveedor (Oracle Cloud, Ampere A1 Always Free + docker-compose) y `sdd/steering/infra.md` para la convención completa.

**Operación:** procedimientos de mantenimiento y recuperación (acceso SSH y gestión de claves, backup/recuperación de la clave en OCI Vault, recuperación del state, destroy, diagnóstico de cloud-init) en [`RUNBOOK.md`](./RUNBOOK.md).

## Qué aprovisiona el Terraform

- Red: una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- Security list: SSH (22), 8000 (backend) y 3000 (frontend) — los puertos que `docker-compose.yml` publica — todos **acotados a los CIDRs de operadores** (`var.allowed_ssh_cidrs`, lista), sin ningún `0.0.0.0/0` de entrada.
- Una instancia `VM.Standard.A1.Flex` (2 OCPU/12 GB, cupo Always Free completo) con una imagen Ubuntu 22.04 ARM64 resuelta dinámicamente (nunca un OCID hardcodeado), con `cloud-init` que instala Docker + el plugin de Compose.
- Una IP pública reservada (no efímera) asociada a la instancia.
- Un presupuesto (`oci_budget_budget` + `oci_budget_alert_rule`) que avisa por email si el gasto real supera un umbral — mitigación del riesgo de facturación documentado en el ADR.

Lo que este Terraform **no** hace: desplegar la aplicación en sí (`docker compose pull && up -d` dentro de la VM). Eso es un workflow/step futuro, fuera de alcance de este change, que usa la IP pública de salida (`output "instance_public_ip"`) como input.

## Acceso SSH a la instancia

**Par de claves dedicado a la VM** — nunca la API key de OCI que usa Terraform para hablar con la cuenta, son cosas distintas:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/autohostai_dev_vm -C "autohostai-dev-vm"
```

El contenido del `.pub` va en la variable `ssh_public_key` (Terraform lo inyecta vía `cloud-init`, campo `ssh_authorized_keys`, al usuario por defecto de la imagen Ubuntu). La privada se queda en tu máquina, nunca en el repo ni en ningún secret — solo hace falta en el momento de conectarte.

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

El workflow `plan-apply` (`.github/workflows/infra-dev.yml`, disparo manual `workflow_dispatch`) necesita estos secrets del repo (Settings → Secrets and variables → Actions). **Estado: 11 secrets esperados** — verificar con `gh secret list` cuáles faltan (`SSH_PUBLIC_KEY` se añadió después de los primeros 10, al detectar que faltaba una estrategia de acceso SSH a la instancia):

| Secret | Para qué |
|---|---|
| `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_REGION` | Autenticación del provider **y** del backend (el backend `oci` necesita sus propias credenciales, no puede leer `var.*`). |
| `OCI_PRIVATE_KEY` | Contenido del `.pem` privado. El workflow lo escribe a un fichero en `$RUNNER_TEMP` y pasa la **ruta** (`private_key_path`) a Terraform — nunca el contenido inline en un string/heredoc HCL (más frágil, ver `design.md` D2). |
| `OCI_COMPARTMENT_OCID` | Compartment donde se crean los recursos. |
| `TFSTATE_NAMESPACE`, `TFSTATE_BUCKET` | Config del backend de state (paso de bootstrap de arriba). |
| `ALLOWED_SSH_CIDR` | CIDR IPv4 restringido (`>= /24`, nunca abierto) permitido para SSH — hoy apunta a la IP del usuario, que es dinámica: si cambia, hay que actualizar este secret y volver a aplicar. |
| `SSH_PUBLIC_KEY` | Contenido de la clave **pública** SSH dedicada a la VM (no sensible, pero se guarda como secret por consistencia) — la privada nunca sale de la máquina del usuario. |
| `BUDGET_ALERT_EMAIL` | Destinatario de la alerta de presupuesto. |

## Ejecutar el pipeline

- **En cualquier PR** que toque `infra/environments/dev/**`: el job `check` corre `fmt`/`validate` automáticamente, sin credenciales.
- **Para `plan`/`apply` reales**: pestaña Actions → workflow `infra-dev` → **Run workflow** → elegir `plan` o `apply`. `apply` solo se ejecuta si el `plan` previo del mismo run fue exitoso.
- **Ya verificado en vivo**: un `workflow_dispatch` con `action: plan` corrió contra la cuenta real — `init`/`validate`/`plan` en verde, 9 recursos a crear, 0 errores ([run 29728765058](https://github.com/mreyesojeda/AutoHostAI/actions/runs/29728765058)).

## Pendiente (no automatizable por este change)

- **`terraform apply` inicial**: los secrets ya están cargados y el `plan` ya se ha verificado en vivo — solo falta la confirmación explícita del usuario para disparar `action: apply`. No se dispara solo.
- Una vez aplicado: desplegar la app en la VM (`docker compose pull && up -d` vía SSH) — workflow futuro, fuera de alcance.
