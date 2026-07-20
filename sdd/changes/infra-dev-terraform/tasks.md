# Tasks: infra-dev-terraform

## 1. Root module — red y cómputo

- [ ] 1.1 `infra/environments/dev/variables.tf`: declarar `tenancy_ocid`, `user_ocid`, `fingerprint`, `private_key` (`sensitive = true`), `region`, `compartment_ocid`, `allowed_ssh_cidr` (sin default abierto a `0.0.0.0/0`) — ninguna con valor por defecto real. [R1.4]
- [ ] 1.2 `infra/environments/dev/main.tf`: bloque `terraform { required_version = ">= 1.12", required_providers { oci = { source = "oracle/oci" } } }` y bloque `provider "oci"`. [R1.1]
- [ ] 1.3 `infra/environments/dev/main.tf`: VCN `10.0.0.0/16` + subred pública `10.0.1.0/24` (`oci_core_vcn`, `oci_core_subnet`, internet gateway + route table). [R1.1]
- [ ] 1.4 `infra/environments/dev/main.tf`: security list con ingress TCP 22 (restringido por `var.allowed_ssh_cidr`), 8000, 3000; egress abierto. Exactamente estos puertos, ninguno más (`docker-compose.yml`). [R1.1]
- [ ] 1.5 `infra/environments/dev/main.tf`: `oci_core_instance` shape `VM.Standard.A1.Flex` (2 OCPU/12 GB), imagen ARM64 elegible Always Free (confirmar el OCID/nombre de imagen vigente contra la lista actual de OCI para `eu-frankfurt-1`), `oci_core_public_ip` tipo `RESERVED` asociada a la VNIC. `cloud-init` mínimo: instala Docker + Docker Compose plugin. [R1.1]
- [ ] 1.6 `infra/environments/dev/outputs.tf`: exponer la IP pública de la instancia (para el futuro workflow de despliegue de la app, fuera de alcance aquí). [R1.1]
- [ ] 1.7 `terraform fmt` + `terraform validate` (con `-backend=false`) sobre `infra/environments/dev/` pasan sin error. [R1.2]

## 2. Backend de state remoto (`oci` nativo)

- [ ] 2.1 `infra/environments/dev/backend.tf`: `terraform { backend "oci" {} }` con configuración parcial (sin namespace/bucket/región hardcodeados). [R2, D7]
- [ ] 2.2 `infra/environments/dev/backend.hcl.example`: documentar los nombres de las claves de `-backend-config` esperadas (`namespace`, `bucket`, `region`, `key`), sin valores reales. [R2, D7]
- [ ] 2.3 Verificar con `terraform init -backend-config=...` usando los secrets ya configurados (`TFSTATE_NAMESPACE=frag3zplc9up`, `TFSTATE_BUCKET=autohostai-tfstate-dev`) que el backend real inicializa correctamente contra el bucket ya creado por el usuario. [R2]

## 3. Alerta de presupuesto

- [ ] 3.1 `infra/environments/dev/main.tf`: `oci_budget_budget` (`target_type = "COMPARTMENT"`, `amount` configurable por variable) + `oci_budget_alert_rule` (`type = "ACTUAL"`, `threshold` por variable `budget_alert_threshold_percent` con default documentado, `recipients` desde variable obligatoria `budget_alert_email` sin default). [R5.1]
- [ ] 3.2 Confirmar en `variables.tf` que `budget_alert_email` falla la validación (`variable` sin default, o `validation` block) si no se pasa — no debe poder desplegarse una alerta sin destinatario. [R5.2]

## 4. CI — validación en PR (sin credenciales)

- [ ] 4.1 `.github/workflows/infra-dev.yml`, job `check`: trigger `pull_request` (paths: `infra/environments/dev/**`) → `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`. [R3.3]
- [ ] 4.2 Verificar (abriendo un PR de prueba de esta rama, o `act`/revisión manual del YAML) que el job `check` completa sin necesitar ningún secret. [R3.3]

## 5. CI — plan/apply manual

- [ ] 5.1 Mismo `.github/workflows/infra-dev.yml`, job `plan-apply`: trigger `workflow_dispatch` (input `action`: `plan`|`apply`) → checkout, `hashicorp/setup-terraform` (versión ≥1.12), `terraform init` con `-backend-config` desde secrets, `terraform plan` (guardando el plan como artifact), `terraform apply -auto-approve` **solo si** `action == 'apply'`. [R3.1, R3.2]
- [ ] 5.2 Todas las variables sensibles (`OCI_*`, `TFSTATE_*`) inyectadas vía `TF_VAR_*`/`-backend-config` desde `secrets.*` — ninguna hardcodeada en el YAML. [R1.4, security.md #8]

## 6. CI — build multi-arch (arm64)

- [ ] 6.1 `.github/workflows/multiarch-build-check.yml`: `docker/setup-qemu-action` + `docker/setup-buildx-action` + `docker buildx build --platform linux/amd64,linux/arm64` contra `backend/devops/Dockerfile` (target `prod`), sin `--push`. [R4.1]
- [ ] 6.2 Mismo workflow, build `frontend/devops/Dockerfile` (target `prod`) para ambas plataformas, sin `--push`. [R4.2]
- [ ] 6.3 Si el build `arm64` falla por algo específico de una capa (p. ej. un binario `amd64`-only), corregir `backend/devops/Dockerfile`/`frontend/devops/Dockerfile` mínimamente para soportar ambas plataformas. [R4.1, R4.2]
- [ ] 6.4 Confirmar que el workflow corre en cada PR (mismo trigger `pull_request`, sin necesitar credenciales de OCI) — verificación repetible, no manual-una-vez. [R4.3]

## 7. Documentación

- [ ] 7.1 Reescribir `infra/environments/dev/README.md`: qué aprovisiona, bootstrap manual del bucket de state (ya hecho, documentar los pasos para que sea reproducible), cómo ejecutar `plan`/`apply` (local y vía workflow), tabla de secrets esperados, sección "Estado" veraz (código+pipeline verificados; `apply` real pendiente de confirmación explícita). [R6.1, R6.2]
- [ ] 7.2 Actualizar `README.md` raíz, sección "Estructura": añadir `infra/` (real desde este change) y `.github/workflows/` a la lista. [documentation.md]

## 8. Verification

- [ ] 8.1 `cd infra/environments/dev && terraform fmt -check && terraform validate` (con `-backend=false`) — sin errores. [R1.2]
- [ ] 8.2 `terraform init` con el backend real (`-backend-config` con los valores del usuario) y `terraform plan` contra la cuenta real — completa sin errores de sintaxis/referencia (esto es una lectura contra la API de OCI, no crea recursos). [R2, R1]
- [ ] 8.3 Build multi-arch local de verificación: `docker buildx build --platform linux/amd64,linux/arm64 -f backend/devops/Dockerfile --target prod backend/` y lo mismo para `frontend` — ambos sin error. [R4]
- [ ] 8.4 Revisión manual del YAML de ambos workflows: ningún secret expuesto en logs (`set -x` evitado en steps con variables sensibles), ningún trigger automático de `apply`. [security.md #8, R3.2]
- [ ] 8.5 `terraform apply` real: **no se ejecuta como parte de esta verificación automática** — queda como acción explícita, confirmada por el usuario, después de este change (ver proposal.md, Out of scope).
