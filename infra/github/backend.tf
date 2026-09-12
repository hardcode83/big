# Backend nativo `oci` (Terraform >= 1.12) — el state vive en el **mismo
# bucket** que el módulo dev (`autohostai-tfstate-dev`), separado por `key =
# "github.tfstate"`. Patrón "un bucket, varios states" — la separación entre
# los dos módulos es la `key`, no el bucket.
#
# Configuración parcial a propósito: namespace/bucket/region/key se pasan en
# `terraform init -backend-config=...` (flags en CI, o `backend.hcl` local no
# versionado) — nunca hardcodeados aquí. Ver `backend.hcl.example`.
#
# Pre-requisito: `autohostai-tfstate-dev` debe existir con `versioning =
# enabled` — ya creado por `infra/environments/dev/`, no es bootstrap
# irreducible de este módulo.

terraform {
  backend "oci" {}
}