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

# --- Almacén de objetos (change object-storage-provisioning) ---
# Los tres primeros son exactamente los valores que el backend necesita configurar (R1.4). Los
# cuatro siguientes son NOMBRES de secreto, no valores: el deploy los resuelve por nombre, y
# publicarlos como output da una única fuente de verdad al workflow y al RUNBOOK.
#
# NINGÚN output lleva el valor de la Customer Secret Key (R2.3). Tampoco su `id` —la mitad
# pública del par—, porque nadie lo consume: viaja al Vault y de ahí al `.env` de la VM.

output "media_bucket_name" {
  description = "Nombre del bucket privado de medios de este entorno. Es el valor de S3_BUCKET en el backend."
  value       = oci_objectstorage_bucket.media.name
}

output "media_region" {
  description = "Región del bucket de medios. Es el valor de S3_REGION; coincide con la región del resto del entorno."
  value       = var.region
}

output "media_s3_endpoint" {
  description = "Endpoint compatible con S3 del almacén de objetos, derivado del namespace de la tenancy y de la región (nunca escrito a mano). Es el valor de S3_ENDPOINT_URL."
  value       = local.media_s3_endpoint
}

output "media_access_key_secret_name" {
  description = "Nombre del secreto del Vault que guarda el AWS_ACCESS_KEY_ID del bucket. El deploy lo resuelve POR NOMBRE, igual que el token del túnel."
  value       = oci_vault_secret.media_access_key_id.secret_name
}

output "media_secret_key_secret_name" {
  description = "Nombre del secreto del Vault que guarda el AWS_SECRET_ACCESS_KEY del bucket. El NOMBRE, nunca el valor (R2.3)."
  value       = oci_vault_secret.media_secret_access_key.secret_name
}

output "media_endpoint_secret_name" {
  description = "Nombre del secreto del Vault que guarda el endpoint compatible con S3. Va al Vault porque es el único canal Terraform → VM que existe, no porque sea secreto."
  value       = oci_vault_secret.media_s3_endpoint.secret_name
}

output "media_region_secret_name" {
  description = "Nombre del secreto del Vault que guarda la región del bucket. Mismo motivo que el endpoint: canal, no confidencialidad."
  value       = oci_vault_secret.media_region.secret_name
}

output "cloudflare_tunnel_token_secret_name" {
  description = "Nombre del secreto del Vault que guarda el token del túnel. El job de deploy lo resuelve POR NOMBRE (get-secret-bundle-by-name), no por OCID, porque cloud-init no puede reescribir /etc/autohostai-deploy.env en la VM viva (design D3). Se expone como output para que el workflow y el RUNBOOK citen una única fuente de verdad."
  value       = oci_vault_secret.cloudflare_tunnel_token.secret_name
}
