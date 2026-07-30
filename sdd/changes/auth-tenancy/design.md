# Design: auth-tenancy

## Context

El backend es hoy dominio puro más esquema: `backend/app/<dominio>/{domain,infrastructure}/`
con entidades dataclass, enums y modelos SQLAlchemy de `domain-foundation-core`/`-ops`, y
el `TimelineEventFactory`/`PropertyStateMachine` en `backend/app/timeline/domain/services.py`.
**No existe ninguna capa `application/` ni `api/` en el proyecto**: `backend/app/main.py`
son 9 líneas con `app = FastAPI(...)` y un `GET /health`, y `backend/app/core/db.py` ya
expone `Base`, `engine`, `async_session_factory` y los mixins `UUIDPrimaryKeyMixin`,
`TimestampMixin` y `TenantScopedMixin` (este último ya pone `tenant_id` FK indexado en
cada modelo). `backend/app/auth/` tiene la entidad `User` (dataclass con `password_hash`),
`UserRole` con cinco valores, `UserStatus`, y `UserModel` con `UniqueConstraint(tenant_id, email)`.

Del lado del cliente la fontanería ya está a medio camino y **condiciona el contrato**:
`frontend/lib/api/errors.ts` parsea exactamente el sobre `{error:{code,message,details}}`
de PRD §23 y trata `204` como cuerpo vacío, y `frontend/lib/api/client.ts` tiene ya los
puntos de extensión `getHeaders()` (auth) y `onUnauthorized()` (refresh). El backend debe
encajar en ese contrato, no proponer otro.

Dos hechos del entorno desplegado que salieron al leer `docker-compose.deploy.yml` y
`sdd/specs/ingress-https-dev.md` y que cambian decisiones de este diseño: el túnel de
Cloudflare enruta **solo** a `http://frontend:3000` y el backend se publica únicamente en
`127.0.0.1:8000` de la VM, así que **la API no es alcanzable desde internet**; y el
frontend recibe `BACKEND_INTERNAL_URL=http://backend:8000`, es decir, el camino previsto
es servidor-a-servidor por la red interna. Ver D12 y OQ2.

## Decisions

### D1 — La fontanería genérica en `app/core/`, la semántica de auth en `app/auth/`

**Chosen:** `app/core/` recibe solo lo que no es de nadie —factoría de la aplicación,
sesión por request, handlers del sobre de error, cliente Redis, settings— y todo lo que
tiene reglas de negocio vive en `app/auth/` con sus cuatro capas. Los módulos futuros
importarán la dependencia de autorización desde `app.auth.api.dependencies`, que es un
import explícito entre módulos en la capa `api`, permitido por la regla de dependencia de
`steering/backend-architecture.md`. La política de roles (PRD §6) es lógica de negocio y
va en `app/auth/domain/policy.py`, no en `core`.

Rejected: meter el `RequestContext` y el RBAC en `app/core/security.py` — pondría las
reglas de PRD §6 en un módulo sin dominio, y `core` acabaría siendo el vertedero de
negocio que `backend.md` prohíbe. Rejected: duplicar la dependencia en cada módulo —
la política dejaría de tener un único sitio auditable.

### D2 — `create_app()` conservando `app` a nivel de módulo y `/health` donde está

**Chosen:** `app/main.py` pasa a exponer `create_app()` —que registra routers, handlers de
error y ciclo de vida— y mantiene `app = create_app()` a nivel de módulo. Dos razones
concretas: `backend/tests/test_health.py` importa `from app.main import app`, y el
`healthcheck` de los tres composes (`docker-compose.yml:69`,
`docker-compose.deploy.yml:66`) hace `urlopen('http://localhost:8000/health')`. **`/health`
se queda en la raíz, fuera de `/api/v1/`**: moverlo rompería el healthcheck del contenedor
y con él el `depends_on: service_healthy` del frontend y del `worker`.

Rejected: solo `create_app()` sin instancia de módulo — rompe el test existente y el
`uvicorn app.main:app` del Dockerfile. Rejected: mover `/health` a `/api/v1/health` por
uniformidad — coste real (CD roto) a cambio de estética.

### D3 — PyJWT con HS256 y el algoritmo como constante, no como variable de entorno

**Chosen:** `pyjwt` con HS256 sobre `JWT_SECRET_KEY`, que ya existe en
`.env.deploy.example` y lo genera Terraform. El algoritmo se fija como **constante en el
código** y la verificación pasa `algorithms=["HS256"]` explícitamente.

Rejected: `python-jose` — arrastra un historial de CVEs y mantenimiento parado, y es la
dependencia que más veces ha aparecido en incidentes de verificación de JWT. Rejected:
RS256/EdDSA — obliga a gestionar un par de claves y su distribución sin ninguna ventaja
mientras haya un solo servicio firmando y verificando. Rejected: `JWT_ALGORITHM` como env
var — un despliegue mal configurado con `none` desactivaría la verificación de firma; no
merece la pena hacer configurable algo que nunca se va a cambiar.

### D4 — `bcrypt` directamente, con límite explícito de longitud de contraseña

**Chosen:** la librería `bcrypt` usada directamente en
`app/auth/infrastructure/password_hasher.py`, detrás del puerto `PasswordHasher` definido
en `app/auth/domain/ports.py`. `project.md` y PRD §22 fijan bcrypt, así que no hay
decisión de algoritmo, solo de envoltorio. **bcrypt trunca silenciosamente a 72 bytes**:
el hasher SHALL rechazar con error de validación cualquier contraseña cuya codificación
UTF-8 exceda 72 bytes, en vez de truncar y aceptar como válida una contraseña distinta.
El coste (`rounds`) queda en el default de la librería (12) y configurable por entorno
para poder bajarlo en los tests, donde 12 rounds por login hacen la suite lenta.

