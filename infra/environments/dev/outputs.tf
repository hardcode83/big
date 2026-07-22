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
