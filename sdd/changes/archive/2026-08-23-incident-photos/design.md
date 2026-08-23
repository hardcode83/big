# Design: incident-photos

## Context

El puerto de almacenamiento ya existe y está completo: `backend/app/integrations/domain/storage.py`
declara `FileStoragePort`, `LocalFileReadPort`, `FileStorageFactory`, la allowlist de formatos, el
esquema de claves y las primitivas de firma HMAC, y `app/integrations/infrastructure/storage/`
implementa `LOCAL` y `S3`. Su único consumidor es `cleaning`, con tres piezas que este change tiene
que replicar o compartir: `UploadCleaningPhotoUseCase` / `ListCleaningPhotosUseCase` /
`ServeLocalCleaningPhotoUseCase` (`app/cleaning/application/use_cases.py:1554-1908`), el router
anónimo `app/cleaning/api/photos_router.py`, y los adaptadores
`SqlAlchemyCleaningPhotoRepository` / `SqlAlchemyUnscopedCleaningPhotoLocationQuery`
(`app/cleaning/infrastructure/repositories.py:410-571`).

Del lado de `maintenance` está todo lo que hace falta menos la foto: `IncidentActor` con
`restrict_to_technician_id` derivado del rol y `_load_incident_in_scope` con su `404` único
(`app/maintenance/application/use_cases.py:377-465`), la tabla de transiciones y sus tres refusals
en `Incident._check_transition` (`app/maintenance/domain/entities.py:162-234`), `_AuditWriter` que
rechaza una fila sin actor, el mapeo de errores de `api/errors.py`, y `ROLE_PERMISSIONS` con
`EXECUTE_INCIDENTS` en `TECHNICIAN` y `PROPERTY_MANAGER` y `READ_INCIDENTS` además en
`TENANT_OWNER` (`app/auth/domain/policy.py:206-208`). No hay entidad, ni tabla, ni ruta de foto:
`IncidentPhoto` / `incident_photos` no aparecen en ninguna línea de `backend/`.

El techo de cuerpo se resuelve por path en un único `MaxBodySizeMiddleware`
(`app/main.py:242-256`), y el censo de rutas anónimas vive en `ANONYMOUS_ENDPOINTS` de
`tests/test_route_authorization.py`.

## Decisions

### D1 — El código vive dentro de `app/maintenance/`, sin dominio nuevo

**Chosen:** entidad y enum en `app/maintenance/domain/`, modelo en el
`infrastructure/models.py` que ya existe, casos de uso al final de
`application/use_cases.py`, las dos rutas autenticadas sobre el `incidents_router` actual y la
ruta anónima en un `api/photos_router.py` nuevo. Una foto de incidente no es raíz de agregado: se
carga siempre a través de su incidencia y su regla de acotamiento por fila es la de `maintenance`.
Además el modelo entra gratis en `app/core/models_registry.py`, que ya lista
`app.maintenance.infrastructure.models` — y `tests/test_models_registry.py` exige una entrada por
dominio con modelos.

La spec **sí** es propia (`sdd/specs/incident-photos.md`), como pide el proposal: una spec describe
una capability, no un directorio, y `tech-incident-context` ya tiene la suya con el código dentro de
`maintenance`.

Rejected: un `app/incident_photos/` propio — obligaría a registrar dominio, error handlers y
entrada de registry para tres ficheros que importan la entidad de `maintenance` de todas formas.

### D2 — `incident_photos` lleva `tenant_id` **y** clave ajena compuesta contra su incidencia

**Chosen:** confirmar R1.3 y dar un paso más. La tabla usa `TenantScopedMixin` (columna `tenant_id`
`NOT NULL` indexada, FK a `tenants.id`) y declara además

```python
ForeignKeyConstraint(
    ["tenant_id", "incident_id"],
    ["incidents.tenant_id", "incidents.id"],
    ondelete="RESTRICT",
    name="fk_incident_photos_incident_within_tenant",
)
```

