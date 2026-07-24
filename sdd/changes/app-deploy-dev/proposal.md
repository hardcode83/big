# Proposal: app-deploy-dev

## Why

La infra dev está desplegada y operativa (spec `infra-dev-terraform`): una VM en Oracle Cloud (4 OCPU/24 GB, AD-3) con Docker + Compose funcionando, security list abierto en 8000/3000, y CI que ya construye ambas imágenes `target: prod` para arm64 (`multiarch-build-check.yml`) **sin publicarlas**. Pero **no hay forma de llevar la aplicación a esa VM**: hoy el código vive en `main` y la máquina está vacía de app. Este change cierra ese hueco con el CD del roadmap (§26, entrada `app-deploy-dev`): construir → publicar en registry → desplegar por SSH. Depende de `infra-dev-hardening` (R3 dejó `docker compose` operativo en la VM), ya cerrado.

## What changes

Tras este change, un **push a `main`** que toque `backend/**` o `frontend/**` construirá las imágenes `prod` arm64 de backend y frontend, las publicará en **GHCR** (GitHub Container Registry) etiquetadas por SHA de commit, y desplegará automáticamente en la VM dev mediante un **runner self-hosted que corre en la propia VM** (deploy local, sin SSH ni puertos entrantes nuevos): renderiza el `.env` de runtime desde GitHub Secrets, usa un **docker-compose de deploy** que consume las imágenes del registry (no build local, `postgres:16`/`redis:7` persistentes), aplica migraciones Alembic y hace `docker compose pull && up -d --wait`, verificando que los servicios quedan `healthy`. La provisión del runner se define como **IaC** (cloud-init + instance principal para leer el PAT del Vault), aunque en esta VM viva se ejecute a mano una vez. Existirá un nuevo workflow de deploy y un compose de deploy versionados en el repo, más la documentación operativa (README/RUNBOOK). Staging/prod quedan fuera.

## Requirements

### R1 — Publicar imágenes de la app en GHCR

**As a** operador de dev, **I want** que cada cambio en `main` produzca imágenes `prod` versionadas en un registry, **so that** la VM pueda tirar de artefactos inmutables en lugar de construir en la máquina.

Acceptance criteria:

1. WHEN se hace push a `main` y el diff toca `backend/**`, `frontend/**` o sus lockfiles/Dockerfiles, THE SYSTEM SHALL construir las imágenes `target: prod` de backend y frontend para `linux/arm64` y publicarlas en GHCR bajo el namespace del repo.
2. THE SYSTEM SHALL etiquetar cada imagen con el **SHA de commit** (inmutable) y con un tag móvil `dev`; el deploy referencia el SHA, nunca `latest`.
3. WHERE el build de una de las dos imágenes falle, THE SYSTEM SHALL abortar sin publicar ninguna imagen ni continuar al deploy.
4. THE SYSTEM SHALL publicar autenticándose con el `GITHUB_TOKEN` del workflow (sin credenciales de registry adicionales en el repo).

### R2 — Compose remoto de dev (imágenes de registry, no build)

**As a** operador de dev, **I want** un docker-compose específico de la VM que consuma las imágenes de GHCR, **so that** la máquina ejecute artefactos publicados y conserve sus datos entre despliegues.

Acceptance criteria:

1. THE SYSTEM SHALL versionar en el repo un compose de dev-remoto que declare `image:` (GHCR, por SHA) para `backend`, `worker` y `frontend`, **sin sección `build`**, y mantenga `postgres:16` y `redis:7` con sus volúmenes persistentes.
2. THE SYSTEM SHALL ejecutar las migraciones Alembic como paso one-shot (servicio `migrate`/`command`) con la imagen `prod` del backend antes de arrancar backend y worker.
3. THE SYSTEM SHALL publicar únicamente los puertos ya abiertos en el security list de la VM (8000 backend, 3000 frontend); ningún puerto nuevo.
4. THE SYSTEM SHALL declarar `restart: unless-stopped` y healthchecks en los servicios de app, sin montar bind-mounts de código fuente (a diferencia del compose local de desarrollo).

### R3 — Despliegue automático en la VM vía runner self-hosted

**As a** operador de dev, **I want** que el deploy ocurra solo tras publicarse las imágenes, **so that** `main` y la VM converjan sin intervención manual y sin abrir puertos entrantes.

Acceptance criteria:

1. WHEN las imágenes de R1 se han publicado con éxito para un commit de `main`, THE SYSTEM SHALL ejecutar el deploy en un **runner self-hosted en la propia VM** (`runs-on: [self-hosted, dev]`), autenticar el Docker de la VM contra GHCR (token read-only) y ejecutar **localmente** `docker compose pull` + `up -d` con el compose de deploy pineado a ese SHA — sin SSH ni puertos entrantes nuevos.
2. THE SYSTEM SHALL serializar los despliegues con `concurrency` (un solo deploy a la vez sobre la VM) y aplicar `timeout-minutes`.
3. IF el `docker compose up` (o un paso previo del deploy) falla, THEN THE SYSTEM SHALL terminar el workflow en estado de fallo y dejar registrado el error, sin marcar el deploy como exitoso.
4. THE SYSTEM SHALL restringir el job de deploy a ejecutarse **solo desde `main`** (`github.ref == 'refs/heads/main'`), con todas las GitHub Actions fijadas por SHA de commit (convención del repo).

