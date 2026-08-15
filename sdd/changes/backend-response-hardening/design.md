# Design: backend-response-hardening

## Context

El backend monta **un solo middleware de usuario**, `MaxBodySizeMiddleware`
(`backend/app/core/http_limits.py`), añadido al final de `create_app()` en
`backend/app/main.py:209-222` con el techo resuelto por ruta. Es ASGI puro a propósito —
`BaseHTTPMiddleware` construye un `Request` y consume el cuerpo, que es justo lo que ese
módulo existe para evitar— y **construye su propio `413` dentro de `_refuse`**
(`http_limits.py:173-187`), sin pasar por ningún handler ni por ninguna ruta.

Los errores del envelope de PRD §23 los emiten tres handlers registrados sobre la app
(`backend/app/core/errors.py:75-104`: `AppError`, `RequestValidationError`,
`StarletteHTTPException`), más los de cada dominio. El `404` de ruta inexistente y el `405`
salen del mismo `StarletteHTTPException`, así que también son `JSONResponse`.

`X-Content-Type-Options: nosniff` existe en **un** sitio: `_respond` en
`backend/app/cleaning/api/photos_router.py:226-238`, la salida única de ese módulo. Su propio
docstring (líneas 26-31) ya escribió el diagnóstico que abre este change: *«Closing that gap
means a response header middleware, which is a posture decision for the whole backend — the
twelve authenticated routes have no `nosniff` either»*.

El patrón de guardia estructural por enumeración ya existe y funciona:
`backend/tests/test_route_authorization.py` sobre `backend/tests/route_walk.py`, con su test
en rojo (`test_the_check_catches_an_endpoint_that_forgets`) y su trampa de superficie no
inspeccionable (`test_the_check_catches_surface_it_cannot_inspect`). Este change lo reusa,
literalmente, con la misma forma.

## Decisions

### D1 — La cabecera la pone un middleware ASGI puro, no las rutas ni los handlers

**Chosen:** un módulo nuevo `backend/app/core/response_headers.py` con
`NoSniffMiddleware`, ASGI puro, que intercepta el mensaje `http.response.start` y escribe
la cabecera sobre su lista de headers. Es la única capa que ve **todas** las respuestas —
las de handler, las de ruta y las que otro middleware fabrica— y no toca el cuerpo ni el
`receive`, así que no puede interferir con el contador de `MaxBodySizeMiddleware`.

Boceto de la interfaz, que es todo lo que hay:

```python
class NoSniffMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def stamped(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Content-Type-Options"] = "nosniff"
            await send(message)

        await self._app(scope, receive, stamped)
```

Rejected: `BaseHTTPMiddleware` — construye un `Request` y consume el cuerpo; `http_limits.py`
ya documenta por qué eso es inaceptable en esta pila.
Rejected: `@app.middleware("http")` — es azúcar sobre `BaseHTTPMiddleware`, mismo problema.
Rejected: repetir el sello en cada handler de `errors.py` y en `_refuse` — es exactamente la
propiedad-por-ruta que este change existe para borrar, y dejaría fuera el `404`/`405`.
Rejected: `Response(headers=...)` por defecto en un helper compartido — no cubre lo que la
aplicación no construye (el `413` del middleware, el `405` de Starlette).

### D2 — Se monta **el último**, porque el último es el más externo, y eso es lo que atrapa el `413`

**Chosen:** la llamada `app.add_middleware(NoSniffMiddleware)` va **después** de la de
`MaxBodySizeMiddleware` en `create_app()`. `Starlette.add_middleware` inserta en la posición
0 de `user_middleware` y `build_middleware_stack` envuelve recorriendo la lista al revés, así
que **el último añadido queda por fuera**. Sólo por fuera ve el `http.response.start` que
`MaxBodySizeMiddleware._refuse` fabrica por su cuenta, que es R1.3.

La pila resultante, de fuera a dentro:

