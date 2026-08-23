# Tasks: incident-photos

> Orden general: primero la extracción compartida de la ruta firmada con `cleaning` migrado y
> verde (D5, y el riesgo escrito en design.md manda hacerlo **antes** de escribir nada de
> `maintenance`), luego el dominio, la persistencia, los casos de uso y las tres rutas. Tras cada
> sección la aplicación arranca y su suite pasa.

## 1. Extracción de la ruta de servido firmada a `app/integrations/` (D5) <!-- panel: PASS 2026-08-22 -->

Sin cambio de comportamiento observable. `cleaning` queda migrado y su suite verde antes de que
exista una sola línea de `maintenance`.

- [x] 1.1 Añadir a `backend/app/integrations/domain/storage.py` el value object `ObjectLocation`
      (`storage_key`, `tenant_id`) y el puerto `UnscopedObjectLocationQuery` con
      `locate_without_tenant_scoping(object_id) -> ObjectLocation | None`. Test en
      `backend/tests/integrations/test_storage_ports.py`: el puerto es abstracto y `ObjectLocation`
      no expone nada más. No se toca `FileStoragePort`, `LocalFileReadPort` ni
      `FileStorageFactory`. [R4]
- [x] 1.2 Crear `backend/app/integrations/application/signed_serving.py` con
      `ServeSignedObjectUseCase`: orden **resolver → verificar firma → servir bytes**, y los tres
      refusals (firma inválida / caducada / objeto inexistente) colapsados en un único
      `InvalidSignatureError`. Mover aquí el cuerpo de `ServeLocalCleaningPhotoUseCase`
      (`app/cleaning/application/use_cases.py`). Test nuevo
      `backend/tests/integrations/test_signed_serving_use_case.py` que fija el orden (una firma
      válida contra un id inexistente no revela nada) y la respuesta `404` para tenant `S3`. [R4]
- [x] 1.3 Crear `backend/app/integrations/api/signed_media.py` con
      `build_signed_media_router(*, prefix, tag, log_event, use_case_dep)`: cuerpo `403`
      **constante y precomputado**, `X-Content-Type-Options: nosniff` con un solo valor,
      `Cache-Control: private, max-age=<lo que le queda a la firma>` en el `200` y `no-store` en
      las negativas, y el bloque `responses` con los media types de la allowlist. [R4]
- [x] 1.4 Migrar `cleaning` al par compartido: `app/cleaning/api/photos_router.py` se construye con
      el factory, `ServeLocalCleaningPhotoUseCase` desaparece a favor del caso de uso compartido y
      `app/cleaning/api/dependencies.py` inyecta el adaptador
      `SqlAlchemyUnscopedCleaningPhotoLocationQuery` como `UnscopedObjectLocationQuery`. **Sin
      cambio de contrato**: el prefijo `/api/v1/cleaning-photos/{photo_id}` y todos los cuerpos se
      conservan byte a byte. [R4]
- [x] 1.5 Correr la suite de `cleaning` y las de postura HTTP como puerta de esta sección —
      `docker compose exec backend uv run pytest tests/cleaning tests/test_response_headers.py tests/test_route_authorization.py tests/test_unscoped_reads.py tests/test_layering.py` — sin
      relajar ni reescribir ninguna aserción existente de `test_serve_photo_api.py`
      (compara los cuerpos de refusal literalmente). Si algo obliga a cambiar una aserción, es una
      regresión, no una actualización. [R4]

## 2. La clave de almacenamiento de la foto de incidente (D4) <!-- panel: PASS 2026-08-22 -->

- [x] 2.1 En `backend/app/integrations/domain/storage.py`: extraer el cuerpo común a
      `_photo_storage_key(*, tenant_id, collection, owner_id, photo_id, extension)` —una sola casa
      para la guarda de `ACCEPTED_EXTENSIONS`— y añadir
      `storage_key_for_incident_photo(*, tenant_id, incident_id, photo_id, extension)` →
      `tenants/{tenant_id}/incidents/{incident_id}/{photo_id}.{ext}`. La función pública de limpieza
      conserva su firma y su call site. Tests en
      `backend/tests/integrations/test_storage_keys.py`: la clave nueva, la vieja intacta, y la
      extensión fuera de la allowlist rechazada por las dos. [R1]

## 3. Dominio: enum, entidad y la puerta por estado (D3, D6) <!-- panel: PASS 2026-08-22 -->

TDD en `domain/` (invariante real: la puerta de estado y su orden de refusals).

