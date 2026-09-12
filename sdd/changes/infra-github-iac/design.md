# Design: infra-github-iac

## Context

Hoy, el lado GitHub del repo `autohostai-labs/AutoHostAI` se gestiona a mano: los secrets/variables de Actions se ponen con `gh secret set` contra el repo vivo (`infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados" enumera once secretos y `app-deploy-dev` añade cuatro variables más), la instalación de la GitHub App sobre el repo se hizo una vez en la consola y no se documenta su estado, y los settings del repo (descripción, topics, default branch) viven solo en la UI. El lado cloud (`infra/environments/dev/`) ya está completamente como código — red, cómputo, IAM, backend de state, secrets al Vault, túnel de Cloudflare — siguiendo la convención de layout de `steering/infra.md` (un root module por entorno, ortogonal al layout por dominio del backend/frontend). El provider `integrations/github` aún no está declarado en ningún módulo de Terraform. La GitHub App que `app-deploy-dev` creó para el CD (`infra/environments/dev/cloud-init.yaml.tftpl` la usa para mintear el installation token del runner) ya tiene los permisos que el provider `integrations/github` necesita para gestionar el repo, así que no introduce un mecanismo de auth nuevo.

## Decisions

### D1 — Módulo nuevo en `infra/github/`, no dentro de `infra/environments/dev/`

**Chosen:** Crear un nuevo root module `infra/github/` en la raíz de `infra/`, paralelo a `infra/environments/<env>/`. Estructura idéntica al módulo dev: `main.tf`, `variables.tf`, `outputs.tf`, `backend.tf`, `RUNBOOK.md`, `README.md`, `backend.hcl.example`, `github.tfvars.example`. Esto introduce un **tercer patrón** en el layout de `infra/` (junto a `environments/<env>/` y `modules/`), justificado porque la superficie GitHub-side es por-organización: **se modifica este change** `sdd/steering/infra.md` §Convención de layout para nombrar explícitamente el patrón `infra/<superficie-cross-env>/` (GitHub-side hoy; DNS/org/policies futuras que tampoco son por entorno). El módulo `infra/github/` es su primer caso real, lo que cierra el patrón.

Rejected:
- **Dentro de `infra/environments/dev/`** — la superficie GitHub-side es por-organización, no por-entorno. Acoplarla al módulo dev obligaría a duplicarla en `staging`/`prod` cuando se decida proveedor para ellos, y crea un acoplamiento de orden (el `apply` de infra podría depender del `apply` de GitHub-side para que los secrets existan antes de que se ejecute el deploy).
- **Como `infra/modules/github/` compartido** — el steering solo crea `infra/modules/` cuando hay un primer módulo compartido entre entornos. La superficie GitHub-side no es compartida: se gestiona una vez por org, no por entorno. Meterla en `infra/modules/` introduce un patrón de "módulo compartido" que no aplica.
- **Esperar a que aparezca un segundo caso `infra/<superficie>/` antes de formalizar el patrón** — retrasaría este change sin motivo: la decisión sobre dónde vive GitHub-side es independiente del patrón en sí, y este change ya la necesita. El patrón se formaliza con su primer caso real, que es este.

### D2 — Auth del provider `integrations/github` por la misma GitHub App del runner

**Chosen:** El provider se autentica con la **misma GitHub App** que `infra/environments/dev/cloud-init.yaml.tftpl` usa para mintear el installation token del runner. Los valores `app_id` e `installation_id` llegan como variables Terraform (ya las tiene `dev.tfvars` hoy); la clave privada `.pem` se inyecta como variable **sensible** desde el workflow de CI, igual que `TF_VAR_github_app_private_key` se inyecta hoy para el `apply` de infra-dev.

Rejected:
- **Personal Access Token (PAT) de un owner** — introduce una credencial nueva (radio de daño: toda la cuenta del owner), no rotable automáticamente, y choca con la decisión de `ADR 0002` de no depender de cuentas personales.
- **GitHub App nueva dedicada al Terraform** — la App existente tiene los permisos que el provider requiere (`repository: read/write`, `members: read`, `packages: read/write` cuando aplique); añadir una segunda App duplica el bootstrap irreducible (cada App requiere creación manual y rotación de clave) sin un beneficio claro. La separación se haría si la App ganase permisos ajenos a Terraform, cosa que no se prevé.

### D3 — Backend de state en el bucket compartido `autohostai-tfstate-dev`, separado por `key`

**Chosen:** `backend.tf` declara el backend nativo `oci` con configuración parcial (`-backend-config`) apuntando al **mismo bucket** que el módulo dev (`autohostai-tfstate-dev`, ya creado por `infra/environments/dev/` con `versioning = enabled`), usando la `key = "github.tfstate"` para separar el state del state dev (`key = "dev.tfstate"`). Patrón estándar de Terraform — "un bucket, varios states": la separación entre los dos módulos es la `key`, no el bucket. **No introduce bootstrap irreducible** para este módulo en lo que al bucket se refiere: pre-requisito = el bucket existe y está versionado, lo cual ya está verificado por `infra/environments/dev/`.

Rejected:
- **State local** — pierde la propiedad central de "infra como código, recuperable, con drift detectable". Quedaría en la máquina del runner.
- **Bucket separado `autohostai-tfstate-github`** — propuesta original de D3, revisada tras pushback del usuario. Un bucket separado añade un objeto OCI más (bootstrap irreducible adicional, mismo motivo que el dev), una IAM policy más, y un segundo blast radius — sin un beneficio claro cuando los dos módulos comparten tenancy, owner y servicio `svc-terraform-dev`. La separación lógica por `key` dentro del mismo bucket ya da el aislamiento que importa (un `apply` de `infra/github/` solo lee/escribe `github.tfstate`; el `apply` de dev solo lee/escribe `dev.tfstate`; los `concurrency` se aplican por operación, no por bucket).
- **`pre-existing state` huérfano** — si por error alguien ejecutó antes un `apply` de `infra/github/` con otra `key` (p.ej. `terraform.tfstate` por defecto), ese state no se mezcla con `github.tfstate` (claves distintas = objetos distintos en OCI Object Storage). Confirmación de la separación: `oci os object list --bucket-name autohostai-tfstate-dev --prefix github.tfstate` debe devolver 0 objetos antes del primer `apply` de este módulo.

### D4 — Secrets: leer de Vault por nombre donde ya exista; sensibles en variable donde no

**Chosen:** Cada `github_actions_secret` se declara con su valor leído de una **variable Terraform sensible** (`type = string, sensitive = true`). Las variables se inyectan desde el workflow de CI mediante `TF_VAR_<nombre>` con `secrets.<nombre>` — igual que `TF_VAR_github_app_private_key_path` hoy para el dev module. Los secretos que **ya están en el Vault** (los `oci_vault_secret` que crea `infra/environments/dev/`) se quedan donde están: este módulo **no** los duplica en `github_actions_secret`. La duplicación abriría una superficie de drift entre el Vault (fuente de verdad para el runtime por instance principal) y los secrets de Actions (que el CD no usa para runtime), sin valor.

Sigue `sdd/steering/security.md` regla 8 (excepción dev/test, análoga a la que `infra-dev-terraform` ya ejerce sobre la clave de la App): la clave `.pem` de la GitHub App que recibe este módulo acaba en el `tfstate` de `infra/github/` — vive en el mismo bucket `autohostai-tfstate-dev` (privado + versionado + IAM mínima de `svc-terraform-dev`) bajo la `key = "github.tfstate"`, separado del state dev. Esto **no** introduce una relajación nueva: la clave ya está en el `tfstate` del dev module, y mantenerla en el mismo bucket (con `key` separada) es coherente con el patrón del módulo dev. Ámbito dev/test; antes de reutilizar el patrón en `staging`/`prod`, se revisará el gestor de secretos dedicado (compromiso heredado de `app-deploy-dev` y re-declarado en `infra-dev-terraform`).

Rejected:
- **Leer secretos directamente del Vault con un data source desde Terraform** — `oci_objectstorage`/`oci_secrets` no exponen un data source para "leer un secreto por nombre y devolverlo en claro". Lo más cercano (`oci_vault_secret`) es para **gestionar** secretos, no para consumirlos en otro `apply`.
- **Materializar los secretos en el `.tfvars`** — los `.tfvars` están pensados para valores no sensibles (el patrón del módulo dev: `oci_region`, `tenancy_ocid` y similares). Los secretos no deben versionarse y, si están en `.tfvars.example`, llevan un placeholder; los reales van por variable de entorno del workflow, igual que hoy.

### D5 — Branch protection: declarar lo que el plan Free soporte, documentar el resto

**Chosen:** Declarar `github_branch_protection` (o el recurso equivalente del provider vigente) sobre `main` con: required status checks (los nombres exactos de los checks que `infra-dev.yml`/`deploy-dev.yml`/etc. expongan en sus `permissions` o en el `if`/`needs`), required linear history, y `enforce_admins = true` si el provider lo permite en el tier Free. Lo que la API rechace se queda en el `plan` como nota y se documenta en el RUNBOOK como "regla no enforced por el plan Free; queda por convención".

Rejected:
- **No declarar branch protection en Terraform** — pierde la propiedad de "todo el repo es código": un cambio en la política de merge seguiría siendo un clic en la consola. La automatización parcial (lo que el Free soporta) es mejor que nada, y deja evidencia en el `plan` de qué falta.
- **Pedir GitHub Pro/Team para tener required reviewers** — el coste fijo del plan Pro/Team no se justifica solo por esta automatización, y `ADR 0002` ya documenta que el gate de aprobación sigue siendo "review del PR + apply manual desde main". Lo que se automatiza aquí es la parte automatizable; el gate humano se mantiene.

### D6 — Importación de recursos existentes en el primer `apply`, no recreación

**Chosen:** El primer `apply` es una **adopción** de los recursos que ya existen en el repo (settings, los once secrets de Actions ya creados con `gh secret set`, las cuatro variables de Actions enumeradas en R3.2 — `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `NEXT_PUBLIC_APP_ENV`, `PUBLIC_HOSTNAME` —, instalación de la GitHub App sobre el repo). El orden es: 1) declarar los recursos en Terraform con `lifecycle { create_before_destroy = false }` (el default), 2) ejecutar `terraform import <recurso> <id-real>` para cada recurso existente, 3) ejecutar `terraform plan` para verificar que el diff queda vacío. El procedimiento exacto (qué recurso se importa con qué identificador) se codifica en `infra/github/import.sh` (script versionado que imprime los `terraform import` listos para copiar/pegar, ejecutado una sola vez durante la fase de `/sdd:run`).

