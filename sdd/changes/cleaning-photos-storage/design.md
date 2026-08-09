# Design: cleaning-photos-storage

## Context

La tabla `cleaning_photos` existe desde `domain-foundation-ops` con todas sus columnas
(`backend/app/cleaning/infrastructure/models.py:117-126`) y **ningún escritor**. En el dominio,
`RequiredPhotoSpec` ya se valida y se transporta (`backend/app/cleaning/domain/value_objects.py:53-62`)
pero no se aplica, y `CleaningCompletionEvidence` (líneas 65-84) está diseñado para recibir la
evidencia desde el caso de uso — recibe, no lee. `CleaningTask.complete()`
(`backend/app/cleaning/domain/entities.py:129-159`) aplica dos de las tres cláusulas de PRD §11 y
documenta la ausente. No existe `CleaningPhotoRepository`, ni ningún puerto de almacenamiento en
ningún dominio, ni `boto3` en el proyecto.

Del lado HTTP, `backend/app/cleaning/api/tasks_router.py` monta 10 de las 12 rutas de PRD §23 y
declara ausentes las dos de fotos. `MaxBodySizeMiddleware` ya resuelve el tope **por path**
(`backend/app/main.py:113-121`), con tres ramas y `CSV_IMPORT_MAX_BYTES` como precedente exacto de
un límite de subida configurable.

## Decisions

### D1 — Dos puertos, no uno: escritura/URL por un lado, lectura local por otro

**Chosen:** `FileStoragePort` en `domain/` con **tres** métodos, todos con llamante en este change
(`put`, `signed_url`, `delete`), más un `LocalFileReadPort` **separado** que sólo implementa el
adaptador `LOCAL`. La resolución la hace un factory que rechaza con
`LocalFileReadUnsupportedError` cuando el tenant es `S3`, en vez de un método que exista para
fallar. Es exactamente el patrón que este repositorio ya estableció con `PMSMessagingPort` y
`PMSAdapterFactory.messaging_for` (`backend/app/integrations/domain/ports.py:78,189`), por la
misma razón: con `S3` el navegador va directo al proveedor y **nadie** lee bytes a través de la
aplicación, así que `open()` en el puerto común tendría un implementador que nunca se llama.

Rechazadas:
- Un puerto único con `open()` que `S3Adapter` implementa lanzando `NotImplementedError` — es la
  violación de Liskov que `steering/backend-architecture.md` §SOLID nombra explícitamente y que
  ADR 0006 decisión 3 ya rechazó una vez.
- Un `StorageAdapter` con `exists`, `list`, `copy`, `move`, `metadata`… — el «gigante con 15
  métodos» que el mismo steering usa como *su* ejemplo de fallo de segregación (R1.1 lo prohíbe
  por criterio de aceptación).

### D2 — El puerto vive en `app/integrations/`, no en `app/cleaning/` ni en un dominio nuevo

**Chosen:** `backend/app/integrations/domain/storage.py` (puertos) y
`backend/app/integrations/infrastructure/storage/{local,s3}.py` (adaptadores), replicando la forma
de `beds24/` y `channex/`. `steering/backend.md` lo dice literalmente: *«Adapters externos
compartidos en `app/integrations/`»*. Además `maintenance` (fotos de incidente) y `revenue`
(`expenses.receipt_storage_key`) serán consumidores, y colgarlo de `cleaning/` les obligaría a
importar desde otro dominio de negocio.

Rechazadas:
- `app/cleaning/domain/ports.py` — convierte a `cleaning` en dependencia de `maintenance`.
- Un dominio nuevo `app/storage/` — contradice la frase explícita de `backend.md`, y el
  almacenamiento no es un dominio de negocio con entidades propias.

### D2b — `S3` es el **protocolo**, no AWS: el adaptador queda abierto a otros proveedores

**Corrección de procedencia, añadida el 2026-08-08 tras una pregunta del usuario.** El diseño y la
tarea 1.5 dieron `boto3` por sentado sin declararlo como decisión, y eso fue una inferencia mía,
no algo que el proyecto tuviera escrito. Lo que sí está escrito es el PRD, y dice dos cosas:
*«`LocalStorageAdapter` dev / S3 prod»* (§4, línea 140) y, explícitamente,
*«Producción futura: **S3-compatible (Cloudflare R2 o AWS S3)**»* (línea 196). **El proveedor está
abierto**; no hay ADR, spec ni steering que lo cierre. El enum `StorageType.LOCAL`/`S3`
(`backend/app/tenants/domain/enums.py:10`) es preexistente de `domain-foundation`.

