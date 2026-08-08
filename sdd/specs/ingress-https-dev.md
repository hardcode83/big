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
### Aislamiento de red del túnel (`docker-compose.deploy.yml`, desde `ingress-https-hardening`)

- THE SYSTEM SHALL declarar dos redes en el compose de deploy, `ingress` y `private`, y THE SYSTEM SHALL asignar explícitamente la red de **los siete** servicios, de modo que la red `default` implícita no se cree. Asignarlos todos es lo que hace el control fail-closed: un servicio nuevo sin sección `networks` queda aislado y roto —error visible en el deploy— en vez de aterrizar en la red que contiene la base de datos.
- THE SYSTEM SHALL mantener `cloudflared` **únicamente** en `ingress`, y `postgres`/`redis`/`migrate`/`backend`/`worker` **únicamente** en `private`.
- THE SYSTEM SHALL mantener `frontend` en **ambas** redes: es el origen público y a la vez consume la API por `BACKEND_INTERNAL_URL`, sin cambios en la aplicación. Es el único puente entre las dos redes.
- THE SYSTEM SHALL NOT declarar `internal: true` en `ingress`: cortaría su salida a internet y `cloudflared` no podría abrir la conexión al edge.
- THE SYSTEM SHALL NOT pinear la puerta de salida por defecto del `frontend`. El campo que la gobierna es `gw_priority` (`priority` solo ordena la conexión a las redes); hoy el servidor de Next no hace llamadas salientes, así que no hace falta ninguno, y `gw_priority` es un campo reciente cuyo rechazo por una versión antigua de Compose tumbaría el parseo del fichero y con él todos los deploys.
- El mecanismo que separa las dos redes es el **aislamiento L3 entre bridges** —Docker descarta el tráfico entre bridges distintos, así que una regla de ingress no llega a `private` ni por nombre ni por IP literal—; el acotado del DNS interno es una consecuencia, no la causa.
- **Verificado en el entorno desplegado** (2026-08-04): `cloudflared` está solo en `autohostai_ingress`; desde esa red no se resuelve `postgres` y la conexión a su IP literal falla, con el control positivo desde `autohostai_private` conectando. Procedimiento repetible en `RUNBOOK.md` §7.4.6.
- WHERE se necesite publicar un origen público nuevo, THE SYSTEM SHALL respetar las dos mitades del invariante del aislamiento: (a) el alcance de `cloudflared` es la **unión** de sus redes, así que conectarlo a una red más le suma todo lo que haya en ella y el aislamiento **no admite excepción por origen**; y (b) todo origen de `ingress` extiende el radio a lo que **reenvíe** hacia `private`, así que "un servicio que no sea `backend`" es necesario pero no suficiente. Enumeración canónica del invariante y del radio de daño en `docs/adr/0003-https-ingress-dev.md` §Addendum 2026-08-04 §2 y §1.
- **Residual conocido y medido, que el aislamiento no cubre**: `cloudflared` sigue alcanzando su propio loopback (endpoint de métricas con `/debug/pprof`) y el host por el gateway del bridge, y por ahí el puerto 22 y el servicio de metadatos de la instancia — ambos comprobados alcanzables el 2026-08-04. Mitigarlo es superficie de VM y tiene entrada propia en el roadmap (`tunnel-host-surface-hardening`).
- **Enumeración vigente de lo que `frontend` reenvía hacia `private`**, que es la mitad (b) del invariante anterior: `frontend` reenvía **todo `/api/`** hacia `backend:8000` — los endpoints de `/api/v1` que `backend/openapi.json` publica, con su autorización intacta. Y nada más. `frontend` sigue siendo el único puente `ingress`→`private`.
- **Nota para cuando `private` gane servicios**: esa red tiene IPAM fijo **sin `ip_range`**, así que un servicio nuevo creado antes que `frontend` podría en teoría tomar `10.89.0.10`, la dirección de confianza del proxy. Es fail-loud —`frontend` no podría reclamar su IP estática y `compose up --wait` fallaría el deploy—, así que no requiere acción hoy; si esa red gana servicios, la salida es declarar un `ip_range` que excluya la dirección reservada.

