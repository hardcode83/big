# Design: api-ingress-routing

## Context

El túnel entrega a `http://frontend:3000` con **una sola** regla de ingress (`infra/environments/dev/main.tf:383-390`) y el enrutado vive en el edge (`config_src = "cloudflare"`), así que añadir un camino a la API sin tocar Terraform obliga a que el salto lo dé el propio frontend. `docker-compose.deploy.yml:59-61` declara `ingress` y `private` **sin IPAM** (subredes dinámicas), `frontend` es el único servicio en ambas (`:230`) y ya recibe `BACKEND_INTERNAL_URL` (`:232`); `backend` publica solo `127.0.0.1:8000` (`:127-128`) y `frontend` solo `127.0.0.1:3000` (`:243-244`).

En el frontend, `next.config.ts` tiene únicamente `output: "standalone"`, no existe `frontend/app/api/`, y `getServerConfig()` (`frontend/lib/config/server.ts:17-21`) ya expone `backendInternalUrl` desde `process.env` en runtime, marcado `server-only`. Next es `^16.2.11` con React 19.

En el backend, `get_client_ip()` (`backend/app/auth/api/dependencies.py:50-72`) toma el peer del socket salvo que `TRUSTED_CLIENT_IP_HEADER` esté configurada (viene vacía), y **no** comprueba el peer. No alimenta solo el throttle: es la fuente de `AuditLog.actor_ip` en `auth/api/users_router.py:115,172,200,230`, `auth/api/router.py:53` y `tenants/api/router.py:76` — regla 9 de `steering/security.md`. Uvicorn arranca sin flags de proxy (`backend/devops/Dockerfile:20,35`).

Topología resultante y frontera de confianza:

```
internet ──TLS──▶ Cloudflare edge ──(escribe CF-Connecting-IP,
                     │                sobreescribe la del cliente)
                     │  conexión SALIENTE del túnel
              red `ingress`
                     │
              cloudflared ──http──▶ frontend:3000
                                      │  app/api/[...path]/route.ts
                                      │  ▸ descarta cabeceras de reenvío del cliente
                                      │  ▸ escribe X-Forwarded-For que él deriva
                                 red `private`   ◀── único puente ingress→private
                                      │
                                  backend:8000
                                      │  peer = IP del frontend  →  ¿de confianza?
                                      ▼
                                get_client_ip() → throttle por IP + AuditLog.actor_ip
```

## Decisions

### D1 — Route Handler catch-all, **no** `rewrites` de `next.config.ts`

**Chosen:** un Route Handler en `frontend/app/api/[...path]/route.ts` que reenvía a `getServerConfig().backendInternalUrl`. Es el patrón que Next 16 documenta para esto (guía *Backend for Frontend*: `new Request(proxyURL, request)` + `fetch`), y es la única de las dos formas que lee la URL del backend **en runtime**, que es lo que R1.4 exige.

Y es una decisión de hecho, no de gusto: los `destination` de `rewrites` se **hornean en tiempo de build** dentro de `.next/routes-manifest.json` (`load-custom-routes.ts` llama a `config.rewrites()` una sola vez durante `next build`; `router-utils/filesystem.ts` lee el manifest en producción y **nunca** vuelve a invocar la función). `${process.env.BACKEND_INTERNAL_URL}` capturaría el valor presente en el job de GitHub Actions, donde no existe. Lo que hace la trampa peligrosa es su modo de fallo: en `next dev` sí se llama a `loadCustomRoutes` en cada arranque, así que **la vía `rewrites` funcionaría en local y fallaría solo en el entorno desplegado**.

Rejected:
- `rewrites` con `BACKEND_INTERNAL_URL` inyectada como build arg del Dockerfile — hornea la topología de despliegue en la imagen, que dejaría de ser la misma para todos los entornos con el mismo `IMAGE_TAG`.
- `rewrites` con `http://backend:8000` literal — viola R1.4 y tiene el mismo problema de imagen atada a un entorno.
- `proxy.ts` (el antiguo `middleware.ts`, renombrado en Next 16) — corre en **todas** las peticiones, incluidos los renders de página, y `frontend-auth-session` ya planea ser dueño de ese fichero para la protección de rutas; meter aquí el proxy de la API acopla dos asuntos sin relación en el único fichero cuyo coste paga cada petición.

### D2 — El handler **reescribe** la cabecera de IP; no la reenvía

