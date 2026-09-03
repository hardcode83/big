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
  # SOLO SSH. Desde el change ingress-https-dev la app se sirve por Cloudflare Tunnel (conexión
  # saliente de la VM al edge), así que 8000 y 3000 dejaron de necesitar exposición: se retiraron
  # tras verificar que el túnel servía la app por HTTPS (R4.1, orden exigido por R4.4 — verificar y
  # después cerrar, nunca al revés). El 22 se mantiene acotado a los CIDRs de operadores y es la
  # única vía de entrada a la máquina; ningún 0.0.0.0/0. Producto cartesiano CIDR × puerto.
  ingress_ports = [22]
  # `allowed_ssh_cidrs` (mínimo /24) + `allowed_ssh_cidrs_wide` (excepción nombrada, mínimo /16).
  # Se concatenan aquí y no en una sola variable a propósito: cada lista tiene su propia validación,
  # así que un rango ancho no puede colarse por la puerta de la estrecha. Ver `variables.tf`.
  ingress_cidrs = concat(var.allowed_ssh_cidrs, var.allowed_ssh_cidrs_wide)
  ingress_rules = flatten([
    for cidr in local.ingress_cidrs : [
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

# Un único puerto de entrada: SSH (22), acotado por CIDR de operador — una regla por
# (CIDR × puerto), sin ningún 0.0.0.0/0 de entrada. Ver `local.ingress_ports` arriba: 8000 y 3000
# dejaron de abrirse aquí con el change `ingress-https-dev` (el acceso público llega por el túnel de
# Cloudflare, y esos puertos solo se publican en el loopback de la VM para depuración por SSH).
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
  # UN solo statement, y es deliberado (change ingress-https-hardening, design D5).
  #
  # Enumeración explícita de OCID, y NADA más: un secreto nuevo es INVISIBLE para el runner hasta
  # añadirlo aquí. Es la causa de fallo más probable al sumar secretos (design D4 de app-deploy-dev)
  # y se mantiene así a propósito, porque es el invariante que acota el acceso al CONTENIDO.
  #
  # OJO al ámbito antes de tocar la condición: `var.compartment_ocid` es hoy la RAÍZ de la tenancy
  # (ver dev.tfvars y la mejora futura de `iam-policy.md`), y una concesión en la raíz la heredan
  # todos los compartments descendientes. Por eso la condición va por OCID y no por nombre: los
  # nombres de secreto son únicos POR VAULT, no por compartment, así que un `target.secret.name`
  # aquí concedería lectura de contenido a cualquier secreto que se llamara igual en cualquier vault
  # de la tenancy — y el invariante de arriba dejaría de ser cierto para ese nombre.
  #
  # El deploy resuelve el token del túnel POR NOMBRE (`get-secret-bundle-by-name`, design D3 de
  # ingress-https-dev: cloud-init no puede reescribir /etc/autohostai-deploy.env en la VM viva, así
  # que no hay dónde poner un OCID nuevo), y la condición por OCID le basta: `GetSecretBundleByName`
  # exige SECRET_BUNDLE_READ, permiso que solo concede este statement, y el deploy lee por nombre
  # con éxito desde el 2026-07-29 — luego OCI resuelve nombre→OCID antes de autorizar. (Ese "solo
  # concede este statement" es una premisa sobre la tenancy que el repositorio no puede establecer,
  # porque hay policies aplicadas a mano; queda declarada en `iam-policy.md` con el comando que la
  # cierra. No la leas como hecho verificado.)
  #
  # Aquí hubo un segundo statement `read secrets in compartment` SIN condición, y se eliminó porque
  # nunca fue necesario: `read secrets` concede SECRET_INSPECT + SECRET_READ, es decir ListSecrets y
  # GetSecret, que el deploy no invoca en ningún momento. Tabla de permisos y razonamiento en
  # `iam-policy.md`; referencia: docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm
  #
  # Los cuatro secretos de medios (change object-storage-provisioning) entran aquí en el MISMO
  # apply que los crea, que es la mitigación del riesgo que el design declara: olvidarlos haría
  # fallar el paso «Render .env» del deploy nombrando la clave — el comportamiento correcto, pero
  # un viaje de ida y vuelta evitable.
  #
  # `demo_account_password` (change `demo-user`) entra por lo mismo y en el mismo apply que lo
  # crea. Su lector no es el deploy sino el workflow `demo-reset`, que lo resuelve **por nombre**
  # como hace el del túnel — así que le vale igual esta condición por OCID, por la razón escrita
  # arriba: `GetSecretBundleByName` exige el mismo permiso y OCI resuelve nombre→OCID antes de
  # autorizar.
  #
  # Los seis `smtp_*` (change `smtp-delivery-adapter`) entran por lo mismo y en el mismo apply
  # que los crea — mirror en `iam-policy.md`'s bloque de la policy del runner.
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.dev_runner.name} to read secret-bundles in compartment id ${var.compartment_ocid} where any {target.secret.id = '${oci_vault_secret.github_app_key.id}', target.secret.id = '${oci_vault_secret.postgres_password.id}', target.secret.id = '${oci_vault_secret.jwt_secret_key.id}', target.secret.id = '${oci_vault_secret.encryption_key.id}', target.secret.id = '${oci_vault_secret.cloudflare_tunnel_token.id}', target.secret.id = '${oci_vault_secret.media_access_key_id.id}', target.secret.id = '${oci_vault_secret.media_secret_access_key.id}', target.secret.id = '${oci_vault_secret.media_s3_endpoint.id}', target.secret.id = '${oci_vault_secret.media_region.id}', target.secret.id = '${oci_vault_secret.demo_account_password.id}', target.secret.id = '${oci_vault_secret.smtp_host.id}', target.secret.id = '${oci_vault_secret.smtp_port.id}', target.secret.id = '${oci_vault_secret.smtp_username.id}', target.secret.id = '${oci_vault_secret.smtp_password.id}', target.secret.id = '${oci_vault_secret.smtp_from_email.id}', target.secret.id = '${oci_vault_secret.smtp_use_tls.id}'}",
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

# La contraseña de las cuatro cuentas del tenant de demostración (change `demo-user`, design D12).
#
# `random_password` **no es la contraseña que se publica**: es el valor con el que el secreto nace
# para que nunca haya un default en el árbol, y para que un entorno recién aplicado tenga
# credenciales inertes en lugar de conocidas hasta que una persona fije las de verdad. La
# publicada la pone alguien out-of-band con `oci vault secret update-base64` (RUNBOOK), que es el
# mismo canal que la regla 8 de `steering/security.md` ya acepta para la clave SSH — y su forma la
# acordó el gate del design: una frase corta y dictable por teléfono, del orden de 15 caracteres,
# **por encima de `PASSWORD_MIN_LENGTH`** para que un visitante que la cambie pueda volver a
# ponerla desde `POST /auth/change-password`.
#
# `ignore_changes = [secret_content]` es exactamente lo que hace que ese valor sobreviva al apply
# siguiente. Y es el riesgo de cabecera del design: si el provider de OCI no lo respetara, cada
# apply devolvería la contraseña al valor generado y el reset siguiente la propagaría a las cuatro
# cuentas **en silencio**, dejando las credenciales publicadas sin funcionar. Se verifica con el
# primer `plan` teniendo ya el valor out-of-band puesto, **antes de publicar nada a nadie**: un
# `plan` que proponga reescribir `secret_content` es la señal. Si no aguanta, la salida escrita en
# Risks es no depender de `ignore_changes` —la publicada pasa a ser la que genera `random_password`,
# leída del Vault— y la rotación es `terraform apply -replace`.
resource "random_password" "demo_account" {
  length  = 24
  special = false # mismo motivo que las de arriba: nada que complique una URL ni un `.env`
}

resource "oci_vault_secret" "demo_account_password" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-demo-account-password"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.demo_account.result)
  }

  lifecycle {
    # El contenido lo gobierna una persona a partir del primer apply, no Terraform. Sin esto, el
    # valor publicado duraría hasta el siguiente `terraform apply`.
    ignore_changes = [secret_content]
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
# ALCANCE: este ajuste es de ZONA, no de hostname — Cloudflare no lo ofrece por hostname en el plan
# Free, así que aplica a TODO el apex. Se aceptó a sabiendas (design D7) tras inventariar la zona:
# de los 7 hosts publicados en digitalsec.work solo 3 son `proxied` (argocd, carto-api, ha) y por
# tanto solo esos tres se ven afectados; los que están en modo "DNS only" no pasan por el edge.
# Riesgo asumido: un cliente programático que llame por http:// y NO siga redirecciones recibiría
# un 301 en vez de la respuesta.
resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

# NO se declara `min_tls_version`. La zona está hoy en 1.0 y subirla a 1.2 concentraba casi todo el
# riesgo del change sobre servicios ajenos a él (rompería cualquier integración que solo hable TLS
# 1.0/1.1), sin aportar nada al ingress: el túnel no expone TLS del origen y el edge ya negocia
# TLS moderno con los navegadores. Decisión del 2026-07-29, ver design D7 y R3.2.
# Si algún día se sube, es un cambio de una línea aquí — y de alcance de zona, así que merece su
# propia decisión y su propia ventana de verificación.

# --- Almacén de objetos para las fotos (change object-storage-provisioning) ---
# El backend le habla por la API **compatible con S3** de OCI, con boto3 apuntado por endpoint_url
# y sin SDK de OCI en ninguna parte (R4.2). Elección de proveedor y matriz de alternativas en
# `docs/adr/0008-object-storage-provider-dev.md`.

# El namespace de Object Storage es propio de la tenancy y NO se escribe a mano (R1.1): es la
# primera etiqueta del host compatible y cambiarlo a mano es exactamente el desajuste que un data
# source no puede tener.
data "oci_objectstorage_namespace" "dev" {
  compartment_id = var.compartment_ocid
}

locals {
  # El endpoint compatible se DERIVA del namespace y de la región (D2), así que el mismo código
  # sirve en otro entorno sin editar ninguna URL. `oraclecloud.com` es el sufijo histórico y sigue
  # siendo válido; Oracle publica hoy también `oci.customer-oci.com`. Si algún día dejara de
  # resolver, corregirlo es esta línea y un `apply` — el valor viaja por el Vault, no por la imagen.
  media_s3_endpoint = "https://${data.oci_objectstorage_namespace.dev.namespace}.compat.objectstorage.${var.region}.oraclecloud.com"
  media_bucket_name = "autohostai-${var.env}-media"
}

# Bucket PRIVADO (R1.2): todo objeto se entrega por URL prefirmada de caducidad acotada, así que un
# bucket público anularía el esquema de firma entero.
#
# Sin `prevent_destroy` a propósito (D6): bloquearía el `terraform destroy` del entorno, que es la
# propiedad «reproducible desde cero» que dev quiere conservar. El borrado accidental ya tiene su
# guarda natural — OCI rechaza eliminar un bucket no vacío, así que un destroy sobre un bucket con
# fotos falla en vez de tragárselas.
#
# Sin versioning: es una decisión de RETENCIÓN, y la retención está fuera de alcance del change.
# R1.3 (converger sin recrear ni vaciar) sale de que name, namespace y compartment son estables
# entre applies: el recurso queda `no changes`.
resource "oci_objectstorage_bucket" "media" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.dev.namespace
  name           = local.media_bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
}

# --- Identidad del usuario del bucket (D7 / R2.2) ---
# Usuario propio, NO `svc-terraform-dev`: reutilizarlo le daría a la aplicación la credencial que
# gobierna toda la infraestructura. Y no vale un instance principal: la API compatible con S3 de OCI
# **solo** autentica con Customer Secret Key.
#
# El precio está declarado en `iam-policy.md`: `svc-terraform-dev` necesita `manage users` y
# `manage groups` a nivel de tenancy, que OCI no permite acotar. Es la segunda relajación consciente
# del mínimo privilegio, con ámbito dev/test y revisión antes de staging/prod (OQ1).
resource "oci_identity_user" "media" {
  compartment_id = var.tenancy_ocid
  name           = "autohostai-${var.env}-media"
  description    = "Usuario de servicio que el backend de ${var.env} usa para leer y escribir fotos en el bucket de medios por la API compatible con S3. Sin login de consola; su única credencial es la Customer Secret Key de abajo."

  # Obligatorio en esta tenancy, y no es opcional del provider: usa **Identity Domains** (IDCS), que
  # rechaza la creación sin email primario —`error.identity.user.primaryEmailNotSpecified`, 400— aunque
  # el usuario sea de servicio y no vaya a iniciar sesión jamás. La IAM clásica no lo pedía, y por eso
  # el primer apply (run 31909392774) falló aquí con el bucket y el grupo ya creados.
  email = var.media_user_email
}

resource "oci_identity_group" "media" {
  compartment_id = var.tenancy_ocid
  name           = "autohostai-${var.env}-media"
  description    = "Grupo del usuario de medios de ${var.env}. Existe porque las policies de OCI se dirigen a grupos, no a usuarios."
}

resource "oci_identity_user_group_membership" "media" {
  user_id  = oci_identity_user.media.id
  group_id = oci_identity_group.media.id
}

# Policy acotada al bucket y a cuatro permisos (D8). `read buckets` es lo que permite resolver el
# bucket; los cuatro permisos de objeto son exactamente los que invoca `S3FileStorage`:
# `put_object` (OBJECT_CREATE + OBJECT_OVERWRITE), `get_object` (OBJECT_READ, que es lo que honra la
# URL prefirmada) y `delete_object` (OBJECT_DELETE).
#
# `manage objects` a secas añadiría OBJECT_INSPECT sin llamante, así que se enumera.
# `manage object-family` se descartó: concede además gestión de buckets, incluido borrarlos.
resource "oci_identity_policy" "media_bucket_access" {
  compartment_id = var.compartment_ocid
  name           = "autohostai-${var.env}-media-bucket-access"
  description    = "Permite al usuario de medios de ${var.env} operar SOLO sobre los objetos de su propio bucket (mínimo privilegio: ni gestión de buckets, ni otros buckets del compartment)."
  statements = [
    "Allow group ${oci_identity_group.media.name} to read buckets in compartment id ${var.compartment_ocid} where target.bucket.name = '${local.media_bucket_name}'",
    "Allow group ${oci_identity_group.media.name} to manage objects in compartment id ${var.compartment_ocid} where all {target.bucket.name = '${local.media_bucket_name}', any {request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_DELETE', request.permission='OBJECT_OVERWRITE'}}",
  ]
}

# La credencial de la API compatible con S3. Se rota con `terraform apply -replace` (procedimiento
# en el RUNBOOK), no con un humano copiando de una consola.
#
# Su valor acaba en el tfstate, igual que POSTGRES_PASSWORD, JWT_SECRET_KEY y ENCRYPTION_KEY:
# cubierto por la excepción dev/test de `steering/security.md` §8, que se apoya en que el bucket del
# state es privado, versionado y con IAM mínima.
resource "oci_identity_customer_secret_key" "media" {
  user_id      = oci_identity_user.media.id
  display_name = "autohostai-${var.env}-media-s3"
}

# --- Los cuatro valores que la VM necesita, por el Vault (D9) ---
# El Vault leído por nombre es el ÚNICO canal Terraform → VM que existe hoy:
# /etc/autohostai-deploy.env lo escribe cloud-init y `metadata` es ForceNew con `ignore_changes`,
# así que Terraform no puede reescribirlo en la máquina viva (design D3 de ingress-https-dev).
#
# Dos de los cuatro NO son secretos, y conviene decirlo en voz alta: el endpoint y la región van al
# Vault porque es el único canal, no porque haga falta cifrarlos. La alternativa —variables de repo
# de GitHub, como OCI_VAULT_ID— funciona y hay precedente, pero son dos pasos manuales por entorno
# justo en el punto que `steering/infra.md` señala como lección de app-deploy-dev.
resource "oci_vault_secret" "media_access_key_id" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-media-access-key-id"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_identity_customer_secret_key.media.id)
  }
}