### Camino a la API (`/api/`, desde `api-ingress-routing`)

- WHEN un cliente de internet solicita una ruta bajo `/api/` en el hostname público, THE
  SYSTEM SHALL entregarla al servicio `backend` por la red `private` y devolver su
  respuesta al cliente sin alterar método, cuerpo, código de estado ni el sobre de error
  `{"error": {...}}` de PRD §23.
- THE SYSTEM SHALL implementar ese reenvío como un Route Handler de Next
  (`frontend/app/api/[...path]/route.ts`) que resuelve el destino desde
  `BACKEND_INTERNAL_URL` **en tiempo de ejecución**, y THE SYSTEM SHALL NOT implementarlo
  como una `rewrite` de `next.config.ts`: los `destination` de las rewrites se serializan
  en `routes-manifest.json` durante `next build` y producción no vuelve a invocar
  `config.rewrites()`, así que la URL quedaría fijada al valor del job de CI — y como
  `next dev` sí la recarga, el fallo aparecería solo en el entorno desplegado.
- THE SYSTEM SHALL NOT añadir ninguna regla de ingress al túnel, hostname, registro DNS ni
  puerto al security list para servir este camino, y THE SYSTEM SHALL NOT conectar
  `cloudflared` a la red `private`.
- THE SYSTEM SHALL enrutar **únicamente** las rutas bajo `/api/`, y THE SYSTEM SHALL NOT
  enrutar `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` ni `/health`. Esos
  cuatro primeros son anónimos por allowlist (`backend/tests/test_route_authorization.py`)
  y hasta este change estaban protegidos **solo** por que el backend escuchaba en
  loopback; su no exposición es ahora una decisión explícita, sostenida por un test de
  alcance (`frontend/app/proxy-scope.test.ts`) y no por convención.
- WHEN el reenvío no puede alcanzar el backend, THE SYSTEM SHALL responder `502` con el
  sobre de PRD §23 y `code` `INTERNAL_ERROR`, y THE SYSTEM SHALL NOT incluir en la
  respuesta el nombre del servicio interno, la URL interna ni la causa — que van al log del
  servidor con prefijo `[api-proxy]`. El `code` es uno ya publicado a propósito:
  `backend/app/core/error_codes.py` es su fuente única y el contrato lo publica como
  `enum`, así que un código propio del proxy dejaría el switch exhaustivo del frontend
  exhaustivo sobre el conjunto equivocado.
- THE SYSTEM SHALL NOT declarar un tope de tamaño de cuerpo en el proxy. Medido: la opción
  `proxyClientMaxBodySize` **no existe** en Next 16.2.11, y no hace falta — el backend
  rechaza con `413` antes de leer el cuerpo y el handler reenvía en **streaming**
  (`duplex: "half"`), así que el rechazo llega sin que el proceso de Next acumule el
  cuerpo. El tope conserva un solo origen, en el backend.
- WHEN la respuesta del backend lleva un `Location` absoluto apuntando al origen interno,
  THE SYSTEM SHALL reescribirlo a la ruta equivalente del origen público, y THE SYSTEM
  SHALL NOT reenviar la cabecera `server` del backend. Sin esto, el `307` de
  `redirect_slashes` de Starlette publicaba `http://backend:8000/...` a cualquier llamante
  anónimo — el nombre y el puerto del servicio que el aislamiento mantiene fuera de
  internet — y mandaba al navegador a un host que no resuelve.
- THE SYSTEM SHALL rechazar, en el propio proxy, un `CF-Connecting-IP` con zone identifier
  o más largo que 45 caracteres, además de validarlo con `isIP`. Medido: `isIP` de Node
  **acepta** el zone identifier (`isIP("fe80::1%" + "z"*100)` devuelve `6`), así que
  validar solo con él reenviaría un valor de 108 caracteres que el backend tiene que
  descartar. Defensa en profundidad: el backend lo rechaza igualmente en su frontera
  (spec `auth-tenancy` §Identificación del cliente).

### El secreto del túnel y su lectura en el deploy