**Chosen:** mantener `boto3` como cliente del **protocolo S3**, no como compromiso con AWS, y
dejar la elección de proveedor explícitamente fuera de este change. La costura que lo permite ya
existe y es la que hace que esto no sea una promesa vacía:

- `build_s3_client(*, region_name, endpoint_url)` acepta un `endpoint_url` arbitrario.
- `S3FileStorage.__init__(*, bucket, client)` **recibe el cliente inyectado**, no lo construye.

Con eso, cualquier almacén compatible funciona sin tocar el adaptador. Y el candidato natural en
este proyecto **no es AWS**: el entorno `dev` ya corre en **Oracle Cloud** (ADR 0001), y OCI
Object Storage expone una API compatible con S3, así que el almacenamiento puede vivir donde ya
vive la VM, sin cuenta de AWS ni proveedor nuevo. Cloudflare R2 —que el PRD nombra primero— y
MinIO entran por la misma puerta.

El nombre `S3FileStorage` se conserva a propósito: espeja el valor del enum `StorageType.S3`, y
renombrarlo desalinearía el código de la columna. Lo que cambia es que su docstring dice qué
significa —el protocolo, no el proveedor— en vez de dejarlo a la suposición del lector, que es
exactamente lo que pasó aquí.

Rechazadas:
- **Fijar AWS ahora** — el PRD deja la elección abierta y no hay entorno de producción decidido
  (`steering/infra.md`: staging/prod siguen sin elegir). Cerrarla desde un change de fotos sería
  decidir infraestructura por la puerta de atrás.
- **Quitar `S3FileStorage` del alcance** — opción real y planteada al usuario, que decidió
  mantenerlo (2026-08-08). Sin una segunda implementación, la sustituibilidad de SOLID-L que el
  steering exige al puerto no tendría contra qué demostrarse, y el `read_for()` que rechaza en
  `S3` (D1) no tendría caso que rechazar.

Consecuencia registrada: **no existe `S3_BUCKET`, ni `endpoint_url`, ni región en `config.py`**, y
por eso un tenant en `S3` recibiría `502` en cada subida. Es deuda declarada, no descuido — ver
`BLOCKED.md` §4, donde vive junto con la elección de proveedor.

### D3 — Esquema de clave con `tenant_id` delante, y la extensión sale del contenido

**Chosen:** `tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{ext}`, donde `photo_id` es el
UUID de la fila `CleaningPhoto` generado antes de escribir, y `{ext}` se deriva del **MIME
detectado** (D5). El nombre de fichero que envía el cliente **no toca la clave en ningún punto**:
es entrada no confiable y la única forma segura de tratarla es no usarla. `tenant_id` primero
satisface R1.4 y hace que un prefijo de S3 sea directamente acotable por tenant el día que haga
falta.

Rechazada: clave derivada del nombre del cliente, aunque fuera saneada — «saneado» es una lista
negra y las listas negras de rutas fallan; y no aporta nada, porque el nombre original no se
muestra en ninguna parte.

### D4 — Objeto primero, fila después, y borrado compensatorio si el commit falla

**Chosen:** escribir el objeto en el almacén, luego insertar la fila, y si la transacción falla
llamar a `delete` en *best effort*. R1.5 prohíbe una fila apuntando a un objeto inexistente; el
orden inverso lo garantizaría al revés (objeto huérfano) y ese es el fallo barato: un objeto sin
fila es basura recuperable, una fila sin objeto es un `GET` roto para siempre. El borrado
compensatorio es lo que le da a `delete` un llamante real y mantiene el puerto en tres métodos
con consumidor (R1.1).

Rechazada: transacción distribuida o *outbox* — desproporcionado para una foto; el modo de fallo
aceptado (objeto huérfano) se documenta y se barre después si alguna vez importa.

### D5 — MIME por *magic bytes* propios, sin dependencia nueva

**Chosen:** leer los primeros bytes del fichero y comparar contra una allowlist corta —
JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), WebP (`RIFF....WEBP`)— ignorando por completo
el `Content-Type` que declara el cliente (R2.4 exige el MIME **real**). Son ~15 líneas y cero
superficie nueva de dependencias.

Rechazadas:
- `python-magic` — obliga a instalar `libmagic` en la imagen del backend, es decir infraestructura
  por 15 líneas.
- `filetype` — dependencia pura-Python pero dependencia al fin, con su propio CVE surface.
- `imghdr` de la stdlib — **retirado en Python 3.13**, y el proyecto declara «Python 3.12+».

Consecuencia con nombre: **HEIC/HEIF queda fuera**, y es el formato nativo de la cámara de iPhone.
Ver Q1 — es una decisión de producto, no técnica.

