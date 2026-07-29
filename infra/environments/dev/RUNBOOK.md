# Runbook operativo — infra dev (Oracle Cloud)

Procedimientos de operación/recuperación del entorno `dev`. Complementa al `README.md` (uso) y al `docs/adr/0001-dev-hosting-provider.md` (decisión). Los cambios de infra se aplican **por el pipeline** (`workflow_dispatch` de `.github/workflows/infra-dev.yml`), no con `terraform apply` local.

Referencias rápidas: usuario SSH `ubuntu` · clave local `~/.ssh/autohostai_dev_vm` · bucket de state `autohostai-tfstate-dev` (objeto `dev.tfstate`) · la instancia vive en **AD-3** · Terraform corre como `svc-terraform-dev` (policy mínima en [`iam-policy.md`](./iam-policy.md)).

## 0. Aplicar cambios de infra (modelo de aprobación)

Los cambios se aplican **solo por el pipeline** (`.github/workflows/infra-dev.yml`), nunca con `terraform apply` local salvo bootstrap excepcional. El modelo de aprobación (repo privado + plan Free, sin Environments con required reviewers):

1. El cambio de Terraform va en un **PR revisado** → merge a `main`.
2. En Actions, lanzar **Run workflow** de `infra-dev` con `action=plan` desde `main` y revisar el plan.
3. Repetir con `action=apply` desde `main`: solo aplica lo que está en `main` (ya revisado), solo lo lanza un colaborador con push, y `concurrency` impide dos apply simultáneos.

Es decir, la "aprobación" es el **review del PR + el dispatch manual desde `main`** (no un Environment).

⚠️ **Limitación de enforcement (repo privado + plan Free):** ni los Environments con required reviewers ni la **branch protection / rulesets** están disponibles (la API devuelve `403 "Upgrade to GitHub Pro or make this repository public"`). Por tanto **el "PR revisado antes de merge" es una convención, no está forzado técnicamente**: alguien con push podría subir directo a `main` y aplicar sin review. Lo que **sí** está forzado es que el `apply` solo corre contra el código de `main` (`if: github.ref == 'refs/heads/main'`), no contra una rama arbitraria. Es un **modelo de confianza de 2 personas**. Para forzarlo de verdad: pasar a GitHub Pro/Team (desbloquea branch protection + Environments) o hacer el repo público.

## 1. Acceso SSH

```bash
ssh -i ~/.ssh/autohostai_dev_vm ubuntu@$(terraform output -raw instance_public_ip)
```

El acceso está acotado por `allowed_ssh_cidrs` (security list): tu IP pública debe estar en la lista. Si cambió, añade tu CIDR a `allowed_ssh_cidrs` (dev.tfvars/secret) y aplica por el pipeline.

### Añadir / rotar / revocar una clave

⚠️ El `metadata` de la instancia (incluidas las `ssh_authorized_keys`) es **ForceNew** en el provider `oci`: cambiarlo por Terraform **recrearía la VM** (por eso lleva `lifecycle { ignore_changes = [metadata] }`). Sobre la **instancia viva** se gestiona **out-of-band**:

```bash
# Añadir una clave (desde tu máquina, o editando en la VM):
ssh -i ~/.ssh/autohostai_dev_vm ubuntu@<ip> \
  "echo 'ssh-ed25519 AAAA... operador' >> ~/.ssh/authorized_keys"
# Revocar: editar ~/.ssh/authorized_keys en la VM y borrar la línea.
```

La lista `ssh_authorized_keys` en Terraform define el arranque de una **VM nueva** (rebuild desde 0), no la viva.

## 2. Backup / recuperación de la clave SSH (OCI Vault)

La clave privada de deploy se guarda como secret en el Vault (`vault_id`/`secrets_key_id` en outputs), como copia recuperable por el equipo (además de GitHub Secrets para el CI). El valor se sube **out-of-band** (no por Terraform, para no dejarlo en el `tfstate`).

```bash
# Subir (una vez):
oci vault secret create-base64 \
  --compartment-id <compartment_ocid> \
  --vault-id "$(terraform output -raw vault_id)" \
  --key-id "$(terraform output -raw secrets_key_id)" \
  --secret-name autohostai-dev-ssh-key \
  --secret-content-content "$(base64 -i ~/.ssh/autohostai_dev_vm)"

# Recuperar (si se pierde localmente):
oci secrets secret-bundle get --raw-output \
  --secret-id ocid1.vaultsecret.oc1.eu-frankfurt-1.amaaaaaa2r32b6yaq2vmuzumiynmonnbvbta7qgz23x6yoxssyhxt5q3mgrq \
  --query 'data."secret-bundle-content".content' | base64 -d > ~/.ssh/autohostai_dev_vm
chmod 600 ~/.ssh/autohostai_dev_vm
```

## 3. Recuperación del state remoto

El bucket `autohostai-tfstate-dev` tiene **versioning** activado. Para restaurar una versión previa del state:

```bash
# Listar versiones del objeto dev.tfstate:
oci os object-version list --bucket-name autohostai-tfstate-dev \
  --namespace <namespace> --prefix dev.tfstate
# Descargar una versión concreta:
oci os object get --bucket-name autohostai-tfstate-dev --namespace <namespace> \
  --name dev.tfstate --version-id <version_ocid> --file dev.tfstate.restore
# Tras validarla, volver a subirla como versión actual (o usar terraform state push con cuidado).
```

## 4. Destroy controlado

⚠️ `terraform destroy` **elimina la VM** (y con ella cualquier dato no respaldado); recrearla depende de la capacidad A1 (ruleta). El Vault, además, tiene un periodo de **borrado programado** (no se elimina al instante). Úsalo solo a conciencia:

