# Modelos de dominio y esquema DB — dominios operativos

## Purpose

Entidades de dominio y esquema de base de datos para las 8 entidades del PRD (§7.9-7.16) que forman los dominios operativos: `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`, `Incident`, `Conversation`, `Message`, `AccessRecord`. Construye sobre el backbone de `domain-foundation-core` (`Tenant`, `Property`, `Reservation`, `Guest`, `User`) — solo estructura de datos (entidades + esquema + migraciones), sin lógica de negocio, repositorios, casos de uso ni endpoints todavía. El tercer tercio del PRD §7 (`domain-foundation-financial`) construye encima de este y de `domain-foundation-core`.

## Requirements

### Estructura por módulo de dominio

- Las 8 entidades se reparten en 4 módulos de dominio ya nombrados en `architecture.md`: `cleaning` (`CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`), `maintenance` (`Incident`), `messaging` (`Conversation`, `Message`), `access` (`AccessRecord`).
- Este change aportó a cada módulo solo `domain/` (entidades Python puras + enums) e `infrastructure/` (modelos SQLAlchemy). El `application/` y el `api/` de cada uno los añade el change que primero persiste/expone la entidad: `cleaning` lo hizo para las cuatro suyas y `access-notifications` para `AccessRecord`; `maintenance` (`Incident`) y `messaging-ai` (`Conversation`, `Message`) siguen sin ellos.
- `domain/entities.py` y `domain/enums.py` de los 4 módulos no importan `sqlalchemy`, `fastapi` ni `pydantic` (regla de dependencia de `backend-architecture.md`, verificable).
- Los puertos de repositorio (`Protocol`/ABC) y los casos de uso llegan con ese mismo change por entidad — `CleaningTask` y compañía en `cleaning`, `AccessRecord` en `access-notifications`; `Incident`, `Conversation` y `Message` todavía no los tienen.
- Las entidades nacieron aquí como `@dataclass` simple, sin métodos de mutación custom, porque ninguna tenía aún un caso de uso que protegiera una invariante. Las que ya lo tienen los han ganado después: `AccessRecord` lleva desde `access-notifications` su máquina de estados en la propia entidad (`register_manual_code`, `mark_external_managed`, `mark_delivered`, `revoke`, `expire`). Las tres sin dueño siguen siendo dataclasses planas.

### Enums de dominio exactos del PRD