### D6 — La firma de la URL local se deriva de `JWT_SECRET_KEY` por HKDF, no la reutiliza

**Chosen:** `HMAC-SHA256` sobre un mensaje versionado que incluye la clave y la caducidad, con
`k = HKDF(JWT_SECRET_KEY, info=b"autohostai/cleaning-photo-url/v1")`. La derivación da separación
de dominio criptográfico —firmar una URL nunca puede producir ni verificar un JWT— sin introducir
un secreto nuevo que haya que provisionar en Terraform, en el Vault de OCI, en `docker-compose` y
en `.env.example`. El prefijo de versión permite rotar el esquema sin invalidar nada por sorpresa.
Comparación con `hmac.compare_digest` (R3.5).

**Endurecido tras el panel de la sección 1** (dos hallazgos aceptados, uno de seguridad y uno de
tenancy):

- **La codificación del mensaje firmado es inequívoca por construcción**, no por disciplina del
  llamante. La primera versión concatenaba `v1|{key}|{expiry}` sin validar que `key` no contuviera
  el delimitador: hoy no era explotable porque el único productor de claves es
  `storage_key_for_photo` (segmentos literales, UUIDs y extensiones de la allowlist), pero eso es
  una propiedad de *quién llama*, no una invariante del primitivo — y D2 ya nombra a `maintenance`
  y `revenue` como los próximos firmantes, con claves construidas de otra forma. El formato pasa a
  `v2`.
- **El TTL tiene techo, y se comprueba también al verificar.** `signed_url(expires_in=...)` acotaba
  nada y `verify_signed_key` aceptaba cualquier `expiry` que la firma cubriese, así que los 3600 s
  de R3.1 eran un argumento por defecto y no una invariante: un consumidor futuro podía acuñar una
  URL anónima efectivamente permanente. Ahora se acota al firmar **y** se rechaza al verificar
  cuando `expiry - now` excede el techo. La segunda mitad es la que importa — es la que invalida
  una URL excesiva aunque alguien consiga firmarla.

**Residuo consciente, nombrado por el panel y no cerrado**: el techo se mide sobre `expiry - now`,
así que una URL firmada con `exp = now + 1 año` **no es permanente, pero sí es válida durante su
última hora**, en un instante futuro que elige quien la firmó. Cierra el riesgo grande —acceso
anónimo perpetuo— y deja una URL «durmiente». Cerrarlo del todo exige meter un `iat` en el
payload y acotar `expiry - iat`; no se hace ahora porque el único firmante es código propio, y
queda escrito aquí para que el día que un tercero pueda pedir una firma esto no se redescubra.

Rechazadas:
- Usar `JWT_SECRET_KEY` en crudo como clave HMAC — misma clave para dos propósitos distintos; si
  alguna vez un oráculo de firma se expone, contamina la autenticación.
- Un `MEDIA_SIGNING_KEY` nuevo — correcto en abstracto, pero toca Terraform (`random_password` +
  `oci_vault_secret`), el compose, el deploy y `.env.example` por un beneficio que la derivación ya
  da. Ver Q2: si el usuario lo prefiere, es un cambio localizado.
- Firmar con Fernet (`ENCRYPTION_KEY`) — ese secreto gobierna credenciales de proveedor bajo la
  regla 3 de `steering/security.md`; ampliarle el radio de uso va en dirección contraria.

### D7 — El endpoint de servido local es anónimo a propósito, y la firma es su autorización

**Chosen:** `GET /api/v1/cleaning-photos/{photo_id}` con `exp` y `sig` en query, **sin JWT**. Un
`<img src>` no envía cabecera `Authorization`, así que exigir el token haría la URL firmada
inservible para lo único que existe. La firma es la credencial: cubre la clave completa —que
lleva el `tenant_id` (D3)— y su caducidad, así que no hay forma de pivotar a otro tenant sin el
secreto. Ante firma inválida, caducada o manipulada: **`403` siempre**, idéntico, sin distinguir
«no existe» de «no autorizado» (R3.4).

**Esto es superficie pública nueva y hay que decirlo:** `api-ingress-routing` dejó `/api/v1`
alcanzable desde internet por el túnel de Cloudflare, así que esta ruta nace expuesta. Mitigado
por: caducidad 3600 s (regla 5), comparación en tiempo constante, cero información en el error, y
un tope de tamaño de respuesta que es el del objeto ya validado en la subida.

