# Fotos de la incidencia

## Purpose

Da al técnico la **evidencia fotográfica de su trabajo**: la foto de llegada y la de cierre de una
incidencia de mantenimiento, con una entidad propia, dos rutas autenticadas colgadas de la
incidencia y una tercera anónima que sirve los bytes contra una firma para que un `<img src>`
funcione. Es «subir fotos (antes y después)» de PRD §6 y las dos peticiones de PRD §12 («fotos del
incidente», «subir fotos finales»).

Es el **segundo consumidor** del almacenamiento compartido de
[`file-storage`](file-storage.md) —y el que cobra la razón declarada de que esa capability viva en
`app/integrations/` y no colgando de `cleaning`—, así que **no decide** proveedor, esquema de
claves, detección de formato ni esquema de firma: eso está cerrado. Decide entidad, rutas, quién
puede llamarlas, y qué distingue una foto de llegada de una de cierre.

El código vive dentro de `app/maintenance/`: una foto de incidencia no es raíz de agregado, se carga
siempre a través de su incidencia y su acotamiento por fila es el de
[`maintenance`](maintenance.md) R8. La spec es propia porque describe una capability, no un
directorio. El *cómo se opera* está en [`docs/maintenance.md`](../../docs/maintenance.md).

## Requirements

### La entidad, y las dos cosas que el esquema hace imposibles

- THE SYSTEM SHALL persistir `IncidentPhoto` en la tabla `incident_photos` con **exactamente siete**
  columnas: `id` (UUID PK), `tenant_id`, `incident_id`, `uploaded_by`, `stage`, `storage_key`
  (`String(500)`) y `created_at` (`TIMESTAMPTZ`).
- `ASSUMPTION`: **la entidad no está en el PRD.** PRD §7.13 `Incident` no declara columna de fotos y
  PRD §7 solo define `CleaningPhoto` (§7.12). THE SYSTEM SHALL llevar la marca `ASSUMPTION` literal
  en los tres sitios donde se declara —el enum, la entidad de dominio y el modelo—, igual que
  `cleaning` registró la desviación de sus plantillas.
- THE SYSTEM SHALL llevar `tenant_id` en la **propia fila** vía `TenantScopedMixin`, y no derivarlo
  por la incidencia. Eso es lo que mete la tabla en `tenant_scoped_classes()` —o sea bajo el filtro
  global de `app/core/db.py`— y lo que permite su test de aislamiento propio sin depender de la
  incidencia. Es una **desviación deliberada** del precedente: `cleaning_photos` no tiene la columna
  y su aislamiento se demuestra por la tarea; esa ausencia es histórica, no diseñada.
- THE SYSTEM SHALL declarar la pertenencia a la incidencia con una **clave ajena compuesta**,
  `fk_incident_photos_incident_within_tenant` sobre `(tenant_id, incident_id) →
  (incidents.tenant_id, incidents.id)` con `ON DELETE RESTRICT`, y NEVER SHALL declarar una clave
  ajena simple sobre `incident_id`. Con dos claves ajenas independientes una fila que empareja el
  tenant A con una incidencia del tenant B **es legal**, y eso es exactamente lo que los paneles de
  `guest-portal-api` reprodujeron: la compuesta convierte «el tenant de la foto y el de su
  incidencia no pueden divergir» en un invariante del esquema en vez de disciplina del repositorio.
- THE SYSTEM SHALL sostener esa clave ajena con `UniqueConstraint("tenant_id", "id",
  name="uq_incidents_tenant_id_id")` sobre `incidents`, el mismo par que `reservations` ya tiene
  para que `guest_access_tokens` pueda apuntarla. NEVER SHALL cambiar ninguna columna de `incidents`
  por esta causa. El índice único no puede fallar por duplicados preexistentes porque `id` ya es
  clave primaria.
- THE SYSTEM SHALL crear la tabla, el tipo `incident_photo_stage` y el `UNIQUE` sobre `incidents` en
  la revisión de Alembic `d4a7e18c6b93` (sobre `c8e1f4a92b70`), y su `downgrade` SHALL deshacer las
  cuatro cosas —los dos índices, la tabla, el tipo enum y la restricción única—, de modo que la
  revisión sea reversible sobre una base con filas.
- THE SYSTEM SHALL indexar `(tenant_id, incident_id)` como `ix_incident_photos_tenant_id_incident_id`
  —el listado es siempre por incidencia dentro de un tenant— además del índice de `tenant_id` que
  aporta el mixin.
- THE SYSTEM SHALL admitir **varias fotos de la misma etapa** en una misma incidencia y NEVER SHALL
  declarar restricción de unicidad sobre `(incident_id, stage)`: un técnico fotografía dos ángulos
  de la misma avería. La ausencia está escrita como comentario en `__table_args__` para que sea una
  decisión visible y no un olvido.