lo que obliga a añadir `UniqueConstraint("tenant_id", "id", name="uq_incidents_tenant_id_id")` a
`incidents` — exactamente el par que `reservations` ya tiene para que `guest_access_tokens` pueda
apuntarla (`app/reservations/infrastructure/models.py:35`,
`app/guests/infrastructure/models.py:99-110`).

Tres cosas lo justifican y son distintas entre sí: la columna mete la tabla en
`tenant_scoped_classes()`, o sea bajo el filtro global de `app/core/db.py`, cosa que
`cleaning_photos` no consigue; hace posible el test de aislamiento propio que pide R6.3 sin
depender de la incidencia; y la clave compuesta convierte «el tenant de la foto y el de su
incidencia no pueden divergir» en un invariante del esquema en vez de disciplina del repositorio —
con dos claves ajenas independientes una fila que empareja el tenant A con una incidencia del
tenant B es legal, que es justo lo que reprodujeron los paneles de `guest-portal-api`.

Rejected: calcar `cleaning_photos`, que no tiene `tenant_id` y se acota por la tarea — el proposal
pide confirmar o revertir la desviación explícitamente, y la ausencia allí es histórica, no
diseñada (su propio adaptador se documenta como «the other table with no `tenant_id`»).
Rejected: `tenant_id` con dos claves ajenas simples — deja legal la fila cruzada. Decidido en el
gate de `/sdd:design` (OQ2, aprobado por Jose el 2026-08-22).

Consecuencia con nombre: la migración toca **dos** tablas, y `incidents` es una tabla que
`tech-cycle-completion` también va a migrar (ver Risks).

### D3 — `stage` es un enum cerrado nativo, no una columna de texto

**Chosen:** `IncidentPhotoStage(str, enum.Enum)` con `BEFORE` y `AFTER` en
`app/maintenance/domain/enums.py`, mapeado con
`Enum(IncidentPhotoStage, name="incident_photo_stage", native_enum=True)` como los seis enums que
ya tiene ese módulo. Marcado `ASSUMPTION`: el nombre es inventado, PRD §6 solo dice «subir fotos
(antes y después)» y PRD §7 no declara la entidad (R1.6).

Es la diferencia estructural que nombra el proposal: `cleaning_photos.photo_type` es
`String(100)` porque la plantilla de la tarea acota los valores admisibles; una incidencia no tiene
plantilla, así que un texto libre del llamante sería un sumidero nuevo de la regla 11 de
`steering/security.md` sin nada que lo cierre. El enum es lo que permite que R6.5 se cumpla por
construcción.

Rejected: `String(100)` calcando limpieza — abre el sumidero. Rejected: un booleano `is_final` —
no admite una tercera etapa el día que exista y se lee peor en el contrato.

### D4 — Una segunda función de clave, sobre un cuerpo compartido

**Chosen:** `storage_key_for_incident_photo(*, tenant_id, incident_id, photo_id, extension)` →
`tenants/{tenant_id}/incidents/{incident_id}/{photo_id}.{ext}`, junto a la que ya existe y
apoyada con ella en un `_photo_storage_key(*, tenant_id, collection, owner_id, photo_id,
extension)` privado que conserva en un solo sitio la comprobación de que la extensión sale de
`ACCEPTED_EXTENSIONS`. El segmento de colección es `incidents`, igual que `cleaning-tasks` refleja
el prefijo de su ruta.

Rejected: parametrizar la función pública existente — cambia el call site de `cleaning` y pierde
la forma greppable por consumidor. Rejected: copiar el cuerpo — duplica la guarda de extensión, que
es la que impide que una clave se construya con algo que el almacén luego no sabe servir.

### D5 — La ruta anónima de servido se extrae una vez y se usa dos

**Chosen:** sacar a `app/integrations/` el par que hoy vive en `cleaning` y que es **idéntico**
palabra por palabra para cualquier consumidor:

- `app/integrations/domain/storage.py` gana el puerto `UnscopedObjectLocationQuery`
  (`locate_without_tenant_scoping(object_id) -> ObjectLocation | None`, con
  `ObjectLocation(storage_key, tenant_id)`);
