# Tasks: cleaning-photos-storage

Orden pensado para que el sistema siga en pie tras cada sección: 1-2 añaden infraestructura sin
tocar ninguna ruta viva; 3-4 añaden rutas nuevas; 5 es la única que **cambia comportamiento
existente** (el cierre pasa a exigir fotos) y por eso va después de que la subida funcione.

`domain/` lleva TDD por `steering/testing.md` (invariante real). `infrastructure/` no.

## 1. Puerto de almacenamiento y sus dos adaptadores <!-- panel: PASS 2026-08-08 -->
<!-- Panel: architect PASS · cicd PASS · documentation PASS · qa PASS · tenancy PASS (1 hallazgo
     bajo, arreglado) · security FAIL→PASS (3 hallazgos: 2 aceptados y arreglados, 1 rechazado
     por estar cubierto por la tarea 3.1). i18n omitido: cero ficheros de frontend en la sección.
     Arreglos aplicados: techo de TTL verificado también al verificar; codificación de firma
     inequívoca por prefijo de longitud (v1→v2); contrato de Content-Type derivado de la misma
     allowlist. Dos huecos de contrato trasladados a las tareas 4.3b/4.3c/4.4. -->



- [x] 1.1 Definir `FileStoragePort` (`put`, `signed_url`, `delete`) y `LocalFileReadPort` en
  `backend/app/integrations/domain/storage.py` (nuevo), con sus errores
  (`StorageWriteError`, `LocalFileReadUnsupportedError`, `InvalidSignatureError`). Docstrings que
  nombren por qué son **dos** puertos y no uno, citando el precedente `PMSMessagingPort`. Test de
  capas: `backend/tests/test_layering.py` sigue en verde (nada de `boto3`/`fastapi` en `domain/`). [R1]
- [x] 1.2 Allowlist de *magic bytes* (JPEG/PNG/WebP) en una **única constante** de
  `backend/app/integrations/domain/storage.py`, con función pura `detect_image_type(head: bytes)`.
  Tests unitarios: cada formato admitido, un PDF disfrazado de `.jpg`, un fichero vacío y uno más
  corto que la firma más larga. [R2]
- [x] 1.3 Derivación de clave de firma por HKDF de `JWT_SECRET_KEY` y firma
  `HMAC-SHA256("v1|" + key + "|" + expiry)` en `domain/storage.py`, verificada con
  `hmac.compare_digest`. Tests: firma válida, caducada, con `key` alterada, con `expiry` alterado,
  y con la firma truncada. **Función pura, sin I/O.** [R3]
- [x] 1.4 `LocalFileStorage` en `backend/app/integrations/infrastructure/storage/local.py` (nuevo):
  escribe bajo `/app/media/`, resuelve la ruta y **verifica que el resultado sigue dentro de la
  raíz** antes de tocar disco. Tests de integración incluyendo intento de traversal en la clave. [R1]
- [x] 1.5 `S3FileStorage` en `backend/app/integrations/infrastructure/storage/s3.py` (nuevo) con
  presigned URL de 3600 s. Marcado `EXTERNAL_DEPENDENCY`; se prueba contra el contrato del puerto
  y la sustituibilidad (SOLID-L), no contra AWS. Añadir `boto3` a las dependencias del backend. [R1, R3]
- [x] 1.6 Factory por `TenantConfig.storage_type` en `domain/storage.py`, con `read_for()` que lanza
  `LocalFileReadUnsupportedError` en `S3`. Tests: resuelve `LOCAL`, resuelve `S3`, y `read_for()`
  rechaza en `S3` **sin** instanciar nada. [R1]
- [x] 1.7 Clave de almacenamiento `tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{ext}`
  como función pura, con la extensión derivada del MIME detectado y **cero** uso del nombre de
  fichero del cliente. Tests que fijan el formato y prueban que dos tenants nunca colisionan. [R1]
- [x] 1.8 Ajustar `docker-compose.yml` y `docker-compose.deploy.yml` para montar un volumen con
  nombre en `/app/media/` del servicio `backend`, y verificar que `make up` sigue arrancando. [R1]

