# Autenticación y tenencia

Cómo se opera la autenticación del backend. El *qué hace* está en las specs EARS de
`sdd/specs/auth-tenancy.md`; el patrón de capas que este change fijó para todo el
backend está en [ADR 0004](adr/0004-backend-layering-pattern.md).

## Los cuatro endpoints

Todos bajo `/api/v1/`, con el sobre de error `{"error": {"code", "message", "details"}}`
de PRD §23.

| Método | Ruta | Auth | Respuesta |
|---|---|---|---|
| `POST` | `/auth/login` | anónima | `200` con `access_token`, `refresh_token`, `token_type`, `expires_in` |
| `POST` | `/auth/refresh` | anónima (el refresh es la credencial) | `200`, mismo cuerpo |
| `POST` | `/auth/logout` | Bearer | `204` sin cuerpo |
| `GET` | `/auth/me` | Bearer | `200` con `id`, `tenant_id`, `name`, `email`, `role`, `preferred_language` |

El token de acceso vive 15 minutos y el de refresh 7 días, ambos configurables. La
documentación navegable está en `/docs`, con el esquema Bearer declarado.

## Dar acceso a un entorno nuevo

El producto **no tiene registro público**: la propietaria y el manager son dos personas
reales. Un entorno recién levantado no tiene ninguna cuenta con la que entrar hasta que
se ejecuta el bootstrap.

> **Desde `user-management`**, el bootstrap ya no es la única forma de crear usuarios: sigue
> siendo la única forma de *entrar* a un entorno nuevo, pero a partir de ahí las cuentas se
> dan de alta por API (`POST /api/v1/users`) sin tocar la VM. Ver
> [`user-management.md`](user-management.md). Dos cosas de esta página cambian de matiz:
> desactivar o suspender una cuenta, y resetear su contraseña, **revocan sus tokens de
> refresh** (razones `USER_DEACTIVATED` y `PASSWORD_RESET`) — sin eso, `POST /auth/refresh`,
> que no revalida el estado de la cuenta, seguiría emitiendo pares nuevos durante los 7 días
> de vida del refresh.

### En local

```bash
# 1. Rellena en tu .env (sin valores por defecto en el repositorio, a propósito)
BOOTSTRAP_TENANT_NAME=
BOOTSTRAP_TENANT_BILLING_EMAIL=
BOOTSTRAP_OWNER_NAME=
BOOTSTRAP_OWNER_EMAIL=
BOOTSTRAP_OWNER_PASSWORD=
BOOTSTRAP_MANAGER_NAME=
BOOTSTRAP_MANAGER_EMAIL=
BOOTSTRAP_MANAGER_PASSWORD=

# 2. Ejecuta
make bootstrap
```

Crea el tenant, su `TenantConfig` y dos usuarios (`TENANT_OWNER` y `PROPERTY_MANAGER`).
Es **idempotente**: una segunda ejecución no duplica ni modifica nada, y tampoco falla
si cambias la caja del email. Si falta alguna variable, aborta **antes** de abrir
transacción y lista todas las que faltan de golpe.

**Una excepción a la idempotencia, a propósito**: si cambias `BOOTSTRAP_TENANT_NAME` y
vuelves a lanzarlo, aborta con `BootstrapConflictError` en lugar de intentar crear un
segundo tenant con los mismos emails. El índice único global rechazaría esa escritura de
todas formas (ver más abajo); lo que aporta el aborto explícito es un error que nombra la
variable a revisar en vez de un `IntegrityError` sobre un índice. Si te sale, ya existen
usuarios con esas direcciones: revisa el nombre del tenant.

No está enganchado a `make up`, que sigue arrancando sin pasos manuales.

### En el entorno desplegado

El mismo comando, pero contra el compose de deploy y con los valores en un **env-file
temporal con permisos 600** que se borra al terminar — no con `-e` en la línea de
comandos, que las dejaría en el `bash_history` y en `/proc/<pid>/cmdline`, ni en el `.env`
que el workflow reescribe en cada despliegue:

```bash
docker compose -f docker-compose.deploy.yml run --rm --no-deps \
  --env-file /tmp/bootstrap.env backend python -m app.cli.bootstrap
```