- [x] 3.1 `backend/app/maintenance/domain/enums.py`: `IncidentPhotoStage(str, Enum)` con **solo**
      `BEFORE` y `AFTER`, marcado `ASSUMPTION` (no está en el PRD). Test en
      `backend/tests/maintenance/test_entities.py` que fija los dos miembros y falla si aparece un
      tercero. [R1]
- [x] 3.2 `backend/app/maintenance/domain/entities.py`: entidad `IncidentPhoto` con `id`,
      `tenant_id`, `incident_id`, `uploaded_by`, `stage`, `storage_key`, `created_at` — sin campo de
      `Content-Type` ni de nombre de fichero del cliente. Marcada `ASSUMPTION` con la remisión a
      PRD §7.13/§7.12. Test de construcción en `backend/tests/maintenance/test_entities.py`. [R1]
- [x] 3.3 **Test primero**: en `backend/tests/maintenance/test_entities.py`, los cuatro casos de
      `Incident.ensure_accepts_photo()` — `RESOLVED`/`CANCELLED` → `IncidentAlreadyClosedError`;
      `AWAITING_OWNER_APPROVAL` → `IncidentBlockedByPendingApprovalError`; cualquier otro estado que
      no sea `IN_PROGRESS`/`WAITING_EXTERNAL_PARTS` → `InvalidIncidentTransitionError`;
      `IN_PROGRESS` y `WAITING_EXTERNAL_PARTS` → no lanza. El test debe distinguir los tres errores,
      no solo el `409`. [R2]
- [x] 3.4 Implementar `Incident.ensure_accepts_photo()` en
      `backend/app/maintenance/domain/entities.py`, extrayendo las dos primeras ramas de
      `_check_transition` a un helper privado compartido para que el orden tenga una sola casa. El
      método **no muta**. Correr `tests/maintenance/test_entities.py` completo: todas las
      transiciones existentes siguen pasando. [R2]
- [x] 3.5 `backend/app/maintenance/domain/repositories.py`: puerto `IncidentPhotoRepository` con
      `add(photo)` y `list_for_incident(incident_id)` (orden ascendente por `created_at`). [R1, R3]

## 4. Persistencia: modelo, `UNIQUE` en `incidents`, migración y adaptadores (D2, D13) <!-- panel: PASS 2026-08-22 -->

- [x] 4.1 `backend/app/maintenance/infrastructure/models.py`: `IncidentPhotoModel` con
      `UUIDPrimaryKeyMixin` + `TenantScopedMixin`, `incident_id`, `uploaded_by` (FK a `users.id`,
      `ON DELETE RESTRICT`), `stage` como
      `Enum(IncidentPhotoStage, name="incident_photo_stage", native_enum=True)`,
      `storage_key String(500)`, `created_at TIMESTAMPTZ` **sin** `server_default`, el
      `ForeignKeyConstraint(["tenant_id","incident_id"] → ["incidents.tenant_id","incidents.id"],
      ondelete="RESTRICT")` y el índice `ix_incident_photos_tenant_id_incident_id`. **Sin** unicidad
      sobre `(incident_id, stage)`. [R1]
- [x] 4.2 En el mismo fichero, añadir `UniqueConstraint("tenant_id", "id", name="uq_incidents_tenant_id_id")`
      a `IncidentModel` (sin cambio de columnas), que es lo que hace posible la clave ajena compuesta
      de 4.1. [R1]
- [x] 4.3 Tests de modelo en `backend/tests/maintenance/test_models.py`: la tabla existe con sus
      columnas y tipos, admite **dos filas de la misma etapa** para la misma incidencia (R1.4), no
      tiene columna de `Content-Type` ni de nombre de fichero (R1.5), y una fila que empareje el
      `tenant_id` de A con una incidencia de B es **rechazada por la base de datos** (R1.3/D2).
      Verificar además que `incident_photos` entra en `tenant_scoped_classes()` y por tanto bajo el
      filtro global de `app/core/db.py`. [R1, R6]
- [x] 4.4 Una revisión de Alembic en `backend/alembic/versions/`: tipo `incident_photo_stage`, tabla
      `incident_photos` con sus constraints e índice, y el `UNIQUE (tenant_id, id)` sobre
      `incidents`. `down_revision` desde el head actual y `downgrade` que revierta las dos tablas y
      el tipo. Verificar con `docker compose exec backend uv run alembic heads` (un solo head) y
      `uv run pytest tests/test_migrations.py`. [R1]