resource "oci_vault_secret" "media_secret_access_key" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-media-secret-access-key"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_identity_customer_secret_key.media.key)
  }
}

resource "oci_vault_secret" "media_s3_endpoint" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-media-s3-endpoint"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(local.media_s3_endpoint)
  }
}

resource "oci_vault_secret" "media_region" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-media-region"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.region)
  }
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

# --- Relay SMTP: OCI Email Delivery (change `smtp-delivery-adapter`, design D6/D7) ---
#
# Usuario propio, NO `oci_identity_user.media`: una credencial SMTP filtrada no debe conceder
# también escritura en el bucket de fotos, y viceversa — decisión de tasks.md 5.3 (design D6
# deja el usuario "decidido en tasks.md, no design implication either way"). Mismo requisito de
# email primario que `media` — esta tenancy usa Identity Domains (IDCS), que rechaza un usuario
# sin él aunque sea de servicio y no vaya a iniciar sesión nunca.
resource "oci_identity_user" "smtp" {
  compartment_id = var.tenancy_ocid
  name           = "autohostai-${var.env}-smtp"
  description    = "Usuario de servicio que el backend de ${var.env} usa exclusivamente para autenticar contra el relay SMTP de OCI Email Delivery. Sin login de consola; su única credencial es el SMTP credential de abajo."
  email          = var.smtp_user_email
}

