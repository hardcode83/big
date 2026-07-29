terraform {
  required_version = ">= 1.12"

  required_providers {
    oci = {
      source = "oracle/oci"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
    # Ingress HTTPS del entorno (change ingress-https-dev). Comparte root module con oci a
    # propósito (design D1): el oci_vault_secret del token del túnel depende de atributos de
    # recursos Cloudflare, así que ambos tienen que estar en el mismo grafo.
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

locals {
  # Puertos publicados por docker-compose.yml (8000 backend, 3000 frontend) + SSH (22),
  # todos acotados a los CIDRs de operadores (ningún 0.0.0.0/0). Producto cartesiano CIDR × puerto.
  ingress_ports = [22, 8000, 3000]
  ingress_rules = flatten([
    for cidr in var.allowed_ssh_cidrs : [
      for port in local.ingress_ports : { cidr = cidr, port = port }
    ]
  ])
}

# --- Red ---
# Modelo VM única + docker-compose (ADR 0001) — una sola instancia, sin fragmentar en microservicios.

resource "oci_core_vcn" "dev" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.0.0.0/16"
  display_name   = "autohostai-dev-vcn"
  dns_label      = "autohostaidev"
}

resource "oci_core_internet_gateway" "dev" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.dev.id
  display_name   = "autohostai-dev-igw"
  enabled        = true
}

resource "oci_core_route_table" "dev_public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.dev.id
  display_name   = "autohostai-dev-public-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.dev.id
  }
}

# Puertos de docker-compose.yml (8000 backend, 3000 frontend) + SSH (22), todos acotados
# por CIDR de operador — una regla por (CIDR × puerto), sin ningún 0.0.0.0/0 de entrada.
resource "oci_core_security_list" "dev_public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.dev.id
  display_name   = "autohostai-dev-public-sl"

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  dynamic "ingress_security_rules" {
    for_each = local.ingress_rules
    content {
      protocol = "6" # TCP
      source   = ingress_security_rules.value.cidr
      tcp_options {
        min = ingress_security_rules.value.port
        max = ingress_security_rules.value.port
      }
    }
  }
}

resource "oci_core_subnet" "dev_public" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.dev.id
  cidr_block                 = "10.0.1.0/24"
  display_name               = "autohostai-dev-public-subnet"
  dns_label                  = "public"
  route_table_id             = oci_core_route_table.dev_public.id
  security_list_ids          = [oci_core_security_list.dev_public.id]
  prohibit_public_ip_on_vnic = false
}

# --- Cómputo ---
# Ampere A1, cupo Always Free completo (2 OCPU/12GB) — imagen resuelta por data source,
# nunca un OCID hardcodeado (los OCID de imagen cambian por región y con el tiempo).

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_instance" "dev" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domain.dev.name
  display_name        = "autohostai-dev"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 4
    memory_in_gbs = 24
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.dev_public.id
    assign_public_ip = false # la IP pública se asocia explícitamente vía oci_core_public_ip (reservada, no efímera)
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 200 # cupo free de block storage completo (200 GB); crecer la partición en el SO tras aplicar
  }

  metadata = {
    ssh_authorized_keys = join("\n", var.ssh_authorized_keys) # claves de todos los operadores; par(es) dedicado(s) a esta VM, distinto de la API key de OCI
    # cloud-init en cloud-init.yaml.tftpl: Docker (repo APT oficial, arm64) + runner self-hosted
    # (label ${var.env}) para el CD. El runner lee la clave de la GitHub App del Vault por
    # instance principal y mintea tokens efímeros (D13/R7).
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      env                        = var.env
      github_repo                = var.github_repo
      github_app_id              = var.github_app_id
      github_app_installation_id = var.github_app_installation_id
      app_key_secret_ocid        = oci_vault_secret.github_app_key.id
      pg_password_secret_ocid    = oci_vault_secret.postgres_password.id
      jwt_secret_ocid            = oci_vault_secret.jwt_secret_key.id
      encryption_key_secret_ocid = oci_vault_secret.encryption_key.id
      postgres_db                = var.postgres_db
      postgres_user              = var.postgres_user
      runner_bootstrap           = file("${path.module}/runner-bootstrap.sh")
      gh_app_token_helper        = file("${path.module}/gh-app-install-token.py")
    }))
  }

  lifecycle {
    # `metadata` (user_data/ssh_authorized_keys) es ForceNew en el provider oci: cambiarlo
    # recrearía la instancia (ruleta de capacidad + pérdida de datos). El cloud-init de aquí
    # define el arranque de una VM NUEVA (rebuild desde 0 correcto); sobre la instancia viva,
    # altas/rotaciones de clave y remediaciones se hacen out-of-band por SSH (ver RUNBOOK).
    ignore_changes = [metadata]
  }
}

