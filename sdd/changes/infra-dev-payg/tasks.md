# Tasks: infra-dev-payg

> Estado real: R2/R3/R5 (código) ya implementados y verificados esta sesión — pre-marcados `[x] (preexistente)`. Queda R6 (documentación de la decisión) y la aplicación del resize vía pipeline + expansión de disco en el SO.

## 1. Reconfiguración de la instancia dev (Terraform)

- [x] 1.1 Redimensionar `shape_config` a 4 OCPU / 24 GB y añadir `boot_volume_size_in_gbs = 200` (cupo free de block storage) — **Files:** `infra/environments/dev/main.tf` — (preexistente) — [R2]
- [x] 1.2 Confirmar por `terraform plan` que el cambio es **in-place** (`0 to destroy`, todo `~ update in-place`) con `ad_number` apuntando al AD real de la instancia — **Files:** ninguno (verificación read-only, ejecutada esta sesión con `-lock=false`) — (preexistente) — [R2]
- [x] 1.3 Verificar que la alerta de presupuesto (`oci_budget_budget` mensual + `oci_budget_alert_rule` tipo `ACTUAL`, destinatario obligatorio) sigue desplegada como salvaguarda del riesgo de facturación PAYG — **Files:** `infra/environments/dev/main.tf` — (preexistente de `infra-dev-terraform`) — [R4]

## 2. Reconciliación del pipeline

- [x] 2.1 Fijar el default de `ad_number` del `workflow_dispatch` a "3" (AD real donde se bootstrapeó la instancia), con descripción que advierte que cambiarlo fuerza destrucción + recreación — **Files:** `.github/workflows/infra-dev.yml` — (preexistente) — [R3]

## 3. Higiene de repositorio y secretos

- [x] 3.1 Blindar `.gitignore`: ignorar todo `**/*.hcl` salvo `.terraform.lock.hcl` (caza typos como `backekn.hcl` que filtrarían credenciales del backend), más `*.pem`, `**/*.log` y `apply_loop.sh` (local-only) — **Files:** `.gitignore` — (preexistente) — [R5]
- [x] 3.2 Eliminar del working tree los artefactos del bootstrap manual sin valor versionable: `oci_provision.log` (35 MB) y `backekn.hcl` (duplicado stray con secretos del backend) — **Files:** `infra/environments/dev/oci_provision.log`, `infra/environments/dev/backekn.hcl` (borrados) — (preexistente) — [R5]
- [x] 3.3 Auditar que ninguna credencial real esté en el historial de git (`dev.tfvars`, `*.pem`, `backend.hcl` real, fingerprint, tenancy OCID) — **Files:** ninguno (auditoría `git log --all -S`, ejecutada esta sesión: sin resultados) — (preexistente) — [R5]

## 4. Registro de la decisión (documentación)

- [x] 4.1 Añadir addendum fechado al `docs/adr/0001-dev-hosting-provider.md`: activación del criterio de revisión #5 (paso a PAYG), resultado del debate reabierto (precios verificados 2026 — Hetzner CX33 ~€9, Lightsail ~$44, Contabo/Netcup; se mantiene Oracle), y la nueva configuración de `dev` (4 OCPU/24 GB/200 GB, AD-3, tenancy PAYG) — **Files:** `docs/adr/0001-dev-hosting-provider.md` — [R1, R6]
- [x] 4.2 Documentar en el ADR/addendum el carácter **unidireccional** del PAYG (no hay downgrade a Always Free-only) y la única vía de "coste $0" (permanecer dentro de límites free; terminar recursos de pago), más que conserva toda la capa gratuita y da prioridad de capacidad — **Files:** `docs/adr/0001-dev-hosting-provider.md` — [R1]
- [x] 4.3 Actualizar la spec `sdd/specs/infra-dev-terraform.md`: de "2 OCPU/12 GB Always Free" a "4 OCPU/24 GB/200 GB en tenancy PAYG, AD-3", y reflejar el default de `ad_number` = 3 — **Files:** `sdd/specs/infra-dev-terraform.md` — [R6]
- [x] 4.4 Actualizar el steering `sdd/steering/infra.md`: decisión de `dev` de Always Free → PAYG (conservando íntegra la tabla comparativa como histórico) — **Files:** `sdd/steering/infra.md` — [R6]

## 5. Verificación

- [x] 5.1 `terraform fmt -check -diff` y `terraform validate` pasan en `infra/environments/dev/` (los ejecuta el job `check` del workflow en el PR) — **Files:** solo correcciones de formato si falla — [R2, R3]
- [ ] 5.2 Ejecutar el `workflow_dispatch` (`action=apply`, `ad_number=3`) tras el merge y confirmar en el run que el plan es `0 to destroy` y la instancia queda en 4 OCPU / 24 GB — **Files:** ninguno (operación vía pipeline) — [R2, R3]
- [ ] 5.3 Tras el apply, expandir la partición en el SO por SSH (`sudo /usr/libexec/oci-growfs -y`, o `sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1`) y verificar 200 GB usables (`df -h`) — **Files:** ninguno (operación en la VM) — [R2]
- [x] 5.4 Confirmar `git status` limpio: sin secretos ni cruft trackeados; `dev.tfvars`, `backend.hcl`, `*.pem`, `*.log` y `apply_loop.sh` efectivamente ignorados (`git check-ignore -v`) — **Files:** ninguno (verificación) — [R5]