```
ServerErrorMiddleware      (Starlette, fuera del alcance de cualquier middleware de usuario → D3)
  NoSniffMiddleware        ← sella aquí: todo lo de dentro pasa por él
    MaxBodySizeMiddleware  ← fabrica su propio 413
      ExceptionMiddleware  ← 404, 405 y los handlers de errors.py
        Router             ← las 65 operaciones, incluida la de fotos
```

El orden **no se documenta y se confía**: R1.3 es su test. Un `413` que llegue sin la
cabecera significa que alguien reordenó los dos `add_middleware`, y eso es precisamente lo
que hay que hacer fallar.

Rejected: envolver la app exportada (`app = NoSniffMiddleware(create_app())`) para quedar por
fuera incluso de `ServerErrorMiddleware` — `app` dejaría de ser una `FastAPI` para todo lo que
la importa, y **los tests construyen con `create_app()`**, así que la guardia quedaría ciega
justo donde se comprueba: verde en test, sin cobertura real de la reordenación.
Rejected: montarlo el primero (más interno) — no vería el `413`, que es el caso que R1.3 nombra.

### D3 — El `500` de `ServerErrorMiddleware` es un residuo nombrado, no una omisión

**Chosen:** documentarlo explícitamente en el docstring del módulo, en la spec y en el test,
y **no** cubrirlo. Starlette monta `ServerErrorMiddleware` por fuera de todo middleware de
usuario, así que una excepción no capturada sale con su `PlainTextResponse("Internal Server
Error", 500)` sin pasar por `NoSniffMiddleware`. Se acepta con el mismo criterio que
`photos_router` usó para nombrar su hueco del `422`: **el cuerpo es una constante de
compilación sin un solo byte controlado por el cliente**, así que no hay nada que esnifar.

Rejected: registrar un handler global de `Exception` para que `ServerErrorMiddleware` invoque
código nuestro y selle ahí — cerraría el hueco, pero **cambia el cuerpo del `500`** de
`text/plain` al envelope §23, lo que es un cambio de comportamiento que ningún requisito pide
(y que la sección *Out of scope* de la proposal excluye por analogía), además de alterar el
`raise_server_exceptions` de los tests. Si se quiere, es su propia entrada con su medición.
Rejected: callarlo — R2.4 prohíbe explícitamente degradar a verde una superficie no cubierta.

### D4 — La cabecera se **escribe**, no se añade: exactamente un valor y ninguna ruta puede debilitarla

**Chosen:** `MutableHeaders.__setitem__`, que borra todas las apariciones previas y añade una.
Con eso `GET /api/v1/cleaning-photos/{photo_id}` —que hoy la pone en `_respond`— emite un
único `nosniff` (R1.4), y una ruta futura no puede emitir un valor distinto que sobreviva.

Rejected: `setdefault` — respeta lo que puso la ruta, incluido un valor equivocado. No existe
ninguna razón legítima para querer sniffing en una respuesta de este backend, así que la
postura global gana siempre.
Rejected: `headers.append(...)` — dos cabeceras idénticas; R1.4 lo prohíbe literalmente.

### D5 — `photos_router._respond` **conserva** su sello, y el docstring del módulo se reescribe

**Chosen:** no se toca la línea `response.headers["X-Content-Type-Options"] = _NOSNIFF`. Lo
que sí cambia es el bloque 2 del docstring del módulo (líneas 20-31), que hoy afirma que las
otras rutas no llevan la cabecera y que cerrar el hueco «significa un middleware de
respuesta»: pasa a decir que ese middleware **ya existe** y a enlazarlo. R1.5 se cumple sola —
`tests/cleaning/test_serve_photo_api.py` conduce peticiones contra la app completa, así que
sus aserciones sobre `nosniff`, `Content-Type` y `Cache-Control` siguen verdes con o sin el
sello local.

La redundancia es deliberada y acotada: `_respond` es la salida única de una ruta **anónima,
alcanzable desde internet, que devuelve bytes controlados por quien subió la foto** — la única
del backend donde el `nosniff` no es higiene sino la mitad de una defensa contra XSS
almacenado que `content_type_for_extension` documenta en su otra mitad
(`app/integrations/domain/storage.py:171-174`). Es también el único sitio donde el sello local
tiene un test que lo mira desde dentro.

