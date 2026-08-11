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

### 6.3.1 Cambiar la definición de una red del compose ROMPE el deploy siguiente

**Medido en el deploy real del 2026-08-08** (change `api-ingress-routing`, run 31250116992), y la primera redacción de esta sección lo decía más suave de lo que es. Decía «todo rebota pero `up --wait` sigue saliendo en 0», extrapolando de una reproducción en un stack de prueba. **Es falso en la VM**, y el motivo es exactamente por qué un stack de prueba no sirve para medirlo.

Lo que pasa, con el log delante:

```
Network autohostai_private Removed
Network autohostai_private Created          ← subred nueva
Container migrate-1  Recreate/Recreated     ← su definición cambió
Container backend-1  Recreate/Recreated     ← idem (command, imagen)
Container frontend-1 Recreate/Recreated     ← idem (ipv4_address, imagen)
Container postgres-1 Starting               ← SOLO start, nunca Recreate
Container redis-1    Starting               ← SOLO start, nunca Recreate
```

Compose recrea los contenedores **cuya definición de servicio cambió**. `postgres` y `redis` no cambiaron, así que los arranca sin recrearlos — y quedan adjuntos a la red que Compose acaba de **borrar**. El primer contenedor que intente resolverlos revienta:

```
migrate-1 | socket.gaierror: [Errno -3] Temporary failure in name resolution
```

En un stack recién creado esto no aparece: todos los contenedores nacen a la vez en la red nueva. Hace falta un stack **preexistente** para verlo, es decir la VM.

#### Recuperación

1. **Primero, lo barato**: re-lanzar el deploy (`gh run rerun <id> --failed`). Con la red vieja ya borrada, la referencia de esos dos contenedores está rota, así que Compose suele recrearlos en el segundo paso.
2. **Si no**, por SSH en la VM, que es determinista:

```bash
cd /opt/actions-runner/_work/AutoHostAI/AutoHostAI   # el checkout del runner (§7.4)
docker compose -f docker-compose.deploy.yml down
```

   y volver a lanzar el deploy. `down` **no borra los volúmenes con nombre**, así que la base de datos de dev sobrevive.

#### Antes de tocar `networks:` en el compose

Súbelo con la recuperación planeada, no con la esperanza de que salga verde. El arreglo automático —`--force-recreate` en el paso de deploy, que elimina la clase de fallo a cambio de reiniciar Postgres y Redis en **todos** los despliegues— tiene entrada propia y no se metió aquí para no cambiar la semántica del deploy en caliente.

### 6.4 Rollback (manual, por SHA)

El deploy pinea la imagen al `sha-<commit>`. Para volver a una versión previa, re-lanzar el deploy de ese commit anterior: en **Actions → deploy-dev**, usa el `workflow_dispatch` desde el commit deseado (o `git revert` + push a `main`). No hay rollback automático — es una decisión de diseño (dev, corte breve aceptable).

**Cómo confirmar que el rollback surtió efecto, sin entrar en la VM** (change
`app-version-visibility`). Antes, la única forma era leer `IMAGE_TAG` del `.env` por túnel
SSH. Ahora basta con abrir la app: el badge del pie muestra la cadena canónica completa
`<base>+<fecha-build>.<sha-corto>` (p. ej. `0.1.0+2026-07-31.5872022`) de lo que está
corriendo — la **misma** que el label `org.opencontainers.image.version` de la imagen, así que
comparar pantalla y VM es comparar dos cadenas idénticas. Ojo: la fecha tiene granularidad de
día, así que dos builds del mismo commit **el mismo día** se ven iguales en el badge; para
distinguirlos hace falta `org.opencontainers.image.created`, que lleva la hora. Desde la VM,
la identidad que lleva la imagen dentro:

```bash
docker inspect ghcr.io/autohostai-labs/autohostai-backend:sha-<commit> \
  --format '{{json .Config.Labels}}'
```

