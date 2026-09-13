# Módulo `infra/github/` (change infra-github-iac, secciones 2 + 3).
#
# En esta sección se cablea el provider `integrations/github` autenticado por
# la misma GitHub App del runner (D2) y se declaran los recursos que R2/R4
# piden: `github_repository` (OQ2 fallback — `github_repository_settings`
# no existe en la versión pinada v5.45.0, ver `## Implementation Notes`).
#
# NOTA: la instalación de la GitHub App sobre el repo NO se modela como
# recurso Terraform — el provider v5.45.0 documenta que
# `github_app_installation_repositories` es incompatible con `app_auth`
# (que es la autenticación de este provider por D2). La instalación es
# bootstrap irreducible (D11) y se documenta en RUNBOOK.md §1.

terraform {
  required_version = ">= 1.12"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 5.0"
    }
  }
}

provider "github" {
  owner = var.github_owner

  # Auth por la misma GitHub App que el runner usa (D2). `app_auth` se
  # autodetecta cuando sus tres campos están poblados (modo "auto" del
  # provider); no hace falta `auth_mode = "app"` explícito (la sintaxis de
  # referencia del design.md no lo incluye).
  app_auth {
    id              = var.github_app_id               # identificador público
    installation_id = var.github_app_installation_id  # identificador público
    pem_file        = var.github_app_private_key_path # ruta, no inline (sensitive)
  }
}

locals {
  # `github_repository_full_name` es por diseño un valor computado (D1: el owner
  # y el nombre son configurables; el nombre "completo" no es independiente).
  # Vive aquí para que `outputs.tf` ya pueda exponerlo y para que el primer
  # `terraform plan` post-apply no necesite tocar este fichero.
  github_repository_full_name = "${var.github_owner}/${var.github_repository_name}"
}

# R2 — settings del repo (description, homepage, topics, visibility,
# default_branch, has_issues/has_projects/has_wiki, archived, merge flags).
# El provider `integrations/github` v5.45.0 NO expone `github_repository_settings`
# como recurso dedicado (verificado contra `website/docs/r/` del tag v5.45.0 y
# contra `## Implementation Notes`); por OQ2 fallback se usa
# `github_repository` con `count = 1` y se importa el repo existente en el
# primer apply (procedimiento en `import.sh`, sección 3/5).
#
# El repo NO se crea desde Terraform: R2.3 prohíbe la creación (bootstrap
# irreducible, R6). `name` se usa para que el provider haga
# `Repositories.Get` y adopte los settings del repo ya existente; el
# recurso queda "managing" el repo, sin recrearlo, mientras ningún atributo
# del bloque cambie.
#
# Merge flags (R2.1 + D11 adyacente): para que el provider aplique estos
# flags en un `apply`, la GitHub App de autenticación debe tener
# `contents: write`. R1.5 fail-fast en el primer `plan` con mensaje
# nombrando el permiso ausente — no se llega a un `apply` parcial.
# Valores leídos del repo vivo `autohostai-labs/AutoHostAI` el 2026-09-12
# (`gh api /repos/autohostai-labs/AutoHostAI | jq '{...merge flags...}'`):
# allow_merge_commit=true, allow_squash_merge=true, allow_rebase_merge=true,
# allow_auto_merge=false, delete_branch_on_merge=false.
resource "github_repository" "this" {
  name = var.github_repository_name

  description  = "AutoHostAI monorepo — backend (FastAPI + Postgres + Celery) and frontend (Next.js) for short-stay rental automation."
  homepage_url = ""

  topics = []

  visibility     = "private"
  default_branch = "main"

  has_issues   = true
  has_projects = false
  has_wiki     = false

  archived = false

  # Merge flags (R2.1) — leídos del repo vivo el 2026-09-12; el App debe
  # tener `contents: write` para que el provider los pueda aplicar (R1.5).
  allow_merge_commit     = true
  allow_squash_merge     = true
  allow_rebase_merge     = true
  allow_auto_merge       = false
  delete_branch_on_merge = false

  # D10 — `lifecycle { ignore_changes = [] }` defensivo. Lista inicial vacía
  # porque la doc del provider v5.45.0 no expone atributos derivados de
  # timestamps/contadores en estos campos (todos los del bloque son user-set);
  # se rellena si el primer `plan` post-apply muestra diff inocuo (procedimiento
  # completo en §"Rotación / Known limitations" del RUNBOOK, sección 5).
  lifecycle {
    ignore_changes = []
  }
}

