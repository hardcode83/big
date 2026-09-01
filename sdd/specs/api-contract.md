# Contrato de API (OpenAPI)

## Purpose

Esta capacidad publica la forma de la API REST como un artefacto versionado del
repositorio, `backend/openapi.json`, para que el frontend tenga una fuente compartida de
la que derivar tipos y para que un cambio en la forma de una respuesta aparezca en el diff
del Pull Request que lo provoca.

Su alcance está acotado a propósito y conviene no leerlo de más: **no protege de cambios
incompatibles**. El check de CI solo detecta que alguien olvidó regenerar el fichero;
renombrar un campo lo deja en verde en cuanto se regenera. Quien rompe ante eso es el
typecheck del frontend contra los tipos derivados, que pertenece a otra capacidad.

## Requirements

### El artefacto y su generación

- THE SYSTEM SHALL escribir el documento OpenAPI de `create_app()` en
  `backend/openapi.json` cuando se ejecuta `make openapi` o
  `python -m app.cli.openapi`.
- THE SYSTEM SHALL producir una salida **byte-idéntica** entre ejecuciones sobre el mismo
  código, serializando con claves ordenadas, indentación de 2 y salto de línea final. El
  orden de inserción que produzcan FastAPI y Pydantic no puede influir: si influyera, el
  check de deriva fallaría de forma intermitente y se leería como un test inestable en vez
  de como el defecto que es.
- THE SYSTEM SHALL generar el documento **sin base de datos, Redis ni red**. Solo importa
  la aplicación y serializa su esquema; `Settings` exige una única variable para importar
  (`jwt_secret_key`, con suelo de 32 caracteres) y ni `database_url` ni `redis_url` abren
  conexión.
- WHERE la generación corre en CI, THE SYSTEM SHALL usar una clave JWT de usar y tirar
  generada en el momento con `openssl rand -hex 32`, nunca un secreto versionado ni un
  GitHub Secret. Un valor que no llegue a 32 caracteres aborta el import con un error de
  Pydantic que **re-codifica** el valor (`ab\cd` sale como `'ab\\cd'`), y esa
  transformación evade el enmascarado por coincidencia exacta de GitHub Actions.
- THE SYSTEM SHALL escribir el fichero indentado, una clave por línea, para que el diff sea
  legible en revisión.
- THE SYSTEM SHALL declarar en `info.version` la versión del paquete leída de
  `backend/pyproject.toml`. **Nunca** la cadena de build de `app-version-visibility`
  (`0.1.0+2026-07-31.5872022`), que cambiaría en cada commit y dejaría el check
  permanentemente en rojo; ni el `VERSION` de la raíz, que el contenedor no ve porque monta
  solo su propio directorio.

### El registro único de códigos de error

- THE SYSTEM SHALL definir en `app/core/error_codes.py` el `StrEnum` `ErrorCode` como
  **única fuente de verdad** de los códigos del envoltorio de PRD §23.
- THE SYSTEM SHALL referenciar ese registro desde todos los sitios que emiten un código: los
  atributos `code` de las subclases de `AppError`, el diccionario `_HTTP_STATUS_CODES`, las
  **once** tablas `_MAPPING` de `access`, `auth`, `cleaning`, `guests`, `maintenance`,
  `messaging`, `pricing`, `properties`, `reservations`, `tenants` y `timeline`, los literales de
  `integrations` y `TOO_LARGE_CODE` de `app/core/http_limits.py`. La de `cleaning`
  existía desde aquel change y quedaba fuera de la guarda; entró con `cleaning-photos-storage`,
  que es lo que hizo que la omisión importara — le añade cuatro filas, una con un código
  (`BAD_GATEWAY`) que ninguna otra tabla emite.
- THE SYSTEM SHALL incluir cada `_MAPPING` nuevo en la guarda que recorre el registro. Una
  tabla que la guarda no importa queda fuera de la comprobación aunque exista, y el módulo
  seguiría pudiendo emitir un literal ajeno a `ErrorCode` sin que la suite lo notara.
  `revenue-pricing` cumplió esta regla en la **misma** tarea que creó su tabla y no una tarea
  después, citando en el comentario de la guarda que el hueco ya se había estrenado antes. Hoy
  **la guarda importa seis de las once** —`auth`, `cleaning`, `pricing`, `properties`,
  `reservations` y `tenants`—; las cinco que faltan están en §Estado como deuda con dueño.
