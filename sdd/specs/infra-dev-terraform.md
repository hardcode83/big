# Infraestructura real del entorno dev (Terraform + CI/CD)

## Purpose

Terraform real y pipeline de CI/CD para el entorno `dev` de AutoHostAI en Oracle Cloud Infrastructure, según `docs/adr/0001-dev-hosting-provider.md` (addendum 2026-07-21: tenancy en Pay-As-You-Go conservando la capa gratuita a $0 — change `infra-dev-payg`): una VM única (Ampere A1) ejecutando el `docker-compose.yml` del repo. Cubre red, cómputo, backend de state remoto, alerta de presupuesto, backup de credenciales en OCI Vault, IAM de mínimo privilegio, y los workflows de GitHub Actions que validan y aplican ese Terraform — sin desplegar todavía la aplicación en sí ni tocar `staging`/`prod`.

## Requirements

### Red y cómputo (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL aprovisionar una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- THE SYSTEM SHALL acotar el security list de la subred a los puertos 22 (SSH), 8000 (backend) y 3000 (frontend) — los que publica `docker-compose.yml` — **todos restringidos a `var.allowed_ssh_cidrs`** (ningún `0.0.0.0/0` de entrada), generando una regla por (CIDR × puerto) con un bloque `dynamic`.
- THE SYSTEM SHALL aprovisionar una única instancia `VM.Standard.A1.Flex` (4 OCPU/24 GB, boot volume 200 GB, dentro del grant Always Free que la tenancy PAYG conserva a $0), fijada en AD-3 vía `var.ad_number` (default 3), con imagen Ubuntu 22.04 ARM64 resuelta vía `data.oci_core_images` — nunca un OCID hardcodeado.
- THE SYSTEM SHALL inyectar por `cloud-init` las claves de `var.ssh_authorized_keys` (`list(string)`) al usuario `ubuntu`, e instalar Docker + Compose vía el **repositorio APT oficial de Docker** (`docker-ce`, `docker-compose-plugin`, arm64) — nunca `docker-compose-plugin` de los repos por defecto de Ubuntu (no existe ahí).
- THE SYSTEM SHALL declarar `lifecycle { ignore_changes = [metadata] }` en la instancia: el `metadata` (user_data/claves) es ForceNew en el provider `oci`, así que cambiarlo recrearía la VM; la lista de claves y el cloud-init definen el arranque de una VM nueva, y las altas/rotaciones de clave sobre la VM viva se hacen out-of-band por SSH (ver `RUNBOOK.md`).
- THE SYSTEM SHALL asociar una IP pública reservada (no efímera) a la instancia.
- El `cloud-init` (movido a `cloud-init.yaml.tftpl` vía `templatefile()`) provisiona además el **runner self-hosted de GitHub Actions** del CD y declara el **instance principal** (`oci_identity_dynamic_group` + `oci_identity_policy` de mínimo privilegio) que lo autoriza a leer del Vault; el comportamiento del CD se especifica en `app-deploy-dev`.
- WHEN algún elemento de `var.allowed_ssh_cidrs` no es un CIDR IPv4 con prefijo ≥ /24, o `var.ssh_authorized_keys` está vacía / con formato inválido, THE SYSTEM SHALL rechazar el `plan`/`apply` en la validación de variables.

### Backend de state remoto (`infra/environments/dev/backend.tf`)

- THE SYSTEM SHALL usar el backend nativo `oci` con configuración parcial — namespace, bucket, región y credenciales por `-backend-config`, nunca hardcodeados en el repo; autenticación por `private_key_path` (ruta a fichero), nunca el PEM inline.
- THE SYSTEM SHALL requerir Terraform >= 1.12 (versión mínima con backend `oci`).
- El bucket de Object Storage (`autohostai-tfstate-dev`) se crea manualmente una vez fuera de este Terraform (dependencia circular), con **versioning activado**; el procedimiento de recuperación del state (restaurar una versión previa del objeto) está en `RUNBOOK.md`.
- THE SYSTEM SHALL ejecutarse (provider y backend) como el usuario de servicio **`svc-terraform-dev`**, miembro de un grupo con **policy IAM** acotada a los recursos gestionados (compute, red, budgets, object-family del bucket del state, vault/keys/secrets, y — desde `app-deploy-dev` — `dynamic-groups`/`policies` para el instance principal del runner), versionada en `iam-policy.md` y aplicada por un admin de la tenancy. La inclusión de `manage dynamic-groups/policies in tenancy` es una **relajación consciente** del mínimo privilegio (superficie de escalada), documentada y de ámbito dev/test; a revisar antes de staging/prod.

