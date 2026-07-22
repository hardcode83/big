# Runbook operativo — infra dev (Oracle Cloud)

Procedimientos de operación/recuperación del entorno `dev`. Complementa al `README.md` (uso) y al `docs/adr/0001-dev-hosting-provider.md` (decisión). Los cambios de infra se aplican **por el pipeline** (`workflow_dispatch` de `.github/workflows/infra-dev.yml`), no con `terraform apply` local.

Referencias rápidas: usuario SSH `ubuntu` · clave local `~/.ssh/autohostai_dev_vm` · bucket de state `autohostai-tfstate-dev` (objeto `dev.tfstate`) · la instancia vive en **AD-3**.

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
  --secret-id <secret_ocid> \
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
