# Proposal: api-ingress-routing

## Why

Hoy la API no tiene ningún camino desde internet. El túnel de Cloudflare enruta **una sola** regla —`hostname` → `http://frontend:3000`— y `backend` se publica solo en `127.0.0.1:8000` de la VM (`docker-compose.deploy.yml:127-128`), así que `/api/v1` únicamente se verifica por túnel SSH (`RUNBOOK §7.4`). Mientras nada llamaba al backend eso no era deuda, y esta entrada se aplazó dos veces por ese motivo (2026-08-02 y 2026-08-04) con condiciones de disparo observables.

**Lo que la reabre**: el 2026-08-07 el roadmap separó **`frontend-auth-session`** de `dashboard-web` y le puso `needs: api-ingress-routing`. Su entrega es un formulario de login real contra `POST /api/v1/auth/login` **desde el navegador**, es decir exactamente el consumidor que la primera condición de disparo describía («el instante en que el navegador necesita el camino»), solo reubicado a una entrada anterior. La `frontier` lo confirma: esta entrada es trabajable y `frontend-auth-session` está bloqueada tras ella. La deuda deja de ser latente.

Verificado en código el 2026-08-07, no supuesto:

- `frontend/next.config.ts` no tiene `rewrites` (solo `output: "standalone"`).
- `frontend/lib/config/public.ts:95-107` no expone ningún `apiBaseUrl`; `createApiClient()` (`frontend/lib/api/client.ts:88`) nunca se invoca fuera de su test.
- `frontend` está en las redes `private` **e** `ingress`; `cloudflared` solo en `ingress`. R1.2 de `ingress-https-hardening` está en vigor: `cloudflared` no resuelve `backend`.
- `TRUSTED_CLIENT_IP_HEADER` viene vacía (`.env.example:62` comentada, ausente de los dos composes) y `get_client_ip()` honra la cabecera **sin comprobar el peer** (`backend/app/auth/api/dependencies.py:53-68`).
- `/docs`, `/docs/oauth2-redirect`, `/redoc` y `/openapi.json` siguen en `ANONYMOUS_ENDPOINTS` (`backend/tests/test_route_authorization.py:25-33`).

**Análisis heredado que este proposal asume y no vuelve a derivar** (entrada del roadmap, revisiones del 2026-08-02 y 2026-08-04): no hace falta *exponer el backend*; hace falta que el navegador llegue a `/api` **en el propio origen público del frontend**. Con un camino same-origin bajo el hostname que ya es público, el backend sigue inalcanzable desde internet y no hace falta CORS ni un segundo certificado. Las otras dos vías conocidas están cerradas: una segunda regla de ingress hacia `backend:8000` choca de frente con el aislamiento de red del túnel (`specs/ingress-https-dev.md` §Aislamiento, que deja a `cloudflared` sin poder resolver `backend` a propósito), y abrir puerto en el security list reabre lo que ADR 0003 cerró.

Fuentes: entradas `api-ingress-routing` y `frontend-auth-session` de `sdd/roadmap.md`; `sdd/specs/ingress-https-dev.md`; `sdd/specs/auth-tenancy.md` §«Protección de los endpoints de autenticación» y §«Identificación del cliente»; `docs/adr/0003-https-ingress-dev.md` §Addendum 2026-08-04; `sdd/steering/security.md` reglas 1 y 7.

## What changes

Después de este change, una petición del navegador a `https://<hostname público>/api/v1/...` llega al backend por la red interna del compose, y el backend ve la **IP real del cliente** en vez de la del proxy. Aparece un único camino nuevo, acotado a `/api/`, sin regla de ingress nueva en el túnel, sin hostname nuevo, sin puerto nuevo en el security list y sin ampliar el alcance de red de `cloudflared`. Con el proxy existiendo de verdad, se cierran las dos deudas que `auth-tenancy` dejó anotadas y solo se pueden cerrar aquí: honrar la cabecera de IP **solo** cuando el peer del socket es un proxy de confianza, y que el límite de 10 intentos/min/IP vuelva a discriminar por cliente real en lugar de contar todo el despliegue en un contador. La postura queda idéntica en local y en el dev desplegado, para que nadie desarrolle contra una topología que no existe.