**Chosen:** el handler construye la petición saliente **borrando** de la copia toda cabecera de reenvío controlable por el cliente (`x-forwarded-*`, `forwarded`, `cf-connecting-ip`, `true-client-ip`, `x-real-ip`) y las hop-by-hop (`connection`, `keep-alive`, `transfer-encoding`, `upgrade`, `te`, `trailer`, `proxy-*`), y **escribe** `X-Forwarded-For` con el valor que él deriva de `CF-Connecting-IP` tal como llegó del edge. `Host` se reescribe al del backend y `redirect: "manual"` evita que un 3xx del backend se persiga en el servidor.

Sin ese borrado la vía es insegura por construcción: el patrón documentado `new Request(proxyURL, request)` copia las cabeceras entrantes **literalmente**, así que un `CF-Connecting-IP` que envíe el cliente viajaría al backend, y el backend —que confía en el peer— lo creería. Es exactamente el bypass de R4.

**Residual, y se acepta por escrito en vez de diseñar contra él**: el servidor de Next también escucha en `127.0.0.1:3000` de la VM (publicación que `ingress-https-dev` conserva para depurar por `ssh -L`). Una petición que entre por ahí no viene del edge, así que su `CF-Connecting-IP` es el que enviara quien llama. Requiere SSH en la VM — una posición ya privilegiada, con la que además se llega directamente a `127.0.0.1:8000`.

Rejected: reenviar las cabeceras entrantes tal cual y confiar en que el edge las sobreescribe — cierto para el camino por el túnel, falso para el camino por loopback, y deja la garantía dependiendo de por dónde entró la petición.

### D3 — La comprobación del peer la hace `ProxyHeadersMiddleware` de uvicorn; `TRUSTED_CLIENT_IP_HEADER` se retira

**Chosen** (decidido con Jose el 2026-08-08): arrancar uvicorn con `--proxy-headers` explícito y `--forwarded-allow-ips=<IP del frontend>`, de modo que `scope["client"]` —y con él `request.client.host`— sea ya la IP real del cliente. `get_client_ip()` colapsa a devolver el peer, y `TRUSTED_CLIENT_IP_HEADER` **desaparece** de `config.py`, `.env.example` y los composes.

Tres razones, en orden de peso:

1. **Arregla todos los consumidores a la vez, no solo el throttle.** `get_client_ip()` alimenta `AuditLog.actor_ip` en cinco sitios (regla 9 de `steering/security.md`). Sin esto, en cuanto exista el proxy esas filas registrarían la IP del contenedor `frontend` en vez de la de la persona — una regresión silenciosa de la auditoría que el proposal no nombra porque se descubre leyendo el código.
2. **El algoritmo correcto ya está escrito y probado.** `_TrustedHosts.get_trusted_client_address` recorre `X-Forwarded-For` **de derecha a izquierda** y devuelve el primer salto **no** confiable, que es estrictamente mejor que «el de más a la derecha» de `auth-tenancy` cuando hay más de un proxy, y acepta **notación CIDR** además de IPs.
3. **Elimina el solapamiento, que es el riesgo real.** `proxy_headers` **viene a `True` por defecto** en uvicorn (`Config.__init__`), con `forwarded_allow_ips` a `127.0.0.1`. Es decir: hoy ya hay un mecanismo que reescribe `request.client.host` desde `X-Forwarded-For`, y nuestro `get_client_ip()` es un segundo mecanismo encima. Con los dos vivos, la comprobación del peer de R4 compararía contra un valor que el primero pudo haber reescrito desde entrada del atacante — una comprobación circular e inútil. Hay que **decidir explícitamente** cuál manda; dejarlo implícito es el bug.

Rejected: mantener `get_client_ip()` con su propia lista de proxies y pasar `--no-proxy-headers` para desactivar el de uvicorn — funciona y honra R4 al pie de la letra, pero reimplementa código ajeno ya probado y deja `AuditLog.actor_ip` correcto solo por el camino de esa función. Es la Opción B de OQ1.

**Dónde van los flags.** Los dos van al `CMD` de **ambos** stages de `backend/devops/Dockerfile`, y el `command:` del servicio `backend` de `docker-compose.deploy.yml` sobreescribe el CMD entero para poner el valor del entorno desplegado.

Lo que **no** va en la imagen es la IP de confianza del despliegue: es específica del entorno y hornearla repetiría el error que D1 rechaza para los `rewrites` — la imagen dejaría de ser la misma para todos los entornos con el mismo `IMAGE_TAG`. Lo que sí va en la imagen es el flag con un valor **que no confía en nadie** (`127.0.0.1`), por el motivo del párrafo siguiente.

