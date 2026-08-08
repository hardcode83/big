# Spec deltas — api-ingress-routing

Texto ya redactado para que `/sdd:archive` lo lleve a las specs vivas. Existe porque la
regla compartida 1 reserva la escritura de `sdd/specs/` al archivado, y redactarlo aquí
—con el código delante— evita reconstruirlo de memoria semanas después.

---

## `sdd/specs/ingress-https-dev.md`

### Sección nueva, tras «Aislamiento de red del túnel»: «Camino a la API (`/api/`)»

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
  anónimo — el nombre y el puerto del servicio que R1.3 mantiene fuera de internet — y
  mandaba al navegador a un host que no resuelve.
- THE SYSTEM SHALL rechazar, en el propio proxy, un `CF-Connecting-IP` con zone identifier
  o más largo que 45 caracteres, además de validarlo con `isIP`. Medido: `isIP` de Node
  **acepta** el zone identifier (`isIP("fe80::1%" + "z"*100)` devuelve `6`), así que
  validar solo con él reenviaría un valor de 108 caracteres que el backend tiene que
  descartar. Defensa en profundidad: el backend lo rechaza igualmente en su frontera.

### Nota para cuando `private` gane servicios

`private` tiene ahora IPAM fijo **sin `ip_range`**, así que un servicio nuevo creado antes
que `frontend` podría en teoría tomar `10.89.0.10`, que es la dirección de confianza. Es
fail-loud —`frontend` no podría reclamar su IP estática y `compose up --wait` fallaría el
deploy—, así que no requiere acción hoy; pero si esa red gana servicios, la salida es
declarar un `ip_range` que excluya la dirección reservada.

### Cláusula que se satisface, en «Aislamiento de red del túnel»

La cláusula `WHERE se necesite publicar un origen público nuevo` exige enumerar lo que un
origen de `ingress` reenvía hacia `private`. Enumeración vigente tras este change, y el
comentario de `docker-compose.deploy.yml` que decía «capacidad, no uso» ya está corregido:

- `frontend` reenvía **todo `/api/`** hacia `backend:8000` — los endpoints de `/api/v1` que
  `backend/openapi.json` publica, con su autorización intacta.
- Y nada más. `frontend` sigue siendo el único puente `ingress`→`private`.

### Añadir a «Estado y pendientes»

- **Ampliado por `api-ingress-routing`** (2026-08-08): la API es alcanzable desde internet
  por el camino same-origin `/api/`, sin regla de ingress nueva ni puerto nuevo. El túnel
  SSH deja de ser la única vía documentada a `/api/v1`, y sigue siendo la única a `/docs`.

---

## `sdd/specs/auth-tenancy.md`

### Sustituir íntegra la sección «Identificación del cliente»

- THE SYSTEM SHALL usar **la IP del peer del socket** como identidad del cliente, y THE
  SYSTEM SHALL NOT leer ninguna cabecera de reenvío en código de aplicación.
- THE SYSTEM SHALL delegar la resolución de la cabecera de proxy en
  `ProxyHeadersMiddleware` de uvicorn, arrancado con `--proxy-headers` y con
  `--forwarded-allow-ips` nombrando explícitamente los peers de confianza, de modo que
  `scope["client"]` ya sea la IP real del cliente cuando —y solo cuando— la petición viene
  de un proxy de confianza.
- THE SYSTEM SHALL pinear `--forwarded-allow-ips` en **ambos** stages de
  `backend/devops/Dockerfile`, porque un flag ausente no es neutro: uvicorn cae entonces a
  la variable de entorno `FORWARDED_ALLOW_IPS` (`uvicorn/config.py:356`), que el backend
  recibe por `env_file` junto al resto del `.env`. El flag del CLI gana sobre el entorno, y
  el `command:` del compose de deploy es la única vía para ensanchar la lista.
- WHERE el entorno es el desplegado, THE SYSTEM SHALL fijar esa lista a la dirección
  estática del contenedor `frontend` en `private`, declarada **una sola vez** con un ancla
  de YAML que alimenta tanto su `ipv4_address` como el `--forwarded-allow-ips` del
  `backend`. Un valor malformado impide arrancar el contenedor y con él el deploy, en vez de
  degradar el límite en silencio — uvicorn convierte cualquier entrada inválida de esa
  lista en una comparación literal de cadena sin avisar.
- THE SYSTEM SHALL usar un **/32** y no la subred, porque la subred contiene a los demás
  servicios: medido en el deploy real, `private` alberga `postgres`, `redis`, `backend`,
  `worker`, `beat`, `migrate` y `frontend`, de los cuales **uno solo** es el proxy. Confiar
  en la subred sería autorizar a seis servicios a reportar la dirección de un cliente.
- WHERE el entorno es el local, THE SYSTEM SHALL NOT confiar en ningún peer
  (`--forwarded-allow-ips 127.0.0.1`), porque `docker-compose.yml` publica el 8000 en todas
  las interfaces a propósito y con un puerto abierto a la LAN la cabecera la suministra
  quien llama. Consecuencia aceptada: el límite por IP degrada a un contador único.
- WHEN el valor resuelto no es una dirección IP, o es **IPv6 con zone identifier**, o
  excede los 45 caracteres de `audit_logs.actor_ip`, THE SYSTEM SHALL usar `127.0.0.1`.
  Delegar en uvicorn da la selección del salto correcta pero **no** la validación: devuelve
  el primer salto no confiable literalmente. Y «parsea como IP» no bastaba, porque el texto
  tras `%` de un zone identifier es casi libre: medido, un zone rotatorio daba un contador
  de throttle nuevo por petición, un zone con CR/LF forjaba líneas en el log de login, y uno
  largo hacía lanzar `AuditContractError`, abortando la transacción de la operación
  auditada. Un zone identifier es ámbito link-local de una máquina y nunca describe
  legítimamente a un cliente remoto.
