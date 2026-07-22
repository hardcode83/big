terraform {
  required_version = ">= 1.12"

  required_providers {
    oci = {
      source = "oracle/oci"
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
    # Docker desde el repo APT OFICIAL de Docker (arm64): docker-compose-plugin NO está en los
    # repos por defecto de Ubuntu 22.04 (bug del cloud-init anterior). cloud-init sustituye
    # $RELEASE (codename) y $KEY_FILE (ruta donde guarda la clave del keyid).
    user_data = base64encode(<<-CLOUDINIT
      #cloud-config
      package_update: true
      apt:
        sources:
          docker:
            source: "deb [arch=arm64 signed-by=$KEY_FILE] https://download.docker.com/linux/ubuntu $RELEASE stable"
            keyid: 9DC858229FC7DD38854AE2D88D81803C0EBFCD88
      packages:
        - docker-ce
        - docker-ce-cli
        - containerd.io
        - docker-buildx-plugin
        - docker-compose-plugin
      runcmd:
        - systemctl enable --now docker
        - usermod -aG docker ubuntu
    CLOUDINIT
    )
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
