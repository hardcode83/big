# 0003 — Ingress HTTPS del entorno dev

## Estado

Aceptado — 2026-07-29.

## Contexto

Tras `app-deploy-dev` la aplicación se despliega en la VM dev, pero solo es alcanzable por **HTTP plano** en los puertos 8000 y 3000, y únicamente desde los CIDRs de operador de `var.allowed_ssh_cidrs`. Eso impide validar el producto en las condiciones reales de uso: el principio 2 de `sdd/steering/product.md` exige que la propietaria vea el estado de sus viviendas **desde el móvil** en menos de 10 segundos, y un móvil fuera de la red de un operador no puede abrir la app. Además, cualquier funcionalidad futura de sesión (JWT en cookies, PWA, service workers) requiere contexto seguro.

Dos restricciones acotan la solución:

1. **`specs/infra-dev-terraform.md` prohíbe cualquier regla de ingress con origen `0.0.0.0/0`** y exige prefijo `>= /24` en cada CIDR. Abrir 80/443 al mundo contradice esa regla EARS; abrirlos a los rangos de Cloudflare no cabe en esa variable (sus prefijos son `/12`, `/13`, `/20`…).
2. **El backend no necesita exposición pública.** `frontend/lib/config/public.ts` excluye a propósito `BACKEND_INTERNAL_URL` del bundle del navegador, así que todo el acceso al backend es server-side por la red interna del compose. Basta **un** hostname público apuntando al frontend, sin CORS ni segundo certificado. *(La segunda frase es **falsa** y lo era al escribirse — el fetching de datos es del navegador; ver Addendum 2026-08-04 §5. La conclusión, un solo hostname sin CORS, sigue siendo válida.)*

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
- **El API token de Cloudflare queda deliberadamente fuera del Vault y del `tfstate`.** No se replica para él el patrón "GitHub Secret = consumidor de CI, Vault = copia recuperable" que se usa con la clave SSH, por dos razones: su radio de daño es **toda la zona** (con `Zone | DNS | Edit` + `Zone | Zone Settings | Edit` puede reescribir DNS y bajar el TLS de todos los servicios de `digitalsec.work`) — *radio **subestimado**: el token permite además publicar en internet lo que sea alcanzable desde el contenedor del túnel, enumerado en el Addendum 2026-08-04 §1* —, radio que la excepción §8 no cubre; y un API token es **re-emitible en segundos**, así que una copia "recuperable" no aporta recuperación. Terraform no persiste la configuración de provider, de modo que sin esa copia el token nunca llega al estado.
- **El job `plan` del workflow de infra queda acotado a `main`**, como ya lo estaba `apply`. Antes aceptaba `workflow_dispatch` desde cualquier rama, y ahora recibe el API token; `sensitive = true` no impide desredactarlo desde código de una rama no revisada. **Precio operativo:** no se puede planificar desde una rama de feature, así que el `plan`/`apply` de un change de infra ocurre tras el merge.
- **Queda una puerta de depuración, acotada a loopback** (D11). `backend` y `frontend` publican en `127.0.0.1:8000` y `127.0.0.1:3000` de la VM en lugar de no publicar nada: un operador con SSH se los trae a su máquina con `ssh -L` y abre la app en el navegador **sin pasar por Cloudflare**, que es la única forma de distinguir un fallo de la app de uno del edge o del túnel. No añade superficie —`127.0.0.1` no es enrutable, así que no llega desde internet ni desde la VCN— y de hecho estrecha el binding anterior, que era `0.0.0.0`. Procedimiento en `RUNBOOK.md` §7.4. Esto **enmendó R4.3**, que originalmente exigía suprimir los puertos.
- **A vigilar:** al pasar por el proxy, la IP del cliente llega en `CF-Connecting-IP` y el esquema en `X-Forwarded-Proto`. Hoy ninguna lógica lee IP ni esquema, pero `auth-tenancy` traerá rate limiting por IP (`security.md` regla 7) y tendrá que leer esa cabecera en vez de la IP de la conexión. *(Esta viñeta es **incompatible con la restricción 2** tal como está redactada: el backend solo recibiría esas cabeceras si su tráfico atravesara el proxy. Ver Addendum 2026-08-04 §6.)*