Rejected: borrarlo y dejar que sólo el middleware lo ponga — es la lectura más pura de «un solo
hogar», y se descarta porque el hogar único que este change crea es el de la **postura del
sistema**, no el de esa ruta: quitar la línea convierte el ataque que `storage.py` describe en
dependiente del orden de dos `add_middleware`, sin ganar nada más que una línea menos.
*(Ver OQ2: es discutible y es barato cambiarlo.)*

### D6 — El hogar de la nota de R3 es `steering/security.md`, con un puntero desde `backend.md`

**Chosen:** una **regla 14** nueva en `sdd/steering/security.md`, y **una línea** en la sección
*Don'ts* de `sdd/steering/backend.md` que enlaza a ella sin reformularla (R3.2).

Tres razones, y la primera es la que decide:

1. **R3.3 lo exige por frontmatter.** `security.md` declara `phases: [design, run]`, que es
   literalmente «los paneles de `/sdd:review` la tienen cargada»; el agente `sdd:sdd-security`
   lee ese documento. `backend.md` no declara `phases` en absoluto: se carga por
   `applies_to: ["backend/**"]`, que es una condición sobre el *scope del change*, no sobre la
   fase, y que no se cumple para un change de ingress o de infra que razone sobre topes.
2. **Es una afirmación de seguridad, y su modo de fallo es una falsa sensación de protección.**
   Es una aclaración de las reglas 6 (uploads, «tamaño máx. configurable») y 12(c) («límite de
   tasa y tope de tamaño de cuerpo»), que ya viven ahí. Enunciarla lejos de ellas es reproducir
   el problema que la motiva.
3. **`security.md` ya tiene la forma.** Sus reglas 9, 11 y 13 usan el patrón *«éste es el único
   sitio donde vive el contrato, el resto lo cita»*, con excepciones nombradas y acotadas. La
   nota entra como una más y no inventa un género nuevo.

Contenido de la regla 14, en una frase normativa y su porqué:

> **Un requisito de «rechazar antes de leer el cuerpo» sólo lo satisface el contador
> acumulativo de `MaxBodySizeMiddleware`.** Una comprobación de tamaño posterior a
> `request.form()`, a `file.read()` o a cualquier consumo del `UploadFile` **acota la copia en
> memoria y nada más**: FastAPI llama a `await request.form()` antes de resolver las
> dependencias y Starlette vuelca la parte a un `SpooledTemporaryFile` sin techo propio, así
> que cuando esa comprobación mira ya está todo recibido y escrito en disco — y ya ha corrido
> antes de `require(...)`. Conservarla es correcto y tiene dos motivos reales (acota la copia
> en memoria; es el único techo para un llamante sin middleware delante: un test, un worker,
> un consumidor no-HTTP). Presentarla como defensa frente a un `Content-Length` mentido, o
> como segunda aplicación de la misma garantía, es falso. **Éste es el único sitio donde vive
> esta afirmación; quien la necesite, enlaza aquí.**

Rejected: `steering/backend.md` — es un documento de convenciones sin reglas de seguridad, sin
`phases`, y cuyo *Don'ts* son de arquitectura («no saltarse `PropertyStateMachine`»); además su
carga condicionada al path la haría invisible en el único momento en que importa (el diseño de
un módulo que aún no tiene código bajo `backend/**`).
Rejected: los dos, con la afirmación repartida — es exactamente lo que R3.2 prohíbe.
Rejected: un `steering/` nuevo dedicado a HTTP — un documento para una regla, y la regla es de
seguridad; multiplicar hogares es el problema, no la solución.

### D7 — La verificación por enumeración conduce una petición real por ruta y falla nombrando lo que no puede

**Chosen:** `backend/tests/test_response_headers.py`, con un helper
`_responses_without_nosniff(app, client)` que:

1. llama a `flatten_routes(app)` (`tests/route_walk.py`) — la misma pieza compartida que ya usan
   la guardia de autorización y la del contrato;
