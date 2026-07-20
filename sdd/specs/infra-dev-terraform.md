# Infraestructura real del entorno dev (Terraform + CI/CD)

## Purpose

Terraform real y pipeline de CI/CD para el entorno `dev` de AutoHostAI en Oracle Cloud Infrastructure, según la decisión de `docs/adr/0001-dev-hosting-provider.md`: una VM única (Ampere A1, Always Free) ejecutando el `docker-compose.yml` del repo. Cubre red, cómputo, backend de state remoto, alerta de presupuesto, y los workflows de GitHub Actions que validan y aplican ese Terraform — sin desplegar todavía la aplicación en sí ni tocar `staging`/`prod`.

## Requirements

### Red y cómputo (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL aprovisionar una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- THE SYSTEM SHALL restringir el security list de la subred a exactamente: SSH (puerto 22, origen acotado por `var.allowed_ssh_cidr`, CIDR IPv4 con prefijo ≥ /24), 8000 (backend) y 3000 (frontend) — los mismos puertos que publica `docker-compose.yml`, ningún otro.
- THE SYSTEM SHALL aprovisionar una única instancia `VM.Standard.A1.Flex` (2 OCPU/12 GB, cupo Always Free) con una imagen Ubuntu 22.04 ARM64 resuelta dinámicamente vía `data.oci_core_images` — nunca un OCID de imagen hardcodeado.
- THE SYSTEM SHALL asociar una IP pública reservada (no efímera) a la instancia.
- WHEN `var.allowed_ssh_cidr` no es un CIDR IPv4 válido con prefijo ≥ /24, THE SYSTEM SHALL rechazar el `plan`/`apply` en la fase de validación de variables.

### Backend de state remoto (`infra/environments/dev/backend.tf`)

- THE SYSTEM SHALL usar el backend nativo `oci` de Terraform (no el shim S3-compatible) con configuración parcial — namespace, bucket, región y credenciales se pasan vía `-backend-config`, nunca hardcodeados en el repo.
- THE SYSTEM SHALL requerir Terraform >= 1.12 (`required_version` en `main.tf`), versión mínima que soporta el backend `oci`.
- La autenticación del backend usa `private_key_path` (ruta a fichero) — nunca el contenido de la clave privada embebido inline en un string/heredoc HCL.
- El bucket de Object Storage (`autohostai-tfstate-dev`) se crea manualmente, una sola vez, fuera de este Terraform (dependencia circular: no se puede usar Terraform para crear el almacén de su propio state).

### Alerta de presupuesto (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL crear un `oci_budget_budget` (reset mensual) sobre el compartment de `dev` más un `oci_budget_alert_rule` (tipo `ACTUAL`) que notifica por email si el gasto supera un umbral configurable.
- IF no se proporciona un email de destinatario, THEN THE SYSTEM SHALL rechazar el `plan`/`apply` — nunca desplegar una alerta sin destinatario.

### Pipeline de GitHub Actions (`.github/workflows/infra-dev.yml`)

- WHEN se abre o actualiza un PR que toca `infra/environments/dev/**`, THE SYSTEM SHALL ejecutar el job `check` (`terraform fmt -check`, `init -backend=false`, `validate`) sin requerir ningún secret — seguro incluso para PRs de forks.
- THE SYSTEM SHALL exponer un único camino capaz de tocar recursos reales: `workflow_dispatch` con input `action` (`plan`|`apply`). Nunca se dispara automáticamente en push/merge.
- WHEN el `action` elegido es `apply`, THE SYSTEM SHALL ejecutarlo solo si el `plan` del mismo run fue exitoso.
- El job `plan-apply` ejecuta `init` → `validate` → `plan` → (`apply` condicional) contra el backend y la cuenta reales.

### Build multi-arch (`.github/workflows/multiarch-build-check.yml`)

- WHEN se modifica `backend/devops/Dockerfile`, `frontend/devops/Dockerfile`, o sus lockfiles, THE SYSTEM SHALL construir ambas imágenes (`target: prod`) para `linux/amd64` y `linux/arm64`, sin publicar a ningún registry — verifica que ambas corren en la arquitectura ARM64 de la instancia Ampere A1.

## Key files

- `infra/environments/dev/{main.tf,variables.tf,outputs.tf,backend.tf}` — Terraform real.
- `infra/environments/dev/{backend.hcl.example,dev.tfvars.example}` — plantillas de configuración local, sin valores reales.
- `infra/environments/dev/README.md` — instrucciones de uso, estado real, secrets esperados.
- `.github/workflows/infra-dev.yml`, `.github/workflows/multiarch-build-check.yml` — pipelines de CI/CD.
- `docs/adr/0001-dev-hosting-provider.md` — decisión de proveedor que este spec implementa.

## Estado y pendientes

- El `apply` real contra la cuenta y el primer despliegue de la aplicación en la VM quedan como acción explícita del usuario — no se ejecutan automáticamente. Un `terraform plan` real ya se ha verificado en vivo (vía CI y localmente): 9 recursos a crear, 0 errores.
- El despliegue de la aplicación (`docker compose pull && up -d` dentro de la VM) es un workflow/step futuro, fuera de este spec.