Se descarta pasarlo por variable de entorno, y el motivo **cambió al medirlo** (corregido durante `/sdd:run`, hallazgo del panel de seguridad). La primera redacción decía que uvicorn solo configura por entorno con prefijo `UVICORN_` y que `FORWARDED_ALLOW_IPS` era «de gunicorn». **Es falso**: `uvicorn/config.py:356` de la 0.51.0 instalada hace `self.forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")` cuando el flag del CLI no está, y el propio `--help` lo documenta.

Eso no debilita la decisión, la refuerza y **añade una obligación**: una variable de entorno es precisamente el canal que no queremos, porque `docker-compose.yml:76` entrega al backend el `.env` entero por `env_file` y publica el 8000 en todas las interfaces. Quien añada el famoso `FORWARDED_ALLOW_IPS=*` a su `.env` depurando le daría a cualquiera de la LAN su propio contador de throttle y su propio `actor_ip`. Y un flag **ausente no es neutro**: delega la decisión al entorno.

Por eso el flag se pinea **en los dos stages del Dockerfile** a `127.0.0.1` («no confíes en nadie salvo el loopback de este contenedor»), y el `command:` del deploy es la **única** forma de ensancharlo. El CLI gana sobre el entorno, así que escribirlo cierra el canal por accidente.

**Solo a `backend`.** `worker` y `beat` usan la misma imagen pero sobreescriben `command:` con `celery` (`docker-compose.deploy.yml:143,174`): no hay servidor HTTP, así que ni el flag ni la lista tienen sentido ahí.

**El footgun de `_TrustedHosts`, y por qué aquí no muerde.** El upstream convierte **en silencio** cualquier entrada malformada en comparación literal de cadena, y su propio comentario dice que el usuario no puede detectarlo: un typo no falla, deja de confiar en nadie y el throttle vuelve a contar todo el despliegue en un contador, sin ruido. La defensa no es un test, es **estructural** — ver D4, donde el valor se declara una sola vez con un ancla de YAML y lo consumen las dos puntas. Un valor malformado hace fallar el `ipv4_address` y con él `compose up --wait`, o sea el deploy; y un valor válido es por construcción el mismo en las dos. Un **nombre de host** ahí tampoco se resuelve: sería un literal — por eso la vía DNS de D4 queda descartada.

### D4 — El frontend se identifica por IP estática /32 en `private`

**Chosen** (decidido con Jose el 2026-08-08): fijar `ipam.config.subnet` en la red `private` de `docker-compose.deploy.yml` y dar a `frontend` un `ipv4_address` en ella; ese /32 es el valor de `--forwarded-allow-ips`. Compose exige IPAM declarado para admitir `ipv4_address`, así que las dos mitades van juntas.

El /32 no es purismo: al publicar `127.0.0.1:8000:8000`, Docker hace SNAT de la conexión al **gateway del bridge**, que está dentro de la subred. Confiar en la subred entera haría de confianza a quien llegue por `ssh -L 8000`; el /32 lo excluye, y esa es la única diferencia material entre las dos opciones.

La subred elegida **no puede solaparse** con la VCN `10.0.0.0/16` (`infra/environments/dev/main.tf:53`, subred `10.0.1.0/24` en `:107`) ni con el pool por defecto de Docker (172.17–172.31): el candidato es `10.89.0.0/24`, y la restricción se anota junto a la declaración.

**La IP se declara UNA vez, con un ancla de YAML**, y la consumen las dos puntas: `frontend.networks.private.ipv4_address` y el `--forwarded-allow-ips` del `command:` de `backend`. Esto no es cosmética — hace **imposible por construcción** la clase de bug que D3 describe:

```yaml
x-frontend-private-ip: &frontend_private_ip "10.89.0.10"
```

Un valor malformado revienta el `ipv4_address` y con él `compose up --wait`, es decir el deploy, de forma visible; y un valor válido es necesariamente el mismo en las dos puntas, así que no hay deriva que un test tuviera que vigilar. Por eso este design **no añade** un test de la configuración resuelta: el guard es el fichero. Lo único que queda para la revisión humana y para `sdd-review-cicd` es que nadie escriba `*` ahí, que sería un acto deliberado y visible en el diff.

