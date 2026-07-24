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

### D6 — Autenticación de la VM contra GHCR (pull) con token read-only efímero

**Chosen:** imágenes **privadas**; en el paso de deploy la VM hace `docker login ghcr.io` con un token de solo lectura (`read:packages`) pasado desde el secret `GHCR_PULL_TOKEN`, y `docker logout` al terminar (no persistir credenciales de larga vida en la VM). 

Rejected: hacer los paquetes públicos — el repo es privado, exponer imágenes es peor postura. · PAT de larga vida guardado en la VM — credencial persistente innecesaria.

### D7 — `NEXT_PUBLIC_*` como build-args, no runtime

**Chosen:** las vars `NEXT_PUBLIC_*` (p. ej. `NEXT_PUBLIC_APP_ENV`) se hornean en `RUN npm run build`, así que se pasan como **`build-args`** en `build-frontend` (desde secrets/vars de CI), **no** en el `.env` de runtime. El `.env` de runtime solo lleva vars leídas por el server en ejecución (`BACKEND_INTERNAL_URL`, creds Postgres para backend/worker, `JWT`/`ENCRYPTION_KEY`, etc.). Un `NEXT_PUBLIC_*` en el `.env` de runtime no tendría efecto — se documenta.

Rejected: intentar inyectar `NEXT_PUBLIC_*` en runtime — Next standalone ya las tiene fijadas; sería un bug silencioso.

### D8 — Render del `.env` desde Secrets con validación previa

**Chosen:** el paso de deploy compone el `.env` desde GitHub Secrets, comprueba que **todas** las claves requeridas están presentes **antes** de tocar contenedores (falla temprano con el nombre de la que falte, R4.3), y lo coloca en la VM con `chmod 600` propiedad de `ubuntu`. El repo solo versiona la lista de claves esperadas (`.env.deploy.example`), nunca valores (steering `security.md` §8).

Rejected: subir un `.env` pre-hecho — mete secretos en un artefacto. · Validar después del `up` — dejaría el stack a medio arrancar.

### D9 — Verificación de salud con `up --wait`

**Chosen:** `docker compose -f docker-compose.deploy.yml up -d --wait --wait-timeout 120`; healthchecks definidos en el compose de deploy para backend (`/health`, ya existe) y frontend (GET a `:3000`). Si algún servicio no queda `healthy` en el timeout, el comando sale ≠0 → el job falla y se vuelca `docker compose logs` al output (R5.1/R5.2). Los volúmenes de postgres/redis no se recrean (R5.3).

Rejected: polling casero con `curl` — reinventa lo que `--wait` ya hace de forma nativa.

### D10 — Restricciones del job de deploy (convención del repo)

**Chosen:** `deploy` con `if: github.ref == 'refs/heads/main'`, `concurrency: { group: deploy-dev, cancel-in-progress: false }` (serializa deploys sobre la VM), `timeout-minutes`, y **todas** las Actions fijadas por SHA de commit (igual que `infra-dev.yml`).

### D12 — Conectividad CI→VM: runner self-hosted en la VM, deploy local (resuelve OQ1)

**Chosen:** un **runner self-hosted de GitHub Actions corriendo en la propia VM dev**. El job `deploy` usa `runs-on: [self-hosted, dev]`; los builds (`build-backend`/`build-frontend`) siguen en `ubuntu-latest` (GitHub-hosted, tienen salida a GHCR). El deploy se ejecuta **localmente en la VM** (`docker compose -f docker-compose.deploy.yml …`) → **sin SSH ni puerto entrante nuevo**: el security list endurecido se mantiene intacto (22/8000/3000 solo a CIDRs de operador). La salida a GHCR (pull) y a github.com (runner) es tráfico saliente, no bloqueado.

Consecuencia sobre OQ2 (clave SSH): con el runner **en** la VM, el deploy no usa SSH → la clave de deploy es **moot**. Solo si en el futuro el runner se moviera a otra máquina del entorno se reutilizaría `autohostai_dev_vm` (su pública ya está en la VM) para SSH sobre la red privada. Se registra como fallback, no se implementa ahora.

Rejected: Tailscale — más piezas (tailnet + authkey) de las necesarias cuando el runner puede vivir en la VM. · SSH desde runner GitHub-hosted — bloqueado por el security list. · Abrir 22 a rangos de Actions — contradice el hardening.

**Bootstrap (out-of-band, antes del primer deploy):** instalar el runner como servicio (`svc`) en la VM con auto-arranque, con label `dev`, token de registro del repo; usuario del runner en el grupo `docker` (o acceso al socket) para operar Compose. Documentado en el RUNBOOK.