resource "oci_identity_group" "smtp" {
  compartment_id = var.tenancy_ocid
  name           = "autohostai-${var.env}-smtp"
  description    = "Grupo del usuario del relay SMTP de ${var.env}. Existe porque las policies de OCI se dirigen a grupos, no a usuarios."
}

resource "oci_identity_user_group_membership" "smtp" {
  user_id  = oci_identity_user.smtp.id
  group_id = oci_identity_group.smtp.id
}

# Mínimo privilegio real para ENVIAR correo (operación `SmtpSend`), no para gestionar approved
# senders ni dominios — eso lo concede la ampliación de `iam-policy.md` a `svc-terraform-dev`
# (R5.1, la aplica un admin de la tenancy fuera de este apply). `use approved-senders` es
# exactamente el permiso `APPROVED_SENDER_USE` que cubre `SmtpSend` en la referencia de policies
# del servicio Email — ni domain-create ni sender-create, que quedan fuera de lo que este usuario
# puede hacer.
resource "oci_identity_policy" "smtp_send_access" {
  compartment_id = var.compartment_ocid
  name           = "autohostai-${var.env}-smtp-send-access"
  description    = "Permite al usuario del relay SMTP de ${var.env} SOLO enviar correo (SmtpSend) — ni gestionar approved senders ni dominios."
  statements = [
    "Allow group ${oci_identity_group.smtp.name} to use approved-senders in compartment id ${var.compartment_ocid}",
  ]
}