## 2. Repositorio de fotos, con el aislamiento demostrado <!-- panel: PASS 2026-08-08 -->
<!-- Panel: architect PASS · tenancy PASS (reprodujo el mutation testing de los 4 métodos) ·
     security FAIL y QA FAIL, ambos por el MISMO incidente de orquestación, no por el código.
     cicd/documentation/i18n omitidos: la sección no toca compose, Terraform, endpoints,
     variables de entorno ni frontend.

     INCIDENTE: pedí mutation testing (editar/correr/revertir) a tres revisores CONCURRENTES
     sobre el mismo fichero. Cada "revertir al original" restauraba un snapshot de un momento
     distinto, y QA revirtió con `git checkout --` sobre un fichero trackeado, destruyendo las
     ~200 líneas que la sección 2 le había añadido. Los tres "tests de aislamiento inestables"
     reportados coinciden uno a uno con la ventana de mutación de otro revisor: security y QA
     vieron fallar `list_for_task` mientras tenancy lo mutaba; yo vi fallar `get` 6 de 15 veces
     mientras QA lo mutaba. No hay fallo de aislamiento ni carrera en el arnés de test: con
     nadie más ejecutando, la suite completa da 4040 passed / 35 skipped, y
     `test_repositories.py` da 5 de 5 ejecuciones idénticas.

     Adaptador reconstruido desde el Protocol y los 8 tests supervivientes. La reconstrucción
     omitió silenciosamente `created_at=photo.created_at` y NINGUNO de los 8 tests lo detectó
     (la columna tiene `server_default`); se detectó comparando con la salida de un fallo
     anterior. Arreglado, y añadido el test que faltaba — verificado no-vacío por mutación con
     restauración desde copia, no con `git checkout`. -->



- [x] 2.1 `CleaningPhotoRepository` (Protocol) en `backend/app/cleaning/domain/repositories.py`:
  `add`, `list_for_task`, `get`, `uploaded_photo_types`. Sólo estos cuatro, cada uno con llamante
  en este change. [R6]
- [x] 2.2 `SqlAlchemyCleaningPhotoRepository` en
  `backend/app/cleaning/infrastructure/repositories.py`, con **`JOIN cleaning_tasks` obligatorio en
  todas las consultas** y filtro por el tenant de la sesión. Comentario que explique por qué el
  filtro global no cubre esta tabla (`core/db.py:62` selecciona por columna y `cleaning_photos` no
  tiene `tenant_id`). [R6]
- [x] 2.3 Tests de aislamiento del repositorio en `backend/tests/cleaning/`: una foto del tenant A
  no es alcanzable por `get`, `list_for_task` ni `uploaded_photo_types` desde el tenant B — **ni
  siquiera conociendo su UUID**. Modelado sobre los tests de `cleaning_checklist_completions`, que
  son el precedente de una tabla sin `tenant_id`. [R6]

