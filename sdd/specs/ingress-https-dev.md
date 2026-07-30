# Ingress HTTPS del entorno dev (Cloudflare Tunnel)

## Purpose

Vía de acceso público a la aplicación desplegada en el entorno `dev`: **https://autohostai.digitalsec.work**, servida a través de un Cloudflare Tunnel. El contenedor `cloudflared` que corre en la VM abre una conexión **saliente** al edge de Cloudflare, que termina TLS y entrega al frontend por la red interna del compose, de modo que la máquina **no expone ningún puerto HTTP** y no gestiona certificados. Sustituye al acceso HTTP directo por los puertos 8000/3000 restringido a CIDRs de operador, que ya no existe. Decisión y alternativas descartadas en `docs/adr/0003-https-ingress-dev.md`; operación en `infra/environments/dev/RUNBOOK.md` §7 y uso en `docs/ingress-https.md`.

## Requirements

### Túnel, routing y DNS como código (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL declarar el túnel como `cloudflare_zero_trust_tunnel_cloudflared` con `config_src = "cloudflare"` — la configuración de ingress reside en el edge, no en un fichero de la VM — y su secreto como `random_bytes` de 32 bytes generado por Terraform.
- THE SYSTEM SHALL declarar el routing como `cloudflare_zero_trust_tunnel_cloudflared_config` con dos reglas de ingress en este orden: `hostname = var.public_hostname` → `service = "http://frontend:3000"`, y una **catch-all final** `service = "http_status:404"`, de modo que cualquier hostname no previsto que resuelva al túnel reciba 404 y nunca la aplicación.
- THE SYSTEM SHALL declarar el registro DNS como `cloudflare_dns_record` de tipo `CNAME` hacia `<tunnel_id>.cfargotunnel.com` con `proxied = true` y `ttl = 1` (obligatorio en el provider y único valor válido con proxy activo), derivando el destino del `id` del recurso del túnel — nunca un literal.
- THE SYSTEM SHALL declarar un `lifecycle { precondition }` en el registro DNS que exija que el nombre real de la zona de `var.cloudflare_zone_id` coincida con `var.cloudflare_zone_name`, para que una desincronización entre ambas no deje pasar un hostname fuera del alcance del certificado gratuito.
- THE SYSTEM SHALL derivar el token que consume `cloudflared` de datos que ya están en el grafo — `base64encode(jsonencode({a = account_tag, t = id, s = secreto}))` — porque el provider v5 no expone un atributo `token`, y THE SYSTEM SHALL NOT requerir que ningún valor generado por Terraform se copie a mano desde el dashboard de Cloudflare.
- THE SYSTEM SHALL fijar el provider `cloudflare` con constraint `~> 5.0` en `required_providers` y mantener `.terraform.lock.hcl` versionado con sus hashes para `darwin_arm64` y `linux_amd64`.

### HTTPS forzado en el edge

- WHEN un cliente solicita el hostname público por HTTP, THE SYSTEM SHALL responder con una redirección permanente a HTTPS, mediante el recurso `cloudflare_zone_setting.always_use_https`.
- WHEN se solicita el hostname público por HTTPS, THE SYSTEM SHALL servir la aplicación con un certificado válido y confiado por navegadores, sin ningún certificado gestionado en el origen.
- THE SYSTEM SHALL NOT modificar `min_tls_version` de la zona, que permanece en **1.0**: `digitalsec.work` aloja servicios ajenos a este entorno y subirlo concentraría el riesgo sobre ellos sin aportar nada al ingress. El forzado de HTTPS es de **zona completa** —Cloudflare no lo ofrece por hostname en el plan Free— y afecta a los hosts `proxied` del dominio.
- THE SYSTEM SHALL exigir que `var.public_hostname` sea **una sola etiqueta** bajo el apex de la zona, porque el certificado Universal SSL gratuito solo cubre el apex y el primer nivel; mayor profundidad requeriría un certificado de pago.
- THE SYSTEM SHALL exigir además que esa etiqueta empiece por `autohostai`, porque la zona es un dominio compartido y el valor llega de una variable de Actions editable sin revisión: sin ese límite, cambiarla podría redirigir un hostname ajeno al túnel de este entorno.
- WHEN `var.public_hostname` o `var.cloudflare_zone_name` no cumplen lo anterior, THE SYSTEM SHALL rechazar el `plan` en la validación de variables.

### El contenedor del túnel (`docker-compose.deploy.yml`)

- THE SYSTEM SHALL declarar un servicio `cloudflared` con la imagen oficial **pineada por dígest** del índice multi-arch (incluye `linux/arm64`, la arquitectura de la instancia), `command: tunnel --no-autoupdate run`, `restart: unless-stopped`, **sin `ports` publicados** y **sin acceso al socket de Docker**.
- THE SYSTEM SHALL fijar `TUNNEL_METRICS` en loopback y declarar el healthcheck como `["CMD","cloudflared","tunnel","ready"]`: la imagen es distroless —sin shell, `curl` ni `wget`— así que el propio binario consulta su endpoint de métricas y solo devuelve 0 con conexión establecida al edge.
- THE SYSTEM SHALL declarar `depends_on: frontend: {condition: service_healthy}`, para no anunciar al edge un origen que todavía no responde.
- WHEN `docker compose up -d --wait` termina, THE SYSTEM SHALL considerar el deploy exitoso solo si `cloudflared` queda `healthy`.
- El servicio `cloudflared` comparte hoy la red `default` del compose con `postgres`, `redis` y `backend`, por lo que puede resolver sus nombres. Combinado con el routing remoto, esto amplía el radio de daño del API token más allá de lo que describe el ADR 0003; **su aislamiento en una red dedicada es el objeto del change `ingress-https-hardening`**.