- THE SYSTEM SHALL NOT declarar `updated_at`, y esa es una desviación consciente de
  `steering/backend.md`: la fila es **inmutable tras el insert** —el puerto declara `add` y
  `list_for_incident`, sin `save`—, así que la columna solo podría igualar a `created_at` para
  siempre e invitaría a leerla como prueba de una edición que no puede ocurrir. `cleaning_photos` la
  omite por lo mismo.
- THE SYSTEM SHALL escribir `created_at` desde el caso de uso y NEVER SHALL darle `server_default`:
  el orden de subida es parte del contrato del listado y tiene que salir del reloj del caso de uso,
  el mismo que audita.
- THE SYSTEM SHALL NOT persistir el `Content-Type` detectado, el nombre de fichero que envía el
  cliente ni `ai_validation_result` en ninguna columna. El `Content-Type` de servido se deriva de la
  extensión de la clave y el nombre del cliente no toca la clave en ningún punto.

### La etapa es un enum cerrado de dos valores, y eso es estructural

- THE SYSTEM SHALL declarar `stage` como `IncidentPhotoStage(str, enum.Enum)` con **exactamente
  dos** miembros, `BEFORE` y `AFTER`, mapeado como enum **nativo** de Postgres
  (`Enum(IncidentPhotoStage, name="incident_photo_stage", native_enum=True)`), como los demás enums
  del módulo.
- THE SYSTEM NEVER SHALL admitir un tercer valor ni un campo de texto libre de tipo de foto. Es la
  **diferencia estructural** con `cleaning`: allí `photo_type` es `String(100)` porque la plantilla
  de la tarea acota los valores admisibles, y una incidencia **no tiene plantilla**. Un texto del
  llamante sería un sumidero nuevo de la regla 11 de `steering/security.md` sin pantalla que lo
  muestre y sin nada que lo cierre.
- WHEN la etapa recibida no es `BEFORE` ni `AFTER`, THE SYSTEM SHALL responder `422` y **no** `404`:
  la etapa llega como `Annotated[IncidentPhotoStage, Form()]`, así que FastAPI la rechaza antes de
  que el caso de uso exista. A diferencia del `photo_type` desconocido de limpieza —que contesta
  `404` desde una consulta a la plantilla—, aquí no hay ninguna fila cuya existencia se pueda
  filtrar, y por tanto el `404` sería la respuesta equivocada.
- THE SYSTEM SHALL derivar de este enum el hecho de que la capacidad **no añade fila al censo de
  sumideros** de la regla 11: no hay texto libre del llamante en ninguna de las tres rutas.

### Subir una foto

- WHEN el técnico asignado solicita `POST /api/v1/incidents/{incident_id}/photos` con
  `multipart/form-data` —`stage` y `file`—, THE SYSTEM SHALL almacenar el fichero por el puerto
  compartido, persistir la fila y responder `201` con la foto y su URL firmada.
- THE SYSTEM SHALL exigir `EXECUTE_INCIDENTS` (`ExecuteDep`) y NEVER SHALL crear permiso nuevo:
  `ROLE_PERMISSIONS` no se toca. Quedan por tanto autorizados el técnico —acotado a las incidencias
  que tiene asignadas— y el `PROPERTY_MANAGER`, que [`maintenance`](maintenance.md) R6 ya autoriza a
  conducir todo el ciclo del técnico «para desatascar», y nadie más. La propietaria **no** sube.
- THE SYSTEM SHALL montar las dos rutas autenticadas sobre el `incidents_router` existente, que ya
  declara `AUTHENTICATED_RESPONSES`, y SHALL resolver la incidencia con
  `_load_incident_in_scope(...)`, que es lo que hace indistinguibles sus `404`.
- THE SYSTEM NEVER SHALL permitir la subida a un técnico que no sea el asignado, y esa negativa
  SHALL ser indistinguible de «no existe»: la restricción se deriva de
  `IncidentActor.restrict_to_technician_id`, que es el **rol del token**, y NEVER SHALL aceptarse ni
  ensancharse desde la petición — no existe parámetro equivalente en la ruta.
- THE SYSTEM SHALL comprobar la puerta por estado **antes de leer un byte del cuerpo**: el orden del
  caso de uso es resolver la incidencia → `Incident.ensure_accepts_photo()` → leer. Un `409` por
  estado no consume el fichero.

### La puerta por estado vive en la entidad, y rechaza en tres

- THE SYSTEM SHALL admitir la subida únicamente con la incidencia en `IN_PROGRESS` o
  `WAITING_EXTERNAL_PARTS` (`PHOTO_ACCEPTING_INCIDENT_STATUSES`) — los dos estados en los que el
  trabajo del técnico está en curso.
