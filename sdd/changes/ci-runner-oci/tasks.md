# Tasks: ci-runner-oci

<!-- Single-PR migration. Sections leave the system working between them
     (each migrated workflow keeps running, just on the new runner). -->

## 1. Setup — runbook skeleton, README link, QEMU probe

- [ ] 1.1 Crear `docs/ci-runner-rollback.md` con las 6 secciones del design D8 (resumen / tabla / `git revert` / rollback manual / validación / rotación-retirada). La tabla de la §2 queda como placeholder "se completa en §7" hasta migrar todos los workflows. Enlazar desde `README.md` raíz, sección "Infra / CI / runner self-hosted" (R6.1, R6.2).
- [ ] 1.2 Probar QEMU en la VM viva: desde SSH, ejecutar `docker run --privileged --rm tonistiigi/binfmt --install all` y `docker buildx create --use --driver docker-container --bootstrap && docker buildx build --platform linux/amd64 - < <(echo 'FROM alpine:3.19')` para verificar que la emulación amd64 sobre arm64 funciona end-to-end. Documentar el resultado en `sdd/changes/ci-runner-oci/STATE.md` (campo `qemu_verification`). Si falla, marcar en el runbook que `multiarch-build-check.yml` se queda en `ubuntu-latest` desde el inicio (D5 fallback explícito, R4).

## 2. Migrate lightweight contract & guard workflows

- [ ] 2.1 `.github/workflows/api-contract.yml`: `runs-on: ubuntu-latest` → `runs-on: [self-hosted, dev]`. Añadir cabecera de comentario con puntero al runbook (D3, D7). El resto del workflow byte a byte: `permissions`, `concurrency`, `timeout-minutes`, actions pineadas por SHA. [R1] [R2]
- [ ] 2.2 `.github/workflows/compose-ports.yml`: idem. [R1] [R2]
- [ ] 2.3 `.github/workflows/frontend-api-contract.yml`: idem. [R1] [R2]
- [ ] 2.4 `.github/workflows/rule11-ownership.yml`: idem. [R1] [R2]

## 3. Migrate backend-tests.yml

- [ ] 3.1 `.github/workflows/backend-tests.yml` (3 jobs: `backend-tests-detect`, `backend-tests-suite`, `backend-tests`): `runs-on` de los 3 jobs a `[self-hosted, dev]`. Mantener el `concurrency` por ref con `cancel-in-progress: true`. Cabecera de comentario. El cambio se queda byte a byte fuera del `runs-on` y la cabecera. [R1] [R2] [R7]

## 4. Migrate frontend-tests.yml + infra-dev.yml

- [ ] 4.1 `.github/workflows/frontend-tests.yml` (2 jobs): `runs-on` a `[self-hosted, dev]`. Concurrency por ref con `cancel-in-progress: true`. Cabecera de comentario. [R1] [R2] [R7]
- [ ] 4.2 `.github/workflows/infra-dev.yml` (3 jobs: `check`, `plan`, `apply`): `runs-on` a `[self-hosted, dev]` en los 3 jobs. Mantener el actor IAM `svc-terraform-dev` — no se mueve a `instance_principal` (D6). `secrets.OCI_PRIVATE_KEY` se sigue escribiendo a `$RUNNER_TEMP/oci_private_key.pem` (`infra-dev.yml:62-66`, `infra-dev.yml:152-156`), el cleanup por job del runner ya cubre la persistencia. Concurrency de `apply` (`group: infra-dev-apply`, `cancel-in-progress: false`) intacto. Cabecera de comentario. [R1] [R2] [R5] [R7]

## 5. Migrate deploy-dev.yml build jobs

- [ ] 5.1 `.github/workflows/deploy-dev.yml` (3 jobs a migrar: `provenance`, `build-backend`, `build-frontend`): `runs-on` de los 3 a `[self-hosted, dev]`. El job `deploy` ya está en `[self-hosted, dev]`, sin cambios. Mantener `concurrency` exacto: `build-backend-${{ github.ref }}` y `build-frontend-${{ github.ref }}` con `cancel-in-progress: true` en los builds, `group: deploy-dev` con `cancel-in-progress: false` en el deploy (compartido con `demo-reset.yml`, ver D4). `docker/login-action` sigue usando `GITHUB_TOKEN` (`packages: write`) — sin nuevo secret (R5). Cabecera de comentario. [R1] [R2] [R3] [R5] [R7]

## 6. Migrate multiarch-build-check.yml (QEMU caveat)

- [ ] 6.1 `.github/workflows/multiarch-build-check.yml` (2 jobs: `build-backend`, `build-frontend`): `runs-on` a `[self-hosted, dev]`. Mantener `docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3` + `docker/build-push-action@v6` con `platforms: linux/amd64,linux/arm64`, `push: false`. Cabecera de comentario. **SI** la verificación de §1.2 reveló que QEMU no se registra en binfmt, **revertir solo este workflow** a `runs-on: ubuntu-latest` y declarar la excepción ("9 de 10 migrados, 1 excepción deliberada") en la tabla del runbook (D5, R4). [R1] [R2] [R4] [R7]

## 7. demo-reset.yml header + runbook finalization + verification

- [ ] 7.1 `.github/workflows/demo-reset.yml`: el `runs-on: [self-hosted, dev]` ya está (caso base). Solo actualizar la cabecera de comentario para incluir el puntero al runbook. [R1]
- [ ] 7.2 Rellenar la tabla de `docs/ci-runner-rollback.md` §2 con los valores reales: workflow / `runs-on` previo / `runs-on` actual / excepción (multiarch-build-check si QEMU falló). Confirmar que la tabla cubre los 10 workflows y coincide con los `.yml` migrados (R6.1, R6.3). Verificar que `pr-review-cicd` (cuando se añada el chequeo de `runs-on:`) lo dé por bueno.
- [ ] 7.3 Verificación end-to-end (R7): ejecutar `gh run list --workflow=<name> --json name,conclusion,runner --limit 1` por los 10 workflows contra el commit del PR. Para los que no se disparen en push/PR (típicamente `demo-reset.yml` por schedule), correr `workflow_dispatch` ad-hoc. Adjuntar la salida al PR como evidencia. Si algún workflow queda rojo, NO abrir el PR — escribir el bloqueo en `STATE.md` y `BLOCKED.md`, y reabrir §5 o §6 según corresponda. [R7]

## Implementation Notes

(Implementers: append here any decision, name or gotcha that the next section needs to know.)