## 3. Subida de foto <!-- panel: PASS 2026-08-08 -->
<!-- Panel: architect PASS · tenancy PASS (cierra las 3 obligaciones heredadas de las secciones
     1 y 2) · documentation FAIL→PASS (1) · security FAIL→PASS (3) · qa FAIL→PASS (2).
     cicd/i18n omitidos: ni workflows/Terraform, ni cadenas de UI.

     Siete arreglos aplicados: bloque `responses` del OpenAPI con 404/409/413/502 y las DOS
     mitades del contrato regeneradas; la `description` decía "never the internal storage path"
     y era FALSA para S3 (una presigned URL lleva bucket y clave por construcción) — corregida
     por backend, comportamiento intacto; el comentario de D11 afirmaba que el conteo en trozos
     protege de un `Content-Length` mentido, y no es cierto (`request.form()` vuelca la parte
     antes de resolver dependencias) — corregido en los dos sitios, sin quitar ninguna de las
     dos comprobaciones; docstring de `S3FileStorage` según D2b (protocolo, no proveedor;
     OCI Object Storage como candidato natural); riesgo aceptado de 10 MiB anónimos pre-auth
     registrado en `main.py`.

     Los dos hallazgos de QA valían la ronda entera:
     (a) `OVERSIZED` se calculaba a partir de `JSON_BODY_MAX_BYTES`, la misma constante que el
     test decía vigilar, así que subirla globalmente NO ponía el test en rojo — QA lo demostró
     mutando a 2 MiB y viendo pasar los tres tests. Ahora es un tamaño absoluto, verificado
     rojo-antes/verde-después.
     (b) mutar `uploaded_by=actor.user_id` a `task.assigned_cleaner_id` no mataba ningún test:
     mutante equivalente por construcción, porque sólo `CLEANER` tiene el permiso y `_load_task`
     ya obliga a que coincidan. Añadido un test unitario con un actor manager —estado hoy
     inalcanzable por HTTP— que distingue las dos fuentes; verificado no-vacío.

     INCIDENTE 2 (mismo error que en la sección 2, cometido otra vez): retomé a QA, que muta,
     mientras despachaba el agente de arreglos. QA dejó viva una sonda `JSON_BODY_MAX_BYTES =
     10 * 1024 * 1024  # MUTATION PROBE` en `http_limits.py`, es decir el techo de cuerpo a 10 MB
     en todo el backend. La detectó y restauró el agente de arreglos. No se perdió trabajo y los
     snapshots permitieron datar la contaminación como posterior a ellos. Suite reverificada por
     mí, en serie y a solas: 4081 passed / 35 skipped. -->



- [x] 3.1 Setting `photo_upload_max_bytes` (default `10485760`) en `backend/app/core/config.py`,
  espejo de `csv_import_max_bytes`, y su entrada en `.env.example` con comentario y **sin valor
  sensible**. [R2, R5]
- [x] 3.2 Rama nueva en el `max_bytes_provider` de `backend/app/main.py`, **antes** de la de
  `/cleaning-`, que case `/cleaning-tasks/` + final `/photos`. [R5]
- [x] 3.3 Test en rojo primero: un `POST` de >1 MiB a la ruta de fotos pasa el middleware, **y** un
  `POST` de >1 MiB a `/cleaning-checklist-templates` sigue siendo rechazado. El segundo es el que
  falla si alguien sube `JSON_BODY_MAX_BYTES` globalmente. [R5]
- [x] 3.4 `UploadCleaningPhotoUseCase` en `backend/app/cleaning/application/use_cases.py`: consume
  el `UploadFile` **en trozos contando bytes** y aborta al superar el tope (D11), detecta el MIME
  real, valida el `photo_type` contra la plantilla, exige `IN_PROGRESS`, escribe objeto → fila, y
  **borra el objeto si el commit falla**. Tests con fakes del puerto: camino feliz, `photo_type`
  desconocido → 404, tarea no `IN_PROGRESS` → 409, MIME no admitido → 422, tamaño excedido → 413,
  fallo del almacén → 502, y fallo de commit → se llamó a `delete`.
  **Obligación heredada del panel de la sección 1**: toda `storage_key` se construye
  exclusivamente con `storage_key_for_photo` a partir del `tenant_id` de la sesión autenticada —
  ningún caso de uso ni endpoint acepta, reenvía ni serializa una clave venida del cliente. Los
  métodos del puerto aceptan una `key` arbitraria a propósito, así que esta garantía vive aquí y
  en ningún otro sitio.
  **Y `uploaded_by` sale del principal autenticado, nunca del cuerpo de la petición** (panel de
  la sección 2): la FK a `users.id` no está restringida por tenant y `add` la escribe verbatim,
  así que un id de otro tenant quedaría registrado como autor. El repositorio no lo comprueba
  a propósito —es el patrón de la casa, igual que `completed_by`— luego la garantía es de aquí. [R1, R2, R6]
