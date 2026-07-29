# BLOCKED — app-deploy-dev

Código completo y con el panel en PASS (§1–§4 + §6). Falta la secuencia operativa (tu consola GitHub/OCI + VM) y la verificación end-to-end del deploy real, no automatizables desde aquí.

Diseño vigente: registro del runner vía **GitHub App** (no PAT); la clave de la App = **1 GitHub Secret** que Terraform escribe al Vault; los secrets de runtime los **genera Terraform** → Vault; el deploy los lee del Vault por instance principal. Cero secrets de app a mano.

## ops · run · decision — secuencia operativa del CD (§5)

Orden (las dependencias importan):

1. **§5.1** — crear **una GitHub App** (permisos repo: `Administration: read/write` + `Packages: read`), instalarla en el repo. Guardar en GitHub: **variables** `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `NEXT_PUBLIC_APP_ENV=dev`; **secret** `GH_APP_PRIVATE_KEY` (contenido del `.pem`). Anotar `github_app_id`/`github_app_installation_id` en `dev.tfvars`.
2. **§5.2** — (nada más a mano en OCI) confirmar que `NEXT_PUBLIC_APP_ENV` es *variable* (no secret) y que las variables de la App existen. La clave de la App la escribe Terraform al Vault desde `GH_APP_PRIVATE_KEY`.
3. **§5.3** — `workflow_dispatch` `apply` de `infra-dev.yml` desde `main`: crea dynamic group + policy + `random_*` + **4** `oci_vault_secret` (3 runtime + clave App). Confirmar **`0 to destroy`** (instancia intacta; el cambio de cloud-init está en `ignore_changes` y no debe aparecer).
4. **§5.4** — provisionar el runner en la **VM viva a mano, una vez** (RUNBOOK §6.2: `pip install oci-cli`, escribir `/etc/autohostai-deploy.env` con los OCIDs, copiar `runner-bootstrap.sh`+`gh-app-install-token.py`, ejecutar el bootstrap). Verificar **online con label `dev`** en Settings → Actions → Runners.
5. **§5.5** — **borrar** los 6 GitHub Secrets del primer intento (`POSTGRES_DB/USER/PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `NEXT_PUBLIC_APP_ENV` si quedó como secret) — ya no se usan.

**Resume:** `/sdd:run app-deploy-dev` para marcar §5 conforme se complete.

## verify · run · deferred — verificación end-to-end (§7)

Tras la secuencia ops, disparar un deploy (push a `main` o `workflow_dispatch`) y verificar:
- §7.1 build publica ambas imágenes arm64 en GHCR (tags `sha-<commit>` + `dev`).
- §7.2 el job `deploy` corre en el runner, mintea el token de la App, lee los secrets del Vault, `migrate` aplica migraciones, y `up -d --wait` deja todo `healthy` (confirmar en particular la interacción one-shot `migrate` + `--wait`, no ejecutable sin daemon en el panel).
- §7.3 smoke: `GET /health` (8000) y frontend (3000) desde un CIDR de operador; volúmenes postgres/redis intactos.
- §7.4 rollback: redeploy pineando un SHA previo.
- §7.5 seguridad: sin abrir puertos, `.env` con permisos, la clave de la App **no** en el plan/artifact (el plan ya no se sube), y solo los secrets de runtime + clave App en el `tfstate` (intencional, D14).

**Resume:** `/sdd:run app-deploy-dev` (marcar §7) o hazlo y luego `/sdd:review app-deploy-dev` + `/sdd:archive app-deploy-dev`.