Si el badge sigue mostrando la versión **anterior** después de un deploy verde, el problema
no es el deploy — mira la tabla de §7.

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
| El **badge del pie** muestra una versión anterior a la que acabas de desplegar | El edge está sirviendo una **página** cacheada. Compara con los labels OCI de la imagen desplegada (`docker inspect`): si la imagen es la nueva y el navegador muestra la vieja, es caché del edge, no el deploy. Purga la caché de Cloudflare o prueba en incógnito. **Ojo al alcance**: el badge se renderiza en servidor, así que delata una página cacheada pero **no** chunks JS antiguos servidos con HTML fresco — para ese caso hay que mirar los nombres de fichero en la pestaña Network |
| El badge muestra `versión desconocida` en el entorno desplegado | **Dos causas distintas, y se distinguen mirando la imagen.** (1) *No se horneó identidad*: en dev local es lo normal y correcto (el target `dev` no ejecuta `npm run build`); en la VM significa que el job `provenance` no alimentó el build — revisa sus `outputs` en el run de Actions. (2) *Se horneó pero el frontend la rechazó por no tener la forma esperada*: el snapshot público solo admite `X.Y.Z+YYYY-MM-DD.<7 hex>` (o `local`) y el commit corto solo 7 caracteres hex, y cae a vacío con cualquier otra cosa — a propósito, porque ese valor viaja en el HTML de todas las superficies. Ocurre si alguien ensancha `${GITHUB_SHA:0:7}`, cambia el formato de la fecha o `VERSION` deja de ser `X.Y.Z`. **Cómo separarlas**: `docker inspect ... --format '{{json .Config.Labels}}'` y mira `org.opencontainers.image.version`. Si el label está **vacío**, es la causa 1; si lleva una cadena pero el badge dice "desconocida", es la causa 2 — compara esa cadena con las formas de arriba y corrige el patrón de `frontend/lib/config/public.ts` y el CD en el mismo commit |

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

1. **Desde internet** solo hay un camino a la app: `https://autohostai.digitalsec.work` → edge de Cloudflare → túnel → contenedor. No hay ningún puerto HTTP abierto en la VM. Desde el change `api-ingress-routing`, ese mismo camino sirve también **la API**: `/api/v1/...` en el hostname público lo reenvía el contenedor `frontend` a `backend:8000` por la red interna. Lo que sigue **sin** viajar por ahí, a propósito: `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` y `/health` — para esos, el túnel SSH de abajo sigue siendo la única vía.
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

#### Comprobar el camino a la API, y la IP que el backend observa

El túnel SSH ya no es la única forma de alcanzar `/api/v1`: desde el change `api-ingress-routing` la API responde también por el hostname público. Sigue siendo la única forma de alcanzar `/docs`.

```bash
# Por el hostname público: debe responder el sobre de error DEL BACKEND, no un 404 de Next
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' -d '{"email":"x@y.z","password":"x"}' \
  https://autohostai.digitalsec.work/api/v1/auth/login          # 401 (o 429 si ya te pasaste)

# Y estas cuatro NO deben ser alcanzables por ahí (404 de la app Next, sin tocar el backend)
for p in /openapi.json /docs /docs/oauth2-redirect /redoc; do
  printf '%s -> ' "$p"
  curl -sS -o /dev/null -w '%{http_code}\n' "https://autohostai.digitalsec.work$p"
done
```

**El diagnóstico que no es obvio: qué IP está viendo el backend.** Si la propagación se rompe, la API funciona igual pero el límite de 10 intentos/min cuenta *todo el despliegue* en un solo contador —y `audit_logs.actor_ip` registra la IP del contenedor en vez de la de la persona—. Nada falla ruidosamente, así que hay que mirarlo:

```bash
# En la VM: provoca un fallo de login por el hostname público desde tu móvil o tu portátil,
# y mira con qué IP lo registró el backend
docker compose -f docker-compose.deploy.yml logs backend --tail 50 | grep -i "ip="
```

Debe aparecer **tu IP pública**, no `10.89.0.10` (la del contenedor `frontend`). Si aparece la del contenedor, el `--forwarded-allow-ips` del `command:` de `backend` y el `ipv4_address` del `frontend` se han desincronizado — los dos salen del mismo ancla YAML, así que revisa que nadie haya escrito uno a mano.

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
cd /opt/actions-runner/_work/AutoHostAI/AutoHostAI   # checkout del runner, con el docker-compose.deploy.yml
# (localizarlo si cambia: sudo find /opt/actions-runner/_work -maxdepth 3 -name docker-compose.deploy.yml)
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

