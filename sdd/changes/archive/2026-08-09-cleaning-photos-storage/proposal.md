# Proposal: cleaning-photos-storage

## Why

`cleaning` (archivado 2026-08-08) implementó la regla de validación de PRD §11 **sin su
cláusula de fotos**: hoy una limpiadora puede cerrar una tarea sin haber subido ni una sola de
las fotos que la plantilla marca como obligatorias. No es un descuido, es un recorte declarado
—`specs/cleaning.md` §Cierre y validación lo dice, y el docstring de `CleaningTask.complete`
(`backend/app/cleaning/domain/entities.py:132-137`) lo repite— pero deja exactamente el mismo
tipo de hueco que `cleaning` vino a cerrar: la regla existe y no se puede ejercitar.

La razón de que no entrara allí es que **el puerto de almacenamiento no existe**. No hay
`StoragePort` ni `StorageAdapter` en ningún dominio del backend, ni `boto3`, ni ninguna noción
de signed URL. Y dimensionarlo no es una firma que se escriba de paso:
`steering/backend-architecture.md` nombra al «`StorageAdapter` gigante con 15 métodos» como
*su* ejemplo de fallo de segregación de interfaces, y el docstring de
`backend/app/integrations/domain/ports.py:11` lo cita como el precedente por el que `PMSAdapter`
se dejó en dos métodos. Es una decisión de arquitectura con referente en el steering.

Las dos rutas de PRD §23 (`POST`/`GET /api/v1/cleaning-tasks/{id}/photos`) son las dos únicas de
las doce que `cleaning` dejó **deliberadamente ausentes en vez de stubbed**
(`backend/app/cleaning/api/tasks_router.py:3-6`).

Entrada de roadmap: `cleaning-photos-storage` (`completes: cleaning · size: M · kind: feature`),
con su nota larga en `sdd/roadmap/cleaning-photos-storage.md`.

## What changes

Después de este change existe un puerto de almacenamiento de ficheros acotado, con
implementación `LOCAL` y `S3` seleccionada por `TenantConfig.storage_type`, y las dos rutas de
fotos de PRD §23 sobre él: subir una foto de limpieza validando MIME y tamaño, y listar las
fotos de una tarea con URLs firmadas de caducidad 3600 s que nunca exponen la clave interna. Con
la subida en pie, `CleaningTask.complete()` pasa a exigir también las fotos `required: true` de
la plantilla, cerrando la tercera cláusula de PRD §11. El terreno ya está preparado:
`RequiredPhotoSpec` (`backend/app/cleaning/domain/value_objects.py:53-62`) se valida y se
transporta desde `cleaning` sin aplicarse, y `CleaningCompletionEvidence` está diseñado para
recibir la evidencia desde el caso de uso — así que esto **añade una comprobación, no un
parser**.

## Requirements

### R1 — Puerto de almacenamiento acotado, con sus dos implementaciones

**As a** equipo de backend, **I want** un puerto de almacenamiento de ficheros mínimo con
adaptadores `LOCAL` y `S3`, **so that** las fotos se guarden fuera de la base de datos sin
acoplar el dominio a un proveedor ni repetir el fallo de segregación que el steering ya nombra.

Acceptance criteria:

1. THE SYSTEM SHALL definir el puerto de almacenamiento en la capa de dominio con **como mucho
   cuatro métodos**, y cada método declarado SHALL tener al menos un llamante en este change —
   un método sin consumidor es exactamente el fallo de segregación que
   `steering/backend-architecture.md` nombra.
2. THE SYSTEM SHALL resolver la implementación a partir de `TenantConfig.storage_type` (enum
   `LOCAL`/`S3` ya existente en `backend/app/tenants/domain/enums.py:10`), sin que ningún caso
   de uso conozca cuál está activa.
3. WHERE `storage_type` es `LOCAL`, THE SYSTEM SHALL persistir bajo `/app/media/` (PRD §4
   §Almacenamiento de archivos), montado en volumen, y no dentro del árbol de código.
4. THE SYSTEM SHALL derivar la clave de almacenamiento de forma que incluya el `tenant_id`, de
   modo que dos tenants no puedan colisionar en el mismo objeto ni por colisión de UUID de
   tarea ni por `photo_type` repetido.
5. IF la escritura en el almacén falla, THEN THE SYSTEM SHALL no dejar fila de `CleaningPhoto`
   apuntando a un objeto inexistente, y responder `502` en el envelope de PRD §23.
6. THE SYSTEM SHALL exponer el `storage_type` como configuración de sólo lectura: `PATCH` de
   `TenantConfig` sigue sin admitirlo, conforme a R5.4 de `user-management`.

