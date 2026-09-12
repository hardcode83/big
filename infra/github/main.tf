# Módulo `infra/github/` (change infra-github-iac, sección 2).
#
# En esta sección se cablea el provider `integrations/github` autenticado por
# la misma GitHub App del runner (D2) y se declaran los recursos que R2/R4
# piden: `github_repository` (OQ2 fallback — `github_repository_settings`
# no existe en la versión pinada v5.45.0, ver `## Implementation Notes`)
# y `github_app_installation_repositories`.

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
# default_branch, has_issues/has_projects/has_wiki, archived). El provider
# `integrations/github` v5.45.0 NO expone `github_repository_settings` como
# recurso dedicado (verificado contra `website/docs/r/` del tag v5.45.0 y
# contra `## Implementation Notes`); por OQ2 fallback se usa
# `github_repository` con `count = 1` y se importa el repo existente en el
# primer apply (procedimiento en `import.sh`, sección 3/5).
#
# El repo NO se crea desde Terraform: R2.3 prohíbe la creación (bootstrap
# irreducible, R6). `name` se usa para que el provider haga
# `Repositories.Get` y adopte los settings del repo ya existente; el
# recurso queda "managing" el repo, sin recrearlo, mientras ningún atributo
# del bloque cambie.
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

  # D10 — `lifecycle { ignore_changes = [] }` defensivo. Lista inicial vacía
  # porque la doc del provider v5.45.0 no expone atributos derivados de
  # timestamps/contadores en estos campos (todos los del bloque son user-set);
  # se rellena si el primer `plan` post-apply muestra diff inocuo (procedimiento
  # completo en §"Rotación / Known limitations" del RUNBOOK, sección 5).
  lifecycle {
    ignore_changes = []
  }
}

# R4 — instalación de la GitHub App sobre el repo. `installation_id` llega
# por variable (la App ya está creada y registrada en la org, bootstrap
# irreducible, R4.3/R4.4); `selected_repositories` referencia el repo por
# su nombre (NO full name — la doc del provider en v5.45.0 dice "list of
# repository names"; el provider hace `Repositories.Get(ctx, owner, repo)`
# con `owner` del bloque provider y `repo` = cada elemento de la lista).
# Ver `## Implementation Notes` por la discrepancia con la tarea original.
resource "github_app_installation_repositories" "this" {
  installation_id       = var.github_app_installation_id
  selected_repositories = [var.github_repository_name]
}
