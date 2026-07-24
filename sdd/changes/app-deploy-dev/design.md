# Design: app-deploy-dev

## Context

La infra dev está viva y operativa (spec `infra-dev-terraform`): VM Ampere A1 (4 OCPU/24 GB, AD-3) con Docker + Compose, IP pública reservada, y un security list que **restringe 22/8000/3000 a `var.allowed_ssh_cidrs`** — sin ningún `0.0.0.0/0` de entrada (endurecido en `infra-dev-hardening`). El repo ya tiene `prod` targets en `backend/devops/Dockerfile` (uvicorn, `alembic` es dependencia **de runtime**) y `frontend/devops/Dockerfile` (Next.js `output: standalone`, `node server.js`), y un workflow `multiarch-build-check.yml` que los construye para amd64+arm64 **sin publicar**. El `docker-compose.yml` de raíz orquesta postgres:16, redis:7, migrate (one-shot), backend, worker, frontend con `target: dev` y bind-mounts. Backend expone `/health`. GitHub Secrets ya alberga las credenciales OCI y `SSH_PUBLIC_KEY`. **No existe** ningún workflow de deploy ni un compose sin `build`.

## Decisions

### D1 — Un solo workflow con jobs encadenados

**Chosen:** `.github/workflows/deploy-dev.yml`, `on: push: branches: [main]` con `paths` (`backend/**`, `frontend/**`, sus Dockerfiles/lockfiles, el compose de deploy y el propio workflow). Jobs: `build-backend` y `build-frontend` en paralelo (push a GHCR) → `deploy` (`needs: [build-backend, build-frontend]`). Un único grafo hace trivial pinear el SHA construido al deploy y aborta el deploy si cualquier build falla (R1.3).

Rejected: dos workflows encadenados por `workflow_run` — más frágil, propaga mal el SHA. · Reusar `infra-dev.yml` — concierne a IaC, otra responsabilidad y otro gate.

### D2 — Registry GHCR, tags por SHA + `dev`, solo arm64

**Chosen:** GHCR bajo el namespace del repo: `ghcr.io/mreyesojeda/autohostai-backend` y `-frontend`. `docker/build-push-action` (pineado por SHA) con `target: prod`, `platforms: linux/arm64` (la VM es ARM), `push: true`, auth con `GITHUB_TOKEN` + `permissions: packages: write`. Tags: el **SHA de commit** (inmutable, lo consume el deploy) y `dev` (móvil, conveniencia). El check amd64+arm64 sigue en `multiarch-build-check.yml` (no se toca).

Rejected: OCIR — IAM/token OCI extra sin beneficio en dev. · Docker Hub — rate limits y credenciales propias. · Publicar amd64 — la VM no lo usa.

### D3 — Compose de deploy dedicado en la raíz

**Chosen:** nuevo `docker-compose.deploy.yml` en la raíz (junto al de dev). Declara `image: ghcr.io/${GHCR_NS}/autohostai-<svc>:${IMAGE_TAG}` para `backend`, `worker`, `frontend` (**sin `build`**, sin bind-mounts de código), mantiene `postgres:16`/`redis:7` con volúmenes nombrados persistentes, `restart: unless-stopped`, y healthchecks. Es orquestación de app, no IaC → raíz, no `infra/environments/dev/`.

Rejected: `docker-compose.override.yml` — la semántica de merge de override es frágil y arrastra los `build` del base. · Editar el compose de dev — mezcla dev local y remoto. · Ubicarlo en `infra/environments/dev/` — contamina el root module de Terraform (steering `infra.md`).

### D4 — Pineado de SHA vía `.env` renderizado

**Chosen:** el deploy escribe en la VM un `.env` que incluye `IMAGE_TAG=<sha-del-commit>` y `GHCR_NS=mreyesojeda`; el compose interpola `${IMAGE_TAG}`/`${GHCR_NS}`. `docker compose pull && up -d` arranca exactamente las imágenes de ese commit. El rollback manual es re-deploy con un `IMAGE_TAG` previo (R6.1).

Rejected: tag `dev` móvil como referencia del deploy — no reproducible, imposible de revertir por SHA.

### D5 — Migraciones con la imagen `prod` del backend, one-shot

