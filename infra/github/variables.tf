# Variables del módulo `infra/github/` (change infra-github-iac, secciones 1+2+4).
#
# Conteo verificado contra el §"Variables nuevas (resumen)" de `design.md`:
# 18 variables declaradas — 12 sensibles + 6 no sensibles.
# - Sección 1 añadió 14 (12 sensibles + 2 no sensibles: `github_owner`,
#   `github_repository_name`).
# - Sección 2 añadió 2 no sensibles (`github_app_id`, `github_app_installation_id`)
#   que la tarea 2.1 declara explícitamente sin `sensitive = true` por ser
#   IDs públicos (mismo patrón que el módulo dev).
# - Sección 4 añade 2 no sensibles más (`next_public_app_env`, `public_hostname`)
#   que alimentan las `github_actions_variable` que la tarea 4.1 declara; ambas
#   llegan con default `""` y validación fail-fast (R3.2).
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
  description = "Namespace de Object Storage donde vive el bucket de state (lo imprime la consola de OCI). Hoy `autohostai-tfstate-dev` (compartido con el módulo dev, key separada)."
  type        = string
  sensitive   = true
}

variable "tfstate_bucket" {
  description = "Nombre del bucket de state. Hoy fijado a `autohostai-tfstate-dev` (D3 amend: compartido con el módulo dev, separados por `key`); se deja variable para no hardcodear."
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

# --- Identificadores públicos de la GitHub App (no sensibles) ---
# IDs públicos del App y de su instalación sobre la org. Mismo patrón que
# `infra/environments/dev/variables.tf`: el `app_id` y el `installation_id`
# son nombres que aparecen en la URL de configuración de la App, NO secretos.
# Por eso llegan en `github.tfvars` sin `sensitive = true` y NO se filtran
# al loggear el provider. La clave privada `.pem` (el único secreto real)
# sigue por `github_app_private_key_path` con `sensitive = true` (D2).
variable "github_app_id" {
  description = "ID público de la GitHub App que autentica el provider `integrations/github`. La misma App que `infra/environments/dev/cloud-init.yaml.tftpl` usa para mintear el installation token del runner."
  type        = string
}

variable "github_app_installation_id" {
  description = "ID público (no sensible) de la instalación de la GitHub App sobre el repo/owner. El módulo NO declara `github_app_installation_repositories` (D11 — bootstrap irreducible: `github_app_installation_repositories` es incompatible con `app_auth` en el provider v5.45.0, documentado en `infra/github/RUNBOOK.md` §1); este valor lo aporta el operador porque la App ya está creada, registrada en la org e instalada sobre el repo."
  type        = string
}

# --- Variables de Actions que NO son IDs públicos (no sensibles) ---
# Las dos se inyectan como `github_actions_variable` (`NEXT_PUBLIC_APP_ENV`,
# `PUBLIC_HOSTNAME`) — sección 4 tarea 4.1 — y se consumen en runtime desde
# `deploy-dev.yml` (`build-args` del frontend) y desde el render de `.env`
# (`FRONTEND_BASE_URL`). El valor es información pública (un hostname DNS y
# un literal de entorno), NO un secreto, así que llegan como variables NO
# sensibles — mismo trato que `github_app_id` y `github_app_installation_id`
# arriba. El `sdd/steering/security.md` regla 8 (no secretos en el tfstate
# plano) NO se ve afectado: el tfstate guarda los valores que el operador
# pasó como variables, igual que guarda `github_app_id` hoy.
#
# Defaults `""` + validación fail-fast: el workflow de CI inyecta ambas vía
# `TF_VAR_*` desde `${{ vars.* }}` (mismo patrón que `infra-dev.yml`). Si el
# workflow no las inyecta —porque alguien reusó la plantilla y olvidó el
# `vars:` del job—, Terraform debe fallar **aquí**, con un mensaje que nombre
# la variable ausente, NO más tarde con un apply que crea la variable de
# Actions vacía y un `NEXT_PUBLIC_APP_ENV=""` horneado en el frontend.
variable "next_public_app_env" {
  description = "Valor de la variable de repo `NEXT_PUBLIC_APP_ENV` (env de runtime que Next.js exporta como `NEXT_PUBLIC_APP_ENV`). Default vacío para que `terraform plan` sin vars inyectadas falle aquí con un mensaje explícito en vez de seguir con un valor vacío hasta el `apply`."
  type        = string
  default     = ""

  validation {
    # Lista cerrada de entornos que el frontend distingue; cualquier valor fuera
    # de la lista se considera un error de configuración (typo en el dispatch
    # del workflow, p. ej. `prod` vs `production`). El coste de un valor
    # incorrecto es bajo (el badge muestra el literal erróneo), pero el coste
    # de silenciar typos es alto (un futuro `if APP_ENV == 'production'` que
    # nunca dispara). El default `""` queda FUERA de la lista para que
    # `terraform plan` sin vars inyectadas falle aquí — fail-fast en
    # validación, no en `apply` con un valor vacío propagado al frontend.
    condition     = contains(["dev", "staging", "production", "test"], var.next_public_app_env)
    error_message = "next_public_app_env debe ser uno de: dev, staging, production, test — el valor vacío (default) significa que el workflow no inyectó la variable y el plan debe fallar aquí, no propagar el vacío al apply."
  }
}

variable "public_hostname" {
  description = "Valor de la variable de repo `PUBLIC_HOSTNAME` (hostname DNS público bajo el que se sirve el frontend). Default vacío para que `terraform plan` sin vars inyectadas falle aquí con un mensaje explícito en vez de seguir con un valor vacío hasta el `apply`."
  type        = string
  default     = ""

  validation {
    # Forma de hostname DNS relajada: no exigimos TLD real (los entornos de
    # preview usan `.local`, `.test`, etc.) y aceptamos tanto un apex como un
    # subdominio. Lo que SÍ exigimos es no vacío: si el workflow no inyecta la
    # variable, el default `""` se queda con `length() == 0` y la validación
    # falla. La regex permite letras, dígitos, guion y punto; lo que un
    # hostname real puede llevar — el resto son artefactos de una inyección
    # accidental (espacios, saltos de línea, comillas).
    condition     = length(var.public_hostname) > 0 && can(regex("^[A-Za-z0-9.-]+$", var.public_hostname))
    error_message = "public_hostname no puede llegar vacío (default) y debe tener solo letras, dígitos, guion y punto — el valor vacío significa que el workflow no inyectó la variable y el plan debe fallar aquí, no propagar el vacío al apply."
  }
}