2. de la lista `found` (las `APIRoute`) toma cada `(path, method)`, sustituye **todo** segmento
   `{...}` por un UUID literal fijo, y conduce la petición **sin credenciales y sin cuerpo**;
3. de la lista `other` conduce igual las que son `Route` HTTP con `methods` — hoy
   `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`— y **devuelve como
   `UNINSPECTABLE` todo lo demás** (un `APIWebSocketRoute`, un `Mount`), sobre lo que el test
   falla nombrándolo (R2.4);
4. devuelve la lista de las que no traen `x-content-type-options: nosniff`.

**Sin allowlist de ninguna clase** (R2.2): el estatus da igual —un `401`, un `422`, un `200` o
un `502` valen lo mismo para esta comprobación—, así que no hay nada que exceptuar. Es la
diferencia con `test_route_authorization.py`, que necesita su `ANONYMOUS_ENDPOINTS` porque allí
la propiedad **sí** depende de la ruta. Una ruta nueva entra sola (R2.1/R2.2).

Rejected: comprobar estructuralmente que el middleware está montado (`app.user_middleware`) en
vez de conducir peticiones — pasa verde con el middleware montado en el orden equivocado, que es
el único fallo realista. Es la trampa de vacuidad que `test_where_the_exempt_list_is_actually_
enforced` documenta para el caso simétrico.
Rejected: una lista de rutas escrita a mano — R2.1 lo prohíbe literalmente.
Rejected: fabricar respuestas en vez de conducirlas — no probaría el montaje, que es lo único
que puede romperse.

**Honestidad sobre lo que esta guardia prueba y lo que no**, para que no se sobrevenda: con la
cabecera puesta por un middleware global, una ruta **no puede** perderla; lo que la enumeración
pin es que ninguna superficie escapa a la pila y que el conjunto real de rutas está cubierto.
El fallo que de verdad acecha es la reordenación de D2, y lo caza el test del `413` de R1.3.

### D8 — El test en rojo compara la app real contra una app deliberadamente rota

**Chosen:** el mismo patrón que `test_the_check_catches_an_endpoint_that_forgets`. Como la
cabecera es global, no se puede fabricar una *ruta* que la pierda; lo que se fabrica es una
**app sin el middleware**:

```python
def test_the_check_catches_an_app_that_forgets_the_middleware() -> None:
    naked = FastAPI()
    @naked.get("/forgot-the-header")
    async def forgotten() -> dict[str, bool]: return {"ok": True}
    assert _responses_without_nosniff(naked) == ["GET /forgot-the-header"]
```

Y un segundo, más fino, que es el que cierra D2: **la misma app con los dos `add_middleware`
en el orden inverso** debe dejar el `413` sin cabecera. Sin él, «se monta el último» es una
frase en un comentario.

Rejected: un único test verde sobre la app real — pasa vacuamente si el helper devuelve
siempre `[]` (p. ej. si la enumeración inspecciona cero rutas, que es la trampa que
`route_walk.py` documenta haber pisado dos veces).

### D9 — R4 corrige **dos** sitios, no uno, y el segundo está publicado en el contrato

**Chosen:** el barrido de R4.3 sobre todo el árbol da exactamente dos redacciones vivas de la
clase, y las dos se corrigen:

1. `backend/app/integrations/api/router.py:93-95` — el que nombra R4.1
   (*«defence in depth for a request whose body arrived in one chunk under a lying
   `Content-Length`»*). La lectura `await file.read(limit + 1)` **se conserva** (R4.2).
2. `backend/app/cleaning/api/tasks_router.py:399-405` — la descripción del `413` en
   `_PHOTO_UPLOAD_RESPONSES`: *«Answered by `MaxBodySizeMiddleware` before the body is read,
   **and again by the use case while it consumes the stream**»*. Ese «and again» es la misma
   afirmación falsa en su forma más dañina, porque **está publicada en `backend/openapi.json`**
   (línea 6891) y llega al frontend.

