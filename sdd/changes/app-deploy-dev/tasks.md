# Tasks: app-deploy-dev

> Change de infra/CI — **no toca código de dominio backend/frontend**, así que las reglas de unit/integration/tenant-isolation de `steering/testing.md` no aplican (no hay `domain/` que testear). La verificación es por **runs de CI, `terraform plan` y deploy real** (§7). Las tareas marcadas **(op.)** son operaciones en tu consola (GitHub/OCI/VM), al estilo de las ops del hardening.

## 1. Build y publicación de imágenes en GHCR <!-- panel: PASS 2026-07-24 -->

- [x] 1.1 Crear `.github/workflows/deploy-dev.yml` con `on: push: branches:[main]` + `paths` (`backend/**`, `frontend/**`, sus Dockerfiles/lockfiles, `docker-compose.deploy.yml`, el propio workflow) y `workflow_dispatch`; jobs `build-backend` y `build-frontend` en `ubuntu-latest` con `docker/build-push-action` (pineado por SHA), `target: prod`, `platforms: linux/arm64`, `push: true`, `permissions: packages: write`, auth con `GITHUB_TOKEN`; tags `sha-<commit>` (inmutable) + `dev`. — **Files:** `.github/workflows/deploy-dev.yml` — [R1]
- [x] 1.2 Declarar `ARG`/`ENV` para las `NEXT_PUBLIC_*` en `frontend/devops/Dockerfile` (stage builder, antes de `npm run build`) y pasarlas como `build-args` en `build-frontend` — quedan horneadas en la imagen, no en runtime. — **Files:** `frontend/devops/Dockerfile`, `.github/workflows/deploy-dev.yml` — [R1]
- [x] 1.3 Fijar todas las Actions del workflow por SHA de commit (convención del repo, igual que `infra-dev.yml`). — **Files:** `.github/workflows/deploy-dev.yml` — [R1, R3]

## 2. Compose de deploy y plantilla de entorno <!-- panel: PASS 2026-07-24 -->

- [x] 2.1 Crear `docker-compose.deploy.yml` en la raíz: `backend`/`worker`/`frontend` con `image: ghcr.io/${GHCR_NS}/autohostai-<svc>:${IMAGE_TAG}` (**sin `build`**, sin bind-mounts), `postgres:16`/`redis:7` con volúmenes nombrados persistentes, `restart: unless-stopped`, y healthchecks para backend (`/health`) y frontend (`:3000`). — **Files:** `docker-compose.deploy.yml` — [R2, R5]
- [x] 2.2 Añadir servicio `migrate` one-shot en el compose de deploy: **imagen prod del backend**, `restart: "no"`, `command: alembic upgrade head` (binario de `.venv/bin`, no `uv run`), `depends_on: postgres (healthy)`; backend/worker con `depends_on: migrate (service_completed_successfully)`. — **Files:** `docker-compose.deploy.yml` — [R2]
- [x] 2.3 Crear `.env.deploy.example` con la lista de claves de runtime esperadas (`POSTGRES_*`, `JWT_*`/`ENCRYPTION_KEY`, `BACKEND_INTERNAL_URL`, `IMAGE_TAG`, `GHCR_NS`, …) **sin valores**; documentar que las `NEXT_PUBLIC_*` van como build-args (§1.2), no aquí. — **Files:** `.env.deploy.example` — [R4]

## 3. Provisión del runner + secrets como IaC (Terraform)

<!-- Reabierto 2026-07-24: rediseño "endurecer hacia IaC" — registro vía GitHub App (no PAT) y
     secrets de runtime generados por Terraform → Vault (D13/D14). El cloud-init (§3.1 estructura)
     y el patrón templatefile se conservan; cambia la lógica del bootstrap y la IAM/variables. -->

- [ ] 3.1 Reescribir `runner-bootstrap.sh` para registrar el runner minteando un **installation-token de GitHub App**: leer la clave privada de la App del Vault (instance principal), firmar el JWT de App, obtener installation-token → registration-token, `config.sh --labels dev --unattended`, `svc.sh install/start`. El cloud-init (`cloud-init.yaml.tftpl`) inyecta `app_id`/`installation_id`/OCID de la clave. — **Files:** `infra/environments/dev/{runner-bootstrap.sh,cloud-init.yaml.tftpl,main.tf}` — [R7]
- [ ] 3.2 Generar los secrets de runtime con Terraform y guardarlos en el Vault: `random_password` (POSTGRES_PASSWORD, JWT_SECRET_KEY) + `random_bytes` → clave Fernet (ENCRYPTION_KEY, base64url); un `oci_vault_secret` por cada uno. `POSTGRES_DB`/`POSTGRES_USER` como variables con default. — **Files:** `infra/environments/dev/{main.tf,variables.tf}` — [R8]
- [ ] 3.3 Ajustar la IAM del instance principal: `oci_identity_policy` de mínimo privilegio que autorice a leer **la clave de la App + los 3 secrets de runtime** (`where any {target.secret.id = ...}`); sustituir `runner_pat_secret_ocid` por `runner_app_key_secret_ocid` + `github_app_id`/`github_app_installation_id` en variables y `dev.tfvars.example`. — **Files:** `infra/environments/dev/{main.tf,variables.tf,dev.tfvars.example}` — [R7]
- [ ] 3.4 `terraform fmt -check` + `validate` + render del cloud-init (YAML válido) + `bash -n` del bootstrap. El **`plan`** real (add de policy + `random_*` + `oci_vault_secret`, **0 recreación** de la instancia) → pipeline, §5.3. — **Files:** ninguno (verificación) — [R7, R8]

