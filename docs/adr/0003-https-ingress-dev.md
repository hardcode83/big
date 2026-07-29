# 0003 — Ingress HTTPS del entorno dev

## Estado

Aceptado — 2026-07-29.

## Contexto

Tras `app-deploy-dev` la aplicación se despliega en la VM dev, pero solo es alcanzable por **HTTP plano** en los puertos 8000 y 3000, y únicamente desde los CIDRs de operador de `var.allowed_ssh_cidrs`. Eso impide validar el producto en las condiciones reales de uso: el principio 2 de `sdd/steering/product.md` exige que la propietaria vea el estado de sus viviendas **desde el móvil** en menos de 10 segundos, y un móvil fuera de la red de un operador no puede abrir la app. Además, cualquier funcionalidad futura de sesión (JWT en cookies, PWA, service workers) requiere contexto seguro.

Dos restricciones acotan la solución:

1. **`specs/infra-dev-terraform.md` prohíbe cualquier regla de ingress con origen `0.0.0.0/0`** y exige prefijo `>= /24` en cada CIDR. Abrir 80/443 al mundo contradice esa regla EARS; abrirlos a los rangos de Cloudflare no cabe en esa variable (sus prefijos son `/12`, `/13`, `/20`…).
2. **El backend no necesita exposición pública.** `frontend/lib/config/public.ts` excluye a propósito `BACKEND_INTERNAL_URL` del bundle del navegador, así que todo el acceso al backend es server-side por la red interna del compose. Basta **un** hostname público apuntando al frontend, sin CORS ni segundo certificado.

**El coste no discrimina**: se verificó que Cloudflare Tunnel es gratis y sin límites de uso, que el proxy y el Universal SSL están en el plan Free, y que los Origin CA Certificates son gratuitos con validez de hasta 15 años. Las cuatro opciones evaluadas cuestan **0 €/mes**. Lo que discrimina es el **coste de mantenimiento**, la **superficie expuesta** y el encaje con la norma **IaC-first** de `sdd/steering/infra.md`.

## Decisión

**Cloudflare Tunnel (`cloudflared`) como ingress HTTPS del entorno dev**, con el hostname `autohostai.digitalsec.work` sobre la zona `digitalsec.work` que el equipo ya tiene en Cloudflare.

El contenedor abre una conexión **saliente** al edge de Cloudflare, que termina TLS y entrega a `frontend:3000` por la red interna del compose. Consecuencias directas: **no se abre ningún puerto entrante**, no hay certificados que gestionar en el origen, y el security list queda intacto — de hecho `local.ingress_ports` se reduce de `[22, 8000, 3000]` a `[22]`, quedando SSH como única entrada.

Todo el lado Cloudflare se declara con el provider `cloudflare` en el mismo root module que OCI: el túnel, sus reglas de ingress, el registro DNS y los ajustes de HTTPS de la zona. El token que consume `cloudflared` **se deriva en Terraform** (el provider v5 no expone un atributo `token`, solo acepta `tunnel_secret` de entrada) y se guarda como `oci_vault_secret`, que el CD lee por instance principal igual que el resto de secretos de runtime.

## Alternativas consideradas

Las cuatro cuestan 0 €/mes; se ordenan por número de piezas a mantener.

| | Puertos a abrir | Renovación de certificados | Piezas a mantener | Veredicto |
|---|---|---|---|---|
| **Cloudflare Tunnel** (elegida) | **ninguno** | **ninguna** | 1 contenedor + 1 secreto en Vault | ✅ |
| nginx + Origin Certificate | 443, restringido a rangos de Cloudflare | ninguna (cert de 15 años) | `nginx.conf` + variable de ingress nueva + **enmendar la regla EARS del prefijo `>= /24`** | Rechazada |
| Caddy + Let's Encrypt (DNS-01) | 443 | automática | **imagen propia** con `xcaddy` (plugin `caddy-dns/cloudflare`) + API token | Rechazada |
| Traefik + Let's Encrypt (DNS-01) | 443 | automática | config estática + labels + **socket de Docker montado** | Rechazada |

- **nginx + Origin Certificate** era la segunda opción y la más portable si algún día `staging`/`prod` salen de Cloudflare. Se rechaza porque exige abrir 443 y **enmendar una regla EARS vigente** (los rangos de Cloudflare no caben en la validación de prefijo `>= /24`), a cambio de un beneficio —portabilidad— que hoy no se necesita: `steering/infra.md` mantiene staging/prod explícitamente sin decidir.
- **Caddy + Let's Encrypt** es la única que da certificados públicamente válidos sin depender de Cloudflare en el camino del tráfico, pero el plugin DNS de Cloudflare obliga a **construir y pinear una imagen propia**, es decir a asumir cadena de suministro que mantener y rebuildear por CVEs. Es exactamente el tipo de mantenimiento recurrente que la decisión quiere evitar.
- **Traefik** brilla con auto-discovery de *muchos* servicios; aquí hay **uno** que exponer, así que su maquinaria (config estática + dinámica por labels) no se amortiza, y además montaría el socket de Docker, ampliando superficie sin contrapartida.
- **No hacer nada** (seguir en HTTP restringido por CIDR) bloquea el principio 2 de `product.md` y cualquier funcionalidad que requiera contexto seguro.

### Restricción de certificado que condiciona el naming futuro