- THE SYSTEM SHALL canonicalizar la dirección y colapsar las formas IPv4-mapped sobre su
  IPv4, de modo que `::ffff:1.2.3.4` y `1.2.3.4`, o dos grafías del mismo IPv6, sean un
  único contador y un único `actor_ip`.
- **La «Limitación conocida» de esta sección se retira**: la comprobación del peer existe, y
  ya no hay ajuste `TRUSTED_CLIENT_IP_HEADER` que activar. Un `.env` que lo lleve no hace
  nada.

### Añadir a «Protección de los endpoints de autenticación»

- WHERE la API se sirve por el camino público, THE SYSTEM SHALL contabilizar el límite de
  10 intentos/min contra la dirección real del cliente y no contra la del proxy, de modo
  que dos clientes distintos no compartan presupuesto y ninguno pueda agotar el del otro.
- **Residual nuevo, y conviene que la spec lo diga en vez de que alguien lo re-derive**
  (hallazgo del panel de tenencia): el contador es **por IP y global**, no por tenant, y
  eso no cambia — pero con la API alcanzable desde internet, usuarios de **tenants
  distintos** detrás de un mismo NAT o CGNAT comparten ahora presupuesto de login, un
  escenario que no era alcanzable mientras el backend escuchaba solo en loopback. No viola
  la regla 1 (no cruza ningún dato entre tenants) ni la 7 (el límite es por IP, como pide);
  es equidad y disponibilidad. El bloqueo **por cuenta** sí está acotado por `user_id`, que
  es único global, así que un ataque contra la cuenta de un tenant no bloquea la de otro.
- WHERE `POST /api/v1/auth/refresh` es alcanzable desde internet, THE SYSTEM SHALL
  aplicarle el **mismo** límite por IP que a `login`, comprobado **antes** de decodificar el
  token presentado, respondiendo `429` con `code` `RATE_LIMITED` (R8). El endpoint es
  anónimo por diseño —el refresh token es la credencial— y acuña access tokens, así que
  publicarlo sin medir habría dejado una operación de credenciales con un molinillo
  ilimitado. Se descubrió porque los documentos de `api-ingress-routing` acotaban la
  superficie como «throttle + Bearer» y este endpoint no estaba cubierto por ninguno.
- THE SYSTEM SHALL contabilizar `login` y `refresh` en **un solo** contador por IP, y THE
  SYSTEM SHALL NOT darle a `refresh` un presupuesto propio: partirlo permitiría gastar dos
  presupuestos desde una dirección. Coste aceptado: un refresh legítimo puede recibir `429`
  si ese cliente ya gastó el presupuesto — con access tokens de 15 minutos, unos pocos
  refresh por hora contra un techo de diez por minuto.

---

### Sección nueva: «Tope de tamaño de cuerpo» (o ampliar la existente si la hay)

- THE SYSTEM SHALL aplicar un tope de tamaño de cuerpo a **todo** `/api/v1/`, antes de leer
  el cuerpo, respondiendo `413` con `code` `PAYLOAD_TOO_LARGE`.
- THE SYSTEM SHALL usar `CSV_IMPORT_MAX_BYTES` (10 MiB) para `/api/v1/integrations/` y
  `REQUEST_MAX_BYTES` (1 MiB) para el resto, resolviendo el límite **por ruta** en una sola
  instancia de middleware: dos instancias se anidan, así que la genérica rechazaría la
  subida antes de que la específica la viera.
- **Por qué deja de estar acotado a las subidas**: mientras el backend escuchaba solo en
  loopback, un cuerpo sin tope en un endpoint anónimo no costaba nada. Con `/api/v1`
  alcanzable desde internet es un amplificador de memoria — medido, un `POST` de 400 MB a
  `/auth/login` llevó el contenedor de 195 MiB a 1,016 GiB de RSS, y FastAPI lee el cuerpo
  **antes** de resolver dependencias, o sea antes del throttle de 10/min. Ningún compose
  limita la memoria de `backend`, así que el techo era el de la VM. Regla 12(c) y regla 6 de
  `steering/security.md`.

---

## `sdd/specs/api-contract.md`

- THE SYSTEM SHALL mantener `/openapi.json`, `/docs`, `/docs/oauth2-redirect` y `/redoc`
  **fuera del camino público**: siguen en la allowlist anónima y siguen siendo alcanzables
  solo desde la VM (túnel SSH). Decisión explícita que el panel de seguridad de
  `api-contract-export` dejó pendiente para `api-ingress-routing`; el contrato que consume
  el frontend es `backend/openapi.json` versionado, así que exponer `/docs` no aportaría
  nada que compense publicar la forma completa de la API.

---

## `sdd/specs/frontend-foundation.md`

- §Configuration: THE SYSTEM SHALL mantener `BACKEND_INTERNAL_URL` server-only, y
  `frontend/app/api/[...path]/route.ts` SHALL ser el **único** módulo de `app/` que lo lee
  (a través de `getServerConfig()`), verificado por `frontend/app/proxy-scope.test.ts`. Deja
  de ser cierto que ningún código lo consuma; sigue siendo cierto que no se lee en el
  render del shell.

---

## `sdd/specs/local-environment.md`

- §Postura de red del stack local: el camino `/api/` existe con la **misma forma** que en el
  desplegado, de modo que el frontend use siempre la misma URL relativa; la **confianza en
  cabeceras de proxy no**, y el motivo es el mapeo `8000:8000` en todas las interfaces que
  esa misma sección justifica.