- THE SYSTEM SHALL declarar la puerta como `Incident.ensure_accepts_photo()` en la **entidad**, que
  **no muta** y rechaza en el **mismo orden** que `_check_transition`, compartiendo con ella el
  helper privado de las dos primeras ramas para que ese orden tenga una sola casa:

  1. IF el estado es terminal (`RESOLVED`, `CANCELLED`), THEN `IncidentAlreadyClosedError`;
  2. IF el estado es `AWAITING_OWNER_APPROVAL`, THEN `IncidentBlockedByPendingApprovalError`;
  3. IF el estado es cualquier otro fuera del allowlist, THEN `InvalidIncidentTransitionError`
     («Cannot attach a photo to an incident in status …»).

- THE SYSTEM SHALL mapear las tres a `409 CONFLICT` con **mensajes distintos**, de modo que las tres
  negativas sean distinguibles entre sí sin clase de error nueva y sin tocar el contrato de errores
  del módulo. NEVER SHALL escribir nada en ninguna de las tres: ni fila ni objeto en el almacén.
- THE SYSTEM NEVER SHALL declarar una fila en `_TRANSITIONS` para esto: subir una foto no mueve el
  estado, y una tabla de transiciones con una no-transición dentro miente.

### Objeto primero, fila después, borrado compensatorio

- THE SYSTEM SHALL escribir el objeto por `FileStoragePort.put` **antes** de insertar la fila, y
  después insertar la fila y el `AuditLog` y comitear. Una fila que apunte a un objeto inexistente
  es un `GET` roto para siempre; un objeto sin fila es basura recuperable, y ese es el fallo barato.
- IF la escritura en el almacén falla (`StorageWriteError`), THEN THE SYSTEM SHALL responder `502`
  con código `BAD_GATEWAY` y NEVER SHALL dejar fila. No hay nada que compensar: aún no se había
  insertado nada.
- IF falla cualquier cosa **después** del `put` —el insert, la auditoría o el commit—, THEN THE
  SYSTEM SHALL borrar el objeto en *best effort* y volver a lanzar la excepción original. El borrado
  compensatorio SHALL tragarse su propio fallo y registrar la clave en el log
  (`maintenance.orphaned_incident_photo_object`). Que la clave viaje a **ese** log no contradice la
  prohibición de publicarla: esa regla gobierna respuestas de API, y el log es todo el procedimiento
  de recuperación que tiene un objeto huérfano.
- THE SYSTEM SHALL construir la clave como
  `tenants/{tenant_id}/incidents/{incident_id}/{photo_id}.{extension}`, con el segmento de colección
  `incidents` reflejando el prefijo de la ruta igual que `cleaning-tasks` refleja el suyo, y SHALL
  derivarla **solo** de identificadores que el propio sistema generó.
- THE SYSTEM SHALL decidir el formato por los **primeros bytes** del contenido contra la allowlist
  de [`file-storage`](file-storage.md), nunca por el `Content-Type` declarado (regla 6 de
  `steering/security.md`). IF el contenido no es una imagen de la allowlist, THEN SHALL responder
  `422`.
- THE SYSTEM SHALL derivar `uploaded_by` del token verificado y NEVER SHALL leerlo del cuerpo.

### Listar las fotos de una incidencia

- WHEN se solicita `GET /api/v1/incidents/{incident_id}/photos`, THE SYSTEM SHALL devolver las fotos
  de esa incidencia **de la más antigua a la más reciente** (`ORDER BY created_at, id`), cada una
  con su etapa y una URL firmada **acuñada para esa respuesta**.
- THE SYSTEM SHALL exigir `READ_INCIDENTS` (`ReadDep`) para listar —leer la evidencia es lo que
  hacen el manager y la propietaria, subirla es del técnico— y SHALL aplicar el **mismo**
  acotamiento por fila: WHERE el solicitante es `TECHNICIAN`, solo las fotos de incidencias que
  tiene asignadas.
- IF la incidencia no existe, o no es del tenant, o el solicitante es un técnico que no la tiene
  asignada, THEN THE SYSTEM SHALL responder `404` con el **mismo cuerpo** en los tres casos.
- THE SYSTEM SHALL devolver `IncidentPhotoListResponse` con `items` **sin paginar**, como la de
  limpieza.
- THE SYSTEM SHALL enumerar en `IncidentPhotoResponse` **exactamente seis** campos —`id`,
  `incident_id`, `stage`, `uploaded_by`, `created_at`, `url`— y SHALL construirla con un
  `from_upload(...)` explícito, **nunca** con `model_validate` ni `from_attributes` sobre la entidad.
  Eso es lo que hace cumplir la prohibición siguiente por construcción y no por vigilancia.
- THE SYSTEM NEVER SHALL incluir `storage_key` en ningún cuerpo ni cabecera de respuesta de ninguna
  de las tres rutas, y SHALL fijarlo con un test sobre el **cuerpo serializado** y no sobre la lista
  de campos. La única excepción es lo que una URL prefirmada de un proveedor S3-compatible lleva
  dentro por el propio protocolo de firma, ya aceptada por escrito en
  [`file-storage`](file-storage.md) §Catálogo de asimetrías y
  [ADR 0008](../../docs/adr/0008-object-storage-provider-dev.md).

