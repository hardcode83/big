# Outputs del módulo `infra/github/` (change infra-github-iac, sección 1).
#
# Tres outputs, ninguno expone el valor de un secreto:
# - `github_repository_full_name` — nombre "owner/name" del repo. Valor
#   computado (`local.github_repository_full_name`) a partir de las dos
#   variables no sensibles.
# - `github_repository_default_branch` — placeholder `local.*` por ahora; la
#   sección 2 lo cablea al recurso `github_repository_settings.this`.
# - `github_app_installation_id` — placeholder `local.*` por ahora; la sección
#   2 lo cablea al recurso `github_app_installation_repositories.this`.
#
# Tenerlos como `local.*` ya en la sección 1 hace que `outputs.tf` sea
# sintácticamente válido y que `terraform validate` (gate de la tarea 1.8)
# pase sin anticipar nombres de atributos del provider pinado.

output "github_repository_full_name" {
  description = "Nombre completo del repo en GitHub (`owner/name`). Lo consume el workflow `deploy-dev.yml` para validar la instalación de la App sobre el repo correcto."
  value       = local.github_repository_full_name
}

output "github_repository_default_branch" {
  description = "Rama por defecto del repo (la que `github_repository_settings.this.default_branch` declara — placeholder en sección 1, cableado en sección 2)."
  value       = local.github_repository_default_branch
}

output "github_app_installation_id" {
  description = "ID de la instalación de la GitHub App sobre el repo. Placeholder en sección 1; cableado al recurso en sección 2. Nunca el valor de la clave privada (R1)."
  value       = local.github_app_installation_id
}