Rejected:
- Confiar en la subred entera de `private` — hoy es **dinámica** (sin IPAM), así que no hay valor que escribir en configuración; habría que resolverla al arrancar el contenedor.
- Resolver el nombre DNS `frontend` desde el backend — no requiere tocar el compose y sobrevive a reinicios, pero es **incompatible con D3**: uvicorn no resuelve nombres en `forwarded_allow_ips`, los compara como literales.
- Un secreto compartido en cabecera (`X-Internal-Proxy-Token`) en vez de identificar por peer — probaría el paso por el proxy sin depender de IPs, pero contradice R4.1 («el peer del socket») y añade un secreto más a la regla 8.

### D5 — Alcance del camino: solo `/api/`, y verificado por test de arquitectura

**Chosen:** el único fichero que reenvía es `frontend/app/api/[...path]/route.ts`, y el handler **construye** la URL saliente como `<backendInternalUrl>/api/<path>` a partir del segmento capturado — nunca concatenando la URL entrante. Todo lo que no case con `app/api/**` no existe como camino: `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` y `/health` caen en el 404 de la aplicación Next.

La garantía se fija con **dos** tests, porque cubren fallos distintos: uno de arquitectura al estilo de `frontend/app/route-coverage.test.ts` (recorre `app/` y falla si aparece un segundo `route.ts` que reenvíe, o si el catch-all cambia de sitio), y uno unitario sobre la construcción de la URL (un `path` con `..`, con `//` o vacío no puede producir una URL fuera de `/api/`). El backend no cambia: los cuatro endpoints siguen en `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py:25-33`, y lo que cambia es que dejan de estar protegidos por accidente y pasan a estarlo por alcance declarado.

Rejected: comprobar el 404 arrancando el servidor de Next en el test — la suite del frontend corre sin backend y sin servidor por diseño (`specs/frontend-foundation.md` §Testing), y un test de integración de esa clase pertenece a la verificación en el entorno desplegado (R2.2).

### D6 — Errores del proxy en el sobre de PRD §23

**Chosen:** si el `fetch` al backend falla (backend caído, DNS, timeout), el handler responde `502` con el sobre de PRD §23 —`{"error": {"code", "message", "details"}}`, la forma de `backend/app/core/errors.py:63`— sin nombre de servicio interno, sin URL interna y sin traza. Así el cliente tiene **una** forma de error para todo `/api/`, venga del backend o del salto.

**El `code` es `INTERNAL_ERROR`, no uno nuevo** (corregido durante `/sdd:run`; la primera redacción de esta decisión proponía `UPSTREAM_UNAVAILABLE`). El motivo es un invariante que ya existe y que un código inventado rompería: `backend/app/core/error_codes.py` es la **fuente única** de los `code` que pueden llegar a un cliente y `api-contract-export` los **publica como `enum`** en el contrato (su design D11). Su propio docstring nombra el fallo: un enum publicado al que le falta un código que el sistema devuelve de verdad es peor que no tener enum, porque el switch exhaustivo del frontend sería exhaustivo sobre el conjunto equivocado con el compilador dando fe. Añadir el código al enum del backend tampoco vale: metería en el contrato un valor que el backend **nunca** devuelve, y contradice que `make openapi` no debe producir diff en este change.

Y la distinción que se pierde no le sirve a quien recibe la respuesta: «el backend tiene un bug» y «el proxy no alcanzó el backend» son ambos «5xx, no es culpa tuya, reintenta». A quien sí le sirve es al operador, que la obtiene del log del servidor de Next — que es donde el handler la escribe.

Rejected: `code` propio del proxy (`UPSTREAM_UNAVAILABLE`) — rompe la fuente única de `error_codes.py`. Añadirlo al enum del backend — publica en el contrato un código que el backend no emite.

No añade strings de UI: es JSON de máquina, así que no entra en `locales/es`/`locales/en` y `steering/frontend.md` §i18n no aplica. Conviene decirlo porque el reviewer de i18n corre sobre este diff.

Rejected: dejar escapar el error por defecto de Next — devuelve una página HTML de error a un cliente que espera JSON, y su cuerpo depende de la versión del framework.

### D7 — Paridad de camino sí, paridad de confianza no

**Chosen:** el camino `/api/` tiene la misma forma en `docker-compose.yml` y en `docker-compose.deploy.yml` (el frontend llama siempre a la URL relativa `/api/v1/...`), pero **la confianza en la cabecera queda desactivada en local**: `--forwarded-allow-ips` no se configura en el compose local, así que allí manda el peer del socket.