### Servir los bytes: la ruta anónima, y por qué el orden es el mecanismo

- WHERE el `storage_type` del tenant es `LOCAL`, THE SYSTEM SHALL servir el fichero desde
  `GET /api/v1/incident-photos/{photo_id}`, **anónima a propósito**: un `<img src>` no envía
  `Authorization`, así que exigir el token haría la URL firmada inservible para lo único que existe.
  **La firma es la credencial** — cubre la clave completa, que empieza por el `tenant_id`, así que
  presentarla válida demuestra que quien la trae recibió una URL acuñada para esa foto de ese tenant.
- THE SYSTEM SHALL exigir `exp` y `sig` como parámetros de query **obligatorios**; su ausencia es el
  `422` global de validación y no el `403` de firma.
- THE SYSTEM SHALL resolver → verificar → servir, en ese orden: primero `photo_id → (storage_key,
  tenant_id)` con una lectura **explícitamente sin scoping de tenant**, luego verificar la firma
  contra la clave **reconstruida de la base de datos** —nunca contra nada que mandara el llamante—,
  y solo entonces resolver el `storage_type` del tenant y leer los bytes. El orden es lo que la hace
  segura.
- IF la firma es inválida, es incorrecta, ha caducado, ha sido manipulada o nombra una foto
  inexistente, THEN THE SYSTEM SHALL responder `403` con un cuerpo **constante y precomputado en
  tiempo de importación**, idéntico en todos los casos:
  `{"error":{"code":"FORBIDDEN","message":"The signed URL is not valid for this photo","details":{}}}`.
  NEVER SHALL serializar el mensaje de la excepción: los distintos mensajes de firma más el «no
  existe» convertirían la ruta en un **oráculo de existencia** sobre el espacio de claves para un
  llamante sin credenciales. Los mensajes sobreviven solo en el log
  (`maintenance.photo_url_refused`).
- WHERE el `storage_type` del tenant es `S3`, THE SYSTEM SHALL responder `404` con su propio cuerpo
  constante: el navegador va directo al proveedor y aquí no hay nada que servir. Solo es alcanzable
  **tras** una firma válida, así que no revela nada.
- IF el objeto no se puede leer del almacén, THEN THE SYSTEM SHALL responder `502` con cuerpo
  constante y registrar el fallo (`maintenance.photo_object_unreadable`).
- THE SYSTEM SHALL derivar el `Content-Type` **únicamente** de la extensión de la clave almacenada,
  contra el mapa cerrado de la allowlist, y NEVER SHALL tener valor por defecto ni adivinar: una
  extensión que el mapa no declare es un error, no un `application/octet-stream`. Sin eso —y sin el
  `nosniff`— un polyglot que empiece por `FF D8 FF` y lleve HTML sería XSS almacenado sobre el
  origen de la API, que `api-ingress-routing` dejó alcanzable desde internet.
- THE SYSTEM SHALL emitir `X-Content-Type-Options: nosniff` con **un solo valor** en toda respuesta
  de la ruta —los bytes y las tres negativas—, sellado en el **único punto de salida** de la ruta, y
  el middleware global lo sobrescribe con el mismo valor
  ([`backend-http-posture`](backend-http-posture.md)).
- THE SYSTEM SHALL responder los bytes con `Cache-Control: private, max-age=<lo que le queda a la
  firma>`, acotado por arriba al techo de caducidad de la firma y por abajo a cero, de modo que
  ninguna caché compartida los guarde y ninguna copia del navegador sobreviva a la credencial que la
  compró. Las tres negativas van con `no-store`: cada una es un veredicto sobre *esta* petición en
  *este* instante.
- THE SYSTEM SHALL montar esta ruta en un **router propio** (`app/maintenance/api/photos_router.py`,
  montado en `main.py` junto a los demás) y NEVER SHALL colgarla de `incidents_router`, cuyas rutas
  cuelgan todas de un `require(...)`.
- THE SYSTEM SHALL declararla en `ANONYMOUS_ENDPOINTS` de `tests/test_route_authorization.py` con su
  verbo —`("GET", "/api/v1/incident-photos/{photo_id}")`—, de modo que sea anónima **por diff
  visible y no por descuido**. Es la **duodécima** entrada de ese censo
  ([`api-contract`](api-contract.md)), y la **segunda ruta que sirve bytes de un objeto contra una
  firma HMAC**.

### La lectura sin scoping de tenant, y dónde se ve

- THE SYSTEM SHALL declarar la lectura sin filtro de tenant en una **clase aparte** del repositorio
  de fotos (`SqlAlchemyUnscopedIncidentPhotoLocationQuery`), para que ningún caso de uso autenticado
  pueda alcanzarla por error, y SHALL llamar `require_unmarked_session(...)` **antes** de consultar.
