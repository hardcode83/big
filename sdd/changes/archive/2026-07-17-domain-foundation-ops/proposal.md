# Proposal: domain-foundation-ops

## Why

`domain-foundation-core` dejó el backbone de identidad/tenencia/propiedad/reserva (`Tenant`, `TenantConfig`, `User`, `Property`, `PropertyStateTransition`, `TimelineEvent`, `Guest`, `Reservation`), pero ninguna de las 18 entidades operativas restantes de PRD §7 existe todavía. De esas 18, este change cubre el segundo tercio — los **dominios operativos** (§26.2-3, §7.9-7.16): `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`, `Incident`, `Conversation`, `Message`, `AccessRecord`. El tercer tercio (`domain-foundation-financial`, pricing/financiero/logs de sistema) construye encima de este y de `domain-foundation-core`. Sin este esquema, ningún change posterior del roadmap (`cleaning`, `maintenance`, `messaging-ai`, `access-notifications`) tiene tabla sobre la que persistir.

## What changes

Se crean, por cada una de las 8 entidades, las mismas dos representaciones que estableció `domain-foundation-core`: una entidad de dominio en Python puro (`backend/app/<dominio>/domain/entities.py`, sin imports de `sqlalchemy`/`fastapi`/`pydantic`) y un modelo SQLAlchemy 2.x async (`backend/app/<dominio>/infrastructure/models.py`) que reproduce el esquema exacto de PRD §7.9-7.16, reutilizando los mixins ya existentes (`UUIDPrimaryKeyMixin`, `TimestampMixin`, `TenantScopedMixin` de `backend/app/core/db.py`) donde el esquema del PRD lo permite. Las 8 entidades se reparten en 4 módulos de dominio ya nombrados en `architecture.md`: `cleaning` (`CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`), `maintenance` (`Incident`), `messaging` (`Conversation`, `Message`), `access` (`AccessRecord`). Se crean los enums de dominio de estas 8 entidades (`CleaningTaskStatus`, `IncidentStatus`, `ConversationChannel`, etc., incluyendo nombre explícito para los enums que el PRD declara inline sin bloque propio — ver R1.3). Se añade una nueva migración Alembic encadenada sobre la baseline de `domain-foundation-core` (`down_revision = "4a5faad7796b"`) que crea las 8 tablas nuevas, reversible.

No se crean puertos de repositorio, casos de uso, routers ni lógica de negocio (validación de checklist, clasificación IA de incidencias, escalado de conversación, `StorageAdapter`/`AIAdapter`/adapters de acceso) — eso llega con `cleaning`, `maintenance`, `messaging-ai` y `access-notifications`, cuando exista un consumidor real de estas entidades (mismo YAGNI ya confirmado en `domain-foundation-core`).

## Requirements

### R1 — Enums de dominio exactos del PRD

**As a** developer, **I want** los enums de estas 8 entidades modelados con los mismos nombres y valores exactos del PRD, **so that** el código nunca diverja de la fuente de verdad funcional y los changes futuros (`cleaning`, `maintenance`, `messaging-ai`, `access-notifications`) puedan referenciarlos sin traducir strings.

Acceptance criteria:

1. WHEN se define un enum con bloque propio en el PRD (`CleaningTaskStatus` §7.9, `IncidentCategory`/`IncidentStatus` §7.13, `ConversationChannel` §7.14), THE SYSTEM SHALL usar los mismos nombres y valores literales del PRD, sin traducciones (p.ej. `CleaningTaskStatus.PENDING_REVIEW`, no `PendienteRevision`).
2. WHERE un enum se usa en más de una de estas 8 entidades, THE SYSTEM SHALL definirlo una sola vez en el módulo dueño de la entidad que lo usa primero (mismo patrón que `PropertyOperationalState`/`LegalRegistrationStatus` en `domain-foundation-core`) — dentro de este subconjunto ningún enum se comparte entre los 4 módulos, así que cada uno vive en su propio `domain/enums.py`.
3. WHERE el PRD declara un enum inline sin bloque de valores propio (p.ej. `CleaningTask.validation_status`, `Incident.source`/`severity`, `Conversation.status`/`escalation_status`, `Message.sender_type`, `AccessRecord.provider`/`status`/`created_mode`), THE SYSTEM SHALL asignarle un nombre explícito siguiendo la convención `<Entidad><Campo>` (p.ej. `CleaningValidationStatus`, `IncidentSource`, `ConversationEscalationStatus`, `AccessCreatedMode`) — marcado `ASSUMPTION` en el código porque el PRD no le da nombre — y mapearlo a un tipo `ENUM` nativo de Postgres con ese nombre explícito (nunca autogenerado), igual que el resto.
4. THE SYSTEM SHALL NOT reutilizar `TimelineSeverity` (`INFO`/`WARNING`/`ERROR`/`CRITICAL`, ya definido en `timeline/domain/enums.py`) para `Incident.severity` — el PRD les da conjuntos de valores distintos (`Incident.severity` es `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`), así que son dos enums distintos aunque el nombre se parezca.

### R2 — Entidades de dominio en Python puro