**El `Content-Type` de esta ruta sale de la extensión de la clave y de ningún otro sitio, y la
respuesta lleva `X-Content-Type-Options: nosniff`.** Obligación añadida tras el panel de la
sección 1, donde el revisor de seguridad y el de QA llegaron al mismo punto por caminos distintos:
el MIME detectado en la subida **no se persiste** —en `LOCAL` sólo sobrevive dentro de la
extensión de la clave—, así que un polyglot que empiece por `FF D8 FF` y contenga HTML se
convierte en **XSS almacenado sobre el origen de la API** si este endpoint deja adivinar el tipo.
La función que mapea extensión → MIME vive en `integrations/domain/storage.py`, derivada de la
**misma** allowlist que `detect_image_type` para que las dos no puedan divergir. Sin ella, además,
`LOCAL` serviría `application/octet-stream` mientras `S3` sirve el MIME correcto: una asimetría de
comportamiento observable entre dos implementaciones del mismo puerto.

Rechazada: exigir JWT y que el frontend descargue por `fetch` + `blob:` — mueve el problema al
cliente, multiplica memoria en el navegador de una limpiadora en móvil y sigue necesitando la
firma para S3, donde el navegador va directo.

### D7b — La ruta anónima resuelve el tenant desde la clave, no desde una sesión que no tiene

**Hueco encontrado al implementar la sección 2, no previsto en D7.** La ruta de servido es anónima,
así que **no hay `tenant_id` de sesión** — y lo necesita dos veces: para leer la fila de la foto y
para resolver `TenantConfig.storage_type` y decidir si hay servido local (R3 y el `404` de la
tarea 4.4). Pero `CleaningPhotoRepository.get(tenant_id, photo_id)` exige el tenant por
construcción (tarea 2.1, y es lo que lo hace inalcanzable por UUID), y `LocalFileStorage.signed_url`
sólo pone el `photo_id` en la URL. El bucle no cierra.

**Chosen:** una lectura **explícitamente sin tenant**, acotada a esta ruta, que resuelve
`photo_id → (storage_key, tenant_id)`; con ella se reconstruye la clave y **entonces** se verifica
la firma. El orden importa y es lo que hace que esto sea seguro: la firma cubre la clave completa,
que empieza por `tenants/{tenant_id}/`, así que una firma válida **demuestra** que quien la
presenta obtuvo una URL emitida para esa foto de ese tenant. La lectura sin tenant no concede nada
por sí sola — sin firma válida no devuelve bytes— y no puede usarse como oráculo porque el `403`
es constante (tarea 4.3b).

No va por `CleaningPhotoRepository`: añadirle un quinto método sin tenant rompería el criterio de
aceptación de la tarea 2.1 y, peor, pondría una lectura sin scoping al alcance de los casos de uso
autenticados, donde nunca debe estar. Es una función aparte, nombrada de forma que se vea lo que
hace, y con su propio test de que el orden es «resolver → verificar → servir» y nunca al revés.

Rechazadas:
- **Meter la clave completa en la URL** — resuelve el tenant de un plumazo, pero R3.2 prohíbe que
  `storage_key` aparezca en ninguna respuesta de la API, y la URL firmada es una respuesta.
- **Un JWT de servido con el tenant dentro** — reintroduce el token que D7 descartó justamente
  porque un `<img src>` no manda cabecera `Authorization`.

### D7c — Excepción nombrada a R3.2 para `S3`, con su condición de cierre

**R3.2 no admitía excepción, y el código ya la tiene.** Lo señalaron los paneles de las secciones
3 y 4: `generate_presigned_url` devuelve la clave completa —`tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.ext`—
y el nombre del bucket dentro de la URL. Con `LOCAL` la URL lleva sólo el `photo_id`, así que
**el invariante que R3.2 declara global se cumple hoy en una implementación y no en la otra**.

**Chosen:** reconocerlo como excepción explícita en vez de dejarlo sólo en docstrings. R3.2 se lee,
a partir de aquí: *«`storage_key` no aparece en ninguna respuesta de la API, salvo dentro de una
URL prefirmada emitida por un proveedor S3-compatible, donde la clave es parte del protocolo de
firma y no puede retirarse»*. La primera mitad sigue siendo absoluta para todo lo demás — cuerpo,
cabeceras y el `url` de `LOCAL`.

**Los logs quedan fuera de esa lista, y es deliberado.** Una redacción anterior de este párrafo
incluía «logs de API» entre lo que R3.2 cubre de forma absoluta, y eso contradecía a D7d —que
acepta por escrito que la ruta registre la ruta absoluta en disco al reportar un
`StorageWriteError`— y al código, que sigue a D7d. Lo señaló el panel de seguridad de
`/sdd:review`: no era un incumplimiento, era **una contradicción dentro del texto normativo**, de
las que permiten citar la mitad estricta contra código que funciona. Se resuelve en favor de D7d:
R3.2 gobierna **respuestas de API**, no logs. Si algún día se decide ampliar la regla 11 de
`steering/security.md` a rutas internas en logs, será una decisión consciente y con su propio
diff, no la lectura accidental de una lista mal copiada.

