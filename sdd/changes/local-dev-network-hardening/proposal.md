# Proposal: local-dev-network-hardening

## Why

`docker-compose.yml` publica Postgres en `5432:5432` (línea 12) y Redis en `6379:6379`
(línea 23). Sin prefijo de interfaz, Docker publica en `0.0.0.0`, así que **cualquier
host de la red a la que esté conectado el portátil** alcanza ambos datastores. Redis
además corre **sin `requirepass`** — el servicio de `docker-compose.yml:19-28` no tiene
`command` ni variable de contraseña, y `grep -rn "requirepass\|REDIS_PASSWORD"` sobre el
repositorio no da nada —, de modo que ese acceso es además **no autenticado**.

Eso dejó de ser un detalle de comodidad cuando `auth-tenancy` se mergeó. Los contadores
del throttle de login viven hoy en ese Redis: `backend/app/auth/infrastructure/throttle.py`
usa `login:ip:{ip}` (línea 34), `login:fail:{user_id}` (línea 52) y `login:lock:{user_id}`
(líneas 49 y 61). Quien alcance el puerto 6379 puede borrar esas claves entre intentos, y
entonces **ni el límite de 10 intentos/min/IP ni el bloqueo tras 10 fallos consecutivos se
disparan nunca** — que es literalmente lo que la **regla 7** de `steering/security.md`
exige y lo que `specs/auth-tenancy.md:207` y `:215` documentan como garantía.

Hay además una afirmación falsa que se cita como justificación. La exención de la
**regla 8** de `steering/security.md` permite que la contraseña del Postgres de desarrollo
lleve valor por defecto en `.env.example` porque *«solo existe dentro de la red de
docker-compose, **inalcanzable desde fuera de `localhost`**, sin datos reales»*. La
premisa del medio es falsa desde que existe el mapeo: `5432:5432` publica en todas las
interfaces. La exención puede seguir siendo razonable, pero hoy se apoya en una postura
que el compose no implementa.

El encuadre viene delegado: el design de `ingress-https-hardening` dejó `docker-compose.yml`
explícitamente fuera de su alcance diciendo que *«sus puertos publicados en `0.0.0.0` son
de `local-dev-network-hardening`, que es una entrada propia del roadmap con su propia
decisión de postura»* (`changes/archive/2026-08-04-ingress-https-hardening/design.md:261`).
Y el `RUNBOOK.md:459` ya fija la norma en general —*«si alguna vez publicas un puerto
temporalmente en el compose, **siempre** con el prefijo `127.0.0.1:`»*, citando D11 de
`ingress-https-dev`—, norma que el compose de dev local incumple.

Origen: panel de seguridad de `auth-tenancy`. Referencias: PRD §22,
`steering/security.md` reglas 7 y 8.

## What changes

`docker-compose.yml` pasa a publicar Postgres y Redis **solo en la interfaz de loopback**
(`127.0.0.1:5432:5432` y `127.0.0.1:6379:6379`), con lo que dejan de ser alcanzables desde
otros hosts de la red sin dejar de serlo para las herramientas del desarrollador ni para
los contenedores del propio compose. La postura de `backend` (`8000`) y `frontend` (`3000`)
**no cambia**, pero deja de ser una omisión y pasa a ser una decisión escrita con su
motivo. Y la exención de la regla 8 de `steering/security.md` se reescribe para describir
la postura real en vez de una que no existía.

No cambia ninguna cadena de conexión, ninguna variable de entorno, ningún puerto
(el número sigue siendo el mismo) ni el comportamiento de la aplicación.

## Requirements

### R1 — Los datastores de dev local solo aceptan conexiones desde la propia máquina

**As a** desarrollador de AutoHostAI, **I want** que Postgres y Redis del stack local no
estén alcanzables desde la red a la que esté conectado mi portátil, **so that** trabajar
desde una red compartida (coworking, wifi de un hotel, oficina del cliente) no exponga la
base de datos y el broker a cualquiera en ese segmento.

Acceptance criteria:

1. WHEN se levanta el stack con `make up`, THE SYSTEM SHALL publicar Postgres únicamente
   en `127.0.0.1:5432`.
2. WHEN se levanta el stack con `make up`, THE SYSTEM SHALL publicar Redis únicamente en
   `127.0.0.1:6379`.
3. WHEN otro host de la misma red intenta abrir una conexión TCP a los puertos 5432 o 6379
   de la máquina que corre el stack, THE SYSTEM SHALL rechazar la conexión (verificable
   con `docker compose port` mostrando el bind `127.0.0.1`, y con `docker inspect` sobre
   el `HostIp` de cada mapeo).
