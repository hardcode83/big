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
- THE SYSTEM SHALL referenciar ese registro desde los siete sitios que emiten un código:
  los atributos `code` de las subclases de `AppError`, el diccionario `_HTTP_STATUS_CODES`,
  las tablas `_MAPPING` de `auth`, `reservations` y `tenants`, los literales de
  `integrations` y `TOO_LARGE_CODE` de `app/core/http_limits.py`.
- THE SYSTEM SHALL fallar la suite si alguno de esos sitios contiene un valor que no sea
  miembro de `ErrorCode`, recorriéndolos estructuralmente y descendiendo en profundidad por
  las subclases de `AppError`.
- THE SYSTEM SHALL publicar el catálogo completo como `enum` en el esquema de
  `ErrorEnvelope.code`, para que un consumidor pueda hacer un `switch` exhaustivo
  comprobado por su compilador. El catálogo publicado y el registro deben coincidir
  exactamente.

Los once códigos son `INTERNAL_ERROR`, `HTTP_ERROR`, `VALIDATION_ERROR`, `CONFLICT`,
`PAYLOAD_TOO_LARGE`, `METHOD_NOT_ALLOWED`, `INVALID_CREDENTIALS`, `INVALID_TOKEN`,
`FORBIDDEN`, `RATE_LIMITED` y `NOT_FOUND`.

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

### Verificación estructural sin vacuidad

- THE SYSTEM SHALL aplanar el árbol de rutas con el walk compartido de
  `tests/route_walk.py`, que desciende por `original_router`/`include_context.prefix`.
  Filtrar `app.routes` por `isinstance(route, APIRoute)` **no** funciona: esta versión de
  FastAPI guarda cada router incluido como un único `_IncludedRouter`, así que ese filtro
  no encuentra ninguna ruta y la comprobación pasa sin inspeccionar nada.
- THE SYSTEM SHALL comprobar que la guarda de modelos de respuesta ve al menos las 18 rutas
  reales y los cinco prefijos, porque una guarda que reporta éxito sobre una lista vacía es
  peor que no tenerla.
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

- THE SYSTEM SHALL documentar en el README la ruta del artefacto, el comando que lo
  regenera y el comando que deriva tipos TypeScript de él.
- El frontend **no** consume todavía esos tipos. Cablearlos en `frontend/lib/api/` —hoy
  `client.ts` devuelve `unknown` a propósito— pertenece a la entrada `frontend-ci` del
  roadmap, que añadirá `openapi-typescript` como `devDependency` con lockfile y la
  comprobación de que los tipos no han derivado del contrato.

## Estado

- **El documento servido y el commiteado son el mismo**: `install_openapi()` sustituye
  `app.openapi`, así que `/docs`, `/openapi.json` y `backend/openapi.json` no pueden
  divergir.
- **Deuda con dueño**: la guarda de integridad del registro recorre los `_MAPPING`, las
  subclases de `AppError` y `_HTTP_STATUS_CODES`, pero **no las llamadas sueltas a
  `error_envelope(...)`**. Los siete sitios de hoy están cubiertos, pero un módulo futuro
  que pase un literal directamente se colaría, y el contrato promete que ningún código vive
  fuera del registro. Cerrarlo pide una comprobación por AST sobre `backend/app/**` que
  rechace un primer argumento literal. Lo levantó el panel de QA en el `/sdd:review` del
  change.
- **El límite del guard de red**: bloquear los constructores de `socket` cubre cualquier
  ruta que necesite un event loop —`asyncio` abre un `socketpair` al arrancar—, pero
  `uvloop` (transitivo de `uvicorn[standard]`) crearía sockets en C sin pasar por el módulo.
  Inerte mientras nada instale uvloop y la generación sea síncrona.
- **Sin protección de rama**: como el resto de checks del repositorio, `api-contract` se
  ejecuta y reporta pero no puede marcarse obligatorio (`specs/backend-ci.md` §Estado).
- El contrato declara `HTTPBearer` como esquema de seguridad, y 16 de las 19 operaciones lo
  referencian; las tres restantes son `login`, `refresh` y `GET /health`.

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