### R2 — Subida de foto de limpieza

**As a** limpiadora asignada, **I want** subir las fotos que la plantilla exige, **so that**
pueda cerrar la tarea y el manager tenga evidencia de lo hecho.

Acceptance criteria:

1. WHEN la limpiadora asignada solicita `POST /api/v1/cleaning-tasks/{id}/photos` con un
   fichero y un `photo_type`, THE SYSTEM SHALL almacenar el fichero, persistir una fila de
   `CleaningPhoto` con `uploaded_by`, `photo_type` y `storage_key`, y responder `201`.
2. IF el `photo_type` no pertenece a las `required_photos` de la plantilla de la tarea, THEN
   THE SYSTEM SHALL responder `404`, del mismo modo que el checklist hace con un `item_id`
   desconocido.
3. IF la tarea no está en `IN_PROGRESS`, THEN THE SYSTEM SHALL responder `409` sin escribir
   nada — ni fila ni objeto en el almacén.
4. THE SYSTEM SHALL validar el **MIME real del contenido** y no sólo la cabecera declarada por
   el cliente, admitiendo únicamente formatos de imagen, y responder `422` en caso contrario
   (regla 6 de `steering/security.md`).
5. THE SYSTEM SHALL rechazar ficheros por encima de un tamaño máximo **configurable con default
   10 MB** (regla 6), antes de leer el cuerpo completo, y responder `413`.
6. THE SYSTEM SHALL admitir varias fotos del mismo `photo_type` para una misma tarea, y THE
   SYSTEM SHALL exigir el permiso `EXECUTE_CLEANING_TASKS`, exclusivo del `CLEANER` asignado.
7. THE SYSTEM SHALL registrar la subida en `AuditLog` con su actor y su IP, como el resto de
   operaciones de limpieza iniciadas por una persona.

### R3 — Listado con URL firmada, sin exponer la clave interna

