# Design: ingress-https-dev

## Context

La infra de dev es un único root module de Terraform en `infra/environments/dev/` con **solo el provider `oci`** (más `hashicorp/random`), que declara red, instancia Ampere A1, budget, Vault + master key, y cuatro secretos (`oci_vault_secret.{postgres_password,jwt_secret_key,encryption_key,github_app_key}`). El runner self-hosted los lee por instance principal gracias a `oci_identity_dynamic_group.dev_runner` + `oci_identity_policy.dev_runner_read_secrets` (`main.tf:175-189`), cuya policy **enumera los OCID concretos** de los secretos permitidos.

El CD (`.github/workflows/deploy-dev.yml`) construye imágenes arm64 en `ubuntu-latest`, las publica en GHCR y el job `deploy` corre en la VM (`runs-on: [self-hosted, dev]`), donde renderiza `.env` leyendo del Vault los OCID que obtiene de `/etc/autohostai-deploy.env`. Ese fichero lo escribe **cloud-init** (`cloud-init.yaml.tftpl:25-37`), y la instancia declara `lifecycle { ignore_changes = [metadata] }` porque `metadata` es ForceNew en el provider `oci` — es decir, **Terraform no puede reescribir ese fichero en la VM viva**.

`docker-compose.deploy.yml` publica hoy `8000:8000` y `3000:3000`, y `local.ingress_ports = [22, 8000, 3000]` (`main.tf:26`) abre esos puertos acotados a `var.allowed_ssh_cidrs`. El frontend habla con el backend server-side por `BACKEND_INTERNAL_URL`; `frontend/lib/config/public.ts` excluye a propósito esa URL del bundle del navegador, así que el backend no necesita hostname público.

## Decisions

### D1 — El provider `cloudflare` vive en el mismo root module que `oci`

**Chosen:** añadir `cloudflare/cloudflare` a `required_providers` de `infra/environments/dev/main.tf`, compartiendo state con los recursos OCI. No es una preferencia estética: el `oci_vault_secret` del token del túnel **depende de atributos de recursos Cloudflare** (`account_tag`, `id`), así que ambos tienen que estar en el mismo grafo para que Terraform resuelva la dependencia en un solo `apply`.

Rejected: root module aparte para Cloudflare — obligaría a pasar el token entre states (`terraform_remote_state` o variable manual), reintroduciendo el copiar-valores-a-mano que R1.6 prohíbe.
Rejected: recurso `cloudflare_*` en un `infra/modules/` compartido — todavía no hay un segundo entorno que justifique el módulo (`steering/infra.md`: los módulos se crean cuando hay algo real que compartir).

### D2 — El token del túnel se **deriva** en Terraform, no se lee de un atributo

**Chosen:** el provider v5 no expone atributo `token` en `cloudflare_zero_trust_tunnel_cloudflared`; solo acepta `tunnel_secret` de entrada. Se genera con `random_bytes` (32 bytes, base64) y el token que consume `cloudflared` se compone:

```hcl
local.tunnel_token = base64encode(jsonencode({
  a = cloudflare_zero_trust_tunnel_cloudflared.dev.account_tag,
  t = cloudflare_zero_trust_tunnel_cloudflared.dev.id,
  s = random_bytes.tunnel_secret.base64,
}))
```

Es el mismo patrón ya usado para la clave Fernet (`main.tf:279-283`): `random_bytes` + un `local` que la transforma al formato que espera el consumidor.

Rejected: `config_src = "local"` con ficheros de credenciales — mismo contenido, pero exige montar un JSON en la VM en lugar de una variable de entorno, y la configuración de ingress dejaría de ser declarable en Terraform.
Rejected: acuñar el token en el dashboard y ponerlo como GitHub Secret — viola R1.6 y la norma IaC-first.

### D3 — El OCID del nuevo secreto llega al deploy **resolviéndolo por nombre**, no editando la VM