# La credencial SMTP se genera DENTRO del apply, igual que la Customer Secret Key de medios
# (`oci_identity_customer_secret_key.media`): Terraform la captura, nunca un humano la copia de
# una consola. Se rota con `terraform apply -replace` (mismo procedimiento que la de medios).
resource "oci_identity_smtp_credential" "smtp" {
  user_id     = oci_identity_user.smtp.id
  description = "autohostai-${var.env}-smtp-credential"
}

# --- Dominio de envío, DKIM y approved sender (D6) ---
# Subdominio dedicado a correo, no el apex ni `public_hostname`: acota DKIM/SPF al tráfico de
# mail y no a lo que sirve el túnel (D6 del design).
resource "oci_email_email_domain" "smtp" {
  compartment_id = var.compartment_ocid
  name           = "mail.${var.public_hostname}"
  description    = "Dominio de envío del relay SMTP de ${var.env} (change smtp-delivery-adapter)."
}

# La clave DKIM se genera DENTRO del apply: `cname_record_value`/`dns_subdomain_name` son
# atributos de este recurso, no un valor que un humano copia de un dashboard (D6, R5.2). Los
# registros Cloudflare de abajo los referencian directamente.
resource "oci_email_dkim" "smtp" {
  email_domain_id = oci_email_email_domain.smtp.id
  name            = "smtp-${var.env}"
  description     = "Clave DKIM del dominio de envío de ${var.env}."
}

