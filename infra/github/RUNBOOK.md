# Runbook operativo — `infra/github/` (GitHub-side como código)

Procedimientos de operación/rotación de la superficie **GitHub-side** de `autohostai-labs/AutoHostAI`. Complementa al [`README.md`](./README.md) (uso del módulo) y al [`docs/adr/0002-github-org-hosting.md`](../../docs/adr/0002-github-org-hosting.md) (decisión de la org). Los cambios de este módulo se aplican **por el pipeline** (`workflow_dispatch` de `.github/workflows/infra-github.yml`), no con `terraform apply` local — mismo modelo de aprobación que describe [`infra/environments/dev/RUNBOOK.md` §0](../environments/dev/RUNBOOK.md).

Referencias rápidas: org `autohostai-labs` (plan **Free**) · repo `autohostai-labs/AutoHostAI` (**privado**) · provider `integrations/github` pinado a `~> 5.0` (resuelve a **v5.45.0**) · state en el bucket `autohostai-tfstate-dev`, key `github.tfstate` · **adopción de los recursos que ya existen en GitHub: [`import.sh`](./import.sh)** — imprime los `terraform import` del primer `apply` (once secrets + cuatro variables); se ejecuta **una sola vez**, procedimiento en [§2.4](#24-adopción-de-los-recursos-existentes-importsh).

> ⚠️ Este documento **no contiene ningún valor real** de credencial, OCID, fingerprint ni clave privada: todo va como placeholder `<...>`. Los valores viven en los GitHub Secrets/Variables del repo y en el OCI Vault del entorno.

## 1. Bootstrap irreducible (a mano, una vez)

Lo que la API de GitHub **no permite codificar** y, por tanto, no vive en Terraform. Se hace una vez, en este orden, antes del primer `apply` del módulo.

### 1.1 Crear la organización

Crear la org **`autohostai-labs`** en plan Free, con Marta y Jose como **owners** (decisión y motivos en `ADR 0002`). Terraform **no** crea la org (R4.4).

### 1.2 Transferir el repo a la org

Transferir `AutoHostAI` a `autohostai-labs/AutoHostAI`. Terraform **no** crea el repo (R2.3): el recurso `github_repository.this` **adopta** el repo existente vía import ([§2.4](#24-adopción-de-los-recursos-existentes-importsh)) y a partir de ahí gestiona sus settings.

### 1.3 Crear la GitHub App y concederle los permisos

Una **sola GitHub App** (la misma que usa el runner self-hosted del CD — decisión D2) autentica el provider `integrations/github`. Crearla desde **Settings de la org → Developer settings → GitHub Apps → New GitHub App**. Permisos de repositorio que necesita:

| Permiso | Nivel | Para qué |
|---|---|---|
| `Administration` | **write** | Registrar/retirar runners self-hosted y gestionar settings del repo. |
| `Contents` (repository) | **read/write** | Aplicar los merge flags y el resto de settings de `github_repository.this` (R1.5 falla rápido en el `plan` si falta). |
| `Secrets` / `Variables` (Actions) | **write** | Gestionar los once `github_actions_secret` y las cuatro `github_actions_variable`. |
| `Members` (org) | **read** | Requisito del provider para resolver el owner de la org. |
| `Packages` | **write** | OQ1 — ver la nota de abajo. |
| `Metadata` | read (implícito) | Lo concede GitHub automáticamente. |

> **Nota sobre `Packages: write` (OQ1).** El `docker push`/`pull` de GHCR del CD lo hace el **`GITHUB_TOKEN`** del propio job, **no** la App (así lo documenta [`infra/environments/dev/RUNBOOK.md` §6.1](../environments/dev/RUNBOOK.md)). El permiso se concede igualmente a la App porque es la pieza (1) del modelo de acceso a packages de D9 y porque el job `verify-ghcr` (sección 6 del change) verifica end-to-end que el acceso compone. Si la App no lo tiene, **añadirlo aquí, a mano, antes del primer `apply`**: no existe recurso Terraform que cambie los permisos de una App ya creada.

### 1.4 Generar la clave privada `.pem`

En la página de la App: **Private keys → Generate a private key**. GitHub descarga un `.pem` **una sola vez** (no se puede volver a descargar). Guardarlo fuera del repo; nunca commitearlo. Rotación: [§3.1](#31-rotar-la-clave-privada-de-la-github-app-dos-pasos-coordinados).

### 1.5 Instalar la App sobre el repo

Instalar la App en `autohostai-labs`, con acceso al repo `AutoHostAI`. **Esto no se modela en Terraform** (D11): el provider v5.45.0 documenta que `github_app_installation_repositories` es **incompatible** con la autenticación `app_auth` que D2 eligió. La instalación es una acción one-time y sin drift significativo; el job `verify-ghcr` detecta en runtime si la App pierde permisos.

Tras instalarla, anotar el **`installation_id`** (aparece en la URL de la instalación: `.../settings/installations/<installation_id>`) y el **`app_id`** (en la página de la App). Ambos son **identificadores públicos**, no secretos.

### 1.6 Dónde se inyectan `GH_APP_ID` / `GH_APP_INSTALLATION_ID` / `GH_APP_PRIVATE_KEY`

| Valor | Dónde vive | Cómo llega a Terraform |
|---|---|---|
| `app_id` | Variable de repo `GH_APP_ID` (pública) | `TF_VAR_github_app_id` ← `${{ vars.GH_APP_ID }}` → `var.github_app_id` |
| `installation_id` | Variable de repo `GH_APP_INSTALLATION_ID` (pública) | `TF_VAR_github_app_installation_id` ← `${{ vars.GH_APP_INSTALLATION_ID }}` → `var.github_app_installation_id` |
| contenido del `.pem` | **Secret** de repo `GH_APP_PRIVATE_KEY` | El workflow escribe el secret a un fichero en `$RUNNER_TEMP` y pasa la **ruta** en `TF_VAR_github_app_private_key_path` → `var.github_app_private_key_path` (`sensitive = true`), que el bloque `provider "github"` lee como `pem_file` |

El `.pem` **por ruta, nunca inline**: evita embeber un PEM multilínea en un string HCL (mismo patrón que `OCI_PRIVATE_KEY`). El secret `GH_APP_PRIVATE_KEY` es el **único secret-zero** del sistema; el módulo **no** lo declara como `github_actions_secret` (R3.3 + D2) — su gestión la mantiene el mismo mecanismo que `infra-dev.yml`.

Las dos variables públicas **sí** las gestiona este módulo como `github_actions_variable` ([§2.3](#23-variables-de-actions-r32--cuatro-github_actions_variable)): Terraform las adopta por import, no las inventa.

## 2. Lo que Terraform ya cubre

Todo lo que sigue está declarado en [`main.tf`](./main.tf) y se reconcilia en cada `apply`. Un cambio a mano en la consola de GitHub aparece como **drift** en el siguiente `plan`.

### 2.1 Settings del repo (R2) — `github_repository.this`

Un único recurso adopta el repo y gestiona: `description`, `homepage_url`, `topics`, `visibility` (`private`), `default_branch` (`main`), `has_issues`/`has_projects`/`has_wiki`, `archived`, y los **merge flags** (`allow_merge_commit`, `allow_squash_merge`, `allow_rebase_merge`, `allow_auto_merge`, `delete_branch_on_merge`).

> El provider v5.45.0 **no** expone `github_repository_settings` como recurso dedicado (OQ2 fallback): `github_repository` es el recurso que crea **y** gestiona settings. Como el repo ya existe y R2.3 prohíbe crearlo, se **importa** ([§2.4](#24-adopción-de-los-recursos-existentes-importsh)) y el recurso queda "managing" sin recrear nada.

### 2.2 Secrets de Actions (R3.1) — once `github_actions_secret`

Cada secret mapea 1:1 una variable Terraform marcada `sensitive = true` en [`variables.tf`](./variables.tf):

| Secret en GitHub | Recurso | Variable Terraform |
|---|---|---|
| `ALLOWED_SSH_CIDRS` | `github_actions_secret.allowed_ssh_cidrs` | `jsonencode(var.allowed_ssh_cidrs)` |
| `ALLOWED_SSH_CIDRS_WIDE` | `.allowed_ssh_cidrs_wide` | `jsonencode(var.allowed_ssh_cidrs_wide)` |
| `OCI_COMPARTMENT_OCID` | `.oci_compartment_ocid` | `var.oci_compartment_ocid` |
| `OCI_FINGERPRINT` | `.oci_fingerprint` | `var.oci_fingerprint` |
| `OCI_PRIVATE_KEY` | `.oci_private_key` | `file(var.oci_private_key_path)` |
| `OCI_REGION` | `.oci_region` | `var.oci_region` |
| `OCI_TENANCY_OCID` | `.oci_tenancy_ocid` | `var.oci_tenancy_ocid` |
| `OCI_USER_OCID` | `.oci_user_ocid` | `var.oci_user_ocid` |
| `SSH_PUBLIC_KEYS` | `.ssh_public_keys` | `jsonencode(var.ssh_public_keys)` |
| `TFSTATE_BUCKET` | `.tfstate_bucket` | `var.tfstate_bucket` |
| `TFSTATE_NAMESPACE` | `.tfstate_namespace` | `var.tfstate_namespace` |

**Qué NO se declara aquí, y por qué (R3.4):**

- **Los secretos de runtime que viven en el OCI Vault** (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, los de medios, los `SMTP_*`, el token del túnel, `DEMO_ACCOUNT_PASSWORD`): la fuente de verdad son los `oci_vault_secret` que crea `infra/environments/dev/`, y la app los lee por **instance principal**. Duplicarlos como secrets de Actions abriría una superficie de drift sin valor: dos sitios donde cambiar la misma contraseña y ninguna garantía de que coincidan.
- **`GH_APP_PRIVATE_KEY`**: el provider ya lee la clave desde `pem_file` (D2); el secret sigue existiendo porque lo consume `deploy-dev.yml`, pero su gestión queda fuera de este módulo ([§1.6](#16-dónde-se-inyectan-gh_app_id--gh_app_installation_id--gh_app_private_key)).

### 2.3 Variables de Actions (R3.2) — cuatro `github_actions_variable`

Ninguna es sensible (IDs públicos, un literal de entorno y un hostname DNS):

| Variable en GitHub | Recurso | Variable Terraform | Quién la consume |
|---|---|---|---|
| `GH_APP_ID` | `github_actions_variable.gh_app_id` | `var.github_app_id` | `infra-dev.yml` / `infra-github.yml` (auth del provider) |
| `GH_APP_INSTALLATION_ID` | `.gh_app_installation_id` | `var.github_app_installation_id` | idem |
| `NEXT_PUBLIC_APP_ENV` | `.next_public_app_env` | `var.next_public_app_env` | `deploy-dev.yml` — build-arg del frontend (se hornea en el bundle) |
| `PUBLIC_HOSTNAME` | `.public_hostname` | `var.public_hostname` | `deploy-dev.yml` — `FRONTEND_BASE_URL` del render de `.env` y build del frontend |

Las dos últimas llegan con default `""` y **validación fail-fast**: si el workflow no las inyecta, el `plan` falla nombrando la variable ausente en vez de propagar un valor vacío hasta el `apply`.

### 2.4 Adopción de los recursos existentes: `import.sh`

Los recursos de arriba **ya existen** en GitHub (creados a mano durante el bootstrap irreducible). El primer `apply` no los crea: los **importa**. El procedimiento exacto está codificado en [`import.sh`](./import.sh) (D6), versionado junto al módulo:

```bash
bash infra/github/import.sh            # imprime los comandos, no los ejecuta
bash infra/github/import.sh | bash     # los ejecuta (solo en el runner de CI, tras `terraform init` contra el backend real)
```

Formatos de ID (distintos por tipo de recurso en el provider v5.45.0 — confundirlos produce un `Error: parse ID`):

- `github_actions_secret.<n>` → `<repository>/<SECRET_NAME>` (**barra**)
- `github_actions_variable.<n>` → `<repository>:<VARIABLE_NAME>` (**dos puntos**)

El script cubre hoy esos **quince** recursos. El repo en sí (`github_repository.this`, [§2.1](#21-settings-del-repo-r2--github_repositorythis)) se adopta con un import adicional que **aún no está en el script** y se ejecuta a mano antes que el resto:

```bash
terraform -chdir=infra/github import github_repository.this AutoHostAI
```

Se ejecuta **una sola vez**. Tras el import, `terraform plan` debe quedar **vacío** sobre estos recursos; cualquier diff es un bug del script o un cambio a mano en la consola.

### 2.5 Lo que NO es un recurso de este módulo

| Superficie | Dónde vive | Por qué |
|---|---|---|
| Creación de la org y del repo | [§1.1](#11-crear-la-organización) / [§1.2](#12-transferir-el-repo-a-la-org) | Bootstrap irreducible (R2.3, R4.4). |
| Creación de la App y sus permisos | [§1.3](#13-crear-la-github-app-y-concederle-los-permisos) | La API no lo permite headless (R4.3); no hay recurso que altere una App ya creada. |
| Instalación de la App sobre el repo | [§1.5](#15-instalar-la-app-sobre-el-repo) | D11 — `github_app_installation_repositories` es incompatible con `app_auth`. |
| **Branch protection de `main`** | [§3.3](#33-branch-protection-convención-no-forzada) | **D5 enmendado** — la API la rechaza por completo en el plan Free. Es **convención no forzada**, no un recurso Terraform. |
| Flag de acceso a packages del repo | [§3.2](#32-packages--ghcr-la-flag-del-repo-no-es-modelable-d9) | No modelable en la versión pinada del provider (D9). |

## 3. Rotación / Known limitations

### 3.1 Rotar la clave privada de la GitHub App (dos pasos coordinados)

La misma clave la usan **dos** consumidores: el provider `integrations/github` de este módulo (por `pem_file`) y el runner self-hosted del CD (que la lee del **OCI Vault**, donde la escribe `infra/environments/dev/` como `oci_vault_secret.github_app_key`). Por eso la rotación es un procedimiento de **dos pasos coordinados, manual y no automatizado** — automatizarlo introduciría una race condition entre los dos `apply`.

Una GitHub App admite **varias claves privadas activas a la vez**: generar la nueva **antes** de revocar la vieja es lo que permite rotar sin ventana de caída.

1. **Generar** la nueva clave en la página de la App (**Private keys → Generate a private key**). **No borrar la anterior todavía.**
2. **Actualizar** el secret de repo `GH_APP_PRIVATE_KEY` con el contenido del `.pem` nuevo (`gh secret set GH_APP_PRIVATE_KEY < <ruta-al-pem-nuevo>`).
3. **Paso Vault** — re-aplicar `infra/environments/dev/` (`workflow_dispatch` de `infra-dev.yml`, `action=apply` desde `main`): reescribe el secret del Vault con la clave nueva. El runner la recoge en el siguiente mint de token; verificar en **Settings → Actions → Runners** que los agentes siguen **Idle** (procedimiento de recuperación en [`infra/environments/dev/RUNBOOK.md` §6.2](../environments/dev/RUNBOOK.md)).
4. **Paso Terraform GitHub-side** — lanzar `infra-github.yml` con `action=plan` y confirmar que autentica con la clave nueva y el plan queda vacío; después `action=apply` si hubiera algo que reconciliar.
5. **Solo con los dos pasos en verde**, borrar la clave antigua en la página de la App.

Si el paso 3 o el 4 falla, la clave vieja **sigue siendo válida**: revertir el secret y reintentar, sin prisa.

### 3.2 Packages / GHCR: la flag del repo no es modelable (D9)

El acceso del CD a `ghcr.io/autohostai-labs/*` se compone de tres piezas: (1) el permiso `Packages: write` de la **App** ([§1.3](#13-crear-la-github-app-y-concederle-los-permisos), bootstrap irreducible), (2) la **flag de acceso a packages del repo**, y (3) el job `verify-ghcr` que publica y borra una imagen efímera en cada PR como verificación end-to-end.

**Limitación asumida:** la pieza (2) **no es modelable** en la versión pinada del provider (`integrations/github` v5.45.0) — no existe un recurso que exprese "permitir el acceso a GHCR en este repo" (`github_repository_collaborators` gestiona colaboradores, no packages). Se gestiona **fuera de Terraform**, a mano, y la verificación end-to-end del job `verify-ghcr` es la única red. Un bump del provider que añada ese atributo se aborda en un change aparte.

### 3.3 Branch protection: convención NO forzada

**El módulo NO declara `github_branch_protection`** (D5 enmendado en la sección 4 del change `infra-github-iac`, decisión del usuario tras DESIGN-CONFLICT).

**Motivo, verificado en vivo el 2026-09-13:**

```console
$ gh api repos/autohostai-labs/AutoHostAI/branches/main/protection
403  "Upgrade to GitHub Pro or make this repository public"
```

La API rechaza el recurso **completo** mientras el repo siga **privado en el plan Free** — no solo el sub-bloque `required_pull_request_reviews` que la redacción original anticipaba. Declararlo haría fallar el `apply` entero, no producir "un rechazo con nota en el plan". La fuente de la restricción es el **plan/visibilidad del repo**, no un límite parcial del recurso. El mismo hecho ya estaba documentado en [`infra/environments/dev/RUNBOOK.md` §0](../environments/dev/RUNBOOK.md) desde antes de este change.

Las tres reglas que la protección habría forzado quedan como **convención no forzada** — exactamente el mismo estado que ya tiene "required reviewers" en el RUNBOOK del módulo dev. Lo que *debería* cumplirse, por acuerdo del equipo y no por enforcement técnico:

1. **Required status checks** — ningún PR se mergea con alguno de los **siete** checks always-run en rojo (nombres de **job**, no de workflow): `api-contract`, `backend-tests`, `compose-ports`, `frontend-api-contract`, `frontend-tests`, `rule11-ownership`, `version-parity`.
   Quedan **fuera a propósito** `infra-dev`, `infra-github` y `multiarch-build-check` (paths-filtered: no se reportan en los PR que no tocan esas rutas) y `deploy-dev` (solo `push: branches: [main]`, no `pull_request`). Marcar como required un check que no se reporta dejaría el PR bloqueado esperando para siempre — por eso, si algún día se retoma el recurso, la lista es esta y no "todos los workflows".
2. **Required linear history** — no mergear con merge commit desde la UI (squash o rebase). El CD dispara tras un `push` a `main`: un merge commit generaría un deploy sin un SHA de commit trazable a un PR.
3. **Sin bypass por administradores** (`enforce_admins`) — la regla aplica a los dos owners igual que a cualquiera; nadie sube directo a `main`.

⚠️ **Nada de lo anterior está forzado técnicamente**: alguien con push podría subir directo a `main`. Es un **modelo de confianza de dos personas**, el mismo que describe `infra/environments/dev/RUNBOOK.md` §0 para el gate de apply. Lo que **sí** está forzado es que el `apply` solo corre contra el código de `main` (`if: github.ref == 'refs/heads/main'`).

**Para forzarlo de verdad** hay exactamente dos caminos, ambos decisión de negocio fuera del alcance de este módulo: pasar la org a **GitHub Pro/Team**, o hacer el repo **público**. Cuando ocurra, un change futuro puede retomar `github_branch_protection` con este mismo contenido (la lista de checks de arriba y `required_linear_history = true` — con "d", el nombre que expone el provider v5.45.0 — más `enforce_admins = true`). El bloque de comentario de [`main.tf`](./main.tf) §R5 conserva la declaración prevista.

### 3.4 Otras limitaciones conocidas

- **`default_branch` deprecado**: el provider v5.45.0 marca el atributo `default_branch` de `github_repository` como `[DEPRECATED] Use the github_branch_default resource instead`. Se mantiene declarado (`validate` emite el warning); la migración al recurso dedicado queda para un change aparte.
- **`lifecycle { ignore_changes = [] }` defensivo (D10)**: la lista arranca **vacía** porque ningún atributo del bloque es derivado del provider. Si el primer `plan` post-`apply` muestra un diff **inocuo** y recurrente (un atributo que GitHub recalcula solo), añadir ese atributo a la lista en un PR propio, con la salida del `plan` como justificación — nunca a ciegas.
- **La clave `.pem` de la App queda en el `tfstate`** (relajación de `sdd/steering/security.md` regla 8, ámbito dev/test, ya aceptada para el módulo dev). Mitigación: el state vive en `autohostai-tfstate-dev` (privado, versionado, IAM mínima de `svc-terraform-dev`) bajo la key `github.tfstate`.

### 3.5 Pendiente

- Evidencia de **"deploy from zero"**: enlazar aquí el run de `infra-github.yml` (`action=apply` desde `main`) cuyo `plan` posterior quedó completamente vacío.