**As a** manager o limpiadora, **I want** ver las fotos de una tarea, **so that** pueda validar
el trabajo sin que el sistema publique rutas internas de almacenamiento.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/cleaning-tasks/{id}/photos`, THE SYSTEM SHALL devolver las
   fotos de esa tarea con una **URL firmada de caducidad 3600 s** por foto (regla 5 de
   `steering/security.md`).
2. THE SYSTEM SHALL no incluir `storage_key` ni ninguna ruta interna en ninguna respuesta de la
   API, ni en el cuerpo ni en cabeceras.
3. WHERE `storage_type` es `LOCAL`, THE SYSTEM SHALL servir el fichero desde un endpoint propio
   que **verifique la firma y su caducidad** antes de devolver bytes — una ruta de disco no
   satisface la regla 5.
4. IF la firma es inválida, ha caducado o ha sido manipulada, THEN THE SYSTEM SHALL responder
   `403` sin revelar si la clave existe.
5. THE SYSTEM SHALL comparar la firma en tiempo constante.

### R4 — El cierre exige las fotos requeridas (tercera cláusula de PRD §11)

**As a** propietario, **I want** que una limpieza no pueda cerrarse sin las fotos obligatorias,
**so that** la regla de validación del PRD se cumpla entera y no a dos tercios.

Acceptance criteria:

1. WHEN la limpiadora asignada cierra la tarea, THE SYSTEM SHALL verificar —además de los ítems
   `required` y de la ausencia de incidencia `CRITICAL` sin resolver— que existe al menos una
   foto subida para **cada** `photo_type` con `required: true` de la plantilla.
2. IF falta alguna foto requerida, THEN THE SYSTEM SHALL responder `409` **enumerando los
   `photo_type` que faltan**, en el mismo formato en que hoy enumera los ítems.
3. THE SYSTEM SHALL aplicar la regla dentro de `CleaningTask.complete()`, extendiendo
   `CleaningCompletionEvidence`, y no en el caso de uso ni en el router — la invariante de
   PRD §11 tiene un único lugar y sigue teniéndolo.
4. THE SYSTEM SHALL ordenar la enumeración de forma estable, como ya hace
   `missing_required_item_ids()`.
5. WHERE la plantilla no declara ninguna foto `required: true`, THE SYSTEM SHALL permitir el
   cierre sin fotos — la regla es «las requeridas», no «alguna».

### R5 — La ruta de subida sale del techo JSON sin quitárselo al resto

**As a** equipo de backend, **I want** que el límite de cuerpo de la ruta de fotos sea el suyo,
**so that** subir una foto de 10 MB funcione sin reabrir el agujero que `cleaning` cerró en el
resto de rutas de limpieza.

Acceptance criteria:

1. THE SYSTEM SHALL aplicar a `POST /api/v1/cleaning-tasks/{id}/photos` el tope de tamaño de
   R2.5 y **no** el `JSON_BODY_MAX_BYTES` de 1 MiB que hoy cubre el prefijo `/cleaning-`
   (`backend/app/main.py:115-121`).
2. THE SYSTEM SHALL mantener el techo de 1 MiB para **todas** las demás rutas bajo `/cleaning-`,
   y THE SYSTEM SHALL demostrarlo con un test en rojo que falle si alguien lo sube globalmente.
3. THE SYSTEM SHALL rechazar el cuerpo sobredimensionado **antes** de leerlo entero, como ya
   hace el middleware para JSON.

### R6 — Aislamiento entre tenants de una tabla sin `tenant_id`

**As a** operador de la plataforma, **I want** que las fotos de un tenant sean inalcanzables
desde otro, **so that** la regla 1 de `steering/security.md` se cumpla también donde el filtro
global no llega.

Acceptance criteria:

1. THE SYSTEM SHALL derivar el aislamiento de `cleaning_photos` del `JOIN` con
   `cleaning_tasks`: la tabla **no tiene columna `tenant_id`** —scoping transitivo decidido en
   `domain-foundation-ops`— y `tenant_scoped_classes()` (`backend/app/core/db.py:62`) selecciona
   por columna, así que el filtro global de defensa en profundidad **no la cubre**.
2. THE SYSTEM SHALL demostrar con tests propios que ni el listado, ni la subida, ni la URL
   firmada alcanzan una foto de otro tenant.
3. IF se referencia una tarea de otro tenant, THEN THE SYSTEM SHALL responder `404` con un
   cuerpo **idéntico** al de un identificador inexistente.
4. WHILE el solicitante tiene rol `CLEANER`, THE SYSTEM SHALL admitir subida y listado **solo**
   sobre las tareas cuya `assigned_cleaner_id` sea la suya, derivado del rol persistido y no de
   ningún parámetro de la petición.

## Out of scope

- **Validación automática con IA de las fotos** (`cleaning_photos.ai_validation_result`).
  Depende de `MockAIAdapter`, que llega con `messaging-ai` (PRD §26.12). La columna existe
  (`backend/app/cleaning/infrastructure/models.py:125`) y sigue sin escritor.
- **Toda la UI de subida** — es de `field-apps` (PRD §26.19). Este change entrega la API.
- **Hacer escribible `TenantConfig.storage_type`** — `user-management` lo dejó deliberadamente
  no escribible (su R5.4): cambiarlo apuntaría a las fotos ya subidas a un sitio donde no están.
  Migrar objetos entre backends al cambiarlo es un problema propio, y no se abre aquí.
- **Fotos de incidentes/mantenimiento** (PRD §12) y **justificantes de gasto**
  (`expenses.receipt_storage_key`, PRD §7.x). Son consumidores futuros del mismo puerto; entran
  con `maintenance` y `revenue` respectivamente. El puerto se dimensiona para admitirlos, pero
  no se implementan sus rutas.
- **Borrado de fotos.** PRD §23 no declara `DELETE` y la evidencia de una limpieza cerrada no
  debería poder desaparecer sin una decisión de retención que nadie ha tomado.
- **Antivirus / escaneo de contenido** de lo subido. Es superficie propia y sin decisión previa.

## Affected specs

- `sdd/specs/cleaning.md` — **existe**. Se levanta la nota «La cláusula de fotos de PRD §11 no
  se aplica todavía» (líneas 115-118), se añaden las dos rutas y sus reglas, y se actualiza
  §Cierre y validación y §Key files.
- `sdd/specs/api-contract.md` — **existe**. Dos endpoints nuevos (más el de servido firmado en
  `LOCAL`) entran en el contrato OpenAPI versionado; `steering/documentation.md` exige
  regenerar `backend/openapi.json` **y** `frontend/lib/api/generated/openapi.d.ts` en el mismo
  PR.
- `sdd/specs/file-storage.md` — *(no existe aún — se creará al archivar)*. El puerto de
  almacenamiento es una capability compartida con futuros consumidores (`maintenance`,
  `revenue`), no un detalle de limpieza. **Si `/sdd:design` concluye que el puerto no merece
  spec propia todavía**, su contenido va a `sdd/specs/cleaning.md` y esta entrada decae.
- `sdd/specs/user-management.md` — **existe**. Sólo si el diseño toca la superficie de
  `TenantConfig`; hoy no se espera (R1.6 mantiene el statu quo).