- THE SYSTEM SHALL fallar la suite si alguno de esos sitios contiene un valor que no sea
  miembro de `ErrorCode`, recorriéndolos estructuralmente y descendiendo en profundidad por
  las subclases de `AppError`.
- THE SYSTEM SHALL publicar el catálogo completo como `enum` en el esquema de
  `ErrorEnvelope.code`, para que un consumidor pueda hacer un `switch` exhaustivo
  comprobado por su compilador. El catálogo publicado y el registro deben coincidir
  exactamente.

Los **catorce** códigos son `INTERNAL_ERROR`, `HTTP_ERROR`, `VALIDATION_ERROR`, `CONFLICT`,
`PROPERTY_STATE_CONFLICT`, `PAYLOAD_TOO_LARGE`, `METHOD_NOT_ALLOWED`, `INVALID_CREDENTIALS`,
`INVALID_TOKEN`, `FORBIDDEN`, `RATE_LIMITED`, `PASSWORD_CHANGE_REQUIRED`, `NOT_FOUND` y
`BAD_GATEWAY`.

Tres de ellos existen para partir en dos un status que ya estaba ocupado, y por el mismo motivo
las tres veces —que son dos mensajes distintos que enseñar a una persona distinta—:

- `BAD_GATEWAY` lo añadió `cleaning-photos-storage` para el fallo del almacén de ficheros,
  distinto de `INTERNAL_ERROR` a propósito: el frontend distingue «reintentar puede funcionar» de
  «esto es un bug nuestro», y son dos mensajes distintos que enseñar a una limpiadora con una foto
  que no sube.
- `PASSWORD_CHANGE_REQUIRED` lo añadió `auth-account-recovery`.
- `PROPERTY_STATE_CONFLICT` lo añadió `cleaning-assign-preconditions` para separar del `CONFLICT`
  del `409` la negativa que viene de la **máquina de estados de la vivienda** y no del ciclo de
  vida del recurso pedido. Conserva el sufijo del código del que se separa, que es lo que hace
  legible que sigan compartiendo el `409`. Su emisor es la clase de excepción
  (`PropertyStateBlocksCleaningError`), así que lo produce **toda** operación de limpieza que la
  matriz bloquee y no solo la asignación; el detalle vive en [`cleaning.md`](cleaning.md).

**Esta cifra en prosa no la guarda ningún test, y ha estado desviada.** La igualdad que la suite
sí afirma es la del párrafo anterior —catálogo publicado ↔ registro—, y esa se cumplió siempre;
lo que derivó es la enumeración de aquí. `PASSWORD_CHANGE_REQUIRED` entró el 2026-08-11 con
`auth-account-recovery` y no se escribió, así que cuando `incident-photos` corrigió «once → doce»
el 2026-08-23 la lista ya estaba corta en uno y la corrección la dejó igual de corta.
`cleaning-assign-preconditions` la reconstruyó contra `ErrorCode` en vez de incrementarla, que es
la única forma de que un recuento en prosa vuelva a ser cierto.

### Lo que el documento declara sobre los errores

- THE SYSTEM SHALL registrar el esquema `ErrorEnvelope` —espejo de
  `app.core.errors.error_envelope()`— y hacer que **toda** respuesta 4xx/5xx con cuerpo lo
  referencie, incluida la `422` que FastAPI genera por su cuenta.
- THE SYSTEM SHALL eliminar del documento los esquemas `HTTPValidationError` y
  `ValidationError` de FastAPI, cuya forma (`{"detail": [...]}`) el backend no devuelve
  nunca y que `frontend/lib/api/errors.ts` degradaría a `UNKNOWN_ERROR`.
- THE SYSTEM SHALL eliminarlos **solo cuando nada los referencia**: un modelo de dominio
  futuro llamado `ValidationError` se borraría estando aún referenciado y dejaría un `$ref`
  colgante en el artefacto publicado.