- THE SYSTEM SHALL guardar el token del túnel como `oci_vault_secret` de nombre `autohostai-<env>-cloudflare-tunnel-token`, con contenido en BASE64, generado íntegramente por Terraform.
- WHEN el job `deploy` renderiza el `.env` de runtime, THE SYSTEM SHALL leer ese secreto del Vault **por nombre** (`get-secret-bundle-by-name`, con el OCID del Vault desde una variable de repositorio) por instance principal, y THE SYSTEM SHALL fallar el deploy nombrando la clave si no puede leerlo, **antes de tocar contenedores**.
- THE SYSTEM SHALL resolver por nombre y no por OCID porque `cloud-init` escribe `/etc/autohostai-deploy.env` solo al crear la VM: el `metadata` de la instancia es ForceNew y lleva `ignore_changes`, así que una clave añadida después nunca llegaría a la máquina viva.
- THE SYSTEM SHALL autorizar esa lectura ampliando `oci_identity_policy.dev_runner_read_secrets` con el OCID del secreto en su condición `where any {...}`. El acceso al **contenido** de los secretos queda acotado por la enumeración explícita de OCID; un secreto nuevo es invisible para el runner hasta añadirlo.
- THE SYSTEM SHALL mantener esa policy con **un solo statement** (`read secret-bundles` condicionado por OCID) y THE SYSTEM SHALL NOT concederle `read secrets` ni condicionar el acceso por `target.secret.name`. Desde `ingress-https-hardening`: `GetSecretBundleByName` exige únicamente `SECRET_BUNDLE_READ`, que ese statement ya concede, y **medido en el entorno real** (2026-08-04) la resolución por nombre funciona con la condición por OCID, luego OCI resuelve nombre→OCID antes de autorizar. Una condición por nombre además ensancharía: `compartment_ocid` es la raíz de la tenancy y los nombres de secreto son únicos por *vault*, así que concedería lectura de contenido a cualquier secreto homónimo de la tenancy.
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
- `docker-compose.deploy.yml` — servicio `cloudflared`, el binding a loopback de `backend`/`frontend`, el ancla `x-frontend-private-ip` y el `--forwarded-allow-ips` del `backend`.
- `frontend/app/api/[...path]/route.ts` — el reenvío `/api/` → `backend:8000`; `frontend/app/proxy-scope.test.ts` — su test de alcance.
- `.github/workflows/deploy-dev.yml` — lectura del token por nombre y renderizado del `.env`.
- `.github/workflows/infra-dev.yml` — gating por rama de `plan` y `apply`.
- `docs/adr/0003-https-ingress-dev.md` — decisión y alternativas descartadas.
- `infra/environments/dev/RUNBOOK.md` §7 — bootstrap del token, diagnóstico, rotación y depuración por túnel SSH.
- `docs/ingress-https.md` — cómo se usa y se opera la capability.

## Estado y pendientes

- **Operativo y verificado en producción** (2026-07-29): HTTPS sirviendo la app con certificado válido, redirección desde HTTP, security list en `[22]`, acceso directo a la IP en 3000/8000 sin conectar, y depuración por `ssh -L` funcionando.
- El **bootstrap irreducible** de Cloudflare —el dominio con su zona y el API token del provider— se hace a mano una vez y está documentado en `steering/infra.md`.
- **Cerrado por `ingress-https-hardening`** (2026-08-04): `cloudflared` aislado en su propia red, la policy del runner reducida a un solo statement, y el radio de daño del API token corregido y enumerado de forma canónica en el Addendum de ADR 0003. Los tres verificados en el entorno desplegado.
- **Ampliado por `api-ingress-routing`** (2026-08-08): la API es alcanzable desde internet por el camino same-origin `/api/`, sin regla de ingress nueva ni puerto nuevo. El túnel SSH deja de ser la única vía documentada a `/api/v1`, y sigue siendo la única a `/docs`.
- **Sin verificar por comportamiento**: que la catch-all devuelva 404. La regla existe en el estado aplicado, pero observarla exigiría un hostname desechable apuntando al túnel.
- **Riesgo a vigilar**: la zona la gestionan además dos instancias de `external-dns` en `policy = "sync"`. El CNAME de Terraform no lleva su TXT de propiedad, así que en teoría no lo tocan; conviene confirmar que persiste.