`ASSUMPTION`: la vía elegida es la inclinación heredada del design de `auth-tenancy` (OQ2) — una `rewrite` de Next.js sobre el `BACKEND_INTERNAL_URL` que el frontend ya recibe. Un Route Handler de Next.js no es una alternativa distinta, es esa misma opción escrita en TypeScript; la elección entre ambas formas es de `/sdd:design`, y R3 la condiciona por comportamiento en cualquier caso.

## Requirements

### R1 — Camino same-origin hacia la API

**As a** desarrolladora del frontend, **I want** que el navegador alcance `/api/v1/...` en el mismo origen que sirve la aplicación, **so that** pueda escribir llamadas HTTP reales al backend sin túnel SSH y sin CORS.

Acceptance criteria:

1. WHEN un cliente de internet solicita una ruta bajo `/api/` en el hostname público del entorno dev, THE SYSTEM SHALL entregar la petición al servicio `backend` por la red interna del compose y devolver su respuesta al cliente, incluidos método, cuerpo, códigos de estado y el sobre de error `{"error": {...}}` de PRD §23.
2. THE SYSTEM SHALL NOT añadir ninguna regla de ingress al túnel, ningún hostname nuevo, ningún registro DNS nuevo ni ningún puerto al security list de la subred, que permanece en `[22]`.
3. THE SYSTEM SHALL NOT conectar `cloudflared` a la red `private` ni publicar `backend` fuera de `127.0.0.1` en ninguna interfaz de la VM.
4. THE SYSTEM SHALL mantener `frontend` como único puente entre `ingress` y `private`, y THE SYSTEM SHALL derivar el destino del reenvío de `BACKEND_INTERNAL_URL` — nunca de un literal `http://backend:8000` en el código de aplicación.
5. WHEN el reenvío no puede alcanzar el backend, THE SYSTEM SHALL devolver un error de servidor sin filtrar el nombre del servicio interno, la URL interna ni la traza al cliente.

### R2 — El camino está acotado, y `/docs` no viaja con él

**As a** responsable de la seguridad del entorno, **I want** que el camino público exponga exclusivamente `/api/`, **so that** la superficie anónima que hoy está protegida solo por el bind a loopback no se publique por accidente al abrir el camino.

Acceptance criteria:

1. THE SYSTEM SHALL enrutar únicamente las rutas bajo `/api/`, y THE SYSTEM SHALL NOT enrutar `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` ni `/health`.
2. WHEN un cliente de internet solicita `/openapi.json`, `/docs`, `/docs/oauth2-redirect` o `/redoc` en el hostname público, THE SYSTEM SHALL responder sin alcanzar el backend (el 404 de la aplicación Next).
3. THE SYSTEM SHALL cubrir lo anterior con un test automático que falle si el alcance del reenvío se ensancha, de modo que la exclusión sea una garantía verificada y no un efecto colateral de la expresión de ruta elegida.
4. THE SYSTEM SHALL registrar esta decisión como explícita —los cuatro endpoints anónimos **no se exponen**— cerrando la decisión que el panel de seguridad de `api-contract-export` dejó pendiente para este change. El contrato del frontend sigue siendo `backend/openapi.json`, que ya está versionado (`specs/api-contract.md`).

### R3 — La IP real del cliente llega al backend, comprobado por comportamiento

**As a** operadora del entorno, **I want** que el backend observe la dirección del cliente y no la del proxy, **so that** el límite por IP y los logs de intento fallido identifiquen a quien de verdad llama.

Acceptance criteria:

1. WHEN una petición atraviesa el camino de R1, THE SYSTEM SHALL hacer llegar al backend la dirección del cliente observada por el edge de Cloudflare, en una cabecera nombrada explícitamente por configuración.
2. THE SYSTEM SHALL demostrar el criterio anterior **por observación en el entorno desplegado** —la dirección que el backend registra coincide con la IP pública real del cliente— y THE SYSTEM SHALL NOT darlo por bueno a partir de la documentación del proxy. Este es el único desconocido real de la vía elegida: si el reenvío no propaga la IP, el camino existe pero R4 y R5 se quedan sin insumo.
3. IF la propagación no se puede conseguir por la vía elegida, THEN THE SYSTEM SHALL registrar el hallazgo en `BLOCKED.md` como decisión para una persona antes de dar por cumplido R1, en lugar de entregar el camino con el límite por IP degradado en silencio.
4. THE SYSTEM SHALL declarar en `.env.example` y en los dos composes el valor de `TRUSTED_CLIENT_IP_HEADER` que corresponde a la topología implantada, hoy vacío en los tres sitios.

