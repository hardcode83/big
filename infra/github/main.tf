# Esqueleto del módulo `infra/github/` (change infra-github-iac, sección 1).
# Los recursos del provider `integrations/github` se declaran en secciones
# posteriores (2 en adelante). Aquí solo se fija el pin de Terraform y del
# provider, y los `local.*` que las `output` de la sección 1 ya prometen.

terraform {
  required_version = ">= 1.12"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 5.0"
    }
  }
}

locals {
  # `github_repository_full_name` es por diseño un valor computado (D1: el owner
  # y el nombre son configurables; el nombre "completo" no es independiente).
  # Vive aquí para que `outputs.tf` ya pueda exponerlo sin esperar a la sección
  # 2 — y para que el primer `terraform plan` post-apply no necesite tocar este
  # fichero (D10: pin + locales estables).
  github_repository_full_name = "${var.github_owner}/${var.github_repository_name}"

  # Placeholders para los outputs que se rellenarán en secciones 2+ cuando
  # existan los recursos `github_repository_settings.this` y
  # `github_app_installation_repositories.this`. Tenerlos como `local.*` ahora
  # permite que `outputs.tf` ya sea sintácticamente válido (y que
  # `terraform validate` pase — gate de la tarea 1.8) sin anticipar nombres de
  # atributos del provider pinado.
  github_repository_default_branch = "main"
  github_app_installation_id       = "0"
}