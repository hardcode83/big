output "instance_public_ip" {
  description = "IP pública reservada de la instancia dev — input del futuro workflow de despliegue de la app (fuera de alcance de este change)."
  value       = oci_core_public_ip.dev.ip_address
}

output "instance_id" {
  description = "OCID de la instancia dev."
  value       = oci_core_instance.dev.id
}

output "vault_id" {
  description = "OCID del Vault de dev — input para subir/recuperar el secret de la clave SSH por OCI CLI (ver RUNBOOK)."
  value       = oci_kms_vault.dev.id
}

output "vault_management_endpoint" {
  description = "Management endpoint del Vault dev (necesario para operaciones de KMS/secret por CLI)."
  value       = oci_kms_vault.dev.management_endpoint
}

output "secrets_key_id" {
  description = "OCID de la master key software que cifra los secrets del Vault."
  value       = oci_kms_key.dev_secrets.id
}

output "public_url" {
  description = "URL pública por la que se sirve la app del entorno, a través del Cloudflare Tunnel (change ingress-https-dev)."
  value       = "https://${var.public_hostname}"
}

output "cloudflare_tunnel_token_secret_name" {
  description = "Nombre del secreto del Vault que guarda el token del túnel. El job de deploy lo resuelve POR NOMBRE (get-secret-bundle-by-name), no por OCID, porque cloud-init no puede reescribir /etc/autohostai-deploy.env en la VM viva (design D3). Se expone como output para que el workflow y el RUNBOOK citen una única fuente de verdad."
  value       = oci_vault_secret.cloudflare_tunnel_token.secret_name
}