**Por qué es aceptable hoy, y sólo hoy**: no hay bucket configurado, así que `storage_for` lanza
`StorageWriteError` → `502` antes de emitir ninguna URL (D2b y `BLOCKED.md` §4). La excepción es,
literalmente, código inalcanzable.

**Condición de cierre, y esto es lo que hay que registrar**: el día que se configure un bucket,
R3.2 pasa a incumplirse **en ese mismo commit y sin que ningún test lo detenga**. Así que la
entrada de aprovisionamiento (`BLOCKED.md` §4) hereda la obligación de decidir una de tres:
poner un CDN o una ruta propia delante del bucket, aceptar la exposición por escrito con su
razón, o servir también S3 por la ruta firmada propia. **No es una tarea de este change**, pero
tampoco puede llegar como sorpresa.

Rechazada: **servir S3 por nuestra ruta ahora** — anula el motivo de usar presigned URLs (que el
navegador vaya directo al proveedor) y mete todo el tráfico de fotos por el backend, por un
riesgo que hoy no existe.

### D7d — Riesgos de la ruta anónima que se aceptan por escrito

Ninguno viola una regla dura; los tres son **superficie nueva que hay que nombrar**, y el panel
de la sección 4 tenía razón en que no estaban escritos en ninguna parte:

- **Sin límite de tasa.** La ruta hace un `SELECT` con `JOIN` por petición, sin credencial, desde
  internet. La regla 7 de `steering/security.md` acota el rate limiting a `Auth` y la 12 a
  webhooks, así que no hay regla que aplicar. La enumeración es inútil —`403` constante sobre un
  espacio de 122 bits— y lo que queda es coste de base de datos. Se acepta con el mismo criterio
  que los 10 MiB anónimos de la subida; si alguna vez se pone límite de tasa en el borde, es
  decisión de infraestructura y no de este change.
- **Residuo de temporización entre ramas de error.** Una foto inexistente falla en el `locate` y
  **no llega a calcular el HMAC**, así que "no existe" y "existe con firma mala" difieren en
  microsegundos. Ni R3.4 ni R3.5 exigen tiempo constante *entre* ramas —sólo en la comparación de
  la firma— y explotarlo pide medir microsegundos por internet sobre 122 bits por candidato. Está
  documentado en el propio caso de uso y se acepta.
- **La ruta escribe en los logs la ruta absoluta en disco** al registrar un `StorageWriteError`.
  R3.2 habla de respuestas de API, no de logs, y no hay regla de steering sobre rutas internas en
  logs — así que es dato, no incumplimiento. Se nombra aquí para que la decisión de ampliar la
  regla 11 a este caso sea consciente si algún día se toma.

### D7e — Catálogo cerrado de asimetrías entre `LOCAL` y `S3`

`steering/backend-architecture.md` §SOLID-L exige que dos implementaciones de un puerto sean
*«100% intercambiables — mismas excepciones, misma forma de retorno, mismas precondiciones»*. Este
change tiene un puerto con dos implementaciones y **no** son intercambiables al 100%. Dos de las
diferencias estaban razonadas sólo en el docstring del adaptador, que es el sitio donde no las lee
quien revisa el diseño; el panel de `/sdd:review` las sacó. Se recogen aquí para que la lista sea
**cerrada**: cualquier asimetría que no esté en ella es un defecto, no una decisión.

1. **La clave viaja dentro de la URL en `S3` y no en `LOCAL`** — D7c, con su condición de cierre.
2. **El `Content-Type` lo sirve el proveedor en `S3` y `content_type_for_extension` en `LOCAL`** —
   D7, resuelto derivando ambos de la misma allowlist.
3. **`signed_url` devuelve una URL relativa al origen en `LOCAL` y absoluta en `S3`.** Es
   deliberado y no tiene arreglo mejor: la aplicación **no conoce el origen público desde el que
   la sirven** —túnel de Cloudflare en dev, puerto pelado en local— e inventárselo produciría URLs
   que sólo funcionan en un entorno. El navegador resuelve la relativa contra la página en la que
   está, que es donde ya vive la API. Consecuencia para el consumidor, y es la parte que había que
   escribir: el campo `url` de la respuesta **no garantiza ser absoluto**, así que un cliente que
   lo concatene a un origen propio se romperá el día que un tenant pase a `S3`. Un `<img src>` —el
   único consumidor previsto, y el motivo de que la ruta sea anónima— funciona con las dos formas
   sin tocar nada.