4. WHILE el stack está levantado, THE SYSTEM SHALL seguir permitiendo que `backend`,
   `worker`, `migrate` y `frontend` alcancen Postgres y Redis por nombre de servicio a
   través de la red de compose, sin cambiar ninguna cadena de conexión.
5. WHEN se ejecuta la suite del backend desde el host (`cd backend && uv run pytest`, que
   según `specs/domain-foundation-core.md:39` cae al valor por defecto contra
   `localhost:5432`), THE SYSTEM SHALL seguir conectando correctamente, porque `localhost`
   resuelve a la interfaz de loopback a la que ahora está acotado el mapeo.

### R2 — La garantía del throttle de login deja de ser anulable desde la red local

**As a** responsable de la seguridad del proyecto, **I want** que los contadores del
throttle no se puedan manipular desde otro host de la red, **so that** el límite de
10 intentos/min/IP y el bloqueo tras 10 fallos de la regla 7 de `steering/security.md` se
cumplan de verdad y no solo en el código.

Acceptance criteria:

1. WHEN un proceso ajeno al host intenta ejecutar comandos de Redis contra el puerto 6379
   del stack local, THE SYSTEM SHALL impedir la conexión, de forma que las claves
   `login:ip:*`, `login:fail:*` y `login:lock:*` de
   `backend/app/auth/infrastructure/throttle.py` no puedan borrarse ni alterarse desde la
   red.
2. THE SYSTEM SHALL dejar constancia por escrito de que la defensa que protege esos
   contadores en dev local es **el acotado a loopback y no la autenticación de Redis**,
   que sigue sin existir, para que la ausencia de `requirepass` no se lea como un
   descuido.
3. IF en el futuro se necesita exponer Redis fuera de loopback, THEN THE SYSTEM SHALL
   exigir que se resuelva antes la autenticación, y esa condición SHALL quedar escrita
   junto a la decisión.

### R3 — La postura de `backend` y `frontend` queda decidida por escrito, no por omisión

**As a** desarrollador que revisa el compose, **I want** entender por qué `8000` y `3000`
siguen publicados en todas las interfaces cuando los datastores no, **so that** no parezca
una inconsistencia olvidada y nadie lo "arregle" rompiendo la prueba en dispositivo real.

Acceptance criteria:

1. THE SYSTEM SHALL mantener `8000:8000` y `3000:3000` publicados en todas las interfaces
   en `docker-compose.yml` (decisión del usuario, 2026-08-04).
2. THE SYSTEM SHALL documentar el motivo: el proyecto es mobile-first
   (`sdd/project.md` §Stack, `steering/product.md` principio 2) y abrir la app desde el
   móvil por la IP de la LAN es cómo se comprueba el diseño en un viewport real — lo hizo
   `app-version-badge-date`. Acotar `3000` a loopback eliminaría esa vía.
3. THE SYSTEM SHALL registrar qué queda expuesto con esa decisión y qué no: la UI y la API
   de un stack de desarrollo con datos de prueba, **sin** acceso directo al datastore, que
   es la diferencia que R1 introduce.
4. WHERE la documentación describa esta asimetría, THE SYSTEM SHALL evitar afirmar que el
   stack local es inalcanzable desde la red, porque con `8000` y `3000` en `0.0.0.0` no lo
   es — el mismo error de redacción que R4 corrige en la regla 8.

### R4 — La exención de la regla 8 describe la postura que el repositorio implementa

**As a** lector de `steering/security.md`, **I want** que la justificación de la exención
sea verificable contra el compose, **so that** ninguna regla dura se apoye en una premisa
falsa (el modo de fallo que `ingress-https-hardening` R5 ya tuvo que corregir en ADR 0003 §2).

Acceptance criteria:

1. WHEN se lee la exención de la regla 8 de `steering/security.md`, THE SYSTEM SHALL
   justificarla con la postura real —Postgres publicado solo en loopback y sin datos
   reales— y SHALL NOT afirmar «inalcanzable desde fuera de `localhost`» mientras exista
   cualquier mapeo que lo contradiga.
2. THE SYSTEM SHALL conservar el efecto de la exención: la contraseña del Postgres de
   desarrollo puede seguir llevando valor por defecto funcional en `.env.example` para que
   `make up` arranque sin pasos manuales.
3. THE SYSTEM SHALL dejar la redacción condicionada a la postura, de forma que si el
   mapeo vuelve a `0.0.0.0` la exención quede visiblemente sin fundamento en vez de
   seguir citándose.

## Out of scope