- THE SYSTEM SHALL resolverla **sin `JOIN`**: `tenant_id` está en la propia fila. La gemela de
  limpieza necesita uno porque su tabla no lleva la columna, y esa diferencia es una consecuencia
  directa de la decisión de esquema, no una optimización.
- THE SYSTEM SHALL declararla en el censo de excepciones de `tests/test_unscoped_reads.py`, que es
  donde una excepción de scoping tiene que ser visible, y SHALL cablearla **solo** en el builder de
  la ruta anónima.
- THE SYSTEM SHALL considerar esta la **única** excepción de scoping que esta capacidad introduce.

### Auditoría

- WHEN se sube una foto, THE SYSTEM SHALL escribir su `AuditLog` con actor e IP en la **misma
  transacción** que la fila, contra la **propia foto** como entidad (`ENTITY_INCIDENT_PHOTO`,
  acción `INCIDENT_PHOTO_UPLOADED`) y con `entity_id` = el id de la foto, **no** el de la
  incidencia: `entity_id` es lo que indexa `ix_audit_logs_tenant_id_entity_type_entity_id`, y
  apuntar varias subidas al id de la incidencia convertiría «quién subió ESTA foto» en un escaneo
  sobre `changes`. Es el mismo motivo por el que existe `ENTITY_CLEANING_PHOTO`.
- THE SYSTEM SHALL auditar sobre `INCIDENT_PHOTO` **exactamente tres** campos —`stage`,
  `incident_id` y `uploaded_by`— y NEVER SHALL incluir `storage_key` entre ellos: `audit_logs.changes`
  es un sumidero de la regla 11 y la clave interna es precisamente el string que el diseño trabaja
  para no publicar. `ChangeSet` la rechaza **por construcción**, no por vigilancia.
- THE SYSTEM SHALL exigir actor: `INCIDENT_PHOTO_UPLOADED` NEVER SHALL entrar en el conjunto de
  acciones que el escritor de auditoría exime, así que una subida sin actor se rechaza y no comitea
  nada. Esta capacidad **no pide ninguna excepción nueva a la regla 9** de `steering/security.md`.
- THE SYSTEM SHALL acuñar **exactamente una** acción y **exactamente un** tipo de entidad nuevos, y
  fijarlo con un test: NEVER SHALL existir `INCIDENT_PHOTO_DELETED` mientras no exista superficie de
  borrado.
- THE SYSTEM NEVER SHALL escribir `TimelineEvent` por una foto, y es decidido y no olvidado: el
  vocabulario de `TimelineEventType` es el de PRD §10 y no tiene miembro para una foto de
  incidencia; la subida de limpieza tampoco escribe uno; e inventar un miembro para poner una
  afirmación en una tabla *append-only* es lo que `WaitForPartsUseCase` ya rechazó por escrito.

### El techo de cuerpo de la subida, y su posición

- THE SYSTEM SHALL aplicar a `POST /api/v1/incidents/{incident_id}/photos` el mismo
  `PHOTO_UPLOAD_MAX_BYTES` (10 MiB por defecto) que la subida de limpieza, comprobado **antes** de
  leer el cuerpo entero por el contador acumulativo de `MaxBodySizeMiddleware`, y NEVER SHALL
  introducir un ajuste nuevo: es el mismo tipo de fichero por la misma clase de puerta.
- THE SYSTEM SHALL resolver esa rama en el proveedor por path del **único** middleware de tamaño,
  acotada por **los dos extremos** —prefijo `/api/v1/incidents/` y sufijo `/photos`—, para que no
  ensanche el techo de ninguna otra ruta del módulo, y SHALL cubrirlo con un test que falle si
  alguien lo sube globalmente.
- THE SYSTEM SHALL mantener el resto de las rutas bajo `/api/v1/incidents` en el techo del
  `else` final, `REQUEST_MAX_BYTES` (1 MiB), y **no** en `JSON_BODY_MAX_BYTES`: esa rama se
  selecciona por el prefijo `/cleaning-` y `/incidents` nunca la ha tocado. Los dos valen 1 MiB hoy
  y se mantienen separados a propósito, así que no se añadió rama JSON para `/incidents`.
- THE SYSTEM SHALL sostener además un tope **en proceso** dentro del caso de uso, que aborta
  mientras consume y responde `413` (`PAYLOAD_TOO_LARGE`). Eso acota el pico en memoria y es el
  único techo para un llamante sin middleware delante; NEVER SHALL presentarse como defensa frente a
  un `Content-Length` mentido, que es lo que cubre el contador (regla 14 de
  `steering/security.md`).
- THE SYSTEM SHALL aceptar por escrito el mismo riesgo que la rama de limpieza y no heredarlo en
  silencio: son 10 MiB de cuerpo recibidos **antes** de cualquier autenticación, y el patrón es
  **más ancho que la ruta** — `/api/v1/incidents/photos` y `/api/v1/incidents/a/b/c/photos` también
  casan, consumen hasta el techo y luego contestan `404`/`405`.