Es `python -m` y no `uv run`: la imagen `prod` no lleva `uv`, solo el venv en el `PATH`.
El procedimiento completo, con todas las variables y las comprobaciones, está en
`infra/environments/dev/RUNBOOK.md` §6.5. No está en el pipeline a propósito: las
contraseñas las elige una persona, así que no encajan en el patrón `random_*` + Vault del
resto de secretos.

## Comprobar que funciona

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```

## Configuración

| Variable | Default | Para qué |
|---|---|---|
| `JWT_SECRET_KEY` | — (requerida) | Firma HS256. La app **no arranca** sin ella, y exige al menos 32 caracteres no-blancos. En local la genera `make up` con `openssl rand -hex 32` y la escribe en tu `.env`; en dev remoto la genera Terraform y vive en OCI Vault. Nunca en el repositorio. |
| `JWT_ACCESS_TOKEN_MINUTES` | 15 | Vida del access token |
| `JWT_REFRESH_TOKEN_DAYS` | 7 | Vida del refresh token |
| `BCRYPT_ROUNDS` | 12 | Coste del hash. **No lo cambies sobre una base con usuarios** sin rehashear: ver abajo |
| `BCRYPT_MAX_CONCURRENCY` | nº de CPUs | Cuántos hashes pueden calcularse a la vez. Es el presupuesto de CPU del login: ver abajo |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | 10 | Intentos por IP y minuto |
| `LOGIN_MAX_FAILED_ATTEMPTS` | 10 | Fallos consecutivos antes de bloquear la cuenta |
| `LOGIN_LOCKOUT_MINUTES` | 15 | Duración del bloqueo |

> **`TRUSTED_CLIENT_IP_HEADER` ya no existe.** La retiró el change
> `api-ingress-routing`: la identificación del cliente pasó a uvicorn y se configura por
> línea de arranque, no por variable de entorno. Si te la encuentras en un `.env` viejo,
> bórrala — no hace nada. Detalle en la sección siguiente.

**Sobre el nombre `JWT_SECRET_KEY`** *(decisión cerrada por Jose el 2026-07-30, antes del
merge del PR #25: se mantiene este nombre y no se renombra al del PRD)*. El PRD §25 la
llama `SECRET_KEY`. Se usa el nombre
más específico a propósito, y de forma consistente en todo el repositorio (`settings`,
`.env.example`, los dos composes, `Makefile`, Terraform, el workflow de deploy y esta
documentación): en la misma sección del PRD ya convive `ENCRYPTION_KEY`, así que
`SECRET_KEY` a secas no dice de qué es la clave y el día que haya una tercera obliga a
adivinar. Es una desviación deliberada del PRD, no un despiste, y no se renombra al
revés porque la variable ya vive en OCI Vault y en el `.env` de la VM: cambiarla es un
paso operativo sobre el entorno desplegado, no una edición de código.

## De quién es la IP que cuenta el límite

La identidad del cliente es **la IP del peer del socket**, y punto: `get_client_ip()`
(`backend/app/auth/api/dependencies.py`) no lee ninguna cabecera. Quien resuelve la
cabecera de proxy es **uvicorn**, con su `ProxyHeadersMiddleware`, aguas arriba de la
aplicación — y solo para los peers que `--forwarded-allow-ips` nombra explícitamente.

Por qué en un solo sitio y no en dos: `proxy_headers` viene a `True` **por defecto** en
uvicorn, así que un lector de cabeceras en la aplicación sería un segundo mecanismo
decidiendo si confiar en un peer que el primero pudo haber reescrito ya desde entrada del
atacante — una comprobación que valida su propio insumo. Y la IP no alimenta solo al
throttle: es el `actor_ip` de `AuditLog` en cinco endpoints, así que resolverla en la
frontera ASGI la arregla para todos los consumidores a la vez.

### Cómo está configurado, por entorno

| Entorno | `--forwarded-allow-ips` | Efecto |
|---|---|---|
| Local (`docker-compose.yml`) | `127.0.0.1`, pineado en el Dockerfile | No se cree a nadie. El throttle degrada a **un contador para todo el stack** |
| Dev desplegado (`docker-compose.deploy.yml`) | la IP fija del contenedor `frontend` | Solo el proxy puede reportar una IP de cliente |

En local es deliberado y no una omisión: `docker-compose.yml` publica el 8000 **en todas
las interfaces** a propósito, para poder probar desde un móvil real por la IP de LAN. Con
un puerto abierto a la LAN, la cabecera la pone quien llama, así que confiar en ella daría
a cualquiera de tu red un presupuesto nuevo de 10 intentos/min por petición. Un contador
global en un entorno sin datos reales es el precio correcto.

> ⚠️ **No añadas `FORWARDED_ALLOW_IPS` a tu `.env`, y menos `FORWARDED_ALLOW_IPS=*`.**
> uvicorn cae a esa variable cuando el flag falta (`uvicorn/config.py:356`), y el backend
> recibe el `.env` entero por `env_file`. El flag está pineado en
> `backend/devops/Dockerfile` justo para que la variable no pueda surtir efecto.

### En el dev desplegado

El navegador llega a la API por `https://<hostname>/api/...` en el **mismo origen** que
sirve la app: un Route Handler de Next (`frontend/app/api/[...path]/route.ts`) reenvía a
`backend:8000` por la red interna. Ese handler descarta toda cabecera de reenvío que
pudiera haber puesto el cliente y escribe **una** `X-Forwarded-For` derivada del
`CF-Connecting-IP` que escribió el edge de Cloudflare. El backend se la cree porque el
peer es el contenedor `frontend`, que es la única dirección de la lista.