## Trazabilidad

Change `ingress-https-dev` (`sdd/changes/ingress-https-dev/`), decisiones **D1–D11** de su `design.md`. D9 y D10 nacieron de hallazgos del panel de revisión durante la implementación; D11 de una pregunta del usuario antes de mergear la fase B. Ninguna de las tres estaba en el diseño inicial.

El panel de `/sdd:review` a escala de feature devolvió además 3 hallazgos bloqueantes que **no** se resuelven en este change: se separaron en `ingress-https-hardening` (aislar `cloudflared` en una red de compose dedicada, acotar el statement `read secrets` de la policy del runner, y corregir un ejemplo peligroso del RUNBOOK). Hasta que ese change se aplique, el radio de daño del API token descrito arriba **está subestimado**: como el routing del túnel es remoto y `cloudflared` comparte la red del compose con `backend`, `postgres` y `redis`, el token permite publicar cualquiera de ellos sin abrir un puerto y sin dejar rastro en el `tfstate` hasta el siguiente `plan`. *(Ese change **ya está aplicado**: el radio corregido, que sigue sin ser el que este párrafo sugiere, está en el Addendum 2026-08-04.)*

## Addendum — 2026-08-04 — Aislamiento del túnel, radio real del token, y dos premisas que no se sostenían

Change `ingress-https-hardening`. Este addendum **no altera la decisión** —Cloudflare Tunnel sigue siendo el ingress HTTPS de dev— ni la tabla de alternativas. Corrige el radio de daño que este documento describe y dos afirmaciones del Contexto y de las Consecuencias que la realidad desmiente. Se escribe como addendum, y no reescribiendo la prosa de arriba, porque un ADR registra lo que se decidió con la información de aquel día: borrar la premisa equivocada borraría justo lo que conviene dejar constando. Es la misma convención del Addendum de [ADR 0001](0001-dev-hosting-provider.md).

### 1. El radio de daño del API token, corregido

La viñeta de Consecuencias lo limita a *"reescribir DNS y bajar el TLS de todos los servicios de `digitalsec.work`"*. Era una subestimación, y el párrafo de Trazabilidad ya la advertía: como el routing del túnel es **remoto** (`config_src = "cloudflare"`), quien tenga el token puede apuntar un hostname a cualquier dirección alcanzable desde el contenedor del túnel y publicarla en internet **sin abrir un puerto, sin ejecutar un `apply` y sin dejar rastro en el `tfstate` hasta el siguiente `plan`**.

Tras el aislamiento de redes, el radio real es **todo lo alcanzable desde el contenedor de `cloudflared`**, y conviene enumerarlo sin volver a subestimarlo.

> **Esta tabla es la enumeración canónica del radio.** Es el **único** sitio donde vive completa; el comentario de `networks` en `docker-compose.deploy.yml`, `sdd/steering/infra.md`, `infra/environments/dev/RUNBOOK.md` §7.4.6 y el `BLOCKED.md` del change **apuntan aquí y no la reformulan**, a propósito. Motivo, y está medido: durante `ingress-https-hardening` esta enumeración se corrigió tres veces y **ninguna corrección acertó en todos los sitios a la vez** — una de ellas llegó a eliminar un requisito porque una reescritura local sustituyó contenido que otro documento daba por registrado. Si tienes que corregir el radio, corrígelo **aquí**; si al hacerlo te ves reescribiendo la lista en otro fichero, ese fichero debería llevar un puntero, no una copia.

