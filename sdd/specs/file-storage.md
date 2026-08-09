# Almacenamiento de ficheros

## Purpose

Guarda fuera de la base de datos los ficheros que sube la aplicación y los devuelve por URL
firmada de caducidad acotada, sin que ningún caso de uso sepa dónde acaban. Es una capability
**compartida**: hoy su único llamante son las fotos de limpieza
([`specs/cleaning.md`](cleaning.md)), y `maintenance` (fotos de incidente) y `revenue`
(`expenses.receipt_storage_key`) están nombrados como sus siguientes consumidores, que es la
razón de que viva en `app/integrations/` y no colgando del dominio que la estrenó.

Cubre el puerto, sus dos implementaciones (`LOCAL` y `S3`), el esquema de claves, la detección
del tipo real del contenido y el esquema de firma. **Lo que no cubre**: qué rutas HTTP existen
sobre él ni quién puede llamarlas — eso pertenece a la capability que lo consume.

## Requirements

### El puerto, y por qué son dos

- THE SYSTEM SHALL declarar el puerto de escritura en la capa de dominio con **tres** métodos —
  `put`, `signed_url` y `delete`— y cada uno SHALL tener un llamante real: la subida usa `put` y
  `signed_url`, y el borrado compensatorio de una transacción fallida usa `delete`. Un método sin
  consumidor es el fallo de segregación que `steering/backend-architecture.md` nombra con su
  ejemplo del «`StorageAdapter` gigante con 15 métodos».
- THE SYSTEM SHALL declarar la lectura de bytes a través de la aplicación como un puerto
  **separado**, `LocalFileReadPort`, que solo implementa el adaptador `LOCAL`. Con `S3` el
  navegador va directo al proveedor con su URL prefirmada, así que un `read` en el puerto común
  tendría un implementador cuyo único cuerpo posible es `raise NotImplementedError` — la
  violación de sustituibilidad que el steering prohíbe por su nombre y que ADR 0006 decisión 3 ya
  rechazó una vez para el PMS.
- THE SYSTEM SHALL declarar `signed_url` **síncrono**: las dos implementaciones calculan una firma
  local y ninguna abre red, así que declararlo `async` prometería una frontera de I/O inexistente.
- THE SYSTEM SHALL ejecutar todo I/O bloqueante —disco en `LOCAL`, boto3 en `S3`— fuera del bucle
  de eventos, por `anyio.to_thread`.
- THE SYSTEM SHALL mantener `domain/` libre de dependencias de infraestructura: los puertos, la
  allowlist de formatos, el esquema de claves y las primitivas de firma son **funciones puras**
  sin reloj, disco ni red, y `verify_signed_key` recibe `now` como argumento por esa razón.

### Resolución por tenant

- THE SYSTEM SHALL resolver la implementación a partir de `TenantConfig.storage_type` (enum
  `LOCAL`/`S3`), a través de una factoría, sin que ningún caso de uso conozca cuál está activa:
  los casos de uso dependen del puerto de factoría y nunca de un adaptador concreto.
- THE SYSTEM SHALL declarar el puerto de la factoría en `domain/` y su implementación en
  `infrastructure/`, porque resolver exige importar los adaptadores concretos y `test_layering.py`
  falla si `domain/` importa `infrastructure/`. Es el mismo reparto que `PMSAdapterFactory`.
- WHEN se pide el puerto de lectura local para un tenant cuyo `storage_type` no es `LOCAL`, THE
  SYSTEM SHALL rechazarlo con `LocalFileReadUnsupportedError` **antes de instanciar nada** — ni
  cliente de boto3 ni ruta de disco—, porque la respuesta es una propiedad del tipo de
  almacenamiento y no un fallo transitorio. Es el mecanismo de `PMSAdapterFactory.messaging_for`.
- THE SYSTEM SHALL no cachear adaptadores ni retener sesión en la factoría: un objeto que
  arrastrase el estado de un tenant a la resolución de otro es exactamente el fallo que las
  guardas de tenant existen para atrapar.