- [x] 3.5 `POST /api/v1/cleaning-tasks/{id}/photos` en
  `backend/app/cleaning/api/tasks_router.py` + DTOs en `schemas.py` + DI en `dependencies.py` +
  mapeo de errores en `errors.py`. Permiso `EXECUTE_CLEANING_TASKS`, CLEANER asignada. Retirar la
  nota de `tasks_router.py:3-6` que declara la ruta ausente. Tests de integración de la ruta. [R2]
- [x] 3.6 `AuditLog` de la subida con actor e IP, siguiendo el contrato de la regla 11 de
  `steering/security.md` que ya cumplen las demás operaciones de limpieza. Test que lo verifica. [R2]
- [x] 3.7 Test de aislamiento de la ruta: subir a una tarea de otro tenant responde `404` con
  cuerpo **idéntico** al de un id inexistente; y una `CLEANER` no puede subir a una tarea que no es
  suya. [R6]

## 4. Listado y servido firmado

- [x] 4.1 `ListCleaningPhotosUseCase` que devuelve las fotos con su URL firmada, **sin
  `storage_key`**. Tests con fakes: la respuesta no contiene la clave interna por ningún campo.
  **El schema de respuesta es lista blanca de campos, no exclusión** (panel de la sección 2): la
  entidad de dominio `CleaningPhoto` **sí** arrastra `storage_key` —lo necesita el firmante— así
  que cualquier `model_validate`/`from_attributes`/`asdict` sobre ella publica R3.2 por accidente.
  El test debe fallar si `storage_key` aparece en el cuerpo serializado, no comprobar sólo que el
  DTO no lo declara. [R3]
- [x] 4.2 `GET /api/v1/cleaning-tasks/{id}/photos` en `tasks_router.py`, con la misma autorización
  que el resto (CLEANER sólo las suyas, manager/owner todas las del tenant). Tests de integración
  y de cruce de tenant. [R3, R6]
- [x] 4.3 `ServeLocalCleaningPhotoUseCase` + `backend/app/cleaning/api/photos_router.py` (nuevo):
  `GET /api/v1/cleaning-photos/{photo_id}` **anónimo**, verifica firma y caducidad antes de
  devolver bytes, y responde `403` idéntico ante firma inválida, caducada, manipulada o foto
  inexistente. Montar el router en `main.py`. La clave se reconstruye **desde la fila de BD**,
  nunca desde el cliente (obligación heredada del panel de la sección 1).
  **Resolución del tenant — ver D7b, hueco encontrado al implementar la sección 2**: la ruta es
  anónima, así que no hay `tenant_id` de sesión, y hace falta dos veces (leer la fila y resolver
  `storage_type` para decidir el `404` de la 4.4). `CleaningPhotoRepository.get` exige el tenant
  por construcción y no sirve aquí. Usa una lectura **explícitamente sin tenant**, acotada a esta
  ruta y fuera de `CleaningPhotoRepository`, que resuelva `photo_id → (storage_key, tenant_id)`;
  reconstruye la clave y **sólo entonces** verifica la firma. El orden es la garantía: la firma
  cubre la clave, que empieza por `tenants/{tenant_id}/`, así que una firma válida demuestra que
  la URL se emitió para esa foto de ese tenant. Test propio de que el orden es
  «resolver → verificar → servir» y nunca al revés. [R3, R6]
- [x] 4.3b **El cuerpo del `403` es una constante, y `str(exc)` NO se serializa en esta ruta.**
  El panel de la sección 1 detectó que `InvalidSignatureError` tiene ahora tres mensajes distintos
  ("does not match" / "has expired" / "outlives the maximum lifetime") mientras su contrato entero
  es la indistinguibilidad; el patrón de la casa (`cleaning/api/errors.py:66`) mapea con
  `message = str(exc)`, así que seguirlo aquí convertiría la ruta en un **oráculo de existencia
  sobre el espacio de claves**, para un atacante sin credenciales. Los tres mensajes se conservan
  **para el log**, no para la respuesta. [R3]