**As a** developer, **I want** cada una de las 8 entidades modelada como Python puro en `domain/entities.py`, **so that** el dominio sea testeable sin DB y no dependa de detalles de infraestructura (regla de dependencia de `backend-architecture.md`).

Acceptance criteria:

1. WHEN se modela `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`, `Incident`, `Conversation`, `Message` o `AccessRecord` en `backend/app/<dominio>/domain/entities.py`, THE SYSTEM SHALL implementarla sin ningún `import` de `sqlalchemy`, `fastapi` ni `pydantic`.
2. THE SYSTEM SHALL modelar las 8 entidades como `@dataclass` simple, sin métodos de mutación custom — ninguna de ellas tiene todavía un caso de uso real que proteja una invariante (mismo criterio aplicado a las 8 entidades de `domain-foundation-core`, ver su R2.2/R2.3).
3. THE SYSTEM SHALL NOT implementar en este change la lógica de validación de checklist (`CleaningTask`/`CleaningChecklistCompletion`), clasificación IA de incidencias (`Incident.ai_classification`), escalado de conversación (`Conversation.escalation_status`) ni generación de códigos de acceso (`AccessRecord`) — ver roadmap `cleaning`, `maintenance`, `messaging-ai`, `access-notifications`. Las entidades de este change son estructura de datos instanciable, no orquestación.
4. THE SYSTEM SHALL NOT crear interfaces de repositorio (`Protocol`/ABC) en `domain/repositories.py` en este change — se difieren al change que primero necesite persistir cada entidad, evitando puertos especulativos sin caso de uso real (mismo criterio que `domain-foundation-core` R2.4).

### R3 — Modelos SQLAlchemy 2.x async (ORM)

**As a** developer, **I want** un modelo SQLAlchemy declarativo async por entidad que reproduzca el esquema exacto del PRD, **so that** Alembic pueda generar el esquema real y los changes futuros tengan ya la tabla lista para sus repositorios.

Acceptance criteria:

1. WHEN se define el modelo SQLAlchemy de cada una de las 8 entidades en `backend/app/<dominio>/infrastructure/models.py`, THE SYSTEM SHALL reproducir exactamente columnas, tipos, nullability, defaults, `UNIQUE`/`INDEX` (incluidos los compuestos, p.ej. `INDEX(property_id, status)` + `INDEX(assigned_cleaner_id, status)` en `CleaningTask`; `UNIQUE(cleaning_task_id, item_id)` en `CleaningChecklistCompletion`; `INDEX(tenant_id, status)` + `INDEX(reservation_id)` en `Conversation`) de PRD §7.9-7.16.
2. WHERE el PRD declara la entidad con `tenant_id UUID FK→Tenant NOT NULL` y columnas `created_at`/`updated_at` (`CleaningTask`, `CleaningChecklistTemplate`, `Incident`, `Conversation`, `AccessRecord`), THE SYSTEM SHALL usar `TenantScopedMixin`/`TimestampMixin`/`UUIDPrimaryKeyMixin` de `backend/app/core/db.py`, igual que `domain-foundation-core`.
3. WHERE el PRD declara la entidad sin `tenant_id` propio porque se scopea transitivamente vía su entidad padre (`CleaningChecklistCompletion` y `CleaningPhoto` vía `cleaning_task_id`; `Message` vía `conversation_id`), THE SYSTEM SHALL NOT añadir un `tenant_id` que el PRD no declara — el aislamiento de tenant de estas 3 tablas se hereda de su FK padre, no de una columna propia.
4. WHERE el PRD declara la entidad solo con `created_at` sin `updated_at` (`CleaningPhoto`, `Message` — registros de evento inmutables) o sin ninguna de las dos (`CleaningChecklistCompletion` — solo `completed_at` nullable), THE SYSTEM SHALL reproducir exactamente esa ausencia, sin añadir `updated_at`/`created_at` que el PRD no pide.
5. WHEN una columna FK referencia una tabla de otro módulo (p.ej. `CleaningTask.property_id`→`properties.id`, `CleaningTask.reservation_id`→`reservations.id`, `Incident.property_id`→`properties.id`, `Conversation.guest_id`→`guests.id`, `AccessRecord.reservation_id`→`reservations.id`), THE SYSTEM SHALL declararla con tipo `Uuid` explícito en `mapped_column(Uuid, ForeignKey(...))` — nunca solo la anotación `Mapped[uuid.UUID]` — para evitar que SQLAlchemy la resuelva como `NullType` según el orden de import (deviation ya detectada y documentada en `domain-foundation-core`, D15).
6. WHERE una FK nullable referencia `User` (`CleaningTask.assigned_cleaner_id`, `CleaningTask.validated_by_user_id`, `Incident.reported_by_user_id`, `Incident.assigned_technician_id`, `Message.sender_user_id`), THE SYSTEM SHALL usar `ondelete="SET NULL"` (mismo criterio que `PropertyStateTransition.triggered_by_user_id`/`TimelineEvent.actor_user_id` en `domain-foundation-core`); toda otra FK obligatoria usa `ondelete="RESTRICT"` por defecto.
7. WHERE el PRD declara una columna `JSONB` (`CleaningChecklistTemplate.items`/`required_photos`, `CleaningTask.notes`... `Incident.ai_classification`, `Message.metadata`, etc.), THE SYSTEM SHALL mapearla a `JSONB` de Postgres sin validar su estructura interna en este change — el schema de esos JSON (p.ej. el de `items`/`required_photos` documentado en PRD §7.10) no se valida a nivel de DB, solo se persiste.

