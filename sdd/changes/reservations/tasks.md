# Tasks: reservations

Comandos de este proyecto (`sdd/project.md`): el backend corre en Docker, así que
los tests son `docker compose exec backend uv run pytest` (o
`docker compose run --rm backend uv run pytest` con el stack parado). No hay linter
ni typecheck configurados en `backend/` — el workflow `backend-tests.yml` corre
`alembic upgrade head`, `alembic check`, `pytest -q -rs` y `alembic downgrade base`.

## 1. Puertos y adaptadores de lectura (base para todo lo demás) <!-- panel: PASS 2026-07-31 (architect, security, qa, tenancy; 8 hallazgos corregidos en ronda 1) -->

- [x] 1.1 `PropertyRepository` (Protocol) en `backend/app/properties/domain/repositories.py` con `get`, `find_by_internal_code` y `find_by_pms_external_id`, los tres con `tenant_id` explícito; test de dominio que compruebe que el Protocol es puro (sin imports prohibidos, cubierto ya por `tests/test_layering.py`) [R1, R3, R4]
- [x] 1.2 `SqlAlchemyPropertyRepository` en `backend/app/properties/infrastructure/repositories.py` traduciendo `PropertyModel` → entidad `Property`; tests de integración en `backend/tests/properties/test_repositories.py`: encuentra por las tres vías dentro del tenant y devuelve `None` para una propiedad del tenant B [R1, R3, R4, R5]
- [x] 1.3 `GuestRepository` (Protocol) en `backend/app/guests/domain/repositories.py` con `get`, `find_by_email` y `add`; normalización de email (`strip` + `lower`) como función de dominio con su unit test [R1, R3]
- [x] 1.4 `SqlAlchemyGuestRepository` en `backend/app/guests/infrastructure/repositories.py`; tests de integración: desempate determinista por `created_at` y luego `id` cuando dos huéspedes del tenant comparten email (D8), `None` cross-tenant, y `add` que rechaza un `tenant_id` ajeno [R3, R5]
- [x] 1.5 `TimelineEventRepository` (Protocol) en `backend/app/timeline/domain/repositories.py` con `add`, y `SqlAlchemyTimelineEventRepository` en `backend/app/timeline/infrastructure/repositories.py`; tests de integración en `backend/tests/timeline/test_repositories.py`: persiste un evento construido con `TimelineEventFactory` y lo recupera con su `metadata` intacta [R2]
- [x] 1.6 `UnitOfWork` (Protocol) + `SqlAlchemyUnitOfWork` en `backend/app/core/unit_of_work.py` con su test de que `commit` delega en la sesión (D3) [R2]

## 2. Agregado `Reservation`: invariantes y repositorio <!-- panel: PASS 2026-07-31 (architect, security; 5 hallazgos corregidos en ronda 1) -->

- [x] 2.1 Métodos de mutación en `backend/app/reservations/domain/entities.py` (`update_details`, `cancel`) que recalculan `nights`/`total_guests` y revalidan las invariantes de fechas y ocupación, sin setters públicos; TDD — unit tests primero en `backend/tests/reservations/test_entities.py`, incluidos los casos de rechazo (`check_out <= check_in`, `adults < 1`, `children < 0`) [R1]
- [x] 2.2 `cancel()` idempotente: cancelar una reserva ya `CANCELLED` no cambia nada y expone que no hubo transición, para que el caso de uso no emita un segundo evento; unit test [R1, R2]
- [x] 2.3 Excepciones de dominio **puras** en `backend/app/reservations/domain/exceptions.py` (sin importar `app/core/errors.py`, que arrastra FastAPI: mismo patrón que `auth/domain/exceptions.py`); el mapeo a status/código va en `backend/app/reservations/api/errors.py` en la sección 4 [R1]
- [x] 2.4 `ReservationRepository` (Protocol) en `backend/app/reservations/domain/repositories.py` (`get`, `find_by_external_pms_id`, `list`, `add`, `save`) y el value object `ReservationFilters` [R1, R3]
- [x] 2.5 `SqlAlchemyReservationRepository` en `backend/app/reservations/infrastructure/repositories.py`: `tenant_id` explícito en cada query, `add` que rechaza `tenant_id` ajeno (los INSERT no los cubre el listener de `core/db.py`), orden estable `check_in_date DESC, id`, y el filtro de solape de estancia de D12; tests de integración en `backend/tests/reservations/test_repositories.py` incluidos los de aislamiento cross-tenant [R1, R5]

