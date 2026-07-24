# Tasks: app-deploy-dev

> Change de infra/CI — **no toca código de dominio backend/frontend**, así que las reglas de unit/integration/tenant-isolation de `steering/testing.md` no aplican (no hay `domain/` que testear). La verificación es por **runs de CI, `terraform plan` y deploy real** (§7). Las tareas marcadas **(op.)** son operaciones en tu consola (GitHub/OCI/VM), al estilo de las ops del hardening.

## 1. Build y publicación de imágenes en GHCR

- [x] 1.1 Crear `.github/workflows/deploy-dev.yml` con `on: push: branches:[main]` + `paths` (`backend/**`, `frontend/**`, sus Dockerfiles/lockfiles, `docker-compose.deploy.yml`, el propio workflow) y `workflow_dispatch`; jobs `build-backend` y `build-frontend` en `ubuntu-latest` con `docker/build-push-action` (pineado por SHA), `target: prod`, `platforms: linux/arm64`, `push: true`, `permissions: packages: write`, auth con `GITHUB_TOKEN`; tags `sha-<commit>` (inmutable) + `dev`. — **Files:** `.github/workflows/deploy-dev.yml` — [R1]
- [x] 1.2 Declarar `ARG`/`ENV` para las `NEXT_PUBLIC_*` en `frontend/devops/Dockerfile` (stage builder, antes de `npm run build`) y pasarlas como `build-args` en `build-frontend` — quedan horneadas en la imagen, no en runtime. — **Files:** `frontend/devops/Dockerfile`, `.github/workflows/deploy-dev.yml` — [R1]
- [x] 1.3 Fijar todas las Actions del workflow por SHA de commit (convención del repo, igual que `infra-dev.yml`). — **Files:** `.github/workflows/deploy-dev.yml` — [R1, R3]

## 2. Compose de deploy y plantilla de entorno

- [x] 2.1 Crear `docker-compose.deploy.yml` en la raíz: `backend`/`worker`/`frontend` con `image: ghcr.io/${GHCR_NS}/autohostai-<svc>:${IMAGE_TAG}` (**sin `build`**, sin bind-mounts), `postgres:16`/`redis:7` con volúmenes nombrados persistentes, `restart: unless-stopped`, y healthchecks para backend (`/health`) y frontend (`:3000`). — **Files:** `docker-compose.deploy.yml` — [R2, R5]
- [x] 2.2 Añadir servicio `migrate` one-shot en el compose de deploy: **imagen prod del backend**, `restart: "no"`, `command: alembic upgrade head` (binario de `.venv/bin`, no `uv run`), `depends_on: postgres (healthy)`; backend/worker con `depends_on: migrate (service_completed_successfully)`. — **Files:** `docker-compose.deploy.yml` — [R2]
- [x] 2.3 Crear `.env.deploy.example` con la lista de claves de runtime esperadas (`POSTGRES_*`, `JWT_*`/`ENCRYPTION_KEY`, `BACKEND_INTERNAL_URL`, `IMAGE_TAG`, `GHCR_NS`, …) **sin valores**; documentar que las `NEXT_PUBLIC_*` van como build-args (§1.2), no aquí. — **Files:** `.env.deploy.example` — [R4]

## 3. Provisión del runner como IaC (Terraform)

- [x] 3.1 Añadir al cloud-init de la instancia (`infra/environments/dev/main.tf`, plantilla `user_data`) el bloque de provisión del runner: descarga del binario, `config.sh --url <repo> --labels dev --unattended`, `svc.sh install && svc.sh start`, usuario del runner en el grupo `docker`; el registration-token se obtiene en arranque leyendo el PAT desde el secret del OCI Vault vía instance principal. — **Files:** `infra/environments/dev/{main.tf,cloud-init.yaml.tftpl,runner-bootstrap.sh}` — [R7] (cloud-init movido a `templatefile()` + script separado para evitar el footgun de escaping heredoc/HCL)
- [x] 3.2 Declarar `oci_identity_dynamic_group` (matchea la instancia) y `oci_identity_policy` de **mínimo privilegio** (`read secret-bundles` limitado *solo* al secret del PAT); añadir variables para el OCID del secret y la URL del repo. — **Files:** `infra/environments/dev/{main.tf,variables.tf,dev.tfvars.example}` — [R7]
- [x] 3.3 `terraform fmt -check` + `validate` **hechos** (OK; cloud-init renderizado = YAML válido, `bash -n` OK). El **`plan`** real (confirmar `add` de dynamic group+policy y **0 recreación** de la instancia) necesita creds OCI → se ejecuta en el pipeline, ver §5.3. — **Files:** ninguno (verificación) — [R7]