### R4 — Migraciones Alembic (encadenada sobre la baseline de `domain-foundation-core`)

**As a** developer, **I want** una migración Alembic que añada estas 8 tablas sobre el esquema ya existente, **so that** el stack local tenga el esquema completo de dominios operativos desde el primer `make up` tras este change.

Acceptance criteria:

1. WHEN se genera la migración de este change, THE SYSTEM SHALL encadenarla como `down_revision = "4a5faad7796b"` (la baseline de `domain-foundation-core`) — no una nueva baseline independiente.
2. WHEN se ejecuta `alembic upgrade head` sobre una DB que ya tiene el esquema de `domain-foundation-core`, THE SYSTEM SHALL crear las 8 tablas nuevas (`cleaning_tasks`, `cleaning_checklist_templates`, `cleaning_checklist_completions`, `cleaning_photos`, `incidents`, `conversations`, `messages`, `access_records`) con su esquema completo (columnas, FKs, constraints, índices, tipos ENUM de Postgres).
3. WHEN se ejecuta `alembic downgrade` hasta la revisión de `domain-foundation-core`, THE SYSTEM SHALL revertir exactamente estas 8 tablas y sus tipos ENUM sin dejar huérfanos ni afectar las tablas de `domain-foundation-core`.
4. WHEN arranca el stack (`make up`), THE SYSTEM SHALL aplicar esta migración automáticamente vía el servicio `migrate` ya existente (`domain-foundation-core`, D11) — sin paso manual adicional.

### R5 — Integridad referencial hacia entidades ya existentes

**As a** developer, **I want** que las FKs hacia `domain-foundation-core` queden bien definidas, **so that** los changes de negocio (`cleaning`, `maintenance`, `messaging-ai`, `access-notifications`) no tengan que rediseñar el esquema.

Acceptance criteria:

1. WHEN una FK de estas 8 entidades referencia una entidad de `domain-foundation-core` (`Property`, `Reservation`, `Guest`, `User`), THE SYSTEM SHALL declararla como FK real contra la tabla ya existente, nunca como referencia débil (UUID suelto sin constraint).
2. THE SYSTEM SHALL tener un índice sobre `tenant_id` en toda tabla de este change que lo declare (`cleaning_tasks`, `cleaning_checklist_templates`, `incidents`, `conversations`, `access_records`), coherente con el patrón que `auth-tenancy` usará para el middleware de aislamiento.

### R6 — Verificación end-to-end

**As a** developer, **I want** confirmar que el esquema y las entidades funcionan de extremo a extremo junto al esquema ya existente, **so that** los changes siguientes puedan construir sobre una base verificada.

Acceptance criteria:

1. WHEN se levanta el stack (`make up`) desde una DB vacía, THE SYSTEM SHALL dejar las 16 tablas (8 de `domain-foundation-core` + 8 de este change) creadas, verificable con un test de integración que las liste.
2. WHEN se instancia cada una de las 8 entidades de dominio en un test unitario, THE SYSTEM SHALL construirse sin necesitar la DB (Python puro, R2).
3. WHEN se ejecuta un test de integración que fuerza la violación de una constraint `UNIQUE` real (p.ej. insertar dos `CleaningChecklistCompletion` con el mismo `(cleaning_task_id, item_id)`), THE SYSTEM SHALL rechazarla a nivel de DB.

## Out of scope

- Las 10 entidades restantes de PRD §7 (pricing/financiero/logs de sistema: `PricingRule`, `PriceRecommendation`, `OwnerApproval`, `Review`, `ReviewResponseDraft`, `OwnerStatement`, `Expense`, `NotificationLog`, `AuditLog`, `WebhookEvent`) — cubiertas por `domain-foundation-financial`.
- Puertos de repositorio, casos de uso, routers FastAPI — se crean en el change que primero necesite persistir/exponer cada entidad (`cleaning`, `maintenance`, `messaging-ai`, `access-notifications`).
- Lógica de negocio real: validación de checklist de limpieza, clasificación IA de incidencias, `MockAIAdapter`/escalado de conversación, `ManualAccessAdapter`/generación de códigos — roadmap `cleaning`, `maintenance`, `messaging-ai`, `access-notifications`.
- Cifrado/descifrado real de cualquier campo sensible (ninguna columna de estas 8 entidades está marcada como cifrada en el PRD, a diferencia de `Property.wifi_password_encrypted`/`Guest.document_number_encrypted` en `domain-foundation-core`).
- `StorageAdapter` real para `CleaningPhoto.storage_key`/signed URLs — roadmap `cleaning` (`security.md` #5).
- Seed data (PRD §27) — roadmap `hardening-release`.

## Affected specs

- `sdd/specs/domain-foundation-ops.md` (no existe aún — se creará al archivar este change).
