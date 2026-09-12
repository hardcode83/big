# `infra/github/` — GitHub-side as code

**Propósito:** declarar la parte de la organización `autohostai-labs/AutoHostAI` que hoy se gestiona a mano desde la consola de GitHub — settings del repo, secrets y variables de Actions, instalación de la GitHub App, branch protection — como código Terraform ejecutable por el pipeline. Es un **tercer patrón** del layout `infra/` (junto a `environments/<env>/` y `modules/`): superficies **por-organización** que no son por entorno. Ver `sdd/steering/infra.md` §Convención de layout.

**Estado:** sección 1 — bootstrap del módulo (estructura, backend, variables). Los recursos del provider `integrations/github` se añaden en secciones 2+ (ver `sdd/changes/infra-github-iac/tasks.md`).

## Por qué módulo aparte (no dentro de `infra/environments/dev/`)

La superficie GitHub-side es **por-organización**, no por-entorno. Acoplarla al módulo dev obligaría a duplicarla en `staging`/`prod` cuando se decida proveedor para ellos, y crea un acoplamiento de orden (el `apply` de infra podría depender del `apply` de GitHub-side para que los secrets existan antes del deploy). Decisión completa en `sdd/changes/infra-github-iac/design.md` D1.

## Backend de state: `oci` nativo, bucket propio

El state vive en Object Storage (backend nativo `oci` de Terraform), en el bucket **`autohostai-tfstate-github`** — paralelo al `autohostai-tfstate-dev`, no reutilizado (D3). Requiere **Terraform >= 1.12**.

### Bootstrap manual (una sola vez, tarea 1.1)

El bucket **no** lo crea este Terraform — mismo motivo que el bucket dev: no se puede usar Terraform para crear el almacén de su propio state.

1. Consola OCI → **Storage → Object Storage & Archive Storage → Buckets**.
2. **Create Bucket** → nombre `autohostai-tfstate-github`, tier Standard, **versioning = enabled** (recomendado para el state — mismo patrón que `autohostai-tfstate-dev`).
3. Anotar el **namespace** de la tenancy (aparece en la propia consola).

### Inicializar localmente

```bash
cp backend.hcl.example backend.hcl        # rellenar con tus valores reales, NO versionar
cp github.tfvars.example github.tfvars    # rellenar valores no sensibles, NO versionar
terraform init -backend-config=backend.hcl
terraform plan -var-file=github.tfvars
```

Las variables **sensibles** no van en ningún `.tfvars`: se inyectan por `TF_VAR_*` desde el entorno o desde los GitHub Secrets del repo en CI.

## Secrets de GitHub Actions esperados

El workflow `infra-github` (job `plan`/`apply`, disparo `workflow_dispatch`, aún no creado — sección 6) consume los mismos secrets de OCI que `infra-dev`, más los específicos del provider `github`. Mismas reglas que `infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados":

| Secret | Para qué |
|---|---|
| `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_REGION` | Auth del provider **y** del backend (el backend `oci` no puede leer `var.*`). |
| `OCI_PRIVATE_KEY` | Contenido del `.pem` privado. El workflow lo escribe a `$RUNNER_TEMP` y pasa la **ruta** (`oci_private_key_path`) — nunca inline (más frágil). |
| `OCI_COMPARTMENT_OCID` | Compartment donde se crean los recursos OCI que este módulo pueda llegar a tocar. |
| `TFSTATE_NAMESPACE`, `TFSTATE_BUCKET` | Config del backend `oci`. |
| `GH_APP_PRIVATE_KEY` | Contenido del `.pem` de la GitHub App. Se escribe a `$RUNNER_TEMP` y se pasa como `github_app_private_key_path` (mismo patrón que `OCI_PRIVATE_KEY`). El módulo dev ya consume este secret (`TF_VAR_github_app_private_key`); aquí se reutiliza el mismo. |
| `GH_APP_ID`, `GH_APP_INSTALLATION_ID` | Variables públicas (no secret). ID de la App y de su instalación sobre el repo/owner. |
| `ALLOWED_SSH_CIDRS`, `ALLOWED_SSH_CIDRS_WIDE`, `SSH_PUBLIC_KEYS` | Mismos arrays JSON que el módulo dev — los secrets de Actions del repo hoy los define `infra-dev` y este módulo los reutiliza. |

> Las credenciales OCI corresponden al usuario de servicio **`svc-terraform-dev`** (IAM mínima), no a un usuario amplio. La clave `.pem` de la App acaba en el tfstate (mismo bucket privado + versionado que `autohostai-tfstate-dev`; relajación `sdd/steering/security.md` regla 8, ámbito dev/test).

## Pendiente (no automatizable por este change)

- Crear el bucket `autohostai-tfstate-github` (tarea 1.1, bootstrap irreducible).
- Crear la GitHub App con los permisos que `RUNBOOK.md` §1 detallará (sección 5).

## Operación

Los procedimientos de mantenimiento (rotación de la clave de la App, bootstrap irreducible, import de recursos existentes, free-plan branch protection) viven en `RUNBOOK.md` (a redactar en sección 5).