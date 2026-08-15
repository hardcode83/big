# Proposal: backend-response-hardening

## Why

Dos hallazgos que el panel de `/sdd:review` de `cleaning-photos-storage` dejó en su `BLOCKED.md`
(entradas §6(b) y §7) y que se separaron a esta entrada el 2026-08-09 comparten la misma forma:
**una propiedad que se decidió bien en una ruta y que nadie aplicó a las demás**.

1. **`X-Content-Type-Options: nosniff` existe en una sola respuesta de todo el backend.** Es la que
   `cleaning-photos-storage` añadió a su ruta anónima de servido de fotos
   (`app/cleaning/api/photos_router.py`, único `nosniff` de `backend/app`). El
   `backend/openapi.json` versionado declara hoy **65 operaciones sobre 49 rutas**; las otras 64 no
   lo llevan. *(La entrada del roadmap dice «las 12 rutas autenticadas»: ese número describía el
   módulo `cleaning` cuando se escribió, no el backend. El backend ha crecido desde entonces, así
   que el hallazgo es más grande, no menor.)*
2. **El error de razonamiento sobre topes de tamaño ya está reproducido en un segundo módulo.**
   `backend/app/integrations/api/router.py:93-95` justifica su `await file.read(limit + 1)` como
   *«defence in depth for a request whose body arrived in one chunk under a lying
   `Content-Length`»*. No puede serlo: FastAPI llama a `await request.form()` **antes** de resolver
   las dependencias y Starlette vuelca la parte a un `SpooledTemporaryFile` sin techo propio, así
   que un cuerpo que «arrived» ya se recibió entero y se escribió en disco. Esa lectura acota la
   copia en memoria; no caza al que miente. Quien cumple «rechazar antes de leer el cuerpo» es el
   contador acumulativo de `MaxBodySizeMiddleware`, y sólo él — el propio módulo lo explica en su
   docstring. El panel de `cleaning-photos-storage` gastó **dos rondas** en la misma afirmación
   falsa, escrita entonces en cinco ficheros; se arregló allí y **volvió a aparecer sola** en otro
   módulo, escrita por otra gente sin copiarse.

La salida del segundo no es un tercer arreglo de redacción sino una **nota de steering escrita una
vez**: mientras el contrato no tenga un solo hogar, cada módulo lo reinventa y cada revisión
encuentra una copia desincronizada. Y hay una tercera copia ya derivada que lo demuestra: el
contrato de topes vive hoy en `specs/auth-tenancy.md` §«Tope de tamaño de cuerpo», que enumera
**dos** techos (`CSV_IMPORT_MAX_BYTES` y `REQUEST_MAX_BYTES`) cuando `app/main.py` resuelve **cuatro**
desde que llegaron `cleaning` y `cleaning-photos-storage` (`PHOTO_UPLOAD_MAX_BYTES`,
`CSV_IMPORT_MAX_BYTES`, `JSON_BODY_MAX_BYTES`, `REQUEST_MAX_BYTES`).

Nota de método que esta entrada hereda: la regla 13(c) de `steering/security.md` y el precedente del
guard de fixtures de `channex-staging-adapter` — una guardia se demuestra **en rojo** antes de darla
por buena. `backend/tests/test_route_authorization.py` ya tiene esa forma (`test_the_check_catches_an_endpoint_that_forgets`)
y es el patrón a seguir aquí.

## What changes

Después de este cambio, la postura de respuesta del backend deja de ser una propiedad por ruta y
pasa a ser una del sistema: **toda** respuesta HTTP que la aplicación emita —incluidas las de error,
los 404 y el `413` que emite el propio middleware de tamaño— lleva `X-Content-Type-Options: nosniff`
sin que ninguna ruta tenga que acordarse, y un test que **enumera las rutas de la aplicación** (no
una lista escrita a mano) impide que una ruta nueva nazca sin ella. Además, la afirmación sobre qué
capa satisface «rechazar antes de leer el cuerpo» pasa a tener **un solo hogar** en `steering/`, las
dos justificaciones que hoy dicen lo contrario del código quedan corregidas, y el contrato de topes
de tamaño se consolida en un hogar propio y al día en `sdd/specs/`. No cambia ningún número de tope
ni ningún comportamiento de negocio.

## Requirements

### R1 — `nosniff` en toda respuesta del backend