Rejected:
- **Borrar y recrear** — perdería el valor actual de los secrets (algunos son claves `.pem` que rotarían y obligarían a un re-deploy manual del runner); recrear `github_actions_secret` con un valor distinto invalida la credencial en el siguiente job que la lea.
- **Aceptar drift permanente** — el módulo declararía recursos que el repo no tiene en Terraform, sin evidencia en el `plan`. La propiedad "drift detectable con un `plan`" se pierde.

### D7 — Validación en CI por workflow nuevo, no extendiendo `infra-dev.yml`

**Chosen:** Crear `.github/workflows/infra-github.yml` con la misma estructura que `.github/workflows/infra-dev.yml`: un job `check` (paths-filtered sobre `infra/github/**`, sin secretos, en `ubuntu-latest`) para `pull_request`, y un workflow `workflow_dispatch` con `action: plan`/`apply` gateado por `if: github.ref == 'refs/heads/main'` (mismo gate que `infra-dev.yml` — el job mintea installation tokens y muta el repo, mismo modelo de amenaza que el cloud-side `apply`), ejecutado en el runner self-hosted `[self-hosted, dev]`, con `concurrency` y `timeout-minutes`. El job `check` reusa la imagen y el patrón de `infra-dev.yml` (mismo `terraform` por SHA de commit). El gate sobre `main` está motivado por la decisión estable de `steering/infra.md` §Decisión estable ("los jobs `plan` y `apply` del workflow de infra están acotados a `main`") — se re-aplica aquí sin reabrirla.