## 3. Casos de uso de reservas + timeline atómico <!-- panel: pendiente, se revisa junto a la 4 -->

- [x] 3.1 `CreateReservationUseCase` en `backend/app/reservations/application/use_cases.py`: resuelve la propiedad por `PropertyRepository.get` (→ `NotFoundError` si no es del tenant), crea la reserva, emite `RESERVATION_CREATED_MANUAL` con `actor_type` USER y hace un único `commit`; unit tests con fakes en memoria de los cuatro puertos [R1, R2, R5]
- [x] 3.2 `UpdateReservationUseCase`: aplica solo los campos presentes, revalida sobre el resultado y emite `RESERVATION_UPDATED` con los campos cambiados en `metadata`; unit tests, incluido que un PATCH vacío no emite evento [R1, R2]
- [x] 3.3 `CancelReservationUseCase`: emite `RESERVATION_CANCELLED` solo si hubo transición real (2.2); unit tests de la doble cancelación [R1, R2]
- [x] 3.4 `GetReservationUseCase` y `ListReservationsUseCase`: el detalle resuelve el `Guest` vinculado con `GuestRepository.get` y nunca expone campos de documento; la lista aplica filtros + paginación y devuelve `(items, total)`; unit tests con fakes [R1, R5]
- [x] 3.5 Test de atomicidad (R2.6): un `TimelineEventRepository` que lanza al persistir deja la reserva sin escribir — test de integración contra Postgres, no con fakes, porque lo que se prueba es la transacción [R2]

## 4. API de reservas

- [x] 4.1 Dos permisos nuevos (`READ_RESERVATIONS`, `MANAGE_RESERVATIONS`) y su matriz de roles en `backend/app/auth/domain/policy.py` según D7; ampliar `backend/tests/auth/test_policy.py` con los cinco roles [R5]
- [x] 4.2 Esquemas Pydantic en `backend/app/reservations/api/schemas.py` (crear, patch, respuesta, respuesta paginada `{data,total,page,per_page,total_pages}`), con `per_page` acotado a 100 y fechas ISO 8601 UTC [R1]
- [x] 4.3 Dependencias de inyección en `backend/app/reservations/api/dependencies.py` (un builder por caso de uso, siguiendo `auth/api/dependencies.py`) [R1]
- [x] 4.4 Router `backend/app/reservations/api/router.py` con los cinco endpoints de PRD §23, cada uno declarando `require(...)`, con `summary`/`description` y modelos de respuesta para OpenAPI; montarlo en `backend/app/main.py` bajo `API_V1_PREFIX` [R1, R5]
- [x] 4.5 Tests de API en `backend/tests/reservations/test_api.py` (httpx AsyncClient): los cinco endpoints en camino feliz, `422` de validación, `404` de propiedad de otro tenant, `204` idempotente del DELETE, y la comprobación de que el endpoint manual **no** acepta `external_pms_id` — el `409` del unique constraint solo es alcanzable desde la ingesta y se cubre en `test_repositories.py` (design D9 corregido) [R1]
- [x] 4.6 Tests de la matriz completa endpoint × rol en `backend/tests/reservations/test_authorization.py`: los cinco roles contra los cinco endpoints, reutilizando las fixtures `tenant_a`/`tenant_b`/`users_by_role_*` de `backend/tests/auth/conftest.py` [R5]
- [x] 4.7 Tests de aislamiento en `backend/tests/reservations/test_isolation.py`: un usuario del tenant A recibe `404` (no `403`) al pedir, editar y cancelar por `id` una reserva real del tenant B, y su listado nunca la incluye [R5]

## 5. Integraciones: puerto PMS, mock y sincronización