- IF `storage_type` es `S3` y el despliegue no tiene bucket configurado, THEN THE SYSTEM SHALL
  fallar con `StorageWriteError` y **nunca** caer silenciosamente a `LOCAL`: escribir las fotos de
  ese tenant a un disco desde el que nadie las sirve parecería un éxito y lo descubriría la
  primera persona que abriera una.
- THE SYSTEM SHALL exponer `storage_type` como configuración de **solo lectura**: el `PATCH` de
  `TenantConfig` sigue sin admitirlo (R5.4 de [`user-management`](user-management.md)), porque
  cambiarlo apuntaría a ficheros ya subidos a un sitio donde no están.

### Claves de almacenamiento

- THE SYSTEM SHALL derivar la clave de una foto de limpieza como
  `tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{ext}`, con el `tenant_id` **delante**,
  de modo que dos tenants no puedan colisionar en el mismo objeto —ni por colisión de UUID de
  tarea ni por `photo_type` repetido— y un prefijo del almacén sea directamente acotable por
  tenant.
- THE SYSTEM SHALL construir la clave únicamente a partir de identificadores que el propio sistema
  generó. **El nombre de fichero que envía el cliente no toca la clave en ningún punto**: es
  entrada no confiable, sanearlo sería una lista negra de fragmentos de ruta, y el nombre original
  no se muestra en ninguna parte.
- THE SYSTEM SHALL derivar la extensión del **MIME detectado** y rechazar con `ValueError` una
  extensión que la allowlist no declare: cualquier otra solo puede venir de un llamante que se la
  inventó.
- WHERE el almacenamiento es `LOCAL`, THE SYSTEM SHALL comprobar que la ruta **resuelta** de una
  clave sigue dentro de la raíz antes de tocar disco, y rechazar con `StorageWriteError` una clave
  vacía, con bytes NUL o que se escape de la raíz. La comprobación es sobre el resultado de
  resolver y no sobre la entrada: rechazar `..` no cubre una clave absoluta —`Path("/app/media") /
  "/etc/passwd"` es `/etc/passwd`— ni un symlink que `resolve()` sigue fuera del árbol.

### Detección del tipo de contenido

- THE SYSTEM SHALL decidir el formato leyendo los **primeros bytes del contenido** contra una
  allowlist corta —JPEG, PNG y WebP—, ignorando por completo el `Content-Type` que declara el
  cliente (regla 6 de `steering/security.md`).
- THE SYSTEM SHALL mantener la allowlist en **una sola constante**, y derivar de ella tanto la
  cantidad de bytes que hay que leer para decidir como la tabla extensión → MIME. Una segunda
  tabla escrita a mano sería una segunda fuente de verdad, y el día que la allowlist creciera una
  línea las dos discreparían con la mitad que habla con el navegador sosteniendo la versión vieja.
- IF el contenido no es ninguno de los formatos admitidos —incluido un fichero vacío o más corto
  que la firma—, THEN THE SYSTEM SHALL devolverlo como «no reconocido» y no como un fallo: es una
  respuesta que el llamante convierte en `422`.
- THE SYSTEM SHALL derivar el `Content-Type` con el que se sirve un objeto **únicamente** de la
  extensión de su clave y de esa misma allowlist. El MIME detectado en la subida no se persiste en
  ninguna columna, así que esta es la única forma honesta de responder; dejar que el servidor
  adivine convertiría un polyglot que empieza por `FF D8 FF` y lleva HTML en **XSS almacenado
  sobre el origen de la API**.
- IF la extensión de una clave no está en la allowlist, THEN THE SYSTEM SHALL lanzar `ValueError`
  en lugar de devolver un valor por defecto: solo puede venir de una clave que este sistema
  construyó, es decir de un bug, y un valor por defecto invitaría a la ruta de servido a caer en
  el sniffing que esta función existe para impedir.

**Consecuencia con nombre: HEIC/HEIF queda fuera**, y es el formato nativo de la cámara de iPhone
(decisión Q1 de `cleaning-photos-storage`). Admitirlo obliga a elegir entre transcodificar en el
backend —dependencia pesada— o servirlo tal cual, que Chrome y Firefox no pintan. Es una decisión
de producto, y ampliar la allowlist es una línea el día que se tome.