**As a** responsable de seguridad del backend, **I want** que ninguna respuesta permita al navegador
adivinar su `Content-Type`, **so that** un cuerpo controlado por el cliente no pueda interpretarse
como HTML sobre el origen de `/api/v1`, que `api-ingress-routing` dejó alcanzable desde internet.

Acceptance criteria:

1. WHEN la aplicación emite cualquier respuesta HTTP, THE SYSTEM SHALL incluir la cabecera
   `X-Content-Type-Options: nosniff`.
2. WHERE la respuesta es un error del envelope de PRD §23, un `404` de ruta inexistente o un `405`,
   THE SYSTEM SHALL incluirla igualmente — la cabecera no depende de que exista un handler.
3. WHEN `MaxBodySizeMiddleware` rechaza un cuerpo con `413`, THE SYSTEM SHALL incluirla también en
   esa respuesta, que hoy se construye entera dentro de ese middleware y no pasa por ninguna ruta.
4. WHERE una ruta ya fija la cabecera por su cuenta —hoy `GET /api/v1/cleaning-tasks/{id}/photos/{id}`—
   THE SYSTEM SHALL emitir un único valor `nosniff`, sin duplicar ni contradecir el que la ruta puso.
5. THE SYSTEM SHALL seguir sirviendo esa ruta de fotos con el `Content-Type` derivado de la extensión
   almacenada y su `Cache-Control`, sin regresión de los tests que ya la pinan
   (`tests/cleaning/test_serve_photo_api.py`).

### R2 — La postura se verifica por enumeración, no ruta a ruta

**As a** quien añada la ruta número 66, **I want** que la cabecera llegue sin que yo la escriba y que
el test falle si no llega, **so that** la propiedad no vuelva a decidirse bien en una ruta y a
olvidarse en las demás — que es exactamente el hallazgo que abre este change.

Acceptance criteria:

1. THE SYSTEM SHALL verificar la cabecera recorriendo las rutas que la aplicación tiene montadas,
   **no** una lista de rutas escrita a mano en el test.
2. IF una ruta nueva se monta sin tocar el middleware, THEN THE SYSTEM SHALL cubrirla sin ningún
   cambio en el test ni en una allowlist.
3. THE SYSTEM SHALL incluir un test que demuestre la comprobación **en rojo**: una respuesta
   fabricada sin la cabecera hace fallar la verificación (regla 13(c) de `steering/security.md`;
   patrón de `tests/test_route_authorization.py::test_the_check_catches_an_endpoint_that_forgets`).
4. IF alguna superficie queda fuera de lo que la enumeración puede inspeccionar, THEN THE SYSTEM
   SHALL fallar nombrándola, nunca degradar a verde.

### R3 — El contrato de «rechazar antes de leer» tiene un solo hogar

**As a** quien escriba el próximo endpoint con cuerpo grande, **I want** encontrar la afirmación
correcta enunciada una sola vez, **so that** no la reinvente por módulo — que es cómo se reprodujo
sola entre `cleaning-photos-storage` e `integrations`.

Acceptance criteria:

1. THE SYSTEM SHALL registrar en `sdd/steering/` que una comprobación de tamaño posterior a
   `request.form()` o a `file.read()` **acota memoria y no satisface un requisito de «rechazar antes
   de leer»**, y que eso sólo lo puede hacer el middleware.
2. THE SYSTEM SHALL enunciarla en **un único documento de steering**; cualquier otro sitio que la
   necesite enlaza a él en vez de reformularla (mismo contrato que la regla 11 y que la excepción de
   granularidad de la regla 9 ya aplican).
3. THE SYSTEM SHALL declarar en qué fases se aplica, de forma que los paneles de `/sdd:review` la
   tengan cargada cuando revisen un módulo con cuerpo de petición.

### R4 — Las dos justificaciones que contradicen al código quedan corregidas

**As a** revisor, **I want** que el comentario que justifica una lectura acotada describa lo que esa
lectura hace de verdad, **so that** leer el código no vuelva a costar dos rondas de panel.

Acceptance criteria:

1. THE SYSTEM SHALL corregir la justificación de `app/integrations/api/router.py:93-95`, que hoy
   presenta `file.read(limit + 1)` como defensa frente a un `Content-Length` mentido, para que diga
   que acota **la copia en memoria** y que quien rechaza antes de leer es el middleware.