# El "approved sender", self-service y gestionado por Terraform — sin espera de aprobación
# manual comparable a la de SES, que es precisamente por lo que D6 rechazó SES/Brevo/Resend.
# `email_address` deriva del propio recurso de dominio (no de un string copiado), así que un
# dominio recreado se reconcilia en el mismo apply.
resource "oci_email_sender" "smtp" {
  compartment_id = var.compartment_ocid
  email_address  = "noreply@${oci_email_email_domain.smtp.name}"
}

# SPF y DKIM del dominio de envío (D7, cierra R5.2). Ninguno de los dos se proxea: no son
# tráfico HTTP y Cloudflare no permite proxy sobre TXT en cualquier caso.
resource "cloudflare_dns_record" "smtp_spf" {
  zone_id = var.cloudflare_zone_id
  name    = oci_email_email_domain.smtp.name
  type    = "TXT"
  # Variante `eu.` — región eu-frankfurt-1 (docs.oracle.com/en-us/iaas/Content/Email/Tasks/configurespf.htm),
  # confirmada en el gate de diseño (D6): la base `rp.oracleemaildelivery.com` sin el prefijo de
  # región es la variante US y no autorizaría el relay real de este entorno.
  content = "v=spf1 include:eu.rp.oracleemaildelivery.com ~all"
  ttl     = 3600
  proxied = false
}

