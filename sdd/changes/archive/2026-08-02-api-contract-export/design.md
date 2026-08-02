# Design: api-contract-export

## Context

`backend/app/main.py:create_app()` monta cinco routers bajo `/api/v1` (18 rutas) y registra los
handlers de error de `app/core/errors.py`, que traducen `AppError`, `RequestValidationError` y
`StarletteHTTPException` al envoltorio `{"error":{"code","message","details"}}` de PRD §23. El
OpenAPI que FastAPI deriva de esas rutas **no conoce esos handlers**: documenta el 422 con su
`HTTPValidationError` por defecto (`{"detail":[...]}`), forma que el backend no devuelve nunca y
que `frontend/lib/api/errors.ts` degrada a `UNKNOWN_ERROR`.

El documento no se persiste en ningún sitio: se sirve en `/docs` y `/openapi.json`, ambos en la
allowlist anónima de `backend/tests/test_route_authorization.py`.

`backend/app/cli/bootstrap.py` establece el patrón de comando del backend (`python -m
app.cli.bootstrap`, expuesto como `make bootstrap`). `Settings`
(`backend/app/core/config.py`) solo exige **una** variable para importar la aplicación:
`jwt_secret_key` con `min_length=32`; `database_url` y `redis_url` tienen defaults, así que
importar no abre ninguna conexión. `.github/workflows/backend-tests.yml` ya resuelve ese requisito
generando una clave efímera con `openssl rand -hex 32`.

## Decisions

### D1 — El generador es un módulo CLI del backend, no un script del workflow

**Chosen:** `backend/app/cli/openapi.py`, invocable como `python -m app.cli.openapi`, espejo de
`app/cli/bootstrap.py`. Es el mismo código el que usan el target de Makefile y el job de CI, que es
lo que R2.4 exige; y al ser Python importable, se puede testear (D8) en vez de solo ejecutarse.

Rejected: script en `.github/scripts/` — reproduce el problema que `app-version-provenance` ya
tiene anotado (bash de CI sin test de regresión) y no sirve en local. `python -c` embebido en el
Makefile — no testeable y se duplicaría literalmente en el workflow.

### D2 — El artefacto vive en `backend/openapi.json`

**Chosen:** junto al código que lo genera. Es la interfaz publicada del backend y el job que lo
regenera ya corre con `working-directory: backend`; en un monorepo, que `frontend-ci` lea
`../backend/openapi.json` es trivial.

Rejected: `docs/api/openapi.json` — `steering/documentation.md` define `docs/` como documentación
extendida *en prosa, orientada a cómo se usa/opera*; un artefacto de máquina ahí desdibuja esa
regla. Raíz del repositorio — `steering/architecture.md` mantiene la raíz limpia a propósito
(`docker-compose.yml`, `Makefile`, `VERSION` y poco más).

### D3 — Serialización determinista por construcción, no por suerte

**Chosen:** `json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)` más un `\n` final y
saltos LF. `sort_keys=True` es lo que hace la salida independiente del orden de inserción que
produzcan FastAPI y Pydantic, que es la fuente de inestabilidad que convertiría el check de R2 en
un test flaky (R1.2). `indent=2` mantiene una clave por línea para R1.5.

Rejected: conservar el orden natural de registro de rutas — legible de arriba abajo, pero ata el
determinismo a un detalle no documentado del comportamiento de las librerías. Minificar — R1.5 lo
prohíbe explícitamente.

### D4 — `info.version` se fija a la versión del paquete, nunca a la versión de build

**Chosen:** `create_app()` pasa `version=` leyendo la versión declarada en
`backend/pyproject.toml` (hoy `0.1.0`, igual que el `VERSION` de la raíz).

Es una decisión con consecuencia directa sobre R2, no cosmética: si `info.version` llevara la
cadena de build de `app-version-visibility` (`0.1.0+2026-07-31.5872022`), el fichero commiteado
cambiaría **en cada commit** y el check de deriva estaría permanentemente en rojo. Y leer el
`VERSION` de la raíz no es una opción: los contenedores montan solo su propio directorio y no ven
la raíz — restricción ya registrada en la entrada `app-version-provenance` del roadmap.

Hoy `FastAPI(title="AutoHostAI backend")` no pasa `version`, así que hereda el `0.1.0` por defecto
de FastAPI. Coincide con el real por casualidad; sin esta decisión, subir `VERSION` a `0.2.0`
dejaría el contrato afirmando `0.1.0` para siempre.

Rejected: dejar el default de FastAPI — mentira latente. Versión de build — rompe R2 por
construcción.

### D5 — El check vive en su propio workflow, no como paso de `backend-tests.yml`