### Aislamiento de tenant

- THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado, SHALL pasarlo explícito a
  cada método de repositorio y NEVER SHALL aceptarlo en ningún esquema de petición.
- THE SYSTEM SHALL entregar un test de aislamiento **propio** que demuestre, con dos tenants reales,
  que las filas de `incident_photos` de uno no son alcanzables desde el otro por **ninguna de las
  tres rutas**: ni subiendo, ni listando, ni sirviendo con una URL firmada del vecino.
- THE SYSTEM SHALL correr la parte de repositorio de ese test sobre **sesión sin marcar**: sobre una
  sesión marcada el listener filtra y el test no puede fallar.

### El contrato publicado

- THE SYSTEM SHALL declarar las tres operaciones en `backend/openapi.json` como
  `upload_incident_photo_api_v1_incidents__incident_id__photos_post`,
  `list_incident_photos_api_v1_incidents__incident_id__photos_get` y
  `serve_incident_photo_api_v1_incident_photos__photo_id__get`, y SHALL mantener regenerado y
  commiteado `frontend/lib/api/generated/openapi.d.ts` en el mismo PR — las **dos mitades del mismo
  puente** (`steering/documentation.md`).
- THE SYSTEM SHALL declarar en la subida las respuestas `201`, `401`, `403`, `409`, `413`, `422` y
  `502`, y en la ruta anónima `200`, `403`, `404`, `422` y `502` **sin `401`**: no hay credencial que
  falte.
- THE SYSTEM SHALL responder todos los errores con el sobre `{error:{code,message,details}}` de PRD
  §23.
- THE SYSTEM SHALL NOT introducir ninguna variable de entorno nueva: `PHOTO_UPLOAD_MAX_BYTES` y
  `JWT_SECRET_KEY` —de la que se deriva la clave de firma por HKDF— ya existen, así que
  `.env.example` no se toca.

### Lo que esta capacidad no hace

- THE SYSTEM NEVER SHALL exponer superficie de **borrado** de fotos por ninguna vía de la API. El
  puerto tiene `delete` y su único llamante sigue siendo el borrado compensatorio. No habrá
  superficie de borrado sin una decisión de retención ([`file-storage`](file-storage.md) §Estado).
- THE SYSTEM SHALL dejar `resolve` exigiendo únicamente `final_cost`
  ([`maintenance`](maintenance.md) R6): la foto de cierre es **opcional** y no hay puerta de
  evidencia. Decidido explícitamente — añadirla toca R6, la tabla de transiciones y el contrato
  publicado.
- THE SYSTEM NEVER SHALL aceptar foto en el **alta** de la incidencia: ni la limpiadora desde su
  tarea ([`cleaner-incident-report`](cleaner-incident-report.md)) ni el portal anónimo del huésped
  ([`guest-portal-api`](guest-portal-api.md)) suben fotos. Consecuencia con nombre: «fotos del
  incidente» de PRD §12 son las `BEFORE` que sube el **propio técnico**, no las de quien reportó.
  Abrir subida de ficheros a un portador anónimo es una superficie propia.
- THE SYSTEM SHALL dejar `ai_validation_result` sin escribir: el `AIAdapter` de
  [`messaging-ai`](messaging-ai.md) no declara nada equivalente y `maintenance` no tiene puerto
  propio para ello — el mismo motivo por el que `cleaning` lo dejó sin escribir.
- THE SYSTEM SHALL dejar la allowlist de formatos como está: HEIC/HEIF sigue fuera. Es una decisión
  de producto sobre [`file-storage`](file-storage.md), no de este consumidor.
- THE SYSTEM NEVER SHALL exponer las fotos en la proyección de contexto del técnico
  (`GET /api/v1/incidents/{id}/context`, [`tech-incident-context`](tech-incident-context.md)): son
  rutas distintas y aquélla no cambió por esta causa.
- La **pantalla** —`/tech/incidents/[id]` y su carrete— la implementa `tech-app`; esta capacidad no
  trae frontend ni claves de i18n.

## La capa compartida que esta capacidad estrenó

Tener un **segundo** consumidor del almacén obligó a decidir si se calcaba la ruta de servido
firmada de limpieza o se extraía. Se extrajo, y `cleaning` se migró a ella en el mismo PR, sin
cambio de comportamiento.

- THE SYSTEM SHALL declarar en `app/integrations/` el puerto de localización
  `UnscopedObjectLocationQuery` (`locate_without_tenant_scoping(object_id) -> ObjectLocation | None`,
  con `ObjectLocation(storage_key, tenant_id)` congelado), el caso de uso `ServeSignedObjectUseCase`
  con el orden resolver→verificar→servir y sus refusals colapsados en una sola excepción, y la
  factoría de router `build_signed_media_router(...)`, que produce el cuerpo `403` constante, el
  sello de `nosniff`, el `Cache-Control` derivado de la firma y el bloque `responses` con los media
  types de la allowlist.
