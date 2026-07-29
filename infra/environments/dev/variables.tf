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

variable "budget_alert_recipients" {
  description = "Lista de correos que reciben las alertas de presupuesto (ACTUAL y FORECAST). Obligatoria: sin destinatarios no se despliegan las alertas."
  type        = list(string)
  default     = ["josegascon@gmail.com", "mreyesojeda@gmail.com"]

  validation {
    condition     = length(var.budget_alert_recipients) > 0 && alltrue([for e in var.budget_alert_recipients : can(regex("^[^@[:space:]]+@[^@[:space:]]+$", e))])
    error_message = "budget_alert_recipients no puede estar vacía y cada entrada debe ser un email válido."
  }
}

variable "budget_amount" {
  description = "Presupuesto mensual (unidad de la tenancy) — límite absoluto sobre el que disparan las alertas ACTUAL y FORECAST."
  type        = number
  default     = 1
}

# Runner self-hosted (R7 — change app-deploy-dev)

variable "github_repo" {
  description = "owner/repo del repositorio GitHub cuyo runner self-hosted corre en la VM dev (para la URL de registro del runner)."
  type        = string
  default     = "autohostai-labs/AutoHostAI"
}

variable "env" {
  description = "Nombre del entorno (dev/test/staging/prod). Se interpola en los nombres de los recursos de CD para que el código sea reutilizable por entorno sin tocar nada a mano. Default dev → los nombres coinciden con los existentes (cero drift)."
  type        = string
  default     = "dev"
}

variable "github_app_id" {
  description = "ID de la GitHub App que mintea installation-tokens para registrar el runner y hacer pull de GHCR. Identificador no sensible. Una sola App vale para todos los entornos."
  type        = string
}

variable "github_app_installation_id" {
  description = "ID de la instalación de la GitHub App en el repo/owner. Identificador no sensible."
  type        = string
}

variable "github_app_private_key" {
  description = "Clave privada (.pem) de la GitHub App. Único secret-zero: vive como UN secret de GitHub Actions (org/repo), se inyecta por TF_VAR y Terraform la escribe al Vault de CADA entorno → un entorno nuevo no requiere pasos manuales en OCI. Su valor queda en el tfstate (bucket privado+versionado — relajación de security.md §8, solo dev/test)."
  type        = string
  sensitive   = true
}

variable "postgres_db" {
  description = "Nombre de la base de datos de la app en dev (no sensible)."
  type        = string
  default     = "autohostai"
}

variable "postgres_user" {
  description = "Usuario de Postgres de la app en dev (no sensible; la contraseña la genera Terraform → Vault)."
  type        = string
  default     = "autohostai"
}

# Ingress HTTPS vía Cloudflare Tunnel (change ingress-https-dev)

variable "cloudflare_api_token" {
  description = "API token de Cloudflare para el provider. Permisos mínimos: Account | Cloudflare Tunnel | Edit, Zone | DNS | Edit, Zone | Zone Settings | Edit, acotado a la zona gestionada. Bootstrap irreducible (se acuña en el dashboard, ver steering/infra.md): vive como GitHub Secret CLOUDFLARE_API_TOKEN e inyectado por TF_VAR. ATENCIÓN a su radio de daño: NO es un secreto de ámbito dev — con esos permisos sobre digitalsec.work puede reescribir el DNS y bajar el TLS de TODOS los servicios de la zona, no solo de este entorno. Por eso, a diferencia de la clave de la GitHub App, este token NO se copia al Vault: es re-emitible en segundos desde el dashboard, así que una copia 'recuperable' no aporta nada y en cambio lo metería en el tfstate, cuyo radio la excepción dev/test de security.md §8 no cubre. Terraform no persiste la configuración de provider, así que mientras no exista esa copia el token no llega al estado."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Account ID de Cloudflare — necesario para los recursos de túnel, que son de ámbito de cuenta y no de zona. Identificador no sensible."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Zone ID de la zona gestionada en Cloudflare. Tratado como sensible por convención del equipo, igual que en el resto de proyectos."
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_name" {
  description = "Apex de la zona en Cloudflare (p. ej. digitalsec.work). No sensible. Se usa para validar que public_hostname cuelga de esta zona a un solo nivel de profundidad."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9-]+\\.)+[a-z]{2,}$", var.cloudflare_zone_name))
    error_message = "cloudflare_zone_name debe ser un nombre de dominio válido en minúsculas, sin protocolo ni barra final (p. ej. digitalsec.work)."
  }
}

variable "public_hostname" {
  description = "Hostname público por el que se sirve la app del entorno. No es un secreto: es un nombre DNS público y su valor de dev se documenta en dev.tfvars.example y en el README. Debe colgar de cloudflare_zone_name a UN solo nivel, porque el certificado Universal SSL gratuito solo cubre el apex y los subdominios de primer nivel; más profundidad exigiría Total TLS o Advanced Certificate Manager, ambos de pago."
  type        = string

  validation {
    # Dos reglas, no una:
    # 1) UNA sola etiqueta bajo el apex (<etiqueta>.<zona>) — rechaza el apex desnudo, wildcards y
    #    cualquier profundidad extra que dejaría el hostname fuera del Universal SSL gratuito.
    # 2) La etiqueta debe empezar por "autohostai" — la zona es un dominio compartido con otros
    #    servicios y este valor llega de una variable de Actions editable sin PR; sin este prefijo,
    #    un cambio de esa variable podría redirigir un hostname ajeno (www, mail...) al túnel de
    #    este entorno en el siguiente apply. Permite autohostai, autohostai-staging, etc.
    condition = (
      endswith(var.public_hostname, ".${var.cloudflare_zone_name}") &&
      can(regex("^autohostai[a-z0-9-]*[a-z0-9]$|^autohostai$", trimsuffix(var.public_hostname, ".${var.cloudflare_zone_name}")))
    )
    error_message = "public_hostname debe ser UNA sola etiqueta bajo cloudflare_zone_name y empezar por 'autohostai' (p. ej. autohostai.digitalsec.work, autohostai-staging.digitalsec.work). El apex desnudo, los wildcards y los subdominios más profundos quedan fuera del Universal SSL gratuito; el prefijo evita apropiarse de un hostname ajeno de una zona compartida."
  }
}