- [x] 4.5 `backend/app/maintenance/infrastructure/repositories.py`:
      `SqlAlchemyIncidentPhotoRepository` (`add`, `list_for_incident` ordenado ascendente). Tests en
      `backend/tests/maintenance/test_repositories.py`, incluido el orden de la lista. [R1, R3]
- [x] 4.6 En el mismo fichero, `SqlAlchemyUnscopedIncidentPhotoLocationQuery` — **clase aparte** del
      repositorio de fotos, que llama `require_unmarked_session(...)` antes de consultar y devuelve
      `ObjectLocation(storage_key, tenant_id)` desde una sola tabla (sin `JOIN`, gracias a D2). Test
      en `backend/tests/maintenance/test_repositories.py` que demuestra que **falla** sobre una
      sesión marcada y resuelve una foto de cualquier tenant sobre una sin marcar. [R4, R6]
- [x] 4.7 Añadir la entrada de esta lectura al censo de
      `backend/tests/test_unscoped_reads.py`, que es donde R6.4 pide que la excepción se vea, con su
      comentario de por qué existe. [R6]

## 5. Auditoría (D8) <!-- panel: PASS 2026-08-22 -->

- [x] 5.1 `backend/app/audit/domain/actions.py`: `ENTITY_INCIDENT_PHOTO = "INCIDENT_PHOTO"` e
      `INCIDENT_PHOTO_UPLOADED`, con sus entradas en `ENTITY_TYPES` y `ACTIONS`. **No** se añade a
      `_ACTOR_OPTIONAL_ACTIONS`: este change no pide excepción nueva a la regla 9. [R6]
- [x] 5.2 `backend/app/audit/domain/value_objects.py`:
      `AUDITABLE_FIELDS["INCIDENT_PHOTO"] = {"stage", "incident_id", "uploaded_by"}` —
      **sin `storage_key`**. Test en `backend/tests/audit/` que falla si `storage_key` entra en la
      allowlist de esa entidad. [R6]

## 6. Casos de uso (D7, D10) <!-- panel: PASS 2026-08-22 -->

- [x] 6.1 `UploadIncidentPhotoUseCase` en `backend/app/maintenance/application/use_cases.py`:
      resuelve la incidencia por `_load_incident_in_scope` (con `restrict_to_technician_id` del
      `IncidentActor`), llama `Incident.ensure_accepts_photo()`, decide el formato **por los bytes**
      contra la allowlist, escribe el objeto por `FileStoragePort.put`, inserta la fila, escribe el
      `AuditLog` por el `_AuditWriter` existente y acuña la URL firmada de la respuesta. Si el
      commit falla, borra el objeto en *best effort* registrando la clave en el log. `uploaded_by`
      sale del token, nunca del cuerpo. [R2, R6]
- [x] 6.2 Tests de `UploadIncidentPhotoUseCase` en
      `backend/tests/maintenance/test_photo_upload_use_case.py` (nuevo): el camino feliz en los dos
      estados admitidos; los tres refusals de estado distinguibles; el técnico no asignado obtiene
      el **mismo `404`** que una incidencia inexistente y la restricción se deriva del rol del token;
      contenido no-imagen → error de formato aunque el `Content-Type` declarado sea válido; fallo del
      almacén → sin fila; fallo del commit → objeto borrado; la fila de `AuditLog` apunta a la foto
      y no lleva `storage_key`. [R2, R6]
- [x] 6.3 `ListIncidentPhotosUseCase` en el mismo fichero: mismo `_load_incident_in_scope`, devuelve
      las fotos de la más antigua a la más reciente, cada una con su URL firmada **acuñada para esa
      respuesta**. Tests en `backend/tests/maintenance/test_photo_listing_use_case.py` (nuevo):
      orden, acotamiento del técnico, y `404` indistinguible en los tres casos de R3.4. [R3]

## 7. API autenticada: schemas, dependencias y las dos rutas (D10, D11) <!-- panel: PASS 2026-08-23 -->

- [x] 7.1 `backend/app/maintenance/api/schemas.py`: `IncidentPhotoResponse` enumerando `id`,
      `incident_id`, `stage`, `uploaded_by`, `created_at`, `url`, construido con un
      `from_upload(...)` explícito y **nunca** con `model_validate`/`from_attributes` sobre la
      entidad; `IncidentPhotoListResponse` envolviendo `items` sin paginar. [R3]