```bash
# Preferible por el pipeline; en local, revisar el plan de destrucción primero:
terraform plan -destroy -var-file=dev.tfvars
```

## 5. Diagnóstico de cloud-init

```bash
ssh -i ~/.ssh/autohostai_dev_vm ubuntu@<ip>
sudo cloud-init status --long              # estado (done/error)
sudo cat /var/log/cloud-init-output.log    # salida de la instalación de paquetes
sudo cat /var/log/cloud-init.log           # log detallado
# Reintentar (solo en bootstrap, no sobre una VM en uso):
sudo cloud-init clean --logs && sudo cloud-init init
```

Recordatorio del bug histórico: `docker-compose-plugin` no está en los repos por defecto de Ubuntu 22.04; el cloud-init añade el **repo APT oficial de Docker**. Verificar tras arrancar: `docker compose version`.

## 6. Despliegue de la app (CD — change `app-deploy-dev`)

La app se despliega con `.github/workflows/deploy-dev.yml`: un **push a `main`** que toque `backend/**`/`frontend/**` (o `workflow_dispatch`) construye las imágenes `prod` arm64, las publica en **GHCR** (tag `sha-<commit>` + `dev`), y un job `deploy` en un **runner self-hosted que corre EN la VM** hace el deploy **localmente** (`docker compose -f docker-compose.deploy.yml pull && up -d --wait`) — sin SSH ni puertos entrantes. El `.env` de runtime lo **lee del OCI Vault** por instance principal en cada deploy (secrets generados por Terraform); el `docker login ghcr.io` usa el **`GITHUB_TOKEN`** del propio job (la GitHub App **solo** registra el runner, no interviene en el pull de GHCR). **Cero secrets de app a mano.**

### 6.1 GitHub App (único secret-zero) + variables

Una **sola GitHub App** (reutilizable por todos los entornos) con permiso de repo `Administration: read/write` (registrar runners). *(El pull de GHCR **no** usa la App — lo hace el `GITHUB_TOKEN` del job de deploy; conceder `Packages: read` a la App sería vestigial y puede omitirse.)* Tras crearla e instalarla en el repo:

- **Variables** de repo (no sensibles): `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `NEXT_PUBLIC_APP_ENV` (p. ej. `dev`).
- **Secret** de repo: `GH_APP_PRIVATE_KEY` = contenido del `.pem` de la App. Es el **único secret-zero**; Terraform lo lee (`TF_VAR_github_app_private_key`) y lo escribe al Vault de cada entorno (`oci_vault_secret.github_app_key`). **Rotar** = regenerar el `.pem` en la App, actualizar el secret y re-aplicar.

Los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) **no se crean a mano**: los genera Terraform (`random_*`) → Vault.

### 6.2 Provisión del runner (IaC + alta a mano en la VM viva)

La provisión es **IaC**: `cloud-init.yaml.tftpl` + `runner-bootstrap.sh` + `gh-app-install-token.py`, así que una VM nueva arranca con el runner. Como el `metadata` es ForceNew + `ignore_changes`, sobre la **VM viva** se ejecuta **una vez a mano** (tras aplicar Terraform, §5.3, que ya puso la clave de la App y los OCIDs en el Vault):

```bash
# En la VM (por SSH). /etc/autohostai-deploy.env lo escribe el cloud-init en una VM nueva;
# para la VM viva, replicarlo con los OCIDs reales (los da el apply / la consola del Vault):
sudo apt-get update && sudo apt-get install -y python3-pip && sudo pip3 install oci-cli
sudo tee /etc/autohostai-deploy.env >/dev/null <<'EOF'
ENV=dev
GITHUB_REPO=autohostai-labs/AutoHostAI
GITHUB_APP_ID=<app id>
GITHUB_APP_INSTALLATION_ID=<installation id>
APP_KEY_SECRET_OCID=<ocid del secret gh-app-key>
PG_PASSWORD_SECRET_OCID=<...>
JWT_SECRET_OCID=<...>
ENCRYPTION_KEY_SECRET_OCID=<...>
POSTGRES_DB=autohostai
POSTGRES_USER=autohostai
EOF
sudo install -m0755 runner-bootstrap.sh /opt/bootstrap-runner.sh
sudo install -m0755 gh-app-install-token.py /opt/gh-app-install-token.py
sudo bash /opt/bootstrap-runner.sh
```

Verificar: **Settings → Actions → Runners** muestra `autohostai-dev-vm` **Idle** con label `dev`. Recuperación: `sudo /opt/actions-runner/svc.sh start`; si se desregistra, re-ejecutar el bootstrap (`--replace`, idempotente).

### 6.3 Arranque en frío (primer deploy sobre VM sin app)

1. GitHub App + variables/secret creados (6.1); Terraform aplicado (§5.3, crea la IAM + los secrets del Vault); runner provisionado (6.2) y online.
2. Lanzar el deploy (push a `main` o `workflow_dispatch`). El job lee los secrets del Vault → `.env`, hace `docker login ghcr.io` con el `GITHUB_TOKEN` del job, `pull`, corre `migrate` (Alembic) y arranca la app; `up --wait` falla si algo no queda `healthy`.

### 6.4 Rollback (manual, por SHA)

El deploy pinea la imagen al `sha-<commit>`. Para volver a una versión previa, re-lanzar el deploy de ese commit anterior: en **Actions → deploy-dev**, usa el `workflow_dispatch` desde el commit deseado (o `git revert` + push a `main`). No hay rollback automático — es una decisión de diseño (dev, corte breve aceptable).
