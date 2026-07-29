# Proposal: ingress-https-dev

## Why

Hoy la app desplegada en dev solo es alcanzable por **HTTP plano** en los puertos 8000/3000, y únicamente desde los CIDRs de operador de `var.allowed_ssh_cidrs` (`specs/infra-dev-terraform.md`, `specs/app-deploy-dev.md` §Estado lo deja explícito como pendiente). Eso impide validar el producto en las condiciones en las que se va a usar: el principio 2 de `steering/product.md` exige que la propietaria vea el estado de sus viviendas **desde el móvil** en menos de 10 segundos, y un móvil fuera de la red de un operador no puede abrir la app. Además cualquier funcionalidad futura de sesión (JWT en cookies, PWA, service workers) requiere contexto seguro.

Este change añade un ingress HTTPS público con un hostname real, **sin abrir ningún puerto entrante** y **sin gestionar certificados**, y aprovecha para cerrar el acceso HTTP directo que deja de ser necesario.

## What changes

Un servicio `cloudflared` se suma a `docker-compose.deploy.yml` y publica el frontend a través de un **Cloudflare Tunnel**: el contenedor abre una conexión *saliente* al edge de Cloudflare, que termina TLS con el certificado del dominio y enruta las peticiones a `frontend:3000` por la red interna de compose. El backend sigue sin exposición pública — el frontend ya le habla server-side por `BACKEND_INTERNAL_URL`, y `frontend/lib/config/public.ts` excluye deliberadamente esa URL del bundle del navegador, así que no hace falta ni un segundo hostname ni CORS.

El hostname de `dev` es **`autohostai.digitalsec.work`**, sobre la zona `digitalsec.work` que el equipo ya tiene en Cloudflare. Se elige un subdominio de primer nivel a propósito: es el alcance que cubre el certificado Universal SSL gratuito, así que el HTTPS sale a €0 sin certificados de pago. La **estrategia de nombres para varios entornos queda deliberadamente aplazada** — se decidirá cuando exista un segundo entorno, con el dato de que profundizar (`dev.autohostai.digitalsec.work`) obligaría a un certificado de pago mientras que aplanar (`autohostai-staging.digitalsec.work`) o usar otra zona no.

Todo el lado Cloudflare se declara con el provider `cloudflare` en `infra/environments/dev/`: el túnel, sus reglas de ingress, el registro DNS y los ajustes de HTTPS de la zona. El secreto del túnel lo genera Terraform y se guarda como `oci_vault_secret`, de modo que el CD lo lee por instance principal igual que ya hace con `JWT_SECRET_KEY` y `ENCRYPTION_KEY`. Una vez verificado el túnel, `ingress_ports` baja de `[22, 8000, 3000]` a `[22]`.

Se elige Cloudflare Tunnel frente a nginx + Origin Certificate, Caddy + Let's Encrypt (DNS-01) y Traefik; el razonamiento y los criterios se registran en **`docs/adr/0003-https-ingress-dev.md`** siguiendo el precedente de ADR 0001. Los cuatro candidatos cuestan €0; la decisión se toma por número de piezas a mantener, superficie expuesta y encaje con la norma IaC-first. Este change también amplía el **bootstrap irreducible** de `steering/infra.md` con las dos únicas piezas de Cloudflare que no son codificables: la zona del dominio y el API token del provider.

## Requirements

### R1 — Túnel, routing y DNS declarados como código

**As a** operador de la infra, **I want** que el túnel y su publicación DNS existan solo como Terraform, **so that** una tenancy o zona reconstruida se rehaga sin pasos manuales en la consola de Cloudflare (norma IaC-first de `steering/infra.md`).

Acceptance criteria:

1. THE SYSTEM SHALL declarar el túnel como `cloudflare_zero_trust_tunnel_cloudflared` con `config_src = "cloudflare"`, y su secreto como un recurso `random_*` de Terraform — nunca un valor escrito a mano.
2. THE SYSTEM SHALL declarar el routing como `cloudflare_zero_trust_tunnel_cloudflared_config` con una regla de ingress cuyo `service` apunte a `http://frontend:3000`, y una regla `catch-all` que devuelva `http_status:404` para cualquier hostname no previsto.
3. THE SYSTEM SHALL declarar el registro DNS como `cloudflare_dns_record` de tipo `CNAME` hacia `<tunnel_id>.cfargotunnel.com` con `proxied = true`, sin que el ID del túnel aparezca literal en el repo.
4. THE SYSTEM SHALL fijar la versión del provider `cloudflare` en `.terraform.lock.hcl` con constraint explícito en la configuración.
5. IF el `plan` necesita credenciales de Cloudflare que no están presentes, THEN THE SYSTEM SHALL fallar nombrando la variable ausente, nunca continuar con un recurso a medias.
6. THE SYSTEM SHALL NOT requerir que ningún valor generado por Terraform (ID del túnel, secreto, token) se copie a mano desde el dashboard de Cloudflare.

### R2 — El deploy arranca `cloudflared` con el secreto leído del Vault

**As a** operador, **I want** que el token del túnel viaje por el mismo camino que el resto de secretos de runtime, **so that** no haya un secreto gestionado de forma distinta a los demás.

Acceptance criteria:

1. THE SYSTEM SHALL guardar el token del túnel como `oci_vault_secret`, generado por Terraform a partir del `account_tag`, el `id` del túnel y el secreto — sin que exista un paso manual de copiar el token desde el dashboard.
2. WHEN el job `deploy` renderiza el `.env` de runtime, THE SYSTEM SHALL leer ese secreto del Vault por instance principal y fallar el deploy nombrando la clave si no se puede leer, antes de tocar contenedores.
3. THE SYSTEM SHALL declarar en `docker-compose.deploy.yml` un servicio `cloudflared` con imagen pineada, `restart: unless-stopped`, sin `ports` publicados y sin acceso al socket de Docker.
4. WHEN `docker compose up -d --wait` termina, THE SYSTEM SHALL considerar el deploy exitoso solo si `cloudflared` queda `healthy`; IF el túnel no llega a conectar dentro del timeout, THEN THE SYSTEM SHALL fallar el job y volcar sus logs.
5. THE SYSTEM SHALL declarar el servicio `cloudflared` con `depends_on` del `frontend` en estado `service_healthy`, para no anunciar al edge un origen que todavía no responde.

### R3 — HTTPS forzado en el edge, también como código

**As a** usuaria en el móvil, **I want** que la app solo se sirva por HTTPS, **so that** no exista una vía en claro ni un aviso de sitio no seguro.

Acceptance criteria:

1. WHEN un cliente solicita el hostname público por HTTP, THE SYSTEM SHALL responder con una redirección permanente a HTTPS.
2. THE SYSTEM SHALL declarar como código (recurso de ajuste de zona del provider `cloudflare`) el forzado de HTTPS. THE SYSTEM SHALL NOT modificar la versión mínima de TLS de la zona: `digitalsec.work` aloja servicios ajenos a este change y subirla de 1.0 a 1.2 concentraría casi todo el riesgo sobre ellos sin aportar nada al ingress (revisado 2026-07-29 con el inventario real de la zona, ver D7).
3. WHEN se solicita el hostname público por HTTPS, THE SYSTEM SHALL servir la aplicación con un certificado válido y confiado por navegadores, sin intervención de un certificado gestionado en el origen.
4. THE SYSTEM SHALL usar un hostname de **primer nivel** bajo el apex de la zona (`<etiqueta>.digitalsec.work`), que es el alcance que cubre el certificado Universal SSL gratuito; IF se necesitara un hostname de mayor profundidad (p. ej. `dev.autohostai.digitalsec.work`), THEN THE SYSTEM SHALL tratarlo como decisión de coste, porque exige Total TLS o Advanced Certificate Manager (de pago).