- `app/integrations/application/signed_serving.py` gana `ServeSignedObjectUseCase`, el orden
  resolver → verificar → servir con sus tres refusals colapsados en `InvalidSignatureError`;
- `app/integrations/api/signed_media.py` gana `build_signed_media_router(...)`, que produce un
  `APIRouter` con el cuerpo `403` constante, el sello de `nosniff`, el `Cache-Control` derivado de
  lo que le queda a la firma y el bloque `responses` con los media types de la allowlist.

`cleaning` se migra a ese par en el mismo PR y `maintenance` monta el suyo con
`prefix="/incident-photos"`. El motivo es el que este repositorio aplica en todas partes: esta es
la superficie más expuesta de la aplicación —anónima, alcanzable desde internet por el túnel de
`api-ingress-routing`, devolviendo bytes que subió un tercero— y dos copias de su prosa de
seguridad son dos sitios donde la garantía puede divergir. Son ~400 líneas de las que lo único
específico del dominio es el prefijo, el tag y el nombre del evento de log.

Lo que **no** se toca: `FileStoragePort`, `LocalFileReadPort` ni `FileStorageFactory`. El proposal
dice que este change es el segundo consumidor del puerto y no su modificación, y eso se mantiene:
lo que se añade es un puerto de *localización* nuevo y una capa de aplicación/API por encima.

Decidido en el gate de `/sdd:design` (OQ1, aprobado por Jose el 2026-08-22).

Rejected: calcar los dos ficheros bajo `maintenance/` — es lo que el proposal describe como
«calco», y es defendible, pero deja dos implementaciones de la misma frontera de seguridad, y una
entrada de roadmap para unirlas que nadie garantiza que se haga.
Rejected: una sola ruta compartida `/api/v1/media/{id}` para los dos dominios — rompería el
contrato publicado de `cleaning`.

### D6 — La puerta por estado vive en la entidad, no en el caso de uso

**Chosen:** `Incident.ensure_accepts_photo()`, que no muta y rechaza en el **mismo orden** que
`_check_transition`:

1. estado terminal (`RESOLVED`, `CANCELLED`) → `IncidentAlreadyClosedError` (R2.6);
2. `AWAITING_OWNER_APPROVAL` → `IncidentBlockedByPendingApprovalError` (R2.5);
3. cualquier estado que no sea `IN_PROGRESS` ni `WAITING_EXTERNAL_PARTS` →
   `InvalidIncidentTransitionError` (R2.4).

Las dos primeras ramas se extraen de `_check_transition` a un helper privado compartido, para que
el orden tenga una sola casa. Los tres errores ya están en `_MAPPING` de
`app/maintenance/api/errors.py` como `409 CONFLICT` con mensajes distintos, así que R2.4/R2.5/R2.6
se cumplen sin clase de error nueva y sin tocar el contrato de errores del módulo.

Rejected: la forma de limpieza (`if task.status is not IN_PROGRESS` dentro del caso de uso) — no
puede producir las tres negativas distinguibles que pide el proposal y duplicaría el orden.
Rejected: una fila en `_TRANSITIONS` — subir una foto no mueve el estado, y una tabla de
transiciones con una no-transición dentro miente.

### D7 — Objeto primero, fila después, borrado compensatorio

**Chosen:** calco literal de la D4 de `cleaning-photos-storage` (R2.7): se escribe el objeto por
`FileStoragePort.put`, luego se inserta la fila y se escribe el `AuditLog`, y si el commit falla se
borra el objeto en *best effort* registrando la clave en el log. Un fallo de escritura del almacén
se traduce en `502 BAD_GATEWAY` sin fila (R2.8), reutilizando el `ErrorCode.BAD_GATEWAY` que
introdujo aquel change. La clave **sí** viaja al log del borrado fallido y eso no contradice R3.3:
esa regla gobierna respuestas de API, y el log es todo el procedimiento de recuperación que tiene
un objeto huérfano.

### D8 — Auditoría: entidad propia, sin `storage_key`, y **sin** evento de timeline