El **Universal SSL gratuito cubre solo el apex y los subdominios de primer nivel**. Por eso el hostname es `autohostai.digitalsec.work` (una sola etiqueta bajo el apex), y una `validation` de Terraform lo hace cumplir en el `plan`. Consecuencia para cuando exista un segundo entorno: **aplanar** (`autohostai-staging.digitalsec.work`) o usar otra zona son 0 €, mientras que **profundizar** (`dev.autohostai.digitalsec.work`) exigiría Total TLS o Advanced Certificate Manager, **ambos de pago**. La estrategia multi-entorno queda deliberadamente aplazada, pero con ese dato sobre la mesa.

## Consecuencias

- **Positivas:** cero puertos entrantes y cero certificados que gestionar; el security list pasa a `[22]`; ninguna regla EARS existente se relaja; el patrón es coherente con el que ya se validó para el runner self-hosted (la VM sale hacia fuera, nadie entra); no hace falta nginx ni ningún reverse proxy en el stack.
- **Dependencia de runtime en Cloudflare.** Antes Cloudflare solo era el DNS; ahora está en el camino del tráfico. Si el edge o el túnel caen, la app deja de ser alcanzable por HTTPS (el acceso de emergencia sigue siendo SSH — ver RUNBOOK §7).
- **El forzado de HTTPS es de zona, no de hostname.** Cloudflare no lo ofrece por hostname en el plan Free, así que `always_use_https` **aplica a todo `digitalsec.work`**. Se aceptó tras inventariar la zona: tiene 7 hosts publicados y dos instancias de `external-dns` gestionándola, pero **solo 3 son `proxied`** (`argocd`, `carto-api`, `ha`) y por tanto solo esos pasan por el edge. Único escenario de rotura: un cliente que llame por `http://` y no siga redirecciones. Si alguno diera problemas, la salida es una *Redirect Rule* por hostname (viable en Free).
- **El TLS mínimo de la zona NO se modifica** (se queda en 1.0). Subirlo a 1.2 concentraba casi todo el riesgo del change sobre servicios ajenos a él, sin aportar nada al ingress: el túnel no expone TLS del origen y el edge ya negocia TLS moderno con los navegadores. R3.2 se relajó en consecuencia (decisión del 2026-07-29, ver design D7).
- **Bootstrap irreducible ampliado** (ver `sdd/steering/infra.md`): (a) el dominio y su zona en Cloudflare —registrar y delegar nameservers establece propiedad y no es codificable— y (b) el API token del provider. Todo lo demás es Terraform.
- **El `tfstate` gana exactamente un secreto nuevo**: el token del túnel. Su radio **sí** es el de este entorno (solo permite servir tráfico de ese túnel), así que queda amparado por la excepción dev/test de `sdd/steering/security.md` §8 sin relajarla ni extenderla a staging/prod.
- **El API token de Cloudflare queda deliberadamente fuera del Vault y del `tfstate`.** No se replica para él el patrón "GitHub Secret = consumidor de CI, Vault = copia recuperable" que se usa con la clave SSH, por dos razones: su radio de daño es **toda la zona** (con `Zone | DNS | Edit` + `Zone | Zone Settings | Edit` puede reescribir DNS y bajar el TLS de todos los servicios de `digitalsec.work`), radio que la excepción §8 no cubre; y un API token es **re-emitible en segundos**, así que una copia "recuperable" no aporta recuperación. Terraform no persiste la configuración de provider, de modo que sin esa copia el token nunca llega al estado.
- **El job `plan` del workflow de infra queda acotado a `main`**, como ya lo estaba `apply`. Antes aceptaba `workflow_dispatch` desde cualquier rama, y ahora recibe el API token; `sensitive = true` no impide desredactarlo desde código de una rama no revisada. **Precio operativo:** no se puede planificar desde una rama de feature, así que el `plan`/`apply` de un change de infra ocurre tras el merge.
- **Queda una puerta de depuración, acotada a loopback** (D11). `backend` y `frontend` publican en `127.0.0.1:8000` y `127.0.0.1:3000` de la VM en lugar de no publicar nada: un operador con SSH se los trae a su máquina con `ssh -L` y abre la app en el navegador **sin pasar por Cloudflare**, que es la única forma de distinguir un fallo de la app de uno del edge o del túnel. No añade superficie —`127.0.0.1` no es enrutable, así que no llega desde internet ni desde la VCN— y de hecho estrecha el binding anterior, que era `0.0.0.0`. Procedimiento en `RUNBOOK.md` §7.4. Esto **enmendó R4.3**, que originalmente exigía suprimir los puertos.
- **A vigilar:** al pasar por el proxy, la IP del cliente llega en `CF-Connecting-IP` y el esquema en `X-Forwarded-Proto`. Hoy ninguna lógica lee IP ni esquema, pero `auth-tenancy` traerá rate limiting por IP (`security.md` regla 7) y tendrá que leer esa cabecera en vez de la IP de la conexión.

## Trazabilidad

Change `ingress-https-dev` (`sdd/changes/ingress-https-dev/`), decisiones **D1–D11** de su `design.md`. D9 y D10 nacieron de hallazgos del panel de revisión durante la implementación; D11 de una pregunta del usuario antes de mergear la fase B. Ninguna de las tres estaba en el diseño inicial.

El panel de `/sdd:review` a escala de feature devolvió además 3 hallazgos bloqueantes que **no** se resuelven en este change: se separaron en `ingress-https-hardening` (aislar `cloudflared` en una red de compose dedicada, acotar el statement `read secrets` de la policy del runner, y corregir un ejemplo peligroso del RUNBOOK). Hasta que ese change se aplique, el radio de daño del API token descrito arriba **está subestimado**: como el routing del túnel es remoto y `cloudflared` comparte la red del compose con `backend`, `postgres` y `redis`, el token permite publicar cualquiera de ellos sin abrir un puerto y sin dejar rastro en el `tfstate` hasta el siguiente `plan`.