data "oci_identity_availability_domain" "dev" {
  compartment_id = var.tenancy_ocid
  ad_number      = var.ad_number
}

# --- Instance principal para el runner self-hosted (R7) ---
# La instancia se autentica como instance principal para leer del Vault SIN credenciales en disco:
# la clave privada de la GitHub App (única secret-zero; la escribe Terraform al Vault desde
# var.github_app_private_key, un GitHub Secret del pipeline) y los secrets de runtime (generados
# por TF, arriba). Dynamic group que matchea SOLO esta instancia + policy de mínimo privilegio
# acotada a esos secrets concretos.
resource "oci_identity_dynamic_group" "dev_runner" {
  compartment_id = var.tenancy_ocid
  name           = "autohostai-${var.env}-runner"
  description    = "Instancia ${var.env} que ejecuta el runner self-hosted; lee del Vault por instance principal (clave de la GitHub App + secrets de runtime)."
  matching_rule  = "ALL {instance.id = '${oci_core_instance.dev.id}'}"
}

resource "oci_identity_policy" "dev_runner_read_secrets" {
  compartment_id = var.compartment_ocid
  name           = "autohostai-${var.env}-runner-read-secrets"
  description    = "Permite al runner ${var.env} leer SOLO la clave de la GitHub App, los secrets de runtime y el token del túnel en el Vault (mínimo privilegio)."
  statements = [
    # Enumeración explícita de OCID: un secreto nuevo es INVISIBLE para el runner hasta añadirlo
    # aquí. Es la causa de fallo más probable al sumar secretos (design D4).
    "Allow dynamic-group ${oci_identity_dynamic_group.dev_runner.name} to read secret-bundles in compartment id ${var.compartment_ocid} where any {target.secret.id = '${oci_vault_secret.github_app_key.id}', target.secret.id = '${oci_vault_secret.postgres_password.id}', target.secret.id = '${oci_vault_secret.jwt_secret_key.id}', target.secret.id = '${oci_vault_secret.encryption_key.id}', target.secret.id = '${oci_vault_secret.cloudflare_tunnel_token.id}'}",
    # El deploy resuelve el token del túnel POR NOMBRE (design D3: cloud-init no puede reescribir
    # /etc/autohostai-deploy.env en la VM viva, así que no hay dónde poner un OCID nuevo). Resolver
    # por nombre necesita además leer los metadatos del secreto, no solo su bundle.
    "Allow dynamic-group ${oci_identity_dynamic_group.dev_runner.name} to read secrets in compartment id ${var.compartment_ocid}",
  ]
}

data "oci_core_private_ips" "dev" {
  ip_address = oci_core_instance.dev.private_ip
  subnet_id  = oci_core_subnet.dev_public.id
}

resource "oci_core_public_ip" "dev" {
  compartment_id = var.compartment_ocid
  lifetime       = "RESERVED"
  display_name   = "autohostai-dev-public-ip"
  private_ip_id  = data.oci_core_private_ips.dev.private_ips[0].id
}

# --- Presupuesto (R5) ---
# Mitigación directa del riesgo de facturación bajo tenancy PAYG documentado en el ADR 0001.

resource "oci_budget_budget" "dev" {
  compartment_id = var.tenancy_ocid # el presupuesto se define a nivel de tenancy, aunque vigile un compartment
  display_name   = "autohostai-dev-budget"
  amount         = var.budget_amount
  reset_period   = "MONTHLY"
  target_type    = "COMPARTMENT"
  targets        = [var.compartment_ocid] # target_compartment_id está deprecado en favor de targets
}