La base de datos **no** publica puerto ni en loopback, a propósito: no hay motivo para llegar a ella desde fuera del compose.

#### Cliente gráfico contra la base de datos, sin publicar nada

No hace falta tocar el compose. El bridge de Docker es enrutable **desde la propia VM**, así que puedes reenviar directamente a la IP del contenedor: la resolución del destino de un `-L` ocurre en el extremo **remoto** (la VM), no en tu portátil, que es el mismo detalle que explica `-L 3000:localhost:3000` en §7.4.1.

```bash
# En la VM: saca la IP del contenedor de postgres (cambia cada vez que se recrea, así que
# no la anotes en ~/.ssh/config — resuélvela en el momento).
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' autohostai-postgres-1
```

```bash
# En tu portátil, con esa IP:
ssh -i ~/.ssh/autohostai_dev_vm -L 5432:<IP-del-contenedor>:5432 ubuntu@<IP pública>
# y apunta el cliente gráfico a localhost:5432 con las credenciales del .env de la VM
```

Nada publicado, nada que revertir, y el security list sigue intacto. Si prefieres una sola línea desde tu portátil:

```bash
ssh autohostai-dev -L 5432:"$(ssh autohostai-dev docker inspect -f \
  '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
  "$(ssh autohostai-dev docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' autohostai-postgres-1)")":5432
```

> **Norma, y aplica a cualquier servicio, no solo a Postgres:** si alguna vez publicas un puerto temporalmente en el compose, **siempre** con el prefijo `127.0.0.1:` (`"127.0.0.1:5432:5432"`, nunca `"5432:5432"`). Sin el prefijo, Docker publica en `0.0.0.0` y el servicio queda alcanzable **desde toda la VCN** — con Postgres eso significa la contraseña del superusuario expuesta a cualquier recurso de la red. Es el razonamiento de la decisión D11 del change `ingress-https-dev`, que es también por lo que `backend` y `frontend` publican en `127.0.0.1` y no a secas. Y recuerda que un puerto publicado a mano sobrevive hasta que alguien lo revierte: el reenvío de arriba no tiene ese modo de fallo, y por eso es el camino recomendado.

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

### 7.4.6 Comprobar que el túnel sigue aislado de los datos

El compose de deploy separa dos redes a propósito. Lo que impide que una regla de ingress reescrita en el edge —que solo cuesta el API token de Cloudflare, sin `apply`— publique la base de datos o la API es el **aislamiento L3 entre bridges**: Docker descarta el tráfico entre bridges distintos, así que desde la red del túnel no se llega a `private` **ni por IP**. Como consecuencia de esa separación, `cloudflared` tampoco **resuelve** los nombres `postgres`, `redis` ni `backend` — pero la resolución es el síntoma, no el control, y por eso la comprobación (3) de abajo es la que de verdad lo demuestra. El razonamiento completo vive en `docs/adr/0003-https-ingress-dev.md` §Addendum 2026-08-04: **§1** es la enumeración canónica del radio y **§2** la del invariante (con sus dos mitades, pertenencia y reenvío). El comentario de la sección `networks` de `docker-compose.deploy.yml` lleva el resumen operativo para quien edita la topología.

Conviene comprobarlo tras cualquier cambio de topología, y toma medio minuto. La prueba se hace **sobre la red**, no metiéndose en el contenedor del túnel: la imagen de `cloudflared` es distroless (sin shell, `curl` ni `wget`), así que no admite `exec`; y como está atado a una sola red, una propiedad de esa red es una propiedad suya. Se usa la imagen `postgres:16` porque ya está en la VM y trae `getent` y `bash`, así que no hay que descargar nada.