**Chosen:** servicio `migrate` en el compose de deploy con la **misma imagen `prod`** del backend, `restart: "no"`, `command: alembic upgrade head` (binario de `.venv/bin`, **no** `uv run` — el stage final `prod` no lleva `uv`), `depends_on: postgres (healthy)`; backend/worker con `depends_on: migrate (service_completed_successfully)`. Viable porque `alembic>=1.13` es dependencia de runtime (verificado en `backend/pyproject.toml`).

Rejected: imagen de migraciones aparte — innecesario, la prod ya trae alembic. · `uv run alembic` — `uv` no está en el stage prod.

### D6 — Autenticación de la VM contra GHCR (pull) vía token minteado por GitHub App

**Chosen (revisado — "endurecer hacia IaC"):** imágenes **privadas**; en el paso de deploy la VM **mintea un installation-token de la GitHub App** (misma App que registra el runner, D13; permiso `packages: read`) leyendo su clave privada del Vault por instance principal, hace `docker login ghcr.io -u x-access-token --password-stdin` con ese token efímero y `docker logout` al terminar. **No hay `GHCR_PULL_TOKEN` puesto a mano** — cero PAT de GitHub como secret.

Rejected: PAT `read:packages` como GitHub Secret puesto a mano (`GHCR_PULL_TOKEN`) — viola el principio "nada a mano"; era el diseño previo. · Paquetes públicos — el repo es privado.

### D7 — `NEXT_PUBLIC_*` como build-args, no runtime

**Chosen:** las vars `NEXT_PUBLIC_*` (p. ej. `NEXT_PUBLIC_APP_ENV`) se hornean en `RUN npm run build`, así que se pasan como **`build-args`** en `build-frontend` (desde secrets/vars de CI), **no** en el `.env` de runtime. El `.env` de runtime solo lleva vars leídas por el server en ejecución (`BACKEND_INTERNAL_URL`, creds Postgres para backend/worker, `JWT`/`ENCRYPTION_KEY`, etc.). Un `NEXT_PUBLIC_*` en el `.env` de runtime no tendría efecto — se documenta.

Rejected: intentar inyectar `NEXT_PUBLIC_*` en runtime — Next standalone ya las tiene fijadas; sería un bug silencioso.

### D8 — Render del `.env` desde el OCI Vault (secrets generados por Terraform) con validación previa

**Chosen (revisado — "endurecer hacia IaC"):** el paso de deploy compone el `.env` leyendo los secrets de runtime del **OCI Vault** por instance principal (no de GitHub Secrets). Los valores los **genera Terraform** (D14) y los guarda en el Vault, así que **no se ponen a mano**. El deploy comprueba que cada secret requerido se leyó bien **antes** de tocar contenedores (falla temprano nombrando el que falte, R4.3), y coloca el `.env` con `chmod 600`. El repo solo versiona la lista de claves esperadas (`.env.deploy.example`), nunca valores.

Rejected: `.env` desde GitHub Secrets puestos a mano (diseño previo) — viola "nada a mano". · Subir un `.env` pre-hecho — mete secretos en un artefacto. · Validar después del `up` — dejaría el stack a medio arrancar.

### D9 — Verificación de salud con `up --wait`

**Chosen:** `docker compose -f docker-compose.deploy.yml up -d --wait --wait-timeout 180` (180s, no 120: el primer `pull` de imágenes arm64 sobre la VM puede ser lento); healthchecks definidos en el compose de deploy para backend (`/health`, ya existe), frontend (GET a `:3000`) y **worker** (`celery inspect ping` — sin él `--wait` no gatearía sobre el worker). Si algún servicio no queda `healthy` en el timeout, el comando sale ≠0 → el job falla y se vuelca `docker compose logs` al output (R5.1/R5.2). Los volúmenes de postgres/redis no se recrean (R5.3).

Rejected: polling casero con `curl` — reinventa lo que `--wait` ya hace de forma nativa.

### D10 — Restricciones del job de deploy (convención del repo)

**Chosen:** `deploy` con `if: github.ref == 'refs/heads/main'`, `concurrency: { group: deploy-dev, cancel-in-progress: false }` (serializa deploys sobre la VM), `timeout-minutes`, y **todas** las Actions fijadas por SHA de commit (igual que `infra-dev.yml`).