2. THE SYSTEM SHALL conservar esa lectura acotada: bajar el techo de la copia en memoria es un
   efecto real, y quitarla ampliaría la superficie sin que ningún requisito lo pida.
3. THE SYSTEM SHALL comprobar, sobre todo el árbol, que no queda ninguna otra redacción de la misma
   clase —una comprobación de tamaño posterior a la lectura presentada como si rechazara antes—, y
   corregir la que aparezca.

### R5 — El contrato de topes de tamaño se consolida y se pone al día

**As a** quien busque cuál es el techo de una ruta, **I want** encontrarlo en un sitio que lo diga
entero y bien, **so that** no lea en `auth-tenancy` una versión con la mitad de los techos.

Acceptance criteria:

1. THE SYSTEM SHALL declarar los topes de tamaño de cuerpo en **un solo** documento de `sdd/specs/`,
   enumerando los **cuatro** techos que `app/main.py` resuelve hoy y la razón de cada número.
2. WHERE `specs/auth-tenancy.md` u otra spec necesiten el contrato, THE SYSTEM SHALL dejar una
   referencia al hogar único en vez de una segunda enunciación.
3. THE SYSTEM SHALL recoger en ese mismo documento el riesgo ya aceptado y nombrado en `app/main.py`
   —hasta `PHOTO_UPLOAD_MAX_BYTES` de cuerpo anónimo antes de autenticar en la rama de fotos, y el
   mismo trato en `/integrations/`— sin reabrirlo ni volver a razonarlo.

## Out of scope

- **Cualquier otra cabecera de seguridad** (`Content-Security-Policy`, `X-Frame-Options`,
  `Referrer-Policy`, `Strict-Transport-Security`). Las tres primeras protegen orígenes que sirven
  HTML y este backend sirve JSON e imágenes; HSTS es del ingress (Cloudflare Tunnel,
  `specs/ingress-https-dev.md`), no de la aplicación. Si alguna se justifica, será con su medición y
  su entrada propia, no de rebote aquí.
- **Cambiar cualquier tope de tamaño.** Los cuatro números están medidos contra un caso concreto
  (338 KB de plantilla con acentos, 400 MB de `POST /auth/login`, 10 MiB de foto y de CSV) y
  retocarlos es una decisión con su propia evidencia. Este change los documenta; no los mueve.
- **Cabeceras del frontend.** Next.js sirve otro origen y tiene sus propias capacidades (`frontend-*`).
- **`rule11-ownership-single-source`.** Esa entrada audita la propiedad de los nueve sumideros de la
  regla 11 en seis artefactos. Aquí se escribe **una** nota nueva con un solo hogar; no se audita la
  regla 11 ni se toca su contrato. Comparten diagnóstico, no alcance.
- **Rate limiting y throttling.** Otra clase de tope, con su propio hogar en `auth-tenancy`.
- **Reescribir `MaxBodySizeMiddleware`.** Su lógica de conteo y su `413` son correctos y están
  medidos; lo que falta es la cabecera en esa respuesta (R1.3) y el hogar del contrato (R5).

## Affected specs

- `sdd/specs/backend-http-posture.md` — *(no existe aún — se creará al archivar)*. Hogar único de la
  postura HTTP de todo el backend: cabeceras de respuesta (R1/R2) y los cuatro topes de cuerpo (R5).
- `sdd/specs/auth-tenancy.md` — su sección «Tope de tamaño de cuerpo» (líneas 360-374) deja de
  enunciar el contrato y pasa a referenciar el hogar único; hoy nombra dos techos de cuatro.
- `sdd/specs/cleaning.md` — su afirmación sobre `nosniff` en la ruta de fotos (línea 189) y su
  mención de `MaxBodySizeMiddleware` (línea 289) pasan a citar la postura global, conservando lo que
  es propio de esa ruta (`Content-Type` por extensión, `Cache-Control`).
- `sdd/steering/security.md` **o** `sdd/steering/backend.md` — hogar único de la nota de R3. Cuál de
  los dos es la primera decisión de `/sdd:design`: `security.md` carga en `design` y `run` y es donde
  vive la regla 6 de uploads; `backend.md` se aplica por path a `backend/**` y es donde vive el
  «Don'ts» que un autor de endpoint lee.