**Chosen:** el job `deploy` obtiene el bundle con `oci secrets secret-bundle get-secret-bundle-by-name --secret-name autohostai-dev-cloudflare-tunnel-token --vault-id "$OCI_VAULT_ID"`, tomando `OCI_VAULT_ID` de una variable de repo (`vars.OCI_VAULT_ID`). Motivo: `/etc/autohostai-deploy.env` lo escribe cloud-init y `ignore_changes = [metadata]` impide que Terraform lo actualice en la VM viva; resolver por nombre **elimina el paso manual de este change y de todos los futuros**, porque el nombre del secreto sí es determinista (`autohostai-${var.env}-...`).

Los nombres se mantienen en cloud-init para una VM nueva, de modo que el aprovisionamiento desde cero sigue siendo 100 % IaC.

Rejected: editar `/etc/autohostai-deploy.env` a mano en la VM (precedente de RUNBOOK §6) — funciona, pero añade un paso manual recurrente cada vez que se sume un secreto, justo lo que la norma IaC-first quiere erradicar.
Rejected: recrear la instancia para que cloud-init se reaplique — destruye los volúmenes de postgres/redis; desproporcionado.

### D4 — La policy IAM se amplía al nuevo secreto; sin ampliarla el deploy falla

**Chosen:** añadir `oci_vault_secret.cloudflare_tunnel_token.id` a la lista `where any {...}` de `oci_identity_policy.dev_runner_read_secrets` (`main.tf:187`). La policy es una enumeración explícita de OCID, así que un secreto nuevo es **invisible** para el runner hasta que se añade — es la causa de fallo más probable de este change.

Resolver por nombre (D3) requiere además `read secrets` sobre el compartment (no solo `read secret-bundles`) para listar/resolver el nombre; se añade como statement separado acotado al compartment, y queda reflejado en `iam-policy.md`.

Rejected: `Allow ... to read secret-bundles in compartment` sin condición — daría acceso a todo secreto presente y futuro del compartment, rompiendo el mínimo privilegio que la spec exige.

### D5 — Healthcheck de `cloudflared` con su propio subcomando

**Chosen:** la imagen oficial es distroless (sin shell, `curl` ni `wget`), pero `cloudflared` trae el subcomando `tunnel ready`, que consulta su endpoint de métricas. Se fija `TUNNEL_METRICS: 127.0.0.1:2000` y el healthcheck es `test: ["CMD", "cloudflared", "tunnel", "ready"]`. Así R2.4 se cumple sin construir imagen propia.

Rejected: imagen propia con `curl` — añade cadena de suministro que mantener, exactamente el coste por el que se descartó Caddy en el ADR 0003.
Rejected: sin healthcheck, verificando solo por `curl` externo desde el runner — se pierde el fallo temprano de `up -d --wait`; la verificación externa se añade **además** (ver D6), no en su lugar.

### D6 — El cierre de puertos va en un `apply` posterior, con verificación externa entre medias

**Chosen:** R4 se implementa en **dos fases separadas**, no en un único `apply`:

1. Fase A: túnel + DNS + `cloudflared` en el compose + secreto y policy. `local.ingress_ports` sigue en `[22, 8000, 3000]` y el compose sigue publicando puertos.
2. Verificación: `curl -sSf https://autohostai.digitalsec.net` devuelve 200 desde fuera de los CIDRs de operador, y `cloudflared` está `healthy`.
3. Fase B: `local.ingress_ports = [22]` y se quitan los `ports` de backend/frontend en el compose.

Motivo: cerrar antes de verificar deja la app inalcanzable por ambas vías a la vez. El 22 nunca se toca, así que SSH sigue siendo la red de seguridad.

Rejected: un solo `apply` con todo — si el túnel no levanta, se pierde el acceso HTTP directo al mismo tiempo y el diagnóstico se complica.

### D7 — Ajustes de HTTPS de zona: alcance mínimo

**Chosen:** declarar únicamente el forzado de HTTPS y el TLS mínimo (R3.1, R3.2) como recursos de ajuste de zona del provider. Son ajustes **de zona**, no de hostname: afectan a todo `digitalsec.net`, no solo a `autohostai`.