- THE SYSTEM SHALL hacer que los dos dominios monten su ruta anónima con esa factoría, cada uno con
  su prefijo, su tag y su nombre de evento de log, y NEVER SHALL mantener dos implementaciones de
  esa frontera: es la superficie más expuesta de la aplicación —anónima, alcanzable desde internet
  por el túnel de `api-ingress-routing`, devolviendo bytes que subió un tercero— y dos copias de su
  prosa de seguridad son dos sitios donde la garantía puede divergir.
- THE SYSTEM SHALL NOT modificar `FileStoragePort`, `LocalFileReadPort` ni `FileStorageFactory` por
  esta causa. Lo que se añadió es un puerto de *localización* nuevo y una capa de aplicación/API por
  encima.
- THE SYSTEM SHALL construir la factoría de almacenamiento **por consumidor**, con su prefijo de URL
  firmada (`storage_factory_for(url_prefix)`), y cada dominio SHALL nombrar el suyo
  (`CLEANING_PHOTO_URL_PREFIX`, `INCIDENT_PHOTO_URL_PREFIX = "/api/v1/incident-photos"`). La clave
  de firma sigue compartida —es el mismo secreto para firmar y verificar—; lo que varía es un
  argumento de constructor que la clase **ya aceptaba**.
- THE SYSTEM SHALL considerar que **ningún consumidor debe depender ya del valor por defecto** del
  prefijo. `DEFAULT_SIGNED_URL_PREFIX` sigue apuntando a la ruta de limpieza, así que quien lo
  herede acuñará URLs que resuelven contra `cleaning_photos`, no encontrarán la fila y contestarán
  el `403` constante — **una feature rota que se lee como una firma rota**. Por eso el comando de
  siembra pasa el suyo explícito.

## Estado

- **Entregada y verificada extremo a extremo el 2026-08-23.** La comprobación que importa no la hace
  la suite: se abrió la URL firmada devuelta **en el navegador, sin cabecera de autorización**, que
  es lo único que demuestra la razón de existir de la ruta anónima; y se comprobaron el `403` con
  firma manipulada y el `409` con la incidencia en `RESOLVED`.
- **El prefijo de la URL firmada no estaba previsto y rompió la feature.** Con la dependencia de
  almacenamiento compartida tal cual, las fotos de incidencia recibían URLs apuntando a
  `/api/v1/cleaning-photos/{id}`; esa ruta resolvía el id contra `cleaning_photos`, no lo encontraba
  y contestaba el `403` constante. Lo cazaron seis tests esperando `200`. La lección es del método:
  **un cuerpo de error constante y bien diseñado también esconde los errores propios**, y el síntoma
  de un fallo de wiring fue indistinguible de una firma inválida.
- **La afirmación de `file-storage.md` §Key Files sobre el «único punto» donde se leen los ajustes
  del almacén dejó de ser cierta con este change**, y se corrigió allí: la clave de firma y la
  construcción de la factoría viven ahora en `app/integrations/api/dependencies.py`. Lo detectó el
  panel de documentación, no el diseño.
- **Dos afirmaciones del proposal se corrigieron contra el código y se conservan corregidas.** R4.6
  decía que ésta sería la «segunda ruta anónima de la aplicación»: el censo tenía once entradas y
  ésta es la **duodécima** — lo cierto y más estrecho es que es la segunda que sirve bytes contra
  una firma HMAC. Y R5.2 decía que las demás rutas de `/incidents` estaban en `JSON_BODY_MAX_BYTES`:
  están en `REQUEST_MAX_BYTES`, y la intención se satisface dejando el fall-through como estaba.
- **El guardián que R6.5 nombraba no es el que se actualizó.** El proposal pedía verificar la
  ausencia de sumidero nuevo contra el guardián de la regla 11 (entonces en `backend/tests/`, hoy
  en `scripts/rule11-ownership.py`), y ese fichero **no se tocó**:
  lo que se amplió fue el censo de `tests/maintenance/test_free_text_sink_contract.py` (de dos
  routers a tres). La propiedad de fondo —enum cerrado, ningún texto libre del llamante— sí queda
  fijada, por el test de los dos miembros del enum y por el `Form()` que lo coacciona; pero el
  fichero que la requisición nombraba no ganó ninguna aserción, y conviene que conste.
- **La migración tocó una tabla compartida.** El `UNIQUE (tenant_id, id)` sobre `incidents` se
  aceptó en el gate del diseño con su alternativa rechazada. En un entorno con datos es un
  `CREATE UNIQUE INDEX` que no puede fallar por duplicados, porque `id` ya es clave primaria.
- **Colisionó con `tech-cycle-completion`, como estaba previsto**, y el `down_revision` se repuntó a
  mano sobre `origin/main` antes de abrir el PR. El rebase también arregló dos tests que `main` dejó
  desfasados. `alembic heads` devuelve un solo head.