Residual aceptado por escrito: una petición que entre por `127.0.0.1:3000` de la VM (la
publicación que existe para depurar con `ssh -L`) no viene del edge, así que su
`CF-Connecting-IP` es el que envíe quien llama. Requiere SSH en la VM — posición desde la
que ya se llega directamente a `127.0.0.1:8000`.

### Qué se rechaza, y por qué no basta con «parsea como IP»

`get_client_ip()` valida y canonicaliza antes de devolver: rechaza lo que no sea una IP,
rechaza **IPv6 con zone identifier** (`fe80::1%eth0`), colapsa las formas IPv4-mapped
sobre su IPv4, y acota la longitud a los 45 caracteres de la columna `actor_ip`. En todos
esos casos cae a `127.0.0.1`, que es fail-closed: comparten un contador en vez de
inventarse uno cada uno.

El caso del zone identifier merece el detalle porque **sí parsea**: el texto tras `%` es
casi libre, así que `fe80::1%<100 caracteres>` es una dirección válida de 108 caracteres, y
un zone puede llevar CR o LF. Medido, dejarlo pasar daba tres cosas: un contador nuevo por
cada zone distinto (adiós al límite por IP), líneas forjadas en el log de login que lee
quien investiga un incidente, y un `AuditContractError` que **aborta la transacción** de la
operación auditada. Un zone identifier es ámbito link-local de una sola máquina, así que
nunca puede describir legítimamente a un cliente remoto.

### La otra defensa, que no depende de nada de esto

El **bloqueo por cuenta**: 10 fallos consecutivos y la cuenta queda bloqueada 15 minutos.
Tiene un coste conocido —quien conozca un email puede mantener esa cuenta bloqueada en
bucle—, inherente a lo que pide PRD §22; el bloqueo temporal en vez de permanente acota el
daño.

## Cosas que sorprenden y conviene saber

**Un email es único en toda la instalación, no por tenant.** Se aparta del PRD §7.3,
que define `UNIQUE(tenant_id, email)`, y el motivo está en [ADR
0005](adr/0005-global-email-uniqueness.md): el login recibe `{email, password}` y nada
más, así que si una dirección puede existir dos veces **no identifica la cuenta**. La
garantía es un índice único funcional sobre `lower(email)` — en la base de datos, no en
código de aplicación — y los emails se normalizan a minúsculas también en escritura y en
lectura (design D19). La constraint `UNIQUE(tenant_id, email)` se retiró: la unicidad
global ya la implica.

Lo que esto cierra: con unicidad por tenant, quien pudiera crear usuarios en el tenant B
introducía la dirección del propietario del tenant A y **lo dejaba fuera del producto de
forma indefinida**, porque no hay endpoint de desbloqueo. Ahora la base de datos rechaza
esa escritura, con o sin comprobación en Python — que es lo que hace que la invariante no
dependa de que ningún escritor futuro se olvide.

