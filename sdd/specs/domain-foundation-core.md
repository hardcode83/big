# Modelos de dominio y esquema DB — backbone core

## Purpose

Entidades de dominio y esquema de base de datos para las 8 entidades del PRD (§7.1-7.8) que forman el backbone de identidad, tenencia, propiedad y reserva: `Tenant`, `TenantConfig`, `User`, `Property`, `PropertyStateTransition`, `Guest`, `Reservation`, `TimelineEvent`. Es la base sobre la que se construyen `domain-foundation-ops`, `domain-foundation-financial` y el resto del roadmap — solo estructura de datos (entidades + esquema + migraciones), sin lógica de negocio, repositorios, casos de uso ni endpoints todavía.

## Requirements

### Estructura por módulo de dominio

- Cada entidad vive en su módulo de dominio de negocio ya nombrado en `architecture.md` (`tenants`, `auth`, `properties`, `guests`, `reservations`, `timeline`) — `User` vive en `auth/`, no en `tenants/`.
- Cada módulo tiene al menos `domain/` (entidades Python puras + enums) e `infrastructure/` (modelos SQLAlchemy). `application/` y `api/` los añade el change que primero persiste o expone cada entidad: hoy solo existen en `auth/`, donde los introdujo `auth-tenancy` para `User` y para leer el estado de `Tenant`.
- `domain/entities.py` y `domain/enums.py` no importan `sqlalchemy`, `fastapi` ni `pydantic` (regla de dependencia de `backend-architecture.md`, verificada por `backend/tests/test_layering.py`).
- De las 8 entidades, solo `User` y `Tenant` tienen puertos de repositorio y casos de uso, aportados por `auth-tenancy` (`UserRepository`, `TenantStatusReader`; ver spec `auth-tenancy`). Las otras seis siguen siendo solo estructura de datos, y sus puertos se difieren al change que primero necesite persistirlas.

### Enums de dominio exactos del PRD

- Todo enum usado por estas 8 entidades usa los mismos nombres y valores literales de PRD §7.1-7.8 y §8.1 (p.ej. `PropertyOperationalState.VACANT_READY`, nunca traducido).
- `PropertyOperationalState` incluye los 11 valores completos de PRD §8.1, aunque las transiciones entre ellos no se implementan hasta el change `timeline-state-machine`.
- Un enum usado por más de un módulo se define una sola vez, en el módulo dueño de la entidad que lo usa primero, e importado desde ahí por los demás — nunca duplicado. Dentro de este subconjunto de 8 entidades, esto aplica a `PropertyOperationalState` (`properties/`, reutilizado en 3 columnas: `current_operational_state`, `to_state`, `from_state`) y a `LegalRegistrationStatus` (definido en `guests/`, reutilizado por `reservations/` — el PRD define el mismo enum idéntico en `Guest` §7.6 y `Reservation` §7.7).

### Esquema DB — modelos SQLAlchemy 2.x async