### URL firmadas

- THE SYSTEM SHALL entregar todo objeto por URL firmada de caducidad **acotada a 3600 s** (regla 5
  de `steering/security.md`), nunca como ruta interna.
- THE SYSTEM SHALL tratar los 3600 s como un **techo y no como un argumento por defecto**:
  aplicado al firmar, y aplicado otra vez al verificar rechazando toda `expiry` que se aleje del
  instante actual más que el techo. La segunda mitad es la que importa — es la que invalida una
  URL excesiva aunque algo consiguiera firmarla.
- WHEN se pide una caducidad mayor que el techo, THE SYSTEM SHALL recortarla en silencio en lugar
  de fallar: no hay nada que el llamante pueda decidir, y convertir una política en un error
  dejaría sin funcionar la ruta cuyo trabajo entero es repartir URLs. IF la caducidad pedida no es
  positiva, THEN THE SYSTEM SHALL rechazarla, porque acuñaría una URL muerta en el instante de
  nacer y no hay intención que inventar.
- THE SYSTEM SHALL derivar la clave de firma de `JWT_SECRET_KEY` por HKDF-SHA256 con una etiqueta
  de separación de dominio, y **no** reutilizar el secreto en crudo: firmar una URL nunca puede
  producir ni verificar un JWT. No hay secreto nuevo que aprovisionar en Terraform, en el vault,
  en el compose ni en `.env.example`.
- THE SYSTEM SHALL firmar un mensaje versionado que cubre la clave **completa** —que empieza por
  el `tenant_id`— y la caducidad, con la longitud de la clave prefijada para que la codificación
  sea inequívoca **por construcción** y no por disciplina del llamante. Así una firma válida no se
  puede pivotar a otro objeto, a otro tenant ni a un plazo posterior.
- THE SYSTEM SHALL mantener el prefijo de versión **dentro** de la firma, de modo que subirlo
  invalide por construcción toda URL emitida bajo el esquema anterior y rotar el esquema sea una
  decisión y no una sorpresa.
- THE SYSTEM SHALL comparar la firma en **tiempo constante**, comparando bytes y no `str`: una
  comparación byte a byte filtra la posición del primer carácter erróneo, y `compare_digest`
  lanza `TypeError` sobre un `str` no-ASCII, que llega desde una query string.
- THE SYSTEM SHALL señalar firma incorrecta, caducada y excesiva con **un solo tipo de error**:
  distinguirlas aquí invitaría a distinguirlas en la ruta que las sirve y la convertiría en un
  oráculo de existencia sobre el espacio de claves.
- THE SYSTEM SHALL devolver de la verificación `None` en caso de éxito y no un booleano: un
  booleano invita a escribir la llamada sin el `if`, y una verificación cuyo resultado se puede
  ignorar no lo es.

### El adaptador `LOCAL`

- THE SYSTEM SHALL persistir bajo `/app/media/` (PRD §4 §Almacenamiento de archivos), montado como
  volumen con nombre y **no** dentro del árbol de código: `/app` es el repositorio por bind mount,
  así que sin el volumen las fotos aparecerían en `git status`.
- THE SYSTEM SHALL fijar esa raíz como constante de módulo y no como ajuste de despliegue: un
  despliegue que pudiera apuntarla a otro sitio podría apuntarla al árbol de código.
- THE SYSTEM SHALL escribir a un fichero temporal vecino y renombrarlo con `os.replace`, que es
  atómico dentro de un sistema de ficheros: sin eso una caída a mitad de escritura dejaría un
  objeto truncado al que apuntaría la fila insertada después.
- THE SYSTEM SHALL emitir una URL **relativa** al origen, con solo el identificador del objeto, su
  caducidad y la firma. La aplicación no conoce el origen público desde el que la sirven —túnel de
  Cloudflare en dev, puerto pelado en local— e inventárselo produciría URLs que funcionan en un
  solo entorno.
