# Tasks: infra-dev-terraform

## 1. Root module — red y cómputo <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa) -->

- [x] 1.1 `infra/environments/dev/variables.tf`: declarar `tenancy_ocid`, `user_ocid`, `fingerprint`, `private_key` (`sensitive = true`), `region`, `compartment_ocid`, `allowed_ssh_cidr` (sin default abierto a `0.0.0.0/0`, con `validation` block que lo rechaza) — ninguna con valor por defecto real. [R1.4]
- [x] 1.2 `infra/environments/dev/main.tf`: bloque `terraform { required_version = ">= 1.12", required_providers { oci = { source = "oracle/oci" } } }` y bloque `provider "oci"`. [R1.1]
- [x] 1.3 `infra/environments/dev/main.tf`: VCN `10.0.0.0/16` + subred pública `10.0.1.0/24` (`oci_core_vcn`, `oci_core_subnet`, internet gateway + route table). [R1.1]
- [x] 1.4 `infra/environments/dev/main.tf`: security list con ingress TCP 22 (restringido por `var.allowed_ssh_cidr`), 8000, 3000; egress abierto. Exactamente estos puertos, ninguno más (`docker-compose.yml`). [R1.1]
- [x] 1.5 `infra/environments/dev/main.tf`: `oci_core_instance` shape `VM.Standard.A1.Flex` (2 OCPU/12 GB), imagen ARM64 resuelta vía `data.oci_core_images` (Canonical Ubuntu 22.04, nunca un OCID hardcodeado), `oci_core_public_ip` tipo `RESERVED` asociada vía `data.oci_core_private_ips`. `cloud-init` mínimo: instala Docker + Docker Compose plugin. [R1.1]
- [x] 1.6 `infra/environments/dev/outputs.tf`: expone `instance_public_ip` e `instance_id`. [R1.1]
- [x] 1.7 `terraform fmt -check` + `terraform validate` (con `-backend=false`) sobre `infra/environments/dev/` — verificado contra el binario real (Terraform 1.15.8) y el schema real del provider `oracle/oci` v8.23.0: sin error. [R1.2]

## 2. Backend de state remoto (`oci` nativo) <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa; R2.3 doc gap fixed in design.md D7 + README) -->

- [x] 2.1 `infra/environments/dev/backend.tf`: `terraform { backend "oci" {} }` con configuración parcial (sin namespace/bucket/región hardcodeados). [R2, D7]
- [x] 2.2 `infra/environments/dev/backend.hcl.example`: documenta las claves de `-backend-config` reales (`bucket`, `namespace`, `key`, `region`, más `tenancy_ocid`/`user_ocid`/`fingerprint`/`private_key` — confirmado empíricamente que el backend `oci` necesita su propia autenticación, no puede leer `var.*` del provider), sin valores reales. [R2, D7]
- [x] 2.3 Verificado con `terraform init -backend-config=...` real (namespace `frag3zplc9up`, bucket `autohostai-tfstate-dev`, credenciales reales pasadas por archivo temporal fuera del repo, nunca mostradas): **"Successfully configured the backend oci!"** contra el bucket ya creado por el usuario. [R2]

## 3. Alerta de presupuesto <!-- panel: PASS 2026-07-20 (sdd-architect, sdd-security, sdd-qa; R5.2 validation dynamically confirmed with a standalone terraform plan probe) -->

- [x] 3.1 `infra/environments/dev/main.tf`: `oci_budget_budget` (`target_type = "COMPARTMENT"`, `targets = [var.compartment_ocid]`, `amount` configurable por variable) + `oci_budget_alert_rule` (`type = "ACTUAL"`, `threshold` por variable `budget_alert_threshold_percent`, `recipients` desde variable obligatoria `budget_alert_email` sin default). [R5.1]
- [x] 3.2 `variables.tf`: `budget_alert_email` lleva `validation` block que rechaza cadena vacía — no puede desplegarse una alerta sin destinatario. [R5.2]

## 4. CI — validación en PR (sin credenciales)