### R4 — La cabecera se honra solo si el peer es un proxy de confianza

**As a** responsable de la seguridad del entorno, **I want** que la cabecera de IP se acepte únicamente cuando la conexión viene del proxy, **so that** nadie que alcance la API se dé un presupuesto nuevo de 10 intentos/min enviando la cabecera él mismo.

Acceptance criteria:

1. WHILE `TRUSTED_CLIENT_IP_HEADER` está configurada, THE SYSTEM SHALL honrar esa cabecera **solo si** la dirección del peer del socket pertenece a la lista de proxies de confianza declarada por configuración.
2. IF el peer no está en esa lista, THEN THE SYSTEM SHALL ignorar la cabecera y usar la IP del peer del socket como identidad del cliente, sea cual sea el valor recibido.
3. THE SYSTEM SHALL mantener la lectura del salto de **más a la derecha** de la **última** aparición de la cabecera, que `auth-tenancy` ya dejó correcta y que vale tanto para un proxy que **añade** (`X-Forwarded-For`) como para uno que **reemplaza** (`CF-Connecting-IP`).
4. THE SYSTEM SHALL cubrir con tests, como mínimo: peer de confianza con cabecera legítima, peer **no** de confianza enviando una cabecera falsificada, cabecera con varias apariciones, y valor no parseable como IP.
5. THE SYSTEM SHALL retirar de `backend/app/auth/api/dependencies.py` y de `sdd/specs/auth-tenancy.md` §«Identificación del cliente» la anotación de limitación conocida que asigna esta comprobación a este change, porque a partir de aquí deja de ser cierta.

### R5 — El límite por IP discrimina por cliente real con el proxy en medio

**As a** propietaria de la cuenta, **I want** que el throttle de login siga siendo efectivo ahora que las peticiones llegan por un proxy, **so that** un atacante no consuma el presupuesto de todos los usuarios ni se libre del suyo.

Acceptance criteria:

1. WHILE una misma dirección de cliente real ha realizado 10 o más intentos de login en el último minuto a través del camino de R1, THE SYSTEM SHALL responder `429` con `{"error": {"code": "RATE_LIMITED", ...}}` sin comprobar las credenciales, conforme a `specs/auth-tenancy.md` y a la regla 7 de `steering/security.md`.
2. WHEN dos clientes con direcciones reales distintas usan el camino simultáneamente, THE SYSTEM SHALL contabilizarlos en contadores separados, y THE SYSTEM SHALL NOT agotar el presupuesto de uno por los intentos del otro.
3. THE SYSTEM SHALL verificar ambos criterios end-to-end a través del camino público real, no solo con la aplicación en local.

### R6 — Paridad local/desplegado y radio de aislamiento documentado

**As a** desarrolladora, **I want** que el camino tenga la misma forma en local y en el dev desplegado, **so that** no escriba código contra una topología que solo existe en un entorno.

Acceptance criteria:

1. THE SYSTEM SHALL ofrecer el camino `/api/` con la misma forma en el stack local (`docker-compose.yml`) y en el desplegado (`docker-compose.deploy.yml`), de modo que el frontend use la misma URL relativa en ambos.
2. THE SYSTEM SHALL mantener el binding de `backend` a `127.0.0.1` en el compose de deploy y su publicación local documentada tal como están, sin convertir el camino nuevo en una segunda vía que las contradiga.
3. THE SYSTEM SHALL declarar en `sdd/specs/ingress-https-dev.md` que el origen público `frontend` **reenvía ahora `/api/` hacia `private`**, satisfaciendo explícitamente la cláusula WHERE del §Aislamiento de red del túnel —«todo origen de `ingress` extiende el radio a lo que reenvíe hacia `private`»— y enumerando qué queda dentro de ese radio.
4. THE SYSTEM SHALL actualizar `docs/ingress-https.md` y `infra/environments/dev/RUNBOOK.md` §7 para que el diagnóstico por túnel SSH deje de ser la única forma documentada de alcanzar la API, sin borrarlo (sigue siendo lo único que distingue un fallo de la app de uno del edge).