**Chosen:** `ENTITY_INCIDENT_PHOTO = "INCIDENT_PHOTO"` y `INCIDENT_PHOTO_UPLOADED` en
`app/audit/domain/actions.py` (con su entrada en `ENTITY_TYPES` y en `ACTIONS`), y
`AUDITABLE_FIELDS["INCIDENT_PHOTO"] = {"stage", "incident_id", "uploaded_by"}` en
`app/audit/domain/value_objects.py`. Entidad propia y no la incidencia, por lo mismo que existe
`ENTITY_CLEANING_PHOTO`: `entity_id` es lo que indexa
`ix_audit_logs_tenant_id_entity_type_entity_id`, y apuntar varias subidas al id de la incidencia
convertiría «quién subió ESTA foto» en un escaneo sobre `changes`. `storage_key` **no** está en la
allowlist (R6.2): `audit_logs.changes` es un sumidero de la regla 11 y la clave interna es
precisamente el string que el diseño trabaja para no publicar.

Se escribe por el `_AuditWriter` que `maintenance` ya tiene, que rechaza una fila sin actor salvo
para las acciones de `_ACTOR_OPTIONAL_ACTIONS` — `INCIDENT_PHOTO_UPLOADED` no entra ahí, así que
**este change no pide ninguna excepción nueva a la regla 9** de `steering/security.md`.

**No hay `TimelineEvent`**, y es decidido y no olvidado: el vocabulario de `TimelineEventType` es
el de PRD §10 y no tiene ningún miembro para una foto de incidente; la subida de limpieza tampoco
escribe uno (su `TimelineEventType.CLEANING_PHOTO_UPLOADED` existe en el enum y no tiene escritor
en `app/`); e inventar un miembro para poner una afirmación en una tabla *append-only* es lo que
`WaitForPartsUseCase` ya rechazó por escrito. R6 pide `AuditLog` y no menciona timeline.

### D9 — El techo de cuerpo, y la corrección a R5.2

**Chosen:** una rama más en el proveedor por path de `MaxBodySizeMiddleware`
(`app/main.py:244-255`), antes del `else` final:

```python
settings.photo_upload_max_bytes
if path.startswith(f"{API_V1_PREFIX}/incidents/") and path.endswith("/photos")
```

Acotada por los **dos** extremos igual que la de limpieza (R5.3), y reutilizando
`PHOTO_UPLOAD_MAX_BYTES` sin introducir ajuste nuevo (R5.1). Su posición relativa no es crítica
como la de la rama de limpieza —`/incidents/` no comparte prefijo con `/cleaning-` ni con
`/integrations/`— pero tiene que estar antes del `else`, y el test lo fija.

**Corrección a R5.2, verificada en el código:** hoy todas las rutas bajo `/api/v1/incidents` caen
en el `else`, o sea en `settings.request_max_bytes` (`REQUEST_MAX_BYTES`), **no** en
`JSON_BODY_MAX_BYTES` — esa rama se activa por el prefijo `/cleaning-` y `/incidents` nunca la ha
tocado. Los dos valen 1 MiB hoy y se mantienen separados a propósito (uno está fijado contra el
máximo de un esquema y el otro es una perilla operativa), así que la intención de R5.2 se satisface
**dejando el fall-through como está** y este design no añade rama JSON para `/incidents`. La spec
nueva lo escribirá con la constante correcta.

El riesgo aceptado que `app/main.py` documenta para la rama de limpieza se extiende a ésta
literalmente y hay que escribirlo, no heredarlo en silencio: son 10 MiB de cuerpo anónimo antes de
cualquier autenticación, y el patrón es **más ancho que la ruta** (`/api/v1/incidents/photos` y
`/api/v1/incidents/a/b/c/photos` también casan, consumen hasta el techo y luego contestan 404/405).

### D10 — Las tres rutas, sus permisos y lo que nunca sale en el cuerpo

**Chosen:**

| Ruta | Permiso | Acotamiento por fila |
|---|---|---|
| `POST /api/v1/incidents/{incident_id}/photos` | `EXECUTE_INCIDENTS` | `restrict_to_technician_id` |
| `GET /api/v1/incidents/{incident_id}/photos` | `READ_INCIDENTS` | `restrict_to_technician_id` |
| `GET /api/v1/incident-photos/{photo_id}` | ninguno (anónima) | la firma es la credencial |

