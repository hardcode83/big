# BLOCKED — app-deploy-dev

Código completo y verificado por el panel (§1–§4 + §6 en PASS: architect/security/qa). Falta la secuencia operativa (tu consola GitHub/OCI/VM) y la verificación end-to-end del deploy real, que no son automatizables desde aquí.

## ops · run · decision — secuencia operativa del CD (§5)

Orden recomendado (las dependencias importan):

1. **§5.1** — crear en GitHub los secrets: `GHCR_PULL_TOKEN` (scope `read:packages`), las claves de runtime del `.env` (`POSTGRES_DB/USER/PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, opcional `BACKEND_INTERNAL_URL`), y el build-arg `NEXT_PUBLIC_APP_ENV`.
2. **§5.2** — subir el **PAT de GitHub** al OCI Vault out-of-band (`oci vault secret create-base64`, ver RUNBOOK §6.2) y anotar su OCID en `dev.tfvars` (`runner_pat_secret_ocid`). ⚠️ Requerido antes del §5.3 (la variable Terraform no tiene default).
3. **§5.3** — lanzar `workflow_dispatch` `apply` de `infra-dev.yml` desde `main`: crea el `oci_identity_dynamic_group` + `oci_identity_policy` del instance principal. Confirmar **`0 to destroy`** (instancia intacta; el cambio de cloud-init está en `ignore_changes` y NO debe aparecer en el plan).
4. **§5.4** — provisionar el runner en la **VM viva a mano, una vez** (RUNBOOK §6.1: instalar oci-cli, `/etc/autohostai-runner.env`, ejecutar `runner-bootstrap.sh`). Verificar que aparece **online con label `dev`** en Settings → Actions → Runners.

**Resume:** `/sdd:run app-deploy-dev` para marcar §5 conforme se complete.

## verify · run · deferred — verificación end-to-end (§7)

Tras la secuencia ops, disparar un deploy (push a `main` o `workflow_dispatch`) y verificar:
- §7.1 build publica ambas imágenes arm64 en GHCR (tags `sha-<commit>` + `dev`).
- §7.2 el job `deploy` corre en el runner, `migrate` aplica migraciones, `up -d --wait` deja backend/worker/frontend `healthy` (confirmar en particular la interacción one-shot `migrate` + `--wait`, que el panel no pudo ejecutar sin daemon).
- §7.3 smoke: `GET /health` (8000) y frontend (3000) desde un CIDR de operador; volúmenes postgres/redis intactos.
- §7.4 rollback: redeploy pineando un SHA previo.
- §7.5 seguridad: sin abrir puertos, `.env` con permisos, nada en repo/imagen/tfstate.

**Resume:** `/sdd:run app-deploy-dev` (marcar §7) o hazlo y luego `/sdd:review app-deploy-dev` + `/sdd:archive app-deploy-dev`.
