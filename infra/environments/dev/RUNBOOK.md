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

**Cómo confirmar que el rollback surtió efecto, sin entrar en la VM** (change `app-version-visibility`). Antes, la única forma era leer `IMAGE_TAG` del `.env` por túnel SSH. Ahora hay tres vías, de más barata a más profunda:

```bash
# 1. Desde fuera, sin credenciales: la cadena de versión que sirve el backend.
curl -s https://autohostai.digitalsec.work/deployment/version
# → {"frontend":"0.1.0+2026-07-30.a2f3c1d","backend":"0.1.0+2026-07-30.a2f3c1d"}

# 2. Abrir la app: el badge del pie muestra `<base>+<sha-corto>`. En el workspace,
#    "Detalles" abre el panel con el PR, el commit y el run de Actions ENLAZADOS —
#    de ahí se llega al PR que produjo lo que está corriendo.

# 3. Desde la VM, la identidad que lleva la imagen dentro (no lo que compose cree):
docker inspect ghcr.io/autohostai-labs/autohostai-backend:sha-<commit> \
  --format '{{json .Config.Labels}}'
```

Las dos versiones deben coincidir. **Si no coinciden**, el panel lo avisa: significa que backend y frontend corren imágenes distintas — típicamente un `restart` a mano o un `pull` del tag móvil `dev`. Se arregla re-lanzando el deploy del commit deseado, que vuelve a pinear los dos al mismo `sha-`.

Y al revés: si el badge sigue mostrando la versión **anterior** después de un deploy verde, el problema no es el deploy — mira la tabla de §7.

**Si el `migrate` falla por el índice único de emails.** La migración `e1eed2e039ee` crea un índice **único** sobre `lower(email)` en `users` — global, no por tenant (ADR 0005) — y retira la constraint `UNIQUE(tenant_id, email)`. Si la base ya tuviera la misma dirección en dos tenants, o dos variantes de mayúsculas en cualquier sitio, el `migrate` aborta (correctamente: `restart: "no"`, y `backend`/`worker` no arrancan porque dependen de `service_completed_successfully`). El rollback por SHA de arriba **no sirve**, porque el problema son los datos, no el código: el siguiente deploy hacia delante volvería a fallar igual. Hay que limpiar primero:

```bash
# desde la VM, ver las colisiones (ojo: agrupado SOLO por la dirección, sin tenant_id —
# dos tenants con el mismo email ya son una colisión)
docker compose -f docker-compose.deploy.yml exec postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT lower(email) AS addr, count(*), array_agg(id), array_agg(tenant_id) FROM users
   GROUP BY lower(email) HAVING count(*) > 1;"
```

Decidir cuál fila se queda, borrar o corregir el resto, y re-lanzar el deploy. Por qué existe ese índice: el login recibe solo `{email, password}`, así que si una dirección puede existir dos veces **no identifica la cuenta**, y quien pueda crear usuarios en otro tenant deja fuera del producto a una cuenta existente sin que haya endpoint de desbloqueo (ADR 0005, design D16/D19).

### 6.5 Crear los usuarios iniciales en el entorno desplegado (change `auth-tenancy`)

El producto no tiene registro público, así que tras un arranque en frío **no hay ninguna cuenta con la que entrar** hasta que se ejecuta el bootstrap. No está en el pipeline a propósito: las contraseñas las elige una persona, así que no encajan en el patrón `random_*` + Vault que usa el resto de secretos (`steering/security.md` §8) y no deben quedar escritas en el `.env` que el workflow reescribe en cada deploy.

Se hace **una vez**, a mano. **No con `-e` en la línea de comandos**: eso deja las dos contraseñas más privilegiadas del despliegue en el `~/.bash_history` del operador y, mientras corre, en un `/proc/<pid>/cmdline` legible por cualquiera de la máquina (CWE-214). Se pasan por un fichero temporal con permisos `600` que se borra al terminar:

```bash
# en la VM, en el directorio del proyecto compose
umask 077 && cat > /tmp/bootstrap.env <<'EOF'
BOOTSTRAP_TENANT_NAME=...
BOOTSTRAP_TENANT_BILLING_EMAIL=...
BOOTSTRAP_OWNER_NAME=...
BOOTSTRAP_OWNER_EMAIL=...
BOOTSTRAP_OWNER_PASSWORD=...
BOOTSTRAP_MANAGER_NAME=...
BOOTSTRAP_MANAGER_EMAIL=...
BOOTSTRAP_MANAGER_PASSWORD=...
EOF

# el heredoc con 'EOF' entre comillas no expande nada, y el fichero nace en 600
docker compose -f docker-compose.deploy.yml run --rm --no-deps \
  --env-file /tmp/bootstrap.env backend python -m app.cli.bootstrap

shred -u /tmp/bootstrap.env 2>/dev/null || rm -f /tmp/bootstrap.env
```