- THE SYSTEM SHALL tratar el borrado de un objeto inexistente como éxito: su llamante es el
  borrado compensatorio de una transacción fallida, y esa vía no puede fallar por segunda vez de
  salida.

### El adaptador `S3`

- THE SYSTEM SHALL entender `S3` como el **protocolo** y no como AWS: el proveedor no está
  decidido y el PRD lo deja abierto explícitamente («S3-compatible: Cloudflare R2 o AWS S3»). El
  candidato natural del proyecto es OCI Object Storage, donde ya corre la VM de dev (ADR 0001).
- THE SYSTEM SHALL mantener las dos costuras que hacen que eso no sea una frase vacía: el
  constructor del cliente acepta un `endpoint_url` arbitrario, y el adaptador **recibe** el
  cliente inyectado en lugar de construirlo. Apuntar a otro almacén compatible es configuración,
  no un cambio de código.
- THE SYSTEM SHALL conservar el nombre `S3FileStorage` espejando el valor del enum
  `StorageType.S3`: renombrarlo desalinearía el código de la columna.
- THE SYSTEM SHALL tomar las credenciales de la cadena estándar del proveedor (entorno, rol de
  instancia) y no de ajustes versionados (regla 8 de `steering/security.md`).
- THE SYSTEM SHALL etiquetar el objeto con el MIME **detectado** al escribirlo: sin él el almacén
  sirve `binary/octet-stream` y el navegador descarga la foto en vez de mostrarla.
- THE SYSTEM SHALL firmar con SigV4 fijado en el cliente, para que una URL acuñada en una máquina
  verifique en cualquier otra.
- THE SYSTEM SHALL traducir todo fallo de botocore a `StorageWriteError`, el mismo error que emite
  `LOCAL` para la misma clase de fallo: la sustituibilidad que exige SOLID-L es un requisito, y un
  caso de uso probado contra un adaptador debe comportarse igual contra el otro.

### Catálogo cerrado de asimetrías entre `LOCAL` y `S3`

`steering/backend-architecture.md` §SOLID-L exige dos implementaciones intercambiables al 100 %.
Estas cuatro no lo son, están decididas y **la lista es cerrada**: cualquier asimetría que no esté
aquí es un defecto, no una decisión.

- WHERE el almacenamiento es `S3`, THE SYSTEM SHALL emitir una URL prefirmada que **contiene el
  bucket y la clave completa**, porque es parte del protocolo de firma y no se puede retirar. La
  prohibición de exponer la clave interna sigue siendo absoluta para todo lo demás —cuerpo,
  cabeceras y la URL de `LOCAL`— y **no alcanza a los logs**, que sí pueden registrar la ruta
  absoluta al reportar un fallo de escritura. Hoy es código inalcanzable: sin bucket configurado
  la resolución falla antes de emitir ninguna URL.
- THE SYSTEM SHALL servir el `Content-Type` desde el proveedor en `S3` y desde la tabla derivada
  de la allowlist en `LOCAL`, ambas alimentadas por la **misma** allowlist para que no puedan
  divergir.
- THE SYSTEM SHALL emitir una URL relativa al origen en `LOCAL` y absoluta en `S3`. Consecuencia
  para el consumidor: el campo `url` de una respuesta **no garantiza ser absoluto**, así que un
  cliente que lo concatene a un origen propio se romperá el día que un tenant pase a `S3`. Un
  `<img src>` funciona con las dos formas.
- THE SYSTEM SHALL verificar las precondiciones sobre la clave solo en `LOCAL` (en `put`, `delete`
  y `read`, no en `signed_url`, que no resuelve ruta); `S3` no valida ninguna. Hoy es inalcanzable
  porque la única productora de claves es la función del esquema y ningún caso de uso acepta ni
  reenvía una clave venida del cliente.

### Configuración y despliegue

- THE SYSTEM SHALL montar `/app/media` como volumen con nombre **solo en el servicio `backend`**,
  el único que escribe y sirve ficheros, tanto en el compose local como en el de despliegue.
  `worker` y `beat` no lo montan: ampliar el radio de escritura sin llamante no se hace.
