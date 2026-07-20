# Identidad OCI — sin valores por defecto reales (security.md #8: solo el nombre, nunca el valor).
# Inyectadas vía TF_VAR_* desde secrets de GitHub Actions, o localmente vía backend.hcl/tfvars no versionado.

variable "tenancy_ocid" {
  description = "OCID de la tenancy de Oracle Cloud."
  type        = string
}

variable "user_ocid" {
  description = "OCID del usuario de Oracle Cloud usado por Terraform."
  type        = string
}

variable "fingerprint" {
  description = "Fingerprint de la clave API asociada al usuario."
  type        = string
}

variable "private_key_path" {
  description = "Ruta al fichero .pem de la clave privada de la API key. Se usa por ruta, no por contenido inline: evita el riesgo de sintaxis HCL de embeber un PEM multilínea en un string/heredoc (hallazgo de revisión — ver design.md)."
  type        = string
}

variable "region" {
  description = "Región OCI (identificador técnico, p. ej. eu-frankfurt-1)."
  type        = string
}

variable "compartment_ocid" {
  description = "OCID del compartment donde se aprovisionan los recursos de dev."
  type        = string
}

variable "ad_number" {
  description = "Número de Availability Domain (1-based) dentro de la región donde crear la instancia. Configurable para reintentar en otra AD si Oracle devuelve 'Out of host capacity' en la elegida — riesgo ya documentado en el ADR 0001. No hay reintento automático nativo en Terraform/OCI (a diferencia de un ASG en AWS); se reintenta cambiando este valor."
  type        = number
  default     = 1
}

# Red

variable "allowed_ssh_cidr" {
  description = "CIDR IPv4 permitido para SSH (puerto 22) a la instancia — origen conocido y acotado, nunca un rango abierto."
  type        = string

  validation {
    # Formato estricto n.n.n.n/n (rechaza IPv6 tipo ::/0 y espacios finales por el anclado ^...$)
    # + prefijo >= /24: excluye estructuralmente 0.0.0.0/0, 0.0.0.0/1 y cualquier rango igual de amplio,
    # en vez de comparar solo contra el literal "0.0.0.0/0".
    condition = (
      can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$", var.allowed_ssh_cidr)) &&
      tonumber(split("/", var.allowed_ssh_cidr)[1]) >= 24
    )
    error_message = "allowed_ssh_cidr debe ser un CIDR IPv4 válido con prefijo >= /24 (origen conocido y acotado) — rangos abiertos como 0.0.0.0/0 no están permitidos."
  }
}

variable "ssh_public_key" {
  description = "Clave pública SSH (contenido, p. ej. de un fichero .pub) inyectada vía cloud-init para el usuario por defecto de la imagen (ubuntu). Par de claves dedicado a esta VM — distinto de la API key de OCI que usa el provider/backend de Terraform, nunca reutilizar la misma."
  type        = string

  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) ", var.ssh_public_key))
    error_message = "ssh_public_key debe ser el contenido de una clave pública SSH válida (empieza por 'ssh-ed25519 ' o 'ssh-rsa ')."
  }
}

# Presupuesto (R5)

variable "budget_alert_email" {
  description = "Destinatario de la alerta de presupuesto. Obligatoria: sin destinatario no se despliega la alerta."
  type        = string

  validation {
    condition     = length(trimspace(var.budget_alert_email)) > 0
    error_message = "budget_alert_email es obligatorio — no se despliega una alerta de presupuesto sin destinatario."
  }
}

variable "budget_amount" {
  description = "Umbral de presupuesto mensual (USD) sobre el que se calcula la alerta."
  type        = number
  default     = 10
}

variable "budget_alert_threshold_percent" {
  description = "Porcentaje del presupuesto que dispara la alerta (tipo ACTUAL)."
  type        = number
  default     = 80
}