Las dos redacciones nuevas **enlazan a la regla 14 de D6** en vez de volver a razonarlo, que es
el contrato que R3.2 pide. La redacción modelo ya existe y no hay que inventarla:
`UploadCleaningPhotoUseCase._read_within_limit` (`app/cleaning/application/use_cases.py:1433-1466`)
y `Settings.photo_upload_max_bytes` (`app/core/config.py:149-161`) son las versiones corregidas
en `cleaning-photos-storage`.

Lo que el barrido **descarta** por no ser de la clase, dicho para que no se rehaga:
`app/guests/api/portal_schemas.py:80` (subrogados UTF-8, ya corregido), 
`app/integrations/application/webhooks.py:169` (autenticación antes del cuerpo — cierto),
`specs/reservations.md:238`, `specs/cleaning.md:25`, `specs/ingress-https-dev.md:78`,
`specs/pms-beds24-spike.md:92` y `docs/cleaning.md:120` (todas describen el middleware, y bien).

**Consecuencia de coste que hay que ver antes de empezar**: tocar la descripción del `413`
obliga a `make openapi` **y** a regenerar `frontend/lib/api/generated/openapi.d.ts`
(`steering/documentation.md`, «las dos mitades del mismo puente»). El segundo comando
documentado **no funciona en un worktree enlazado**; la salida verificada está en
`sdd/project.md` § *Worktree bootstrap* (`docker compose cp` + symlink + `npm run api:generate`).

Rejected: dejar el segundo sitio y arreglar sólo el que R4.1 nombra — R4.3 pide el barrido y
el hallazgo es exactamente lo que pide; además es el único de los dos que está publicado.

### D10 — El hogar de R5 es una spec nueva, escrita **al archivar**

**Chosen:** `sdd/specs/backend-http-posture.md`, creada por `/sdd:archive` con la postura HTTP
del backend entera: la cabecera (R1/R2), su residuo nombrado (D3), y los **cuatro** techos de
cuerpo que `app/main.py` resuelve hoy con la razón medida de cada número y el riesgo aceptado
que ese fichero ya nombra (R5.3). `specs/auth-tenancy.md` §*Tope de tamaño de cuerpo*
(líneas 360-374) se reduce a una referencia (R5.2), y `specs/cleaning.md:189` y `:289` pasan a
citar la postura global conservando lo propio de la ruta de fotos (R1.5).

**Por qué al archivar y no en `/sdd:run`:** `sdd/specs/` documenta el comportamiento del sistema
*vigente* y sólo lo escribe `/sdd:archive` (regla 1 de SDD, y `steering/documentation.md` lo
repite: *«sdd/specs/ … se mantiene solo al archivar»*). El design lo fija aquí para que
`/sdd:tasks` no invente una tarea de `run` que edite specs, y para que el archivado no tenga que
re-derivar qué va en el documento nuevo.

Rejected: escribirla durante `run` — rompe la regla 1 y deja la spec describiendo algo que aún
no está mergeado.
Rejected: dejar el contrato en `auth-tenancy.md` y sólo actualizarlo — R5.1 pide un documento
propio, y el contrato es de la postura HTTP del backend, no de auth ni de tenancy: es
precisamente el hogar prestado el que lo dejó con dos techos de cuatro.

#### Material para el archivado (tarea 4.6, R5.1-R5.3)

Escrito aquí para que `/sdd:archive` no tenga que re-derivarlo leyendo el código. Verificado
contra `app/main.py` y `app/core/config.py` el 2026-08-15.

**Los cuatro techos que `app/main.py` resuelve, en el orden en que los evalúa su `lambda`
(y el orden es el mecanismo, no orden estético — ver abajo):**

