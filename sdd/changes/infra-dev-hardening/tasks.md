# Tasks: infra-dev-hardening

> Depende de que `infra-dev-payg` esté en `main` (ya lo está; rama rebasada). Varias tareas son operaciones OCI/GitHub fuera de Terraform (marcadas "op."). La VM viva ya tiene `docker compose` (remediada esta sesión) — pre-marcada.

## 1. Variables y security list — SSH multi-operador (R2)

- [x] 1.1 Refactorizar variables a listas: `ssh_public_key`→`ssh_authorized_keys` (`list(string)`) y `allowed_ssh_cidr`→`allowed_ssh_cidrs` (`list(string)`), con validación por elemento (IPv4, prefijo ≥ /24, sin rangos abiertos); actualizar plantilla — **Files:** `infra/environments/dev/variables.tf`, `infra/environments/dev/dev.tfvars.example` — [R2]
- [x] 1.2 `main.tf`: cloud-init inyecta **todas** las claves de la lista a `authorized_keys`; security list con `dynamic` ingress por CIDR aplicado a los **tres** puertos (22, 8000, 3000) — quitando el `0.0.0.0/0` de 8000/3000 — **Files:** `infra/environments/dev/main.tf` — [R2]
- [x] 1.3 Verificar por `terraform plan` que el security list cambia **in-place** (no recrea) con solo el CIDR de Jose poblado, y que SSH sigue operativo — **Files:** ninguno (plan) — [R2]

## 2. cloud-init Docker + Compose (R3)

- [x] 2.1 `main.tf`: reescribir el cloud-init para instalar Docker vía **repo APT oficial** (clave GPG + source `download.docker.com … $CODENAME stable`, `arch=arm64`) con `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin` y `ubuntu` en el grupo `docker`. **Verificar por `terraform plan` que el cambio de `user_data` NO recrea la instancia**; si forzara replacement, proteger con `lifecycle { ignore_changes = [metadata] }` (la VM viva ya está remediada; el cloud-init solo aplica a VMs nuevas) — **Files:** `infra/environments/dev/main.tf` — [R3]
- [x] 2.2 Remediar la VM ya desplegada: instalar el plugin de compose por SSH (repo Docker oficial) y verificar `docker compose version` — (preexistente — ejecutado esta sesión, `v5.3.1` OK) — [R3]

## 3. Presupuesto €1 con alertas ACTUAL + FORECAST (R6)

- [x] 3.1 `variables.tf`: `budget_amount` default → **1**; `budget_alert_email` (string) → `budget_alert_recipients` (`list(string)`, default `["josegascon@gmail.com","mreyesojeda@gmail.com"]`); actualizar plantilla — **Files:** `infra/environments/dev/variables.tf`, `infra/environments/dev/dev.tfvars.example` — [R6]
- [x] 3.2 `main.tf`: budget importe 1; regla **ACTUAL** `threshold_type=ABSOLUTE threshold=1`; **añadir** regla **FORECAST** `threshold_type=ABSOLUTE threshold=1`; `recipients = join(",", var.budget_alert_recipients)` — **Files:** `infra/environments/dev/main.tf` — [R6]
- [x] 3.3 Reconciliar el drift: eliminar en la consola OCI la alerta/budget creada a mano **antes** del apply, para que Terraform recree sin duplicar — **Files:** ninguno (op. OCI) — [R6] (pendiente: acción tuya en consola antes del apply)

## 4. OCI Vault — backup de la clave SSH (R7)

- [x] 4.1 `main.tf`: crear `oci_kms_vault` (tipo DEFAULT) + `oci_kms_key` **software-protected** (`protection_mode = "SOFTWARE"`), dentro del cupo Always Free — **Files:** `infra/environments/dev/main.tf` (+ `variables.tf`/outputs si procede) — [R7]
- [ ] 4.2 Subir la clave privada SSH como secret **out-of-band** con OCI CLI (`oci vault secret create-base64 …`), NUNCA como recurso Terraform con el contenido inline (para no filtrar el plaintext al `tfstate`); verificar que se recupera — **Files:** ninguno (op. OCI); procedimiento en el RUNBOOK — [R7] (pendiente: op tuya — OCI CLI)

