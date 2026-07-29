# Tasks: ingress-https-dev

Orden pensado para que el sistema quede funcionando tras cada sección. Las secciones 1-4 son la **fase A** de D6 (el túnel se suma al acceso HTTP existente, sin quitarle nada); la sección 5 produce la evidencia que R4.4 exige; solo entonces la sección 6 ejecuta la **fase B** y cierra los puertos.

**Nota sobre tests**: este change no toca código de aplicación (D8), así que los tipos de test de `steering/testing.md` (pytest, Testing Library, Playwright) no aplican. La verificación es de infraestructura: `fmt`/`validate` en PR, `plan`/`apply` reales, healthcheck del contenedor y comprobación HTTPS externa. Cada tarea dice qué evidencia la cierra.

## 1. Interfaz de Terraform y cableado de CI <!-- panel: PASS 2026-07-29 (architect, security, qa, cicd; 4 hallazgos aceptados y corregidos: marcadores en dev.tfvars.example, radio del API token → D10, gating de rama en el job plan, prefijo autohostai en public_hostname → R5.9) -->

Tras esta sección `plan` sigue verde y **no cambia ningún recurso real**: solo entran variables, el provider y su paso por CI.

- [x] 1.1 Declarar las variables nuevas en `infra/environments/dev/variables.tf`: `cloudflare_api_token` y `cloudflare_zone_id` (`sensitive = true`), `cloudflare_account_id`, `cloudflare_zone_name` (el apex, ver D9) y `public_hostname` **con `validation` de dos reglas**: (a) exactamente una etiqueta bajo el apex — R3.4 se hace cumplir en el `plan`, no en revisión; (b) esa etiqueta debe empezar por `autohostai`, porque la zona es compartida y el valor llega de una variable de Actions editable sin PR (R5.9, hallazgo del panel). Sin `default` en ninguna. [R3.4, R5.1, R5.2, R5.9]
- [x] 1.2 Añadir `cloudflare/cloudflare` a `required_providers` en `infra/environments/dev/main.tf` con constraint de versión mayor explícito, declarar `provider "cloudflare" { api_token = var.cloudflare_api_token }`, y regenerar `.terraform.lock.hcl` de modo que quede **versionado** con los hashes del provider. [R1.4]
- [x] 1.3 Rellenar `infra/environments/dev/dev.tfvars.example`: `public_hostname = "autohostai.digitalsec.net"` con valor real (es público), y `cloudflare_api_token` / `cloudflare_zone_id` / `cloudflare_account_id` solo como marcadores sin valor. [R5.1, R5.2]
- [x] 1.4 Cablear las variables en los jobs `plan` y `apply` de `.github/workflows/infra-dev.yml`: `TF_VAR_cloudflare_api_token` y `TF_VAR_cloudflare_zone_id` desde `secrets`, `TF_VAR_cloudflare_account_id` y `TF_VAR_public_hostname` desde `vars`. El job `check` no recibe ninguna (sigue sin secretos, `init -backend=false`). [R5.3]
- [x] 1.5 Verificar que un `plan` sin las credenciales de Cloudflare **falla nombrando la variable ausente** y no deja recursos a medias; evidencia: log del `plan` o `terraform validate` local mostrando el error de variable requerida. [R1.5]

## 2. Túnel, DNS y el secreto del túnel en el Vault

Tras esta sección el túnel y su DNS existen en Cloudflare, y **el token del túnel** está en el Vault. Nadie lo consume todavía: la app sigue sirviéndose igual que antes por 8000/3000.

**Al Vault va exactamente un secreto nuevo: el del túnel.** El API token de Cloudflare **no** se copia — R5.4 lo prohíbe y D10 explica por qué (radio de zona completa, y es re-emitible en segundos). No reintroducir esa copia.