### D12 — Conectividad CI→VM: runner self-hosted en la VM, deploy local (resuelve OQ1)

**Chosen:** un **runner self-hosted de GitHub Actions corriendo en la propia VM dev**. El job `deploy` usa `runs-on: [self-hosted, dev]`; los builds (`build-backend`/`build-frontend`) siguen en `ubuntu-latest` (GitHub-hosted, tienen salida a GHCR). El deploy se ejecuta **localmente en la VM** (`docker compose -f docker-compose.deploy.yml …`) → **sin SSH ni puerto entrante nuevo**: el security list endurecido se mantiene intacto (22/8000/3000 solo a CIDRs de operador). La salida a GHCR (pull) y a github.com (runner) es tráfico saliente, no bloqueado.

Consecuencia sobre OQ2 (clave SSH): con el runner **en** la VM, el deploy no usa SSH → la clave de deploy es **moot** (no se usa).

Rejected: Tailscale — más piezas de las necesarias cuando el runner vive en la VM. · SSH desde runner GitHub-hosted — bloqueado por el security list. · Abrir 22 a rangos de Actions — contradice el hardening.

### D13 — Provisión del runner como IaC (cloud-init) + instance principal para el token

**Chosen (revisado — registro vía GitHub App, no PAT):** la instalación/registro del runner es **IaC**. Concretamente:

- El **cloud-init** (`cloud-init.yaml.tftpl` + `runner-bootstrap.sh`) instala el runner: descarga el binario, `config.sh --url <repo> --labels dev --unattended`, servicio (`svc.sh install && svc.sh start`), usuario en grupo `docker`. Fuente de verdad: una VM reconstruida arranca con el runner operativo.
- El **registration-token** se obtiene minteando un **installation-token de una GitHub App** (permisos `administration: write` para runners + `packages: read` para GHCR — **una sola App para todos los entornos**). La **clave privada de la App** es el **único secret-zero**, y se maneja **por código**: vive como UN secret de GitHub Actions (`GH_APP_PRIVATE_KEY`) y **Terraform la escribe al Vault de cada entorno** (`oci_vault_secret.github_app_key`, valor desde `var.github_app_private_key`). El bootstrap la lee del Vault por **instance principal**, firma el JWT de App (helper `gh-app-install-token.py`, RS256 con `cryptography`), pide el installation-token y de ahí el registration-token. Los identificadores (`app_id`, `installation_id`) son variables Terraform no sensibles. La `oci_identity_policy` de mínimo privilegio autoriza leer la clave de la App **y** los secrets de runtime (D14).
- **Reutilización por entorno:** las variables `env`/`github_app_*` parametrizan el CD; un entorno nuevo (`test`) reusa el código y la misma App → **`terraform apply` sin pasos manuales en OCI** (la clave se inyecta por el pipeline). La extracción a `infra/modules/` (parametrizar también VCN/instancia/budget) es un change aparte.

**Aplicación a la VM viva (a mano, solo esta vez):** el `metadata` es **ForceNew** con `ignore_changes` — cambiar el cloud-init por Terraform recrearía la VM (ruleta de capacidad A1). El bloque de runner se ejecuta **una vez a mano** sobre la VM actual (mismos comandos, RUNBOOK). Un entorno **nuevo** se aprovisiona 100% del cloud-init, sin este paso. El `plan` no muestra el `metadata` (ignore_changes); la IAM y los secrets del Vault sí los aplica el pipeline.

Rejected: **PAT de GitHub** (diseño previo) — expira/rota a mano, secret-zero más amplio; la App mintea tokens efímeros por código y no caduca. · **Clave de la App subida out-of-band por entorno** (variante intermedia) — un paso manual por entorno; se prefirió inyectarla por el pipeline (cero manual, a cambio de que la clave viva en el tfstate, D14). · Provisioner `remote-exec` — imperativo y choca con el security list.

### D14 — Secrets generados/gestionados por Terraform → Vault (regla tfstate relajada)

**Chosen:** los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) los **genera Terraform** (`random_password` / `random_bytes`; `ENCRYPTION_KEY` como clave Fernet válida vía base64url del `random_bytes` de 32 B) y, junto con la **clave privada de la GitHub App** (inyectada por el pipeline), los guarda como `oci_vault_secret` en el Vault del entorno. El deploy y el runner los leen del Vault por instance principal (D8/D13). `POSTGRES_DB`/`POSTGRES_USER` son variables no sensibles. **Cero secrets de app puestos a mano ni como GitHub Secrets de runtime.**

