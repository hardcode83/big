# Tasks: infra-dev-terraform

## 1. Root module — red y cómputo <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa) -->

- [x] 1.1 `infra/environments/dev/variables.tf`: declarar `tenancy_ocid`, `user_ocid`, `fingerprint`, `private_key_path` (ruta a fichero, no contenido inline — fix de revisión de arquitectura), `region`, `compartment_ocid`, `allowed_ssh_cidr` (sin default abierto a `0.0.0.0/0`, con `validation` block que lo rechaza) — ninguna con valor por defecto real. [R1.4]
- [x] 1.2 `infra/environments/dev/main.tf`: bloque `terraform { required_version = ">= 1.12", required_providers { oci = { source = "oracle/oci" } } }` y bloque `provider "oci"`. [R1.1]
- [x] 1.3 `infra/environments/dev/main.tf`: VCN `10.0.0.0/16` + subred pública `10.0.1.0/24` (`oci_core_vcn`, `oci_core_subnet`, internet gateway + route table). [R1.1]
- [x] 1.4 `infra/environments/dev/main.tf`: security list con ingress TCP 22 (restringido por `var.allowed_ssh_cidr`), 8000, 3000; egress abierto. Exactamente estos puertos, ninguno más (`docker-compose.yml`). [R1.1]
- [x] 1.5 `infra/environments/dev/main.tf`: `oci_core_instance` shape `VM.Standard.A1.Flex` (2 OCPU/12 GB), imagen ARM64 resuelta vía `data.oci_core_images` (Canonical Ubuntu 22.04, nunca un OCID hardcodeado), `oci_core_public_ip` tipo `RESERVED` asociada vía `data.oci_core_private_ips`. `cloud-init` mínimo: instala Docker + Docker Compose plugin. [R1.1]
- [x] 1.6 `infra/environments/dev/outputs.tf`: expone `instance_public_ip` e `instance_id`. [R1.1]
- [x] 1.7 `terraform fmt -check` + `terraform validate` (con `-backend=false`) sobre `infra/environments/dev/` — verificado contra el binario real (Terraform 1.15.8) y el schema real del provider `oracle/oci` v8.23.0: sin error. [R1.2]

## 2. Backend de state remoto (`oci` nativo) <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa; R2.3 doc gap fixed in design.md D7 + README) -->

- [x] 2.1 `infra/environments/dev/backend.tf`: `terraform { backend "oci" {} }` con configuración parcial (sin namespace/bucket/región hardcodeados). [R2, D7]
- [x] 2.2 `infra/environments/dev/backend.hcl.example`: documenta las claves de `-backend-config` reales (`bucket`, `namespace`, `key`, `region`, más `tenancy_ocid`/`user_ocid`/`fingerprint`/`private_key_path` — confirmado empíricamente que el backend `oci` necesita su propia autenticación, no puede leer `var.*` del provider, y que acepta `private_key_path` igual que el provider), sin valores reales. [R2, D7]
- [x] 2.3 Verificado con `terraform init -backend-config=...` real (namespace `frag3zplc9up`, bucket `autohostai-tfstate-dev`, credenciales reales pasadas por archivo temporal fuera del repo, nunca mostradas): **"Successfully configured the backend oci!"** contra el bucket ya creado por el usuario. [R2]

## 3. Alerta de presupuesto <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa; R5.2 validation dynamically confirmed with a standalone terraform plan probe) -->

- [x] 3.1 `infra/environments/dev/main.tf`: `oci_budget_budget` (`target_type = "COMPARTMENT"`, `targets = [var.compartment_ocid]`, `amount` configurable por variable) + `oci_budget_alert_rule` (`type = "ACTUAL"`, `threshold` por variable `budget_alert_threshold_percent`, `recipients` desde variable obligatoria `budget_alert_email` sin default). [R5.1]
- [x] 3.2 `variables.tf`: `budget_alert_email` lleva `validation` block que rechaza cadena vacía — no puede desplegarse una alerta sin destinatario. [R5.2]

## 4. CI — validación en PR (sin credenciales)