# =============================================================================
# R3 — Secrets de GitHub Actions declarados como código (sección 3).
# =============================================================================
#
# Los once `github_actions_secret` de abajo adoptan los secretos que ya existen
# en el repo (creados a mano con `gh secret set` durante el bootstrap irreducible).
# El primer `apply` no los CREA — los IMPORTA: el procedimiento exacto está
# codificado en `import.sh` (D6), ejecutado una sola vez durante esta sección
# y la 5 (RUNBOOK). Tras el import, `terraform plan` debe quedar vacío sobre
# estos recursos.
#
# Cada `plaintext_value` se lee de una variable Terraform marcada
# `sensitive = true` en `variables.tf`. El provider `integrations/github`
# marca `plaintext_value` como `Sensitive` (forzado en el schema, no declarado
# por nosotros), así que el tfplan no lo imprime — verificable con
# `terraform show -json | jq '.planned_values'` (R3.5).
#
# NO se declaran aquí los secretos que viven en el Vault (R3.4) — los
# `oci_vault_secret` que crea `infra/environments/dev/` son la fuente de verdad
# para el runtime (la app los lee por instance principal). Duplicarlos en
# Actions abriría una superficie de drift sin valor. RUNBOOK.md §2 (sección 5)
# explica el inventario completo y por qué cada uno se queda donde está.
#
# NO se declara `github_actions_secret` para `GH_APP_PRIVATE_KEY` (R3.3 +
# D2): la clave `.pem` de la GitHub App NO se inyecta como secret de Actions
# porque el provider `integrations/github` ya la lee directamente desde
# `pem_file = var.github_app_private_key_path`. El secret `GH_APP_PRIVATE_KEY`
# del repo sigue siendo necesario (lo consume `deploy-dev.yml`), pero su
# gestión queda fuera de este módulo — la mantiene el mismo mecanismo que
# `infra-dev.yml`.
#
# Lista de los once (mismo inventario que `infra/environments/dev/README.md`
# §"Secrets de GitHub Actions esperados", sin los históricos `ALLOWED_SSH_CIDR`
# y `SSH_PUBLIC_KEY` singulares — esos ya están migrados a las formas plurales
# que el workflow prefiere):
#
#   ALLOWED_SSH_CIDRS, ALLOWED_SSH_CIDRS_WIDE, OCI_COMPARTMENT_OCID,
#   OCI_FINGERPRINT, OCI_PRIVATE_KEY, OCI_REGION, OCI_TENANCY_OCID,
#   OCI_USER_OCID, SSH_PUBLIC_KEYS, TFSTATE_BUCKET, TFSTATE_NAMESPACE
#
# Serialización:
# - Las tres listas (`ALLOWED_SSH_CIDRS`, `ALLOWED_SSH_CIDRS_WIDE`,
#   `SSH_PUBLIC_KEYS`) llegan a Terraform como JSON arrays vía `TF_VAR_*` desde
#   el workflow (mismo patrón que `infra-dev.yml`). Aquí se vuelven a serializar
#   con `jsonencode()` para producir el string que el provider envía a la API
#   de Actions — el consumidor (cloud-init / tfvars) espera JSON idéntico al
#   que el workflow le pasa, así que el round-trip es seguro.
# - `OCI_PRIVATE_KEY` viaja por RUTA en la variable (`oci_private_key_path`,
#   `type = string, sensitive = true`): el workflow escribe el contenido del
#   secret `OCI_PRIVATE_KEY` a un fichero en `$RUNNER_TEMP` y pasa la ruta
#   (mismo patrón que `github_app_private_key_path` y que `infra-dev.yml`).
#   `file()` lee el PEM sin filtrarlo a un heredoc HCL.