- **La migración de la ruta anónima de `cleaning` a la capa compartida no cambió comportamiento**, y
  eso lo sostiene la suite de `cleaning`, que compara los cuerpos de refusal literalmente y fija el
  orden de los middlewares.
- **Sin pantalla.** Las tres rutas existen y nadie las llama todavía: `tech-app` es quien pinta
  `/tech/incidents/[id]` y declara esta capacidad en su `needs`.
- **Sin borrado, sin puerta de evidencia y sin validación por IA**, los tres por decisión escrita y
  no por olvido. Ver §Lo que esta capacidad no hace.

## Key files

- `backend/app/maintenance/domain/enums.py` — `IncidentPhotoStage` (`BEFORE`/`AFTER`), con su
  `ASSUMPTION`.
- `backend/app/maintenance/domain/entities.py` — `IncidentPhoto`,
  `PHOTO_ACCEPTING_INCIDENT_STATUSES`, `Incident.ensure_accepts_photo()` y el helper privado de
  refusals que comparte con `_check_transition`.
- `backend/app/maintenance/domain/repositories.py` — `IncidentPhotoRepository` (`add`,
  `list_for_incident`; sin `get` y sin `delete`).
- `backend/app/maintenance/domain/exceptions.py` — `IncidentPhotoTooLargeError`,
  `UnsupportedIncidentPhotoFormatError`, `IncidentPhotoStorageUnavailableError`.
- `backend/app/maintenance/infrastructure/models.py` — `IncidentPhotoModel`, la clave ajena
  compuesta, el índice, la ausencia comentada del `UNIQUE` sobre `(incident_id, stage)`, y
  `uq_incidents_tenant_id_id` en `IncidentModel`.
- `backend/app/maintenance/infrastructure/repositories.py` —
  `SqlAlchemyIncidentPhotoRepository` y `SqlAlchemyUnscopedIncidentPhotoLocationQuery`.
- `backend/alembic/versions/d4a7e18c6b93_incident_photos.py` — la revisión, y su `downgrade`
  completo.
- `backend/app/maintenance/application/use_cases.py` — `UploadIncidentPhotoUseCase` (el orden de
  D7, el tope en proceso y el borrado compensatorio), `ListIncidentPhotosUseCase` y
  `_incident_photo_change_set`.
- `backend/app/maintenance/api/incidents_router.py` — las dos rutas autenticadas y
  `_PHOTO_UPLOAD_RESPONSES`.
- `backend/app/maintenance/api/photos_router.py` — la ruta anónima, construida con la factoría
  compartida; el módulo explica por qué es un router propio.
- `backend/app/maintenance/api/schemas.py` — `IncidentPhotoResponse` (seis campos, `from_upload`) y
  `IncidentPhotoListResponse`.
- `backend/app/maintenance/api/dependencies.py` — los tres builders y
  `get_incident_photo_storage_factory` con su prefijo propio.
- `backend/app/maintenance/api/errors.py` — `_MAPPING`, con las tres filas de foto.
- `backend/app/integrations/domain/storage.py` — `storage_key_for_incident_photo`, el
  `_photo_storage_key` compartido con su guarda de extensión, `UnscopedObjectLocationQuery`,
  `ObjectLocation`, `content_type_for_extension`.
- `backend/app/integrations/application/signed_serving.py` — `ServeSignedObjectUseCase`,
  `ServedObject`, `extension_of`.
- `backend/app/integrations/api/signed_media.py` — `build_signed_media_router(...)`, los tres
  cuerpos constantes, el sello de `nosniff` y el `Cache-Control`.
- `backend/app/integrations/api/dependencies.py` — `get_url_signing_key` y
  `storage_factory_for(url_prefix)`.
- `backend/app/integrations/infrastructure/storage/local.py` — `CLEANING_PHOTO_URL_PREFIX`,
  `INCIDENT_PHOTO_URL_PREFIX`, `DEFAULT_SIGNED_URL_PREFIX`.
- `backend/app/audit/domain/actions.py`, `value_objects.py` — `ENTITY_INCIDENT_PHOTO`,
  `INCIDENT_PHOTO_UPLOADED`, `AUDITABLE_FIELDS["INCIDENT_PHOTO"]`.
- `backend/app/main.py` — el montaje del router anónimo y la rama del techo de cuerpo, con su
  riesgo aceptado escrito al lado.
- Tests: `backend/tests/maintenance/test_photo_upload_use_case.py`,
  `test_photo_listing_use_case.py`, `test_photos_api.py`, `test_serve_photo_api.py`,
  `test_photo_isolation.py`, `test_photo_body_limit.py`,
  `backend/tests/audit/test_incident_photo_vocabulary.py`,
  `backend/tests/integrations/test_signed_serving_use_case.py`,
  `test_signed_media_headers.py`, `test_storage_keys.py`; y los dos censos,
  `backend/tests/test_route_authorization.py` y `backend/tests/test_unscoped_reads.py`.
