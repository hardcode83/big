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

La app se despliega con `.github/workflows/deploy-dev.yml`: un **push a `main`** que toque `backend/**`/`frontend/**` (o `workflow_dispatch`) construye las imágenes `prod` arm64, las publica en **GHCR** (tag `sha-<commit>` + `dev`), y un job `deploy` en un **runner self-hosted que corre EN la VM** hace el deploy **localmente** (`docker compose -f docker-compose.deploy.yml pull && up -d --wait`) — sin SSH ni puertos entrantes nuevos. El `.env` de runtime se renderiza desde GitHub Secrets en cada deploy.

### 6.1 Provisión del runner (IaC + alta a mano en la VM viva)

La provisión del runner es **IaC**: vive en el `cloud-init` (`cloud-init.yaml.tftpl` + `runner-bootstrap.sh`), así que una VM reconstruida arranca con el runner. Como el `metadata` es ForceNew + `ignore_changes` (cambiarlo por Terraform recrearía la VM), sobre la **VM viva** se ejecuta **una vez a mano** el mismo bootstrap:

```bash
# Prerrequisitos (ver 6.2): el PAT ya está en el Vault y la policy de instance principal aplicada.
# En la VM (por SSH):
sudo apt-get update && sudo apt-get install -y python3-pip
sudo pip3 install oci-cli
sudo install -m 0644 /dev/stdin /etc/autohostai-runner.env <<EOF
GITHUB_REPO=mreyesojeda/AutoHostAI
PAT_SECRET_OCID=<OCID del secret del PAT en el Vault>
EOF
# copiar runner-bootstrap.sh a la VM (scp) y ejecutarlo:
sudo bash runner-bootstrap.sh
```

Verificar: **Settings → Actions → Runners** del repo muestra `autohostai-dev-vm` **Idle** con label `dev`. (`sudo ./svc.sh status` en `/opt/actions-runner` para el servicio.)

**Recuperación:** si el runner se cae, `sudo ./svc.sh start`; si se desregistra, re-ejecutar `runner-bootstrap.sh` (usa `--replace`, idempotente).

### 6.2 PAT de GitHub en el Vault (subida y rotación)

El runner obtiene su registration-token llamando a la API de GitHub con un **PAT** (scope mínimo: `repo` clásico, o fine-grained con *Administration: read/write* sobre este repo). El PAT se guarda como secret del Vault **out-of-band** (nunca en el `tfstate`); el cloud-init lo lee por **instance principal**.

```bash
# Subir (una vez) — el OCID que devuelve va en dev.tfvars (runner_pat_secret_ocid):
oci vault secret create-base64 \
  --compartment-id <compartment_ocid> \
  --vault-id "$(terraform output -raw vault_id)" \
  --key-id "$(terraform output -raw secrets_key_id)" \
  --secret-name autohostai-dev-gh-pat \
  --secret-content-content "$(printf '%s' '<PAT>' | base64)"

# Rotar: crear una nueva versión del secret y revocar el PAT viejo en GitHub.
oci vault secret update-base64 --secret-id <secret_ocid> \
  --secret-content-content "$(printf '%s' '<PAT nuevo>' | base64)"
```

### 6.3 Arranque en frío (primer deploy sobre VM sin app)

1. Provisionar el runner (6.1) y confirmar que está online.
2. Crear en GitHub los secrets de runtime (ver README dev) y `GHCR_PULL_TOKEN` (read-only).
3. Lanzar el deploy (push a `main` o `workflow_dispatch`). El job crea `.env`, hace `docker login`, `pull`, corre `migrate` (Alembic) y arranca la app; `up --wait` falla si algo no queda `healthy`.

### 6.4 Rollback (manual, por SHA)

El deploy pinea la imagen al `sha-<commit>`. Para volver a una versión previa, re-lanzar el deploy de ese commit anterior: en **Actions → deploy-dev**, usa el `workflow_dispatch` desde el commit deseado (o `git revert` + push a `main`). No hay rollback automático — es una decisión de diseño (dev, corte breve aceptable).