- [x] 4.1 `.github/workflows/infra-dev.yml`, job `check`: trigger `pull_request` (paths: `infra/environments/dev/**`) → `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`. [R3.3]
- [x] 4.2 Verificado en PR real (#7, https://github.com/mreyesojeda/AutoHostAI/pull/7): job `check` → **PASS en 15s**, sin ningún secret configurado. [R3.3]

## 5. CI — plan/apply manual

- [x] 5.1 Mismo `.github/workflows/infra-dev.yml`, job `plan-apply`: trigger `workflow_dispatch` (input `action`: `plan`|`apply`) → checkout, `hashicorp/setup-terraform` (1.15.8, ≥1.12), private key escrita a `$RUNNER_TEMP` (fix de revisión de arquitectura), backend.hcl generado en runtime desde secrets (`private_key_path`), `terraform init -backend-config=backend.hcl`, **`terraform validate`** (paso añadido tras QA feature-scale: R3.1 exige `init`/`validate`/`plan` explícitos, no solo confiar en la validación implícita de `plan`), `terraform plan -out=tfplan`, `terraform apply -auto-approve tfplan` **solo si** `action == 'apply'`. **Verificado en vivo, dos veces**: run [29728765058](https://github.com/mreyesojeda/AutoHostAI/actions/runs/29728765058) (antes del fix de `validate`) y run [29729372326](https://github.com/mreyesojeda/AutoHostAI/actions/runs/29729372326) (después, con el paso `terraform validate` ya incluido) → ambos `plan-apply` **success**, con `init` → `validate` → `plan` en verde en el segundo run, `terraform apply` `skipped` (acción elegida fue `plan`). Cierra tanto el hallazgo del arquitecto (camino CI→backend nunca ejercitado) como el de QA (falta `validate` explícito en el job). [R3.1, R3.2, R2.1]
- [x] 5.2 Todas las variables sensibles (`OCI_*`, `TFSTATE_*`, `ALLOWED_SSH_CIDR`, `BUDGET_ALERT_EMAIL`) inyectadas vía `env:`/`TF_VAR_*`/`-backend-config` desde `secrets.*` — ninguna hardcodeada en el YAML. Los 10 secrets (incluido `ALLOWED_SSH_CIDR`, añadido tras confirmar la IP del usuario) están configurados en el repo. [R1.4, security.md #8]

## 6. CI — build multi-arch (arm64)

- [x] 6.1 `.github/workflows/multiarch-build-check.yml`: `docker/setup-qemu-action` + `docker/setup-buildx-action` + `docker/build-push-action` `--platform linux/amd64,linux/arm64` contra `backend/devops/Dockerfile` (target `prod`), `push: false`. [R4.1]
- [x] 6.2 Mismo workflow, build `frontend/devops/Dockerfile` (target `prod`) para ambas plataformas, `push: false`. [R4.2]
- [x] 6.3 Verificado en PR real (#7): `build-backend` → **PASS en 1m47s**, `build-frontend` → **PASS en 4m5s**, ambas plataformas (`amd64`+`arm64`), sin necesitar ningún cambio en los Dockerfiles — las imágenes base (`python:3.12-slim`, `astral-sh/uv`, `node:22-slim`) construyeron limpio en `arm64` a la primera, confirmando el riesgo que el ADR marcó como "a verificar". [R4.1, R4.2]
- [x] 6.4 Trigger `pull_request` (paths acotados a los Dockerfiles/lockfiles relevantes) — verificación repetible en cada PR, no manual-una-vez. [R4.3]

## 7. Documentación

- [x] 7.1 Reescrito `infra/environments/dev/README.md`: qué aprovisiona, bootstrap manual del bucket de state, cómo ejecutar `plan`/`apply` (local y vía workflow), tabla de secrets esperados, estado real de la carga de secrets (los 10 ya configurados — actualizado tras QA feature-scale, que detectó que la versión anterior seguía diciendo "pendiente" sobre `ALLOWED_SSH_CIDR` cuando ya no lo estaba), sección "Estado"/"Pendiente" veraz. [R6.1, R6.2]
- [x] 7.2 `README.md` raíz, sección "Estructura": añadidos `infra/` y `.github/workflows/`. [documentation.md]

## 8. Verification

- [x] 8.1 `terraform fmt -check` + `terraform validate` (`-backend=false`) — **PASS**, sin errores (Terraform 1.15.8, provider `oracle/oci` v8.23.0). [R1.2]
- [x] 8.2 `terraform init` con el backend real + `terraform plan` contra la cuenta real (credenciales pasadas por archivo temporal fuera del repo, nunca mostradas ni commiteadas) — **PASS**: backend inicializado ("Successfully configured the backend oci!"), plan **9 to add, 0 to change, 0 to destroy**, sin warnings tras corregir la deprecación de `target_compartment_id`. [R2, R1]
- [x] 8.3 Build multi-arch: no disponible localmente (Docker daemon no corriendo en esta sesión) — verificado en su lugar en CI real (PR #7): `build-backend` PASS (1m47s), `build-frontend` PASS (4m5s), ambas plataformas, sin cambios necesarios en los Dockerfiles. [R4]
- [x] 8.4 Revisión manual de ambos workflows: secrets solo vía `env:`/`-backend-config`, nunca interpolados directamente en el texto de un `run:` step; ningún `set -x`/`echo` de variables sensibles; `apply` solo alcanzable por `workflow_dispatch` con `action: apply` explícito — nunca automático. [security.md #8, R3.2]
- [x] 8.5 `terraform apply` real: **no ejecutado**, como estaba previsto — el `plan` de 8.2 ya demuestra que el `apply` sería viable (9 recursos, sin errores), pero la ejecución real queda pendiente de confirmación explícita del usuario. [Out of scope, proposal.md]