Es la única opción defendible, y el motivo está en el propio compose local: `docker-compose.yml:109` publica `8000:8000` **en todas las interfaces a propósito** (el proyecto es mobile-first y se prueba desde el móvil por la IP de LAN). Con un puerto abierto a la LAN y la confianza activada, la cabecera la pone quien llama: cualquiera que comparta red con la máquina se daría un presupuesto nuevo de 10/min en cada petición. En local eso no protege nada y sí abre el bypass; el throttle degradado a «un contador para todo» es el precio correcto en un entorno sin datos reales.

**Corrección de la justificación** (hallazgo del panel de seguridad durante `/sdd:run`, y la corrección importa aunque la decisión no cambie): la primera redacción afirmaba que un cliente de la LAN «aparece **SNATeado** como el gateway del bridge, dentro de cualquier lista basada en subred». Eso **no está medido y depende del ajuste `userland-proxy` del demonio**, que este repositorio no fija ni comprueba — para tráfico que llega por la IP de LAN del host, el DNAT de Docker normalmente **preserva** la IP de origen, y solo el tráfico originado en loopback se enmascara al gateway. La regla 8 de `steering/security.md` ya tiene precedente exacto de este defecto: una exención razonable cuya justificación describía una postura que el compose no implementaba. La decisión aguanta por el argumento simple y verificable —puerto publicado a la LAN ⇒ cabecera suministrada por quien llama—, que no necesita saber cómo enmascara Docker. El comportamiento real se mide en 6.6.

Rejected: activar la confianza en local para que el comportamiento sea idéntico — igualaría el comportamiento del throttle a cambio de un bypass real en la máquina de cada desarrollador.

### D8 — El tope de cuerpo del camino público iguala el del backend, con un solo número

**Decidido con Jose el 2026-08-08 como «igualar los 10 MB con `proxyClientMaxBodySize`», y CORREGIDO por medición durante `/sdd:run`: no hay tope en el proxy, y no hace falta ninguno.**

Dos hechos, los dos medidos y no supuestos:

1. **`proxyClientMaxBodySize` no existe en la versión pineada.** Next 16.2.11 lo rechaza al arrancar: `⚠ Unrecognized key(s) in object: 'proxyClientMaxBodySize'`. La documentación que lo describe es de `canary`. La duda que la tarea 2.6 planteaba —si aplicaría a un Route Handler sin `proxy.ts`— resultó estar mal planteada: la opción no está disponible en absoluto.
2. **El tope ya se aplica, y en el sitio correcto.** `backend/app/main.py:62-66` monta `MaxBodySizeMiddleware` sobre `/api/v1/integrations/` con `CSV_IMPORT_MAX_BYTES`, y rechaza con `413` **antes de leer el cuerpo** (pura ASGI, a propósito, según su propio docstring). Como el handler reenvía el cuerpo **en streaming** (`duplex: "half"`), ese rechazo llega mientras el cuerpo se está enviando y el proceso de Next nunca lo acumula.

Medido en el stack local, con el control positivo al lado:

| Petición | Resultado |
|---|---|
| 12 MB por el proxy | `413 PAYLOAD_TOO_LARGE`, sobre del backend, mensaje citando `10485760` |
| 12 MB directo al backend (control) | idéntico |
| 1 KB por el proxy | `401 INVALID_TOKEN` — la cadena completa llega hasta la autenticación |

**Esto es mejor que la decisión original, no una renuncia**: el número sigue teniendo **una sola casa** (`CSV_IMPORT_MAX_BYTES`, que es la regla 6 de `steering/security.md`) en vez de dos que había que mantener en paralelo — el riesgo que la propia decisión original nombraba y aceptaba. La importación CSV funciona igual por el camino público que por túnel.

Rejected: duplicar el tope en el frontend si algún día `proxyClientMaxBodySize` llega a estable — sería un segundo origen del mismo número sin nada que los mantenga en paralelo. Tope bajo dejando la importación CSV solo por túnel SSH — obligaría a declarar que un endpoint publicado en `backend/openapi.json` no es alcanzable por el camino público.

### D11 — Todo `/api/v1/` lleva tope de cuerpo, con un número propio para las subidas

**Añadida durante `/sdd:run`** por el hallazgo 1 del panel de seguridad de la sección 2, y es una **ampliación de alcance al backend** que hay que declarar, no colar.