- [x] 4.1 `.github/workflows/infra-dev.yml`, job `check`: trigger `pull_request` (paths: `infra/environments/dev/**`) → `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`. [R3.3]
- [ ] 4.2 Verificar abriendo un PR real de esta rama que el job `check` completa sin necesitar ningún secret. [R3.3] — pendiente de abrir el PR (sección 8).

## 5. CI — plan/apply manual

- [x] 5.1 Mismo `.github/workflows/infra-dev.yml`, job `plan-apply`: trigger `workflow_dispatch` (input `action`: `plan`|`apply`) → checkout, `hashicorp/setup-terraform` (1.15.8, ≥1.12), backend.hcl generado en runtime desde secrets, `terraform init -backend-config=backend.hcl`, `terraform plan -out=tfplan`, `terraform apply -auto-approve tfplan` **solo si** `action == 'apply'` (mismo job, no requiere subir el plan como artifact cross-job). [R3.1, R3.2]
- [x] 5.2 Todas las variables sensibles (`OCI_*`, `TFSTATE_*`, `ALLOWED_SSH_CIDR`, `BUDGET_ALERT_EMAIL`) inyectadas vía `env:`/`TF_VAR_*`/`-backend-config` desde `secrets.*` — ninguna hardcodeada en el YAML. Nota: falta añadir el secret `ALLOWED_SSH_CIDR` (no estaba en la lista original de 9) — documentado en el README, pendiente de que el usuario lo añada antes de un `apply` real. [R1.4, security.md #8]

## 6. CI — build multi-arch (arm64)

- [x] 6.1 `.github/workflows/multiarch-build-check.yml`: `docker/setup-qemu-action` + `docker/setup-buildx-action` + `docker/build-push-action` `--platform linux/amd64,linux/arm64` contra `backend/devops/Dockerfile` (target `prod`), `push: false`. [R4.1]
- [x] 6.2 Mismo workflow, build `frontend/devops/Dockerfile` (target `prod`) para ambas plataformas, `push: false`. [R4.2]
- [ ] 6.3 Si el build `arm64` falla en CI por algo específico de una capa, corregir `backend/devops/Dockerfile`/`frontend/devops/Dockerfile` mínimamente. [R4.1, R4.2] — no verificable localmente (Docker daemon no disponible en esta sesión); se confirma al abrir el PR (sección 8).
- [x] 6.4 Trigger `pull_request` (paths acotados a los Dockerfiles/lockfiles relevantes) — verificación repetible en cada PR, no manual-una-vez. [R4.3]

## 7. Documentación

- [x] 7.1 Reescrito `infra/environments/dev/README.md`: qué aprovisiona, bootstrap manual del bucket de state, cómo ejecutar `plan`/`apply` (local y vía workflow), tabla de secrets esperados (incluye `ALLOWED_SSH_CIDR`, pendiente de que el usuario lo añada), sección "Estado" veraz. [R6.1, R6.2]
- [x] 7.2 `README.md` raíz, sección "Estructura": añadidos `infra/` y `.github/workflows/`. [documentation.md]

## 8. Verification

- [ ] 8.1 `cd infra/environments/dev && terraform fmt -check && terraform validate` (con `-backend=false`) — sin errores. [R1.2]
- [ ] 8.2 `terraform init` con el backend real (`-backend-config` con los valores del usuario) y `terraform plan` contra la cuenta real — completa sin errores de sintaxis/referencia (esto es una lectura contra la API de OCI, no crea recursos). [R2, R1]
- [ ] 8.3 Build multi-arch local de verificación: `docker buildx build --platform linux/amd64,linux/arm64 -f backend/devops/Dockerfile --target prod backend/` y lo mismo para `frontend` — ambos sin error. [R4]
- [ ] 8.4 Revisión manual del YAML de ambos workflows: ningún secret expuesto en logs (`set -x` evitado en steps con variables sensibles), ningún trigger automático de `apply`. [security.md #8, R3.2]
- [ ] 8.5 `terraform apply` real: **no se ejecuta como parte de esta verificación automática** — queda como acción explícita, confirmada por el usuario, después de este change (ver proposal.md, Out of scope).