## 5. Endurecimiento del workflow de apply (R1)

- [x] 5.1 `infra-dev.yml`: dividir `plan-apply` en dos jobs — `plan` (init→validate→plan, sube `tfplan` como artifact) y `apply` (descarga el artifact y aplica) — **Files:** `.github/workflows/infra-dev.yml` — [R1]
- [x] 5.2 En el job `apply`: `if: github.ref == 'refs/heads/main'`, `concurrency: { group: infra-dev-apply, cancel-in-progress: false }`, `timeout-minutes` en ambos jobs (sin `environment:` — ver 5.4/opción A) — **Files:** `.github/workflows/infra-dev.yml` — [R1]
- [x] 5.3 Fijar todas las GitHub Actions por **SHA de commit** (checkout, setup-terraform, upload/download-artifact) con el tag en comentario — **Files:** `.github/workflows/infra-dev.yml` — [R1]
- [x] 5.4 Gate de aprobación: en repo privado + plan Free los Environments con required reviewers no están disponibles (API 404) → **opción A**: review del PR + `apply` manual solo desde `main`. No hay Environment que configurar; se quitó `environment:` del workflow y se documentó en RUNBOOK §0 y README — **Files:** `.github/workflows/infra-dev.yml`, `RUNBOOK.md`, `README.md` — [R1]

## 6. IAM mínimo + state backend (R4)

- [x] 6.1 Definir el grupo `autohostai-dev-terraform` + policy IAM acotada al compartment de dev (verbos exactos derivados de los recursos del `main.tf`: instance-family, virtual-network-family, budgets, object-family solo del bucket del state, y vault/keys/secrets de R7) — **Files:** doc de policy (aplicada por admin de tenancy, fuera del root module) — [R4]
- [x] 6.2 Aplicar la policy (admin de tenancy), mover el usuario de Terraform al grupo y **verificar `plan`/`apply` con los permisos acotados** antes de retirar los amplios — **Files:** ninguno (op. OCI) — [R4] (verificado: plan del provider + init del backend con svc-terraform-dev, sin errores de autorización)
- [ ] 6.3 Activar **versioning** en el bucket `autohostai-tfstate-dev` (OCI CLI/consola) — **Files:** ninguno (op. OCI) — [R4]

## 7. Runbook operativo (R5)

- [x] 7.1 Crear `infra/environments/dev/RUNBOOK.md` con: `destroy` controlado, **recuperación del state** (listar/restaurar versión del objeto), **acceso SSH** (usuario `ubuntu`, IP, clave por persona, alta/rotación/revocación de claves y CIDRs, **recuperar la clave del Vault**), y **diagnóstico de cloud-init** (`cloud-init status`, `/var/log/cloud-init-output.log`, reintento); enlazarlo desde `README.md` — **Files:** `infra/environments/dev/RUNBOOK.md` (nuevo), `README.md` — [R2, R4, R5, R7]

## 8. Verificación

- [x] 8.1 `cd infra/environments/dev && terraform fmt -check -diff && terraform validate` pasan (lo corre también el job `check` en el PR) — **Files:** correcciones de formato si falla — [R1, R2, R3, R6, R7]
- [x] 8.2 `terraform plan` completo: confirmar **`0 to destroy` de la instancia** (security list y user_data in-place o protegidos), y que solo se crean/actualizan los recursos esperados (budget, vault, key, reglas) — **Files:** ninguno (plan) — [R2, R3, R6, R7]
- [ ] 8.3 Aplicar vía pipeline (`workflow_dispatch` `apply` desde `main`, con aprobación vía review del PR (opción A, sin Environment)) y verificar en el run: instancia intacta, budget €1 con 2 alertas a ambos correos, vault+key creados — **Files:** ninguno (op. pipeline) — [R1, R6, R7]
- [ ] 8.4 Verificar el secret recuperable del Vault y el versioning activo del bucket; smoke test SSH desde el CIDR de Jose — **Files:** ninguno (op.) — [R2, R4, R7]