- [x] 7.2 `backend/app/maintenance/api/dependencies.py`: los builders de los dos casos de uso,
      reutilizando `get_url_signing_key` y `get_file_storage_factory`. Sin variable de entorno nueva.
      [R2, R3]
- [x] 7.3 `backend/app/maintenance/api/incidents_router.py`:
      `POST /api/v1/incidents/{incident_id}/photos` con `ExecuteDep` (`EXECUTE_INCIDENTS`) →
      `201`, cuerpo `multipart/form-data` con `stage: Annotated[IncidentPhotoStage, Form()]` y
      `file`; y `GET /api/v1/incidents/{incident_id}/photos` con `ReadDep` (`READ_INCIDENTS`).
      Summary/description anotados. **`ROLE_PERMISSIONS` no se toca**: ningún permiso nuevo. [R2, R3]
- [x] 7.4 Tests de API en `backend/tests/maintenance/test_photos_api.py` (nuevo): los códigos de
      R2 (`201`, `409` con sus **tres mensajes distintos**, `422` de formato, `422` de etapa
      desconocida —y **no** `404`—, `502 BAD_GATEWAY`, `404` indistinguible); el listado ordenado
      con su URL firmada; y una aserción sobre el **cuerpo serializado** de las dos rutas que
      demuestre que `storage_key` no aparece en ningún campo ni cabecera. [R2, R3]
- [x] 7.5 Ampliar `backend/tests/maintenance/test_api_authorization.py` con las dos rutas nuevas:
      qué rol puede subir (`TECHNICIAN` asignado, `PROPERTY_MANAGER`) y qué rol puede listar
      (añade `TENANT_OWNER`), y que el técnico no asignado recibe `404`. [R2, R3]

## 8. La ruta anónima de servido y su censo (D5, D12) <!-- panel: PASS 2026-08-23 -->

- [x] 8.1 `backend/app/maintenance/api/photos_router.py` (nuevo): el router construido con
      `build_signed_media_router(...)` de 1.3 con `prefix="/incident-photos"`, su tag y su nombre de
      evento de log, inyectando `SqlAlchemyUnscopedIncidentPhotoLocationQuery`. **No** cuelga de
      `incidents_router` (R4.6). Montarlo en `backend/app/main.py` junto a los demás routers. [R4]
- [x] 8.2 Añadir `("GET", "/api/v1/incident-photos/{photo_id}")` a `ANONYMOUS_ENDPOINTS` de
      `backend/tests/test_route_authorization.py`, con el comentario de por qué es anónima (un
      `<img src>` no envía `Authorization`; la firma es la credencial). [R4]
- [x] 8.3 Tests de la ruta en `backend/tests/maintenance/test_serve_photo_api.py` (nuevo): `200`
      con los bytes, `Content-Type` derivado **solo de la extensión de la clave**,
      `X-Content-Type-Options: nosniff` con un único valor y
      `Cache-Control: private, max-age=<lo que queda de la firma>`; `403` con cuerpo **idéntico**
      (comparado literalmente) en los cuatro casos —firma inválida, caducada, manipulada, foto
      inexistente— y `no-store`; `404` cuando el `storage_type` del tenant es `S3`; `502` si el
      objeto no se puede leer. [R4]

## 9. El techo de cuerpo de la subida (D9) <!-- panel: PASS 2026-08-23 -->

- [x] 9.1 En el proveedor por path de `MaxBodySizeMiddleware` (`backend/app/main.py`), una rama más
      **antes del `else`**: `settings.photo_upload_max_bytes` si
      `path.startswith(f"{API_V1_PREFIX}/incidents/") and path.endswith("/photos")` — acotada por
      los **dos** extremos. Reutiliza `PHOTO_UPLOAD_MAX_BYTES` sin ajuste nuevo. Escribir junto a la
      rama el riesgo aceptado y su medida: son 10 MiB antes de autenticar y el patrón es más ancho
      que la ruta (`/api/v1/incidents/photos` y `/api/v1/incidents/a/b/c/photos` también casan). [R5]
- [x] 9.2 Test en `backend/tests/maintenance/test_photo_body_limit.py` (nuevo): la ruta de la foto
      rechaza con `413` por encima del tope; las demás rutas bajo `/api/v1/incidents` **conservan**
      su techo actual (`REQUEST_MAX_BYTES` por el fall-through, no `JSON_BODY_MAX_BYTES` — la
      corrección verificada de R5.2); y el test falla si alguien ensancha el techo globalmente o
      quita uno de los dos extremos del patrón. [R5]