- Los enums con bloque propio en el PRD (`CleaningTaskStatus` §7.9, `IncidentCategory`/`IncidentStatus` §7.13, `ConversationChannel` §7.14) usan los mismos nombres y valores literales, sin traducciones.
- Los enums que el PRD declara inline sin bloque de valores propio (`CleaningTask.validation_status`, `Incident.source`/`severity`, `Conversation.status`/`escalation_status`, `Message.sender_type`, `AccessRecord.provider`/`status`/`created_mode` — 9 en total) tienen nombre explícito inventado siguiendo la convención `<Entidad><Campo>` (`CleaningValidationStatus`, `IncidentSource`, `IncidentSeverity`, `ConversationStatus`, `ConversationEscalationStatus`, `MessageSenderType`, `AccessProvider`, `AccessRecordStatus`, `AccessCreatedMode`), marcado `ASSUMPTION` en el código porque el PRD no les da nombre.
- `Incident.severity` (`IncidentSeverity`: `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) es un enum distinto de `TimelineSeverity` (`INFO`/`WARNING`/`ERROR`/`CRITICAL`, ya definido en `timeline/domain/enums.py`) — conjuntos de valores distintos, no se reutilizan pese al nombre parecido.
- Ningún enum se comparte entre los 4 módulos de este subconjunto — cada uno vive en su propio `domain/enums.py`.

### Esquema DB — modelos SQLAlchemy 2.x async

- Cada entidad tiene un modelo SQLAlchemy declarativo en `infrastructure/models.py` que reproduce exactamente el esquema del PRD: columnas, tipos, nullability, `UNIQUE`/`INDEX` (incluidos los compuestos — `INDEX(property_id, status)` + `INDEX(assigned_cleaner_id, status)` en `CleaningTask`; `UNIQUE(cleaning_task_id, item_id)` en `CleaningChecklistCompletion`; `INDEX(tenant_id, severity, status)` en `Incident`; `INDEX(tenant_id, status)` en `Conversation`; `INDEX(conversation_id, created_at)` en `Message`; `INDEX(property_id, valid_from, valid_to)` en `AccessRecord`).
- `CleaningTask`, `CleaningChecklistTemplate`, `Incident`, `Conversation` y `AccessRecord` usan los mixins compartidos `UUIDPrimaryKeyMixin`/`TenantScopedMixin`/`TimestampMixin` (`backend/app/core/db.py`) — tienen `tenant_id` FK obligatoria y `created_at`/`updated_at`, igual que el PRD declara para ellas.
- `CleaningChecklistCompletion`, `CleaningPhoto` y `Message` **no** tienen `tenant_id` propio — son registros hijos scopeados de forma transitiva vía su FK padre (`cleaning_task_id` o `conversation_id`, ambas FK obligatorias con `ON DELETE RESTRICT`), porque el PRD no les declara esa columna. `CleaningPhoto` y `Message` tienen solo `created_at` manual (sin `TimestampMixin`, registros de evento inmutables); `CleaningChecklistCompletion` no tiene ni `created_at` ni `updated_at` (solo `completed_at` nullable).
- **Consecuencia de ese scoping transitivo, medida al construir `cleaning` (2026-08-07)**: `tenant_scoped_classes()` (`app/core/db.py`) selecciona las clases acotadas **por la presencia de la columna `tenant_id`**, así que el filtro global de `with_loader_criteria` **no cubre** estas tres tablas. Para ellas el `JOIN` con el padre no es defensa en profundidad: es el único mecanismo de aislamiento, y por eso cada una exige test propio del que ya tienen `cleaning_checklist_completions` y `cleaning_photos` (ver `cleaning.md`). `cleaning_photos` ganó escritor con `cleaning-photos-storage`, que cumplió esa obligación: todas sus consultas parten del `JOIN` con `cleaning_tasks`, y el cruce de tenant tiene tests propios en subida, listado y URL firmada. `messages` sigue sin escritor y hereda la obligación en `messaging-ai`.
- Todo enum de dominio se mapea a un tipo `ENUM` nativo de Postgres con nombre explícito (`sa.Enum(X, name="...", native_enum=True)`), nunca autogenerado.
- Las FKs que referencian una tabla de otro módulo (`property_id`, `reservation_id`, `guest_id`, `checklist_template_id`, `cleaning_task_id`, `conversation_id`, FKs a `users.id`) usan un tipo `Uuid` explícito en `mapped_column`, no solo la anotación `Mapped[uuid.UUID]` — evita que SQLAlchemy la resuelva como `NullType` según el orden de import (mismo fix que `domain-foundation-core` D15).
- FKs nullable hacia `User` (`CleaningTask.assigned_cleaner_id`/`validated_by_user_id`, `CleaningChecklistCompletion.completed_by`, `Incident.reported_by_user_id`/`assigned_technician_id`, `Message.sender_user_id`) usan `ON DELETE SET NULL` — el resto de FKs (incluida la obligatoria `CleaningPhoto.uploaded_by`) usan `ON DELETE RESTRICT`.
- `Message.metadata` se mapea con el atributo Python `metadata_` a la columna real `"metadata"` (`mapped_column("metadata", JSONB, ...)`) para evitar la colisión con el atributo reservado `Base.metadata` de SQLAlchemy — mismo patrón que `TimelineEventModel`.
- Columnas `JSONB` (`CleaningChecklistTemplate.items`/`required_photos`, `CleaningTask` no tiene JSONB propio, `Incident.ai_classification`, `Message.metadata`, `CleaningPhoto.ai_validation_result`) no validan su estructura interna en este change — solo se persisten.
- `AccessRecord.code_masked` solo almacena el valor enmascarado (`****XX`), y **no existe ni existirá** columna de código de acceso en texto plano ni cifrado. `access-notifications` resolvió que no hace falta ninguna: PRD §15 deja la cerradura y la entrega del código en manos del proveedor, así que nadie en el MVP necesita el valor completo y cifrarlo exigiría un consumidor que no hay. El código llega en la petición, se reduce a su máscara y se descarta (ver `access-notifications.md`).

### Migraciones Alembic

- Una migración (`backend/alembic/versions/a1a72da30f8e_domain_foundation_ops.py`) encadenada sobre la baseline de `domain-foundation-core` (`down_revision = "4a5faad7796b"`) crea las 8 tablas nuevas sobre el esquema existente, en orden de dependencia, reversible.
- `alembic downgrade` hasta la revisión de `domain-foundation-core` revierte exactamente estas 8 tablas y sus 13 tipos `ENUM` nuevos, sin afectar las tablas/tipos de `domain-foundation-core` ni dejar huérfanos (`_ENUM_TYPE_NAMES` + `DROP TYPE` explícito, mismo patrón que la baseline).
- Al arrancar el stack local (`make up`), el servicio `migrate` ya existente (de `domain-foundation-core`) aplica esta migración automáticamente junto con la baseline — sin paso manual adicional.
- `backend/alembic/env.py` y `backend/tests/conftest.py` registran los 4 módulos nuevos (`cleaning`, `maintenance`, `messaging`, `access`) importando su `infrastructure/models.py`, añadidos después de los 6 módulos de `domain-foundation-core`.

### Tests

- Cada entidad tiene un test unitario que la instancia en Python puro, sin necesitar la base de datos.
- Cada modelo SQLAlchemy tiene un test de integración contra Postgres real, incluyendo casos que fuerzan comportamiento a nivel de DB: la violación de `UNIQUE(cleaning_task_id, item_id)`, el `RESTRICT` en FKs obligatorias/nullable hacia `Property`/`Reservation`/`Conversation`/`CleaningTask`, el `SET NULL` en FKs nullable hacia `User`, y la distinción real de tipos `ENUM` de Postgres entre `incident_severity` y `timeline_severity`.
- Los tests de integración corren contra la base de datos de test aislada `<nombre-dev>_test` (mismo patrón que `domain-foundation-core`), nunca contra la que gestiona `make up`/`migrate`.

## Key files

- `backend/app/cleaning/{domain,infrastructure}/` — `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`.
- `backend/app/maintenance/{domain,infrastructure}/` — `Incident`.
- `backend/app/messaging/{domain,infrastructure}/` — `Conversation`, `Message`.
- `backend/app/access/{domain,infrastructure}/` — `AccessRecord`.
- `backend/alembic/env.py`, `backend/alembic/versions/a1a72da30f8e_domain_foundation_ops.py`.
- `backend/tests/{cleaning,maintenance,messaging,access}/`, `backend/tests/conftest.py`.