# Dos alertas: ACTUAL (gasto real alcanza el presupuesto) y FORECAST (previsión del mes lo alcanza),
# ambas ABSOLUTE al importe del presupuesto, a los correos de Jose y Marta.
resource "oci_budget_alert_rule" "dev_actual" {
  budget_id      = oci_budget_budget.dev.id
  display_name   = "autohostai-dev-budget-alert-actual"
  type           = "ACTUAL"
  threshold_type = "ABSOLUTE"
  threshold      = var.budget_amount
  recipients     = join(",", var.budget_alert_recipients)
  message        = "AutoHostAI dev: el gasto REAL ha alcanzado el presupuesto mensual (${var.budget_amount})."
}

resource "oci_budget_alert_rule" "dev_forecast" {
  budget_id      = oci_budget_budget.dev.id
  display_name   = "autohostai-dev-budget-alert-forecast"
  type           = "FORECAST"
  threshold_type = "ABSOLUTE"
  threshold      = var.budget_amount
  recipients     = join(",", var.budget_alert_recipients)
  message        = "AutoHostAI dev: el gasto PREVISTO del mes alcanzará el presupuesto (${var.budget_amount})."
}

# --- Vault (R7): backup recuperable de la clave SSH ---
# Vault DEFAULT (partición compartida) + master key SOFTWARE → ambos Always Free (0€).
# El SECRET (la clave privada) NO se crea aquí: se sube out-of-band con OCI CLI para que
# el valor en claro no toque el tfstate (ver RUNBOOK). La policy de lectura para Jose/Marta
# va en la policy IAM del compartment (sección IAM / §6, aplicada por admin de tenancy).
resource "oci_kms_vault" "dev" {
  compartment_id = var.compartment_ocid
  display_name   = "autohostai-dev-vault"
  vault_type     = "DEFAULT"
}

resource "oci_kms_key" "dev_secrets" {
  compartment_id      = var.compartment_ocid
  display_name        = "autohostai-dev-secrets-key"
  management_endpoint = oci_kms_vault.dev.management_endpoint
  protection_mode     = "SOFTWARE"

  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

# --- Secrets de runtime generados por Terraform → Vault (D14 / R8) ---
# "Todo como código": los valores los genera TF y viven en el Vault (y en el tfstate, bucket
# privado+versionado — regla relajada en steering/security.md §8, dev/test). El deploy los lee
# del Vault por instance principal. La clave de la GitHub App NO se genera (no es aleatoria):
# también la escribe TF al Vault, desde var.github_app_private_key (recurso github_app_key, abajo).
resource "random_password" "postgres" {
  length  = 32
  special = false # evita caracteres que compliquen la URL de conexión
}

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "random_bytes" "encryption_key" {
  length = 32 # Fernet exige 32 bytes
}

locals {
  # cryptography.Fernet exige base64 URL-safe (alfabeto -_ en vez de +/). random_bytes.base64
  # es base64 estándar; el replace da exactamente la clave Fernet válida (44 chars, un '=').
  encryption_key_fernet = replace(replace(random_bytes.encryption_key.base64, "+", "-"), "/", "_")
}

resource "oci_vault_secret" "postgres_password" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-postgres-password"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.postgres.result)
  }
}

resource "oci_vault_secret" "jwt_secret_key" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-jwt-secret-key"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.jwt.result)
  }
}

resource "oci_vault_secret" "encryption_key" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-encryption-key"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(local.encryption_key_fernet)
  }
}

# --- Ingress HTTPS: Cloudflare Tunnel (change ingress-https-dev) ---
# El túnel abre una conexión SALIENTE desde la VM al edge de Cloudflare, que termina TLS con el
# certificado de la zona y entrega a frontend:3000 por la red interna del compose. No se abre
# ningún puerto entrante, así que el security list queda intacto (ADR 0003 / design D1).