### R7 — Provisión del runner como IaC

**As a** operador de dev, **I want** que la instalación y registro del runner esté definida en Terraform, **so that** una VM reconstruida arranque con el runner operativo y no quede nada manual que pueda ser IaC.

Acceptance criteria:

1. THE SYSTEM SHALL definir la instalación/registro del runner (binario, `config.sh --labels dev --unattended`, servicio con auto-arranque, usuario en grupo `docker`) en el **cloud-init** de la instancia (`infra/environments/dev/main.tf`), como fuente de verdad para una VM nueva.
2. THE SYSTEM SHALL obtener el registration-token en arranque leyendo un PAT desde un secret del **OCI Vault** vía **instance principal** — nunca renderizando el credencial en `user_data`/`tfstate`.
3. THE SYSTEM SHALL declarar como Terraform un `oci_identity_dynamic_group` (la instancia) y un `oci_identity_policy` de **mínimo privilegio** que autorice a leer *solo* ese secret del Vault.
4. WHERE la VM viva no puede recibir el cloud-init por Terraform (metadata ForceNew + `ignore_changes`), THE SYSTEM SHALL documentar la ejecución **a mano, una sola vez**, del mismo bloque sobre la instancia actual (RUNBOOK).

### R4 — Configuración de runtime en la VM desde Secrets

**As a** operador de dev, **I want** que el `.env` de runtime se genere desde GitHub Secrets en cada deploy, **so that** no haya secretos en el repo ni en la imagen y la config sea reproducible.

Acceptance criteria:

1. WHEN se ejecuta un deploy, THE SYSTEM SHALL renderizar el `.env` que consume el compose remoto (creds Postgres, `JWT`/secretos de app, `NEXT_PUBLIC_APP_ENV`, URLs internas) a partir de GitHub Secrets, colocándolo en la VM con permisos restringidos.
2. THE SYSTEM SHALL NOT versionar ningún valor de secreto en el repo ni hornearlo en las imágenes; el repo solo contiene la plantilla/lista de claves esperadas.
3. IF falta un secret requerido para el runtime, THEN THE SYSTEM SHALL fallar el deploy con un mensaje que identifique la clave ausente, antes de tocar los contenedores en marcha.

### R5 — Verificación post-deploy

**As a** operador de dev, **I want** que el workflow confirme que la app quedó sana, **so that** un deploy verde signifique que la app responde de verdad.

Acceptance criteria:

1. WHEN termina `docker compose up -d`, THE SYSTEM SHALL esperar y verificar que backend (`/health`) y frontend responden como `healthy` dentro de un timeout acotado.
2. IF algún servicio de app no alcanza estado `healthy` en el timeout, THEN THE SYSTEM SHALL marcar el deploy como fallido y exponer los logs relevantes (`docker compose logs`) en el output del workflow.
3. THE SYSTEM SHALL dejar los datos de `postgres`/`redis` intactos a través del deploy (los volúmenes persistentes no se recrean).

### R6 — Documentación operativa del deploy

**As a** operador de dev, **I want** el flujo de deploy y su recuperación documentados, **so that** cualquiera del equipo pueda operar, arrancar en frío o revertir.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en README/RUNBOOK: el trigger (push a `main`), el esquema de tags de imagen y su retención, el arranque en frío (primer deploy sobre VM vacía) y el **rollback manual** (redeploy pineando un SHA previo).
2. THE SYSTEM SHALL documentar el secret de CI para SSH y el token read-only de GHCR usado por la VM, y su procedimiento de rotación.

## Out of scope

- **Staging/prod**: este change es solo `dev`; su CD se decide por separado (steering `infra.md`: staging/prod sin proveedor elegido).
- **Zero-downtime / blue-green / rolling**: el modelo es `pull && up -d` con breve corte; suficiente para dev con 2 viviendas.
- **Rollback automático**: se documenta el rollback **manual** (redeploy por SHA); la automatización queda fuera.
- **Cambios de infra/VM/red**: puertos, security list, VM, Vault y state son de `infra-dev-terraform` y no se tocan — **excepto** la provisión del runner self-hosted, que **sí** entra como IaC en el cloud-init + una IAM de instance principal (decisión de design D12/D13: el usuario pidió que lo aprovisionable sea Terraform, no manual). No se abren puertos nuevos ni se cambia el security list.
- **Registry distinto de GHCR**, gestión de imágenes en OCIR, y observabilidad/monitorización (logs centralizados, métricas) — futuros.
- **Publicar imágenes `amd64`**: la VM es arm64; el build multi-arch de verificación (`multiarch-build-check.yml`) sigue cubriendo amd64+arm64 sin publicar.

## Affected specs

- `sdd/specs/app-deploy-dev.md` *(no existe aún — se creará al archivar)* — nueva capability: CD de la app al entorno dev (build → GHCR → SSH deploy).
- `sdd/specs/infra-dev-terraform.md` — **modificado**: la provisión del runner self-hosted como IaC (cloud-init) + instance principal (dynamic group + policy de mínimo privilegio para leer el PAT del Vault) añade requisitos de infra a este spec (D12/D13). También cierra el pendiente "despliegue de la aplicación … change futuro `app-deploy-dev`".
