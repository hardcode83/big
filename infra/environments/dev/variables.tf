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

variable "allowed_ssh_cidrs" {
  description = "Lista de CIDRs IPv4 de operadores permitidos para SSH (22) y los puertos de app (8000/3000). Cada origen acotado (prefijo >= /24), nunca un rango abierto. Añadir un operador no requiere recrear la instancia."
  type        = list(string)

  validation {
    # Cada elemento: formato estricto n.n.n.n/n (rechaza IPv6 y rangos amplios por el prefijo >= /24).
    condition = alltrue([
      for c in var.allowed_ssh_cidrs :
      can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$", c)) && tonumber(split("/", c)[1]) >= 24
    ])
    error_message = "Cada CIDR de allowed_ssh_cidrs debe ser IPv4 válido con prefijo >= /24 — rangos abiertos como 0.0.0.0/0 no están permitidos."
  }
}

variable "ssh_authorized_keys" {
  description = "Lista de claves públicas SSH autorizadas (una por operador), inyectadas vía cloud-init al usuario por defecto de la imagen (ubuntu). Cada par dedicado a esta VM — distinto de la API key de OCI del provider/backend, nunca reutilizar. Por ahora solo la de Jose; añadir más no requiere recrear."
  type        = list(string)

  validation {
    condition     = length(var.ssh_authorized_keys) > 0 && alltrue([for k in var.ssh_authorized_keys : can(regex("^ssh-(ed25519|rsa) ", k))])
    error_message = "ssh_authorized_keys no puede estar vacía y cada clave debe empezar por 'ssh-ed25519 ' o 'ssh-rsa '."
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