Las dos primeras cuelgan del `incidents_router` existente, que ya declara
`AUTHENTICATED_RESPONSES`, y usan las dependencias `ExecuteDep` / `ReadDep` que ese fichero ya
define. Ninguna crea permiso nuevo (R2.2, R3.2), así que `ROLE_PERMISSIONS` no se toca: subir queda
en `TECHNICIAN` y `PROPERTY_MANAGER`, listar añade `TENANT_OWNER`. La resolución de la incidencia
va por `_load_incident_in_scope`, que es lo que hace indistinguibles los cuatro `404` de R3.4.

`IncidentPhotoResponse` enumera sus campos —`id`, `incident_id`, `stage`, `uploaded_by`,
`created_at`, `url`— y se construye con un `from_upload(...)` explícito, **nunca** con
`model_validate` / `from_attributes` sobre la entidad: eso es lo que hace cumplir R3.3, y el test
lo comprueba sobre el cuerpo serializado y no sobre la lista de campos. `IncidentPhotoListResponse`
envuelve `items` sin paginar, como la de limpieza. La URL firmada se acuña por respuesta, también
en el `201` de la subida.

### D10a — Aclaración: el prefijo de la URL firmada es por consumidor

**Encontrado implementando la sección 8, decidido con Jose el 2026-08-22.** D10 decía
«reutilización de `get_url_signing_key` / `get_file_storage_factory`» y D5 decía que
`FileStorageFactory` no se toca. Las dos siguen en pie, pero entre ambas faltaba un dato: la URL
firmada que acuña `LocalFileStorage.signed_url` es
`{url_prefix}/{object id}?exp=…&sig=…`, y `url_prefix` venía por defecto de
`DEFAULT_SIGNED_URL_PREFIX`, que es **la ruta de limpieza**.

Con la dependencia compartida tal cual, las fotos de incidente recibían URLs apuntando a
`/api/v1/cleaning-photos/{id}`. Esa ruta resuelve el id contra `cleaning_photos`, no lo encuentra
y contesta el `403` constante — o sea, **una feature rota que se lee como una firma rota**. Lo
cazaron los tests de la sección 8 fallando seis veces con `403` donde esperaban `200`.

**Chosen:** `get_url_signing_key` sigue compartido —es el mismo secreto para firmar y
verificar—, y la factory pasa a construirse por consumidor con su prefijo:
`storage_factory_for(url_prefix)` en `app/integrations/api/dependencies.py`, con
`CLEANING_PHOTO_URL_PREFIX` e `INCIDENT_PHOTO_URL_PREFIX` nombrados en el adaptador. Ni el puerto
ni `ConfiguredFileStorageFactory` cambian: lo único que varía es un argumento de constructor que
la clase **ya aceptaba**, y cuyo comentario ya anticipaba este caso por escrito («`maintenance` y
`revenue` servirán sus propios objetos desde sus propias rutas […] y sólo el wiring sabe cuál»).

Rejected: derivar el prefijo del segmento de colección de la clave dentro de
`LocalFileStorage.signed_url` — acopla el adaptador de almacenamiento a los nombres de las rutas
y añade un mapa que hay que mantener sincronizado con los routers.

Consecuencia con nombre: ningún consumidor debe depender ya del valor por defecto. El que lo
haga acuñará URLs de la ruta de limpieza, y el síntoma será un `403` que no parece un error de
wiring.

### D11 — El `422` de una etapa desconocida sale del enum, no de una consulta

**Chosen:** la etapa llega como `Annotated[IncidentPhotoStage, Form()]`, así que FastAPI contesta
`422` antes de que el caso de uso exista — que es exactamente R2.10, y es gratis. Conviene
escribirlo porque en limpieza el `photo_type` desconocido contesta `404` desde una consulta a la
plantilla: aquí no hay ninguna fila cuya existencia se pueda filtrar, así que el `404` sería la
respuesta equivocada.