**El hash señuelo se precalcula al importar** (`prewarm`), no en la primera petición: si
no, el primer login con email inexistente de cada worker pagaría `gensalt` + `hashpw`
**además** de la verificación, o sea el doble de latencia que un login con contraseña
equivocada — un bit de "esta dirección no existe" por vida de proceso, exactamente la
fuga que `burn` cierra. Lo levantó el panel de `/sdd:review` sobre la primera versión.

**Intercambio aceptado y no resuelto aquí: `burn` gasta el factor de trabajo completo
dentro del event loop.** Igualar el trabajo subió la amplificación del atacante en el
camino del email inexistente de ~1 a ~100: esa petición pasó de ~2 ms a ~0,25 s de CPU
síncrona. Con el límite de 10/min por IP hacen falta ~25 direcciones distintas para
saturar un worker, así que hoy no es alcanzable —todas las peticiones llegan con la IP
del contenedor del frontend, un único contador—, pero **se vuelve alcanzable justo cuando
`api-ingress-routing` traiga las IP de cliente reales**. La solución es ejecutar
`verify`/`hash`/`burn` en un hilo (`anyio.to_thread.run_sync`), lo que obliga a volver
async el puerto `PasswordHasher` y sus cinco llamantes. Se deja fuera de este change a
propósito: es un refactor mecánico pero amplio, y hacerlo al cierre de un review tiene
más riesgo que valor cuando la exposición todavía no existe. Queda como requisito de
`api-ingress-routing`, que es el change que la crea.

Rejected: `passlib[bcrypt]` — 1.7.4 es la última release, sin mantenimiento, y rompe con
bcrypt 4.x por el `__about__` que ya no existe; añade una capa que hay que parchear.
Rejected: argon2 — contradice `project.md` y PRD §22 sin que nadie lo haya pedido.
Rejected: truncar a 72 bytes en silencio, que es el comportamiento por defecto y una
degradación silenciosa de seguridad.

### D5 — Estado de refresh en tabla propia `user_sessions`, con el `jti` como clave

**Chosen:** una tabla nueva `user_sessions` en `app/auth/infrastructure/models.py` con su
migración Alembic. El token de refresh es un JWT cuyo `jti` **es** el `id` de la fila, así
que no se almacena el token ni un hash de él: la firma ya prueba autenticidad y la fila
aporta el estado (usado, revocado, expirado). Columnas: `id` (PK, = `jti`), `tenant_id`
(vía `TenantScopedMixin`), `user_id`, `family_id`, `parent_id` (nullable, autorreferencia),
`expires_at`, `used_at`, `revoked_at`, `revoked_reason` (`LOGOUT` | `REUSE_DETECTED`), más `created_at`/`updated_at` de `TimestampMixin`.