| Rama | Techo | Valor | Dónde se define | Por qué ese número |
|---|---|---|---|---|
| `/api/v1/cleaning-tasks/…/photos` | `PHOTO_UPLOAD_MAX_BYTES` | 10 MiB | `Settings.photo_upload_max_bytes` (`app/core/config.py:162`), configurable | Regla 6 de `steering/security.md` («tamaño máx. configurable, default 10 MB»), dimensionado por lo que produce la cámara de un móvil. Setting **propio** y no reutilizar el del CSV: una importación la acota cuántas reservas pega una persona, una foto la acota el sensor, y compartir el número haría que ajustar uno moviera el otro en silencio (`cleaning-photos-storage` D10/D11). |
| `/api/v1/integrations/` | `CSV_IMPORT_MAX_BYTES` | 10 MiB | `Settings.csv_import_max_bytes` (`app/core/config.py:130`), configurable | La misma regla 6 y su default de 10 MB, para la importación manual de reservas. |
| `/api/v1/cleaning-` | `JSON_BODY_MAX_BYTES` | 1 MiB | Constante en `app/core/http_limits.py:79`, **no** setting | `POST /cleaning-checklist-templates` recibe un array que dimensiona el cliente, y sus topes de Pydantic sólo corren con el cuerpo entero en memoria. Medido en `cleaning`: un `POST` anónimo de ~50 MB se recibió entero y luego contestó `401`. El número **está medido contra el máximo del esquema, no estimado**: la plantilla máxima válida (`MAX_ITEMS=200` × `MAX_LABEL_LENGTH=200`) son 87 KB en ASCII pero **338 KB con etiquetas acentuadas** —`json.dumps` escapa el no-ASCII y las fixtures del proyecto dicen `Baño` y `Terraza`— y 640 KB con emoji. Un primer borrador de 256 KiB hacía que el middleware y el validador discreparan sobre qué es legal. Constante y no setting a propósito: no hay razón operativa para ajustarlo y sería un mando que nadie toca. |
| todo lo demás bajo `/api/v1/` | `REQUEST_MAX_BYTES` | 1 MiB | `Settings.request_max_bytes` (`app/core/config.py:171`), configurable | `api-ingress-routing` R7/D11: con `/api/v1` alcanzable desde internet, un cuerpo sin techo en un endpoint anónimo es un amplificador de memoria. Medido: un solo `POST /api/v1/auth/login` de 400 MB llevó el contenedor de 195 MiB a 1,016 GiB de RSS en 2,3 s, y FastAPI lee ese cuerpo antes de las dependencias, o sea antes de que se consulte el límite de 10/min del login. Ningún compose pone límite de memoria a `backend`, así que el techo era el de la VM. |

Dos notas que la spec debe conservar porque sin ellas los números se leen mal:

- **`JSON_BODY_MAX_BYTES` y `REQUEST_MAX_BYTES` valen hoy lo mismo y siguen separados a
  propósito**: uno está clavado al máximo de un esquema y el otro es un mando operativo, así
  que fundirlos haría que ajustar el mando moviera en silencio una frontera medida.
- **El orden de las ramas es el mecanismo**: la de fotos va primera porque su ruta también
  empieza por `/cleaning-`, y un `elif` posterior no se alcanzaría nunca — toda foto por
  encima de 1 MiB quedaría rechazada. La rama casa por los dos extremos (prefijo
  `/cleaning-tasks/` y sufijo `/photos`) para que el techo ancho llegue a esa colección y no
  a un vecino que acabe igual.

**El riesgo aceptado, que se recoge sin reabrirlo ni volver a razonarlo** (`app/main.py:190-208`
lo enuncia entero): la rama de fotos concede **hasta 10 MiB de cuerpo anónimo antes de
autenticar**. El proveedor de techos lo consulta el middleware, que por construcción corre
antes de resolver la ruta y antes de `require(...)` —que es justo para lo que existe—, así que
la coincidencia es sobre la cadena de la ruta: quien adivine la forma de la URL hace que el
backend reciba hasta `PHOTO_UPLOAD_MAX_BYTES` por petición sin token, y la respuesta (un `401`)
llega cuando el cuerpo ya está dentro. El patrón es además **más ancho que la ruta**:
`/api/v1/cleaning-tasks/photos` y `/api/v1/cleaning-tasks/a/b/c/photos` también casan, consumen
hasta 10 MiB y luego contestan `404`/`405`. Se acepta como coste irreducible de tener un
endpoint de subida, y es **el mismo trato que `/integrations/` ya tenía** con
`CSV_IMPORT_MAX_BYTES` (también 10 MiB, también pre-auth). Lo que lo acota: 10 MiB es ~40 veces
menos que el cuerpo de 400 MB que motivó montar el middleware, y es un techo **por petición**,
no por conexión.

