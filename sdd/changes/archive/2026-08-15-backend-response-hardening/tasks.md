# Tasks: backend-response-hardening

> Nota de alcance heredada del design: **`/sdd:run` no toca `sdd/specs/`**. La spec nueva
> `sdd/specs/backend-http-posture.md` y las reducciones de `auth-tenancy.md` y `cleaning.md`
> las escribe `/sdd:archive` (D10). Lo que sí hace este change es dejar el material listo
> (tarea 4.6) para que el archivado no lo re-derive.

## 1. El middleware y su montaje <!-- panel: PASS 2026-08-15 -->

- [x] 1.1 Crear `backend/app/core/response_headers.py` con `NoSniffMiddleware`: ASGI puro
      (`__call__(scope, receive, send)`), deja pasar `scope["type"] != "http"` sin tocar,
      decora **solo** `send` y escribe `MutableHeaders(scope=message)["X-Content-Type-Options"] = "nosniff"`
      sobre `http.response.start`. `receive` se pasa tal cual — envolverlo rompería el contador de
      `MaxBodySizeMiddleware` (D1). Usar `__setitem__`, nunca `append` ni `setdefault` (D4).
      El docstring del módulo dice dos cosas y las dos importan: (a) el residuo nombrado de D3 —
      el `500` de `ServerErrorMiddleware` sale por fuera de todo middleware de usuario y **no**
      queda cubierto, aceptado porque su cuerpo es una constante sin un byte del cliente; (b) por
      qué la posición de montaje es el mecanismo (D2). [R1]

- [x] 1.2 Montar el middleware en `create_app()` (`backend/app/main.py`, tras el bloque
      `add_middleware(MaxBodySizeMiddleware, ...)` de las líneas 209-222): `app.add_middleware(NoSniffMiddleware)`
      **después**, porque `Starlette.add_middleware` inserta en posición 0 y `build_middleware_stack`
      envuelve al revés, así que el último añadido queda el más externo — que es lo único que ve el
      `413` que `MaxBodySizeMiddleware._refuse` fabrica por su cuenta. Comentario al lado explicando
      eso, sin documentar el orden como contrato: su contrato es el test 2.4 (D2). [R1]

- [x] 1.3 Crear `backend/tests/test_response_headers.py` con el caso base: una respuesta normal de
      ruta (p. ej. `GET /health`) trae `x-content-type-options: nosniff`. [R1.1]

- [x] 1.4 Tests de las respuestas que **no** salen de un handler de ruta, en el mismo fichero: un
      `404` de ruta inexistente, un `405` de método equivocado sobre una ruta existente y un error
      del envelope de PRD §23 (`RequestValidationError` → `422`, y un `AppError` → su código) traen
      la cabecera. Los tres salen de `errors.py`/`ExceptionMiddleware`, por dentro del sello. [R1.2]

- [x] 1.5 Test del `413`: conducir contra la app real un cuerpo por encima del techo de su rama en
      `/api/v1/` y comprobar que la respuesta que `MaxBodySizeMiddleware._refuse`
      (`backend/app/core/http_limits.py:173-187`) construye entera por su cuenta trae la cabecera.
      Es el test que sostiene D2: si alguien reordena los dos `add_middleware`, este es el que cae. [R1.3]

- [x] 1.6 Test de no-duplicación sobre `GET /api/v1/cleaning-tasks/{id}/photos/{id}`, que ya sella
      por su cuenta en `photos_router._respond`: contar apariciones con `response.headers.get_list("x-content-type-options")`
      y exigir **exactamente una** con valor `nosniff`. Leer `headers["..."]` a secas colapsaría dos
      valores en uno y el test pasaría vacuamente. [R1.4]

- [x] 1.7 Confirmar que `backend/tests/cleaning/test_serve_photo_api.py` sigue en verde **sin
      tocarlo**: conduce peticiones contra la app completa, así que sus aserciones sobre `nosniff`,
      `Content-Type` derivado de la extensión y `Cache-Control` valen igual con el sello local y el
      global. Si hiciera falta editarlo, es señal de que D4/D5 se implementaron mal. [R1.5]

## 2. La guardia por enumeración <!-- panel: PASS 2026-08-15 -->