# 1. ALLOWED_SSH_CIDRS — array JSON de CIDRs /24+ (variable: list(string)).
resource "github_actions_secret" "allowed_ssh_cidrs" {
  repository      = var.github_repository_name
  secret_name     = "ALLOWED_SSH_CIDRS"
  plaintext_value = jsonencode(var.allowed_ssh_cidrs)
}

# 2. ALLOWED_SSH_CIDRS_WIDE — excepción nombrada al mínimo /24 (default []).
resource "github_actions_secret" "allowed_ssh_cidrs_wide" {
  repository      = var.github_repository_name
  secret_name     = "ALLOWED_SSH_CIDRS_WIDE"
  plaintext_value = jsonencode(var.allowed_ssh_cidrs_wide)
}

# 3. OCI_COMPARTMENT_OCID — compartment raíz donde se aprovisionan los recursos.
resource "github_actions_secret" "oci_compartment_ocid" {
  repository      = var.github_repository_name
  secret_name     = "OCI_COMPARTMENT_OCID"
  plaintext_value = var.oci_compartment_ocid
}

# 4. OCI_FINGERPRINT — fingerprint de la API key del usuario `svc-terraform-dev`.
resource "github_actions_secret" "oci_fingerprint" {
  repository      = var.github_repository_name
  secret_name     = "OCI_FINGERPRINT"
  plaintext_value = var.oci_fingerprint
}

# 5. OCI_PRIVATE_KEY — contenido del `.pem` privado del provider y del backend
# `oci`. El workflow escribe el secret a un fichero temporal y pasa la ruta;
# aquí se lee con `file()` para evitar embeber un PEM multilínea en un string
# HCL (mismo motivo que `infra-dev.yml`).
resource "github_actions_secret" "oci_private_key" {
  repository      = var.github_repository_name
  secret_name     = "OCI_PRIVATE_KEY"
  plaintext_value = file(var.oci_private_key_path)
}

# 6. OCI_REGION — identificador técnico de la región (p. ej. `eu-frankfurt-1`).
resource "github_actions_secret" "oci_region" {
  repository      = var.github_repository_name
  secret_name     = "OCI_REGION"
  plaintext_value = var.oci_region
}

# 7. OCI_TENANCY_OCID — OCID de la tenancy.
resource "github_actions_secret" "oci_tenancy_ocid" {
  repository      = var.github_repository_name
  secret_name     = "OCI_TENANCY_OCID"
  plaintext_value = var.oci_tenancy_ocid
}

# 8. OCI_USER_OCID — OCID del usuario `svc-terraform-dev` (IAM mínima).
resource "github_actions_secret" "oci_user_ocid" {
  repository      = var.github_repository_name
  secret_name     = "OCI_USER_OCID"
  plaintext_value = var.oci_user_ocid
}

# 9. SSH_PUBLIC_KEYS — array JSON con las claves públicas, una por operador.
resource "github_actions_secret" "ssh_public_keys" {
  repository      = var.github_repository_name
  secret_name     = "SSH_PUBLIC_KEYS"
  plaintext_value = jsonencode(var.ssh_public_keys)
}

# 10. TFSTATE_BUCKET — nombre del bucket de state (`autohostai-tfstate-dev`,
# compartido con el módulo dev, separados por `key` — D3 amend).
resource "github_actions_secret" "tfstate_bucket" {
  repository      = var.github_repository_name
  secret_name     = "TFSTATE_BUCKET"
  plaintext_value = var.tfstate_bucket
}

# 11. TFSTATE_NAMESPACE — namespace de Object Storage donde vive el bucket.
resource "github_actions_secret" "tfstate_namespace" {
  repository      = var.github_repository_name
  secret_name     = "TFSTATE_NAMESPACE"
  plaintext_value = var.tfstate_namespace
}
