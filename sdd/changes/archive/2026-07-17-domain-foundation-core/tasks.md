# Tasks: domain-foundation-core

## 1. Core DB infra & dependencies

- [x] 1.1 Añadir `sqlalchemy[asyncio]`, `asyncpg`, `alembic` a las dependencias — files: `backend/pyproject.toml`, `backend/uv.lock` [R3, R4]
- [x] 1.2 Añadir `database_url: str` a `Settings`, leído de la env var `DATABASE_URL` — files: `backend/app/core/config.py` [R4] (nota: se añadió fallback a `localhost:5432` + fix del path de `.env`, ver deviation en design.md D14)
- [x] 1.3 `Base` (declarative base), engine async, `async_session_factory` y mixins `UUIDPrimaryKeyMixin`/`TimestampMixin`/`TenantScopedMixin` (D6) — files: `backend/app/core/db.py` [R3, R5]

## 2. `tenants/` — Tenant, TenantConfig

- [x] 2.1 Enum `TenantStatus` (`ACTIVE`,`SUSPENDED`,`CANCELLED`, PRD §7.1) — files: `backend/app/tenants/domain/enums.py` [R1] (también `StorageType`, ver nota de completitud)
- [x] 2.2 Dataclasses `Tenant` y `TenantConfig` (campos exactos PRD §7.1-7.2) + test unitario que las instancia sin DB — files: `backend/app/tenants/domain/entities.py`, `backend/tests/tenants/test_entities.py` [R2, R6]
- [x] 2.3 Modelos SQLAlchemy `Tenant`/`TenantConfig` (mixins de 1.3; `TenantConfig.tenant_id` `UNIQUE`) + test de integración que crea una fila de cada uno contra Postgres real — files: `backend/app/tenants/infrastructure/models.py`, `backend/tests/tenants/test_models.py` [R3, R5]

## 3. `auth/` — User

- [x] 3.1 Enums `UserRole` (`SUPER_ADMIN`,`TENANT_OWNER`,`PROPERTY_MANAGER`,`CLEANER`,`TECHNICIAN`), `UserStatus` (`ACTIVE`,`INACTIVE`,`SUSPENDED`) — files: `backend/app/auth/domain/enums.py` [R1]
- [x] 3.2 Dataclass `User` (PRD §7.3) + test unitario sin DB — files: `backend/app/auth/domain/entities.py`, `backend/tests/auth/test_entities.py` [R2, R6]
- [x] 3.3 Modelo SQLAlchemy `User` con `UNIQUE(tenant_id, email)`, `INDEX(tenant_id, role)`, `INDEX(tenant_id, status)` + test de integración — files: `backend/app/auth/infrastructure/models.py`, `backend/tests/auth/test_models.py` [R3, R5] (nota: `TenantScopedMixin` requería tipo `Uuid` explícito, ver design.md D15)

## 4. `properties/` — Property, PropertyStateTransition

