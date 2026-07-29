# Verificación — ingress-https-dev (tarea 8.6)

Repaso de los **31 criterios** de los 6 requisitos del `proposal.md` contra la implementación desplegada. Fecha: **2026-07-29**. Estado del entorno: `https://autohostai.digitalsec.work` sirviendo la app por Cloudflare Tunnel, con `local.ingress_ports = [22]`.

Runs de referencia: `infra-dev` apply de fase A **30476015034**, deploy **30476283146**, `infra-dev` apply de fase B **30479130290**.

## R1 — Túnel, routing y DNS declarados como código

| # | Evidencia | |
|---|---|---|
| 1 | `cloudflare_zero_trust_tunnel_cloudflared.dev` con `config_src = "cloudflare"` y `tunnel_secret = random_bytes.tunnel_secret.base64`. Creado en el apply: `id=5c587f7c-d343-4534-83dc-4113034e03b1` | ✅ |
| 2 | `terraform state show` del `_config` muestra `ingress = [{hostname="autohostai.digitalsec.work", service="http://frontend:3000"}, {service="http_status:404"}]` — catch-all presente y última | ✅ |
| 3 | `cloudflare_dns_record.app`: CNAME a `${…dev.id}.cfargotunnel.com`, `proxied = true`. `dig +short autohostai.digitalsec.work` → `104.21.90.5`, `172.67.167.124` (IPs del edge, confirma el proxy). Ningún id literal en el repo | ✅ |
| 4 | `version = "~> 5.0"` en `required_providers`; `.terraform.lock.hcl` versionado con `cloudflare/cloudflare 5.22.0` y hashes de `darwin_arm64` + `linux_amd64` | ✅ |
| 5 | `terraform plan` sin las variables de Cloudflare falla con 5 bloques `No value for required variable`, nombrando cada una, y sin escribir estado | ✅ |
| 6 | El token se **deriva** en `local.tunnel_token` de `account_tag` + `id` + secreto; el CNAME se deriva del `id` del recurso. Ningún valor copiado del dashboard | ✅ |

## R2 — El deploy arranca `cloudflared` con el secreto leído del Vault

| # | Evidencia | |
|---|---|---|
| 1 | `oci_vault_secret.cloudflare_tunnel_token` creado (`amaaaaaa2r32b6yatky4l5ipbavbdyzjczbdmydgjxb672zz34l2zpyisrsa`), contenido `base64encode(local.tunnel_token)`. Sin paso manual | ✅ |
| 2 | Deploy **30476283146**: el paso "Render .env" pasó leyendo por nombre con instance principal. Antes, en **30475510352**, falló con el mensaje esperado (`no se pudo leer del Vault el secret requerido: TUNNEL_TOKEN`) **sin tocar contenedores** — los pasos de login y `up` quedaron sin ejecutar | ✅ |
| 3 | `docker-compose.deploy.yml`: imagen `cloudflare/cloudflared@sha256:e39ee8da…` (índice multi-arch, `linux/arm64` verificado), `restart: unless-stopped`, sin `ports`, sin `/var/run/docker.sock` (0 apariciones en el fichero) | ✅ |
| 4 | El deploy usa `up -d --wait`, que exige `healthy` en todos los servicios, y salió verde → `cloudflared` está `healthy`. El healthcheck es `["CMD","cloudflared","tunnel","ready"]` con `TUNNEL_METRICS` fijado | ✅ |
| 5 | `depends_on: frontend: {condition: service_healthy}` | ✅ |

## R3 — HTTPS forzado en el edge

| # | Evidencia | |
|---|---|---|
| 1 | `curl -sSI http://autohostai.digitalsec.work` → `301 Moved Permanently`, `Location: https://autohostai.digitalsec.work/` | ✅ |
| 2 | `cloudflare_zone_setting.always_use_https = "on"` declarado y aplicado (valor previo verificado por API: `off`). `min_tls_version` **deliberadamente no declarado**, se queda en 1.0 — decisión registrada en D7 tras inventariar la zona | ✅ |
| 3 | HTTPS sirve la app (`<title>AutoHostAI</title>`, bundle `_next/static`) con certificado de Google Trust Services para `digitalsec.work`, válido hasta 2026-09-07. Ningún certificado gestionado en el origen | ✅ |
| 4 | `autohostai.digitalsec.work` es una sola etiqueta bajo el apex. La `validation` de `public_hostname` lo hace cumplir en el `plan`: probada en `terraform console`, acepta `autohostai` y `autohostai-staging`, rechaza apex desnudo, wildcard, `dev.autohostai.…`, mayúsculas y guion final | ✅ |

## R4 — Cierre del acceso HTTP directo, secuenciado