| Alcanzable por una regla de ingress | ¿Lo cubre el aislamiento? |
|---|---|
| `frontend` (único servicio de la red de ingress) | No, y es su función: es el origen público |
| El **loopback del propio contenedor**: endpoint de `TUNNEL_METRICS` (`127.0.0.1:2000`), con `/ready` y `/debug/pprof` | **No, y ninguna separación de redes puede cubrirlo** — una regla `http://localhost:2000` se sirve dentro del contenedor y no pasa por red. Un heap dump de un proceso que lleva el `TUNNEL_TOKEN` en memoria |
| El **host, por el gateway del bridge**: cualquier puerto de la VM bindeado en `0.0.0.0` — hoy el **22** | **No.** Publicar el 22 por el túnel saltaría el acotado por CIDR del security list |
| Por esa misma ruta, el **servicio de metadatos de la instancia** (`169.254.169.254`, link-local) y cualquier dirección **enrutable de la VCN** | **No, y es la fila más grave** — ver abajo |
| **Cualquier destino de internet**: `ingress` no lleva `internal: true` (no puede: el túnel necesita salida) y el egress de la VCN es `all` hacia `0.0.0.0/0`, así que una regla de ingress puede apuntar a un host público y el túnel actúa de **relay saliente con la IP pública de la VM** | **No, y es el destino más ancho de la tabla.** Permite servir contenido ajeno bajo un hostname de la zona, y alcanzar terceros que tengan la IP de la VM en allowlist |
| `127.0.0.1:8000` / `127.0.0.1:3000` de `backend`/`frontend` | **Sí** — el tráfico de un contenedor no entra al loopback del host, así que la decisión D11 sigue haciendo su trabajo. *Estado de la evidencia: **analizado, no medido**. Es la única fila «Sí» que sostiene el acotado del backend, y las reglas de NAT de Docker la respaldan, pero nadie la ha comprobado en esta VM: el comando está en `RUNBOOK.md` §7.4.6 y lo ejecuta la tarea 5.6 del change* |
| `postgres`, `redis`, `backend`, `worker`, `migrate` | **Sí, y es lo que se gana con el change.** *Estado de la evidencia: **verificado estructuralmente** en el compose, y el mecanismo (aislamiento L3, ni por nombre ni por IP) **reproducido con contenedores desechables** fuera de la VM. El comportamiento **en el entorno desplegado** está pendiente de la tarea 5.6 del change, que ejecuta `RUNBOOK.md` §7.4.6* |