- [x] 4.1 Enum `PropertyOperationalState` con los 11 valores de PRD §8.1 (`VACANT_READY`, `AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`, `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, `CLEANING_IN_PROGRESS`, `READY_FOR_NEXT_GUEST`, `MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE`), `PropertyStatus` (`ACTIVE`,`INACTIVE`), `StateTransitionTriggeredBy` (`SYSTEM`,`USER`,`SCHEDULER`,`WEBHOOK`) — files: `backend/app/properties/domain/enums.py` [R1]
- [x] 4.2 Dataclasses `Property` y `PropertyStateTransition` (PRD §7.4-7.5) + test unitario sin DB — files: `backend/app/properties/domain/entities.py`, `backend/tests/properties/test_entities.py` [R2, R6]
- [x] 4.3 Modelos SQLAlchemy `Property` (`UNIQUE(tenant_id, internal_code)`, `INDEX(tenant_id, current_operational_state)`, `INDEX(tenant_id, pms_external_id)`) y `PropertyStateTransition` (sin `updated_at`, `INDEX(property_id, created_at DESC)`, FK `triggered_by_user_id` nullable con `ON DELETE SET NULL`, resto de FKs `RESTRICT`) + test de integración — files: `backend/app/properties/infrastructure/models.py`, `backend/tests/properties/test_models.py` [R3, R5] (nota: mismo fix D15 aplicado a `property_id`/`triggered_by_user_id`, enum `PropertyOperationalState` compartido entre columnas, ver design.md D16; índice `created_at DESC` corregido tras hallazgo del architect, ver D18)

## 5. `guests/` — Guest

- [x] 5.1 Enums `GuestDocumentType` (`DNI`,`NIE`,`PASSPORT`,`RESIDENCE_CARD`,`OTHER`), `GuestDocumentStatus` (`NOT_PROVIDED`,`PENDING`,`PROVIDED`,`VERIFIED`,`REJECTED`), `LegalRegistrationStatus` (`NOT_REQUIRED`,`PENDING_GUEST_DATA`,`READY_TO_SUBMIT`,`SUBMITTED`,`FAILED`,`MANUAL_REVIEW` — compartido con `reservations/`, ver Risks de design.md) — files: `backend/app/guests/domain/enums.py` [R1]
- [x] 5.2 Dataclass `Guest` (PRD §7.6) + test unitario sin DB — files: `backend/app/guests/domain/entities.py`, `backend/tests/guests/test_entities.py` [R2, R6]
- [x] 5.3 Modelo SQLAlchemy `Guest` con `INDEX(tenant_id, email)`, columnas `document_number_encrypted`/`nationality`/`date_of_birth` como `TEXT`/tipos simples sin cifrado real todavía + test de integración — files: `backend/app/guests/infrastructure/models.py`, `backend/tests/guests/test_models.py` [R3, R5]

## 6. `reservations/` — Reservation

- [x] 6.1 Enums `ReservationChannel` (`AIRBNB`,`BOOKING`,`EXPEDIA`,`DIRECT`,`MANUAL`,`OTHER`), `ReservationStatus` (7 valores PRD §7.7), `PaymentStatus`, `ReservationAccessStatus` — importando `LegalRegistrationStatus` desde `guests.domain.enums` (no redefinir) — files: `backend/app/reservations/domain/enums.py` [R1]
- [x] 6.2 Dataclass `Reservation` (PRD §7.7) con validación estructural en `__post_init__` (`check_out_date > check_in_date`) + test unitario sin DB (incluye caso inválido) — files: `backend/app/reservations/domain/entities.py`, `backend/tests/reservations/test_entities.py` [R2, R6]
- [x] 6.3 Modelo SQLAlchemy `Reservation` con `UNIQUE(tenant_id, external_pms_id)` (nullable), `INDEX(property_id, check_in_date)`, `INDEX(property_id, check_out_date)`, `INDEX(tenant_id, status)`, FK `guest_id` nullable `RESTRICT` + test de integración — files: `backend/app/reservations/infrastructure/models.py`, `backend/tests/reservations/test_models.py` [R3, R5] (nota: reutiliza `legal_registration_status_enum` de `guests/infrastructure/models.py`, mismo patrón que `PropertyOperationalState`)

## 7. `timeline/` — TimelineEvent

- [x] 7.1 Enums `TimelineActorType` (6 valores), `TimelineEventType` (45 valores completos de PRD §7.8 — el proposal decía 43, recuento real 45, ver nota), `TimelineSeverity` (`INFO`,`WARNING`,`ERROR`,`CRITICAL`) — files: `backend/app/timeline/domain/enums.py` [R1]
- [x] 7.2 Dataclass `TimelineEvent` (PRD §7.8) + test unitario sin DB — files: `backend/app/timeline/domain/entities.py`, `backend/tests/timeline/test_entities.py` [R2, R6]
- [x] 7.3 Modelo SQLAlchemy `TimelineEvent` con `INDEX(property_id, created_at DESC)`, `INDEX(tenant_id, event_type, created_at DESC)`, `INDEX(reservation_id, created_at DESC)`, FK `actor_user_id` nullable `SET NULL`, FK `reservation_id` nullable `RESTRICT` + test de integración — files: `backend/app/timeline/infrastructure/models.py`, `backend/tests/timeline/test_models.py` [R3, R5] (nota: índices `created_at DESC` corregidos tras hallazgo del architect, ver D18)

## 8. Alembic — bootstrap y migración baseline

- [x] 8.1 `alembic init -t async` en `backend/`; `env.py` usa el engine async de `core/db.py`, `target_metadata = Base.metadata`, importa explícitamente los 6 módulos `infrastructure/models.py` de las secciones 2-7 para registrar sus tablas — files: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako` [R4]
- [x] 8.2 Migración baseline única que crea las 8 tablas en orden de dependencia (`tenants` → `tenant_configs`/`users`/`properties`/`guests` → `property_state_transitions`/`reservations` → `timeline_events`), con los enums nativos de Postgres (D7) — files: `backend/alembic/versions/4a5faad7796b_baseline_domain_foundation_core.py` [R4] (nota: downgrade requirió fix manual para dropear los 17 tipos ENUM, ver design.md D17; regenerada tras el fix de índices DESC del panel de revisión, ver D18; verificado upgrade→downgrade→upgrade limpio)

## 9. Docker Compose — aplicación automática de migraciones

- [x] 9.1 `DATABASE_URL` en `environment:` de `backend`/`worker` (`postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`, D12) — files: `docker-compose.yml` [R4]
- [x] 9.2 Nuevo servicio `migrate` (mismo `build` que `backend`, `command: uv run alembic upgrade head`, `depends_on: {postgres: condition: service_healthy}`, sin `restart`) — files: `docker-compose.yml` [R4]
- [x] 9.3 `backend` y `worker` añaden `depends_on: {migrate: condition: service_completed_successfully}` — files: `docker-compose.yml` [R4] (verificado end-to-end: `docker compose down -v && make up` — migrate corre y termina antes de que backend/worker arranquen, 8 tablas creadas, `/health` responde 200)

## 10. Documentación

- [x] 10.1 Actualizar `README.md`: nuevo servicio `migrate`, mención de que `make up` aplica migraciones Alembic automáticamente antes de servir tráfico (documentation.md) — files: `README.md`

## 11. Verification

- [x] 11.1 `docker compose down -v` (limpia el volumen `postgres_data`) + `make up`: confirma que `migrate` corre y termina antes de que `backend`/`worker` arranquen, y que las 8 tablas existen (`docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c '\dt'`) [R4, R6]
- [x] 11.2 `cd backend && uv run alembic downgrade base && uv run alembic upgrade head`: revierte y reaplica sin dejar tablas/tipos ENUM/índices huérfanos [R4] (encontró y arregló fuga de tipos ENUM, ver design.md D17)
- [x] 11.3 Suite completa de tests backend: `cd backend && uv run pytest` — unit (`domain/`, sin DB) + integration (`infrastructure/`, contra Postgres real) en verde [R2, R3, R6] (20/20 passed; ver design.md D19 — bug crítico encontrado por qa: los tests corrían contra la misma BD que `make up`, corregido con BD de test aislada `<db>_test`, más 2 tests de constraint añadidos)
- [x] 11.4 Confirmar que las 8 entidades de dominio (`Tenant`, `TenantConfig`, `User`, `Property`, `PropertyStateTransition`, `Guest`, `Reservation`, `TimelineEvent`) se instancian en tests unitarios sin necesitar la DB (R6.2) [R2, R6]
- [x] 11.5 Revisar `docs/diagrams/2026-07-13_autohost-er-entidades-core.png` contra el esquema implementado; regenerar con `/sdd:diagram` solo si diverge (documentation.md) — sin divergencia, cubre las 8 entidades correctamente