**Trade-off aceptado por el usuario (2026-07-24):** los valores (incl. la clave de la App) viven en el `tfstate`, relajando la regla "ningún secreto en el tfstate" del hardening — a cambio de **cero pasos manuales por entorno** (objetivo: reutilizar el código para `test`). Mitigación: el bucket de state es **privado + versionado + IAM mínima** (`svc-terraform-dev`); documentado en `steering/security.md`. La clave de la App entra al tfstate solo como `var` sensible desde UN GitHub Secret. **Ámbito dev/test**: para staging/prod se revisará (gestor de secretos dedicado).

Rejected: generar/poner los secrets con `gh secret set` a mano (primer intento) — es justo el "a mano" que el principio evita. · GitHub Secrets de runtime leídos por el deploy — el deploy corre en la VM y lee del Vault directamente, sin gestionar N secrets por entorno.

### D11 — Alcance del deploy: solo app; postgres/redis intactos

**Chosen:** el deploy solo actualiza `backend`/`worker`/`frontend` (imágenes nuevas); `postgres`/`redis` se declaran en el mismo compose pero sus volúmenes persisten entre deploys. `up -d` solo recrea los contenedores cuya imagen cambió.

## Changes by area

| Area | Files | Change |
|---|---|---|
| CI/CD | `.github/workflows/deploy-dev.yml` **(nuevo)** | build→GHCR (2 jobs) + deploy por acceso remoto (1 job), push a `main` path-filtered |
| Orquestación | `docker-compose.deploy.yml` **(nuevo)**, `.env.deploy.example` **(nuevo)** | compose sin `build` (imágenes GHCR por SHA), migrate one-shot con imagen prod, healthchecks; plantilla de claves |
| Frontend | `frontend/devops/Dockerfile` (posible `ARG`/`ENV` para `NEXT_PUBLIC_*`) | aceptar build-args si hoy no los declara |
| Runner + secrets (IaC) | `infra/environments/dev/main.tf` (cloud-init + `oci_identity_dynamic_group` + `oci_identity_policy` + `random_*` + `oci_vault_secret` de runtime), `variables.tf`, `dev.tfvars.example` | provisión del runner en cloud-init; secrets de runtime generados por TF → Vault (D14); instance principal de mínimo privilegio para leer la clave de la App y los secrets de runtime. Security list sin cambios |
| Build args | `frontend/devops/Dockerfile`, `deploy-dev.yml` | `NEXT_PUBLIC_APP_ENV` como `ARG`/build-arg (build-time) — GitHub **variable** (no secret, no sensible) |
| Runner (VM viva) | — (a mano, 1 vez) | ejecutar el bloque del cloud-init sobre la instancia actual (metadata ForceNew + ignore_changes), RUNBOOK |
| Docs | `infra/environments/dev/RUNBOOK.md`, `README` | flujo de deploy, provisión/recuperación del runner, alta de la clave de la GitHub App en Vault y rotación, arranque en frío, rollback (R6) |
| Steering | `sdd/steering/security.md` | relajar la regla "ningún secreto en el tfstate" para dev (D14) |

## Data & interfaces

- **Sin cambios de esquema ni de API.** Las migraciones Alembic existentes se aplican en cada deploy (D5); este change no añade ninguna.
- **Único secret-zero (GitHub Secret `GH_APP_PRIVATE_KEY`):** la **clave privada de la GitHub App**. El pipeline la inyecta (`TF_VAR_github_app_private_key`) y Terraform la escribe al Vault de cada entorno; el bootstrap y el deploy la leen del Vault por instance principal para mintear installation-tokens (registro del runner + login GHCR). No hay PATs ni `GHCR_PULL_TOKEN`. `GH_APP_ID`/`GH_APP_INSTALLATION_ID` son **variables** (no sensibles).
- **Secrets de runtime (generados por Terraform → Vault, D14):** `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY` como `oci_vault_secret`. `POSTGRES_DB`/`POSTGRES_USER` son variables no sensibles (default). El deploy los lee del Vault por instance principal — **ningún GitHub Secret de app**.
- **GitHub variables (no secretos):** `NEXT_PUBLIC_APP_ENV` (build-arg, público). Identificadores de la App (`app_id`, `installation_id`) → variables Terraform en tfvars.
- **Nuevos recursos OCI (Terraform, aplicados por el pipeline):** `oci_identity_dynamic_group` + `oci_identity_policy` (leer la clave de la App y los secrets de runtime), `random_password`/`random_bytes` + `oci_vault_secret` (×4: 3 runtime + clave de la App). La clave de la App la escribe Terraform al Vault desde `var.github_app_private_key` (pipeline).
- **Nuevos paquetes GHCR:** `autohostai-backend`, `autohostai-frontend` (privados).