- [ ] 5.1 Módulo `backend/app/integrations/` con `domain/dtos.py` (`ReservationDTO` con las firmas literales de PRD §16) y `domain/ports.py` (`PMSAdapter` con `list_reservations` y `get_reservation`), marcados `EXTERNAL_DEPENDENCY` [R3]
- [ ] 5.2 `MockPMSAdapter` en `backend/app/integrations/infrastructure/mock_pms.py` devolviendo las reservas del seed de PRD §27 y, deliberadamente, filas problemáticas (propiedad inexistente, fechas inválidas) para que el contrato se pruebe de verdad; unit tests del adapter [R3]
- [ ] 5.3 `SyncReservationsFromPmsUseCase` en `backend/app/integrations/application/use_cases.py`: resuelve la propiedad por `pms_external_id`, hace upsert por `(tenant_id, external_pms_id)`, vincula/crea `Guest`, emite `RESERVATION_IMPORTED` con `actor_type` SYSTEM solo en las creaciones, y devuelve un informe con creadas/actualizadas/errores; unit tests con fakes [R2, R3]
- [ ] 5.4 Test de idempotencia (R3.3): dos pasadas seguidas de la misma sincronización dejan el mismo número de reservas y no añaden eventos en la segunda — test de integración [R3]
- [ ] 5.5 Test de tolerancia (R3.4): una reserva del PMS con propiedad desconocida se reporta como error y las demás se importan [R3]
- [ ] 5.6 Comando `backend/app/integrations/cli/pms_sync.py` (forma de `app/cli/bootstrap.py`) que ejecuta el caso de uso e imprime el informe; test que lo invoca y comprueba el código de salida [R3]

## 6. Importación CSV

- [ ] 6.1 Parser en `backend/app/integrations/infrastructure/csv_parser.py`: UTF-8 con BOM tolerado, columnas requeridas/opcionales de D11, validación por fila devolviendo `(filas válidas, errores con nº de línea y motivo)`; unit tests con CSV bien y mal formados [R4]
- [ ] 6.2 `ImportReservationsFromCsvUseCase`: reutiliza la misma ruta de upsert que 5.3, resuelve la propiedad por `internal_code`, emite `RESERVATION_IMPORTED` con `actor_type` USER y el `actor_user_id` del que sube, y produce `{created,updated,skipped,errors[]}`; unit tests con fakes [R2, R4]
- [ ] 6.3 Settings `CSV_IMPORT_MAX_BYTES` (10 MB) y `CSV_IMPORT_MAX_ROWS` (1000) en `backend/app/core/config.py`, con test de sus defaults [R4]
- [ ] 6.4 Endpoint `POST /api/v1/integrations/pms/import-csv` en `backend/app/integrations/api/{router,schemas}.py` (multipart, `require(Permission.MANAGE_RESERVATIONS)`), montado en `main.py`; validación de content-type y de límites antes de parsear [R4, R5]
- [ ] 6.5 Tests de API del import en `backend/tests/integrations/test_import_csv.py`: camino feliz con informe, fila inválida omitida con su número de línea, `413` por exceso de tamaño y de filas, `422` por columnas ausentes, e idempotencia por `external_pms_id` [R4]
- [ ] 6.6 Tests de autorización e aislamiento del endpoint de import: solo `PROPERTY_MANAGER` puede, y un CSV que nombre una propiedad de otro tenant no importa nada [R4, R5]

## 7. Documentación

- [ ] 7.1 `.env.example`: las dos variables nuevas con comentario y sin valores sensibles (regla de `steering/documentation.md`) [R4]
- [ ] 7.2 `README.md` raíz: secciones Estructura/Tests al día con el módulo `integrations` y el comando de sync [R3, R4]
- [ ] 7.3 `docs/reservations.md`: cómo se opera la capability (crear/editar/cancelar, importar un CSV, sincronizar con el PMS mock), enlazando a la spec en vez de duplicarla [R1, R3, R4]

## 8. Verification

- [ ] 8.1 Suite completa en verde: `docker compose exec backend uv run pytest -q -rs`
- [ ] 8.2 Los modelos siguen coincidiendo con el esquema migrado (este change no añade DDL): `docker compose exec backend uv run alembic check`
- [ ] 8.3 Comprobación manual del flujo end-to-end contra el stack local: login como `manager@adamar.test`, crear una reserva, listarla con filtros, editarla, cancelarla, e importar un CSV de dos filas (una válida y una inválida) verificando el informe; los eventos correspondientes aparecen en `timeline_events`
- [ ] 8.4 Cobertura de `domain/` de los módulos tocados ≥ 80 % (PRD §4): `docker compose exec backend uv run pytest --cov=app/reservations/domain --cov=app/properties/domain --cov=app/guests/domain --cov=app/timeline/domain -q`