### D12 — Censo de rutas anónimas: la entrada nueva, y la corrección a R4.6

**Chosen:** router propio (`app/maintenance/api/photos_router.py`, montado en `main.py` junto a los
demás), y una entrada nueva `("GET", "/api/v1/incident-photos/{photo_id}")` en
`ANONYMOUS_ENDPOINTS`, con su comentario. Nunca colgada de `incidents_router` (R4.6).

**Corrección a R4.6, verificada:** el censo tiene hoy **once** entradas —`/health`,
`auth/login`, `auth/refresh`, `auth/forgot-password`, `auth/reset-password`,
`cleaning-photos/{photo_id}`, el receptor de webhooks y las cuatro del portal del huésped—, como
enumera `sdd/specs/api-contract.md`. Esta será la **duodécima**, no la segunda. Lo que sí es cierto
y es la afirmación que hay que conservar: es la **segunda ruta que sirve bytes de un objeto contra
una firma HMAC**, y la primera desde que existe `object-storage-provisioning`. La spec nueva y la
actualización de `api-contract.md` escriben la cifra corregida (once → doce, y 83 de 94 operaciones
con `HTTPBearer` pasa a su valor nuevo).

### D13 — Lectura sin scoping: un adaptador propio, dentro del censo

**Chosen:** `SqlAlchemyUnscopedIncidentPhotoLocationQuery`, clase aparte del repositorio de fotos
—para que ningún caso de uso autenticado pueda alcanzarla por error—, que llama
`require_unmarked_session(...)` antes de consultar y devuelve `(storage_key, tenant_id)`. Con D2 la
consulta es sobre una sola tabla: `tenant_id` está en la propia fila, así que no hay `JOIN` que
escribir (la de limpieza lo necesita porque su tabla no lleva la columna). Se añade al censo de
`tests/test_unscoped_reads.py`, que es donde R6.4 pide que la excepción se vea.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Dominio maintenance | `app/maintenance/domain/enums.py` | `IncidentPhotoStage` (`BEFORE`/`AFTER`), `ASSUMPTION` (D3) |
| | `app/maintenance/domain/entities.py` | `IncidentPhoto`; `Incident.ensure_accepts_photo()` y el helper de refusals extraído (D6) |
| | `app/maintenance/domain/repositories.py` | puertos `IncidentPhotoRepository` (`add`, `list_for_incident`) |
| Infra maintenance | `app/maintenance/infrastructure/models.py` | `IncidentPhotoModel`; `uq_incidents_tenant_id_id` en `IncidentModel` (D2) |
| | `app/maintenance/infrastructure/repositories.py` | `SqlAlchemyIncidentPhotoRepository`, `SqlAlchemyUnscopedIncidentPhotoLocationQuery` (D13) |
| | `alembic/versions/` | una revisión: tabla `incident_photos`, tipo `incident_photo_stage`, `UNIQUE` en `incidents` |
| Aplicación maintenance | `app/maintenance/application/use_cases.py` | `UploadIncidentPhotoUseCase`, `ListIncidentPhotosUseCase` (D7) |
| API maintenance | `app/maintenance/api/incidents_router.py` | `POST` y `GET .../photos` (D10) |
| | `app/maintenance/api/photos_router.py` | **nuevo**: ruta anónima, construida con el factory de D5 |
| | `app/maintenance/api/schemas.py` | `IncidentPhotoResponse`, `IncidentPhotoListResponse` |
| | `app/maintenance/api/dependencies.py` | tres builders + `get_url_signing_key` compartido y **factory con prefijo propio** (aclaración D10a) |
| Integrations (D5) | `app/integrations/domain/storage.py` | `storage_key_for_incident_photo` (D4); puerto `UnscopedObjectLocationQuery` + `ObjectLocation` |
| | `app/integrations/application/signed_serving.py` | **nuevo**: `ServeSignedObjectUseCase` |
| | `app/integrations/api/signed_media.py` | **nuevo**: `build_signed_media_router(...)` |
| Cleaning (D5) | `app/cleaning/api/photos_router.py`, `application/use_cases.py`, `api/dependencies.py` | migración al par compartido, sin cambio de comportamiento |
| Auditoría | `app/audit/domain/actions.py`, `value_objects.py` | `ENTITY_INCIDENT_PHOTO`, `INCIDENT_PHOTO_UPLOADED`, `AUDITABLE_FIELDS` (D8) |
| Arranque | `app/main.py` | montaje del router anónimo + rama del techo de cuerpo (D9) |
| Tests | `tests/maintenance/` | subida, listado, servido, API, entidad, repositorios, aislamiento propio (R6.3), techo de cuerpo |
| | `tests/test_route_authorization.py`, `tests/test_unscoped_reads.py` | entradas nuevas en los dos censos (D12, D13) |
| Contrato y docs | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados en el mismo PR (R6.6); en worktree, por el rodeo de `sdd/project.md` |
| | `docs/diagrams/`, `docs/maintenance.md` | ER regenerado (entidad nueva) y página de capability al archivar |