- THE SYSTEM SHALL aplicar la corrección como post-proceso sobre el documento generado, no
  declarando `responses=` en cada decorador: FastAPI inyecta ese `422` automáticamente en
  cuanto un endpoint tiene cuerpo o parámetros validados, así que un arreglo por decorador
  se olvidaría en el endpoint siguiente.
- THE SYSTEM SHALL declarar `401` y `403` a nivel de `APIRouter` en los routers cuyas rutas
  cuelgan de la dependencia de autorización (`users`, `tenants`, `reservations`,
  `integrations`) y por ruta en las autenticadas de `auth`, dejando `login` y `refresh` sin
  declararlos porque son anónimas por diseño.
- THE SYSTEM SHALL **no** enumerar por endpoint los estados que *podría* devolver (el `404`
  cross-tenant, el `409` de email duplicado, el `429` del throttle). Un catálogo plausible
  pero no verificado sustituiría la mentira que esta capacidad corrigió por otra distinta.
  Un endpoint que quiera declarar el suyo lo hace en su propio `responses=`.
- THE SYSTEM SHALL declarar todo endpoint bajo `/api/v1` cuyo código de éxito no sea `204`
  con un modelo de respuesta, verificado estructuralmente sobre las rutas registradas.
- WHERE el cuerpo de éxito no es JSON y por tanto no tiene modelo Pydantic que nombrar, THE
  SYSTEM SHALL admitir en su lugar un bloque `content` que enumere sus media types. Hoy es
  exactamente `GET /cleaning-photos/{photo_id}`, que devuelve bytes de imagen y declara
  `image/jpeg`, `image/png` e `image/webp` — la misma allowlist desde la que se resuelve el
  `Content-Type` servido, así que el contrato no puede desviarse de lo que la ruta manda.
- THE SYSTEM SHALL mantener esa exención **estrecha**: un `content` ausente o vacío no la
  satisface y sigue fallando la guarda, comprobado con rutas de prueba que declaran una cosa y
  la otra.

### Verificación estructural sin vacuidad

- THE SYSTEM SHALL aplanar el árbol de rutas con el walk compartido de
  `tests/route_walk.py`, que desciende por `original_router`/`include_context.prefix`.
  Filtrar `app.routes` por `isinstance(route, APIRoute)` **no** funciona: esta versión de
  FastAPI guarda cada router incluido como un único `_IncludedRouter`, así que ese filtro
  no encuentra ninguna ruta y la comprobación pasa sin inspeccionar nada.
- THE SYSTEM SHALL comprobar que la guarda de modelos de respuesta ve al menos 22 rutas
  reales, porque una guarda que reporta éxito sobre una lista vacía es peor que no tenerla.
  El suelo de rutas es un mínimo —añadir una no lo rompe— pero el conjunto de prefijos es
  **exacto**, de modo que un módulo nuevo tiene que nombrarse ahí y no puede colarse sin
  aparecer en el diff.
- THE SYSTEM SHALL comprobar la **fidelidad** contra respuestas reales: una petición
  inválida y una ruta inexistente devuelven cuerpos que validan contra el `ErrorEnvelope`
  publicado. Sin esto, el documento solo sería coherente consigo mismo, que es exactamente
  el defecto corregido con otro disfraz.
- THE SYSTEM SHALL comprobar que la generación no abre ningún socket, monkeypatcheando los
  constructores de `socket`. Es la propiedad de la que depende el job de CI, que corre sin
  PostgreSQL ni Redis mientras local y `backend-tests` siempre los tienen levantados.
- THE SYSTEM SHALL comprobar que el mecanismo de estabilidad **detecta** deriva por
  configuración, empujando por el mismo serializador un documento que sí depende de
  `Settings`. Ningún esquema de `app/` lo hace hoy, así que sin esa comprobación el test de
  estabilidad no podría fallar.

### El gate de CI

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar el workflow `api-contract`, que regenera el contrato y lo compara con el
  commiteado.
- IF difieren, THEN THE SYSTEM SHALL fallar mostrando el diff unificado y el comando exacto
  que lo resuelve.
- THE SYSTEM SHALL ejecutarlo **sin filtro de rutas**, por el mismo motivo que
  `specs/backend-ci.md` documenta: un check requerido con filtro no se ejecuta en los PR
  que no las tocan y los deja bloqueados esperando indefinidamente.