Notas que importan:

- **`python -m`, no `uv run`**: la imagen `prod` no lleva `uv` (solo la etapa `dev` lo copia), pero sí tiene el venv en el `PATH`. El mismo comando vale en local (`make bootstrap`) y aquí.
- Es **idempotente**: repetirlo no duplica nada. Pero si cambias `BOOTSTRAP_TENANT_NAME` y vuelves a lanzarlo, aborta con `BootstrapConflictError` en vez de crear un segundo tenant con los mismos emails. El índice único global rechazaría esa escritura de todas formas (ADR 0005); lo que aporta el aborto explícito es un mensaje que nombra la variable a revisar en lugar de un `IntegrityError` sobre un índice. Si aborta, es que ya hay usuarios con esas direcciones: revisa el nombre del tenant.
- Si falta alguna variable, aborta **antes** de escribir nada y las lista todas.
- `run --rm --no-deps` en vez de `exec`: el contenedor vive solo para este comando y se lleva las variables con él, en vez de inyectarlas en el proceso del `backend` que está sirviendo.
- Comprueba que funciona con un login: ver `docs/auth-tenancy.md`.

## 7. Ingress HTTPS — Cloudflare Tunnel (change `ingress-https-dev`)

La app se sirve en **https://autohostai.digitalsec.work** a través de un Cloudflare Tunnel: el contenedor `cloudflared` abre una conexión **saliente** al edge, que termina TLS y entrega a `frontend:3000` por la red interna del compose. **No hay ningún puerto entrante abierto** — el security list solo permite el 22. Decisión y alternativas descartadas en [`docs/adr/0003-https-ingress-dev.md`](../../../docs/adr/0003-https-ingress-dev.md).

Consecuencia operativa clave: **si el túnel cae, la app no es alcanzable por HTTPS y no hay vía alternativa por HTTP.** El acceso de emergencia es SSH (§1).

### 7.1 Bootstrap irreducible (una vez, a mano)

Dos cosas no son codificables y se hacen en el dashboard de Cloudflare:

1. **El dominio y su zona** — registrar y delegar nameservers establece propiedad.
2. **El API token del provider.** **My Profile → API Tokens → Create Custom Token** (ninguna plantilla sirve). Tres permisos, que mezclan ámbito de cuenta y de zona:

   | Ámbito | Grupo | Nivel | Para qué |
   |---|---|---|---|
   | Account | Cloudflare Tunnel | Edit | crear el túnel y su configuración de routing |
   | Zone | DNS | Edit | el CNAME al `<tunnel_id>.cfargotunnel.com` |
   | Zone | Zone Settings | Edit | forzar HTTPS (`always_use_https`) |

   ⚠️ El **TLS mínimo de la zona sigue en 1.0** y este entorno **no** lo modifica: `digitalsec.work` aloja otros servicios y subirlo a 1.2 concentraría el riesgo sobre ellos sin aportar nada al ingress (decisión D7 del change `ingress-https-dev` / ADR 0003). No des por hecho un mínimo de TLS 1.2 en el hostname público.

   ⚠️ Busca **"Cloudflare Tunnel", no "Zero Trust"**: son grupos distintos en el selector, aunque el recurso de Terraform se llame `zero_trust_tunnel_cloudflared`. Acota **Zone Resources** a la zona concreta, no "All zones".

   Verificar antes de guardarlo, y subirlo (el valor se muestra una sola vez):

   ```bash
   # Léelo SIN dejarlo en el historial del shell: -s no lo muestra al teclearlo, y al no ir
   # como argumento no acaba en ~/.zsh_history. Es el secreto de mayor radio de este entorno
   # (DNS y TLS de toda la zona), así que no lo pases nunca en la línea de comandos.
   read -rs CF_TOKEN

   curl -s -H "Authorization: Bearer $CF_TOKEN" \
     https://api.cloudflare.com/client/v4/user/tokens/verify | jq .success   # debe ser true

   gh secret set CLOUDFLARE_API_TOKEN --repo autohostai-labs/AutoHostAI <<<"$CF_TOKEN"
   unset CF_TOKEN

   # El zone ID también se pide por stdin (convención del equipo: se trata como sensible).
   gh secret   set CLOUDFLARE_ZONE_ID     --repo autohostai-labs/AutoHostAI
   gh variable set CLOUDFLARE_ACCOUNT_ID  --repo autohostai-labs/AutoHostAI
   gh variable set CLOUDFLARE_ZONE_NAME   --repo autohostai-labs/AutoHostAI --body 'digitalsec.work'
   gh variable set PUBLIC_HOSTNAME        --repo autohostai-labs/AutoHostAI --body 'autohostai.digitalsec.work'
   gh variable set OCI_VAULT_ID           --repo autohostai-labs/AutoHostAI   # terraform output vault_id
   ```

   **El API token NO se copia al Vault** (a diferencia de la clave de la GitHub App): su radio de daño es toda la zona y es re-emitible en segundos, así que una copia solo ampliaría la exposición. Si se pierde, se re-emite y se actualiza el GitHub Secret.