## Data & interfaces

**Tabla `incident_photos`** (`ASSUMPTION`: no está en el PRD — R1.6):

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `UUID` PK | `UUIDPrimaryKeyMixin` |
| `tenant_id` | `UUID NOT NULL` | `TenantScopedMixin`; FK a `tenants.id` y mitad de la compuesta (D2) |
| `incident_id` | `UUID NOT NULL` | mitad de `fk_incident_photos_incident_within_tenant`, `ON DELETE RESTRICT` |
| `uploaded_by` | `UUID NOT NULL` | FK a `users.id`, `ON DELETE RESTRICT`; del token, nunca del cuerpo |
| `stage` | `incident_photo_stage` | enum nativo `BEFORE`/`AFTER` (D3) |
| `storage_key` | `String(500)` | nunca en respuesta ni en `AUDITABLE_FIELDS` |
| `created_at` | `TIMESTAMPTZ` | escrito por el caso de uso, no `server_default` — el orden de subida importa |

**Sin `updated_at`**, y es una desviación consciente de `steering/backend.md` («toda entidad con
`tenant_id`, `created_at`, `updated_at`»): la fila es **inmutable tras el insert** —el puerto
declara `add` y `list_for_incident`, sin `save`—, así que la columna solo podría igualar a
`created_at` para siempre e invitaría a leerla como prueba de una edición que no puede ocurrir.
`cleaning_photos` no la lleva por lo mismo. Anotado al cerrar la sección 3, a petición del panel
de arquitectura, siguiendo el precedente con que `OwnerApproval` registra su propia omisión.

Índice `ix_incident_photos_tenant_id_incident_id`. **Sin restricción de unicidad** sobre
`(incident_id, stage)`: R1.4 pide admitir varias fotos de la misma etapa. **Sin** columnas de
`Content-Type`, de nombre de fichero (R1.5) ni de `ai_validation_result` (fuera de alcance).

En `incidents`: `UniqueConstraint("tenant_id", "id")` nuevo, sin cambio de columnas.

**Contrato HTTP.** Las tres rutas de D10. La subida es `multipart/form-data` con `stage` y `file`;
respuesta `201` con `IncidentPhotoResponse`. Códigos: `409` (tres mensajes distintos, D6), `422`
(formato no admitido y etapa desconocida), `413` (techo, desde el middleware), `502`
(`BAD_GATEWAY`, almacén), `404` (incidencia inalcanzable, indistinguible). La ruta anónima:
`200` con bytes + `Content-Type` derivado de la extensión + `nosniff` + `Cache-Control: private,
max-age=<lo que queda de la firma>`; `403` con cuerpo constante en los cuatro casos; `404` para
tenant `S3`; `502` si el objeto no se puede leer.

**Configuración:** ninguna variable de entorno nueva. `PHOTO_UPLOAD_MAX_BYTES` y `JWT_SECRET_KEY`
—de la que se deriva la clave de firma por HKDF— ya existen, así que `.env.example` no se toca.

## Risks & mitigations