### D11 — Alcance del deploy: solo app; postgres/redis intactos

**Chosen:** el deploy solo actualiza `backend`/`worker`/`frontend` (imágenes nuevas); `postgres`/`redis` se declaran en el mismo compose pero sus volúmenes persisten entre deploys. `up -d` solo recrea los contenedores cuya imagen cambió.

## Changes by area

| Area | Files | Change |
|---|---|---|
| CI/CD | `.github/workflows/deploy-dev.yml` **(nuevo)** | build→GHCR (2 jobs) + deploy por acceso remoto (1 job), push a `main` path-filtered |
| Orquestación | `docker-compose.deploy.yml` **(nuevo)**, `.env.deploy.example` **(nuevo)** | compose sin `build` (imágenes GHCR por SHA), migrate one-shot con imagen prod, healthchecks; plantilla de claves |
| Frontend | `frontend/devops/Dockerfile` (posible `ARG`/`ENV` para `NEXT_PUBLIC_*`) | aceptar build-args si hoy no los declara |
| Runner | VM dev (bootstrap out-of-band) | instalar runner self-hosted como servicio, label `dev`, acceso a docker; sin cambios en `.tf` ni en el security list (D12) |
| Docs | `infra/environments/dev/RUNBOOK.md`, `README` | flujo de deploy, alta/recuperación del runner, tags/retención, arranque en frío, rollback por SHA, secrets y rotación (R6) |

## Data & interfaces

- **Sin cambios de esquema ni de API.** Las migraciones Alembic existentes se aplican en cada deploy (D5); este change no añade ninguna.
- **Nuevos GitHub Secrets/Vars (CI):** `GHCR_PULL_TOKEN` (read-only), las claves de runtime del `.env` (`POSTGRES_*`, `JWT_*`/`ENCRYPTION_KEY`, `BACKEND_INTERNAL_URL`, …) y build-args `NEXT_PUBLIC_*`. **No** hacen falta `DEPLOY_HOST`/`DEPLOY_SSH_KEY`: el runner corre en la VM y el deploy es local (D12).
- **Nuevos paquetes GHCR:** `autohostai-backend`, `autohostai-frontend` (privados).

## Risks & mitigations

- **Runner en máquina cuasi-productiva (D12):** el runner comparte la VM con la app → contención de recursos (mitigado: 4 OCPU/24 GB, dev, poca frecuencia de deploy) y superficie de seguridad (un runner comprometido = VM comprometida). Mitigación: runner con usuario propio y mínimo privilegio (solo grupo `docker`), repo privado, sin exponer el runner. Aceptable para dev; reevaluar en staging/prod.
- **Disponibilidad del runner:** si el runner (o la VM) está caído, los deploys quedan en cola. Mitigación: instalarlo como servicio con auto-arranque; documentar el alta/recuperación en el RUNBOOK.
- **Bootstrap del runner (antes del primer deploy):** el runner debe estar registrado y activo en la VM **antes** de que un push a `main` dispare el job `self-hosted` → paso out-of-band documentado; sin él el job queda pendiente indefinidamente.
- **Primer deploy sobre VM vacía (arranque en frío):** no hay `.env` ni imágenes previas; el orden build→login→pull→migrate→up debe ser idempotente y quedar documentado (R6.1).
- **Migraciones destructivas / fallo a mitad:** `migrate` corre antes de arrancar la app; si falla, el deploy aborta con la versión anterior aún en marcha (postgres intacto). Backups del state de datos quedan fuera de este change.
- **Deriva del `.env`:** al renderizarse desde Secrets en cada deploy, la fuente de verdad son los Secrets; documentar para evitar ediciones manuales en la VM que un deploy sobrescribe.

## Open questions

**Ambas resueltas en el gate de design (2026-07-24):**

- **OQ1 — Conectividad CI→VM** → **runner self-hosted en la VM, deploy local** (ver D12). El deploy no usa SSH ni abre puertos; el security list del hardening queda intacto. Trae una tarea de **bootstrap del runner** (out-of-band) a este change, pero **no** un cambio de `.tf`.
- **OQ2 — Clave SSH de deploy** → **moot** con el runner en la VM (deploy local). Fallback documentado si el runner se moviera a otra máquina: reutilizar `autohostai_dev_vm` sobre la red privada. No se implementa ahora.

*Confirmado por el usuario (2026-07-24):* el runner corre **en la propia VM** → deploy local, sin SSH ni `known_hosts`. La clave de deploy no se usa.
