# Variables del módulo `infra/github/` (change infra-github-iac, sección 1).
#
# Conteo verificado contra el §"Variables nuevas (resumen)" de `design.md`:
# 14 variables declaradas — 12 sensibles + 2 no sensibles (los placeholders que
# viajan en `github.tfvars.example`).
#
# Patrón de validación copiado de `infra/environments/dev/variables.tf`:
# - `allowed_ssh_cidrs` (mínimo /24) — el suelo por defecto para operadores.
# - `allowed_ssh_cidrs_wide` (mínimo /16) — excepción nombrada, suelo propio,
#   NO relaja la regla anterior.
# - `ssh_public_keys` — al menos una entrada, formato SSH válido.

# --- GitHub App: clave privada (sensible) ---
# Ruta al fichero `.pem` privado de la GitHub App que autentica el provider
# `integrations/github`. Por ruta, no inline: el workflow escribe el contenido
# del secret `GH_APP_PRIVATE_KEY` a un fichero en `$RUNNER_TEMP` y pasa la
# ruta, mismo patrón que `infra/environments/dev/` para `OCI_PRIVATE_KEY`.
# El valor acaba en el tfstate (relajación de `sdd/steering/security.md` regla
# 8, ámbito dev/test — mismo trato que la clave en el módulo dev).
variable "github_app_private_key_path" {
  description = "Ruta al fichero `.pem` con la clave privada de la GitHub App que autentica el provider `integrations/github`. Inyectado por el workflow vía `TF_VAR_github_app_private_key_path` desde el GitHub Secret `GH_APP_PRIVATE_KEY`."
  type        = string
  sensitive   = true
}

# --- Identidad OCI (sensible) ---
# Mismas seis variables que `infra/environments/dev/variables.tf`. El backend
# nativo `oci` también las consume (no puede leer `var.*`); los nombres
# coinciden a propósito para que la IAM del servicio `svc-terraform-dev`
# siga siendo el único origen de las credenciales.
variable "oci_tenancy_ocid" {
  description = "OCID de la tenancy de Oracle Cloud."
  type        = string
  sensitive   = true
}

variable "oci_user_ocid" {
  description = "OCID del usuario de Oracle Cloud usado por Terraform."
  type        = string
  sensitive   = true
}

variable "oci_fingerprint" {
  description = "Fingerprint de la clave API asociada al usuario."
  type        = string
  sensitive   = true
}

variable "oci_private_key_path" {
  description = "Ruta al fichero `.pem` de la clave privada de la API key de OCI. Se usa por ruta, no inline (mismo motivo que `github_app_private_key_path`)."
  type        = string
  sensitive   = true
}

variable "oci_region" {
  description = "Región OCI (identificador técnico, p. ej. `eu-frankfurt-1`)."
  type        = string
  sensitive   = true
}

variable "oci_compartment_ocid" {
  description = "OCID del compartment raíz de la tenancy (mismo que `autohostai-tfstate-dev` está)."
  type        = string
  sensitive   = true
}

# --- Backend de state (sensible por convención) ---
# Las dos variables las consume el `init -backend-config=`; marcadas sensibles
# para que un `terraform plan` no las filtre en logs aunque viajen por
# `TF_VAR_*` desde secrets.
variable "tfstate_namespace" {
  description = "Namespace de Object Storage donde vive el bucket `autohostai-tfstate-github` (lo imprime la consola de OCI)."
  type        = string
  sensitive   = true
}

variable "tfstate_bucket" {
  description = "Nombre del bucket de state. Hoy fijado a `autohostai-tfstate-github` (D3); se deja variable para no hardcodear el bootstrap irreducible en el módulo."
  type        = string
  sensitive   = true
}

# --- CIDRs / SSH (sensible: la IP de un operador es información personal) ---
# Mismas reglas que `infra/environments/dev/variables.tf` (validación estricta
# + suelo /24 vs /16). Cada entrada exige justificación en el PR que la añade.
variable "allowed_ssh_cidrs" {
  description = "Lista de CIDRs IPv4 de operadores permitidos para SSH (22). Cada origen acotado (prefijo >= /24), nunca un rango abierto."
  type        = list(string)
  sensitive   = true

  validation {
    # Cada elemento: formato estricto n.n.n.n/n (rechaza IPv6 y rangos amplios por el prefijo >= /24).
    condition = alltrue([
      for c in var.allowed_ssh_cidrs :
      can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$", c)) && tonumber(split("/", c)[1]) >= 24
    ])
    error_message = "Cada CIDR de allowed_ssh_cidrs debe ser IPv4 válido con prefijo >= /24 — rangos abiertos como 0.0.0.0/0 no están permitidos."
  }
}

variable "allowed_ssh_cidrs_wide" {
  description = "EXCEPCIÓN NOMBRADA al mínimo de /24 de `allowed_ssh_cidrs`, para operadores con IP dinámica cuyo ISP no da un rango estrecho. Mismo suelo /16 que el módulo dev — la excepción tiene su propio suelo para que no acabe significando \"sin límite\". Vacía por defecto."
  type        = list(string)
  default     = []
  sensitive   = true

  validation {
    condition = alltrue([
      for c in var.allowed_ssh_cidrs_wide :
      can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$", c)) && tonumber(split("/", c)[1]) >= 16
    ])
    error_message = "Cada CIDR de allowed_ssh_cidrs_wide debe ser IPv4 válido con prefijo >= /16. Un rango más ancho que /16 no es una excepción, es abrir el puerto."
  }
}

variable "ssh_public_keys" {
  description = "Lista de claves públicas SSH autorizadas (una por operador). Cada par dedicado — nunca reutilizar la API key de OCI. Solo el contenido de las `.pub`; la privada se queda en la máquina del operador (copia recuperable en el Vault, ver RUNBOOK del módulo dev)."
  type        = list(string)
  sensitive   = true

  validation {
    condition     = length(var.ssh_public_keys) > 0 && alltrue([for k in var.ssh_public_keys : can(regex("^ssh-(ed25519|rsa) ", k))])
    error_message = "ssh_public_keys no puede estar vacía y cada clave debe empezar por 'ssh-ed25519 ' o 'ssh-rsa '."
  }
}

# --- Identificadores públicos (no sensibles) ---
# Mismo patrón que `infra/environments/dev/variables.tf`: los IDs públicos del
# repo y de la GitHub App no son secretos — son nombres que aparecen en la URL
# del repo y en la config de la App — y por eso llevan default versionado o
# llegan en `github.tfvars` sin `sensitive = true`.
variable "github_owner" {
  description = "Owner/org en GitHub donde vive el repo. Default `autohostai-labs` (la org destino de la migración registrada en `ADR 0002`)."
  type        = string
  default     = "autohostai-labs"
}

variable "github_repository_name" {
  description = "Nombre del repo en GitHub. Default `AutoHostAI`."
  type        = string
  default     = "AutoHostAI"
}