- [x] 2.1 Crear `random_bytes.tunnel_secret` (32 bytes) y `cloudflare_zero_trust_tunnel_cloudflared.dev` con `config_src = "cloudflare"`, `account_id = var.cloudflare_account_id` y `tunnel_secret` desde el recurso random — nunca un valor escrito a mano. Ficheros: `infra/environments/dev/main.tf`. [R1.1]
- [x] 2.2 Crear `cloudflare_zero_trust_tunnel_cloudflared_config.dev` con dos reglas de ingress: `hostname = var.public_hostname` → `service = "http://frontend:3000"`, y una **catch-all final** `service = "http_status:404"` para cualquier hostname no previsto. Ficheros: `infra/environments/dev/main.tf`. [R1.2]
- [x] 2.3 Crear `cloudflare_dns_record.app`: `type = "CNAME"`, nombre derivado de `var.public_hostname`, `content = "${cloudflare_zero_trust_tunnel_cloudflared.dev.id}.cfargotunnel.com"`, `proxied = true`. El ID del túnel viene del recurso, nunca literal. Ficheros: `infra/environments/dev/main.tf`. [R1.3, R1.6]
- [x] 2.4 Cerrar la deuda de las dos fuentes de verdad de la zona (D9, opción 2): añadir `data "cloudflare_zone"` resuelto por `var.cloudflare_zone_id` y un `lifecycle { precondition }` en `cloudflare_dns_record.app` que exija `data.cloudflare_zone...name == var.cloudflare_zone_name`. Sin esto, un `cloudflare_zone_name` desincronizado del `zone_id` deja pasar la validación de profundidad y el hostname acaba fuera del Universal SSL con aviso de certificado (demostrado por el panel de seguridad). Ficheros: `infra/environments/dev/main.tf`. [R3.4, R1.5]
- [x] 2.5 Añadir `local.tunnel_token = base64encode(jsonencode({a = ...account_tag, t = ...id, s = random_bytes.tunnel_secret.base64}))` y el recurso `oci_vault_secret.cloudflare_tunnel_token` (`secret_name = "autohostai-${var.env}-cloudflare-tunnel-token"`, `content_type = "BASE64"`), siguiendo el patrón exacto de `oci_vault_secret.jwt_secret_key`. Ficheros: `infra/environments/dev/main.tf`. [R2.1, D2]
- [x] 2.6 **Ampliar `oci_identity_policy.dev_runner_read_secrets`** (`main.tf:187`) para incluir el OCID de `oci_vault_secret.cloudflare_tunnel_token` en la condición `where any {...}`, y añadir el statement de `read secrets` acotado al compartment que la resolución por nombre necesita. Sin esto el runner **no puede leer el secreto** y el deploy falla. Ficheros: `infra/environments/dev/main.tf`. [R2.2, D4]
- [x] 2.7 Añadir `output "public_url"` con `https://${var.public_hostname}` en `infra/environments/dev/outputs.tf`. [R5.1]
- [ ] 2.8 Confirmar que el API token de Cloudflare **no** aparece en el `tfstate` tras el `apply` (R5.4): no existe ningún recurso que lo persista y Terraform no guarda configuración de provider. Evidencia: `terraform show -json | grep -c` del token, o inspección del state por nombre de recurso. [R5.4]
- [ ] 2.9 Ejecutar `plan` y luego `apply` reales por `workflow_dispatch` **desde `main`** (el job `plan` quedó acotado a `main`, ver BLOCKED.md #2) y confirmar en el log que se crean túnel, config, CNAME, el secreto del túnel y la policy ampliada, sin recrear la instancia (`oci_core_instance.dev` no debe aparecer en el plan). [R1.1, R1.2, R1.3]

## 3. HTTPS forzado en la zona

- [x] 3.1 Declarar como código los ajustes de zona de `digitalsec.net`: forzado de HTTPS y versión mínima de TLS 1.2. Alcance de **zona completa**, consecuencia aceptada en D7 — afecta también a los demás servicios del dominio. Ficheros: `infra/environments/dev/main.tf`. [R3.1, R3.2]
- [ ] 3.2 Aplicar y comprobar que `curl -sSI http://autohostai.digitalsec.net` devuelve una redirección permanente a HTTPS. [R3.1]

## 4. `cloudflared` en el deploy (cierre de la fase A)

Tras esta sección la app se sirve por HTTPS **y** sigue accesible por 8000/3000: las dos vías coexisten a propósito, para poder verificar antes de cerrar.

- [x] 4.1 Añadir el servicio `cloudflared` a `docker-compose.deploy.yml`: imagen oficial **pineada por dígest**, `command: tunnel --no-autoupdate run`, `TUNNEL_TOKEN: ${TUNNEL_TOKEN:?...}`, `TUNNEL_METRICS: 127.0.0.1:2000`, `healthcheck: ["CMD","cloudflared","tunnel","ready"]` (la imagen es distroless: sin shell ni `curl`, D5), `restart: unless-stopped`, `depends_on: frontend: {condition: service_healthy}`, **sin `ports`** y **sin montar el socket de Docker**. [R2.3, R2.4, R2.5]
- [x] 4.2 En el job `deploy` de `.github/workflows/deploy-dev.yml`, leer el token del Vault **por nombre** (`oci secrets secret-bundle get-secret-bundle-by-name --secret-name autohostai-dev-cloudflare-tunnel-token --vault-id "$OCI_VAULT_ID"`, con `OCI_VAULT_ID` desde `vars`) y volcarlo al `.env` como `TUNNEL_TOKEN`, fallando y **nombrando la clave** si no se puede leer, antes de tocar contenedores. El API token de Cloudflare no aparece en este job. [R2.2, R5.4, D3]
- [ ] 4.3 Confirmar que `docker compose up -d --wait` deja `cloudflared` en `healthy` y que, si el túnel no conecta, el job falla y vuelca `docker compose logs` de ese servicio. [R2.4]
- [x] 4.4 Documentar `TUNNEL_TOKEN=` sin valor en `.env.deploy.example`, con el comentario de que lo renderiza el CD desde el Vault, coherente con el resto del fichero. [R5.5]
- [x] 4.5 Añadir a `infra/environments/dev/cloud-init.yaml.tftpl` un comentario que registre la convención de D3: los secretos añadidos después del aprovisionamiento **se resuelven por nombre** desde el workflow, no se añaden claves a `/etc/autohostai-deploy.env` (metadata es ForceNew + `ignore_changes`, así que no llegarían a la VM viva). Sin añadir claves nuevas al fichero, para no crear configuración muerta. [R2.2, D3]

## 5. Verificación externa del túnel (evidencia previa al cierre)

R4.4 prohíbe cerrar puertos sin esta evidencia registrada. Nada de la sección 6 empieza hasta que estas dos tareas estén cerradas.

- [ ] 5.1 Comprobar desde una red **fuera** de los CIDRs de `var.allowed_ssh_cidrs` (p. ej. datos móviles) que `https://autohostai.digitalsec.net` sirve la aplicación con certificado válido y sin aviso del navegador. Registrar el resultado como evidencia. [R3.3, R4.4]
- [ ] 5.2 Comprobar que un hostname no previsto de la zona que resuelva al túnel devuelve **404** por la regla catch-all, y no la aplicación. [R1.2]

## 6. Cierre del acceso HTTP directo (fase B)

- [ ] 6.1 Reducir `local.ingress_ports` a `[22]` en `infra/environments/dev/main.tf`, manteniendo el 22 acotado a `var.allowed_ssh_cidrs` con su validación de prefijo `>= /24` intacta y sin introducir ninguna regla con origen `0.0.0.0/0`. Aplicar y confirmar en el log que solo desaparecen reglas de 8000/3000. [R4.1, R4.2]
- [ ] 6.2 Quitar las secciones `ports` de `backend` y `frontend` en `docker-compose.deploy.yml`, de modo que solo sean alcanzables por la red interna del compose. [R4.3]
- [ ] 6.3 Confirmar tras el deploy que `https://autohostai.digitalsec.net` sigue sirviendo la app y que `curl` directo a la IP pública en 3000 y 8000 **ya no conecta**. [R4.1, R4.3]
- [ ] 6.4 Confirmar que el acceso SSH a la VM sigue funcionando desde un CIDR autorizado (la red de seguridad no debe haberse roto). [R4.2]

## 7. Documentación

- [x] 7.1 `infra/environments/dev/RUNBOOK.md`: sección de operación del túnel — comprobar estado, leer logs de `cloudflared`, **rotar el secreto** del túnel, y acceso de emergencia por SSH cuando la app no responda por HTTPS. Incluir los permisos exactos del API token de Cloudflare (`Account | Cloudflare Tunnel | Edit`, `Zone | DNS | Edit`, `Zone | Zone Settings | Edit`) y el aviso de que "Cloudflare Tunnel" no está bajo "Zero Trust" en el selector. [R6.1]
- [x] 7.2 `README.md` raíz: URL pública de dev y nota de que los puertos directos 8000/3000 ya no están expuestos. [R6.4, R5.1]
- [x] 7.3 `sdd/steering/infra.md`: añadir al *bootstrap irreducible* (a) el dominio y su zona en Cloudflare y (b) el API token del provider con sus permisos mínimos; y registrar como decisión estable que el `apply` de infra **no** se protege con GitHub Environment. [R6.2, R6.5]
- [x] 7.4 `infra/environments/dev/iam-policy.md`: reflejar la policy ampliada del runner (secreto del túnel + `read secrets` para resolución por nombre). [R6.1, D4]
- [x] 7.5 `docs/adr/0003-https-ingress-dev.md`: decisión y alternativas descartadas (nginx + Origin Certificate, Caddy + LE DNS-01, Traefik) con tabla de criterios al estilo de ADR 0001, dejando constancia de que las cuatro cuestan €0 y de que decide el coste de mantenimiento, la superficie expuesta y el encaje con IaC-first. Incluir la restricción de Universal SSL (solo apex + primer nivel) como dato para la futura estrategia multi-entorno. [R6.3]
- [x] 7.6 Registrar en el ADR o en el RUNBOOK que el `tfstate` gana **exactamente un** secreto más en claro —el del túnel, cuyo radio es este entorno—, amparado por la excepción dev/test de `steering/security.md` sin extenderla a staging/prod; y que el API token de Cloudflare queda **deliberadamente fuera** del Vault y del state (R5.4 / D10). [R5.8, R5.4]

## 8. Verification

- [x] 8.1 `cd infra/environments/dev && terraform fmt -check -diff` sin diferencias. [R1]
- [x] 8.2 `cd infra/environments/dev && terraform init -backend=false -input=false && terraform validate` sin errores — son los comandos exactos del job `check` de `infra-dev.yml`. [R1]
- [ ] 8.3 `docker compose -f docker-compose.deploy.yml config` valida sin errores y muestra `cloudflared` sin `ports` publicados, ni `backend`/`frontend` con ellos. [R2.3, R4.3]
- [ ] 8.4 `terraform plan` final limpio (sin cambios pendientes) tras el último `apply`, y `oci_core_instance.dev` sin aparecer en ningún plan del change. [R1]
- [x] 8.5 Confirmar con `git ls-files` y revisión del diff que no hay versionado ningún API token, secreto o token de túnel, ni el zone ID; y que `.terraform.lock.hcl` **sí** quedó versionado con el provider `cloudflare`. [R1.4, R5.6]
- [ ] 8.6 Repasar los 6 requisitos del proposal uno por uno contra la implementación y dejar constancia de la evidencia de cada criterio, incluido R1.6 (ningún valor generado por Terraform copiado a mano del dashboard). [R1, R2, R3, R4, R5, R6]