### 7.2 Diagnóstico

```bash
# ¿El túnel está conectado al edge? (healthcheck del compose usa esto mismo)
docker compose -f docker-compose.deploy.yml exec cloudflared cloudflared tunnel ready

# Logs del túnel (registro de conexiones al edge, errores de origen)
docker compose -f docker-compose.deploy.yml logs --tail=100 cloudflared

# Estado visto desde Cloudflare: Zero Trust → Networks → Tunnels (healthy / degraded / down)
```

Interpretación rápida:

| Síntoma | Causa probable |
|---|---|
| `cloudflared` **unhealthy** al desplegar | el token no llegó al `.env` (mira el paso "Render .env" del job) o el edge no es alcanzable |
| Túnel **healthy** pero HTTPS da **502** | el origen no responde: revisar `frontend` (`docker compose ps`) |
| HTTPS da **404** en vez de la app | el hostname no casa con la regla de ingress y cae en la catch-all; revisar `PUBLIC_HOSTNAME` vs. el `hostname` del `_config` |
| **Aviso de certificado** en el navegador | el hostname tiene más de una etiqueta bajo el apex → fuera del Universal SSL gratuito (la `precondition` de Terraform debería haberlo impedido) |
| El **badge del pie** muestra una versión anterior a la que acabas de desplegar | El edge está sirviendo una **página** cacheada. Compara con `curl -s https://autohostai.digitalsec.work/deployment/version`: si ahí sale la nueva y en el navegador la vieja, es caché del edge, no el deploy. Purga la caché de Cloudflare o prueba en incógnito. **Ojo al alcance**: el badge se renderiza en servidor, así que delata una página cacheada pero **no** chunks JS antiguos servidos con HTML fresco — para ese caso hay que mirar los nombres de fichero en la pestaña Network |
| El badge muestra `versión desconocida` en el entorno desplegado | La imagen se construyó sin los build-args de identidad. En dev local es lo normal y correcto (el target `dev` no ejecuta `npm run build`); en la VM significa que el job `provenance` no alimentó el build — revisa sus `outputs` en el run de Actions |
| El panel avisa de **deriva** entre frontend y backend | Corren imágenes distintas: casi siempre un `restart` a mano o un `pull` del tag móvil `dev`. Re-lanza el deploy del commit deseado (§6.4) para volver a pinear los dos al mismo `sha-` |
| El panel dice **`push directo, sin PR`** | No es un error: ese commit llegó a `main` sin Pull Request. La extracción solo reconoce `Merge pull request #N …` y `título (#N)` a propósito, para no confundir un número de issue con uno de PR (ver `docs/app-version-visibility.md`) |

### 7.3 Rotar el secreto del túnel

Lo genera Terraform (`random_bytes.tunnel_secret`), así que rotarlo es forzar un valor nuevo y volver a aplicar:

```bash
# Desde main, con el workflow infra-dev (plan → apply):
terraform taint random_bytes.tunnel_secret      # o: terraform apply -replace='random_bytes.tunnel_secret'
```

El `apply` recrea el túnel, actualiza el secreto del Vault y **reconcilia el CNAME** (depende del id del túnel). Después hace falta **un deploy** para que `cloudflared` recoja el token nuevo del Vault; hasta entonces el contenedor sigue con el antiguo y quedará `unhealthy` cuando el túnel viejo desaparezca.

### 7.4 Depuración y acceso a la máquina

Cómo mirar la app y diagnosticar cuando algo va mal, sabiendo que **no hay ningún puerto HTTP abierto al público**. Léete el modelo mental una vez y el resto se explica solo.