**Chosen:** `.github/workflows/api-contract.yml`, con los mismos disparadores y las mismas
garantías que `backend-tests` (sin filtro de rutas por el motivo de `specs/backend-ci.md`,
`concurrency` con `cancel-in-progress`, `timeout-minutes`, `permissions: contents: read`, actions
pineadas por SHA).

Dos razones. Una: **no necesita servicios**. `backend-tests` levanta PostgreSQL y Redis con
healthcheck porque su suite los usa; regenerar el contrato no toca ninguno (D6), así que como
workflow propio da señal en decenas de segundos en vez de esperar al ciclo completo. Dos:
**independencia de señal**. Como paso dentro de `backend-tests`, olvidarse de regenerar el fichero
cortaría la ejecución antes de la suite y perderías el resultado de los tests en ese PR; y si el
paso fuera el último, tendrías el problema simétrico.

El coste es duplicar ~8 líneas de setup (`checkout`, `setup-uv`, clave efímera, `uv sync
--frozen`). Se acepta: es menos daño que acoplar dos señales que fallan por motivos distintos.

Rejected: paso dentro de `backend-tests.yml` — reutiliza el setup, pero mezcla las señales y
arrastra dos servicios que este check no necesita.

### D6 — La generación no toca base de datos, Redis ni red

**Chosen:** el módulo importa `create_app()` y serializa `app.openapi()`. Nada más. Se apoya en un
hecho verificado de `app/core/config.py`: la única variable sin default es `jwt_secret_key`, y
`database_url`/`redis_url` no abren conexión al importarse. El workflow genera la clave efímera
con `openssl rand -hex 32`, exactamente como `backend-tests.yml` (regla 8 de
`steering/security.md`); en local el target de Makefile corre dentro del contenedor, donde la
clave ya está en el entorno.

Rejected: arrancar el servidor y hacer `GET /openapi.json` — necesitaría puerto, healthcheck y
esperas, y es la clase de paso que falla de forma intermitente en CI.

### D7 — La forma de error se inyecta post-proceso, no endpoint por endpoint

**Chosen:** un `custom_openapi(app)` en `backend/app/core/openapi.py` asignado a `app.openapi`.
Registra un modelo Pydantic `ErrorEnvelope` (espejo exacto de `error_envelope()` en
`app/core/errors.py`) en `components.schemas` y reescribe la respuesta 422 de **toda** operación
para que la referencie, eliminando el `HTTPValidationError` que FastAPI inyecta y que queda sin
referenciar.

Es el único punto de control que cubre las 18 rutas de hoy y las que vengan sin tocar ningún
router: el 422 lo genera FastAPI automáticamente en cuanto un endpoint tiene body o parámetros
validados, así que declararlo a mano en cada decorador se olvidaría en el endpoint 19.

Rejected: `responses=` en los 18 decoradores — ruido y se olvida. `FastAPI(responses=...)` global
— aplica el mismo conjunto a todas las rutas, incluidas las que no pueden devolver ese estado.

### D8 — Qué estados de error se declaran, y por qué no más

**Chosen:** dos niveles, ninguno inventado.

1. **422 en toda operación que lo tenga**, reescrito por D7. Es mecánico y objetivamente correcto:
   FastAPI ya lo genera, y `app/core/errors.py` demuestra qué forma tiene de verdad.
2. **401 y 403 a nivel de `APIRouter`**, en los routers cuyas rutas cuelgan de la dependencia de
   autorización — cinco sitios como mucho, no dieciocho. Es exacto: el router de `auth` mantiene
   `login`/`refresh` anónimos (ya listados en `ANONYMOUS_ENDPOINTS` de
   `tests/test_route_authorization.py`), así que sus 401 no son universales y se declaran en las
   rutas que sí los tienen.

**Lo que deliberadamente no se hace**: enumerar por endpoint todos los estados que *podría*
devolver (404 cross-tenant, 409 de email duplicado, 429 del throttle). Declarar un catálogo
plausible pero no verificado sustituiría la mentira actual por otra distinta, que es exactamente
el defecto que R3 existe para cerrar. Un endpoint que quiera declarar el suyo lo hace en su
`responses=`, y eso es una decisión suya.

### D9 — La guarda estructural es un test, y espeja el que ya existe

**Chosen:** `backend/tests/test_openapi_contract.py`, construido sobre `create_app()` y
`app.routes` igual que `backend/tests/test_route_authorization.py` (R3.3). Cubre cuatro cosas:

1. Toda ruta bajo `/api/v1` cuyo código de éxito no sea `204` declara `response_model` (R3.2).
   Hoy pasa: las tres sin modelo son `POST /auth/logout`, `DELETE /users/{user_id}` y
   `DELETE /reservations/{reservation_id}`, las tres `204` legítimas.
