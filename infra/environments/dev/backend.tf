# Backend nativo `oci` (Terraform >= 1.12) — decisión D7 de design.md.
# Configuración parcial a propósito: namespace/bucket/region se pasan en
# `terraform init -backend-config=...` (flags en CI, o backend.hcl local no
# versionado) — nunca hardcodeados aquí. Ver backend.hcl.example.
#
# El bucket de Object Storage debe existir ANTES del primer `init` — es un
# bootstrap manual, este mismo Terraform no puede crear el backend que usa
# para guardar su propio state (dependencia circular). Ver README.md.

terraform {
  backend "oci" {}
}