`MaxBodySizeMiddleware` estaba acotado a `/api/v1/integrations/`, y su docstring razonaba que un número global sería «demasiado pequeño para un CSV o demasiado grande para un login». La premisa era buena y la conclusión no se seguía: lo que un login necesita no es *ningún* tope, es un tope **pequeño**. Mientras el backend escuchaba solo en loopback el hueco no costaba nada. En cuanto `/api/v1` es alcanzable desde internet, es un **amplificador de memoria anónimo** — y está medido: un `POST /api/v1/auth/login` de 400 MB por el camino público llevó al contenedor de 195 MiB a 1,016 GiB de RSS en 2,3 s, y FastAPI lee ese cuerpo **antes** de resolver dependencias, así que ocurre antes de que el throttle de 10/min se consulte siquiera. Ningún compose pone límite de memoria a `backend`, así que el techo es el de la VM.

**Este change lo posee** porque este change crea la exposición: la regla 12(c) de `steering/security.md` exige tope de tamaño para escritura anónima desde internet, y la regla 6 fija el patrón de «máximo configurable».

Solución: el middleware pasa a cubrir `API_V1_PREFIX` completo, y su `max_bytes_provider` recibe **la ruta**, de modo que `/api/v1/integrations/` conserva `CSV_IMPORT_MAX_BYTES` (10 MiB) y todo lo demás usa un `REQUEST_MAX_BYTES` nuevo (1 MiB por defecto). Dos instancias de middleware no valen: se anidan, así que la genérica rechazaría el CSV antes de que la específica lo viera.

Medido después: 12 MB a `/auth/login` → `413` en 242 ms (antes `422` tras leerse el cuerpo entero), login normal → `401`, 12 MB a `import-csv` → `413` por su propio techo.

Rejected: dejar el hueco y confiar en el throttle — se lee el cuerpo antes que el throttle, así que no llega a tiempo. Un solo número global — o rompe el CSV o no significa nada para un login, que es el razonamiento original y sigue siendo cierto.

### D9 — No se añade `PORT_OFFSET`; la verificación local se hizo desde este worktree

**Chosen** (decidido con Jose el 2026-08-08): R2.2 y R6.1 se comprueban en local con el stack del **checkout principal**, no desde este worktree. No se parametrizan los puertos.

Motivo: `PORT_OFFSET` toca el `Makefile`, los dos composes y `docker-compose.worktree.yml`, es un asunto distinto del ingress y su riesgo es romper `make up` para todo el mundo. `project.md` deja la salida escrita a propósito para «cuando haga falta», y hacerla falta aquí sería ampliar el alcance de un change de infra de ingress a uno de herramientas de desarrollo. R3.2 y R5.3 no se ven afectados: van contra el entorno desplegado, alcanzable desde cualquier sitio.

Consecuencia operativa que las tareas deben recoger: la tarea de verificación local dice explícitamente **dónde** se ejecuta, porque desde este worktree no hay `curl localhost:3000` posible y descubrirlo a mitad de `/sdd:run` cuesta una sesión.

**Corrección medida durante `/sdd:run`, y hace la decisión más barata de lo que parecía**: la premisa «desde el worktree no se puede sondear el camino» era **demasiado fuerte**. Lo que falta en un worktree enlazado son los puertos publicados **en el host**; dentro de la red de compose no falta nada. Así que `docker compose exec -T frontend node -e 'fetch("http://localhost:3000/...")'` sondea el Route Handler y el backend igual de bien, y con eso se verificaron R1.1, R2.1, R2.2 y R6.1 **desde este worktree**, con control positivo (`/openapi.json` da 404 por el proxy y 200 directo al backend). No hizo falta el checkout principal ni `PORT_OFFSET`. Lo único que sigue sin existir es el **navegador**, que no hace falta para estas comprobaciones porque son de protocolo, no de interfaz.

### D10 — R1.2/R1.3 no tienen implicación de diseño: son restricciones que se verifican, no cosas que se construyen