#### El modelo mental en tres frases

1. **Desde internet** solo hay un camino a la app: `https://autohostai.digitalsec.work` → edge de Cloudflare → túnel → contenedor. No hay ningún puerto HTTP abierto en la VM.
2. **Desde la VM**, `backend` y `frontend` sí escuchan en `127.0.0.1` (puertos 8000 y 3000). No son alcanzables desde fuera —`127.0.0.1` no es enrutable— pero sí desde la propia máquina.
3. **Tú entras por SSH** (puerto 22, acotado a los CIDRs de operador) y, si quieres, te traes esos puertos a tu portátil por el propio SSH. Eso te da la app en tu navegador **sin pasar por Cloudflare**, que es como se distingue un fallo de la app de un fallo del edge.

### 7.4.1 Ver la app en tu navegador por túnel SSH (lo que querrás el 90 % de las veces)

**Ojo con el nombre:** este túnel **no** es el de Cloudflare. Son dos cosas opuestas que conviven:

| | Cloudflare Tunnel | Túnel SSH (esta sección) |
|---|---|---|
| Quién lo abre | `cloudflared`, desde la VM hacia el edge | **tú**, desde tu portátil hacia la VM |
| Dirección | **saliente** de la VM | **entrante** a la VM, por el puerto 22 |
| Para quién | el público, en `https://autohostai.digitalsec.work` | solo para ti, mientras la sesión esté abierta |
| Qué expone | publica la app en internet | **nada**; solo te acerca un puerto que ya existe |

#### Requisitos previos

1. Tener la clave privada de la VM en `~/.ssh/autohostai_dev_vm` (recuperable del Vault, §2).
2. Que **tu IP pública esté en `allowed_ssh_cidrs`**. Si cambió de casa/oficina, actualiza el secret `ALLOWED_SSH_CIDR` y aplica `infra-dev` (§0). Compruébala con `curl -s ifconfig.me`.
3. Saber la IP pública de la VM. Es **reservada**, así que no cambia:

   ```bash
   cd infra/environments/dev && terraform output -raw instance_public_ip
   ```

#### El comando

```bash
ssh -i ~/.ssh/autohostai_dev_vm \
    -L 3000:localhost:3000 \
    -L 8000:localhost:8000 \
    ubuntu@"$(cd infra/environments/dev && terraform output -raw instance_public_ip)"
```

Si no tienes el repo a mano, saca la IP de la consola de OCI (Compute → Instance → Public IP) o de un `ssh` previo. **No la anotamos aquí a propósito:** ocultar el enlace hostname→origen es una propiedad que este entorno gana con el túnel —`dig` del hostname solo devuelve IPs del edge de Cloudflare—, y committearla en el repo la revierte.

**Cómo leer `-L 3000:localhost:3000`** — es `-L <puerto_en_tu_portátil>:<destino>:<puerto_del_destino>`:

- El **primer** `3000` es el puerto que `ssh` abre **en tu portátil**.
- `localhost:3000` es el destino **visto desde la VM** — ahí es donde el contenedor `frontend` publica (en `127.0.0.1`, ver el compose). Esa resolución ocurre en el extremo remoto, no en el tuyo: es el detalle que más confunde.

Es decir, el recorrido completo es:

```
navegador → localhost:3000 (tu portátil) → canal SSH cifrado (puerto 22)
          → la VM → 127.0.0.1:3000 de la VM → contenedor frontend
```

Y **por eso** `backend`/`frontend` publican en loopback: si no publicaran nada, `ssh -L` no tendría a qué conectarse en la VM y daría `connection refused`.

#### Qué abrir una vez conectado

Deja esa terminal abierta y ve al navegador:

| URL | Qué es |
|---|---|
| **http://localhost:3000** | el frontend, con devtools y pestaña Network, **sin pasar por Cloudflare** |
| **http://localhost:8000/docs** | Swagger del backend (OpenAPI autogenerado) |
| **http://localhost:8000/health** | healthcheck del backend |

Comprueba que el túnel está vivo sin salir de tu máquina:

```bash
curl -sSI http://localhost:3000 | head -1     # debería responder algo, no "connection refused"
curl -sS  http://localhost:8000/health
```

#### Cerrarlo

Sal de la sesión (`exit` o `Ctrl-D`). El listener de tu portátil desaparece y **no queda nada abierto** en ningún sitio: no has tocado el security list ni la configuración de la VM.