- [x] 2.1 En `backend/tests/test_response_headers.py`, helper `_responses_without_nosniff(app)` que:
      (a) llama a `flatten_routes(app)` de `backend/tests/route_walk.py` — la pieza compartida, no
      una caminata re-derivada; (b) de la lista `found` toma cada `(path, method)`, sustituye **todo**
      segmento `{...}` por un UUID literal fijo y conduce la petición **sin credenciales y sin
      cuerpo**; (c) de la lista `other` conduce igual las que son `Route` de Starlette con `methods`
      (hoy `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) y marca como `UNINSPECTABLE`
      todo lo demás (un `APIWebSocketRoute`, un `Mount`); (d) devuelve las que no traen la cabecera,
      más lo no inspeccionable, nombrado. **Sin allowlist de ninguna clase**: el estatus da igual —
      un `401`, un `422`, un `200` o un `502` valen lo mismo para esta comprobación (D7). [R2.1, R2.2]

- [x] 2.2 Test verde sobre la app real (`create_app()`): `_responses_without_nosniff` devuelve lista
      vacía. Con **aserción anti-vacuidad** en el mismo test: el conjunto enumerado contiene las
      rutas de `auth` (mismo patrón que `test_the_flattener_finds_the_auth_endpoints`), porque una
      enumeración que inspecciona cero rutas pasa verde y es la trampa que `route_walk.py` documenta
      haber pisado dos veces. [R2.1, R2.2]

- [x] 2.3 Test en rojo: `test_the_check_catches_an_app_that_forgets_the_middleware` — una `FastAPI()`
      fabricada **sin** el middleware, con una ruta trivial, hace que el helper devuelva esa ruta.
      Mismo patrón que `tests/test_route_authorization.py::test_the_check_catches_an_endpoint_that_forgets`
      (regla 13(c) de `steering/security.md`). [R2.3]

- [x] 2.4 Segundo test en rojo, el que cierra D2: la misma app con los dos `add_middleware` en el
      **orden inverso** deja el `413` sin cabecera. Sin él, «se monta el último» es una frase en un
      comentario y no una propiedad comprobada. [R2.3, R1.3]

- [x] 2.5 Test en rojo de superficie no inspeccionable: una app con un `Mount` (o un
      `@app.websocket`) hace que el helper la devuelva nombrada y el test falle, en vez de ignorarla
      y quedar verde. Espejo de `test_the_check_catches_surface_it_cannot_inspect`. [R2.4]

## 3. El hogar único del contrato de tamaño

- [x] 3.1 Añadir la **regla 14** a `sdd/steering/security.md` (que ya declara `phases: [design, run]`,
      que es literalmente lo que R3.3 pide): un requisito de «rechazar antes de leer el cuerpo» solo
      lo satisface el contador acumulativo de `MaxBodySizeMiddleware`; una comprobación posterior a
      `request.form()`, a `file.read()` o a cualquier consumo del `UploadFile` **acota la copia en
      memoria y nada más**, porque FastAPI llama a `await request.form()` antes de resolver las
      dependencias y Starlette vuelca la parte a un `SpooledTemporaryFile` sin techo propio.
      Conservarla es correcto por dos motivos reales (acota la copia en memoria; es el único techo
      para un llamante sin middleware delante). Presentarla como defensa frente a un `Content-Length`
      mentido es falso. Cierra con la cláusula de hogar único: **este es el único sitio donde vive
      la afirmación; quien la necesite, enlaza aquí.** Redacción de referencia en D6. [R3.1, R3.2, R3.3]

- [x] 3.2 Añadir **una línea** a la sección *Don'ts* de `sdd/steering/backend.md` que enlaza a la
      regla 14 sin reformularla — reformular es exactamente lo que R3.2 prohíbe. [R3.2]

## 4. Las redacciones que contradicen al código

- [x] 4.1 Corregir la justificación de `backend/app/integrations/api/router.py:93-95`, que hoy
      presenta `await file.read(limit + 1)` como *«defence in depth for a request whose body arrived
      in one chunk under a lying Content-Length»*: pasa a decir que acota **la copia en memoria** y
      que quien rechaza antes de leer es el middleware, enlazando a la regla 14 en vez de volver a
      razonarlo. **La lectura acotada se conserva** — bajar el techo de la copia en memoria es un
      efecto real y quitarla ampliaría superficie sin que ningún requisito lo pida. Redacción modelo
      ya escrita en `app/cleaning/application/use_cases.py:1433-1466` y `app/core/config.py:149-161`. [R4.1, R4.2]

- [x] 4.2 Corregir la descripción del `413` en `_PHOTO_UPLOAD_RESPONSES`
      (`backend/app/cleaning/api/tasks_router.py:399-405`), cuyo *«and again by the use case while it
      consumes the stream»* es la misma afirmación falsa en su forma más dañina porque está
      **publicada** en `backend/openapi.json` (línea 6891) y llega al frontend. Misma redacción y
      mismo enlace a la regla 14. [R4.3]

- [x] 4.3 Reescribir el bloque 2 del docstring de módulo de `backend/app/cleaning/api/photos_router.py`
      (líneas 20-31), que hoy afirma que las otras rutas no llevan la cabecera y que cerrar el hueco
      «significa un middleware de respuesta»: ese middleware ya existe, así que pasa a nombrarlo y
      enlazarlo. **El sello de `_respond` no se toca** (D5): es la salida única de una ruta anónima,
      alcanzable desde internet, que devuelve bytes controlados por quien subió la foto, y quitarlo
      haría depender el XSS almacenado que `app/integrations/domain/storage.py:171-174` describe del
      orden de dos `add_middleware`. [R1.4, R4.3]

- [x] 4.4 Barrido de confirmación sobre todo el árbol (`backend/`, `sdd/`, `docs/`) buscando
      cualquier otra redacción de la clase — una comprobación de tamaño posterior a la lectura
      presentada como si rechazara antes — y corregir la que aparezca. El barrido de D9 dio
      exactamente los dos sitios de 4.1 y 4.2; esta tarea es re-correrlo tras los cambios y dejar
      constancia. Ya descartados por **no** ser de la clase, para que no se rehagan:
      `app/guests/api/portal_schemas.py:80`, `app/integrations/application/webhooks.py:169`,
      `specs/reservations.md:238`, `specs/cleaning.md:25`, `specs/ingress-https-dev.md:78`,
      `specs/pms-beds24-spike.md:92`, `docs/cleaning.md:120`. [R4.3]

- [x] 4.5 Regenerar **las dos mitades del contrato** (`steering/documentation.md`), que 4.2 obliga:
      `make openapi` para `backend/openapi.json`, y para `frontend/lib/api/generated/openapi.d.ts`
      la salida verificada de `sdd/project.md` § *Worktree bootstrap*, porque el comando documentado
      (`cd frontend && npm run api:generate`) **no funciona desde un worktree enlazado**:
      ```bash
      docker compose cp backend/openapi.json frontend:/backend/openapi.json
      docker compose exec -T frontend ln -sfn /app /frontend   # una vez por contenedor
      docker compose exec -T frontend npm run api:generate
      ```
      Los dos ficheros se commitean en el mismo PR. El único cambio esperado es texto de descripción:
      **ninguna forma de respuesta cambia**, y la cabecera no se declara en OpenAPI (D — *Data &
      interfaces*: declararla en las 65 operaciones sería la lista escrita a mano que R2.1 prohíbe,
      en otro fichero). [R4.3]

- [x] 4.6 Dejar en `sdd/changes/backend-response-hardening/design.md` §D10 el material que
      `/sdd:archive` necesita para escribir `sdd/specs/backend-http-posture.md` sin re-derivarlo:
      los **cuatro** techos que `app/main.py:209-222` resuelve hoy (`PHOTO_UPLOAD_MAX_BYTES`,
      `CSV_IMPORT_MAX_BYTES`, `JSON_BODY_MAX_BYTES`, `REQUEST_MAX_BYTES`) con su valor, dónde se
      define cada uno (`Settings` vs. constante) y la medición que justifica su número (338 KB de
      plantilla con acentos, 400 MB del `POST /auth/login` que motivó el middleware, 10 MiB de foto y
      de CSV), más el riesgo aceptado que `app/main.py:190-208` ya nombra (cuerpo anónimo pre-auth en
      la rama de fotos y el mismo trato en `/integrations/`). **No se toca `sdd/specs/`** ni se mueve
      ningún número (*Out of scope*). [R5.1, R5.2, R5.3]

## 5. Verification

- [x] 5.1 Suite completa del backend en verde desde este worktree:
      `docker compose exec backend uv run pytest` (con el stack parado:
      `docker compose run --rm backend uv run pytest`). Vigilar en particular la red que cubre el
      riesgo de romper el contador de tamaño: `tests/test_http_limits.py`,
      `tests/test_request_body_ceiling.py`, `tests/cleaning/test_photo_body_limit.py`,
      `tests/integrations/test_webhook_body_ceiling.py`, `tests/guests/test_portal_body_ceiling.py`,
      `tests/cleaning/test_serve_photo_api.py` y `tests/test_route_authorization.py`. [R1, R2]

- [x] 5.2 Comprobar que los dos tests en rojo **fallan de verdad** cuando deben: quitar
      temporalmente el `add_middleware` de 1.2 y ver caer 2.2/2.3; invertir el orden de los dos
      `add_middleware` y ver caer 1.5/2.4. Restaurar. Es la regla 13(c) de `steering/security.md`
      aplicada a la guardia de este change: una guardia se demuestra en rojo antes de darla por
      buena. [R2.3]

- [x] 5.3 Coste de la suite: medir el delta que introducen las ~69 peticiones de la enumeración
      (`pytest --durations=10` sobre `tests/test_response_headers.py`). Si molesta, la conclusión es
      reducir el fixture, **nunca** la enumeración (D7). [R2.1]

- [x] 5.4 Paridad del contrato: `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`
      regenerados y commiteados juntos, y el diff limitado a texto de descripción del `413`. Los
      workflows `api-contract` y `frontend-api-contract` son los que lo exigen en CI; el
      `npm run api:check` literal no corre desde un worktree enlazado, así que la comprobación local
      es el diff del propio fichero tras 4.5. [R4.3]

- [x] 5.5 Repaso final de cobertura de requisitos: `nosniff` en respuesta normal, `404`, `405`,
      envelope §23 y `413` (R1.1-R1.3); un solo valor en la ruta de fotos (R1.4) sin regresión en
      `test_serve_photo_api.py` (R1.5); enumeración sin allowlist con sus tres tests en rojo
      (R2.1-R2.4); regla 14 con su puntero (R3.1-R3.3); las dos redacciones corregidas conservando
      la lectura acotada y el barrido re-corrido (R4.1-R4.3); material de R5 completo en D10 para el
      archivado (R5.1-R5.3). [R1, R2, R3, R4, R5]