- [x] 4.3c **El `Content-Type` sale exclusivamente de `content_type_for_extension`** y la
  respuesta lleva **`X-Content-Type-Options: nosniff`**, obligatorio. Sin esto, un polyglot que
  empiece por `FF D8 FF` y contenga HTML es **XSS almacenado sobre el origen de `/api/v1`**, que
  `api-ingress-routing` dejó alcanzable desde internet. Derivarlo de otra cosa, u omitirlo y
  dejar que Starlette adivine, es el fallo exacto que esa función existe para impedir. [R3]
- [x] 4.4 Tests de la ruta anónima: firma válida sirve bytes; caducada → 403; `sig` de otra foto →
  403; foto inexistente → 403 **con el mismo cuerpo byte a byte** que una firma mala; y con
  `storage_type = S3` la ruta responde `404` (no hay servido local). **Además**: assert de que la
  respuesta lleva `X-Content-Type-Options: nosniff` y que el `Content-Type` es el de la extensión
  de la clave — ninguna de las dos cosas la verificaba nadie. [R3, R6]

## 5. La tercera cláusula de PRD §11 <!-- panel: PASS 2026-08-09 -->
<!-- Panel: qa PASS (4 mutaciones, las 4 muertas) · tenancy FAIL→PASS (1) · architect FAIL→
     arbitrado (ver la nota de 5.4) · security FAIL→PASS (1). documentation omitido: su único
     ítem real es la tarea 6.2, ya ampliada, y el contrato se verificó sincronizado.

     TDD probado, no declarado: pedí el mensaje exacto del rojo y llegó en dos etapas —
     `ImportError: cannot import name 'PhotosIncompleteError'` y después, con la excepción ya
     añadida pero antes de tocar `complete()`, `Failed: DID NOT RAISE PhotosIncompleteError`.

     5 tests de cierre existentes ajustados SUBIENDO la foto por el endpoint real. `STANDARD_PHOTOS`
     quedó byte a byte intacto (verificado por mí en el diff y por QA revisando cada llamada al
     nuevo `insert_template(required_photos=...)`). Ningún fixture relajado.

     Hallazgo colateral que no pedía ninguna tarea: dos tests pasaban POR LA RAZÓN EQUIVOCADA
     (`..._while_a_guest_is_in_is_a_conflict` y `..._critical_incident_blocks_completion` daban
     409 por falta de fotos, no por lo que decían probar). Corregidos y ahora atribuibles.

     Arreglos: docstring del test de foto ajena, que no podía fallar —el filtro por `cleaning_task_id`
     excluye la fila antes de que el de tenant intervenga— renombrado a
     `test_a_photo_of_another_task_does_not_unlock_this_close` y remitiendo la propiedad de tenant
     a `test_repositories.py`; promesa de `nosniff` acotada a las salidas que el módulo construye
     (el 422/405 los contesta el handler global); `private` deja de "prohibir" y pasa a "instruir",
     con el residuo escrito; y la fila paramétrica de `PhotosIncompleteError` en `test_errors.py`,
     verificada no-vacía por mutación (`assert 422 == 409`). -->



- [x] 5.1 **Test primero** (TDD, `steering/testing.md`): en `backend/tests/cleaning/`, un test que
  exija que `CleaningTask.complete()` falle cuando falta una foto `required` y enumere los
  `photo_type` que faltan, ordenados. Debe fallar en rojo antes de tocar la entidad. [R4]
- [x] 5.2 Extender `CleaningCompletionEvidence` en
  `backend/app/cleaning/domain/value_objects.py` con `required_photo_types`,
  `uploaded_photo_types` y `missing_required_photo_types()` ordenado, espejo del que ya existe
  para ítems. Actualizar su docstring. [R4]
- [x] 5.3 `PhotosIncompleteError` en `backend/app/cleaning/domain/exceptions.py` y su aplicación en
  `CleaningTask.complete()` (`entities.py`), **después** de los ítems y antes de la incidencia
  crítica. Reescribir el docstring que hoy dice que la cláusula no se aplica. [R4]