- Cada entidad tiene un modelo SQLAlchemy declarativo en `infrastructure/models.py` que reproduce exactamente el esquema del PRD: columnas, tipos, nullability, `UNIQUE`/`INDEX` (incluidos los compuestos y los que llevan orden `DESC` en tablas de historial/auditoría — `property_state_transitions`, `timeline_events`).
- **Una excepción deliberada al "exactamente el esquema del PRD"**: la unicidad del email de `users`. PRD §7.3 define `UNIQUE(tenant_id, email)`; el esquema real tiene un índice único funcional **global** sobre `lower(email)` (`uq_users_lower_email`) y **no** tiene la constraint por tenant, que la global ya implica. El motivo es que el login recibe solo email y contraseña, así que una dirección repetible entre tenants no identificaría la cuenta — decidido en la revisión del PR #25, registrado en ADR 0005 y detallado en la spec `auth-tenancy`.
- Toda entidad tiene PK `UUID` y, salvo `Tenant`, un `tenant_id` FK obligatoria a `tenants.id`, indexado — vía los mixins compartidos `UUIDPrimaryKeyMixin`/`TenantScopedMixin` (`backend/app/core/db.py`). `PropertyStateTransition` y `TimelineEvent` son las únicas dos excepciones sin `updated_at` (solo `created_at`) — son históricos/eventos inmutables, no registros editables (PRD §7.5/§7.8, `architecture.md` "Timeline inmutable").
- `created_at`/`updated_at` son `TIMESTAMPTZ` (`DateTime(timezone=True)`), nunca `TIMESTAMP WITHOUT TIME ZONE`.
- Todo enum de dominio se mapea a un tipo `ENUM` nativo de Postgres con nombre explícito (`sa.Enum(X, name="...", native_enum=True)`) — nunca autogenerado, para que el nombre del tipo en Postgres sea estable y predecible.
- Todo valor `DEFAULT` que el PRD especifica en el esquema existe también a nivel de DDL (`server_default`), no solo como default de Python en el ORM — un INSERT que no pase por el ORM (migración de datos, script, `psql` directo) respeta los mismos defaults.
- Las FKs entre estas 8 entidades usan `ON DELETE RESTRICT` por defecto (el PRD modela el borrado vía `status`, nunca `DELETE` real) — excepto las FKs nullable que apuntan a `User` (`PropertyStateTransition.triggered_by_user_id`, `TimelineEvent.actor_user_id`), que usan `ON DELETE SET NULL` para no perder el histórico si un `User` se purga.
- Los campos que el PRD marca como cifrados en reposo (`Property.wifi_password_encrypted`, `Guest.document_number_encrypted`) son columnas de texto sin cifrar/descifrar todavía — el cifrado Fernet real es responsabilidad de un change posterior que lea/escriba esos campos (`security.md` #3).
- Cualquier columna FK que referencia una tabla de otro módulo (p.ej. `reservations.property_id` → `properties.id`) usa un tipo `Uuid` explícito en `mapped_column`, no solo la anotación `Mapped[uuid.UUID]` — SQLAlchemy puede resolverla como `NullType` si el módulo destino no se ha importado antes en el proceso, un fallo silencioso que rompería el DDL.

### Migraciones Alembic

- Una única migración baseline (`backend/alembic/versions/`) crea las 8 tablas sobre una DB vacía, en orden de dependencia, reversible.
- `alembic downgrade base` revierte tablas, índices **y** los tipos `ENUM` de Postgres que las tablas crearon implícitamente — Alembic autogenerate no emite `DROP TYPE` por defecto, así que la migración lo hace explícitamente para no dejar tipos huérfanos.
- Al arrancar el stack local (`make up`), un servicio `migrate` dedicado en `docker-compose.yml` aplica `alembic upgrade head` antes de que `backend`/`worker` arranquen (`depends_on: condition: service_completed_successfully`) — sin paso manual, coherente con el DX de `local-environment`.
- `backend/app/core/config.py` resuelve `DATABASE_URL`: fijada por `docker-compose.yml` a `postgres:5432` dentro de la red de compose; si no viene fijada (ejecución en host), cae a un valor por defecto contra `localhost:5432` con las credenciales de `POSTGRES_*` de `.env` — necesario porque el hostname `postgres` no resuelve fuera de la red de Docker. Ese camino solo sirve en el **worktree principal**, que es el único que publica el `5432` (ver spec `local-environment`); y en la práctica la suite se ejecuta dentro del contenedor, porque `uv` no está instalado en el host.

### Tests

- Cada entidad tiene un test unitario que la instancia en Python puro, sin necesitar la base de datos.
- Cada modelo SQLAlchemy tiene un test de integración contra Postgres real, incluyendo al menos un caso que viola una constraint `UNIQUE` real (no solo el camino feliz).
- Los tests de integración corren contra una base de datos **dedicada y por proceso** (`<nombre-dev>_test_<pid>`), nunca contra la que gestiona `make up`/`migrate` — se crea automáticamente si no existe y se borra al cerrar la sesión de pytest. Compartir la base de datos de desarrollo con los tests dropearía su esquema al terminar cada test, y un nombre fijo hace que dos ejecuciones concurrentes se pisen (ver spec `backend-ci`).

## Key files

- Infra compartida: `backend/app/core/db.py` (`Base`, engine async, `UUIDPrimaryKeyMixin`/`TimestampMixin`/`TenantScopedMixin`), `backend/app/core/config.py` (`Settings.database_url`).
- `backend/app/tenants/{domain,infrastructure}/` — `Tenant`, `TenantConfig`.
- `backend/app/auth/{domain,infrastructure}/` — `User`.
- `backend/app/properties/{domain,infrastructure}/` — `Property`, `PropertyStateTransition`.
- `backend/app/guests/{domain,infrastructure}/` — `Guest`.
- `backend/app/reservations/{domain,infrastructure}/` — `Reservation`.
- `backend/app/timeline/{domain,infrastructure}/` — `TimelineEvent`.
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/` — bootstrap y migración baseline.
- `backend/tests/{tenants,auth,properties,guests,reservations,timeline}/`, `backend/tests/conftest.py` (fixture de base de datos de test aislada).
- `docker-compose.yml` — servicio `migrate`.