**Consecuencia aceptada explícitamente (2026-07-29):** `digitalsec.net` es el dominio personal de Jose y aloja otros servicios (el homelab publica ahí con external-dns + cert-manager). Forzar HTTPS y TLS mínimo 1.2 **también les aplica**. Se acepta a sabiendas: es la postura deseable para todos ellos. Si algún servicio de esa zona necesitara HTTP en claro en el futuro, este ajuste es lo primero que hay que revisar.

Rejected: no tocar los ajustes de zona y confiar en los valores actuales — dejaría R3.1/R3.2 sin evidencia verificable.
Rejected: ajustes por hostname — Cloudflare no los ofrece con esa granularidad en el plan Free.

### D8 — Sin cambios en la aplicación

**Chosen:** ni backend ni frontend cambian. El túnel entrega a `frontend:3000` por la red interna y Next sigue sirviendo con `HOSTNAME=0.0.0.0`. `NEXT_PUBLIC_*` no se toca, porque nada del bundle del navegador depende del hostname público.

Único matiz a vigilar en `/sdd:run`: al pasar por el proxy de Cloudflare, la IP del cliente llega en `CF-Connecting-IP` y el esquema en `X-Forwarded-Proto`. Hoy no hay lógica que lea IP ni esquema, así que no hay nada que adaptar; queda anotado como `ASSUMPTION` para cuando llegue `auth-tenancy` (rate limiting por IP, `security.md` regla 7).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Terraform — providers | `infra/environments/dev/main.tf` | `required_providers` += `cloudflare/cloudflare` con constraint; bloque `provider "cloudflare"` con `api_token = var.cloudflare_api_token` |
| Terraform — túnel | `infra/environments/dev/main.tf` | `random_bytes.tunnel_secret`, `cloudflare_zero_trust_tunnel_cloudflared.dev` (`config_src = "cloudflare"`), `cloudflare_zero_trust_tunnel_cloudflared_config.dev` (ingress → `http://frontend:3000` + catch-all `http_status:404`), `local.tunnel_token` |
| Terraform — DNS y zona | `infra/environments/dev/main.tf` | `cloudflare_dns_record.app` (CNAME → `<tunnel_id>.cfargotunnel.com`, `proxied = true`), recursos de ajuste de zona (HTTPS forzado, TLS mín. 1.2) |
| Terraform — secretos e IAM | `infra/environments/dev/main.tf` | `oci_vault_secret.cloudflare_tunnel_token`; `oci_identity_policy.dev_runner_read_secrets` amplía la lista de OCID y añade statement de `read secrets` |
| Terraform — interfaz | `infra/environments/dev/variables.tf`, `outputs.tf`, `dev.tfvars.example` | vars `cloudflare_api_token` (sensitive), `cloudflare_zone_id` (sensitive), `cloudflare_account_id`, `public_hostname`; output `public_url`; `.example` con `autohostai.digitalsec.net` y marcadores sin valor |
| Terraform — cierre (fase B) | `infra/environments/dev/main.tf` | `local.ingress_ports` → `[22]` |
| CI — infra | `.github/workflows/infra-dev.yml` | `TF_VAR_cloudflare_api_token`, `TF_VAR_cloudflare_zone_id` desde secrets; `TF_VAR_cloudflare_account_id`, `TF_VAR_public_hostname` desde vars — en los jobs `plan` y `apply` |
| CD — deploy | `.github/workflows/deploy-dev.yml` | leer el token del túnel del Vault **por nombre** y volcarlo al `.env` como `TUNNEL_TOKEN`; tras `up --wait`, verificación externa `curl -sSf https://<hostname>` |
| Compose de deploy | `docker-compose.deploy.yml` | servicio `cloudflared` (imagen pineada, `TUNNEL_TOKEN`, `TUNNEL_METRICS`, healthcheck `tunnel ready`, `depends_on: frontend: service_healthy`, sin `ports`); fase B: quitar `ports` de backend y frontend |
| Aprovisionamiento | `infra/environments/dev/cloud-init.yaml.tftpl` | añadir el nombre/OCID del secreto del túnel para que una VM nueva arranque completa |
| Docs | `RUNBOOK.md`, `README.md`, `iam-policy.md`, `sdd/steering/infra.md`, `docs/adr/0003-https-ingress-dev.md` | diagnóstico y rotación del túnel; URL pública; policy actualizada; bootstrap irreducible (zona + API token) y decisión de no usar GitHub Environment; ADR con las cuatro alternativas |