## 4. Job de deploy (runner self-hosted, local)

- [x] 4.1 Añadir job `deploy` a `deploy-dev.yml`: `runs-on: [self-hosted, dev]`, `needs: [build-backend, build-frontend]`, `if: github.ref == 'refs/heads/main'`, `concurrency: { group: deploy-dev, cancel-in-progress: false }`, `timeout-minutes`. — **Files:** `.github/workflows/deploy-dev.yml` — [R3] (sin cambios en el rediseño)
- [ ] 4.2 Paso de render del `.env` leyendo los secrets del **OCI Vault** (instance principal, `oci secrets secret-bundle get`) con **validación previa** (falla nombrando la clave que no se pudo leer, antes de tocar contenedores), `chmod 600`; añade `IMAGE_TAG=sha-<sha>` y `GHCR_NS`. — **Files:** `.github/workflows/deploy-dev.yml` (+ helper en la VM si aplica) — [R4]
- [ ] 4.3 Paso `docker login ghcr.io -u x-access-token` con un **installation-token de la GitHub App** minteado en la VM (misma clave del Vault, permiso `packages: read`) y `docker logout` al finalizar. — **Files:** `.github/workflows/deploy-dev.yml` — [R3]
- [x] 4.4 Paso de deploy: `docker compose -f docker-compose.deploy.yml pull` + `up -d --wait --wait-timeout 180`; en fallo, volcar `docker compose logs` y salir ≠0. — **Files:** `.github/workflows/deploy-dev.yml` — [R3, R5] (sin cambios)

## 5. Operaciones (tu consola — GitHub/OCI)

- [ ] 5.1 (op.) Crear una **GitHub App** (permisos repo: `Administration: read/write` para runners, `Packages: read` para GHCR), instalarla en el repo, y anotar `app_id` + `installation_id` (van a `dev.tfvars`, no son secretos). — **Files:** ninguno (op. GitHub) — [R7]
- [ ] 5.2 (op.) Subir la **clave privada (.pem) de la App** al **OCI Vault** out-of-band (`oci vault secret create-base64`) y anotar su OCID en `dev.tfvars` (`runner_app_key_secret_ocid`). Único secret-zero. — **Files:** ninguno (op. OCI); RUNBOOK — [R7]
- [ ] 5.3 (op.) Aplicar Terraform por el pipeline (`workflow_dispatch` `apply` de `infra-dev.yml` desde `main`): crea dynamic group + policy + `random_*` + `oci_vault_secret` de runtime. Confirmar **`0 to destroy`** (instancia intacta). — **Files:** ninguno (op. pipeline) — [R7, R8]
- [ ] 5.4 (op.) Provisionar el runner en la **VM viva a mano, una sola vez** (mismos comandos que el cloud-init de §3.1, minteando el token vía la App desde el Vault); verificar **online con label `dev`** en Settings → Actions → Runners. — **Files:** ninguno (op. VM); RUNBOOK — [R3, R7]
- [ ] 5.5 (op.) Limpiar los 6 GitHub Secrets de app creados en el primer intento (`POSTGRES_*`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) — ya no se usan (el deploy lee del Vault); dejar solo `NEXT_PUBLIC_APP_ENV` como **variable** de repo. — **Files:** ninguno (op. GitHub) — [R8]

## 6. Documentación

- [ ] 6.1 Actualizar `infra/environments/dev/RUNBOOK.md` §6: flujo de deploy, provisión/recuperación del runner, **GitHub App** (permisos, alta de la clave en Vault, rotación), secrets de runtime generados por TF, arranque en frío, rollback. — **Files:** `infra/environments/dev/RUNBOOK.md` — [R6]
- [ ] 6.2 Actualizar los READMEs (raíz + dev): deploy dev con GitHub App + secrets desde Vault (sin GitHub Secrets de app). — **Files:** `README.md`, `infra/environments/dev/README.md` — [R6]

## 7. Verificación end-to-end

- [ ] 7.1 Build: un run (push a `main` o `workflow_dispatch`) publica **ambas imágenes arm64** en GHCR con tags `sha-<commit>` y `dev`. — [R1]
- [ ] 7.2 Deploy real: el job `deploy` corre en el runner self-hosted, mintea el token GHCR de la App, lee los secrets del Vault, `migrate` aplica migraciones, y `up -d --wait` deja backend/worker/frontend **`healthy`**. — [R3, R4, R5]
- [ ] 7.3 Smoke: `GET /health` (8000) y el frontend (3000) responden desde un CIDR de operador; los volúmenes de `postgres`/`redis` siguen intactos tras el deploy. — [R5]
- [ ] 7.4 Rollback: un redeploy con un `IMAGE_TAG` de un SHA previo restaura esa versión de la app. — [R6]
- [ ] 7.5 Seguridad/reachability: confirmar que el deploy **no requirió abrir puertos** (security list sin cambios), el `.env` renderizado tiene permisos restringidos, la **clave de la App NO** está en el `tfstate` (solo su OCID) y no hay secretos en el repo/imagen. Los secrets de runtime en el `tfstate` son intencionales (D14, dev). — [R3, R4, R7, R8]