### El secreto del túnel y su lectura en el deploy

- THE SYSTEM SHALL guardar el token del túnel como `oci_vault_secret` de nombre `autohostai-<env>-cloudflare-tunnel-token`, con contenido en BASE64, generado íntegramente por Terraform.
- WHEN el job `deploy` renderiza el `.env` de runtime, THE SYSTEM SHALL leer ese secreto del Vault **por nombre** (`get-secret-bundle-by-name`, con el OCID del Vault desde una variable de repositorio) por instance principal, y THE SYSTEM SHALL fallar el deploy nombrando la clave si no puede leerlo, **antes de tocar contenedores**.
- THE SYSTEM SHALL resolver por nombre y no por OCID porque `cloud-init` escribe `/etc/autohostai-deploy.env` solo al crear la VM: el `metadata` de la instancia es ForceNew y lleva `ignore_changes`, así que una clave añadida después nunca llegaría a la máquina viva.
- THE SYSTEM SHALL autorizar esa lectura ampliando `oci_identity_policy.dev_runner_read_secrets` con el OCID del secreto en su condición `where any {...}`, más un statement de lectura de metadatos que la resolución por nombre necesita. El acceso al **contenido** de los secretos queda acotado por la enumeración explícita de OCID; un secreto nuevo es invisible para el runner hasta añadirlo.
- THE SYSTEM SHALL NOT copiar el API token de Cloudflare al Vault ni a ningún almacén que lo lleve al `tfstate`: su radio de daño abarca toda la zona y es re-emitible en segundos, así que una copia no aporta recuperación y sí amplía la exposición. Terraform no persiste configuración de provider, de modo que sin esa copia el token no llega al estado.
- WHERE el secreto del túnel reside en el `tfstate`, THE SYSTEM SHALL ampararse en la excepción dev/test de `steering/security.md` §8 sin extenderla a staging/prod: su radio es este entorno, pues solo permite servir tráfico de ese túnel.

### Superficie de red de la VM

- THE SYSTEM SHALL mantener el security list de la subred con **un único puerto de entrada, el 22**, acotado a `var.allowed_ssh_cidrs` con validación de prefijo `>= /24`, y THE SYSTEM SHALL NOT declarar ninguna regla de ingress con origen `0.0.0.0/0`.
- THE SYSTEM SHALL NOT publicar los puertos de `backend` y `frontend` en ninguna interfaz externa de la VM. WHERE se publican para depuración, THE SYSTEM SHALL acotarlos a `127.0.0.1`, de modo que no sean alcanzables desde internet ni desde la VCN y solo lleguen a ellos quien ya tenga acceso SSH.
- WHEN un operador necesita ver la aplicación sin pasar por Cloudflare —la única forma de distinguir un fallo de la app de uno del edge o del túnel—, THE SYSTEM SHALL permitirlo mediante reenvío de puerto local por SSH (`ssh -L`), sin abrir nada en el security list.

### Credenciales y configuración

- THE SYSTEM SHALL exponer el hostname público, el apex de la zona y el account ID como variables no sensibles, y el API token y el zone ID como variables `sensitive`, ninguna con `default`.
- THE SYSTEM SHALL consumir el API token y el zone ID en CI desde GitHub Secrets, y el resto desde variables de repositorio, inyectados como `TF_VAR_*` en los jobs `plan` y `apply` — nunca en el job `check`, que corre en `pull_request` sin secretos.
- THE SYSTEM SHALL acotar el job `plan` a `main` igual que el `apply`, porque recibe un token con control del DNS y del TLS de toda la zona y `sensitive = true` no impide desredactarlo desde código de una rama no revisada. Consecuencia operativa: el `plan` de un change de infra se ejecuta tras el merge.
- THE SYSTEM SHALL NOT versionar el API token, el secreto o token del túnel, el zone ID ni el ID del túnel.

## Key files

- `infra/environments/dev/main.tf` — túnel, routing, CNAME, `precondition`, ajuste de zona, secreto del Vault, policy del runner, `local.ingress_ports`.
- `infra/environments/dev/variables.tf` — variables de Cloudflare y las dos `validation` del hostname.
- `docker-compose.deploy.yml` — servicio `cloudflared` y el binding a loopback de `backend`/`frontend`.
- `.github/workflows/deploy-dev.yml` — lectura del token por nombre y renderizado del `.env`.
- `.github/workflows/infra-dev.yml` — gating por rama de `plan` y `apply`.
- `docs/adr/0003-https-ingress-dev.md` — decisión y alternativas descartadas.
- `infra/environments/dev/RUNBOOK.md` §7 — bootstrap del token, diagnóstico, rotación y depuración por túnel SSH.
- `docs/ingress-https.md` — cómo se usa y se opera la capability.

## Estado y pendientes

- **Operativo y verificado en producción** (2026-07-29): HTTPS sirviendo la app con certificado válido, redirección desde HTTP, security list en `[22]`, acceso directo a la IP en 3000/8000 sin conectar, y depuración por `ssh -L` funcionando.
- El **bootstrap irreducible** de Cloudflare —el dominio con su zona y el API token del provider— se hace a mano una vez y está documentado en `steering/infra.md`.
- **Pendiente en `ingress-https-hardening`**: aislar `cloudflared` en una red de compose dedicada, acotar el statement de lectura de metadatos de la policy, y corregir el radio de daño documentado del API token.
- **Sin verificar por comportamiento**: que la catch-all devuelva 404. La regla existe en el estado aplicado, pero observarla exigiría un hostname desechable apuntando al túnel.
- **Riesgo a vigilar**: la zona la gestionan además dos instancias de `external-dns` en `policy = "sync"`. El CNAME de Terraform no lleva su TXT de propiedad, así que en teoría no lo tocan; conviene confirmar que persiste.