### Alerta de presupuesto (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL crear un `oci_budget_budget` mensual de importe `var.budget_amount` (default **1**) más **dos** `oci_budget_alert_rule`: una `ACTUAL` y una `FORECAST`, ambas `threshold_type = ABSOLUTE` al importe del presupuesto, notificando a `var.budget_alert_recipients` (`list(string)`, default Jose + Marta).
- IF `var.budget_alert_recipients` está vacía, THEN THE SYSTEM SHALL rechazar el `plan`/`apply`.

### Backup de la clave SSH en OCI Vault (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL crear un `oci_kms_vault` (tipo `DEFAULT`) y un `oci_kms_key` **software-protected** (Always Free, $0).
- THE SYSTEM SHALL mantener la clave privada SSH como secret del Vault **subido out-of-band** (OCI CLI, ver `RUNBOOK.md`), **nunca como recurso Terraform con contenido inline** — para que el valor en claro no llegue al `tfstate`.
- Desde `app-deploy-dev`, el Vault aloja además secrets **gestionados por Terraform**: los de runtime de la app (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) generados con `random_*`, y la clave privada de la GitHub App (inyectada desde un GitHub Secret vía var sensible). Sus valores **sí** residen en el `tfstate` — relajación aceptada de la regla anterior para dev/test (`steering/security.md` §8), no aplicable a la clave SSH. Ver `app-deploy-dev`.

### Pipeline de GitHub Actions (`.github/workflows/infra-dev.yml`)

- WHEN se abre/actualiza un PR que toca `infra/environments/dev/**`, THE SYSTEM SHALL ejecutar el job `check` (`terraform fmt -check`, `init -backend=false`, `validate`) sin ningún secret.
- THE SYSTEM SHALL exponer un único camino a recursos reales: `workflow_dispatch` con input `action` (`plan`|`apply`), en dos jobs — `plan` (init→validate→plan, para revisión por logs) y `apply` (re-planifica y aplica en el mismo job). El `plan` **no** usa `-out` ni sube el `tfplan` como artifact: desde `app-deploy-dev` el plan contiene secrets (clave de la App + secrets generados) y un artifact es descargable por cualquiera con read del repo.
- THE SYSTEM SHALL ejecutar el job `apply` **solo desde `main`** (`if: github.ref == 'refs/heads/main'`), con `concurrency` (serializa applies sobre el mismo state) y `timeout-minutes`; todas las GitHub Actions fijadas por **SHA de commit**.
- El gate de aprobación es **convención** (review de PR + `apply` manual desde `main`): en repo privado + plan Free NO hay Environments con required reviewers ni branch protection/rulesets (la API devuelve 403). Lo forzado técnicamente es que el `apply` solo corre contra `main`; el "PR revisado antes de merge" es un modelo de confianza de operadores. Enforcement real requeriría GitHub Pro/Team o repo público.

### Build multi-arch (`.github/workflows/multiarch-build-check.yml`)

- WHEN se modifica `backend/devops/Dockerfile`, `frontend/devops/Dockerfile` o sus lockfiles, THE SYSTEM SHALL construir ambas imágenes (`target: prod`) para `linux/amd64` y `linux/arm64` sin publicar a registry — verifica que corren en la arquitectura ARM64 de la instancia.

## Key files

- `infra/environments/dev/{main.tf,variables.tf,outputs.tf,backend.tf}` — Terraform real.
- `infra/environments/dev/{backend.hcl.example,dev.tfvars.example}` — plantillas, sin valores reales.
- `infra/environments/dev/README.md` — uso, estado y secrets esperados; `RUNBOOK.md` — operación/recuperación; `iam-policy.md` — policy IAM mínima versionada.
- `.github/workflows/{infra-dev.yml,multiarch-build-check.yml}` — pipelines.
- `docs/adr/0001-dev-hosting-provider.md` — decisión de proveedor (con addendum PAYG).

## Estado y pendientes

- Infra **desplegada y operativa** (aplicada por el pipeline como `svc-terraform-dev`): instancia 4 OCPU/24 GB/200 GB en AD-3 (PAYG, $0), security list acotado por CIDR, Docker+Compose vía repo oficial, budget €1 con alertas ACTUAL+FORECAST, Vault + key + secret SSH recuperable, versioning del state activo. Añadido por `app-deploy-dev`: runner self-hosted (cloud-init) + instance principal + secrets de runtime y clave de la App en el Vault.
- El **despliegue de la aplicación** ya está resuelto por el change **`app-deploy-dev`** (build → GHCR → deploy local en el runner self-hosted); ver su spec. El repo vive en la org **`autohostai-labs`**.