| # | Evidencia | |
|---|---|---|
| 1 | `local.ingress_ports = [22]`. Apply de fase B: `Plan: 0 to add, 1 to change, 0 to destroy`, solo `oci_core_security_list.dev_public` in-place. `http://79.76.101.10:3000` y `:8000` → **timeout** | ✅ |
| 2 | El 22 sigue acotado a `var.allowed_ssh_cidrs` con su `validation` de prefijo `>= /24` intacta. Cero reglas con `0.0.0.0/0`. SSH verificado con una sesión real | ✅ |
| 3 | `backend` y `frontend` publican **solo** en `127.0.0.1` (`docker compose config` → `host_ip = 127.0.0.1` en ambos; ningún puerto en interfaz externa). Puerta de depuración verificada: por `ssh -L` el frontend devuelve `307` y el backend `{"status":"ok"}`; al cerrar la sesión no queda listener | ✅ |
| 4 | El orden se respetó: la fase A se aplicó y verificó (`301`, app servida, y `530/1033` antes del deploy probando que la ruta es edge→túnel→frontend) **antes** de mergear el PR #24 de la fase B, cuya descripción recoge esa evidencia | ✅ |

## R5 — Configuración inyectada, secretos fuera del repo

| # | Evidencia | |
|---|---|---|
| 1 | `public_hostname` es variable sin `default`; valor de dev documentado en `dev.tfvars.example` y en el `README.md` | ✅ |
| 2 | `cloudflare_api_token` y `cloudflare_zone_id` con `sensitive = true`, en el `.example` solo como marcador comentado (comentado a propósito: un placeholder activo retrasaría el fallo hasta un error de auth confuso en vez del claro "No value for required variable") | ✅ |
| 3 | `TF_VAR_cloudflare_api_token` ← `secrets.CLOUDFLARE_API_TOKEN` en los jobs `plan` y `apply`; el job `check` no recibe ninguna | ✅ |
| 4 | `terraform state list`: 5 `oci_vault_secret` y **ninguno** es el API token. Su única referencia es el bloque `provider`, y Terraform no persiste configuración de provider en el estado | ✅ |
| 5 | El `.env` de runtime solo recibe `TUNNEL_TOKEN`; el API token no aparece en `deploy-dev.yml` ni en `cloud-init` | ✅ |
| 6 | `TUNNEL_TOKEN=` sin valor en `.env.deploy.example`, con el comentario de que lo renderiza el CD desde el Vault | ✅ |
| 7 | `git ls-files` no versiona `*.tfvars`, `*.tfstate` ni `backend.hcl`; grep del diff del change sin literales sospechosos | ✅ |
| 8 | El `tfstate` gana **un** secreto (el del túnel), cuyo radio es este entorno. Excepción §8 invocada sin ampliarla | ✅ |
| 9 | `validation` con prefijo `autohostai*` probada: rechaza `www`, `mail`, `api`, `notautohostai` | ✅ |

## R6 — Operación y bootstrap documentados

| # | Evidencia | |
|---|---|---|
| 1 | `RUNBOOK.md` §7 (380 líneas en total): bootstrap con los tres permisos del token y el aviso "Cloudflare Tunnel ≠ Zero Trust", diagnóstico con tabla síntoma→causa, rotación del secreto, y §7.4 completa de depuración con árbol de decisión app/túnel/edge | ✅ |
| 2 | `steering/infra.md` añade al bootstrap irreducible el dominio y su zona DNS, y el API token con sus permisos mínimos y el motivo de no copiarlo al Vault | ✅ |
| 3 | `docs/adr/0003-https-ingress-dev.md` con las tres alternativas descartadas, tabla de criterios, y la restricción de Universal SSL para el naming futuro | ✅ |
| 4 | `README.md` con la URL pública y la nota de que 8000/3000 ya no están expuestos | ✅ |
| 5 | `steering/infra.md` registra como decisión estable que el `apply` no se protege con GitHub Environment, para que su ausencia no se reabra como hallazgo | ✅ |

## Verificación de estado final

- `terraform fmt -check -diff` sin diferencias; `terraform validate` OK; job `check` de CI en verde en el PR.
- `terraform plan` posterior al último apply: **`No changes`** — sin deriva entre código y realidad (tarea 8.4).
- `docker compose config` válido, `cloudflared` sin puertos, `backend`/`frontend` solo en loopback.

## Salvedades honestas

**5.2 cerrada con evidencia estructural, no de comportamiento.** La regla catch-all está en el estado aplicado, pero no se probó que un hostname no previsto devuelva 404. Habría exigido crear un CNAME público desechable en una zona con servicios reales, y lo único que añadiría es confirmar que Cloudflare honra su propia semántica documentada — verifica al proveedor, no a este change.

**Riesgo residual a vigilar (no bloquea el archivado).** La zona `digitalsec.work` la gestionan además **dos instancias de `external-dns` en `policy = "sync"`** (`owner=default` del homelab y `owner=gke-carto…`). En teoría el CNAME de Terraform está a salvo porque `external-dns` solo borra registros que llevan su TXT de propiedad, y el nuestro no lo tiene. Conviene confirmar en los próximos días que el registro sigue en pie; si desapareciera, el síntoma sería la app inalcanzable y Terraform recreándolo en el siguiente `apply`.

**El panel de revisión solo ha visto la sección 1.** Las secciones 2, 3, 4, 6 y 7 no pasaron por panel porque ninguna podía cerrarse sin `apply` real. Lo cubre `/sdd:review ingress-https-dev` a escala de feature, que es el paso siguiente antes de archivar.