resource "random_bytes" "tunnel_secret" {
  length = 32 # el provider exige >= 32 bytes para tunnel_secret
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "dev" {
  account_id = var.cloudflare_account_id
  name       = "autohostai-${var.env}"
  # Gestionado remotamente: las reglas de ingress viven en el recurso _config de abajo (declaradas
  # como código) en vez de en un fichero de configuración dentro de la VM.
  config_src    = "cloudflare"
  tunnel_secret = random_bytes.tunnel_secret.base64
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "dev" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.dev.id

  config = {
    ingress = [
      {
        hostname = var.public_hostname
        service  = "http://frontend:3000"
      },
      # Catch-all obligatoria y SIEMPRE la última: cualquier hostname que resuelva a este túnel y
      # no sea el previsto recibe 404, nunca la aplicación (R1.2).
      {
        service = "http_status:404"
      },
    ]
  }
}

# La zona se resuelve por su id para poder comprobar que coincide con el apex declarado.
data "cloudflare_zone" "dev" {
  zone_id = var.cloudflare_zone_id
}

resource "cloudflare_dns_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = var.public_hostname
  type    = "CNAME"
  # El destino se deriva del id del túnel: si el túnel se recreara, este registro se reconcilia en
  # el mismo apply en vez de quedar apuntando a un túnel muerto (R1.3, R1.6).
  content = "${cloudflare_zero_trust_tunnel_cloudflared.dev.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1 # obligatorio en el provider; 1 = automático, el único valor válido con proxied = true

  lifecycle {
    # Cierra la deuda de las dos fuentes de verdad de la zona (design D9). var.cloudflare_zone_name
    # solo se usa para validar la profundidad de public_hostname, pero el registro se crea en la
    # zona de var.cloudflare_zone_id: si ambas se desincronizan, la validación pasa y el hostname
    # acaba a más de un nivel del apex real → fuera del Universal SSL gratuito → aviso de
    # certificado en el navegador. El panel de seguridad demostró la elusión; esto la convierte en
    # un error de plan.
    precondition {
      condition     = data.cloudflare_zone.dev.name == var.cloudflare_zone_name
      error_message = "cloudflare_zone_name no coincide con el apex real de la zona de cloudflare_zone_id: la validación de profundidad de public_hostname estaría comprobando contra un dominio distinto al que se va a modificar."
    }
  }
}

# Token que consume cloudflared en la VM. El provider v5 NO expone un atributo `token`, solo acepta
# `tunnel_secret` de entrada, así que se compone a partir de datos que ya están en el grafo — el
# mismo patrón que la clave Fernet de arriba: recurso random + un local que lo lleva al formato que
# espera el consumidor. Nada se copia a mano del dashboard (design D2, R1.6).
locals {
  tunnel_token = base64encode(jsonencode({
    a = cloudflare_zero_trust_tunnel_cloudflared.dev.account_tag,
    t = cloudflare_zero_trust_tunnel_cloudflared.dev.id,
    s = random_bytes.tunnel_secret.base64,
  }))
}

# Único secreto de Cloudflare que llega a la VM. El API token del provider NO se guarda aquí:
# su radio es la zona entera y es re-emitible en segundos (R5.4 / design D10).
resource "oci_vault_secret" "cloudflare_tunnel_token" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-cloudflare-tunnel-token"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(local.tunnel_token)
  }
}

# --- HTTPS forzado en el edge (R3.1, R3.2) ---
# ALCANCE: estos ajustes son de ZONA, no de hostname — Cloudflare no los ofrece por hostname en el
# plan Free, así que aplican a TODO el apex, incluidos otros servicios que cuelguen de él.
# Consecuencia aceptada explícitamente en el gate del diseño (design D7).
# Un recurso por ajuste: el provider modela cada setting con su propio setting_id.

resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "min_tls_version" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = "1.2"
}

# Clave privada de la GitHub App: la escribe Terraform al Vault desde UN secret del pipeline
# (var.github_app_private_key). Así un entorno nuevo no requiere subirla a mano en OCI (D14/D13).
resource "oci_vault_secret" "github_app_key" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-gh-app-key"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.github_app_private_key)
  }
}