**Chosen:** no se toca `infra/environments/dev/main.tf` ni el `networks:` de `cloudflared`. R1.2 (ninguna regla de ingress, hostname, DNS ni puerto nuevos) y R1.3 (`cloudflared` fuera de `private`, `backend` en loopback) se cumplen por **no hacer nada** en esos ficheros, y se comprueban con el `sdd-review-cicd` del panel más una lectura del diff. Lo que sí exige escritura es R6.3: la cláusula WHERE de `specs/ingress-https-dev.md` §Aislamiento obliga a enumerar qué reenvía el origen público hacia `private`, y a partir de este change la respuesta deja de ser «nada» y pasa a ser «`/api/` completo». Eso es documentación normativa, no código.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Frontend — proxy | `frontend/app/api/[...path]/route.ts` (nuevo) | Route Handler catch-all para todos los métodos; construye la URL desde `getServerConfig().backendInternalUrl` (D1), sanea cabeceras y escribe `X-Forwarded-For` (D2), errores en sobre §23 (D6), `runtime = "nodejs"` y `dynamic = "force-dynamic"` explícitos |
| Frontend — tests | `frontend/app/api/[...path]/route.test.ts` (nuevo), `frontend/app/proxy-scope.test.ts` (nuevo) | Unitario de saneado de cabeceras y construcción de URL; test de arquitectura de alcance (D5) |
| Frontend — config | `frontend/next.config.ts` | **Sin `rewrites`** (D1) y **sin tope de cuerpo**: `proxyClientMaxBodySize` no existe en Next 16.2.11 y el tope vive en el backend (D8, D11) |
| Backend — identidad del cliente | `backend/app/auth/api/dependencies.py`, `backend/app/core/config.py` | `get_client_ip()` colapsa al peer; retirada de `trusted_client_ip_header` y de la nota de limitación conocida (D3, R4.5) |
| Backend — arranque | `backend/devops/Dockerfile` | `--proxy-headers` **y** `--forwarded-allow-ips 127.0.0.1` pineados en **ambos** stages: un flag ausente delega la decisión a la variable de entorno `FORWARDED_ALLOW_IPS` (D3). La IP del despliegue **no** entra aquí; llega por el `command:` del compose |
| Backend — tests | `backend/tests/auth/` | Peer de confianza / peer no de confianza con cabecera falsificada / varias apariciones / valor no parseable (R4.4) |
| Compose deploy | `docker-compose.deploy.yml` | Ancla `x-frontend-private-ip`, `ipam.config.subnet` en `private`, `ipv4_address` de `frontend`, y `command:` de `backend` con los dos flags (D3, D4). **Solo `backend`**: `worker` y `beat` corren `celery`, no uvicorn |
| Compose local | `docker-compose.yml` | Nada, o a lo sumo un comentario: la confianza queda desactivada a propósito (D7) |
| Config de entorno | `.env.example` | Retirada de `TRUSTED_CLIENT_IP_HEADER` (líneas 59-62) y, si procede, la variable nueva documentada |
| Docs | `docs/ingress-https.md`, `infra/environments/dev/RUNBOOK.md` §7.4 | El camino `/api/` como vía normal, sin borrar el túnel SSH (R6.4) |
| Specs (al archivar) | `sdd/specs/ingress-https-dev.md`, `auth-tenancy.md`, `api-contract.md`, `frontend-foundation.md`, `local-environment.md`, `app-deploy-dev.md` | Los del proposal |

## Data & interfaces