**Lo que la spec nueva NO hace**: mover ningún número (*Out of scope* de la proposal). Los
cuatro se documentan tal como están.

**Y la otra mitad del documento, la de R1/R2**: la cabecera `X-Content-Type-Options: nosniff`
la pone `NoSniffMiddleware` (`app/core/response_headers.py`) sobre **toda** respuesta, incluidas
las que no salen de ningún handler (`404`, `405`, el envelope de §23 y el `413` que
`MaxBodySizeMiddleware` fabrica), con el residuo nombrado de D3 —el `500` de
`ServerErrorMiddleware`, cuerpo constante sin un byte del cliente— y la guardia por enumeración
de `backend/tests/test_response_headers.py`. `specs/cleaning.md:189` y `:289` pasan a citar esta
postura conservando lo propio de la ruta de fotos (`Content-Type` por extensión, `Cache-Control`
y su sello local de D5).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Backend — core | `backend/app/core/response_headers.py` **(nuevo)** | `NoSniffMiddleware`, ASGI puro (D1/D4). Docstring con el residuo de D3 y el porqué del orden de D2. |
| Backend — arranque | `backend/app/main.py` | Un `add_middleware(NoSniffMiddleware)` **después** del de `MaxBodySizeMiddleware`, con el comentario que explica por qué la posición es el mecanismo (D2). |
| Backend — fotos | `backend/app/cleaning/api/photos_router.py` | Sólo docstring del módulo (bloque 2, líneas 20-31): el hueco que describe ya está cerrado. El sello de `_respond` se conserva (D5). |
| Backend — integrations | `backend/app/integrations/api/router.py:93-95` | Redacción corregida, enlazando a la regla 14. La lectura acotada se conserva (R4.2, D9). |
| Backend — cleaning | `backend/app/cleaning/api/tasks_router.py:399-405` | Descripción del `413` corregida (D9). |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados por el cambio de descripción anterior (D9). Sin cambio de forma. |
| Tests | `backend/tests/test_response_headers.py` **(nuevo)** | Enumeración (D7), test en rojo ×2 (D8), `413`/`404`/`405`/`422` (R1.2/R1.3), no-duplicación en la ruta de fotos (R1.4). |
| Steering | `sdd/steering/security.md` | Regla 14 (D6). |
| Steering | `sdd/steering/backend.md` | Una línea en *Don'ts* enlazando a la regla 14 (D6, R3.2). |
| Specs — **al archivar** | `sdd/specs/backend-http-posture.md` **(nuevo)**, `sdd/specs/auth-tenancy.md`, `sdd/specs/cleaning.md` | D10. No se tocan en `/sdd:run`. |

## Data & interfaces

- **Esquema de base de datos**: ninguno.
- **Variables de entorno**: ninguna. Los cuatro techos ya existen
  (`PHOTO_UPLOAD_MAX_BYTES`, `CSV_IMPORT_MAX_BYTES`, `REQUEST_MAX_BYTES` en `Settings`;
  `JSON_BODY_MAX_BYTES` como constante) y **no se mueve ninguno** (*Out of scope*), así que
  `.env.example` no cambia.
- **Contrato de API**: la cabecera **no** se declara en OpenAPI y no aparece en `openapi.json`
  — FastAPI no publica cabeceras de respuesta transversales, y declararla operación por
  operación en las 65 sería la lista escrita a mano que R2.1 prohíbe, en otro fichero. El único
  cambio en `openapi.json` es el texto de la descripción del `413` de la subida de fotos (D9).
