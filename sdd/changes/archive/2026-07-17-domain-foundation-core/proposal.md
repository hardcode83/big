# Proposal: domain-foundation-core

## Why

`local-environment` dejó el monorepo y el stack local funcionando, pero todavía no existe ningún modelo de dominio ni esquema de base de datos — `postgres` arranca vacío. El PRD (§26.2-3) exige que, antes de auth, timeline/state machine o cualquier módulo de negocio, existan las entidades de dominio y el esquema DB/Alembic de la sección 7. Esa sección define 26 entidades; en vez de un único change gigante, se divide en 3 (ver `sdd/roadmap.md`): este es el primero, **`domain-foundation-core`**, con las 8 entidades que forman el backbone de identidad, tenencia, propiedad y reserva de las que todo lo demás depende vía FK — `Tenant`, `TenantConfig`, `User`, `Property`, `PropertyStateTransition`, `TimelineEvent`, `Guest`, `Reservation`. Los otros dos changes (`domain-foundation-ops`, `domain-foundation-financial`) construyen encima de este.

## What changes

Se crean, por cada una de las 8 entidades, dos representaciones separadas según `backend-architecture.md`: una entidad de dominio en Python puro (`backend/app/<dominio>/domain/entities.py`, sin imports de `sqlalchemy`/`fastapi`/`pydantic`) y un modelo SQLAlchemy 2.x async (`backend/app/<dominio>/infrastructure/models.py`) que reproduce el esquema exacto de PRD §7.1-7.8 (columnas, tipos, nullability, defaults, UNIQUE/INDEX). Se crean los enums de dominio exactos del PRD (`TenantStatus`, `UserRole`, `PropertyOperationalState`, `ReservationStatus`, etc.) en un módulo compartido cuando el enum se usa en más de un dominio. Se genera una migración Alembic baseline que crea las 8 tablas sobre una DB vacía, reversible, y se configura que el contenedor `backend` la aplique automáticamente al arrancar (`make up`).

No se crean puertos de repositorio (`Protocol`/ABC en `domain/repositories.py`), casos de uso, routers ni lógica de negocio (state machine, timeline service) — eso llega con `auth-tenancy` y `timeline-state-machine`, cuando exista un consumidor real de esas entidades (YAGNI, decisión confirmada con el usuario).

## Requirements

### R1 — Enums de dominio exactos del PRD

**As a** developer, **I want** los enums de las 8 entidades modelados con los mismos nombres y valores exactos del PRD, **so that** el código nunca diverja de la fuente de verdad funcional y los cambios futuros (auth, timeline) puedan referenciarlos sin traducir strings.

Acceptance criteria:

1. WHEN se define un enum usado por estas 8 entidades (`Tenant.status`, `User.role`, `User.status`, `Property.current_operational_state`, `Property.status`, `PropertyStateTransition.triggered_by`, `Guest.document_type`, `Guest.document_status`, `Guest.legal_registration_status`, `Reservation.channel`, `Reservation.status`, `Reservation.payment_status`, `Reservation.access_status`, `Reservation.legal_registration_status`, `TimelineEvent.actor_type`, `TimelineEvent.event_type`, `TimelineEvent.severity`), THE SYSTEM SHALL usar los mismos nombres y valores literales de PRD §7.1-7.8 y §8.1 (p.ej. `PropertyOperationalState.VACANT_READY`, no `VacantReady` ni traducciones).
2. WHERE un enum se usa en más de una de estas 8 entidades (p.ej. `PropertyOperationalState` en `Property` y `PropertyStateTransition`; `ReservationStatus`/`ReservationLegalRegistrationStatus` compartidos con lo que usará `domain-foundation-ops`), THE SYSTEM SHALL definirlo una sola vez en un módulo compartido (`backend/app/shared/domain/enums.py` o equivalente), nunca duplicado por dominio.
3. THE SYSTEM SHALL incluir el enum completo `PropertyOperationalState` (PRD §8.1: `VACANT_READY`, `AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`, `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, `CLEANING_IN_PROGRESS`, `READY_FOR_NEXT_GUEST`, `MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE`), aunque las transiciones entre ellos no se implementen hasta `timeline-state-machine`.

### R2 — Entidades de dominio en Python puro

**As a** developer, **I want** cada una de las 8 entidades modelada como Python puro en `domain/entities.py`, **so that** el dominio sea testeable sin DB y no dependa de detalles de infraestructura (regla de dependencia de `backend-architecture.md`).

Acceptance criteria:

1. WHEN se modela `Tenant`, `TenantConfig`, `User`, `Property`, `PropertyStateTransition`, `Guest`, `Reservation` o `TimelineEvent` en `backend/app/<dominio>/domain/entities.py`, THE SYSTEM SHALL implementarla sin ningún `import` de `sqlalchemy`, `fastapi` ni `pydantic`.
2. WHERE una entidad no protege ninguna invariante real más allá de sus propios campos (p.ej. `TenantConfig`, `PropertyStateTransition`, `TimelineEvent` — registros de datos sin lógica de negocio propia todavía), THE SYSTEM SHALL modelarla como `@dataclass` simple, sin métodos de mutación custom.
3. THE SYSTEM SHALL NOT implementar en este change la lógica de `PropertyStateMachine` (transiciones de `Property.current_operational_state`) ni `TimelineService` (cómo/cuándo se registra un `TimelineEvent`) — ver roadmap `timeline-state-machine`. Las entidades de este change son estructura de datos instanciable, no orquestación.
4. THE SYSTEM SHALL NOT crear interfaces de repositorio (`Protocol`/ABC) en `domain/repositories.py` en este change — se difieren al change que primero necesite persistir cada entidad (`auth-tenancy` para `Tenant`/`User`, `reservations` para `Reservation`, etc.), evitando puertos especulativos sin caso de uso real.

### R3 — Modelos SQLAlchemy 2.x async (ORM)

**As a** developer, **I want** un modelo SQLAlchemy declarativo async por entidad que reproduzca el esquema exacto del PRD, **so that** Alembic pueda generar el esquema real y los changes futuros (`auth-tenancy`, `reservations`, ...) tengan ya la tabla lista para sus repositorios.

Acceptance criteria:

1. WHEN se define el modelo SQLAlchemy de cada una de las 8 entidades en `backend/app/<dominio>/infrastructure/models.py`, THE SYSTEM SHALL reproducir exactamente columnas, tipos, nullability y defaults de PRD §7.1-7.8 (p.ej. `Tenant.status` `ENUM('ACTIVE','SUSPENDED','CANCELLED')` `DEFAULT 'ACTIVE'`).
2. WHERE el PRD declara la entidad con `tenant_id UUID FK→Tenant NOT NULL` (todas salvo `Tenant` misma), THE SYSTEM SHALL declarar `tenant_id` como FK obligatoria a `tenants.id`; toda entidad SHALL tener PK `UUID` y columnas `created_at`/`updated_at` `TIMESTAMPTZ` (excepto `PropertyStateTransition` y `TimelineEvent`, que el PRD declara solo con `created_at`, sin `updated_at`, por ser histórico/evento inmutable — ver `architecture.md`, "Timeline inmutable").
3. WHEN el PRD declara un `UNIQUE`/`INDEX` compuesto (p.ej. `UNIQUE(tenant_id, email)` + `INDEX(tenant_id, role)` + `INDEX(tenant_id, status)` en `User`; `UNIQUE(tenant_id, internal_code)` en `Property`; `UNIQUE(tenant_id, external_pms_id)` + índices por fecha en `Reservation`), THE SYSTEM SHALL reproducirlo como constraint/index de SQLAlchemy.
4. WHERE el PRD marca un campo como cifrado en reposo (`Property.wifi_password_encrypted`, `Guest.document_number_encrypted`), THE SYSTEM SHALL reservar la columna como `TEXT` sin implementar cifrado/descifrado en este change — el cifrado Fernet real (`security.md` #3) es responsabilidad de un change posterior que lea/escriba esos campos.

### R4 — Migraciones Alembic (baseline de estas 8 tablas)

**As a** developer, **I want** una migración Alembic que cree el esquema completo de estas 8 entidades sobre una DB vacía, **so that** el stack local (`local-environment`) tenga un esquema real desde el primer `make up` tras este change.

Acceptance criteria:

1. WHEN se ejecuta `alembic upgrade head` sobre la DB vacía que crea `local-environment`, THE SYSTEM SHALL crear las 8 tablas (`tenants`, `tenant_configs`, `users`, `properties`, `property_state_transitions`, `timeline_events`, `guests`, `reservations`) con su esquema completo (columnas, FKs, constraints, índices, tipos ENUM de Postgres).
2. WHEN se ejecuta `alembic downgrade base`, THE SYSTEM SHALL revertir el esquema completo sin dejar tablas, tipos ENUM ni índices huérfanos.
3. WHEN arranca el contenedor `backend` (target `dev`, `make up`), THE SYSTEM SHALL aplicar las migraciones Alembic pendientes automáticamente antes de servir tráfico — sin paso manual adicional tras `make up` (coherente con el DX de "zero manual steps" ya establecido en `local-environment`).

### R5 — Integridad referencial y patrón de tenant scoping

**As a** developer, **I want** que las FKs y el patrón `tenant_id` queden bien definidos desde este change, **so that** `auth-tenancy` pueda implementar el middleware de aislamiento de tenant sin tener que rediseñar el esquema.

Acceptance criteria:

1. THE SYSTEM SHALL tener un índice sobre `tenant_id` en toda tabla de este change que lo declare (todas salvo `tenants`), preparando el scoping por tenant que implementará `auth-tenancy` — este change no implementa el middleware de aislamiento en sí.
2. WHERE una FK referencia una entidad que este mismo change no crea todavía (ninguna aplica en este subset — `TenantConfig`→`Tenant`, `User`→`Tenant`, `Property`→`Tenant`, `PropertyStateTransition`→`Property`/`Tenant`/`User`, `Guest`→`Tenant`, `Reservation`→`Tenant`/`Property`/`Guest` están todas dentro de este mismo change), THE SYSTEM SHALL declararla como FK real, no como referencia débil (UUID suelto sin constraint).

### R6 — Verificación end-to-end

**As a** developer, **I want** confirmar que el esquema y las entidades funcionan de extremo a extremo, **so that** los changes siguientes (`domain-foundation-ops`, `auth-tenancy`) puedan construir sobre una base verificada.

Acceptance criteria:

1. WHEN se levanta el stack (`make up`) desde una DB vacía, THE SYSTEM SHALL dejar las 8 tablas creadas, verificable con un test de integración que las liste (o `\dt` en `psql`).
2. WHEN se instancia cada una de las 8 entidades de dominio en un test unitario, THE SYSTEM SHALL construirse sin necesitar la DB (Python puro, R2).

## Out of scope

- Las 18 entidades restantes de PRD §7 (cleaning, maintenance, messaging, access, pricing, financial, sistema) — cubiertas por `domain-foundation-ops` y `domain-foundation-financial`, que dependen de este change.
- Puertos de repositorio (`Protocol`/ABC), casos de uso, routers FastAPI — se crean en el change que primero necesite persistir/exponer cada entidad (`auth-tenancy` para `Tenant`/`User`, `reservations` para `Reservation`, etc.).
- `PropertyStateMachine` (transiciones reales entre `PropertyOperationalState`) y `TimelineService` (cuándo/cómo se registra un `TimelineEvent`) — roadmap `timeline-state-machine`.
- Auth (JWT, RBAC, password hashing real), middleware de tenant isolation — roadmap `auth-tenancy`.
- Cifrado/descifrado real (Fernet) de `wifi_password_encrypted` y `document_number_encrypted` — solo se reserva la columna; la implementación llega con el change que lea/escriba esos campos.
- Seed data (PRD §27) — roadmap `hardening-release`.

## Affected specs

- `sdd/specs/domain-foundation-core.md` (no existe aún — se creará al archivar este change).