# `name`/`content` son atributos del recurso OCI, no un valor copiado de un dashboard (D7): si la
# clave DKIM se rotara (`terraform apply -replace`), este registro se reconcilia en el mismo
# apply en vez de quedar apuntando a una clave muerta.
resource "cloudflare_dns_record" "smtp_dkim" {
  zone_id = var.cloudflare_zone_id
  name    = oci_email_dkim.smtp.dns_subdomain_name
  type    = "CNAME"
  content = oci_email_dkim.smtp.cname_record_value
  ttl     = 3600
  proxied = false
}

# --- Los seis valores que la VM necesita, por el Vault (D7) ---
# Mismo canal que medios/túnel/demo-account, y por el mismo motivo: /etc/autohostai-deploy.env es
# ForceNew (cloud-init ya corrió), así que Terraform no puede reescribirlo en la máquina viva —
# todo lo añadido después se resuelve por nombre, nunca por el OCID que ese fichero tendría que
# llevar.
#
# `smtp_host`/`smtp_port`/`smtp_use_tls` son literales del endpoint SMTP documentado de OCI para
# esta región (D6) — no hay recurso Terraform del que leerlos, a diferencia de usuario/contraseña
# y remitente, que sí son atributos de recursos de este mismo apply.
resource "oci_vault_secret" "smtp_host" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-host"
  secret_content {
    content_type = "BASE64"
    content      = base64encode("smtp.email.${var.region}.oci.oraclecloud.com")
  }
}

resource "oci_vault_secret" "smtp_port" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-port"
  secret_content {
    content_type = "BASE64"
    content      = base64encode("587")
  }
}

resource "oci_vault_secret" "smtp_username" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-username"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_identity_smtp_credential.smtp.username)
  }
}

resource "oci_vault_secret" "smtp_password" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-password"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_identity_smtp_credential.smtp.password)
  }
}

resource "oci_vault_secret" "smtp_from_email" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-from-email"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_email_sender.smtp.email_address)
  }
}

resource "oci_vault_secret" "smtp_use_tls" {
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.dev.id
  key_id         = oci_kms_key.dev_secrets.id
  secret_name    = "autohostai-${var.env}-smtp-use-tls"
  secret_content {
    content_type = "BASE64"
    content      = base64encode("true")
  }
}