## Data & interfaces

**Nuevas variables de Terraform** (`variables.tf`): `cloudflare_api_token` (string, sensitive), `cloudflare_zone_id` (string, sensitive), `cloudflare_account_id` (string), `public_hostname` (string, con `validation` que exija exactamente una etiqueta bajo el apex — hace cumplir R3.4 en el `plan`, no en revisión).

**Nuevo secreto del Vault**: `autohostai-dev-cloudflare-tunnel-token`, `content_type = "BASE64"`, contenido `base64encode(local.tunnel_token)` — nótese que el token ya es base64, así que el contenido queda doblemente codificado, igual que los demás secretos del fichero (el deploy hace `base64 -d` una vez y obtiene el token tal cual lo espera `cloudflared`).

**Nueva variable de entorno de runtime**: `TUNNEL_TOKEN` en el `.env` que renderiza el CD, documentada sin valor en `.env.deploy.example`.

**Nuevos secrets/vars de GitHub**: secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`; variables `CLOUDFLARE_ACCOUNT_ID`, `PUBLIC_HOSTNAME`, `OCI_VAULT_ID`.

**Sin cambios** de esquema de base de datos, contratos de API ni entidades de dominio.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **La policy IAM no cubre el secreto nuevo** → el deploy falla al leer el Vault (causa de fallo más probable) | D4 lo hace parte del mismo `apply`; el paso de verificación del deploy falla nombrando la clave antes de tocar contenedores (R2.2) |
| **Los ajustes de zona afectan a todo `digitalsec.net`**, incluido lo que ya publiques ahí | Pregunta abierta Q1 antes de implementar; si hay conflicto, se limita el alcance |
| Permisos del API token insuficientes (`Cloudflare Tunnel` es de **cuenta**, no de zona, y no está bajo "Zero Trust") | El `plan` falla temprano y de forma legible; el conjunto exacto queda en el RUNBOOK |
| Cerrar puertos con el túnel roto deja la app inalcanzable | D6: dos fases con verificación externa entre medias; el 22 nunca se cierra |
| `cloudflared` sano pero el frontend caído → el edge devuelve 502 | `depends_on: frontend: service_healthy` (R2.5) y verificación externa end-to-end |
| Un `terraform destroy`/recreación del túnel deja el CNAME apuntando a un túnel muerto | El CNAME depende del `id` del túnel, así que Terraform lo reconcilia en el mismo `apply` |
| El `tfstate` gana un secreto más en claro | Cubierto por la excepción dev/test de `security.md`; bucket privado + versionado + IAM mínima |

## Open questions

Ninguna abierta. Las tres que planteó este diseño se resolvieron en el gate del **2026-07-29**:

1. **Alcance de los ajustes de HTTPS de zona** → aplicar a todo `digitalsec.net`, aceptando el efecto sobre los demás servicios de la zona. Registrado en D7.
2. **¿Fase B dentro del change?** → **sí**, tal como la describe D6: fase A, verificación externa, fase B. El change queda autoconclusivo y R4 se cumple aquí.
3. **Paso del hostname a Terraform** → **variable de GitHub** `PUBLIC_HOSTNAME` cableada como `TF_VAR_public_hostname`. Sin `default` en `variables.tf`: ningún valor de entorno concreto entra en el código, conforme a R5.1. La `validation` de una sola etiqueta bajo el apex (R3.4) se mantiene.