- THE SYSTEM SHALL usar el mismo generador que escribe el fichero, no una segunda
  implementación en el workflow: un check con su propia serialización fallaría por un
  motivo que nadie puede reproducir en su máquina.
- THE SYSTEM SHALL correr **sin** services de PostgreSQL ni Redis, conceder solo
  `contents: read` y pinear cada action por SHA. Es un workflow propio y no un paso de
  `backend-tests`: no necesita esos servicios —da señal en ~17 s frente a ~7 min— y como
  paso mezclaría dos señales que fallan por motivos distintos.

### Consumo

- THE SYSTEM SHALL mantener `backend/openapi.json` como única fuente de la que el frontend
  deriva sus tipos TypeScript.
- THE SYSTEM SHALL usar un único generador oficial, `openapi-typescript`, fijado exactamente
  en `frontend/package.json` y `frontend/package-lock.json`.
- THE SYSTEM SHALL escribir el artefacto generado en
  `frontend/lib/api/generated/openapi.d.ts`, que contiene declaraciones TypeScript y no
  clientes, wrappers ni lógica runtime.
- THE SYSTEM SHALL ofrecer desde `frontend/` los comandos `npm run api:generate` para regenerar
  el artefacto y `npm run api:check` para compararlo sin modificarlo.
- WHEN `npm run api:check` detecta una diferencia, THE SYSTEM SHALL fallar mostrando un diff
  del artefacto y el comando exacto de regeneración.
- THE SYSTEM SHALL ejecutar el mismo flujo versionado en macOS, Linux y CI, con Node 22,
  `npm ci` y salida normalizada a bytes reproducibles.
- THE SYSTEM SHALL mantener el transporte en `frontend/lib/api/` genérico: sus rutas y métodos
  se restringen a `paths` y sus cuerpos JSON/respuestas de éxito se derivan del contrato; las
  respuestas no-OK continúan pasando por `ApiError` y `parseApiError`, sin tipos de error por
  endpoint ni wrappers de dominio.

### Alcance público del documento

- THE SYSTEM SHALL mantener `/openapi.json`, `/docs`, `/docs/oauth2-redirect` y `/redoc`
  **fuera del camino público**: siguen en la allowlist anónima y siguen siendo alcanzables
  solo desde la VM (túnel SSH), porque el proxy de `/api/` no los enruta (spec
  `ingress-https-dev` §Camino a la API). Decisión explícita que el panel de seguridad de
  `api-contract-export` dejó pendiente para `api-ingress-routing`; el contrato que consume
  el frontend es `backend/openapi.json` versionado, así que exponer `/docs` no aportaría
  nada que compense publicar la forma completa de la API.

## Estado

- **El documento servido y el commiteado son el mismo**: `install_openapi()` sustituye
  `app.openapi`, así que `/docs`, `/openapi.json` y `backend/openapi.json` no pueden
  divergir.
- **Cinco `_MAPPING` viven fuera de la guarda** (medido el 2026-08-18, al archivar
  `revenue-pricing`): existen once tablas en `app/*/api/errors.py` y
  `tests/test_openapi_contract.py` importa seis. Las de `access`, `guests`, `maintenance`,
  `messaging` y `timeline` no entran, así que ninguna está cubierta por la comprobación que sí
  cubre a las otras seis. No es un hueco de pricing —`pricing` sí entró— sino **el mismo hueco
  que `properties` y `cleaning` ya tuvieron**, repetido por los changes que estrenaron esos
  módulos. Y los tests por módulo no lo tapan: `access`, `guests`, `maintenance` y `timeline` no
  tienen `test_errors.py`, y el de `messaging` compara contra miembros de `ErrorCode` que, siendo
  un `StrEnum`, son iguales al literal equivalente — un `"NOT_FOUND"` a pelo pasaría, que es
  exactamente el fallo que el panel de `properties-crud` demostró inyectando una cadena. Cerrarlo
  es añadir los cinco `import` a la tupla de la guarda; lo que le falta es dueño.
