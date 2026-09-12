# Backend nativo `oci` (Terraform >= 1.12) — paralelo al del módulo dev pero en
# su propio bucket `autohostai-tfstate-github` (D3: no reutilizar el bucket dev).
# Configuración parcial a propósito: namespace/bucket/region se pasan en
# `terraform init -backend-config=...` (flags en CI, o `backend.hcl` local no
# versionado) — nunca hardcodeados aquí. Ver `backend.hcl.example`.
#
# El bucket debe existir ANTES del primer `init` (es un bootstrap irreducible
# — mismo motivo que `autohostai-tfstate-dev`: dependencia circular con el
# propio state). Ver `README.md` y la tarea 1.1 de `tasks.md`.

terraform {
  backend "oci" {}
}