- **Interfaces nuevas**: una clase ASGI sin configuración
  (`NoSniffMiddleware(app)`), sin parámetros y sin filtro de prefijo — R1.1 dice *cualquier*
  respuesta, así que `/health` y `/docs` entran igual que `/api/v1/`.
- **Frontend**: ninguno más allá del artefacto derivado regenerado. Ningún string de UI.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **Alguien reordena los dos `add_middleware`** y el `413` vuelve a salir desnudo, en silencio. | Es el riesgo principal y tiene dos tests: el `413` de R1.3 y el test de orden invertido de D8. Ninguno de los dos pasa vacuamente. |
| El middleware **rompe el contador de `MaxBodySizeMiddleware`** al envolver `receive`. | No lo envuelve: pasa `receive` tal cual y sólo decora `send` (D1). Toda la suite de `tests/test_http_limits.py`, `test_request_body_ceiling.py`, `tests/cleaning/test_photo_body_limit.py`, `tests/integrations/test_webhook_body_ceiling.py` y `tests/guests/test_portal_body_ceiling.py` corre en Verification como red. |
| **Doble cabecera** en la ruta de fotos, que R1.4 prohíbe. | `MutableHeaders.__setitem__` borra y escribe (D4), con su test propio contando apariciones en la respuesta cruda, no leyendo `headers["..."]` (que colapsaría dos valores en uno y pasaría vacuamente). |
| El test de enumeración **inspecciona cero rutas** y pasa verde — la trampa que `route_walk.py` documenta haber pisado dos veces. | Reusa `flatten_routes` (no re-deriva la caminata) y añade el test en rojo de D8 más una aserción de que el conjunto enumerado contiene las rutas de `auth`, como hace `test_the_flattener_finds_the_auth_endpoints`. |
| Conducir 65 peticiones **encarece la suite** o toca la BD en rutas anónimas (webhooks, portal de huésped). | Todas responden sin negocio: `401` antes de dependencias en las protegidas, `422`/`404` constante en las anónimas. Se mide en Verification; si molesta, la conclusión es reducir el fixture, no la enumeración. |
| **Regenerar el contrato desde el worktree** falla con el comando documentado. | Está previsto: la salida verificada de `sdd/project.md` § *Worktree bootstrap*. `/sdd:tasks` debe escribirla literal en la tarea, no el comando de `steering/documentation.md`. |
| Se cuela una **segunda cabecera de seguridad** «ya que estamos». | *Out of scope* de la proposal es explícito y el nombre de la clase (`NoSniffMiddleware`, no `SecurityHeadersMiddleware`) no lo pre-autoriza. |

## Open questions

Ninguna. Las tres que abrió este design se resolvieron en su gate (Jose, 2026-08-15), y las tres
confirmaron la recomendación. Se dejan escritas con su alternativa porque son las tres que un
panel volvería a preguntar:

**OQ1 — El `500` de `ServerErrorMiddleware`: residuo nombrado. RESUELTA → D3.**
Se documenta y no se cubre: su cuerpo es una constante sin un solo byte del cliente. Descartado
cerrarlo con un handler global de `Exception` — arreglaría de paso que hoy el `500` sale en
`text/plain` en vez del envelope §23, pero es un cambio de comportamiento que ningún requisito
pide y que altera `raise_server_exceptions` en los tests. Si se quiere, entrada propia.

**OQ2 — `photos_router._respond` conserva su `nosniff`. RESUELTA → D5.**
Descartado cederlo al middleware: quitar la línea haría que el XSS almacenado que
`storage.py:171-174` describe dependiera del orden de dos `add_middleware`, a cambio de una
línea. R1.4 se cumple en ambos casos porque D4 escribe en vez de añadir.

**OQ3 — La regla 14 va en `steering/security.md`. RESUELTA → D6.**
Decide el frontmatter: `phases: [design, run]` es literalmente lo que pide R3.3, mientras que
`backend.md` se carga por `applies_to`, una condición sobre el scope y no sobre la fase.
`backend.md` recibe un puntero de una línea, sin reformular (R3.2).