- **Deuda con dueño**: la guarda de integridad del registro recorre los `_MAPPING`, las
  subclases de `AppError` y `_HTTP_STATUS_CODES`, pero **no las llamadas sueltas a
  `error_envelope(...)`**. Los **catorce** sitios de hoy pasan todos un miembro de `ErrorCode`
  —cuatro en `integrations/api/errors.py`, tres en `integrations/api/webhooks_router.py`, tres en
  `cleaning/api/photos_router.py`, dos en `guests/api/portal_router.py`, uno en
  `guests/api/errors.py` y uno en el propio `core/errors.py`, el del `422` de validación—, pero un módulo futuro que pase un literal directamente se colaría, y
  el contrato promete que ningún código vive fuera del registro. `pricing` no añade ninguno: su
  handler pasa el `code` que le da su `_MAPPING`, que sí está en la guarda. Cerrarlo pide una comprobación por AST sobre `backend/app/**` que
  rechace un primer argumento literal. Lo levantó el panel de QA en el `/sdd:review` del
  change.
- **El límite del guard de red**: bloquear los constructores de `socket` cubre cualquier
  ruta que necesite un event loop —`asyncio` abre un `socketpair` al arrancar—, pero
  `uvloop` (transitivo de `uvicorn[standard]`) crearía sockets en C sin pasar por el módulo.
  Inerte mientras nada instale uvloop y la generación sea síncrona.
- **Sin protección de rama**: como el resto de checks del repositorio, `api-contract` se
  ejecuta y reporta pero no puede marcarse obligatorio (`specs/backend-ci.md` §Estado).
- El contrato declara `HTTPBearer` como esquema de seguridad, y 92 de las 104 operaciones lo
  referencian. Las doce restantes son `GET /health`, `POST /api/v1/auth/login`,
  `POST /api/v1/auth/refresh`, `POST /api/v1/auth/forgot-password`,
  `POST /api/v1/auth/reset-password`, `GET /api/v1/cleaning-photos/{photo_id}`,
  `GET /api/v1/incident-photos/{photo_id}`,
  `POST /api/v1/webhooks/{provider}/{webhook_token}` y las cuatro del portal del huésped
  (`GET /api/v1/guest/info/{token}`, `GET` y `POST /api/v1/guest/checkin/{token}`,
  `POST /api/v1/guest/incident/{token}`). Las siete últimas son las anónimas que **tocan datos de
  un tenant**, y cada una lo resuelve por su lado porque el llamante no puede mandar cabecera
  `Authorization`: las **dos** de fotos —la de limpieza y la de incidencia—, con la firma HMAC de
  su query string, porque un navegador que resuelve un `<img src>` no la manda; la de webhooks, con
  el token opaco de la ruta más el
  secreto de cabecera del tenant (`specs/reservations-webhooks.md`), porque el llamante es el PMS
  y no tiene sesión; las cuatro del portal, con `GuestPortalAuthenticator` sobre el token de la
  ruta (`specs/guest-portal-api.md`). Las doce están nombradas **con su verbo** en el allowlist de
  `tests/test_route_authorization.py`, que es el diff visible que ese allowlist existe para forzar.
- **Las dieciséis rutas de `maintenance` entraron todas autenticadas y con permiso declarado**:
  quince bajo `/api/v1/incidents` —las dos últimas,
  `POST` y `GET /api/v1/incidents/{incident_id}/photos`, entraron el 2026-08-23 con
  [`incident-photos`](incident-photos.md), y antes de ellas
  `POST /api/v1/incidents/{incident_id}/reject`, el 2026-08-22 con
  [`tech-cycle-completion`](maintenance.md)— y
  `POST /api/v1/owner-approvals/{approval_id}/respond`. Sólo una capacidad del módulo tocó el
  allowlist anónimo: `incident-photos`, que le añadió la **duodécima** entrada
  (`GET /api/v1/incident-photos/{photo_id}`) porque un `<img src>` no puede mandar
  `Authorization`. Las otras no: la proyección de contexto del técnico exige `READ_INCIDENTS` como
  el resto del módulo, y las dos rutas autenticadas de foto también.