2. Ninguna operación del documento referencia `HTTPValidationError`, y el 422 apunta a
   `ErrorEnvelope` (R3.1).
3. **Determinismo**: generar dos veces produce bytes idénticos (R1.2).
4. **Fidelidad**: una petición realmente inválida contra un endpoint del `TestClient` devuelve un
   cuerpo que valida contra el `ErrorEnvelope` publicado. Sin esto, D7 podría declarar una forma y
   los handlers devolver otra, que es el defecto de hoy con otro disfraz.
5. **Integridad del registro de D11**: ningún código vive fuera de `ErrorCode`. El test recorre
   las tablas `_MAPPING` de los tres módulos, los atributos `code` de las subclases de `AppError`
   y `_HTTP_STATUS_CODES`, y falla si alguno no es un miembro del registro. Es lo que impide que
   el `enum` publicado vuelva a quedarse corto.

Al vivir en la suite, corre dentro de `backend-tests` — el workflow de D5 solo compara ficheros.

### D10 — La documentación va al README y al steering, sin página nueva

**Chosen:** el README de la raíz gana el target en su sección de comandos —
`steering/documentation.md` lo exige cuando un change añade un target de Makefile — y
`steering/documentation.md` §Audiencias pasa a apuntar al fichero versionado además de al `/docs`
servido (R4.2). El comando recomendado para derivar tipos (`openapi-typescript`) se documenta
junto al target, como referencia para `frontend-ci`.

Rejected: `docs/api-contract.md` — `steering/documentation.md` reserva `docs/<capability>.md` para
capabilities operativas de cara a usuarios; esto es flujo de desarrollo.

### D11 — `ErrorEnvelope.code` publica un `enum` derivado de un registro único de códigos

**Revisada durante `/sdd:run` (2026-08-01).** La primera redacción decía "por reflexión sobre las
subclases de `AppError` unidas a `_HTTP_STATUS_CODES`" y **era falsa**: se escribió conociendo dos
fuentes de códigos cuando hay seis. Las tablas `_MAPPING` de `app/{auth,reservations,tenants}/api/
errors.py` y los literales de `app/integrations/api/errors.py` aportan `CONFLICT` (409, en auth y
en reservations) y `PAYLOAD_TOO_LARGE` (413), que aquella reflexión no habría visto. Publicar un
`enum` sin ellos es peor que no publicarlo: el `switch` exhaustivo del frontend quedaría exhaustivo
sobre un conjunto incompleto, con el compilador avalando el error.

**Chosen:** crear `app/core/error_codes.py` con un `StrEnum` `ErrorCode` que es **la única fuente
de verdad** de los códigos del envoltorio de PRD §23. Pasan a referenciarlo: los atributos `code`
de las subclases de `AppError`, las tablas `_MAPPING` de los tres módulos, los literales de
`integrations` y el diccionario `_HTTP_STATUS_CODES`. El `enum` del OpenAPI se deriva de
`ErrorCode`, y un test estructural falla si aparece un código en literal fuera del registro.

Es lo único que hace verdadera la premisa original: convierte seis fuentes en una, en lugar de
enseñar a la séptima a leer las otras seis. **No cambia comportamiento**: `StrEnum` serializa
idéntico al literal que sustituye, y la suite existente —que ya afirma códigos concretos en los
tests de cada módulo— lo demuestra.

Consecuencia asumida y deseada: añadir un código de error pasa a ser un **cambio de contrato
visible en el diff** del PR, que es exactamente la señal de revisión que §Why del proposal declara
como el valor de este change.

Rejected: **ampliar la reflexión a los `_MAPPING`** — leería un atributo privado de cada módulo y
un dominio nuevo con su propia tabla no le recordaría a nadie que se registre; mueve el fallo
silencioso en vez de cerrarlo. **`code` como string libre** — deja al frontend sin exhaustividad
comprobable (opción descartada en OQ1). **Lista explícita en `app/core/openapi.py`** — segunda
fuente de verdad, el defecto que este registro elimina.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Generador | `backend/app/cli/openapi.py` *(nuevo)* | Importa `create_app()`, serializa según D3, escribe `backend/openapi.json`. Sin BD/Redis/red (D6). |
| Contrato de error | `backend/app/core/openapi.py` *(nuevo)* | `ErrorEnvelope` + `custom_openapi()` (D7). |
| Aplicación | `backend/app/main.py` | Asigna `app.openapi = custom_openapi(app)`; pasa `version=` (D4). |
| Routers | `backend/app/{auth,tenants,reservations,integrations}/api/*.py` | `responses=` de 401/403 a nivel de `APIRouter` donde aplica (D8.2). |
| Artefacto | `backend/openapi.json` *(nuevo, commiteado)* | Salida del generador. |
| CI | `.github/workflows/api-contract.yml` *(nuevo)* | Regenera y compara; falla con el comando de arreglo (D5, R2.2). |
| Tests | `backend/tests/test_openapi_contract.py` *(nuevo)* | Guarda estructural, determinismo y fidelidad (D9). |
| Orquestación | `Makefile` | Target `openapi`. Implementado como `docker compose run --rm --no-deps -T backend python -m app.cli.openapi`, **no** `exec` como decía la primera redacción de esta tabla: `exec` exige el stack levantado, y sin `--no-deps` el `depends_on` arranca postgres, redis y migrate para una generación que no toca ninguno. La forma con `exec` habría hecho falsa la afirmación de D6. |
| Docs | `README.md`, `sdd/steering/documentation.md` | D10. |