## 4. Job de deploy (runner self-hosted, local)

- [x] 4.1 Añadir job `deploy` a `deploy-dev.yml`: `runs-on: [self-hosted, dev]`, `needs: [build-backend, build-frontend]`, `if: github.ref == 'refs/heads/main'`, `concurrency: { group: deploy-dev, cancel-in-progress: false }`, `timeout-minutes`. — **Files:** `.github/workflows/deploy-dev.yml` — [R3]
- [x] 4.2 Paso de render del `.env` desde GitHub Secrets con **validación previa** (falla nombrando la clave ausente **antes** de tocar contenedores), `chmod 600`; incluye `IMAGE_TAG=sha-<sha>` y `GHCR_NS`. — **Files:** `.github/workflows/deploy-dev.yml` — [R4]
- [x] 4.3 Paso `docker login ghcr.io` con `GHCR_PULL_TOKEN` (read-only) y `docker logout` al finalizar (sin credenciales persistentes en la VM). — **Files:** `.github/workflows/deploy-dev.yml` — [R3]
- [x] 4.4 Paso de deploy: `docker compose -f docker-compose.deploy.yml pull` + `up -d --wait --wait-timeout 180`; en fallo, volcar `docker compose logs` y salir ≠0. — **Files:** `.github/workflows/deploy-dev.yml` — [R3, R5]

## 5. Operaciones (tu consola — GitHub/OCI/VM)

- [ ] 5.1 (op.) Crear en GitHub los secrets/vars: `GHCR_PULL_TOKEN` (scope `read:packages`), las claves de runtime del `.env`, y los build-args `NEXT_PUBLIC_*`. — **Files:** ninguno (op. GitHub) — [R1, R4]
- [ ] 5.2 (op.) Subir el PAT de GitHub (scope mínimo para registration-token del repo) como secret del **OCI Vault** out-of-band (`oci vault secret create-base64`), y anotar su OCID en `dev.tfvars`. — **Files:** ninguno (op. OCI); procedimiento en RUNBOOK — [R7]
- [ ] 5.3 (op.) Aplicar Terraform por el pipeline (`workflow_dispatch` `apply` de `infra-dev.yml` desde `main`): crea dynamic group + policy. Confirmar en el run **`0 to destroy`** (instancia intacta). — **Files:** ninguno (op. pipeline) — [R7]
- [ ] 5.4 (op.) Provisionar el runner en la **VM viva a mano, una sola vez** (mismos comandos que el cloud-init de §3.1, leyendo el PAT del Vault vía instance principal); verificar que el runner aparece **online con label `dev`** en Settings → Actions → Runners del repo. — **Files:** ninguno (op. VM); procedimiento en RUNBOOK — [R3, R7]

## 6. Documentación

- [x] 6.1 Actualizar `infra/environments/dev/RUNBOOK.md`: flujo de deploy (push a `main` → build → deploy local), provisión/recuperación del runner, alta y **rotación del PAT** en Vault, arranque en frío (primer deploy sobre VM sin app), y **rollback manual** (redeploy pineando un `IMAGE_TAG` previo). — **Files:** `infra/environments/dev/RUNBOOK.md` §6 — [R6]
- [x] 6.2 Actualizar el `README` (raíz y/o `infra/environments/dev/README.md`): sección de deploy dev (trigger, esquema de tags/retención de imágenes, `.env.deploy.example`, secrets esperados). — **Files:** `README.md`, `infra/environments/dev/README.md` — [R6]

## 7. Verificación end-to-end

- [ ] 7.1 Build: un run (push a `main` o `workflow_dispatch`) publica **ambas imágenes arm64** en GHCR con tags `sha-<commit>` y `dev`. — [R1]
- [ ] 7.2 Deploy real: el job `deploy` corre en el runner self-hosted, `migrate` aplica migraciones, y `up -d --wait` deja backend/worker/frontend **`healthy`** dentro del timeout. — [R3, R5]
- [ ] 7.3 Smoke: `GET /health` (8000) y el frontend (3000) responden desde un CIDR de operador; los volúmenes de `postgres`/`redis` siguen intactos tras el deploy. — [R5]
- [ ] 7.4 Rollback: un redeploy con un `IMAGE_TAG` de un SHA previo restaura esa versión de la app. — [R6]
- [ ] 7.5 Seguridad/reachability: confirmar que el deploy **no requirió abrir puertos** (security list sin cambios) y que el `.env` renderizado tiene permisos restringidos y ningún secreto quedó en el repo/imagen/tfstate. — [R3, R4, R7]
