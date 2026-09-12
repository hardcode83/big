# Outputs del módulo `infra/github/` (change infra-github-iac, sección 2).
#
# Tres outputs, ninguno expone el valor de un secreto:
# - `github_repository_full_name` — nombre "owner/name" del repo. Valor
#   computado (`local.github_repository_full_name`) a partir de las dos
#   variables no sensibles.
# - `github_repository_default_branch` — cableado al recurso
#   `github_repository.this.default_branch` (sección 2).
# - `github_app_installation_id` — cableado al recurso
#   `github_app_installation_repositories.this.installation_id` (sección 2).

output "github_repository_full_name" {
  description = "Nombre completo del repo en GitHub (`owner/name`). Lo consume el workflow `deploy-dev.yml` para validar la instalación de la App sobre el repo correcto."
  value       = local.github_repository_full_name
}

output "github_repository_default_branch" {
  description = "Rama por defecto del repo (la que `github_repository.this.default_branch` declara — placeholder en sección 1, cableado al recurso real en sección 2)."
  value       = github_repository.this.default_branch
}

output "github_app_installation_id" {
  description = "ID de la instalación de la GitHub App sobre el repo. Cableado al recurso `github_app_installation_repositories.this.installation_id` en sección 2. Nunca el valor de la clave privada (R1)."
  value       = github_app_installation_repositories.this.installation_id
}
