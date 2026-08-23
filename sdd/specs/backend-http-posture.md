# Postura HTTP del backend

## Purpose

Hogar único de las propiedades que el backend aplica a **toda** petición y **toda** respuesta,
con independencia de la ruta: la cabecera `X-Content-Type-Options: nosniff` que impide que un
navegador adivine el `Content-Type` de un cuerpo controlado por el cliente, y los cuatro topes de
tamaño de cuerpo que rechazan una petición **antes** de leerla. Ambas son propiedades del sistema,
no de los endpoints que alguien se acordó de anotar; esta spec existe porque las dos se decidieron
bien en una ruta y se olvidaron en las demás.

## Requirements

### `nosniff` en toda respuesta

- WHEN la aplicación emite cualquier respuesta HTTP, THE SYSTEM SHALL incluir
  `X-Content-Type-Options: nosniff`, sin que la ruta tenga que pedirlo.
- WHERE la respuesta no la construye ningún handler —el `404` de una ruta que nadie reclama, el
  `405` de un verbo equivocado, el `422` de validación y el resto del sobre de error de PRD §23—
  THE SYSTEM SHALL incluirla igualmente.
- WHEN `MaxBodySizeMiddleware` fabrica y envía su propio `413`, THE SYSTEM SHALL incluirla también
  en esa respuesta, que no pasa por ninguna ruta.
- WHERE una ruta sella la cabecera por su cuenta —hoy **dos**, `GET /api/v1/cleaning-photos/{photo_id}`
  y `GET /api/v1/incident-photos/{photo_id}`, las dos rutas anónimas que sirven bytes de un objeto
  contra una firma HMAC— THE SYSTEM SHALL emitir **exactamente un** valor `nosniff`: el sello global
  sobrescribe, no añade ni respeta un valor previo. Ninguna respuesta de este backend tiene una
  razón legítima para querer sniffing.
- THE SYSTEM SHALL sellarlo en esas dos rutas desde **un solo punto de salida compartido**
  (`app/integrations/api/signed_media.py`), por el que pasan tanto los bytes como las tres
  negativas de cada una. Dos copias de ese sello serían dos sitios donde una de las dos rutas
  pudiera perderlo sin que la otra lo notase; desde que hay dos consumidores del almacén
  ([`file-storage`](file-storage.md)) el sello vive una sola vez.
- THE SYSTEM SHALL sellar sin tocar `receive`: sólo se decora `send`. Envolver `receive` se
  interpondría entre el servidor ASGI y el contador acumulativo de `MaxBodySizeMiddleware`, que es
  la mitad que caza un `Content-Length` mentido.
- THE SYSTEM SHALL implementarlo como middleware ASGI puro, no `BaseHTTPMiddleware`: éste último
  construye un `Request` y consume el cuerpo, justo lo que el tope de tamaño existe para evitar.

### La cabecera se monta la última, y esa posición es el mecanismo

- THE SYSTEM SHALL añadir `NoSniffMiddleware` **después** de `MaxBodySizeMiddleware` en
  `create_app()`. `Starlette.add_middleware` inserta en la posición 0 y `build_middleware_stack`
  envuelve la lista en orden inverso, así que el último añadido queda el **más externo** — y sólo
  desde fuera se ve el `413` que el middleware de tamaño se construye solo.
- IF alguien intercambia las dos llamadas, THEN THE SYSTEM SHALL fallar en rojo
  (`tests/test_response_headers.py::test_the_check_catches_the_middlewares_in_the_wrong_order`),
  nunca limitarse a leer bien en un comentario.

### La postura se verifica por enumeración, no ruta a ruta

- THE SYSTEM SHALL verificar la cabecera recorriendo las rutas que la aplicación tiene montadas y
  conduciendo **una petición real por verbo** contra cada una, sin credenciales y sin cuerpo — no
  una lista de rutas escrita a mano.
