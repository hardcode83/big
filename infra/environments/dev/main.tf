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

# Puertos exactos de docker-compose.yml: backend 8000, frontend 3000, más SSH restringido.
resource "oci_core_security_list" "dev_public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.dev.id
  display_name   = "autohostai-dev-public-sl"

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  ingress_security_rules {
    protocol = "6" # TCP
    source   = var.allowed_ssh_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 8000
      max = 8000
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 3000
      max = 3000
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
    ocpus         = 2
    memory_in_gbs = 12
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.dev_public.id
    assign_public_ip = false # la IP pública se asocia explícitamente vía oci_core_public_ip (reservada, no efímera)
  }

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ubuntu_arm.images[0].id
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key # par dedicado a esta VM, distinto de la API key de OCI
    user_data = base64encode(<<-CLOUDINIT
      #cloud-config
      package_update: true
      packages:
        - docker.io
        - docker-compose-plugin
      runcmd:
        - systemctl enable --now docker
    CLOUDINIT
    )
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

resource "oci_budget_alert_rule" "dev" {
  budget_id      = oci_budget_budget.dev.id
  display_name   = "autohostai-dev-budget-alert"
  type           = "ACTUAL"
  threshold_type = "PERCENTAGE"
  threshold      = var.budget_alert_threshold_percent
  recipients     = var.budget_alert_email
  message        = "AutoHostAI dev: el gasto real ha superado ${var.budget_alert_threshold_percent}% del presupuesto mensual (${var.budget_amount} USD)."
}