### R7 — Ningún cuerpo sin tope en la superficie que este change publica

**Añadido durante `/sdd:review`**, y conviene decir por qué no estaba antes: lo encontró el panel de seguridad **midiendo** la superficie que R1 crea, y el panel de arquitectura señaló después que la mitigación se había implementado sin requisito que la respaldara — existía solo como apéndice de diseño auto-autorizado. Esto la hace trazable.

**As a** operadora del entorno, **I want** que ningún endpoint de `/api/v1` acepte un cuerpo sin tope una vez es alcanzable desde internet, **so that** un llamante anónimo no pueda agotar la memoria de la VM antes de que ninguna defensa se consulte.

Acceptance criteria:

1. THE SYSTEM SHALL rechazar con `413` y `code` `PAYLOAD_TOO_LARGE` cualquier cuerpo que exceda el tope de su ruta, **antes de leerlo**, en **todo** `/api/v1/`.
2. THE SYSTEM SHALL usar un tope configurable propio para las rutas de subida (`/api/v1/integrations/`, hoy `CSV_IMPORT_MAX_BYTES` = 10 MiB) y otro, más pequeño y también configurable, para el resto (`REQUEST_MAX_BYTES`, 1 MiB), y THE SYSTEM SHALL NOT colapsar los dos en un único número.
3. WHEN el cuerpo excede el tope, THE SYSTEM SHALL rechazarlo **sin autenticar** al llamante, porque FastAPI lee el cuerpo antes de resolver dependencias y un tope que corriera después no protegería de nada.
4. THE SYSTEM SHALL cubrir lo anterior con tests **contra la aplicación real** (`create_app()`), no solo sobre el middleware aislado: acotar el prefijo de vuelta a las rutas de subida debe romper la suite.

**Por qué pertenece a este change y no a uno propio**: este change **crea** la exposición. Antes de él el backend escuchaba solo en el loopback de la VM, así que un cuerpo sin tope no era alcanzable; después lo es desde internet y sin credencial. Entregar R1 sin esto sería publicar a sabiendas un amplificador de memoria medido en 1,016 GiB de RSS desde una sola petición.

**Y sobre la justificación normativa, corregida**: la primera redacción de esta mitigación citaba la regla **12(c)** de `steering/security.md`. Es una cita estirada y se retira — la regla 12 se acota a sí misma a *«webhooks entrantes sin firma»*, y `/auth/login` no es un webhook. La regla **6** («tamaño máx. configurable, default 10 MB») habla de *uploads*, así que tampoco encaja tal cual. El fundamento honesto es el de arriba: la medición, y el hecho de que la exposición nace aquí. Si el proyecto quiere una regla general de topes de cuerpo, sale de aquí y se escribe en `steering/security.md` como entrada propia.

### R8 — Ningún endpoint anónimo de credenciales queda sin límite de tasa

**Añadido durante `/sdd:review`** y decidido por Jose el 2026-08-08. Lo encontró el panel de seguridad midiendo la superficie que R1 crea: `POST /api/v1/auth/refresh` es **anónimo** —el refresh token *es* la credencial—, **acuña access tokens**, y no consultaba ningún límite. Mientras el backend escuchaba en loopback eso no era alcanzable; R1 lo publica.

Lo que lo convierte en hallazgo y no en observación: los propios documentos de este change acotaban la superficie pública como «throttle + Bearer», y ese endpoint no estaba cubierto por ninguno de los dos.

**As a** propietaria de la cuenta, **I want** que el camino público no ofrezca ninguna operación de credenciales sin medir, **so that** nadie pueda molerla indefinidamente desde internet.

Acceptance criteria:

1. WHILE una misma dirección de cliente ha agotado su presupuesto por minuto, THE SYSTEM SHALL responder `429` con `code` `RATE_LIMITED` a `POST /api/v1/auth/refresh`, **antes** de mirar el token presentado.
2. THE SYSTEM SHALL contabilizar `refresh` y `login` **en el mismo contador por IP**, y THE SYSTEM SHALL NOT darle un presupuesto propio: lo que el límite protege es el coste de trabajo de credenciales anónimo por cliente, y partirlo permitiría gastar dos presupuestos desde una dirección.
3. THE SYSTEM SHALL verificarlo end-to-end sobre el endpoint real, no solo sobre el caso de uso.

**El coste, dicho de frente**: un refresh legítimo puede recibir `429` si ese cliente ya gastó el presupuesto. Con un access token de 15 minutos son unos pocos refresh por hora contra un techo de diez por minuto, así que el margen es de órdenes de magnitud — pero es un cambio de comportamiento observable, no gratis.

## Out of scope

- **Ingress de webhooks de PMS** (`POST /api/v1/webhooks/{provider}/{webhook_token}` desde Beds24). Es la segunda condición de disparo de la entrada del roadmap, **no se ha cumplido** —`reservations-webhooks` no ha arrancado— y su topología exige análisis propio: un tercero haciendo escritura anónima desde internet no es el navegador ni es same-origin, y arrastra las cuatro obligaciones de la **regla 12** de `steering/security.md`. Va a `reservations-webhooks`, y la entrada del roadmap **conserva** esa condición de disparo.
- **Login, sesión, almacén de token, `AuthProvider`, `middleware.ts` y `apiBaseUrl` en `public.ts`** — todo eso es `frontend-auth-session`, que este change desbloquea. Aquí no se toca `frontend/lib/config/`, `frontend/app/` ni `frontend/features/`, más allá de lo que el propio camino exija.
- **Los tres endpoints agregados del dashboard** (`/api/v1/properties`, `/properties/{id}/dashboard`, `/timeline/{property_id}`) y el cambio de `MockDashboardSource` a HTTP: son `dashboard-web`.
- **Exponer el backend por hostname o puerto propio**, y **CORS**: la vía same-origin los hace innecesarios, y ambas alternativas están cerradas por el aislamiento de red del túnel y por ADR 0003.
- **El radio residual del túnel** (IMDS `169.254.169.254`, puerto 22 por el gateway del bridge) y cualquier cambio en `iptables` de la VM: es `tunnel-host-surface-hardening`. Este change no lo amplía —no añade regla de ingress ni red nueva a `cloudflared`— pero tampoco lo cierra.
- **RLS o roles por tenant en Postgres**: la regla 1 de `steering/security.md` se seguirá cumpliendo enteramente en la aplicación. Es una observación de `tunnel-host-surface-hardening`, no trabajo de aquí.
- **Staging y producción**: el entorno dev es el único con ingress decidido (`steering/infra.md`).
- **Autenticar `/docs` o servirlo tras JWT**: descartado en R2, no aplazado.

## Affected specs

- `sdd/specs/ingress-https-dev.md` — el camino `/api/` como parte de la capability de ingress, y la cláusula WHERE del §Aislamiento de red del túnel satisfecha explícitamente (R1, R6).
- `sdd/specs/auth-tenancy.md` — §«Identificación del cliente»: la comprobación del peer deja de ser limitación conocida y pasa a requisito cumplido (R4); §«Protección de los endpoints de autenticación» gana la garantía con proxy en medio (R5).
- `sdd/specs/api-contract.md` — la decisión explícita de no exponer `/openapi.json`, `/docs`, `/docs/oauth2-redirect` ni `/redoc` por el camino público (R2).
- `sdd/specs/frontend-foundation.md` — §Configuration, si el reenvío vive en `next.config.ts` y consume `BACKEND_INTERNAL_URL` (R1.4).
- `sdd/specs/local-environment.md` — §Postura de red del stack local, por la paridad del camino en local (R6.1).
- `sdd/specs/app-deploy-dev.md` — solo si el deploy pasa a inyectar configuración nueva (`TRUSTED_CLIENT_IP_HEADER`, lista de proxies de confianza) en el `.env` de runtime (R3.4, R4.1).

Todos existen. Este change no crea specs nuevas: la capability es el ingress del entorno dev, que ya tiene la suya.