4. **Las precondiciones sobre la clave sólo las verifica `LOCAL`.** `LocalFileStorage` rechaza con
   `StorageWriteError` una clave vacía, con NUL o que se escape de la raíz, en `put`/`delete`/`read`
   (tarea 1.4) pero **no** en `signed_url`, que no resuelve ruta; `S3FileStorage` no valida ninguna.
   Así que la misma clave inválida es `502` en `LOCAL` y una URL firmada de aspecto normal en `S3`.
   **Hoy es inalcanzable**: la única productora de claves es `storage_key_for_photo`, y la tarea 3.4
   fija que ningún caso de uso acepta ni reenvía una clave venida del cliente. Se acepta como riesgo
   residual y no se cierra aquí porque cerrarlo bien es mover la precondición al contrato del puerto
   y aplicarla en un guardián compartido — superficie que este change no necesita. Si aparece un
   segundo productor de claves (`maintenance`, `revenue` — D2), **esto deja de ser teórico** y es lo
   primero que hay que hacer.

### D8 — La tercera cláusula de PRD §11 se aplica dentro de la entidad, extendiendo la evidencia

**Chosen:** `CleaningCompletionEvidence` gana `required_photo_types` y `uploaded_photo_types`
(ambos `frozenset[str]`) y un `missing_required_photo_types()` ordenado, espejo exacto del que ya
existe para ítems. `CleaningTask.complete()` lanza `PhotosIncompleteError` con la tupla. La regla
sigue teniendo **un solo sitio** (R4.3), y el caso de uso sigue siendo quien lee: pide al nuevo
`CleaningPhotoRepository` los `photo_type` distintos de la tarea.

Rechazada: comprobarlo en el caso de uso o en el router — partiría en dos la invariante que
`cleaning` deliberadamente concentró en la entidad.

### D9 — Sin migración de Alembic

**Chosen:** ninguna. `cleaning_photos` ya existe con `id`, `cleaning_task_id`, `uploaded_by`,
`photo_type`, `storage_key`, `ai_validation_result` y `created_at`, y con su `INDEX(cleaning_task_id)`
(`alembic/versions/a1a72da30f8e_domain_foundation_ops.py:181,193`). Este change es el **primer
escritor** de una tabla que se creó completa. Que no haya migración es un resultado, no un olvido:
si aparece una, es señal de que algo se ha salido del diseño.

Rechazada: `UNIQUE(cleaning_task_id, photo_type)` — R2.6 admite varias fotos del mismo tipo a
propósito (una limpiadora fotografía dos ángulos del baño), y el cierre exige «al menos una por
tipo requerido», no «exactamente una».

### D10 — Una rama más en el `max_bytes_provider`, antes de la de `/cleaning-`

**Chosen:** añadir en `backend/app/main.py` una rama que case `/cleaning-tasks/` **y** termine en
`/photos`, devolviendo `settings.photo_upload_max_bytes` (nuevo, default 10 MB, mismo patrón que
`csv_import_max_bytes`). Va **antes** de la rama `/cleaning-`, porque el orden del `if/elif` es lo
que decide. El comentario de `main.py:105-111` ya anticipa esta reparación exacta.

Rechazada: subir `JSON_BODY_MAX_BYTES` — quita el techo JSON a **todas** las rutas de limpieza y
reabre el agujero medido en `cleaning` (un `POST` anónimo de ~50 MB leído entero antes del `401`).

### D11 — El tope se comprueba dos veces: en el middleware y durante el streaming

**Chosen:** el middleware corta por `Content-Length` y por bytes acumulados; **además**, el caso de
uso consume el `UploadFile` en trozos contando bytes y aborta al superar el tope.

**Corrección de la justificación, tras el panel de `/sdd:review`.** La primera redacción de esta
decisión decía que la segunda comprobación es la que protege de un `Content-Length` mentido o de un
`Transfer-Encoding: chunked`. **Eso es falso**, y el comentario que lo repetía dentro del código ya
se corrigió en la sección 3; lo que quedaba sin corregir era este documento. El motivo es mecánico:
FastAPI llama a `await request.form()` **antes** de resolver las dependencias, y el parser multipart
de Starlette vuelca la parte del fichero a un `SpooledTemporaryFile` sin techo propio — así que
cuando el bucle del caso de uso pide su primer trozo, el fichero ya se recibió entero y se escribió
en disco. Contarlo después no lo des-recibe.