## 10. Aislamiento de tenant y guardianes de censo (R6) <!-- panel: PASS 2026-08-23 -->

- [x] 10.1 `backend/tests/maintenance/test_photo_isolation.py` (nuevo): un usuario del tenant A no
      alcanza las filas de `incident_photos` del tenant B por **ninguna de las tres rutas** — subida,
      listado y servido firmado. Para el aislamiento a nivel de repositorio, sobre **sesión sin
      marcar** (una sesión marcada hace que el listener filtre y el test no pueda fallar). [R6]
- [x] 10.2 Correr `backend/tests/test_rule11_ownership.py` sin añadirle fila: el enum cerrado de 3.1
      es lo que hace que este change no introduzca sumidero nuevo de texto libre (R6.5). Si el
      guardián pide una entrada, algo del diseño se rompió y hay que volver a 3.1, no añadir la fila.
      [R6]
- [x] 10.3 Correr `backend/tests/test_models_registry.py` y `backend/tests/test_layering.py`: el
      modelo nuevo entra por la entrada de `app.maintenance.infrastructure.models` que ya existe, y
      la extracción de la sección 1 no rompe la regla de dependencia. [R1]

## 11. Contrato publicado y sus dos mitades (R6.6)

- [x] 11.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo. Verificar con
      `docker compose exec backend uv run pytest tests/test_openapi_contract.py`. [R6]
- [x] 11.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` y commitearlo en el mismo PR. Desde
      un worktree el comando documentado (`cd frontend && npm run api:generate`) **no funciona**:
      usar el rodeo de `sdd/project.md` (`mkdir -p /backend` + `docker compose cp backend/openapi.json`
      + `ln -sfn /app /frontend` dentro del contenedor `frontend`, y después `npm run api:generate`).
      Confirmar sin deriva con `api:check` por la misma vía. [R6]

## 12. Verification

- [x] 12.1 Suite completa del backend: `docker compose exec backend uv run pytest`. Verde entera,
      sin `xfail` ni `skip` nuevos.
- [x] 12.2 Un solo head de migraciones: `docker compose exec backend uv run alembic heads`, y
      `alembic upgrade head` + `downgrade` de la revisión nueva sobre base limpia.
- [x] 12.3 Suite del frontend: `docker compose exec -T frontend npm test` tras la receta de copias
      de `sdd/project.md`. Los dos ficheros que fallan con `ENOENT` en worktree
      (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`)
      **no son de este change** — con la receta aplicada la suite pasa entera.
- [x] 12.4 Comprobación manual del flujo end-to-end con `make up PORT_OFFSET=<n>`: como técnico
      asignado, subir una `BEFORE` y una `AFTER` a una incidencia `IN_PROGRESS`, listarlas como
      `PROPERTY_MANAGER`, y abrir la URL firmada devuelta **en el navegador sin cabecera de
      autorización** (que es lo único que demuestra R4). Repetir con una firma manipulada y
      comprobar el `403`, y con la incidencia en `RESOLVED` y comprobar el `409`.
- [x] 12.5 `rebase` sobre `main` antes de abrir el PR y volver a 12.2: `tech-cycle-completion` está
      viva y también migra `incidents`; el conflicto de `down_revision` es mecánico pero hay que
      resolverlo antes del PR, no después.
      **Hecho en `/sdd:review` (2026-08-23)**, sobre `origin/main` = `20384da`. `down_revision` de
      `d4a7e18c6b93` repuntado a `'c8e1f4a92b70'`; `alembic heads` devuelve un solo head y el
      `upgrade`/`downgrade` de 12.2 vuelve a pasar. El rebase trajo seis conflictos —
      `openapi.json` y `openapi.d.ts` (regenerados desde el código, `api:check` sin deriva),
      `test_models.py`, `test_route_authorization.py`, `incidents_router.py` y `schemas.py`
      (uniones de importaciones y de listas). Y dos tests que `main` dejó desfasados, ambos
      arreglados aquí: `test_the_shared_helper_answers_the_photo_gate_and_a_real_transition_alike`
      llamaba a `Incident.start`, que `tech-cycle-completion` renombró a `en_route`; y
      `test_the_tech_cycle_revision_unwinds_over_populated_rows_and_keeps_its_enum_label` hacía
      `downgrade -1` dando por hecho que su revisión era el head — ahora apunta a la revisión
      explícita, que es la convención que el propio fichero ya declara.