Rejected:
- **Extender `infra-dev.yml`** — mezcla dos dominios (cloud + GitHub-side) en un solo workflow; un cambio en `infra/github/**` no debe disparar un `check` que solo aplica a `infra/environments/dev/**`. La separación por paths-filter ya está en `infra-dev.yml` (`paths: ['infra/environments/dev/**']`) — replicar el patrón en su propio workflow es lo coherente.
- **Workflow genérico reutilizable** — `infra-dev.yml` no es genérico: hardcodea paths, secretos y `runs-on` específicos del dev. Crear uno genérico para añadirle luego `prod`/`staging` es futuro incierto.

### D8 — Provider `github` declarado en su propia sección `terraform {}` del módulo

**Chosen:** `main.tf` declara el provider `integrations/github` en su bloque `terraform { required_providers }`, con `source = "integrations/github"` y la versión que esté vigente al cierre del change. La autenticación se hace vía provider block `provider "github" { owner = var.github_owner }` con un bloque `auth {}` que use la App — la sintaxis exacta se fija en `tasks.md` mirando la doc del provider en su versión pinada.

Rejected:
- **Variables de entorno del runner** — la App con installation token tiene mejor seguridad (rotación automática), mejor auditabilidad (`installation_id` aparece en `audit_logs` de la App en GitHub) y se alinea con el patrón de `app-deploy-dev`. Las variables de entorno del runner (PAT) caerían en la regla 8 de `steering/security.md` como secreto en el entorno.
- **`provider "github"` sin autenticar en CI** — el `plan` funcionaría en CI (los data sources pueden correr sin auth en muchos providers), pero el `apply` real necesita auth. Mezclar auth por variable de entorno (para CI) y auth por App (para runner) crea dos configuraciones que divergen.