Quien cumple R2.5 («rechazar antes de leer el cuerpo completo») es el **contador acumulativo del
middleware**, y sólo él. Las dos comprobaciones siguen en pie porque la segunda compra otras dos
cosas, y son las que hay que citar si alguien se plantea quitarla:

- acota la **copia en memoria** del proceso al tope más un trozo, sea cual sea el tamaño del
  fichero volcado a disco;
- es el único techo para cualquier cableado que no tenga el middleware delante — una llamada
  directa desde un test, un worker o un futuro consumidor no-HTTP del caso de uso.

Es defensa en profundidad **detrás** de la garantía, no una segunda aplicación de la misma. Y por
la misma razón, tampoco vale el movimiento inverso: quitar el contador del middleware alegando que
el caso de uso ya cuenta dejaría a un llamante anónimo volcando a disco lo que quisiera antes de
que la autenticación llegue a correr. La justificación completa vive junto al código, en el
docstring de `_read_within_limit` (`backend/app/cleaning/application/use_cases.py`).

### D12 — El aislamiento se demuestra en el repositorio, no se hereda

**Chosen:** `SqlAlchemyCleaningPhotoRepository` hace **siempre** `JOIN cleaning_tasks` y filtra por
el tenant de la sesión; ninguna consulta parte de `cleaning_photos` a secas. `cleaning_photos` no
tiene columna `tenant_id` y `tenant_scoped_classes()` (`backend/app/core/db.py:62`) selecciona por
columna, así que el filtro global **no la cubre** — igual que pasa con
`cleaning_checklist_completions`, cuyo tratamiento en `cleaning` es el precedente a copiar
(`specs/cleaning.md` §Aislamiento). Tests propios de cruce de tenant para subida, listado y URL
firmada (R6.2).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Puertos de almacenamiento | `backend/app/integrations/domain/storage.py` *(nuevo)* | `FileStoragePort` (`put`/`signed_url`/`delete`), `LocalFileReadPort`, factory por `storage_type`, `LocalFileReadUnsupportedError` |
| Adaptadores | `backend/app/integrations/infrastructure/storage/{__init__,local,s3}.py` *(nuevos)* | `LocalFileStorage` sobre `/app/media/` + firma HMAC; `S3FileStorage` con presigned URL |
| Detección de tipo | `backend/app/integrations/domain/storage.py` | Allowlist de *magic bytes* (D5) |
| Dominio de limpieza | `backend/app/cleaning/domain/value_objects.py` | `CleaningCompletionEvidence` + `required_photo_types`, `uploaded_photo_types`, `missing_required_photo_types()` |
| | `backend/app/cleaning/domain/entities.py` | `complete()` aplica la tercera cláusula |
| | `backend/app/cleaning/domain/exceptions.py` | `PhotosIncompleteError` |
| | `backend/app/cleaning/domain/repositories.py` | `CleaningPhotoRepository` (Protocol) |
| Aplicación | `backend/app/cleaning/application/use_cases.py` | `UploadCleaningPhotoUseCase`, `ListCleaningPhotosUseCase`, `ServeLocalCleaningPhotoUseCase`; `CompleteCleaningTaskUseCase` pasa la evidencia nueva |
| Infraestructura | `backend/app/cleaning/infrastructure/repositories.py` | `SqlAlchemyCleaningPhotoRepository` con `JOIN` obligatorio (D12) |
| API | `backend/app/cleaning/api/tasks_router.py` | `POST`/`GET /cleaning-tasks/{id}/photos` |
| | `backend/app/cleaning/api/photos_router.py` *(nuevo)* | `GET /cleaning-photos/{photo_id}` anónimo firmado (D7) |
| | `backend/app/cleaning/api/{schemas,dependencies,errors}.py` | DTOs, DI de los tres casos de uso, mapeo de `PhotosIncompleteError` → 409. **El 403 de firma NO va aquí** — ver la nota bajo la tabla |
| Config y arranque | `backend/app/core/config.py`, `backend/app/main.py` | `photo_upload_max_bytes`; rama del middleware (D10); montaje del router nuevo |
| Compose | `docker-compose.yml`, `docker-compose.deploy.yml` | Volumen para `/app/media/` en backend |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerar ambos (`steering/documentation.md`) |
| Tests | `backend/tests/cleaning/`, `backend/tests/integrations/` | Unit de dominio, casos de uso con fakes, integración de rutas, cruce de tenant, firma |