El precio, asumido: **una persona no puede tener la misma dirección en dos tenants**. El
día que haga falta, se modela con una identidad global más memberships (entrada
`saas-cross-tenant` del roadmap), nunca repitiendo el email.

**bcrypt no corre en el event loop.** Un `verify` cuesta ~250 ms de CPU con el coste 12
configurado. Medido en este contenedor: ejecutado en línea, congela el proceso entero esos
250 ms, y ocho intentos simultáneos se serializan en 1,87 s durante los que no se sirve
nada más. Por eso `hash`, `verify` y el señuelo `burn` corren en hilos de trabajo con una
cota compartida (`BCRYPT_MAX_CONCURRENCY`, design D21) — los mismos ocho tardan 271 ms y
el loop no se detiene. bcrypt libera el GIL, así que los hilos dan paralelismo real.

La cota importa tanto como el hilo: sin ella el pool por defecto son 40 hilos, y una
ráfaga de logins fallidos pone 40 cálculos de bcrypt en una VM de 4 OCPU, con lo que
**todas** las peticiones —incluidas las que no son de login— se vuelven ~10 veces más
lentas. Por defecto vale el número de CPUs visibles. Subirla por encima no sirve de nada:
el trabajo es de CPU, no de espera.

**Cambiar `BCRYPT_ROUNDS` sobre una base con usuarios reabre un agujero.** Todo fallo de
login gasta a propósito el mismo trabajo de bcrypt, incluso cuando el email no existe:
si no, la diferencia de latencia entre "no existe" (milisegundos) y "existe" (el coste
completo del hash) permite enumerar usuarios aunque las respuestas sean idénticas. Ese
trabajo se gasta contra un hash señuelo construido con el coste **configurado**, mientras
una verificación real cuesta el que lleve embebido el hash del usuario. Ambos coinciden
mientras todos los hashes se hayan creado con el valor actual — que es lo que ocurre, porque
solo hay un sitio que los crea. Si subes o bajas `BCRYPT_ROUNDS` con usuarios ya dados de
alta, los dos costes divergen y el oráculo vuelve, de forma permanente y silenciosa, hasta
que se rehashee. Hazlo con una pasada de rehash-en-login, no solo cambiando la variable.

**Todos los fallos de login responden lo mismo.** Email inexistente, contraseña
equivocada, cuenta `INACTIVE` o `SUSPENDED`, tenant no activo, cuenta bloqueada y email
ambiguo dan el mismo `401 INVALID_CREDENTIALS`. Es deliberado: cualquier diferencia
permitiría enumerar usuarios. Los intentos fallidos sí quedan en el log —en inglés, sin
la contraseña— así que el motivo real se diagnostica ahí.

**Reusar un refresh token tira toda la familia.** La rotación invalida el token
presentado; presentar uno ya usado se trata como indicio de robo y revoca **todas** las
sesiones de esa cadena, incluida la que el usuario legítimo está usando. Eso es lo que se
quiere: si dos partes usan la misma cadena, una de ellas no debería.

**El logout no invalida los access tokens ya emitidos.** Cierra la sesión de refresh, y
los access vivos caducan por su cuenta en 15 minutos como máximo. No hay lista de
revocación de access tokens, por decisión.

**Suspender una cuenta o bajarle el rol surte efecto de inmediato**, sin esperar a que
expire su token: cada petición autenticada recarga usuario y tenant de la base de datos y
usa el rol almacenado, no el del token.

## Roles

Los cinco de PRD §6: `SUPER_ADMIN`, `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`,
`TECHNICIAN`. El catálogo de permisos arranca con los dos que este change realmente
comprueba —leer el propio perfil y cerrar la propia sesión—, concedidos a los cinco
roles; cada módulo añade los suyos. `SUPER_ADMIN` **no** tiene visibilidad cross-tenant:
se descartó a propósito para que el aislamiento sea absoluto y verificable, y queda como
entrada `saas-cross-tenant` del roadmap.

El huésped no es un `User` y no aparece en `UserRole`: su acceso es por token de un solo
uso y va en la entrada `guest-portal` del roadmap.