### D9 — Packages (GHCR): permisos a nivel App + settings a nivel repo, no un recurso dedicado

**Chosen:** El provider `integrations/github` v5.x **no expone** un recurso dedicado a "permitir el acceso a GHCR en este repo" (`github_repository_collaborators` gestiona colaboradores externos al repo, no packages; `github_repository_file` crea ficheros, no permisos). R4.2 se modela combinando tres piezas: (1) el permiso `packages: write` de la **App** (OQ1, parte de bootstrap irreducible — se concede manualmente en la config de la App), (2) los flags de acceso a packages del **repo**, que sí viven en `github_repository_settings` (R2) cuando el provider los expone en su versión pinada — `tasks.md` verifica el nombre exacto del atributo y, si no existe, lo documenta como limitación del provider, (3) un job `pull_request` del workflow `infra-github.yml` que publica una imagen efímera a `ghcr.io/autohostai-labs/<algo-de-prueba>` con etiqueta `ephemeral-<run_id>` y la borra al terminar — verificación end-to-end de que las dos piezas anteriores componen un acceso que funciona. Si (2) resulta no modelable en la versión pinada, queda como **`assumed` documentado** en `infra/github/RUNBOOK.md` §3 ("Rotación / Known limitations"): la flag de packages se gestiona fuera de Terraform y la verificación end-to-end es la única red; el cambio futuro del provider que añada ese atributo se aborda en un change aparte.

Rejected:
- **Forzar un modelado vía `github_repository_collaborators`** — modelaría permisos de personas sobre el repo (no packages), y el `plan` mostraría diff inocuo de "configuré el repo" cuando lo que cambia es un setting distinto. Falso positivo de drift.
- **No modelar nada** — la flag queda en la consola y un cambio futuro pasa desapercibido hasta que el CD falla. La verificación end-to-end cubre la **disponibilidad**, no la **ausencia silenciosa** del setting.
- **No modelarlo** — pierde la propiedad de "todo el repo es código": un cambio en la política de acceso a packages seguiría siendo un clic en la consola.

### D10 — `terraform plan` reproducible: pin de versión + `ignore_changes` defensivo

**Chosen:** `terraform { required_version = ">= 1.12" }` (ya presente en el snippet) más un `lifecycle { ignore_changes }` defensivo sobre atributos que el provider `integrations/github` puede derivar de timestamps o de contadores internos en cada `plan` (campos a verificar contra la doc del provider pinado — `tasks.md` los enumera con el nombre exacto del atributo). La verificación end-to-end (R1.4) es el `plan` post-`apply` (R7.3): si muestra diff no vacío, se documenta el campo que produce ruido y se ajusta `ignore_changes`.