- **Sin cambios de esquema.** Ninguna migración, ninguna entidad, ningún endpoint nuevo en el backend.
- **Variables de entorno**: entra **una**, `REQUEST_MAX_BYTES` (D11, R7). La primera redacción de esta línea decía «ninguna entra» y dejó de ser cierta al añadirse el tope de cuerpo — lo señaló el panel de seguridad de `/sdd:review`, que además midió que la variable **sí** surte efecto desde el `.env` (`Settings().request_max_bytes` = lo que se le ponga), y el backend recibe el fichero entero por `env_file`. Va documentada en `.env.example` junto a `CSV_IMPORT_MAX_BYTES`, con el motivo para no subirla.
- **La IP de confianza no es una variable**, y esa asimetría es deliberada: viaja como argumento del `command:` de `backend` (D3), así que no toca `.env.example`, ni el `.env` de runtime que renderiza `deploy-dev.yml`, ni el Vault.
- Lo que **sale** es `TRUSTED_CLIENT_IP_HEADER`, de `config.py`, `.env.example`, el docstring de `dependencies.py` y `docs/auth-tenancy.md`. Ninguna de las tres es un secreto, así que la regla 8 de `steering/security.md` no entra en juego.
- **Contrato HTTP**: sin cambios en `backend/openapi.json`. El camino es transporte; las rutas, los cuerpos y el sobre de error son los que ya están publicados. `make openapi` no debe producir diff, y si lo produce es señal de que este change se salió de su alcance.
- **Interfaz interna nueva**, la única: el contrato del handler es «`/api/<resto>` → `<backendInternalUrl>/api/<resto>`, método, cuerpo y cabeceras saneadas, respuesta tal cual». No hay tipos compartidos con `frontend/lib/api/client.ts`: ese cliente seguirá llamando a rutas relativas y no sabe que hay un salto.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **La propagación de IP no funciona y no se nota.** Es el único desconocido real del proposal (R3.2). El modo de fallo es silencioso: el camino funciona, el throttle cuenta todo el despliegue en un contador y `AuditLog.actor_ip` registra la IP del contenedor | Verificación **por observación** en el entorno desplegado antes de dar R1 por cumplido, y R3.3 obliga a `BLOCKED.md` si no se consigue. La observación tiene control positivo barato: dos clientes con IP pública distinta (portátil y móvil por datos) deben caer en contadores distintos (R5.2) |
| **Typo en `--forwarded-allow-ips`**, que uvicorn convierte en literal en silencio y sin dejar de arrancar | Ancla de YAML: un solo literal alimenta el `ipv4_address` y la lista de confianza (D4). Malformado revienta el deploy; válido es el mismo en las dos puntas. No hace falta test |
| **La IP estática del `frontend` colisiona** con la VCN o con el pool de Docker, y el deploy no arranca | Subred fuera de `10.0.0.0/16` y de 172.17–172.31 (D4), y la restricción anotada en el fichero. El fallo sería en `compose up --wait`, o sea visible y en el deploy, no en producción silenciosa |
| **Superficie nueva**: `/api/v1` pasa a ser alcanzable desde internet, y con ella el login anónimo | Es el objetivo del change, no un efecto. Lo que lo acota: R2 (solo `/api/`), el throttle de R5 funcionando de verdad, y que el resto de `/api/v1` exige Bearer JWT — garantía que `backend/tests/test_route_authorization.py` ya prueba ruta por ruta |
| **El salto extra añade latencia y un punto de fallo** en el camino de datos del navegador | Es inherente a la vía same-origin y ya estaba aceptado al elegirla. `depends_on: backend: service_healthy` (`docker-compose.deploy.yml:245-247`) ya existe, así que el frontend no se anuncia sano antes que el backend |
| **`frontend` deja de ser «capacidad, no uso»** como su comentario dice hoy (`docker-compose.deploy.yml:219-226`), y con ello crece el radio del puente `ingress`→`private` | R6.3: la enumeración se escribe en la spec, y el comentario del compose se corrige en el mismo diff para que no siga afirmando lo contrario |
| **Verificación local imposible desde este worktree**: un worktree enlazado no publica puertos (`docker-compose.worktree.yml`), así que no hay `curl localhost:3000` desde el host | Resuelto, y la premisa era demasiado fuerte (D9, corregido al medirlo): dentro de la red de compose no falta nada, así que `docker compose exec -T frontend node -e 'fetch(...)'` sondea el camino igual. R2.2 y R6.1 se verificaron **desde este worktree** |
| **Retirar `TRUSTED_CLIENT_IP_HEADER` deja referencias colgando** en `.env.example:59-62`, `specs/auth-tenancy.md` §Identificación del cliente, `docs/auth-tenancy.md` y el docstring de `dependencies.py` | R4.5 ya lo exige para dos de ellos; la tarea barre los cuatro con un `grep` del nombre de la variable como criterio de hecho, no como revisión a ojo |

## Open questions

Ninguna abierta. Las cuatro que este design planteó se resolvieron con Jose el 2026-08-08, y **dos de las respuestas cambiaron después al medirlas** — se listan por su estado final, no por el que tenían al decidirse: **D3** (la comprobación del peer la hace uvicorn, `TRUSTED_CLIENT_IP_HEADER` se retira, y el flag se pinea en ambos stages porque su ausencia delega en una variable de entorno), **D4** (IP estática /32 con IPAM fijado en `private`, declarada una vez con un ancla), **D8+D11** (no hay tope en el proxy: la opción no existe en Next 16.2.11, y el tope vive en el backend cubriendo todo `/api/v1/` con un número por prefijo) y **D9** (la verificación local se hizo **desde este worktree**, sondeando dentro de la red de compose; no hizo falta el checkout principal ni `PORT_OFFSET`).

Queda **un desconocido de hecho, no de decisión**, y está gobernado por el propio proposal: si la propagación de la IP real no se consigue por esta vía, R3.3 obliga a registrarlo en `BLOCKED.md` antes de dar R1 por cumplido, en vez de entregar el camino con el throttle degradado en silencio. La medición de D8 tiene la misma naturaleza: si `proxyClientMaxBodySize` no aplica al Route Handler, se decide de nuevo con el dato delante.
