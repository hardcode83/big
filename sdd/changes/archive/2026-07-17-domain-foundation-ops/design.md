# Design: domain-foundation-ops

## Context

`domain-foundation-core` established the pattern this change follows exactly: per entity, a pure-Python dataclass in `domain/entities.py` + an async SQLAlchemy model in `infrastructure/models.py`, reusing three mixins from `backend/app/core/db.py` (`UUIDPrimaryKeyMixin`, `TimestampMixin`, `TenantScopedMixin`), one native-Postgres-`ENUM` type per domain enum, and a single Alembic migration. None of the four target modules (`cleaning`, `maintenance`, `messaging`, `access`) exist yet — `backend/app/` currently only has `auth`, `core`, `guests`, `properties`, `reservations`, `tenants`, `timeline`. The baseline migration `4a5faad7796b_baseline_domain_foundation_core.py` (`down_revision = None`) created the 8 core tables; this change's migration chains onto it. Two wiring points register new domain modules for SQLAlchemy/Alembic to see them: `backend/alembic/env.py` (imports every domain's `infrastructure/models.py` so `Base.metadata` is complete for autogenerate) and `backend/tests/conftest.py` (same imports, for the `db_session` fixture's `create_all`/`drop_all`).

## Decisions

### D1 — Module assignment (already fixed by the proposal, confirmed against `architecture.md`)

**Chosen:** `cleaning/` → `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto`; `maintenance/` → `Incident`; `messaging/` → `Conversation`, `Message`; `access/` → `AccessRecord`. All four are already named in `architecture.md`'s domain list. Each module gets only `domain/` (entities + enums) and `infrastructure/` (models) — no `application/`/`api/` yet, same as `domain-foundation-core`.

Rejected: putting all 4 checklist/photo entities under a generic `cleaning` module but splitting `CleaningChecklistTemplate` into a shared `templates` module — no other domain needs a generic template concept yet, premature abstraction.

### D2 — Names for PRD-inline enums (no bloque propio)

**Chosen:** the PRD gives 9 of this change's enums as inline `ENUM(...)` literals without a named block (unlike `CleaningTaskStatus`, `IncidentCategory`, `IncidentStatus`, `ConversationChannel`, which do get their own named section). These need an explicit Python/Postgres name regardless (R1.3). Convention: `<Entity><Field>`, PascalCase:

| PRD location | Values | Chosen name |
|---|---|---|
| `CleaningTask.validation_status` | `PENDING, PASSED, FAILED, WAIVED` | `CleaningValidationStatus` |
| `Incident.source` | `GUEST, CLEANER, OWNER, SYSTEM, PMS, LOCK_ALERT` | `IncidentSource` |
| `Incident.severity` | `LOW, MEDIUM, HIGH, CRITICAL` | `IncidentSeverity` |
| `Conversation.status` | `OPEN, RESOLVED, ESCALATED, CLOSED` | `ConversationStatus` |
| `Conversation.escalation_status` | `NONE, PENDING_HUMAN, HUMAN_HANDLING, RESOLVED` | `ConversationEscalationStatus` |
| `Message.sender_type` | `GUEST, OWNER, MANAGER, AI, SYSTEM` | `MessageSenderType` |
| `AccessRecord.provider` | `GRINPASS, MANUAL, MOCK, EXTERNAL_MANAGED` | `AccessProvider` |
| `AccessRecord.status` | `PENDING, CREATED_EXTERNAL, MANUAL_ADDED, DELIVERED, EXPIRED, REVOKED` | `AccessRecordStatus` |
| `AccessRecord.created_mode` | `EXTERNAL_PMS_AUTOMATIC, MANUAL, MOCK` | `AccessCreatedMode` |

Every one of these is marked `ASSUMPTION` in the code (docstring/comment on the enum) — the PRD doesn't name them, so a future PRD revision could pick a different name without changing values; the mapping to Postgres column values is unaffected either way. `Incident.severity` is deliberately **not** unified with the already-existing `TimelineSeverity` (`INFO/WARNING/ERROR/CRITICAL`, `app/timeline/domain/enums.py`) — different value sets, coincidental name similarity only (R1.4).

Rejected: generic shared names (`ValidationStatus`, `Status`, `Source`) reused across entities — collides in intent even where values differ, and the project's existing convention (`ReservationStatus`, `PropertyStatus`, ...) is always entity-prefixed.

**Flagging as open question below** — naming unnamed PRD enums is the one place this design invents something not in the source of truth; worth a quick confirm before implementation.

### D3 — Tenant scoping: mixin vs. transitive via parent FK

**Chosen:** `CleaningTask`, `CleaningChecklistTemplate`, `Incident`, `Conversation`, `AccessRecord` use `TenantScopedMixin` (own `tenant_id` FK + index), matching every PRD schema that declares `tenant_id UUID FK→Tenant NOT NULL`. `CleaningChecklistCompletion`, `CleaningPhoto`, `Message` do **not** get a `tenant_id` column — the PRD doesn't declare one for these three; they're child records reachable only through `cleaning_task_id`/`conversation_id`, so tenant isolation for them is enforced by joining through the parent (same posture `TimelineEvent`/`PropertyStateTransition` established for `updated_at` omission in `domain-foundation-core`, applied here to `tenant_id` omission instead).

Rejected: adding `tenant_id` to all 8 for uniformity — would diverge from the PRD schema (extra column, extra migration surface) for no query `auth-tenancy` actually needs yet; scoping via the parent join is sufficient and is what the PRD models.

### D4 — Timestamp columns per entity

**Chosen:** follow the PRD schema exactly per entity, same three-way split `domain-foundation-core` used for `PropertyStateTransition`/`TimelineEvent`:

| Entity | Timestamp columns | Mixin |
|---|---|---|
| `CleaningTask`, `CleaningChecklistTemplate`, `Incident`, `Conversation`, `AccessRecord` | `created_at` + `updated_at` | `TimestampMixin` |
| `CleaningPhoto`, `Message` | `created_at` only | manual column (no `TimestampMixin`), same pattern as `TimelineEventModel` |
| `CleaningChecklistCompletion` | neither — only nullable `completed_at` | no timestamp mixin/columns at all |

Rejected: giving `CleaningChecklistCompletion` a `created_at` for auditability — not in the PRD schema (7.11), and its parent `CleaningTask.created_at` plus `completed_at`/`completed_by` already cover the audit need this table exists for.

### D5 — Cross-module FK typing (explicit `Uuid`)

**Chosen:** every FK column referencing a table outside its own module uses `mapped_column(Uuid, ForeignKey("<table>.id", ondelete=...))` with `Uuid` imported explicitly from `sqlalchemy` — never bare `Mapped[uuid.UUID]` — for `CleaningTask.property_id`/`reservation_id`, `Incident.property_id`/`reservation_id`, `Conversation.property_id`/`reservation_id`/`guest_id`, `AccessRecord.property_id`/`reservation_id`. This is the exact deviation `domain-foundation-core` hit and fixed as D15 (`NullType` if the referenced module isn't imported yet when the column is evaluated) — applying it from the start here avoids re-discovering the same bug.

Rejected: relying on import order in `env.py`/`conftest.py` alone to avoid `NullType` — D15 showed that's necessary but not sufficient; the explicit type on the column itself is what actually removes the hazard.

### D6 — `ON DELETE` policy

**Chosen:** same rule `domain-foundation-core` set: nullable FKs to `User` get `ondelete="SET NULL"` (`CleaningTask.assigned_cleaner_id`, `CleaningTask.validated_by_user_id`, `Incident.reported_by_user_id`, `Incident.assigned_technician_id`, `Message.sender_user_id`) so purging a user doesn't destroy history; every other FK (to `Property`, `Reservation`, `Guest`, `CleaningTask`, `Conversation`, and required `User` FKs like `CleaningPhoto.uploaded_by`) gets `ondelete="RESTRICT"`, since the PRD models deletion via status fields, never real `DELETE`.

Rejected: `CASCADE` for `CleaningChecklistCompletion`/`CleaningPhoto` on their parent `CleaningTask` — the PRD doesn't model `CleaningTask` deletion at all (status-based like everything else), so cascade delete is speculative behavior with no requirement behind it; `RESTRICT` matches the rest of the schema's posture.

### D7 — `metadata` column name collision

**Chosen:** `Message.metadata` (PRD §7.15, JSONB) collides with SQLAlchemy's reserved `Base.metadata` attribute. Follow the exact precedent `TimelineEventModel` already set: Python attribute `metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)` — mapped to the real column name `metadata` while avoiding the attribute clash.

Rejected: renaming the column itself (e.g. `meta`) — breaks fidelity with the PRD's exact schema (R3.1) for no real benefit; the mapped-column-name trick keeps DB and PRD in sync while sidestepping the ORM-level naming conflict.

### D8 — JSONB structural validation

**Chosen:** `CleaningChecklistTemplate.items`/`required_photos`, `CleaningTask.notes` (plain `TEXT`, not JSONB — no change needed there), `Incident.ai_classification`, `Message.metadata` all map to Postgres `JSONB` with no structural validation at the DB or ORM layer in this change — matches `domain-foundation-core`'s posture for `TimelineEvent.metadata`. The `items`/`required_photos` array shape documented in PRD §7.10 is descriptive for the future `cleaning` change, not enforced here.

Rejected: a Pydantic model validating the JSONB shape at write time — there's no write path yet (no repository/use case exists in this change), so validation would have no caller and no test that could exercise it (YAGNI, same posture as R2.4).

### D9 — Migration chaining and wiring

**Chosen:** the new migration's `down_revision = "4a5faad7796b"`. `backend/alembic/env.py` gets 4 new import lines (`app.cleaning.infrastructure.models`, `app.maintenance.infrastructure.models`, `app.messaging.infrastructure.models`, `app.access.infrastructure.models`), appended after the existing 6, following the file's own comment ("Add new domains here, in dependency order, as later changes introduce them"). `backend/tests/conftest.py` gets the same 4 imports for the same reason (`db_session` fixture's `Base.metadata.create_all`/`drop_all`). Order among the 4 new modules doesn't matter to each other (no FKs between them), only that they come after the 6 existing ones they FK into.

Rejected: a separate `env.py`-equivalent per domain — Alembic's `target_metadata = Base.metadata` design requires one process-wide metadata registry; this is inherent to the tool, not a choice.

## Changes by area

| Area | Files | Change |
|---|---|---|
| `cleaning` | `backend/app/cleaning/domain/{entities,enums}.py`, `backend/app/cleaning/infrastructure/models.py` | New — `CleaningTask`, `CleaningChecklistTemplate`, `CleaningChecklistCompletion`, `CleaningPhoto` |
| `maintenance` | `backend/app/maintenance/domain/{entities,enums}.py`, `backend/app/maintenance/infrastructure/models.py` | New — `Incident` |
| `messaging` | `backend/app/messaging/domain/{entities,enums}.py`, `backend/app/messaging/infrastructure/models.py` | New — `Conversation`, `Message` |
| `access` | `backend/app/access/domain/{entities,enums}.py`, `backend/app/access/infrastructure/models.py` | New — `AccessRecord` |
| Alembic | `backend/alembic/env.py`, `backend/alembic/versions/<new>_domain_foundation_ops.py` | `env.py`: 4 new imports (D9). New migration file, `down_revision="4a5faad7796b"`, creates 8 tables + explicit `DROP TYPE` list on downgrade (same pattern as the baseline's `_ENUM_TYPE_NAMES`) |
| Tests | `backend/tests/conftest.py`, `backend/tests/{cleaning,maintenance,messaging,access}/` | `conftest.py`: 4 new imports (D9). New test dirs mirroring `backend/tests/{tenants,auth,...}/` — unit tests per entity (pure instantiation) + integration tests per model (schema + at least one real `UNIQUE` violation, R6.3) |

## Data & interfaces

- 8 new tables: `cleaning_tasks`, `cleaning_checklist_templates`, `cleaning_checklist_completions`, `cleaning_photos`, `incidents`, `conversations`, `messages`, `access_records` — exact columns/types/constraints per PRD §7.9-7.16.
- 13 new enum types (D2's 9-row table + `CleaningTaskStatus`, `IncidentCategory`, `IncidentStatus`, `ConversationChannel` which already have PRD-given names) — see proposal R1 for the full accounting.
- No API contracts, no new env vars — this change has no `application/`/`api/` layer (same as `domain-foundation-core`).
- FK surface added onto `domain-foundation-core`'s tables: `properties.id`, `reservations.id`, `guests.id`, `users.id` all gain new inbound FKs from this change's tables; none of `domain-foundation-core`'s own migration/schema changes.

## Risks & mitigations

- **Enum names not in the PRD (D2) drift from a future PRD revision that does name them**: mitigated by marking each `ASSUMPTION` in code; a future PRD update only requires a rename, not a value change, and is a one-line grep-and-replace.
- **`metadata` naming collision (D7) missed on a future JSONB column**: mitigated by this design calling it out explicitly and by `TimelineEventModel` already being a working precedent to copy from directly.
- **Import-order `NullType` bug (D5) recurring**: mitigated by making `Uuid` explicit on every cross-module FK from the start, rather than discovering it per-column during `/sdd:run` as `domain-foundation-core` did.
- **Migration chain drift**: if `domain-foundation-core`'s migration were ever amended after archiving, this change's `down_revision` pointer would break — low risk (baseline is already archived and stable), no mitigation needed beyond not editing archived migrations.

## Open questions

None pending — the D2 enum-naming table was confirmed with the user during `/sdd:design` (proceed with `<Entity><Field>`, each marked `ASSUMPTION` in code).