Rejected:
- **Pin sin `ignore_changes`** — los providers maduros no suelen derivar timestamps en nombres de recursos, pero algunos exponen contadores o hashes en atributos que cambian entre planes. Sin `ignore_changes` defensivo, el primer run de "deploy from zero" (R7.3) puede mostrar un diff inocuo que no es drift real.
- **`ignore_changes` agresivo sobre todo** — esconde drift real. La lista se mantiene ajustada a los atributos derivados del provider, no a los que el módulo declara (esos deben aparecer en el `plan` si cambian).

## Changes by area

| Area | Files | Change |
|---|---|---|
| New module | `infra/github/main.tf` | Recursos `github_repository_settings`, `github_actions_secret`, `github_actions_variable`, `github_branch_protection`, `github_app_installation_repositories`, y el recurso de packages (D9) que el provider vigente ofrezca para el acceso a GHCR del repo. `lifecycle { ignore_changes = [...] }` defensivo sobre atributos derivados del provider (D10). Provider `integrations/github` autenticado por App. |
| New module | `infra/github/variables.tf` | Variables sensibles (`github_app_private_key_path`, los seis `oci_*` y los dos `tfstate_*`, `allowed_ssh_cidrs`, `allowed_ssh_cidrs_wide`, `ssh_public_keys`) y **no sensibles** (`github_app_id` y `github_app_installation_id` — son identificadores públicos, mismo patrón que `infra/environments/dev/variables.tf` líneas 196-199 y siguientes donde se documentan como "Identificador no sensible" sin `sensitive = true`; `github_owner`, `github_repository_name`, `github_repository_full_name`). Validación de CIDRs y de la clave SSH (mismas reglas que el módulo dev). `github_app_private_key_path` mapea desde el **mismo** GitHub Secret `GH_APP_PRIVATE_KEY` que `infra-dev` lee como `github_app_private_key` (contenido inline): el workflow escribe el secret a un fichero en `$RUNNER_TEMP` y pasa la ruta — patrón ya documentado en `infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados". |
| New module | `infra/github/outputs.tf` | `github_repository_full_name`, `github_repository_default_branch`, `github_app_installation_id`. Nunca valores de secrets. |
| New module | `infra/github/backend.tf` | Backend nativo `oci` con configuración parcial (`-backend-config`). Terraform `>= 1.12`. |
| New module | `infra/github/backend.hcl.example` | Plantilla sin valores reales (mismo patrón que el módulo dev). |
| New module | `infra/github/github.tfvars.example` | Placeholders para variables no sensibles; comentario explícito de que las sensibles van por `TF_VAR_*`. |
| New module | `infra/github/RUNBOOK.md` | Tres secciones: bootstrap irreducible (org, App con sus permisos, generación de `.pem`, rotación), qué cubre Terraform, cómo importar recursos existentes. |
| New module | `infra/github/README.md` | Propósito, estado, cómo correr `plan`/`apply` local y por CI. |
| New module | `infra/github/import.sh` | Script versionado que imprime los `terraform import` listos para copiar/pegar en el primer `apply`. |
| CI | `.github/workflows/infra-github.yml` | Workflow nuevo siguiendo el patrón de `infra-dev.yml`: `check` en `pull_request` (paths `infra/github/**`, sin secretos, `ubuntu-latest`) + `plan`/`apply` en `workflow_dispatch` con `if: github.ref == 'refs/heads/main'` (D7 — mismo gate que `infra-dev.yml`, no se relaja), runner self-hosted `[self-hosted, dev]`, `concurrency`, `timeout-minutes`. |
| Documentation | `infra/README.md` | Añadir `infra/github/` al árbol. |
| Documentation | `infra/environments/dev/RUNBOOK.md` §6 | Añadir referencia cruzada al nuevo `infra/github/RUNBOOK.md` para el bootstrap irreducible de la App. **No** cambiar el comportamiento del runner, solo el puntero. |
| Spec | `sdd/specs/infra-scaffold.md` | Nota sobre `infra/github/` como root module paralelo a los entornos. |
| Spec | `sdd/specs/infra-dev-terraform.md` | Nota de que la declaración de secrets/variables de Actions pasa a `infra/github/`. |
| Spec | `sdd/specs/app-deploy-dev.md` | Nota de que la lista de variables (`GH_APP_ID`/`GH_APP_INSTALLATION_ID`/`NEXT_PUBLIC_APP_ENV`/`PUBLIC_HOSTNAME`) se gestiona en `infra/github/`; este spec mantiene cómo se consumen en runtime. |
| Spec | `sdd/steering/infra.md` | Dos cambios: (1) §Convención de layout — añadir un tercer bullet `infra/<superficie-cross-env>/` para superficies por-organización (GitHub-side hoy; DNS/org/policies futuras), justificado con `infra/github/` como primer caso; (2) bajo "Lección de `app-deploy-dev`": añadir nota confirmando que el provider `github` ya está adoptado (la nota de "cambio futuro pendiente" queda obsoleta). |

## Data & interfaces

### Interfaces Terraform nuevas

```hcl
# Provider (main.tf)
terraform {
  required_version = ">= 1.12"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 5.0"  # versión pinada en tasks.md
    }
  }
}

provider "github" {
  owner = var.github_owner
  app_auth {
    id              = var.github_app_id               # identificador público (no sensitive)
    installation_id = var.github_app_installation_id  # identificador público (no sensitive, mismo patrón que dev)
    pem_file        = var.github_app_private_key_path # ruta, no inline (sensitive)
  }
}
```

```hcl
# Recurso: settings del repo (R2)
resource "github_repository_settings" "this" {
  repository = var.github_repository_name
  # description, topics, visibility, default_branch, ...
}

# Recurso: secret de Actions (R3) — patrón repetido 11 veces
resource "github_actions_secret" "oci_tenancy_ocid" {
  repository      = var.github_repository_name
  secret_name     = "OCI_TENANCY_OCID"
  plaintext_value = var.oci_tenancy_ocid  # sensitive = true
}

# Recurso: variable de Actions (R3) — patrón repetido N veces
resource "github_actions_variable" "gh_app_id" {
  repository    = var.github_repository_name
  variable_name = "GH_APP_ID"
  value         = var.github_app_id  # no sensible (es un ID público)
}

# Recurso: instalación de la App sobre el repo (R4) — `installation_id` se pasa por variable (ya validada en `app-deploy-dev`); el `data "github_app"` por `slug` solo se usaría si quisiéramos resolver el App ID por nombre (no es el caso aquí).
resource "github_app_installation_repositories" "this" {
  installation_id       = var.github_app_installation_id
  selected_repositories = [var.github_repository_full_name]
}
```

### Variables nuevas (resumen)

- Sensibles (`sensitive = true`): `github_app_private_key_path`, `oci_tenancy_ocid`, `oci_user_ocid`, `oci_fingerprint`, `oci_region`, `oci_private_key_path`, `oci_compartment_ocid`, `tfstate_namespace`, `tfstate_bucket`, `allowed_ssh_cidrs`, `allowed_ssh_cidrs_wide`, `ssh_public_keys`.
- No sensibles: `github_app_id` y `github_app_installation_id` (identificadores públicos, mismo patrón que `infra/environments/dev/variables.tf` — sin `sensitive = true`), `github_owner` (default `"autohostai-labs"`), `github_repository_name` (default `"AutoHostAI"`), `github_repository_full_name` (computado como `"${var.github_owner}/${var.github_repository_name}"`).

### Backend (backend.tf)

```hcl
terraform {
  backend "oci" {}  # configuración parcial vía -backend-config
}
```

`backend.hcl.example`:

```
namespace    = "<OCI_NAMESPACE>"
bucket       = "autohostai-tfstate-github"
region       = "<OCI_REGION>"
tenancy_ocid = "<TENANCY_OCID>"
user_ocid    = "<USER_OCID>"
fingerprint  = "<FINGERPRINT>"
private_key  = "<PRIVATE_KEY_BASE64_OR_PATH>"
```

(El bucket se crea una vez a mano, igual que `autohostai-tfstate-dev`.)

## Risks & mitigations

1. **El primer `apply` no detecta bien el "create" vs "import" para `github_actions_secret`.** Si el `terraform import` no se ejecuta en el orden correcto, el `apply` puede intentar recrear un secret con valor distinto y romper el CD. Mitigación: `import.sh` lista los imports en el orden exacto, con comentarios de qué ID usar (el ID del secret en GitHub es su nombre — `terraform import github_actions_secret.oci_tenancy_ocid OCI_TENANCY_OCID`). El `plan` post-import debe quedar vacío; cualquier diff es un bug del script.

2. **La rotación de la clave de la GitHub App.** El módulo declara la clave como variable sensible leída del path; rotar la clave requiere actualizar el path o el contenido de la variable **y** reaplicar el módulo de runner en `infra/environments/dev/` (porque el Vault también la usa). Mitigación: la rotación está documentada en `RUNBOOK.md` como procedimiento de dos pasos coordinados (Terraform + Vault), no automatizada para evitar race conditions entre los dos `apply`.

3. **Branch protection con required reviewers: la API puede rechazarlo en Free.** Mitigación: el `plan` lo dirá; el RUNBOOK documenta qué reglas quedan enforced técnicamente y cuáles por convención (D5). Aceptado por `ADR 0002`.

4. **El provider `integrations/github` puede cambiar su API entre versiones.** Mitigación: la versión se pinea en `required_providers` (D8), y `tasks.md` verifica contra la doc del provider en esa versión exacta al cierre del change. Cualquier bump de versión del provider queda para un change aparte.

5. **Drift entre `infra/github/` y la realidad de la consola de GitHub** (alguien cambia un setting a mano). Mitigación: misma que para `infra/environments/dev/` — un `terraform plan` desde `main` lo detecta. No hay automation extra: el `apply` se ejecuta por `workflow_dispatch` igual que el módulo dev.

6. **El secreto de la GitHub App queda en el `tfstate` de `infra/github/`** (igual que en `infra-dev-terraform` con la misma clave — `steering/security.md` regla 8, ámbito dev/test). Mitigación: el bucket `autohostai-tfstate-github` es privado, versionado, y la IAM del servicio `svc-terraform-dev` aplica. Mismo patrón que el bucket dev; no introduce una relajación nueva.

## Open questions

- **OQ1 — ¿La GitHub App existente tiene `packages: write`?** El provider `integrations/github` lo requiere para `github_repository_collaborators`/`packages`; la App del CD (`autohostai-dev-deployer`) puede que no lo tenga — los permisos exactos los tiene el RUNBOOK del CD. **Asumido** (recomendación + verificación documentada): la App ya tiene `packages: write` porque `deploy-dev.yml` usa `GITHUB_TOKEN` con `packages: write` para el push a GHCR, no la App; si no lo tiene, se añade manualmente en la configuración de la App antes del primer `apply`, y se documenta en `infra/github/RUNBOOK.md` §1 como parte del bootstrap irreducible. **Decisión tomada por auto: añadir el permiso a la App si falta, antes del primer `apply`**, documentado en RUNBOOK; no se modela el permiso en Terraform (no hay recurso `github_app_permissions` que aplique a una App ya creada con la versión vigente del provider).
- **OQ2 — ¿El recurso `github_repository_settings` existe en la versión pinada del provider?** El provider `integrations/github` v5.x introdujo este recurso como separación del viejo `github_repository` (que creaba repos, no los gestionaba). Si la versión pinada no lo tiene, se usa `github_repository` con `count = 0` (solo settings, no creación). **Asumido** (recomendación): se pinea `~> 5.0` y se usa `github_repository_settings`; si la versión pinada no lo tiene, `tasks.md` ajusta a la alternativa disponible y se documenta la razón. **Decisión tomada por auto: pinar `~> 5.0`; si la doc del provider en esa versión no lo expone, fallback a `github_repository` con `count = 0` declarado explícitamente**.