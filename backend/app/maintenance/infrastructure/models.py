import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.domain.enums import UserRole
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.maintenance.domain.entities import MAX_INCIDENT_MESSAGE_LENGTH
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentPhotoStage,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)


class IncidentModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_property_id_status", "property_id", "status"),
        Index("ix_incidents_tenant_id_severity_status", "tenant_id", "severity", "status"),
        # No column of this table changes. What this buys is a target: Postgres requires a
        # composite foreign key to reference a declared unique key, and
        # `incident_photos.(tenant_id, incident_id)` references exactly this pair
        # (`incident-photos` D2, R1.3) so that a photo of tenant A can never be attached to an
        # incident of tenant B. With two independent single-column foreign keys that row is
        # legal, which is what the panels of `guest-portal-api` reproduced for its own case.
        #
        # It cannot fail on existing data: `id` is already the primary key, so `(tenant_id, id)`
        # is unique for free. Exact precedent, down to the name shape:
        # `uq_reservations_tenant_id_id`, which exists so `guest_access_tokens` can point at it.
        UniqueConstraint("tenant_id", "id", name="uq_incidents_tenant_id_id"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("properties.id", ondelete="RESTRICT"))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # `RESTRICT` like `property_id` and `reservation_id` above, not the `SET NULL` of the
    # two FKs towards `users`: losing the link is worst precisely when someone deletes the
    # task (`cleaner-incident-report` D10).
    cleaning_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cleaning_tasks.id", ondelete="RESTRICT"), default=None
    )
    reported_by_guest_token: Mapped[str | None] = mapped_column(String(200), default=None)
    source: Mapped[IncidentSource] = mapped_column(Enum(IncidentSource, name="incident_source", native_enum=True))
    category: Mapped[IncidentCategory] = mapped_column(
        Enum(IncidentCategory, name="incident_category", native_enum=True),
        default=IncidentCategory.OTHER,
        server_default=IncidentCategory.OTHER.value,
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity", native_enum=True),
        default=IncidentSeverity.MEDIUM,
        server_default=IncidentSeverity.MEDIUM.value,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", native_enum=True),
        default=IncidentStatus.OPEN,
        server_default=IncidentStatus.OPEN.value,
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column()
    ai_summary: Mapped[str | None] = mapped_column(default=None)
    # `none_as_null=True` is load-bearing and was missing (found by the manual end-to-end
    # check of the `maintenance` change, task 10.5). SQLAlchemy's JSON types render a Python
    # `None` **assigned to the attribute** as JSON `'null'`, not as SQL `NULL`; only an
    # attribute nobody sets falls through to the column default. The writer sets every field
    # explicitly — on purpose, so a column it currently expects to be default is not
    # silently dropped — so every incident created through `SqlAlchemyIncidentRepository.add`
    # was stored with `'null'::jsonb`.
    #
    # That is not cosmetic: design D3 makes `status = OPEN AND ai_classification IS NULL` the
    # candidate rule of the classification job, and `'null'::jsonb IS NULL` is false. The job
    # therefore considered **zero** incidents for every incident a real caller had created,
    # while every test passed — the fixtures build the model without the keyword, so they got
    # SQL NULL. No migration: this is a Python-side flag and the DDL is unchanged.
    ai_classification: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), default=None
    )
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # The width lives in the DDL and not only in pydantic, which is the pattern `properties`
    # follows (`MAX_NAME`, `MAX_ADDRESS`…) and what `properties-crud` R2.4 had to retrofit on
    # four columns that shipped without one. `MAX_ASSIGNMENT_NOTE` in `api/schemas.py` mirrors
    # this number, and `tests/maintenance/test_models.py` pins it here.
    assignment_note: Mapped[str | None] = mapped_column(String(2000), default=None)
    # The hour the technician promised (`tech-cycle-completion` R3.1). `TIMESTAMPTZ` like every
    # other instant in the schema, and nullable because most incidents never carry one — the
    # column belongs to the assignment in force, and `assign`/`reject` return it to `NULL`.
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # What the technician says they put in (R4.1). `String(2000)` and not `Text` for
    # `assignment_note`'s reason: the width lives in the DDL as well as in pydantic, so an
    # over-long value is a `422` and not a driver error that aborts the transaction.
    # `MAX_MATERIALS` in `maintenance/domain/entities.py` mirrors this number,
    # `tests/maintenance/test_models.py` pins it here, and `tests/test_migrations.py` reads it
    # back out of the real DDL.
    materials: Mapped[str | None] = mapped_column(String(2000), default=None)
    owner_approval_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    approved_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    final_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class OwnerApprovalModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """No TimestampMixin: §7.19 declares requested_at/responded_at and nothing else.

    Strict PRD fidelity, decided in the design gate (OQ1). The trade-off is recorded:
    `status` mutates (PENDING → APPROVED/REJECTED/EXPIRED), so this is the only
    editable table in the schema without `updated_at`, and an expiry driven by a job
    leaves `responded_at` NULL with no trace of when it happened. `maintenance` adds
    the column if its approval flow needs it — the table is empty until then.
    """

    __tablename__ = "owner_approvals"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    related_type: Mapped[OwnerApprovalRelatedType] = mapped_column(
        Enum(OwnerApprovalRelatedType, name="owner_approval_related_type", native_enum=True)
    )
    # Polymorphic pair (§7.19): related_id points at a different table depending on
    # related_type, so it deliberately carries no ForeignKey. Not an oversight.
    related_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column()
    status: Mapped[OwnerApprovalStatus] = mapped_column(
        Enum(OwnerApprovalStatus, name="owner_approval_status", native_enum=True),
        default=OwnerApprovalStatus.PENDING,
        server_default=OwnerApprovalStatus.PENDING.value,
    )
    # `requested_at` IS this row's creation timestamp — §7.19 declares no created_at
    # precisely because this column plays that role — so it gets the same
    # server_default every creation timestamp in the schema gets. The PRD declares
    # `created_at TIMESTAMPTZ NOT NULL` with no DEFAULT in all 23 tables of §7 and
    # `TimestampMixin` defaults them all; singling this one out would be the
    # inconsistency, not the fidelity (design D5, panel section 2).
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    response_notes: Mapped[str | None] = mapped_column(default=None)


class IncidentPhotoModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """One photo of one incident (`incident-photos` R1, design D1/D2/D3).

    `ASSUMPTION`: not in the PRD — §7.13 `Incident` declares no photo column and §7 defines
    only `CleaningPhoto` (§7.12). The entity's docstring
    (`app/maintenance/domain/entities.py`) carries the full reasoning.

    **`TenantScopedMixin`, unlike `cleaning_photos`** (R1.3, D2). The mixin's `tenant_id` is
    what puts this class into `tenant_scoped_classes()` — which resolves from the SQLAlchemy
    mapper registry, so it is *this* class and not the domain dataclass that enters the global
    filter of `app/core/db.py`. `cleaning_photos` never gets there and is scoped through its
    parent task instead; that omission is historical, and this is the deliberate departure.

    **No `TimestampMixin`.** It would bring `updated_at`, and the row is immutable after insert
    — the port declares `add` and `list_for_incident` and no `save`. `created_at` is therefore
    declared by hand, and **without `server_default`**, which is the one place this model is
    stricter than `cleaning_photos`: Postgres `now()` is the *transaction* timestamp, so a burst
    of photos inserted together would all share one instant and `list_for_incident`'s ordering
    would fall through to a random `uuid4`. The use case passes the real upload time, which is
    the order R3.1 asks the listing to preserve. (`cleaning_photos` carries the default *and*
    has its repository override it — same fix, one layer later.)
    """

    __tablename__ = "incident_photos"
    __table_args__ = (
        # D2's invariant, and the reason `uq_incidents_tenant_id_id` exists above: the photo's
        # tenant and its incident's tenant cannot diverge, because there is no pair of values
        # that satisfies this constraint and disagrees. Two independent single-column foreign
        # keys would leave the cross-tenant row legal and rely on every writer remembering.
        #
        # `ON DELETE RESTRICT`, not CASCADE: a photo is evidence of work done, so it is a
        # reason not to delete the incident silently. Matches `cleaning_photos`' own choice and
        # the `guest_access_tokens` precedent.
        #
        # Note there is deliberately NO separate single-column ForeignKey on `incident_id`: the
        # composite one already enforces referential integrity, and a second FK on the same
        # column would add an index and a constraint that can only ever agree with this one.
        ForeignKeyConstraint(
            ["tenant_id", "incident_id"],
            ["incidents.tenant_id", "incidents.id"],
            ondelete="RESTRICT",
            name="fk_incident_photos_incident_within_tenant",
        ),
        Index("ix_incident_photos_tenant_id_incident_id", "tenant_id", "incident_id"),
        # **No UniqueConstraint on (incident_id, stage)** — R1.4 requires several photos of the
        # same stage: a technician photographs two angles of one fault. Stated as a comment
        # because the absence is a requirement, not an oversight.
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: The uploader, from the verified token. A plain FK to `users.id` with no tenant
    #: qualification, exactly like `cleaning_photos.uploaded_by`; the precondition that it names
    #: a user of this tenant is the caller's, and is documented on `IncidentPhotoRepository.add`.
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    stage: Mapped[IncidentPhotoStage] = mapped_column(
        Enum(IncidentPhotoStage, name="incident_photo_stage", native_enum=True)
    )
    #: Internal, and never in a response body or header (R3.3). 500 chars matches
    #: `cleaning_photos.storage_key`; the keys this system builds are ~110.
    storage_key: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncidentMessageModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """One staff-to-manager message on an incident's thread (`staff-messaging` design D1).

    The mirror of `app.cleaning.infrastructure.models.CleaningTaskMessageModel` — see that
    class for the reasoning behind `TenantScopedMixin`, the absence of `TimestampMixin`, the
    lack of `server_default` on `created_at`, and the plain `VARCHAR` `author_role`.
    """

    __tablename__ = "incident_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "incident_id"],
            ["incidents.tenant_id", "incidents.id"],
            ondelete="RESTRICT",
            name="fk_incident_messages_incident_within_tenant",
        ),
        Index("ix_incident_messages_tenant_id_incident_id", "tenant_id", "incident_id"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    author_role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=32))
    content: Mapped[str] = mapped_column(String(MAX_INCIDENT_MESSAGE_LENGTH))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