#### Variante cómoda: alias en `~/.ssh/config`

Para no recordar el comando, añade esto a tu `~/.ssh/config`:

```
Host autohostai-dev
    HostName <IP pública de la VM — terraform output -raw instance_public_ip>
    User ubuntu
    IdentityFile ~/.ssh/autohostai_dev_vm
    LocalForward 3000 localhost:3000
    LocalForward 8000 localhost:8000
    ServerAliveInterval 30
```

A partir de entonces basta con:

```bash
ssh autohostai-dev
```

y los dos puertos se reenvían solos. `ServerAliveInterval 30` evita que la sesión muera sola cuando llevas rato sin teclear.

#### Variante en segundo plano

Si solo quieres los puertos, sin shell:

```bash
ssh -fN autohostai-dev          # -f = a segundo plano, -N = no ejecutar comando remoto
# ...trabaja en el navegador...
pkill -f 'ssh -fN autohostai-dev'   # para cerrarlo
```

#### Errores frecuentes

| Mensaje | Causa y arreglo |
|---|---|
| `bind: Address already in use` | ya tienes algo en tu 3000 local (tu propio `make up`). Cambia **solo el puerto local**: `-L 3001:localhost:3000` y abre `http://localhost:3001` |
| `channel 1: open failed: connect failed: Connection refused` | la sesión SSH funciona, pero en la VM no hay nada escuchando en ese puerto → el contenedor está caído o no publica en loopback. Mira `$C ps` (§7.4.2) |
| `Connection timed out` al conectar | tu IP no está en `allowed_ssh_cidrs` (requisito 2) |
| `Permission denied (publickey)` | clave incorrecta o no autorizada en la VM; ver §1 para añadir/rotar claves |

### 7.4.2 Estado y logs

```bash
ssh ubuntu@<IP pública>
cd /opt/autohostai        # checkout que deja el runner, con el docker-compose.deploy.yml
C="docker compose -f docker-compose.deploy.yml"

$C ps                     # estado y healthy/unhealthy de los 7 servicios
$C logs --tail=100 backend
$C logs --tail=100 frontend
$C logs --tail=100 cloudflared     # el túnel: conexiones al edge, errores de origen
$C logs -f worker                  # Celery, en vivo
```

### 7.4.3 Entrar a un contenedor o a la base de datos

```bash
$C exec backend bash                                  # shell en el backend
$C exec backend python3 -c "print('hola')"            # one-liner
$C exec postgres psql -U autohostai -d autohostai     # consola SQL
$C exec redis redis-cli info clients
```

La base de datos **no** publica puerto ni en loopback, a propósito: no hay motivo para llegar a ella desde fuera del compose. Si necesitas un cliente gráfico, añade `-L 5432:localhost:5432` **y** publica temporalmente el puerto en el compose; recuerda revertirlo.

### 7.4.4 ¿El problema es la app, el túnel o el edge?

Este es el árbol de decisión. Compara lo que ves **por HTTPS público** con lo que ves **por el túnel SSH**:

| Por HTTPS público | Por `localhost:3000` (SSH) | Diagnóstico |
|---|---|---|
| falla | **falla igual** | **es la app.** Mira los logs de `frontend`/`backend`; Cloudflare no tiene nada que ver |
| falla | **funciona** | **es el túnel o el edge.** Sigue con 7.2 (`cloudflared tunnel ready`, logs de `cloudflared`) |
| `530` / error 1033 | funciona | el túnel **no tiene conector**: `cloudflared` está caído o sin token válido → `$C ps`, `$C logs cloudflared` |
| `502` | funciona | el túnel está arriba pero el origen no responde: revisa `$C ps` del `frontend` |
| `404` en vez de la app | funciona | el hostname no casa la regla de ingress y cae en la catch-all → revisa `PUBLIC_HOSTNAME` vs. el `_config` del túnel en Terraform |
| funciona | falla | raro: cachéo del edge sirviendo una versión anterior, o el frontend responde a `cloudflared` pero no a loopback |

### 7.4.5 Si nada responde y hay que entrar a la fuerza

SSH es la red de seguridad y **nunca se cierra**. Si tampoco entra por SSH:

1. Tu IP pública ha cambiado y ya no está en `allowed_ssh_cidrs` → actualiza el secret `ALLOWED_SSH_CIDR` y aplica `infra-dev`.
2. Si eso no fuera posible, queda la **consola serie de OCI** (Compute → Instance → Console connection), que no depende de la red de la VM.

