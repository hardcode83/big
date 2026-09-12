# Módulo `infra/github/` (change infra-github-iac, sección 2).
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