<!-- DESVIACIÓN ARBITRADA en 5.4 — se pidieron tests con FAKES y se hicieron de INTEGRACIÓN.
     El implementador la justificó diciendo que no había precedente de fakes en el repositorio.
     Esa afirmación era FALSA y el arquitecto lo demostró: `test_photo_upload_use_case.py` testea
     `UploadCleaningPhotoUseCase` íntegramente con fakes, y lo escribió él mismo en la sección 3.
     También se contó 7 colaboradores cuando son 11.
     PERO QA afinó con más precisión: no existe ningún test con fakes para el camino positivo de
     NINGÚN caso de uso del ciclo de vida (Accept/Start/Reject/Complete). Los tres que sí los
     tienen —upload, listing, serve— son los que este change creó, con muchos menos colaboradores.
     El precedente para *cerrar* siempre fue integración vía `test_tasks_api.py`.
     ARBITRAJE: se acepta la desviación. Los tres escenarios que 5.4 pedía están cubiertos, y la
     mutación (b) de QA —cambiar `required_photo_types()` por `photo_types()`— los demuestra
     no-vacíos. Lo que se pierde es aislamiento y velocidad, no cobertura semántica. Forzar los
     fakes serían ~150 líneas de maquinaria nueva para cobertura que ya existe.
     Queda registrado que la justificación literal era falsa, y en `BLOCKED.md` §6(a) el candidato
     a extraer un `CompletionEvidenceGatherer`, que es lo que haría los fakes baratos. -->
- [x] 5.4 `CompleteCleaningTaskUseCase` pasa a leer `uploaded_photo_types` del repositorio nuevo y
  a poblar la evidencia. Tests con fakes: cierre bloqueado sin fotos, permitido con ellas, y
  **permitido cuando la plantilla no declara ninguna foto `required`** (R4.5). [R4]
- [x] 5.5 Mapeo de `PhotosIncompleteError` → `409` con `missing_photo_types` en
  `backend/app/cleaning/api/errors.py`, en el envelope de PRD §23 y con la misma forma que el 409
  de ítems. Test de integración del cierre completo: subir fotos → cerrar → `COMPLETED`. [R4]
- [x] 5.6 Revisar los tests existentes de cierre en `backend/tests/cleaning/` que ahora fallarán
  por no tener fotos: **ajustarlos añadiendo las fotos que la plantilla exige**, nunca relajando la
  plantilla del fixture para esquivar la regla nueva. [R4]

## 6. Contrato, documentación y verificación

- [x] 6.1 Anotar `summary`/`description` y modelos de respuesta de las tres rutas nuevas, regenerar
  `backend/openapi.json` con `make openapi` **y** `frontend/lib/api/generated/openapi.d.ts` con
  `cd frontend && npm run api:generate`, y commitear **los dos** — son las dos mitades del mismo
  puente (`steering/documentation.md`; `cleaning` rompió `main` por hacer sólo una). [R2, R3]
- [x] 6.2 `README.md` de raíz: reflejar el módulo nuevo `app/integrations/infrastructure/storage/`
  y el volumen `/app/media/` en las secciones de estructura y arranque.
  **Y `docs/cleaning.md`**, que hoy dice que las fotos «todavía no se piden» al cerrar — cierto
  mientras la sección 5 no aterrice y **falso en cuanto lo haga** (lo localizó el panel de la
  sección 4, líneas 82-86). Documentar además el flujo operativo de la subida y **el coste del
  volumen**: `docker compose down -v` se lleva las fotos, que es el riesgo que el diseño mandó
  escribir aquí y no sólo en el compose. [R1, R4]
- [x] 6.3 Suite completa del backend en verde:
  `docker compose exec backend uv run pytest`. [R1-R6]
- [x] 6.4 Lint y typecheck del backend según la configuración del proyecto, y typecheck del
  frontend contra los tipos regenerados (`frontend-api-contract` falla si hay deriva). [R1-R6]
- [x] 6.5 Comprobación manual extremo a extremo con el stack del worktree: crear tarea → `IN_PROGRESS`
  → subir foto → listarla → abrir la URL firmada → intentar cerrar sin todas las fotos (409) →
  subirlas → cerrar (200). Dejar constancia del resultado en el `/sdd:review`. [R1-R6]