## Risks & mitigations

- **Runner en máquina cuasi-productiva (D12):** el runner comparte la VM con la app → contención de recursos (mitigado: 4 OCPU/24 GB, dev, poca frecuencia de deploy) y superficie de seguridad (un runner comprometido = VM comprometida). Mitigación: runner con usuario propio y mínimo privilegio (solo grupo `docker`), repo privado, sin exponer el runner. Aceptable para dev; reevaluar en staging/prod.
- **Disponibilidad del runner:** si el runner (o la VM) está caído, los deploys quedan en cola. Mitigación: instalarlo como servicio con auto-arranque; documentar el alta/recuperación en el RUNBOOK.
- **Bootstrap del runner (antes del primer deploy):** el runner debe estar registrado y activo en la VM **antes** de que un push a `main` dispare el job `self-hosted`; en la VM viva se aplica a mano una vez (D13). Sin él el job queda pendiente indefinidamente.
- **Cloud-init IaC vs VM viva (drift invisible):** al ir el runner en el `metadata` (ForceNew + `ignore_changes`), el `plan` **no** mostrará el cambio ni detectará si la VM viva difiere del código. Mitigación: aplicar a mano el mismo bloque y documentar que la fuente de verdad es el cloud-init (un rebuild reproduce el runner). Igual que el patrón de claves SSH del hardening.
- **Clave de la GitHub App en el `tfstate` y en el Vault (credencial de GitHub en OCI):** la clave mintea installation-tokens con `administration: write` + `packages: read`. Mitigación: es un solo secret-zero (`GH_APP_PRIVATE_KEY`), la policy del instance principal solo permite leer *ese* secret, `tfstate` en bucket privado+versionado+IAM mínima (D14, relajación aceptada), rotación documentada (RUNBOOK §6.1). El plan **no** se sube como artifact (contendría la clave) — el `apply` re-planifica en el mismo job.
- **Primer deploy sobre VM vacía (arranque en frío):** no hay `.env` ni imágenes previas; el orden build→login→pull→migrate→up debe ser idempotente y quedar documentado (R6.1).
- **Migraciones destructivas / fallo a mitad:** `migrate` corre antes de arrancar la app; si falla, el deploy aborta con la versión anterior aún en marcha (postgres intacto). Backups del state de datos quedan fuera de este change.
- **Deriva del `.env`:** al renderizarse desde el Vault en cada deploy, la fuente de verdad es el Vault (secrets generados por TF); documentar para evitar ediciones manuales en la VM que un deploy sobrescribe.

## Open questions

**Todas resueltas en el gate de design (2026-07-24):**

- **OQ1 — Conectividad CI→VM** → **runner self-hosted en la VM, deploy local** (D12). Sin SSH ni puertos; el security list del hardening queda intacto.
- **OQ2 — Clave SSH de deploy** → **moot** con el runner en la VM (deploy local). No se implementa.
- **OQ3 — Provisión del runner** → **IaC en cloud-init** + **instance principal** para leer del Vault la clave de la GitHub App (D13). El usuario pidió expresamente que lo aprovisionable sea IaC; el "a mano" se limita a ejecutar el bloque una vez sobre la VM viva (metadata ForceNew). La IAM (dynamic group + policy) y los secrets del Vault los aplica el pipeline.

*Confirmado por el usuario (2026-07-24):* runner en la propia VM (deploy local, sin SSH); provisión como IaC (cloud-init), credencial vía OCI Vault + instance principal, nada en el `tfstate`.