- THE SYSTEM SHALL considerar irrelevante el código de estado: un `200`, un `401`, un `404` y un
  `422` han de llevar la cabecera por igual, así que la comprobación **no tiene allowlist** y una
  ruta nueva queda cubierta sin tocar el test.
- IF la enumeración encuentra superficie que no puede conducir —un websocket, un `Mount`— THEN THE
  SYSTEM SHALL reportarla nombrada como `UNINSPECTABLE` y fallar, nunca omitirla en silencio.
- THE SYSTEM SHALL incluir un test anti-vacuidad que compruebe que el recorrido alcanza rutas
  concretas conocidas: este proyecto ya publicó dos guardias que pasaban inspeccionando una lista
  vacía.
- THE SYSTEM SHALL demostrar la comprobación **en rojo** (regla 13(c) de `steering/security.md`):
  una aplicación construida sin el middleware produce la lista de respuestas desnudas, incluidas
  las cuatro rutas de documentación que FastAPI monta por su cuenta y que una enumeración limitada
  a `APIRoute` no vería.

### Residuo nombrado: el `500` de `ServerErrorMiddleware`

- THE SYSTEM SHALL aceptar que una excepción no capturada sale con el
  `PlainTextResponse("Internal Server Error", 500)` de Starlette **sin** la cabecera: ese
  middleware se monta por fuera de todo middleware de usuario.
- THE SYSTEM SHALL aceptarlo por el criterio de que ese cuerpo es una constante de compilación sin
  un solo byte del cliente, luego no hay nada que esnifar. Cerrarlo exigiría un handler global de
  `Exception`, que cambiaría el cuerpo del `500` de `text/plain` al sobre de PRD §23 — un cambio de
  comportamiento que ningún requisito pide.
- WHERE la aplicación se construyera con `debug=True`, THE SYSTEM SHALL invalidar esa aceptación:
  bajo `debug` ese middleware responde con un traceback HTML derivado de la petición y de la
  excepción, es decir bytes del cliente en la única respuesta que escapa al sello. `create_app()`
  nunca pasa `debug`, y cablear `FastAPI(debug=...)` SHALL hacer fallar
  `tests/test_response_headers.py::test_the_named_residue_stays_what_d3_accepted`.
- THE SYSTEM SHALL extender el mismo criterio, y el mismo límite, a lo que se emite por debajo de
  la aplicación: la respuesta de uvicorn a una petición malformada y lo que produzca el ingress sin
  llegar a nosotros nunca entran en la app ASGI, así que ningún middleware puede sellarlas, y sus
  cuerpos son también constantes.

### Topes de tamaño de cuerpo

- THE SYSTEM SHALL aplicar un tope de tamaño a **todo** `/api/v1/`, antes de leer el cuerpo,
  respondiendo `413` con el sobre de PRD §23 y `code` `PAYLOAD_TOO_LARGE`.
- THE SYSTEM SHALL resolver el techo **por ruta** en una **sola** instancia de middleware. Apilar
  una instancia por prefijo no funciona: las instancias se anidan, así que la más externa decide
  primero y una más estrecha por dentro nunca llega a ver la petición.