**Dónde vive el 403 de firma, y por qué no en `errors.py`.** La fila de arriba decía «y de firma
inválida → 403», y era una trampa: el patrón de la casa en `cleaning/api/errors.py` mapea con
`message = str(exc)`, e `InvalidSignatureError` tiene tres mensajes distintos («does not match» /
«has expired» / «outlives the maximum lifetime») cuando su contrato entero es la
indistinguibilidad. Seguir el patrón ahí convertiría la ruta anónima en un **oráculo de existencia
sobre el espacio de claves** para un atacante sin credenciales. El cuerpo del 403 es por eso una
**constante precomputada en `photos_router.py`**, y los tres mensajes se conservan sólo para el
log. Es lo que fija la tarea 4.3b; la fila de la tabla quedó desactualizada y se corrige aquí para
que nadie «arregle» la inconsistencia moviéndolo de vuelta.

## Data & interfaces

**Esquema**: sin cambios (D9). Ninguna migración.

**Endpoints nuevos**

| Método | Ruta | Auth | Respuesta |
|---|---|---|---|
| `POST` | `/api/v1/cleaning-tasks/{id}/photos` | JWT · `EXECUTE_CLEANING_TASKS` (CLEANER asignada) | `201` con la foto y su URL firmada |
| `GET` | `/api/v1/cleaning-tasks/{id}/photos` | JWT · CLEANER asignada u `MANAGE_CLEANING_TASKS` | `200` con lista + URLs firmadas |
| `GET` | `/api/v1/cleaning-photos/{photo_id}?exp=&sig=` | **anónimo**, firma (D7) | `200` bytes · `403` firma inválida/caducada |

`storage_key` **no aparece en ninguna respuesta** (R3.2).

**Config nueva**: `PHOTO_UPLOAD_MAX_BYTES` (default `10485760`) en `.env.example`. Ningún secreto
nuevo (D6). `/app/media/` como volumen con nombre en compose.

**Errores** (envelope PRD §23): `409` con `missing_photo_types` al cerrar sin fotos · `413`
sobre tamaño · `422` MIME no admitido · `404` `photo_type` desconocido o tarea de otro tenant ·
`403` firma · `502` fallo del almacén.

## Risks & mitigations

- **Ruta pública anónima nueva** (D7) — el mayor riesgo del change. Mitigado por firma HMAC con
  clave derivada, caducidad 3600 s, comparación en tiempo constante y `403` uniforme. Entra de
  lleno en los *triggers* de revisión extra de `steering/security.md` («exposición de storage»),
  así que el panel de seguridad debe mirarla explícitamente.
- **Objetos huérfanos** cuando falla el commit (D4) — aceptado y nombrado; el borrado
  compensatorio cubre el caso normal y lo que quede es basura sin referencia.
- **`/app/media/` es efímero si no se monta volumen** — un `docker compose down -v` se lleva las
  fotos. Es dev, pero hay que dejarlo escrito en `docs/cleaning.md`, no descubrirlo.
- **HEIC fuera** (D5) — si las limpiadoras usan iPhone, `field-apps` se encontrará con subidas
  rechazadas. Q1.
- **`S3FileStorage` no se puede validar de verdad** sin credenciales — `EXTERNAL_DEPENDENCY`. Se
  prueba contra el contrato y con la sustituibilidad que exige SOLID-L, no contra AWS.
- **Un test de tamaño que pase por casualidad**: R5.2 exige un test que falle si alguien sube
  `JSON_BODY_MAX_BYTES` globalmente — hay que escribirlo en rojo primero.

## Open questions

- **Q1 — ¿HEIC/HEIF admitido?** D5 deja fuera el formato nativo de la cámara de iPhone. Admitirlo
  significa magic bytes de `ftyp` + decidir si se transcodifica (dependencia pesada) o se sirve
  tal cual (Chrome/Firefox no lo pintan). Recomendación: **no ahora**, y que `field-apps` fuerce
  captura en JPEG; revisar si el hardware real de las limpiadoras lo desmiente.
- **Q2 — ¿Clave de firma derivada o secreto propio?** D6 deriva de `JWT_SECRET_KEY` por HKDF para
  no tocar Terraform/Vault/compose. Un `MEDIA_SIGNING_KEY` propio es más ortodoxo y permite
  rotarlo sin invalidar sesiones. Recomendación: **derivada ahora**, con el prefijo `v1|` que deja
  la puerta abierta.
- **Q3 — ¿`sdd/specs/file-storage.md` propio, o dentro de `cleaning.md`?** El puerto es compartido
  (D2) y tendrá dos consumidores más. Recomendación: **spec propia al archivar**; se decide en
  `/sdd:archive`, no bloquea la implementación.