**Sobre la fila de IMDS, porque cambia la lectura de la tabla.** Una regla de ingress apuntando a `http://169.254.169.254` publicaría el servicio de metadatos en internet; de ahí se obtienen credenciales de **instance principal** y con ellas los cinco secretos que la policy del runner autoriza: `ENCRYPTION_KEY` (la clave Fernet sobre la que se apoya la regla 3 de `sdd/steering/security.md`), `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, la clave privada de la GitHub App y el propio token del túnel. Es decir: **el aislamiento de red aguanta, pero los datos que las dos últimas filas declaran fuera de alcance quedarían alcanzables por otra vía**, desde la misma credencial única alrededor de la cual se acota todo este change. Los endpoints legacy de IMDS siguen habilitados (`are_legacy_imds_endpoints_disabled` no está puesto en `infra/environments/dev/main.tf`). **Y tiene una consecuencia sobre el aislamiento entre clientes que conviene no perder de vista al priorizar su mitigación**: la regla 1 de `sdd/steering/security.md` se cumple **enteramente a nivel de aplicación** (`WHERE tenant_id = :tenant_id`), sin RLS ni roles por tenant en la base de datos, así que **una vez dentro de la VM** quien tenga `POSTGRES_PASSWORD` entra a Postgres sin pasar por ninguna query y anula el único mecanismo de aislamiento que el proyecto declara — para **todos** los tenants a la vez, no para una fila. **Ojo al salto, porque no es directo y conviene no exagerar la cadena ni minimizarla**: Postgres no publica puerto y la red de ingress no lo alcanza —eso es justo lo que este change consigue—, así que quien solo tenga el API token necesita un paso más, y el que hay es la clave privada de la GitHub App que sale del mismo Vault: con ella se empuja código y el CD lo ejecuta **dentro** de la VM. *Estado de la evidencia: la configuración de IMDS está **verificada** en el repositorio; que `169.254.169.254` sea alcanzable desde un contenedor de la red de ingress en esta VM es lo **esperado** en Docker sobre cloud pero **no se ha medido** — el comando está en `RUNBOOK.md` §7.4.6.*

Mitigar el residual —un firewall de host que descarte el tráfico de los bridges hacia el 22 y hacia la link-local, desactivar los endpoints legacy de IMDS, o desactivar el endpoint de métricas del túnel— es un cambio de la **superficie de la VM**, no de la topología del compose, y queda registrado como candidato a change propio. Documentarlo con exactitud sí entra: repetir aquí el error de subestimar el radio habría sido especialmente caro, porque corregirlo es la razón de ser de `ingress-https-hardening`.

### 2. El mecanismo, y las DOS mitades del invariante

**Esta sección es el hogar canónico del invariante**, igual que §1 lo es del radio. Los demás artefactos lo resumen en una frase y apuntan aquí.

**El mecanismo es aislamiento L3, no DNS.** Lo que separa las dos redes del compose es que Docker descarta el tráfico entre bridges distintos, así que una regla de ingress no llega a `private` ni por nombre ni **por IP literal**. El acotado del DNS interno es una consecuencia, no la causa — y merece decirse porque una comprobación construida solo sobre resolución de nombres pasaría igual en una topología donde los bridges fueran enrutables entre sí (por eso la verificación de `RUNBOOK.md` §7.4.6 incluye un intento de conexión por IP).

El invariante tiene **dos mitades y hacen falta las dos**. Cada una cierra un agujero que la otra deja abierto, y por eso enunciar solo una es peor que inútil: da una lista que se puede cumplir mientras se abre el mismo boquete.

**(a) Pertenencia: el alcance de `cloudflared` es la UNIÓN de las redes a las que está conectado.** Un contenedor alcanza —y resuelve por DNS— los servicios de todas las redes que comparte, así que conectar `cloudflared` a una red más le suma **todo** lo que haya en ella. Consecuencia operativa, y es la que hay que leer antes de tocar la topología: **el aislamiento no admite una excepción por origen sin deshacerse**. Conectar `backend` a la red de ingress "solo para el webhook" no es una excepción acotada, es devolver al API token la capacidad de publicar la API entera. Cualquier origen público futuro tiene que ser un servicio **de** la red de ingress que no sea `backend`.

**(b) Reenvío: todo origen conectado a la red de ingress extiende el radio a lo que ese origen reenvíe hacia la red privada.** Así que la condición de (a) es necesaria pero **no suficiente**: un proxy en la red de ingress que reenvíe a `backend:8000` la cumple al pie de la letra y devuelve el radio entero. Y lo que hay que vigilar es la **clase de superficie**, no un campo concreto — cualquier cosa que haga que el *servidor* de Next emita peticiones:

- `rewrites` en `frontend/next.config.ts`
- route handlers (`app/**/route.ts`)
- `middleware.ts`
- server actions (`"use server"`)
- **`images.remotePatterns`**, porque `/_next/image` hace fetch server-side de las URL que casen ese patrón
- **un `fetch` server-side desde un Server Component, un layout o `generateMetadata`** — y es la vía más probable de todas, porque `frontend/lib/config/server.ts` expone `getServerConfig().backendInternalUrl` justamente para eso, y la doble pertenencia de `frontend` a las dos redes existe *para que la app pueda consumir la API cuando toque*. Una lista que solo enumerara ficheros de configuración se cumpliría al pie de la letra mientras un RSC abre el mismo boquete

Hoy `frontend` no reenvía nada: `next.config.ts` solo declara `output: "standalone"` —sin `rewrites` y sin `images`— y no existe **ninguna de las demás** (verificado: sin `middleware.ts`, sin route handlers, sin `"use server"`, y `getServerConfig()` solo se invoca desde su propio test; ver §5). **Esa ausencia es parte del control**, y vive en un fichero que este ADR no gobierna: quien dé el control por vigente tiene que mirar también `frontend/next.config.ts`.

### 3. La asimetría de control que el change entrega

Y es el valor del cambio, no un efecto colateral:

| Acción | Qué cuesta |
|---|---|
| Reescribir una regla de ingress en el edge | solo el API token — sin `apply`, sin rastro en el `tfstate` hasta el siguiente `plan` |
| Hacer alcanzable un origen **nuevo** | un cambio versionado en `docker-compose.deploy.yml` (o en la superficie de reenvío de un origen) + un deploy, revisable en un Pull Request |

### 4. Consumidor futuro conocido: los webhooks del PMS

Beds24 tiene que hacer `POST` contra `/api/v1/webhooks/{provider}/{webhook_token}` **desde internet** (`docs/beds24-spike.md` §"Consecuencia para la infraestructura"). Hereda **las dos mitades** del invariante de §2: no vale conectar `cloudflared` a una red que contenga `backend` (mitad **a**: sería la "excepción por origen" que deshace el control), y tampoco vale un origen en la red de ingress que reenvíe a `backend:8000` (mitad **b**). **Este addendum no elige su topología**: esa decisión es de la entrada `api-ingress-routing` del roadmap, para la que el webhook es un segundo disparador, independiente del primero y que puede llegar antes.

### 5. La restricción 2 del Contexto es falsa, y lo era al escribirse

Dice: *"El backend no necesita exposición pública. `frontend/lib/config/public.ts` excluye a propósito `BACKEND_INTERNAL_URL` del bundle del navegador, así que todo el acceso al backend es server-side por la red interna del compose."* La conclusión no se sigue de la evidencia.

- **Lo que hoy es cierto**: ningún código accede al backend. `getServerConfig()` no se invoca desde el código de aplicación y `getDashboardDataSource()` devuelve un mock.
- **Lo que la arquitectura comprometida implica**: `sdd/steering/frontend.md` fija TanStack Query para server state (línea 13) y "JWT en memoria + refresh" (línea 18), ambas desde el 2026-07-15; el login de `auth-tenancy` devuelve los tokens en el cuerpo JSON, no en cookie; y `frontend/features/dashboard/components/dashboard-view.tsx:19` ya consume `useDashboardCards()` desde una vista cliente. El renderizado es server-side, pero **el fetching de datos es del navegador**.
- **Por qué la evidencia no sostiene la conclusión**: `public.ts` excluye `BACKEND_INTERNAL_URL` del bundle porque `http://backend:8000` es un nombre de red interna irresoluble desde un navegador, no porque el navegador no vaya a llamar a la API.

**La conclusión operativa del ADR sigue siendo válida**, y por eso esto no reabre la comparativa: el acceso desde el navegador **no exige exponer el backend**. Basta un camino **same-origin** bajo el hostname público que ya existe, así que sigue haciendo falta un solo hostname, sin CORS y sin segundo certificado. La restricción 2 reforzaba el acotado; no sostenía la elección de Cloudflare Tunnel.

El camino en sí queda pendiente en la entrada `api-ingress-routing` del roadmap, aplazada el 2026-08-02 con condiciones de disparo explícitas. `ingress-https-hardening` no lo construye.

### 6. Incoherencia interna resuelta

La viñeta "A vigilar" de Consecuencias asume que el backend recibe `CF-Connecting-IP`, lo que solo ocurre si el tráfico al backend atraviesa el proxy de Cloudflare — imposible si "todo el acceso al backend es server-side por la red interna del compose", como afirma la restricción 2. Las dos frases no podían ser ciertas a la vez. Con la restricción 2 corregida, la viñeta queda en pie: el día que exista el camino same-origin, la propagación de la IP real del cliente es un requisito de ese change, y el límite de 10 intentos/min por IP de `auth-tenancy` depende de ella (su design D12).