- THE SYSTEM SHALL resolver los cuatro techos en **cinco ramas**, en este orden, y el orden es el
  mecanismo:

  1. `/api/v1/cleaning-tasks/…/photos` → `PHOTO_UPLOAD_MAX_BYTES` (10 MiB). **Va primero** porque
     la ruta también empieza por `/cleaning-`; un `elif` después de esa rama no se alcanzaría nunca
     y toda foto por encima de 1 MiB sería rechazada. El patrón exige ambos extremos —prefijo
     `/api/v1/cleaning-tasks/` y sufijo `/photos`— para que el techo ancho llegue a esa colección y
     no a un vecino que acabe igual.
  2. `/api/v1/incidents/…/photos` → `PHOTO_UPLOAD_MAX_BYTES` (10 MiB), el **mismo** ajuste y no uno
     nuevo: es el mismo tipo de fichero por la misma clase de puerta
     ([`incident-photos`](incident-photos.md)). Su posición relativa **no** es crítica como la de la
     rama de limpieza —`/incidents/` no comparte prefijo con `/cleaning-` ni con `/integrations/`—,
     pero tiene que estar antes del `else`, y un test lo fija. Acotada por los dos extremos por el
     mismo motivo que la primera.
  3. `/api/v1/integrations/` → `CSV_IMPORT_MAX_BYTES` (10 MiB). Regla 6 de `steering/security.md`.
  4. `/api/v1/cleaning-` → `JSON_BODY_MAX_BYTES` (1 MiB). El endpoint de plantillas de checklist
     recibe un **array dimensionado por el cliente**, así que su cuerpo no es un objeto pequeño y
     fijo, y sus topes de Pydantic sólo actúan con el cuerpo entero ya en memoria. Medido: un `POST`
     anónimo de ~50 MB se recibió completo y luego se respondió `401`. El número está medido contra
     el máximo del esquema (338 KB con etiquetas acentuadas, porque `json.dumps` escapa el no-ASCII
     y las fixtures del proyecto dicen `Baño`), no estimado.
  5. Todo lo demás → `REQUEST_MAX_BYTES` (1 MiB). Un `POST /auth/login` de 400 MB llevó el
     contenedor de 195 MiB a 1,016 GiB de RSS en 2,3 s, y FastAPI lee el cuerpo **antes** de
     resolver dependencias, o sea antes de consultar el throttle de 10/min. Ningún compose limita
     la memoria de `backend`, así que el techo era el de la VM.

- THE SYSTEM SHALL mantener `JSON_BODY_MAX_BYTES` y `REQUEST_MAX_BYTES` como constantes separadas
  aunque hoy valgan lo mismo: uno está clavado a un máximo de esquema y el otro es una palanca
  operativa, así que fundirlos haría que ajustar la palanca moviera en silencio una frontera medida.
- THE SYSTEM SHALL dejar que las rutas **no** cubiertas por una rama propia caigan en el `else`, y
  eso incluye las **trece** rutas de `/api/v1/incidents` que no son la foto: caen en
  `REQUEST_MAX_BYTES` y **no** en `JSON_BODY_MAX_BYTES`, porque esa rama se selecciona por el
  prefijo `/cleaning-` y `/incidents` nunca la ha tocado. Conviene escribirlo con la constante
  correcta: es un error que ya se coló en un requisito, resuelto verificándolo contra el código en
  vez de añadir una rama JSON que no hacía falta.
- THE SYSTEM SHALL hacer cumplir el tope en dos pasos, porque cada uno solo es sorteable: rechazar
  de entrada un `Content-Length` declarado por encima del techo —sin leer un byte— y contar el
  cuerpo según llega, abortando en cuanto lo excede, que es lo que cubre un `Content-Length` mentido
  o ausente (`Transfer-Encoding: chunked`).
- WHEN el cuerpo se corta y la aplicación intenta responder después, THE SYSTEM SHALL sustituir esa
  respuesta por el `413` **una sola vez** y descartar lo que la aplicación siga queriendo decir:
  nunca se emite un segundo `http.response.start`.
- IF la aplicación lanza una excepción en una petición que **además** excedió el tope, THEN THE
  SYSTEM SHALL responder `413` —es el parser atragantándose con el cuerpo truncado, obra del propio
  middleware—, pero SHALL propagar cualquier otra excepción, y también ésta si la respuesta ya
  empezó: tragársela reportaría un fallo real del endpoint como un problema de tamaño.

### Riesgo aceptado: cuerpo anónimo antes de autenticar

- THE SYSTEM SHALL aceptar que hasta `PHOTO_UPLOAD_MAX_BYTES` (10 MiB) de cuerpo se reciben sin
  token en **las dos** ramas de fotos: el proveedor lo consulta el middleware, que por construcción
  corre antes de resolver la ruta y antes de `require(...)` —esa es la razón de existir—, así que la
  coincidencia es sobre la cadena de la ruta y la respuesta (un `401`) llega con el cuerpo ya dentro.
