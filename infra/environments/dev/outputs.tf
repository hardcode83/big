output "instance_public_ip" {
  description = "IP pública reservada de la instancia dev — input del futuro workflow de despliegue de la app (fuera de alcance de este change)."
  value       = oci_core_public_ip.dev.ip_address
}

output "instance_id" {
  description = "OCID de la instancia dev."
  value       = oci_core_instance.dev.id
}