- **Colisión de migraciones con `tech-cycle-completion`.** Esa feature está viva ahora mismo y va a
  migrar `incidents` (ETA, materiales). Dos revisiones de Alembic con el mismo padre dan dos heads y
  `tests/test_migrations.py` lo caza. Mitigación: rebase antes de abrir el PR y `alembic heads` como
  paso de verificación; el conflicto es mecánico (renumerar `down_revision`), no semántico, porque
  las dos revisiones tocan columnas distintas.
- **El `UNIQUE` sobre `incidents` es una migración sobre una tabla compartida.** En dev la tabla
  está prácticamente vacía y el índice es instantáneo; en un entorno con datos sería
  `CREATE UNIQUE INDEX` sobre `(tenant_id, id)`, que no puede fallar por duplicados porque `id` ya
  es PK. Riesgo real: bajo, y la alternativa de no tocar `incidents` se pesó y se rechazó en el gate
  (OQ2).
- **Migrar la ruta anónima de `cleaning` (D5) toca la superficie más sensible de la aplicación.**
  Mitigación: la suite de `cleaning` ya la fija byte a byte —`test_serve_photo_api.py` compara los
  cuerpos de refusal literalmente y `test_response_headers.py` fija el orden de los middlewares—,
  así que una regresión es ruidosa. La migración debe ser un movimiento sin cambio de
  comportamiento, verificado con la suite de `cleaning` **antes** de escribir nada de
  `maintenance`.
- **Regenerar el contrato desde un worktree no funciona con el comando documentado.** Es el rodeo
  conocido de `sdd/project.md` (copiar `openapi.json` y enlazar `/frontend` dentro del contenedor);
  además dos ficheros de test del frontend fallan con `ENOENT` en worktree por la misma causa. Hay
  que usar la receta de ese documento y no leer esos dos rojos como del change.
- **La rama del techo de cuerpo es más ancha que la ruta.** Riesgo aceptado y heredado de la rama de
  limpieza; se escribe en `app/main.py` junto a la rama, con su medida, en vez de dejarlo implícito.

## Open questions

Ninguna abierta. Las dos que este design planteó se resolvieron en el gate de `/sdd:design`
(2026-08-22, aprobadas por Jose) y quedan aquí con su alternativa rechazada, porque las decisiones
que gobiernan son D5 y D2 y ninguna de las dos se puede reconstruir después desde el resultado.

**OQ1 — ¿Extraer la ruta de servido firmada a `app/integrations/` y migrar `cleaning`, o calcarla
bajo `maintenance`?** (D5) → **extraer y migrar `cleaning` en el mismo PR.** Una sola casa para el
cuerpo `403` constante, el `nosniff`, el `Cache-Control` y el orden resolver→verificar→servir. Se
acepta a cambio que el PR toque `cleaning`, que el proposal declaraba no tocar, y que la migración
pase por la superficie anónima más expuesta de la aplicación — acotado por el riesgo escrito arriba:
el movimiento es sin cambio de comportamiento y se verifica con la suite de `cleaning` **antes** de
escribir nada de `maintenance`.

Rechazado: calcar los dos ficheros bajo `maintenance/` — PR acotado a lo que el proposal describe,
al precio de dos copias de ~400 líneas de una frontera de seguridad y de una entrada de roadmap
para la extracción que nadie garantiza que se haga.

**OQ2 — ¿Se acepta el `UniqueConstraint("tenant_id", "id")` sobre `incidents` que exige la clave
ajena compuesta?** (D2) → **sí, con la clave ajena compuesta.** El cruce de tenants entre foto e
incidencia deja de ser posible en la base de datos, siguiendo el precedente de `reservations` /
`guest_access_tokens`; `incidents.id` ya es clave primaria, así que el índice único no puede fallar
por duplicados preexistentes.

Rechazado: `tenant_id` en la fila con claves ajenas simples — cumple R1.3 igual y no toca
`incidents`, pero deja el invariante sostenido sólo por el repositorio, que es lo que los paneles
de `guest-portal-api` demostraron insuficiente para su caso.