- **Las dos rutas de `cleaning-stall-blocks-next-stay` entraron autenticadas y con permiso
  declarado** (2026-08-23): `POST /api/v1/cleaning-tasks/{task_id}/cancel`
  (`MANAGE_CLEANING_TASKS`) y `GET /api/v1/blocked-transitions` (`READ_PROPERTIES`), la segunda
  servida por un **segundo router del módulo `properties`** con su propio prefijo, porque colgar un
  segmento literal del router de `/properties` colisiona con `/properties/{id}`. Es el mismo patrón
  con que `dashboard` sirve sus dos prefijos. La cancelación declara `200/401/403/409/422` y no
  declara el `404` cross-tenant que sí emite, igual que sus cinco rutas hermanas del ciclo de la
  tarea: es convención del módulo y no una regresión de esta capacidad, y lo que la enumeración de
  arriba prohíbe es justamente ese catálogo plausible por endpoint. La colección devolvía los seis
  campos originales (`property_id`, `property_code`, `reservation_id`, `trigger`, `blocking_state`,
  `due_since`) y el 2026-08-27, con `blocked-transition-response-ids`, se le sumaron
  `cleaning_task_id` e `incident_id` (ambos `uuid | null`, opcionales, `null` cuando no apliquen),
  sin breaking change: los seis originales siguen siendo los únicos campos `required` en
  `openapi.json`. La regla de `extra="forbid"` del modelo de query
  `BlockedTransitionListQuery` rechaza `?tenant_id=…` con `422` antes de llegar al lookup,
  y los dos ids se resuelven tenant-scoped en una sola llamada batch por tabla y página.
- **La ruta de `cleaner-photo-requirements` entró autenticada y con permiso declarado**
  (2026-08-24): `GET /api/v1/cleaning-tasks/{task_id}/photo-requirements` con
  `READ_CLEANING_TASKS`, la cuarta proyección de solo lectura del router de tareas. No tocó el
  allowlist anónimo —siguen siendo doce— y declara `404` con sus **dos** causas alcanzables desde su
  propio handler, que es el criterio que sus rutas hermanas de foto ya fijaron: cada entrada es una
  fila del `_MAPPING` del módulo alcanzada desde una sentencia `raise` propia, no un catálogo
  plausible por endpoint. Sus dos esquemas se nombraron **evitando** el prefijo `CleaningPhoto`, que
  ya es una de las colisiones desambiguadas por módulo de este documento: una tercera manglaría
  también las dos que hoy sobreviven, y son nombres que un consumidor del frontend escribe a mano.

- **Las siete rutas de `messaging` entraron igual** (2026-08-16), todas bajo
  `/api/v1/conversations` y repartidas entre `READ_CONVERSATIONS` y `MANAGE_CONVERSATIONS`
  ([`messaging-ai.md`](messaging-ai.md)). Tampoco tocaron el allowlist anónimo: una conversación
  con un huésped se lee y se escribe siempre desde una sesión autenticada, porque el huésped no
  es quien llama — llama el panel, o la API, con una persona detrás.
- **Las siete rutas de `revenue-reviews` entran igual** (2026-09-01): seis bajo
  `/api/v1/reviews` y una bajo `/api/v1/properties/{id}/reviews/summary`, repartidas entre
  `READ_REVIEWS`, `CREATE_REVIEW`, `APPROVE_REVIEW`, `IGNORE_REVIEW` y `MARK_REVIEW_POSTED`
  ([`revenue-reviews.md`](../sdd/changes/revenue-reviews/proposal.md)). Tampoco tocan el
  allowlist anónimo: una reseña la da de alta un manager, la lee un manager o la propietaria,
  y la publica una persona — el flujo no tiene superficie sin token.

## Key files

- `backend/openapi.json` — el artefacto versionado.
- `backend/app/core/error_codes.py` — el registro `ErrorCode`.
- `backend/app/core/openapi.py` — `ErrorEnvelope`, `build_openapi()`, `install_openapi()` y
  `AUTHENTICATED_RESPONSES`.
- `backend/app/cli/openapi.py` — generación y modo `--check`.
- `backend/tests/route_walk.py` — el walk compartido con `test_route_authorization.py`.
- `backend/tests/test_openapi_contract.py` — las guardas estructurales y de fidelidad.
- `.github/workflows/api-contract.yml` — el gate de deriva.
- `Makefile` — target `openapi`.