## Data & interfaces

- **Sin cambios de esquema, sin migración, sin variables de entorno nuevas.** El generador no
  añade ningún requisito de configuración: reutiliza `jwt_secret_key`, que ya es obligatoria.
- **Nuevo modelo público** `ErrorEnvelope` — `{"error": {"code": str, "message": str, "details":
  object}}`, espejo de `error_envelope()`. Es documentación del contrato existente, no un cambio
  de contrato: ningún endpoint cambia lo que devuelve.
- **Nuevo artefacto versionado** `backend/openapi.json`, consumido por `frontend-ci` cuando le
  toque.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **El contrato declarado y el que devuelven los handlers se desincronizan.** Es el defecto de hoy; D7 lo arregla una vez, pero nada impide que vuelva. | Punto 4 de D9: un test hace una petición inválida real y valida la respuesta contra el `ErrorEnvelope` publicado. Sin ese test, D7 es una promesa. |
| **Salida dependiente del entorno.** Si un modelo Pydantic derivase un default o un ejemplo de `Settings`, el fichero cambiaría con la configuración y el check fallaría según la máquina. | El test de determinismo (D9.3) genera dos veces bajo configuraciones distintas, no solo dos veces seguidas. |
| **Un bump de FastAPI o Pydantic reescribe el documento entero**, produciendo un diff enorme sin cambio de API. | `uv.lock` pinea ambas y `uv sync --frozen` falla si divergen; el diff aparecería en el PR del bump, que es donde debe leerse. |
| **Churn del fichero y conflictos de merge** entre ramas que tocan endpoints distintos. | Consecuencia aceptada: es exactamente la señal de revisión que §Why declara como el valor del change. `sort_keys=True` (D3) mantiene los conflictos locales a la operación tocada. |
| **Un código nuevo se escribe como literal y no llega al registro de D11**, dejando el `enum` publicado incompleto — que es exactamente el defecto que hundió la primera redacción de D11. | El test D9.5: recorre los `_MAPPING`, los atributos `code` de `AppError` y `_HTTP_STATUS_CODES` y falla si alguno contiene un valor que no sea un miembro de `ErrorCode`. Es una guarda estructural, no una lista que mantener. |
| **La guarda del registro no cubre las llamadas sueltas a `error_envelope(...)`.** Recorre los `_MAPPING`, las subclases de `AppError` y `_HTTP_STATUS_CODES` — los tres patrones que existen hoy—, pero un módulo futuro que pase un literal directamente a `error_envelope()` se colaría. La redacción de D11 promete más de lo que el test cubre. *(Detectado por el panel de QA en `/sdd:review`, 2026-08-02; no arreglado aquí porque review es report-only.)* | Hoy no se materializa: los siete sitios están migrados y `integrations/api/errors.py`, que es el único que llama directamente, usa `ErrorCode`. Cerrarlo bien pide una comprobación por AST sobre `backend/app/**` que rechace un primer argumento literal en `error_envelope(...)`. Queda como deuda con dueño para `specs/api-contract.md` al archivar. |
| **Exposición**: el documento enumera nombres de campo de todo el modelo público. | El repositorio es privado y esos nombres ya viajan en cada respuesta HTTP. El generador serializa `app.openapi()` tal cual: no añade `servers`, ni ejemplos, ni valores derivados del entorno. Ningún campo de la regla 3 de `steering/security.md` está hoy en un `response_model`. |

## Open questions

Ninguna abierta. Las dos que planteó este design se resolvieron con el usuario en el gate
(2026-08-01) y están incorporadas arriba:

- **Ruta del artefacto** → `backend/openapi.json`, confirmada (D2).
- **Catálogo de códigos de error** → se publica como `enum`, derivado por reflexión (D11).