- **La comprobación automática de esta postura** (era R5 de este proposal, retirada el
  2026-08-05 por decisión del usuario). Se demostró que construirla bien es un problema con más
  fondo del que aparenta: cinco rondas de revisión, ~19 hallazgos **todos** suyos, y cuatro de
  ellos regresiones del arreglo anterior — mientras R1-R4 no recibieron ninguno. Vive ahora en la
  entrada **`compose-ports-guard`** del roadmap, que hereda los seis criterios que R5 llegó a
  tener, el censo de vías de elusión demostradas y el diagnóstico estructural. **Consecuencia
  asumida mientras tanto, y dicha en voz alta en `README.md` y en la regla 8 de
  `steering/security.md`**: si alguien publica un puerto sin el prefijo `127.0.0.1:`, hoy solo lo
  atrapa la revisión del diff.
- **Añadir `requirepass` a Redis.** Defensa en profundidad legítima. Con R1 el puerto deja de
  ser alcanzable **desde la red**, que es lo que hacía explotable la ausencia de contraseña
  *para un atacante remoto*. Añadirla arrastra `.env.example`, las cadenas de conexión de
  backend y worker, y la lista cerrada de secretos de la regla 8 (*«esas tres y nada más»*) —
  es un change propio si alguna vez se decide. R2.3 deja escrito que exponer Redis fuera de
  loopback exige resolverlo primero.

  **Residual aceptado, y conviene no leer R1 de más** (añadido tras el panel de
  `/sdd:review`, 2026-08-04): en `127.0.0.1:6379` sin `requirepass`, **cualquier otro proceso
  o cuenta de la propia máquina** sigue pudiendo conectarse y borrar `login:ip:*`,
  `login:fail:*` y `login:lock:*`, anulando la garantía de la regla 7 igual que antes — solo
  desde un conjunto de atacantes mucho más pequeño. Lo que este change cierra es la
  explotación **desde la red**, no la explotación en general. Se acepta porque es la máquina
  de desarrollo de una sola persona, con datos de prueba; no se acepta en silencio.
- **`8000` y `3000` a loopback.** Decisión explícita del usuario (2026-08-04), no un
  olvido: la contrapartida es perder la prueba en dispositivo real. R3 lo documenta.
- **La postura de red del entorno dev remoto** (la VM de Oracle Cloud). Ya la resolvieron
  `ingress-https-dev` D11 y `ingress-https-hardening`: `docker-compose.deploy.yml` prefija
  `127.0.0.1` en `8000` y `3000` y no publica los datastores. Este change no toca ese
  fichero.
- **El radio del túnel de Cloudflare** (IMDS y puerto 22 alcanzables desde la red de
  ingress). Es `tunnel-host-surface-hardening`, otra entrada del roadmap.
- **Autenticación de la app pública en dev remoto** y cualquier cosa del ingress: no es
  esta capa.
- **`iptables` o firewall del host**, en la máquina local o en la VM. El acotado se hace
  donde corresponde, en la declaración de puertos del compose.

## Affected specs

- `sdd/specs/local-environment.md` — **al archivar**: (a) gana la postura
  de red del stack local, que hoy **no documenta en absoluto**
  (`grep -nE "5432|6379|8000|3000|0\.0\.0\.0|loopback"` no da resultados) — datastores en
  loopback, `8000`/`3000` en todas las interfaces con su motivo, y que **esta postura no tiene
  comprobación automática**, remitiendo a la entrada `compose-ports-guard`; y (b) **corregir la línea 44**, que repite la afirmación falsa
  *«no son secretos, es un Postgres solo alcanzable dentro de la red de compose»* — es la
  tercera de las tres copias de esa justificación (D7), y la única que este change no arregla
  en su propio diff.
- `sdd/specs/auth-tenancy.md` — su garantía de throttle (`:207`, `:215`) pasa a apoyarse en
  una postura de red que la sostiene: hay que anotar que en dev local esos contadores están
  protegidos por el bind a loopback de `redis` y **no** por autenticación de Redis, que no
  existe.
- `sdd/steering/security.md` — no es una spec y **se edita en este change**, no al archivar:
  reescritura de la exención de la regla 8, condicionada a la postura (R4, D7). Hecho.
- `README.md` — **sí se toca**: (1) la línea 108 llevaba la misma afirmación falsa
  que la regla 8 —tercera copia, corregida en este change—; y (2) una subsección nueva
  `### Postura de red del stack local` en `## Arrancar en local`, que explica qué está acotado a
  loopback y por qué, qué publican `backend`/`frontend` deliberadamente, y **que esta postura no
  tiene comprobación automática todavía**, remitiendo a la entrada `compose-ports-guard`. Las
  líneas 17-20 (URLs locales, `localhost:5432`, `localhost:6379`) siguen exactas y no cambian.