### R4 — Cierre del acceso HTTP directo, secuenciado tras la verificación

**As a** responsable de la infra, **I want** que los puertos de app dejen de estar expuestos una vez el túnel funciona, **so that** la única vía de entrada a la aplicación sea el ingress HTTPS.

Acceptance criteria:

1. WHEN el túnel ha sido verificado sirviendo la aplicación por HTTPS en el hostname público, THE SYSTEM SHALL reducir `local.ingress_ports` a `[22]`, eliminando las reglas de 8000 y 3000.
2. THE SYSTEM SHALL mantener el 22 acotado a `var.allowed_ssh_cidrs` con la validación de prefijo `>= /24` intacta, y THE SYSTEM SHALL NOT introducir ninguna regla de ingress con origen `0.0.0.0/0`.
3. THE SYSTEM SHALL dejar de publicar los puertos 8000 y 3000 en `docker-compose.deploy.yml`, de modo que backend y frontend solo sean alcanzables desde la red interna de compose.
4. IF la verificación del túnel no se ha registrado como evidencia, THEN THE SYSTEM SHALL NOT aplicar el cierre de puertos — el orden es verificar y después cerrar, nunca al revés.

### R5 — Configuración inyectada: hostname como variable, secretos fuera del repo

**As a** equipo, **I want** que el hostname sea una variable y las credenciales nunca estén versionadas, **so that** el mismo código sirva para otra zona o entorno sin editarlo y sin filtrar secretos.

Acceptance criteria:

1. THE SYSTEM SHALL exponer el hostname público como variable de Terraform, cuyo valor para `dev` es **`autohostai.digitalsec.work`**; por ser un nombre público y no un secreto, THE SYSTEM SHALL documentar ese valor en `dev.tfvars.example` y en el `README.md` raíz.
2. THE SYSTEM SHALL declarar el **API token de Cloudflare** y el **zone ID** como variables `sensitive`, presentes en `dev.tfvars.example` solo como marcador sin valor.
3. THE SYSTEM SHALL consumir el API token en CI desde un **GitHub Secret de repositorio** (`CLOUDFLARE_API_TOKEN` → `TF_VAR_cloudflare_api_token`), del mismo modo que `infra-dev.yml` ya consume `GH_APP_PRIVATE_KEY`.
4. THE SYSTEM SHALL NOT copiar el API token de Cloudflare al OCI Vault ni a ningún otro almacén que lo lleve al `tfstate`. A diferencia de la clave SSH o la de la GitHub App, un API token es **re-emitible en segundos** desde el dashboard, así que una copia "recuperable" no aporta capacidad de recuperación y sí ampliaría la exposición de un secreto cuyo radio de daño es **toda la zona** `digitalsec.work` (DNS y TLS de todos sus servicios), radio que la excepción dev/test de `steering/security.md` §8 no cubre.
5. THE SYSTEM SHALL NOT hacer llegar el API token de Cloudflare a la VM: el único secreto de Cloudflare presente en la máquina es el token del túnel, leído del Vault por instance principal.
6. THE SYSTEM SHALL documentar en `.env.deploy.example` la clave del token del túnel sin valor, coherente con el resto del fichero.
7. THE SYSTEM SHALL NOT incluir en ningún fichero versionado el API token de Cloudflare, el secreto o token del túnel, ni el zone ID.
8. WHERE el secreto del túnel queda en el `tfstate`, THE SYSTEM SHALL ampararse en la excepción dev/test ya documentada en `steering/security.md`, sin relajarla ni extenderla a staging/prod — su radio sí es el de este entorno: solo permite servir tráfico de ese túnel.
9. THE SYSTEM SHALL restringir por `validation` la etiqueta de `public_hostname` a un prefijo reservado al proyecto (`autohostai*`), porque la zona es un dominio compartido y el valor llega de una variable de Actions editable sin PR — sin ese límite, cambiarla podría redirigir un hostname ajeno (`www`, `mail`…) al túnel de este entorno en el siguiente `apply`.