```bash
# 1. Estructural: el contenedor del túnel debe estar SOLO en `autohostai_ingress`.
#    Se usan los nombres de contenedor (`autohostai-<servicio>-1`, deterministas) en vez de
#    `compose ps -q`: así estas comprobaciones funcionan desde CUALQUIER directorio y no dependen
#    de encontrar el checkout del runner.
docker inspect -f '{{json .NetworkSettings.Networks}}' autohostai-cloudflared-1

# 2. Por nombre — DEBE fallar en ingress y resolver en private
docker run --rm --network autohostai_ingress postgres:16 getent hosts postgres   # falla
docker run --rm --network autohostai_private postgres:16 getent hosts postgres   # resuelve
```

```bash
# 3. Por IP literal, y es la que de verdad importa: una regla de ingress puede apuntar a una IP,
#    no solo a un nombre. Lo que lo bloquea es el aislamiento L3 entre bridges, no el DNS, y esta
#    es la única comprobación que lo demuestra.
PGIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' autohostai-postgres-1)
if [ -z "$PGIP" ]; then
  echo "NO CONCLUYENTE: no se pudo obtener la IP de postgres (¿está levantado?) — no repitas la"
  echo "comprobación hasta resolverlo: un fallo de conexión aquí no probaría nada."
else
  echo "IP de postgres: $PGIP"
  # Control POSITIVO primero: desde `private` DEBE conectar. Si no conecta, la prueba de abajo
  # daría 'bloqueado' sin haber demostrado nada, y eso es lo peor que puede pasar en una
  # comprobación de seguridad: un OK vacío justo después de cambiar la topología.
  docker run --rm --network autohostai_private postgres:16 \
    timeout 5 bash -c "</dev/tcp/$PGIP/5432" \
    && echo "control positivo OK: desde private se conecta" \
    || echo "CONTROL POSITIVO FALLA -> la comprobación siguiente NO es concluyente"
  docker run --rm --network autohostai_ingress postgres:16 \
    timeout 5 bash -c "</dev/tcp/$PGIP/5432" \
    && echo "ROTO: la red de ingress alcanza postgres por IP" \
    || echo "OK: bloqueado por aislamiento L3"
fi
```

Si (2) resuelve o (3) conecta desde `ingress`, el aislamiento está roto: mira qué redes se han añadido en el compose antes de dar el despliegue por bueno. Y si el control positivo falla, el "OK" de la última línea no vale: arréglalo antes de concluir nada.

> **Lo que este aislamiento NO cubre.** No es solo el frontend: `cloudflared` sigue alcanzando su **propio loopback** (endpoint de métricas con `/ready` y `/debug/pprof` — ninguna separación de redes puede cubrirlo, porque no pasa por red) y **el host por el gateway del bridge**, y por esa vía el puerto **22**, el **servicio de metadatos de la instancia** y la VCN enrutable. La fila de metadatos es la grave: de ahí salen credenciales de instance principal y con ellas los secretos del Vault, así que datos que este apartado declara fuera de alcance siguen siendo alcanzables por otra vía.
>
> **La enumeración completa y autoritativa está en `docs/adr/0003-https-ingress-dev.md` §Addendum 2026-08-04 §1, y este runbook no la copia a propósito** (se corrigió tres veces durante `ingress-https-hardening` y nunca acertó a la vez en todos los sitios donde estaba duplicada). Aquí van solo los comandos, que es lo que puedes ejecutar. Mitigar el residual es un cambio de la superficie de la VM, no de esta topología, y tiene change propio pendiente.

Dos medidas más que conviene hacer una vez, porque hoy están **analizadas y no medidas** (lo esperado en Docker sobre cloud, pero nadie lo ha comprobado en esta VM):

```bash
# 4. El residual de IMDS. Se ESPERA que conecte: eso confirma el residual documentado en el ADR.
docker run --rm --network autohostai_ingress postgres:16 \
  timeout 5 bash -c "</dev/tcp/169.254.169.254/80" \
  && echo "CONFIRMADO: la red de ingress alcanza IMDS (residual real)" \
  || echo "no alcanzable (comprobar por qué antes de darlo por bueno)"
```