La rotación de R2.1 marca `used_at` en la fila presentada e inserta la hija con el mismo
`family_id`. La detección de reuso de R2.2 es exactamente "la fila presentada ya tiene
`used_at`": entonces se revoca la familia completa con un solo `UPDATE ... WHERE
family_id = :fam AND revoked_at IS NULL`.

**Esta tabla no está en la lista de entidades de PRD §7.** Es una adición deliberada: el
PRD pide *refresh token rotation* en §22 sin decir dónde vive el estado, y rotación,
detección de reuso y logout son todos imposibles sin estado durable en el servidor. Queda
anotada como tal en la spec viva.

Rejected: Redis con TTL — más simple para la expiración, pero el estado de sesión deja de
ser durable ni consultable y perderíamos la trazabilidad; además Redis aquí no tiene
persistencia configurada. Rejected: refresh sin estado (solo firma) — hace literalmente
imposibles R2.1, R2.2 y R2.3. Rejected: token opaco aleatorio con columna `token_hash` —
funciona igual de bien pero necesita el mismo viaje a la base de datos y pierde los claims
autodescriptivos, sin ganar nada.

### D6 — El tenant viaja en un `RequestContext` explícito, pasado a los casos de uso

**Chosen:** un value object inmutable
`RequestContext(user_id: UUID, tenant_id: UUID, role: UserRole)` en
`app/auth/domain/context.py`, producido por la dependencia de FastAPI y **pasado como
parámetro explícito** a cada caso de uso, que a su vez lo pasa a los métodos del
repositorio. Los puertos de repositorio reciben `tenant_id` en su firma; no existe ningún
método que consulte una entidad con `tenant_id` sin recibirlo. El `tenant_id` sale
**solo** del claim del token: los DTOs de request no tienen campo `tenant_id`, así que uno
enviado en el cuerpo es descartado por Pydantic y ni llega al caso de uso (R4.1).

Sobre esta vía autorizada se añade además una red estructural, decidida al resolver OQ1 y
detallada en **D16**: los parámetros explícitos siguen siendo el mecanismo autorizado y
legible; el filtro global es solo la red que impide que un olvido futuro se convierta en
una fuga.

Rejected: `contextvars` como única vía, sin parámetros explícitos — cambiaría la semántica
de toda query desde un sitio invisible en la revisión de código y dejaría el aislamiento
acoplado a un detalle de SQLAlchemy sin nada legible en la firma del repositorio.
Rejected: Row-Level Security de PostgreSQL — la garantía más fuerte porque la impone el
motor, pero exige políticas por tabla en las migraciones, que la app corra con un rol
no-superusuario y replicar el montaje en el `Base.metadata.create_all` de
`tests/conftest.py`, que hoy no ejecuta migraciones.

### D7 — Cada request autenticada revalida usuario y tenant contra la base de datos

**Chosen:** la dependencia `get_authenticated_request` no se cree los claims: tras verificar la
firma, carga el usuario por `(tenant_id, user_id)` y comprueba `UserStatus.ACTIVE` y
`TenantStatus.ACTIVE` en una sola query con join. Es lo que exigen R4.5 (tenant inexistente
o no activo → 401) y R1.4 aplicado a una cuenta suspendida *después* de emitir el token; y
el rol efectivo pasa a ser el de la base de datos, no el del token, de modo que degradar un
rol surte efecto de inmediato en vez de esperar 15 minutos.

Rejected: confiar en los claims hasta la expiración — una query menos por request, pero una
cuenta suspendida seguiría operando hasta 15 minutos y `SUPER_ADMIN` degradado también;
con 2 viviendas el ahorro es irrelevante frente a eso.

### D8 — RBAC como enum `Permission` más un mapa por rol, con catálogo mínimo

**Chosen:** `app/auth/domain/policy.py` define `Permission` (enum) y un único
`ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]]` que materializa PRD §6, más
una función pura `is_allowed(role, permission) -> bool`. La capa `api` aporta la fábrica de
dependencias `require(permission)`. **El catálogo arranca con los permisos que este change
realmente usa** y cada módulo futuro añade los suyos: no se pre-declaran los permisos de
limpieza, pricing o statements.

Esto respeta el aviso de `backend-architecture.md` contra la abstracción especulativa
(la tarea 7.4 de `timeline-state-machine` verificó exactamente eso), y a la vez deja PRD §6
en un sitio único y auditable en cuanto lleguen endpoints de negocio.

Rejected: `require_roles(TENANT_OWNER, PROPERTY_MANAGER)` en cada endpoint — más directo
hoy, pero dispersa PRD §6 por todos los routers y obliga a un `grep` para responder "qué
puede hacer una limpiadora". Rejected: catálogo completo de permisos de todo el PRD desde
ya — especulación pura sobre módulos que aún no tienen diseño.

### D9 — La cobertura de autorización se prueba recorriendo las rutas registradas

**Chosen:** un test recorre `app.routes` y, para cada ruta que no esté en una **lista
explícita de rutas anónimas** (`/health`, `POST /api/v1/auth/login`,
`POST /api/v1/auth/refresh`, `/docs`, `/redoc`, `/openapi.json`), afirma que entre sus
dependencias hay una de autenticación/autorización, inspeccionando `route.dependant`. Así
R3.2 y R3.3 se verifican estructuralmente: un endpoint nuevo sin declarar autorización
hace fallar la suite, y colarlo exige añadirlo a mano a la lista de anónimas, que es un
cambio visible en la revisión.

Rejected: revisión manual en el panel de `/sdd:review` — no es un mecanismo, es una
esperanza. Rejected: un middleware que deniegue todo lo no declarado — más hermético, pero
mueve la decisión a runtime y produce 403 confusos en desarrollo en vez de un test rojo.

### D10 — Sesión de base de datos por request, con el `commit` en el caso de uso

**Chosen:** una dependencia `get_db_session()` en `app/core/db.py` que abre una
`AsyncSession` con `async_session_factory`, la cede, hace `rollback()` si la request
termina en excepción y `close()` siempre. La **frontera transaccional es el caso de uso**:
él llama a `commit()` cuando la operación de negocio termina. Los repositorios nunca hacen
`commit`, solo `add`/`flush`/consultas, para que una operación con varias escrituras
—rotar un refresh y actualizar `last_login_at`— sea atómica.

Rejected: commit automático en la dependencia o en un middleware al devolver 2xx — esconde
la frontera y acaba confirmando escrituras a medias de un caso de uso que decidió abortar.
Rejected: commit por operación en el repositorio — rompe la atomicidad de R2.1, donde
marcar la fila usada e insertar la hija tienen que ir juntas.

### D11 — Sobre de error por handlers globales, incluido el reshape del 422 de FastAPI

**Chosen:** `app/core/errors.py` define `AppError(code, message, http_status, details)` como
base, las subclases concretas, y `register_error_handlers(app)` instala los handlers. Se
registran tres: `AppError`, `RequestValidationError` y `HTTPException`. El de
`RequestValidationError` es imprescindible y fácil de olvidar: **FastAPI devuelve por
defecto `{"detail": [...]}`, que no es el sobre de PRD §23** y que
`frontend/lib/api/errors.ts:isApiErrorEnvelope` rechazaría, degradando el error a
`UNKNOWN_ERROR` en el cliente. Los `message` van en inglés (`backend.md`), los `code` son
estables y la traducción es cosa del frontend.

Códigos y estados: `VALIDATION_ERROR` 422, `INVALID_CREDENTIALS` 401, `INVALID_TOKEN` 401,
`FORBIDDEN` 403, `NOT_FOUND` 404, `RATE_LIMITED` 429, `INTERNAL_ERROR` 500.

Rejected: `try/except` en cada router — repetición garantizada y un olvido devuelve un 500
sin sobre. Rejected: middleware que reescriba respuestas ya serializadas — trabajo doble y
frágil con streaming.

### D12 — Identificación del cliente: IP del socket, y cabecera de proxy solo si se activa

**Chosen:** el limitador usa la IP del peer del socket (`request.client.host`) salvo que
`TRUSTED_CLIENT_IP_HEADER` esté configurada, en cuyo caso lee esa cabecera. **Por defecto
viene vacía**, es decir, no se confía en ninguna cabecera.

El motivo es concreto, no teórico. Hoy el túnel enruta solo a `frontend:3000` y el backend
está publicado en `127.0.0.1:8000`, así que toda request al backend llega o desde loopback
(túnel SSH de depuración) o desde otro contenedor de la red de compose: **no hay ninguna IP
de cliente fiable todavía**, y honrar `X-Forwarded-For` por defecto sería confiar en una
cabecera que cualquiera puede falsificar para saltarse el límite de R5.1. El día que la API
se enrute por el túnel habrá que poner `TRUSTED_CLIENT_IP_HEADER=CF-Connecting-IP`, o el
límite de 10/min contará todas las peticiones del despliegue en un solo contador y bastará
un atacante para bloquear el login de todo el mundo. Eso queda escrito en
`docs/auth-tenancy.md` y en la spec viva, y es la razón de que el bloqueo por cuenta de
R5.2 sea la defensa que sí funciona hoy.

Rejected: confiar en `X-Forwarded-For` por defecto — cabecera falsificable y hoy sin
ningún proxy que la ponga. Rejected: no limitar por IP y quedarse solo con el bloqueo por
cuenta — incumple R5.1.

### D13 — Contadores y bloqueo en Redis, con ventana fija asumida

**Chosen:** Redis, que ya está en el stack (`redis>=8.0.1` en `pyproject.toml`,
`REDIS_URL` en los tres composes) y es el único almacén compartido entre los procesos de
`backend` y `worker`, como pide R5.4. Un cliente `redis.asyncio` perezoso en
`app/core/redis.py`. Tres claves: `login:ip:{ip}` (`INCR` + `EXPIRE 60` en el primer
incremento), `login:fail:{user_id}` y `login:lock:{user_id}` con TTL igual al bloqueo.
El puerto `LoginThrottle` vive en `domain/ports.py` y su implementación Redis en
`infrastructure/`, así que los tests usan una implementación en memoria y no necesitan
Redis levantado.

Se asume **ventana fija**, no deslizante: en el peor caso permite hasta 20 intentos en dos
segundos a caballo del cambio de minuto. PRD §22 pide "10 intentos/min" sin más precisión y
el bloqueo por cuenta de R5.2 cubre justo ese escenario, así que no se añade la complejidad
de un contador deslizante.

Rejected: contadores en PostgreSQL — durables pero una escritura por intento en la ruta
crítica y con limpieza a mano. Rejected: contador en memoria del proceso — incumple R5.4
en cuanto hay más de un worker de uvicorn.

### D14 — Bootstrap como módulo ejecutable, nunca como migración de datos

**Chosen:** `app/cli/bootstrap.py`, ejecutable con
`uv run python -m app.cli.bootstrap`, más un target `make bootstrap`. Lee las variables
`BOOTSTRAP_*`, falla antes de escribir si falta alguna (R7.3), y es idempotente buscando
por `(tenant name)` y `(tenant_id, email)` (R7.2). Crea el `Tenant`, su `TenantConfig`
—que otros módulos asumen existente— y dos usuarios: `TENANT_OWNER` y `PROPERTY_MANAGER`.

**No se engancha a `make up`**, que sigue arrancando sin pasos manuales ni secretos: en
`.env.example` las variables `BOOTSTRAP_*` van con **nombre y sin valor**, conforme a la
regla 8 de `steering/security.md` y a R7.4, y el comando falla con un mensaje claro en
inglés si no se han rellenado. Es un paso explícito y consciente, no una sorpresa del
arranque.

**`JWT_SECRET_KEY` en local se genera, no se versiona** (ajustado durante `/sdd:run`, al
descubrir que `.env.example` ya declaraba desde `local-environment` que la clave de firma
JWT nunca puede llevar un valor por defecto ahí). El target `up` del `Makefile` la genera
con `openssl rand -hex 32` y la escribe en el `.env` local si falta o está vacía, de forma
idempotente. Cumple R6.7 al pie de la letra —fallo rápido en el compose, ningún valor real
en el repositorio— sin romper el arranque sin pasos manuales del DoD §28.20. Rejected: un
valor local explícitamente inseguro en `.env.example` — más simple, pero contradice un
comentario ya escrito en ese fichero y la regla 8 de `steering/security.md`.

Rejected: migración de datos de Alembic — mezcla esquema y contenido, no se puede
parametrizar por entorno y no se re-ejecuta con seguridad. Rejected: una CLI con Typer —
una dependencia nueva para un comando. Rejected: contraseñas por defecto en
`.env.example` para que `make up` deje todo listo — es exactamente lo que R7.4 prohíbe.

### D15 — Alcance honesto de los tests de aislamiento en este change

**Chosen:** R4.4 pide demostrar por cada uno de los cinco roles que un usuario del tenant A
no llega a datos del tenant B, pero en este change **los únicos endpoints que existen son
los de auth**, así que no hay recurso de negocio que cruzar. La prueba se hace en tres
niveles y se documenta como tal: (a) sobre el puerto `UserRepository` con dos tenants
poblados, parametrizado por los cinco roles; (b) sobre `GET /api/v1/auth/me` con un token
cuyo `tenant_id` es el de otro tenant para un `user_id` real, que debe dar 401 por D7; y
(c) sobre el caso de R4.5, token con tenant inexistente o no `ACTIVE`.

La matriz completa por endpoint de negocio llega con el primer módulo que los tenga
(`reservations`). Se deja escrito para que el panel de `/sdd:review` no lo lea como
requisito a medias, y para que ese módulo herede la obligación.

**R4.3 está en la misma situación y hay que declararlo igual** (lo levantó el panel de
`/sdd:review`: R4.4 tenía esta decisión y R4.3 no, así que la tabla de cobertura de
`tasks.md` afirmaba que la única parcial era R4.4 y eso era falso). R4.3 pide responder
`404` y no `403` al referenciar un recurso de otro tenant. Ningún endpoint de este change
recibe un identificador de recurso: `login`, `refresh`, `logout` y `me` son todos
autorreferenciales. Así que `NotFoundError` existe como maquinaria del sobre de error pero
**no tiene ni un call site en producción**, y no puede tenerlo hasta que haya un endpoint
con `{id}` en la ruta. R4.3 queda **unmet y declarado**, y la obligación la hereda
`reservations` junto con la matriz de R4.4.

Rejected: inventar un endpoint de negocio de prueba solo para ejercitar el cruce de
tenants o el 404 — código muerto en producción para satisfacer un test. Rejected:
declarar R4.4 o R4.3 cumplidos sin matizar — dejaría un falso verde en la spec viva.

### D16 — Filtro global por tenant en `do_orm_execute`, y el login como única excepción explícita

**Chosen** (resuelve OQ1): un listener del evento `do_orm_execute` de SQLAlchemy en
`app/core/db.py` que, **solo si la sesión lleva `session.info["tenant_id"]`**, añade un
`with_loader_criteria(<modelo>, cls.tenant_id == tenant_id, include_aliases=True)` por cada
modelo mapeado que tenga columna `tenant_id`. La sesión se marca en la dependencia
`get_authenticated_request`, no en `get_db_session()`, porque el tenant no se conoce hasta haber
verificado el token.

`with_loader_criteria` no acepta un mixin sin mapear como `TenantScopedMixin`, así que los
modelos afectados se recorren desde `Base.registry.mappers` filtrando por la presencia de la
columna, no por herencia de clase.

**Cinco límites que quedan escritos y no se disimulan** (los dos primeros desde el
principio; el tercero y el cuarto los levantó el panel de seguridad, y el quinto punto lo
levantó el de tenancy):

1. Cubre `SELECT`/`UPDATE`/`DELETE` de ORM, pero **no** `session.execute(text(...))` ni
   sentencias Core construidas a mano.
2. Solo se activa en sesiones con marca de tenant. Corren **sin marca**: las tareas de
   Celery, el bootstrap, la query anónima del login —que lo **necesita**, porque
   `find_by_email_across_tenants` todavía no tiene tenant— y **`POST /auth/refresh`**,
   que es anónimo y por tanto no pasa por `get_authenticated_request`, el único sitio que
   marca la sesión. Ese cuarto camino lo levantó el panel de seguridad y faltaba en
   esta lista: `RefreshTokenUseCase` emite cinco sentencias con la red desactivada,
   sobre un `tenant_id` que viene de un token presentado por el cliente. Hoy no hay
   fuga porque todos esos métodos llevan su `tenant_id` explícito (D6) y los tests de
   aislamiento lo demuestran, pero quien añada una query a ese camino creerá que la red
   está armada. Cualquier endpoint anónimo futuro que toque datos hereda el mismo aviso.
3. **Los INSERT no están cubiertos**: `session.add` no emite una sentencia ORM que el
   listener pueda reescribir, así que un insert cross-tenant lo para únicamente la
   comprobación explícita de `add()` en el repositorio.
4. **El mapa de identidad no está cubierto**: `session.get()`/`session.refresh()` pueden
   devolver un objeto ya cargado sin emitir SQL, así que una fila leída con la sesión sin
   marcar sigue siendo alcanzable después. De ahí que las entidades cargadas en el camino
   anónimo del login no deban entregarse a una sesión marcada.
5. **Las tablas hijas sin `tenant_id` propio quedan fuera**: `messages`,
   `cleaning_checklist_completions` y `cleaning_photos` cuelgan de un padre con tenant, y el
   escaneo empareja por presencia de columna. Cualquier repositorio futuro que las consulte
   debe unir explícitamente al padre scopado y traer su propio test de aislamiento — es la
   obligación que heredan `messaging` y `cleaning` por D15.

El escaneo **no se memoiza** a propósito: `Base.registry.mappers` solo crece a medida que se
importan los módulos de modelos, así que una caché excluiría para siempre a cualquier entidad
importada después de la primera query filtrada. Por el mismo motivo existe
`app/core/models_registry.py`, que importa los diez dominios en un único sitio compartido por
la aplicación, Alembic y los tests — antes `app/main.py` no importaba ninguno, así que la red
cubría menos tablas en producción que en la suite, incluida `guests`, que guarda el
`document_number` que `steering/security.md` nombra como PII.

Los puntos 3, 4 y 5 son la razón de que el `tenant_id` explícito de D6 siga siendo el
mecanismo autorizado y esto solo la red.

**La excepción del login.** `POST /auth/login` es anónimo: no hay tenant todavía, así que su
sesión no lleva marca y el filtro global no aplica. Es la única consulta legítimamente
cross-tenant del sistema, y para que sea imposible confundirla con un descuido el método del
puerto se llama `find_by_email_across_tenants(email)` — un nombre que salta en cualquier
`grep` y en cualquier revisión.

Eso destapa un problema real del esquema existente: `UserModel` tiene
`UniqueConstraint("tenant_id", "email")`, es decir, **el email es único por tenant, no
globalmente**, así que `{email, password}` no identifica a un usuario de forma inequívoca en
cuanto haya dos tenants. Resolución para el MVP, marcada como `ASSUMPTION`: la búsqueda
devuelve todos los usuarios con ese email y el login **solo procede si hay exactamente uno**;
con dos o más responde el mismo `401 INVALID_CREDENTIALS` genérico de R1.4, sin revelar la
colisión. Con un único tenant en el MVP el caso no se da, y cuando llegue el multi-tenant real
hará falta un discriminador en el login (subdominio, o `tenant` en el cuerpo) — queda anotado
como dependencia de `saas-cross-tenant`, no resuelto aquí.

Rejected: hacer el email globalmente único cambiando la constraint — rompería el modelo
multi-tenant de PRD §7 (dos clientes distintos pueden tener un empleado con el mismo email) y
toca una migración de `domain-foundation-core` que no es de este change. Rejected: exigir ya
un discriminador de tenant en el login — superficie y fricción para un problema que con un
tenant no existe, y cuya forma correcta (subdominio vs campo) depende de decisiones de la fase
SaaS que no están tomadas.

### D18 — El access token lleva también `fam`, para que el logout pueda cumplir R2.3

**Chosen** (refinamiento descubierto al implementar la sección 6): R2.3 dice que el logout
invalida "el token de refresh de esa sesión", pero el endpoint va autenticado con el
**access** token, cuyo `jti` es aleatorio y no guarda ningún vínculo con la familia de
refresh — tal como estaba diseñado, el logout no tenía forma de saber qué sesión cerrar.
El access token incorpora por tanto el claim `fam`, el mismo de su familia de refresh, y
`LogoutUseCase` revoca esa familia con `revoked_reason = LOGOUT`.

Rejected: que el logout reciba el refresh token en el cuerpo (estilo RFC 7009) — funciona
y no cambia el formato del token, pero obliga al cliente a guardar y enviar el refresh en
una llamada que ya va autenticada, y contradice la tabla de endpoints de este design, que
declara el logout como Bearer sin cuerpo. Rejected: revocar **todas** las sesiones del
usuario — cerraría la sesión del móvil al cerrar la del portátil, que no es lo que pide
R2.3.

### D19 — La normalización del email vive en Python, y el índice único la respalda

**Chosen** (hallazgo del panel de seguridad, secciones 3-4): `normalize_email` en
`auth/domain/value_objects.py` es la única definición de "el mismo email", se aplica **en
la escritura y en la lectura**, y la comparación SQL es una igualdad simple — nunca
`lower()` dentro de la query. Se añade además un índice único funcional sobre
`(tenant_id, lower(email))` como red para cualquier escritor futuro que olvide normalizar.

El motivo es concreto: la constraint existente `uq_users_tenant_id_email` es sensible a
mayúsculas, así que buscar con `lower()` y guardar en crudo permitía que `Jose@x.com` y
`jose@x.com` **convivieran en el mismo tenant**; la búsqueda las considera la misma
dirección, devuelve dos filas, y por la regla de "exactamente una" de D16 **las dos
cuentas quedan con 401 para siempre**. Cualquiera que pueda crear usuarios podía así
denegar el acceso a un email conocido de forma permanente — una versión sin límite del
bloqueo de 15 minutos que D13 sí acota. Y hay un segundo motivo para no mezclar motores:
Postgres y Python no coinciden al plegar mayúsculas (`lower('İ')` da un carácter en
Postgres y dos en Python).

Rejected: volver a la comparación exacta sensible a mayúsculas — elimina el desajuste
pero devuelve la trampa de usabilidad de que `Jose@x.com` no pueda entrar. Rejected:
`citext` o una columna generada — resuelve igual pero toca el esquema de `users`, que es
de `domain-foundation-core`, con más cirugía que un índice añadido.

### D20 — La ventana del throttle no puede quedarse sin expiración

**Chosen** (hallazgo del panel de seguridad, secciones 3-4): el contador por IP aplica el
TTL en **cada** intento (`EXPIRE ... NX`), no solo cuando `INCR` devuelve 1.

`INCR` y `EXPIRE` son dos viajes distintos: si el segundo no llega a ejecutarse —caída del
proceso, timeout, failover de Redis entre ambos— la clave se queda sin TTL y el contador
nunca caduca, así que esa IP queda **bloqueada para siempre** en vez de un minuto. Y con
la realidad de D12 (ninguna cabecera de confianza, así que hoy todo el tráfico llega con
la IP del contenedor del frontend) esa única clave es el presupuesto de login de todo el
despliegue: un `EXPIRE` perdido tumba el login hasta que alguien borre la clave a mano.

Rejected: un script Lua — atómico de verdad, pero introduce un artefacto que hay que
mantener y versionar para un contador de dos líneas. Rejected: dejarlo como estaba
asumiendo que el fallo es improbable — el radio de daño es el login completo.

### D17 — El patrón de capas se registra como ADR 0004

**Chosen** (resuelve OQ3): `docs/adr/0004-backend-layering-pattern.md`, siguiendo el formato
de los ADR 0001-0003 ya existentes, con lo que este change fija para todo el backend: regla
de dependencia y las cuatro capas, DI por `Depends`, sesión por request con el `commit` en el
caso de uso (D10), sobre de error por handlers globales (D11), `RequestContext` explícito más
el filtro global (D6, D16) y la cobertura de autorización por test de rutas (D9). Los designs
de `reservations`, `cleaning` y siguientes citan el ADR en vez de arrastrar la spec de
capacidad entera.

Rejected: dejarlo solo en `sdd/specs/auth-tenancy.md` y `docs/auth-tenancy.md` — obligaría a
citar una spec de capacidad de auth para justificar una decisión arquitectónica que no es de
auth.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Core / app | `backend/app/main.py` | `create_app()` + `app = create_app()`; registra routers y handlers; `/health` intacto (D2) |
| Core / errores | `backend/app/core/errors.py` *(nuevo)* | `AppError` y subclases, `register_error_handlers()`, reshape del 422 (D11) |
| Core / db | `backend/app/core/db.py` | añade la dependencia `get_db_session()` con rollback y close garantizados (D10) y el listener `do_orm_execute` del filtro global por tenant (D16) |
| Core / redis | `backend/app/core/redis.py` *(nuevo)* | cliente `redis.asyncio` perezoso y su dependencia (D13) |
| Core / config | `backend/app/core/config.py` | `jwt_secret_key`, vidas de token, umbrales de throttle, `trusted_client_ip_header`, `bootstrap_*`; fallo rápido sin secreto (D3, D12, D14) |
| Auth / domain | `backend/app/auth/domain/{ports,policy,context,exceptions,value_objects}.py` *(nuevos)* | puertos `UserRepository`/`SessionRepository`/`PasswordHasher`/`TokenCodec`/`LoginThrottle`, `Permission` + `ROLE_PERMISSIONS`, `RequestContext`, errores de dominio (D1, D6, D8) |
| Auth / domain | `backend/app/auth/domain/entities.py` | añade la entidad `UserSession` junto a `User` (D5) |
| Auth / application | `backend/app/auth/application/use_cases.py` *(nuevo)* | `LoginUseCase`, `RefreshTokenUseCase`, `LogoutUseCase`, `GetCurrentUserUseCase` (D10) |
| Auth / infrastructure | `backend/app/auth/infrastructure/{repositories,password_hasher,token_codec,throttle}.py` *(nuevos)* | adaptadores SQLAlchemy, bcrypt, PyJWT y Redis de los puertos (D3, D4, D13) |
| Auth / infrastructure | `backend/app/auth/infrastructure/models.py` | añade `UserSessionModel` (D5) |
| Auth / api | `backend/app/auth/api/{router,schemas,dependencies}.py` *(nuevos)* | los cuatro endpoints, DTOs Pydantic, `get_authenticated_request` y `require(permission)` (D7, D8) |
| Migraciones | `backend/alembic/versions/<rev>_auth_sessions.py` *(nuevo)* | tabla `user_sessions` con sus índices y el enum `session_revoked_reason` (D5) |
| CLI | `backend/app/cli/bootstrap.py` *(nuevo)* | bootstrap idempotente de tenant, config y dos usuarios (D14) |
| Tests | `backend/tests/auth/test_{login,refresh,logout,me,policy,isolation,throttle}.py`, `backend/tests/test_route_authorization.py`, `backend/tests/test_layering.py` *(nuevos)* | cobertura de R1-R7, cobertura de rutas (D9), regla de dependencia (R6.4), aislamiento (D15) |
| Tests / fixtures | `backend/tests/conftest.py` | importa `app.auth.infrastructure.models` ya (línea 12); añade fixtures de cliente HTTP con overrides, tenants y usuarios de dos tenants |
| Dependencias | `backend/pyproject.toml` | `pyjwt`, `bcrypt` en `dependencies`; `fakeredis` o doble en memoria en `dev` |
| Entorno | `.env.example`, `docker-compose.yml`, `Makefile` | `JWT_SECRET_KEY` y `BOOTSTRAP_*` por nombre sin valor, fallo rápido en el compose local, target `make bootstrap` (R6.7, D14) |
| Docs / ADR | `docs/adr/0004-backend-layering-pattern.md` *(nuevo)* | el patrón de capas de referencia para todo el backend (D17) |

## Data & interfaces

**Tabla nueva `user_sessions`** (D5) — `id` UUID PK (= `jti` del refresh), `tenant_id` UUID
FK `tenants.id` NOT NULL, `user_id` UUID FK `users.id` NOT NULL, `family_id` UUID NOT NULL,
`parent_id` UUID FK `user_sessions.id` NULL, `expires_at` TIMESTAMPTZ NOT NULL, `used_at`
TIMESTAMPTZ NULL, `revoked_at` TIMESTAMPTZ NULL, `revoked_reason` enum NULL, más
`created_at`/`updated_at`. Índices: `(tenant_id, user_id)`, `(family_id)`, `(expires_at)`.
Sin cambios en `users` ni en ninguna tabla existente.

**Endpoints** (todos bajo `/api/v1/`):

| Método | Ruta | Auth | Respuesta |
|---|---|---|---|
| POST | `/auth/login` | anónima | `200 {access_token, refresh_token, token_type:"bearer", expires_in}` |
| POST | `/auth/refresh` | anónima (el refresh va en el cuerpo) | `200` igual que login |
| POST | `/auth/logout` | Bearer | `204` sin cuerpo |
| GET | `/auth/me` | Bearer | `200 {id, tenant_id, name, email, role, preferred_language}` |

`GET /auth/me` no devuelve `password_hash` nunca (R2.6): el schema Pydantic de salida
enumera los campos, no serializa la entidad.

**Claims del token** (R1.5): `sub` (user_id), `tenant_id`, `role`, `type`
(`"access"`|`"refresh"`), `jti`, `iat`, `exp`; el refresh añade `fam`. La verificación
comprueba `type` contra el esperado, así que un refresh no vale como access ni al revés
(R2.5).

**Variables de entorno nuevas** — `JWT_SECRET_KEY` (requerida, sin default, fallo al
arrancar), `JWT_ACCESS_TOKEN_MINUTES` (15), `JWT_REFRESH_TOKEN_DAYS` (7),
`BCRYPT_ROUNDS` (12), `LOGIN_RATE_LIMIT_PER_MINUTE` (10), `LOGIN_MAX_FAILED_ATTEMPTS` (10),
`LOGIN_LOCKOUT_MINUTES` (15), `TRUSTED_CLIENT_IP_HEADER` (vacía), `BOOTSTRAP_TENANT_NAME`,
`BOOTSTRAP_TENANT_BILLING_EMAIL`, `BOOTSTRAP_OWNER_NAME/EMAIL/PASSWORD`,
`BOOTSTRAP_MANAGER_NAME/EMAIL/PASSWORD`.

**Cobertura de requisitos:** R1 → D3, D4, D7, D11, D16 · R2 → D5, D10 · R3 → D8, D9 ·
R4 → D6, D7, D15, D16 · R5 → D12, D13 · R6 → D1, D2, D10, D11, D17 · R7 → D14. Ningún
requisito queda sin decisión asociada.

## Risks & mitigations

- **La migración de `user_sessions` corre sobre una base con datos** — es una tabla nueva
  con FKs a `tenants` y `users`, sin `ALTER` sobre nada existente, así que el `downgrade`
  es un `drop_table` limpio. Riesgo bajo; se verifica con `upgrade head` y `downgrade -1`
  en la base de test.
- **`Base.metadata.create_all` de `tests/conftest.py` no ejecuta las migraciones**, así que
  un error de Alembic no lo detecta la suite. Mitigación: una prueba explícita del ciclo
  `upgrade`/`downgrade`, que hoy no existe para ninguna migración.
- **La revalidación por request de D7 añade una query a cada llamada autenticada** —
  irrelevante con 2 viviendas, y el índice de `users` por PK lo hace trivial. Si algún día
  molesta, el remedio es una caché corta en Redis, no volver a confiar en los claims.
- **`user_sessions` crece sin límite**: cada login y cada rotación insertan una fila y nada
  las borra. Con este volumen es despreciable, pero la limpieza de filas expiradas es un
  job de `celery-jobs`; se anota como seguimiento, no se implementa aquí.
- **El bloqueo por cuenta de R5.2 es una vía de denegación de servicio contra un usuario
  concreto**: quien conozca un email puede dejar la cuenta bloqueada 15 minutos en bucle.
  Es inherente a lo que pide PRD §22; el bloqueo temporal en vez de permanente (D13) acota
  el daño, y el límite por IP lo encarece en cuanto haya IPs de cliente reales (D12).
- **Riesgo de contrato con el frontend**: si el sobre de error no sale exactamente como lo
  espera `frontend/lib/api/errors.ts`, el cliente degrada todo a `UNKNOWN_ERROR` y los
  mensajes se pierden en silencio. Mitigación: un test por cada código de error afirmando
  la forma `{error:{code,message}}`, incluido el 422 reformado.
- **El filtro global de D16 puede dar una falsa sensación de cobertura**: no alcanza a
  `text()` ni a sentencias Core, y no se activa en sesiones sin contexto (Celery, bootstrap,
  login). El riesgo real es que un desarrollador futuro asuma que el aislamiento es
  automático y deje de pasar el `tenant_id` explícito. Mitigación: los dos límites quedan
  escritos en el ADR 0004 y en la spec viva, los parámetros explícitos de D6 siguen siendo la
  vía autorizada, y el reviewer `sdd-review-tenancy` ya existente verifica el scoping por
  diff en cada change.
- **El login cross-tenant de D16 es la excepción que podría copiarse por error**: un método
  que consulta sin `tenant_id` es exactamente lo que la regla 1 de `steering/security.md`
  prohíbe. Mitigación: el nombre `find_by_email_across_tenants` lo hace visible en cualquier
  `grep` y en la revisión, y es el único método del puerto sin `tenant_id` en la firma.

## Open questions

Las tres preguntas abiertas de este diseño se resolvieron con el usuario en el gate de
`/sdd:design` (2026-07-30). No queda ninguna abierta.

**OQ1 — Defensa estructural del aislamiento: resuelta → `with_loader_criteria` ahora.**
Ver **D16**. El motivo de hacerlo en este change y no en `reservations` es que este es el
patrón de referencia: si la red llegara después, los módulos intermedios se habrían escrito
sin ella y sus tests no la ejercitarían. RLS queda descartado por su coste en migraciones,
rol de base de datos y `conftest.py`. Al aterrizar la decisión apareció un problema de
esquema —email único por tenant, luego `{email, password}` es ambiguo— que se resuelve en
la misma D16 y que no se había detectado al escribir el proposal.

**OQ2 — Camino a la API en dev: resuelta → entrada nueva del roadmap.** Registrada como
`api-ingress-routing` detrás de `auth-tenancy`, con la inclinación técnica anotada allí
(`rewrite` de Next.js sobre el `BACKEND_INTERNAL_URL` que el frontend ya recibe, en lugar de
una segunda regla de ingress que le daría al túnel una ruta directa al backend). **No
bloquea este change**: la implementación y los tests son locales, y la verificación en el
dev desplegado se hace por túnel SSH (`ssh -L 8000:localhost:8000`, RUNBOOK §7.4).

**OQ3 — ADR del patrón de capas: resuelta → sí, ADR 0004.** Ver **D17**.