- THE SYSTEM SHALL persistir ese volumen entre despliegues. Sin él `/app/media` viviría en la capa
  escribible del contenedor y cada despliegue —que lo reemplaza con la imagen nueva— se llevaría
  los ficheros.
- THE SYSTEM SHALL documentar que `docker compose down -v` borra el volumen, y por tanto todas las
  fotos subidas, en el README de la raíz y en `docs/cleaning.md`.

## Estado

- **No hay ningún almacén S3 aprovisionado**, y por tanto no hay bucket, endpoint ni región en la
  configuración: un tenant con `storage_type = S3` recibe hoy `502` en cada subida. Es deuda
  declarada, con entrada propia de roadmap (`object-storage-provisioning`), no un descuido.
  `EXTERNAL_DEPENDENCY`.
- **`S3FileStorage` no se valida contra un servicio real.** Lo que sí se valida es lo que importa
  y lo que unas credenciales no comprobarían mejor: el contrato del puerto y la sustituibilidad
  que exige SOLID-L, con un test que corre las mismas aserciones contra los dos adaptadores sobre
  un cliente de prueba que responde como botocore. `LOCAL` es lo que corre el MVP —el default de
  `TenantConfig.storage_type`—, que es por lo que basta.
- **Condición de cierre heredada por el aprovisionamiento**: el día que se configure un bucket, la
  exposición de la clave en la URL prefirmada pasa a ser real **en ese mismo commit y sin que
  ningún test lo detenga**. La entrada de roadmap hereda la obligación de decidir una de tres:
  poner un CDN o una ruta propia delante del bucket, aceptar la exposición por escrito con su
  razón, o servir también `S3` por la ruta firmada propia.
- **Residuo consciente del techo de caducidad**: se mide sobre `expiry - now`, así que una URL
  firmada con una caducidad muy lejana no es permanente pero **sí es válida durante su última
  hora**, en un instante futuro que elige quien la firmó. Cierra el riesgo grande —acceso anónimo
  perpetuo— y deja una URL «durmiente». Cerrarlo del todo pide un `iat` en el payload y acotar
  `expiry - iat`; no se hizo porque el único firmante es código propio, y queda escrito para que
  el día que un tercero pueda pedir una firma no se redescubra.
- **Rotación acoplada**: al derivarse la clave de firma de `JWT_SECRET_KEY`, no se puede rotar la
  firma de los ficheros sin invalidar todas las sesiones, ni al revés. El prefijo de versión del
  mensaje firmado deja abierta la migración a un `MEDIA_SIGNING_KEY` propio sin romper URLs vivas.
- **Sin borrado desde la API**: el puerto tiene `delete` y su único llamante es el borrado
  compensatorio interno. No hay superficie de borrado para un usuario, y no la habrá sin una
  decisión de retención.
- **Sin antivirus ni escaneo de contenido** de lo subido. Superficie propia, sin decisión previa.

## Key files

- `backend/app/integrations/domain/storage.py` — los tres puertos, la allowlist de formatos, el
  esquema de claves y las primitivas de firma. Todo lo que no es `Protocol` es función pura.
- `backend/app/integrations/infrastructure/storage/__init__.py` — `ConfiguredFileStorageFactory`,
  la resolución por `storage_type`.
- `backend/app/integrations/infrastructure/storage/local.py` — `LocalFileStorage`, la raíz
  `/app/media`, la escritura atómica y la resolución de rutas.
- `backend/app/integrations/infrastructure/storage/s3.py` — `S3FileStorage` y `build_s3_client`,
  con el `endpoint_url` que mantiene abierto el proveedor.
- `backend/app/tenants/domain/enums.py` — el enum `StorageType`, preexistente.
- `docker-compose.yml`, `docker-compose.deploy.yml` — el volumen `backend_media`.
- Tests: `backend/tests/integrations/test_storage_ports.py`, `test_storage_factory.py`,
  `test_storage_keys.py`, `test_storage_signing.py`, `test_image_detection.py`,
  `test_local_file_storage.py`, `test_s3_file_storage.py` (contrato compartido por ambos
  adaptadores).