```bash
# 5. La fila que SOSTIENE el acotado del backend, y es la única «Sí» sin medir del ADR §1: que el
#    gateway del bridge NO dé acceso a los 8000/3000 publicados en el loopback de la VM. Si esto
#    conectara, una regla `http://<gw>:8000` publicaría la API entera y R1 quedaría vacío.
GW=$(docker network inspect autohostai_ingress -f '{{(index .IPAM.Config 0).Gateway}}')
echo "gateway de ingress: $GW"
for p in 8000 3000; do
  docker run --rm --network autohostai_ingress postgres:16 \
    timeout 5 bash -c "</dev/tcp/$GW/$p" \
    && echo "ROTO: el gateway expone $p — la API/el front son publicables por el túnel" \
    || echo "OK: $p no alcanzable por el gateway"
done

# Y el 22, que SÍ está en el residual: aquí lo esperado es que CONECTE (medido el 2026-08-04).
# Si algún día deja de conectar, es que alguien mitigó el residual — comprueba si fue a propósito.
docker run --rm --network autohostai_ingress postgres:16 \
  timeout 5 bash -c "</dev/tcp/$GW/22" \
  && echo "CONFIRMADO: el gateway expone el 22 (residual conocido del ADR §1)" \
  || echo "el 22 ya no es alcanzable — ¿se mitigó el residual?"

# El mecanismo, si necesitas verlo: el ruleset acepta `tcp dpt:22` desde 0.0.0.0/0 (bridges
# incluidos) y rechaza el resto con icmp-host-prohibited, que es el `No route to host` de arriba.
sudo iptables -L INPUT -n --line-numbers | head
```

> **Tras el primer deploy con las dos redes**, un `docker network ls` puede seguir mostrando la vieja `autohostai_default` huérfana: compose no siempre la elimina en un `up`. Es inocua —ya no hay contenedores en ella— pero conviene retirarla con `docker network prune` para que la topología que ves sea la que hay.

## 8. Rescatar una cuenta sin acceso (change `auth-account-recovery`)

**Cuándo**: alguien no puede entrar y la recuperación por correo no le sirve. Hoy eso es
**siempre**, porque el aviso de recuperación no llega a nadie: el canal `EMAIL` resuelve a
`ConsoleEmailAdapter`, al que `specs/access-notifications.md` prohíbe registrar el contenido y el
destinatario, así que el enlace no se puede leer ni del log. El adapter SMTP real llega con
`hardening-release`.

El caso que **no tiene otra salida** es el único `TENANT_OWNER` activo de un tenant: solo
`TENANT_OWNER` tiene `MANAGE_USERS`, así que nadie más puede resetearlo, y él tendría que
autenticarse para resetearse a sí mismo. El bootstrap tampoco vale: es idempotente y no modifica
un usuario que ya existe.

```bash
# En la VM, desde el directorio del compose de deploy.
docker compose exec backend python -m app.cli.reset_password --email <dirección>
```

Imprime la contraseña temporal **una sola vez** por salida estándar. No queda en ningún log ni en
la fila de auditoría — solo en tu terminal y en tu portapapeles, así que entrégala por un canal
que te fíes y no la pegues en un ticket.

Lo que hace, y por lo que existe en lugar de un `UPDATE` a mano:

1. Escribe la contraseña **por la entidad**, así que la cuenta queda obligada a cambiarla antes
   de poder operar (recibe `403 PASSWORD_CHANGE_REQUIRED` en todo salvo `GET /auth/me`,
   `POST /auth/logout` y `POST /auth/change-password`).
2. **Revoca todas las sesiones** del usuario. Un rescate que las dejara vivas no habría
   recuperado la cuenta, le habría añadido una credencial.
3. **Levanta el bloqueo por fallos de login**. Diez intentos fallidos son justo lo que precede a
   una llamada de soporte, y sin esto el login inmediatamente posterior seguiría rechazado.
4. Deja **fila de auditoría** (`USER_PASSWORD_RESET`, sin actor: una línea de comandos no tiene
   identidad que registrar).

**Si avisa de que no pudo levantar el bloqueo** (Redis inalcanzable), la contraseña **sí se
cambió**: el bloqueo caduca por su cuenta dentro de la ventana de lockout. Reintentar el comando
es inocuo, pero genera otra contraseña.

No hay objetivo de `make` para esto a propósito: es una operación de rescate, no parte del flujo
normal. Detalle completo de los tres endpoints y de la política de contraseña en
`docs/auth-account-recovery.md`.