- THE SYSTEM SHALL aceptar que el patrón es **más ancho que la ruta**, en las dos:
  `/api/v1/cleaning-tasks/photos` y `/api/v1/cleaning-tasks/a/b/c/photos` encajan en la primera, y
  `/api/v1/incidents/photos` y `/api/v1/incidents/a/b/c/photos` en la segunda; todas consumen hasta
  10 MiB y responden `404`/`405`. Estrechar el patrón a un segmento UUID acotaría esa mitad pero no
  la primera, que es la que importa: un id real es igual de adivinable en forma.
- THE SYSTEM SHALL escribir ese riesgo **junto a cada rama** en `app/main.py`, con su medida, en vez
  de heredarlo en silencio al añadir la segunda: una rama nueva que copia el patrón copia también la
  concesión, y una concesión que solo consta en la rama original deja de constar en cuanto alguien
  lee la nueva.
- THE SYSTEM SHALL aceptarlo por ser el coste irreducible de tener un endpoint de subida, y por ser
  el mismo trato que `/api/v1/integrations/` ya cerró con `CSV_IMPORT_MAX_BYTES` (10 MiB, también
  pre-auth). Lo que lo acota es que 10 MiB queda ~40× por debajo del cuerpo de 400 MB que motivó
  montar el middleware, y que es un techo por petición, no por conexión.

### El contrato de «rechazar antes de leer» tiene un solo hogar

- THE SYSTEM SHALL enunciar en la **regla 14 de `sdd/steering/security.md`**, y sólo ahí, que una
  comprobación de tamaño posterior a `request.form()`, a `file.read()` o a cualquier consumo del
  `UploadFile` **acota la copia en memoria y nada más**, y que «rechazar antes de leer el cuerpo»
  sólo lo satisface el contador acumulativo de `MaxBodySizeMiddleware`.
- THE SYSTEM SHALL exigir que todo sitio que necesite esa afirmación **enlace** a la regla 14 en vez
  de volver a derivarla; la regla lleva el índice de quién la enlaza. `app/core/http_limits.py` es
  la única excepción nombrada, por ser la *implementación* del contrato, y si ambos discrepan manda
  la regla.
- THE SYSTEM SHALL conservar las lecturas acotadas existentes: acotan el pico en memoria al techo
  más un chunk, y son el único techo para un llamante sin middleware delante (un test, un worker, un
  consumidor no-HTTP). Lo prohibido es presentarlas como defensa frente a un `Content-Length`
  mentido.

## Key files

- `backend/app/core/response_headers.py` — `NoSniffMiddleware`, el sello y el residuo nombrado.
- `backend/app/core/http_limits.py` — `MaxBodySizeMiddleware`, `JSON_BODY_MAX_BYTES` y el `413`.
- `backend/app/main.py` — el montaje de ambos, su orden, y el proveedor por ruta con los cuatro
  techos y el riesgo aceptado.
- `backend/app/core/config.py` — `photo_upload_max_bytes`, `csv_import_max_bytes`,
  `request_max_bytes`.
- `sdd/steering/security.md` regla 14 — hogar único del contrato de «rechazar antes de leer»;
  `sdd/steering/backend.md` lo enlaza desde su sección *Don'ts*.
- `backend/app/integrations/api/signed_media.py` — el punto de salida único de las dos rutas
  anónimas de foto: el sello de `nosniff` y el `Cache-Control` derivado de la firma
  ([`file-storage`](file-storage.md)).
- Tests: `backend/tests/test_response_headers.py` (cabecera, enumeración, orden de montaje y
  residuo), `backend/tests/cleaning/test_photo_body_limit.py` y
  `backend/tests/maintenance/test_photo_body_limit.py` (las mitades del techo por ruta de cada
  colección, incluida la evidencia de que el resto de `/incidents` cae en `REQUEST_MAX_BYTES`),
  `backend/tests/integrations/test_signed_media_headers.py` (el clamp del `max-age`, `private`, y
  exactamente un `nosniff`).
