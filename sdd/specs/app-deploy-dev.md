# Despliegue continuo de la app al entorno dev (CD)

## Purpose

Entrega continua de la aplicación al entorno `dev` de Oracle Cloud: GitHub Actions construye las imágenes `prod` arm64 de backend y frontend, las publica en GHCR, y las despliega en la VM dev mediante un **runner self-hosted que corre en la propia VM** (deploy local por `docker compose`, sin SSH ni puertos entrantes nuevos). Se apoya en la infra de `infra-dev-terraform` (VM, Vault, red) y no toca `staging`/`prod`.

## Requirements

### Build y publicación de imágenes (`.github/workflows/deploy-dev.yml`)

- WHEN se hace push a `main` y el diff toca `backend/**`, `frontend/**`, sus Dockerfiles/lockfiles, `docker-compose.deploy.yml` o el propio workflow (o en `workflow_dispatch`), THE SYSTEM SHALL construir las imágenes `target: prod` de backend y frontend para `linux/arm64` y publicarlas en GHCR bajo el namespace del owner del repo (`ghcr.io/<owner>/autohostai-{backend,frontend}`), autenticando con el `GITHUB_TOKEN` (`packages: write`).
- THE SYSTEM SHALL etiquetar cada imagen con el **SHA de commit** (`sha-<commit>`, inmutable — el que consume el deploy) y con el tag móvil `dev`.
- THE SYSTEM SHALL pasar las `NEXT_PUBLIC_*` como **build-args** (horneadas en el bundle de Next standalone), nunca como config de runtime.
- THE SYSTEM SHALL fijar todas las GitHub Actions por SHA de commit.
- WHERE falla el build de una de las dos imágenes, THE SYSTEM SHALL abortar el deploy (el job `deploy` tiene `needs` de ambos builds); nunca se despliega un commit a medias.

### Compose de deploy (`docker-compose.deploy.yml`)

- THE SYSTEM SHALL declarar `backend`/`worker`/`frontend` con `image:` de GHCR pineada por `${IMAGE_TAG}` (sin sección `build`, sin bind-mounts de código) y mantener `postgres:16`/`redis:7` con volúmenes nombrados persistentes.
- THE SYSTEM SHALL declarar además el servicio `cloudflared` que da el ingress HTTPS público, con imagen pineada por dígest y sin puertos publicados — su comportamiento se especifica en `ingress-https-dev`.
- THE SYSTEM SHALL aplicar migraciones Alembic como paso one-shot (`migrate`, imagen `prod` del backend, `alembic upgrade head`) antes de arrancar backend/worker.
- THE SYSTEM SHALL NOT publicar ningún puerto en una interfaz externa de la VM. `backend` y `frontend` publican **solo en `127.0.0.1`** (8000 y 3000) como puerta de depuración alcanzable por reenvío SSH; `postgres`, `redis` y `cloudflared` no publican puerto alguno. El acceso público llega exclusivamente por el túnel (ver `ingress-https-dev`).
- THE SYSTEM SHALL fijar `HOSTNAME=0.0.0.0` en el frontend (Next standalone usa `$HOSTNAME` como dirección de bind) para que escuche en todas las interfaces.
- THE SYSTEM SHALL declarar healthchecks para backend (`/health`), frontend (`127.0.0.1:3000`) y worker (`celery inspect ping`).

### Deploy en runner self-hosted (`deploy-dev.yml` job `deploy`)

- WHEN las imágenes se han publicado con éxito para un commit de `main`, THE SYSTEM SHALL ejecutar el deploy en un runner self-hosted en la VM (`runs-on: [self-hosted, dev]`), solo desde `main`, con `concurrency` (un deploy a la vez) y `timeout-minutes`.
- THE SYSTEM SHALL autenticar el pull de GHCR con el **`GITHUB_TOKEN`** del job (`packages: read`) — no con la GitHub App — y hacer `docker logout` al terminar.
- THE SYSTEM SHALL renderizar el `.env` de runtime **leyendo los secrets del OCI Vault** por instance principal con `chmod 600`, y fallar el deploy nombrando la clave si alguna no se puede leer, antes de tocar contenedores. Los secrets aprovisionados con la VM se leen por OCID (`secret-bundle get`, con los OCID en `/etc/autohostai-deploy.env`); los añadidos después —hoy el token del túnel— **por nombre** (`get-secret-bundle-by-name`), porque `cloud-init` no puede reescribir ese fichero en la máquina viva.
- WHEN termina `docker compose up -d --wait`, THE SYSTEM SHALL considerar el deploy exitoso solo si todos los servicios quedan `healthy` dentro del timeout; IF alguno no lo alcanza, THEN THE SYSTEM SHALL fallar el job y volcar `docker compose logs`.
- THE SYSTEM SHALL preservar los volúmenes de `postgres`/`redis` entre deploys.

### Runner + secrets como IaC

- THE SYSTEM SHALL definir la instalación/registro del runner en el `cloud-init` de la instancia (`cloud-init.yaml.tftpl` + `runner-bootstrap.sh` + `gh-app-install-token.py`), de modo que una VM reconstruida arranque con el runner operativo; el usuario del runner se añade al grupo `docker`.
- THE SYSTEM SHALL registrar el runner minteando un installation-token de una **GitHub App** (permiso `administration: write`), leyendo la clave privada de la App del Vault por **instance principal** y firmando el JWT localmente; el pull de GHCR no usa la App.
- WHERE la VM viva no puede recibir el `cloud-init` por Terraform (`metadata` ForceNew + `ignore_changes`), THE SYSTEM SHALL ejecutar el mismo bootstrap a mano una sola vez sobre la instancia (documentado en `RUNBOOK.md` §6).
- THE SYSTEM SHALL generar los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY` — clave Fernet válida) con Terraform (`random_*`) y guardarlos, junto con la clave de la App, como `oci_vault_secret`; `POSTGRES_DB`/`POSTGRES_USER` son variables no sensibles.

## Key files

- `.github/workflows/deploy-dev.yml` — build (GHCR) + deploy (runner self-hosted).
- `docker-compose.deploy.yml`, `.env.deploy.example` — orquestación de deploy (imágenes de registry).
- `infra/environments/dev/{cloud-init.yaml.tftpl,runner-bootstrap.sh,gh-app-install-token.py}` — provisión del runner (IaC) y minteo de token de App.
- `infra/environments/dev/{main.tf,variables.tf}` — instance principal (dynamic group + policy), secrets generados → Vault.
- `infra/environments/dev/RUNBOOK.md` §6 — flujo de deploy, GitHub App, provisión del runner, rollback.

## Estado

Desplegado y verificado end-to-end (deploy verde, todos los servicios `healthy`, 2026-07-29). El repo vive en la org `autohostai-labs`.

El **TLS/HTTPS ya está resuelto** por el change `ingress-https-dev`: la app se sirve en `https://autohostai.digitalsec.work` a través de un Cloudflare Tunnel y los puertos 8000/3000 dejaron de estar expuestos. Ver su spec.

Pendiente/futuro: adoptar el provider `github` de Terraform para gestionar la parte GitHub-side como código (ver `steering/infra.md`).