### R6 — Operación y bootstrap documentados

**As a** operador de guardia, **I want** saber qué hacer si el túnel cae y qué pasos son irreducibles, **so that** la recuperación no dependa de quien lo montó.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en `infra/environments/dev/RUNBOOK.md` el diagnóstico del túnel (comprobar estado, leer logs de `cloudflared`, rotar el secreto) y el procedimiento de acceso de emergencia por SSH cuando la app no responda por HTTPS.
2. THE SYSTEM SHALL añadir a la lista de *bootstrap irreducible* de `steering/infra.md`, junto a la API key raíz de OCI y la clave de la GitHub App: (a) el **dominio y su zona en Cloudflare** —registrar y delegar nameservers establece propiedad y no es codificable—, y (b) el **API token de Cloudflare** del provider, con los permisos mínimos que necesita.
3. THE SYSTEM SHALL registrar la decisión y las alternativas descartadas en `docs/adr/0003-https-ingress-dev.md`, con la tabla de criterios al estilo de ADR 0001.
4. THE SYSTEM SHALL actualizar el `README.md` raíz con la URL pública de dev y la nota de que los puertos directos ya no están expuestos.
5. THE SYSTEM SHALL registrar en `steering/infra.md`, como decisión estable, que el `apply` de infra **no** se protege con un GitHub Environment con aprobación —el control es `workflow_dispatch` manual acotado a `main` con dos owners—, para que la ausencia de `environment:` en los workflows no se reabra como hallazgo en cada revisión.

## Out of scope

- **Certificados en el origen** (Origin Certificate, Let's Encrypt, nginx/Caddy/Traefik como reverse proxy): descartados en el ADR 0003; con el túnel no hay TLS que gestionar en la VM.
- **Exponer el backend públicamente** o publicar un segundo hostname de API: innecesario mientras el acceso sea server-side; llegará cuando el navegador tenga que llamar al backend directamente.
- **Autenticación en el edge** (Cloudflare Access / Zero Trust con identidades): la autenticación del producto es `auth-tenancy`, y las funciones de Zero Trust por usuario son de pago.
- **WAF, rate limiting y caché en el edge**: se valorarán cuando haya tráfico real; el rate limiting de auth es requisito de `auth-tenancy` (`steering/security.md` regla 7).
- **staging / prod**: `steering/infra.md` mantiene esos entornos sin decidir; este change es exclusivamente `dev`.
- **Estrategia de nombres multi-entorno**: aplazada explícitamente. Este change fija un único hostname de primer nivel para `dev`; el patrón para más entornos (aplanar bajo el apex, zona aparte, o pagar Total TLS/ACM para profundizar) se decide cuando exista el segundo entorno.
- **Adoptar el provider `github`** para la parte GitHub-side: es el change `infra-github-iac` del roadmap.
- **Gates de CI de tests** (pytest/lint/typecheck en PR): descartado explícitamente para este momento del proyecto, sin MVP todavía.

## Affected specs

- `sdd/specs/ingress-https-dev.md` — *(no existe aún — se creará al archivar)*: la capability de ingress HTTPS público (túnel, routing, DNS, HTTPS del edge).
- `sdd/specs/app-deploy-dev.md` — modificar: el compose de deploy incorpora `cloudflared`, deja de publicar 8000/3000, y el §Estado ya no lista TLS/HTTPS como pendiente.
- `sdd/specs/infra-dev-terraform.md` — modificar: `ingress_ports` pasa a `[22]`, se suma el provider `cloudflare` y los recursos del túnel/DNS/zona.

Fuera de `sdd/specs/`, este change también toca `sdd/steering/infra.md` (bootstrap irreducible) y añade `docs/adr/0003-https-ingress-dev.md`.
