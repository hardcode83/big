import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.domain.enums import UserRole
from app.cleaning.domain.entities import MAX_CLEANING_TASK_MESSAGE_LENGTH
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CleaningTaskModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "cleaning_tasks"
    __table_args__ = (
        Index("ix_cleaning_tasks_property_id_status", "property_id", "status"),
        Index("ix_cleaning_tasks_assigned_cleaner_id_status", "assigned_cleaner_id", "status"),
        # `staff-messaging` design D1: the target a composite foreign key needs. Postgres
        # requires a composite FK to reference a declared unique key, and
        # `cleaning_task_messages.(tenant_id, task_id)` references exactly this pair, the
        # same device `incidents` carries as `uq_incidents_tenant_id_id` for `incident_photos`.
        # Cannot fail on existing data: `id` is already the primary key, so `(tenant_id, id)`
        # is unique for free.
        UniqueConstraint("tenant_id", "id", name="uq_cleaning_tasks_tenant_id_id"),
        # One live cleaning per reservation (`cleaning` R2.5, design D2). `process_checkouts`
        # runs every five minutes, so a read-then-write check in the use case is a race the
        # first concurrent run wins twice; the index is what makes the invariant a property of
        # the schema.
        #
        # Partial, and both halves of the predicate matter. `reservation_id IS NOT NULL`
        # because a manual task without a booking is not constrained by anything. The status
        # list because a REJECTED task must be able to coexist with its replacement (design
        # D3) and a COMPLETED one with a later cleaning of the same booking. The list is the
        # same set as `LIVE_STATUSES` in `app/cleaning/domain/entities.py`, and
        # `tests/cleaning/test_live_task_index.py` pins the two together — they cannot be
        # derived from each other here because a partial index predicate is SQL text.
        Index(
            "uq_cleaning_tasks_live_reservation",
            "tenant_id",
            "reservation_id",
            unique=True,
            postgresql_where=text(
                "reservation_id IS NOT NULL AND status IN "
                "('CREATED', 'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS')"
            ),
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("properties.id", ondelete="RESTRICT"))
    checklist_template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cleaning_checklist_templates.id", ondelete="RESTRICT")
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    assigned_cleaner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[CleaningTaskStatus] = mapped_column(
        Enum(CleaningTaskStatus, name="cleaning_task_status", native_enum=True),
        default=CleaningTaskStatus.CREATED,
        server_default=CleaningTaskStatus.CREATED.value,
    )
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    validation_status: Mapped[CleaningValidationStatus] = mapped_column(
        Enum(CleaningValidationStatus, name="cleaning_validation_status", native_enum=True),
        default=CleaningValidationStatus.PENDING,
        server_default=CleaningValidationStatus.PENDING.value,
    )
    validated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CleaningChecklistTemplateModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "cleaning_checklist_templates"

    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    required_photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class CleaningChecklistCompletionModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "cleaning_checklist_completions"
    __table_args__ = (
        UniqueConstraint(
            "cleaning_task_id", "item_id", name="uq_cleaning_checklist_completions_cleaning_task_id_item_id"
        ),
    )

    cleaning_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cleaning_tasks.id", ondelete="RESTRICT")
    )
    item_id: Mapped[str] = mapped_column(String(100))
    completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    notes: Mapped[str | None] = mapped_column(default=None)


class CleaningPhotoModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "cleaning_photos"
    __table_args__ = (Index("ix_cleaning_photos_cleaning_task_id", "cleaning_task_id"),)

    cleaning_task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cleaning_tasks.id", ondelete="RESTRICT"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    photo_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(500))
    ai_validation_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CleaningTaskMessageModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """One staff-to-manager message on a cleaning task's thread (`staff-messaging` design D1).

    **`TenantScopedMixin`, unlike `cleaning_photos`.** The twin table gets its own
    `tenant_id`, literally the shape `IncidentPhotoModel` uses: this class enters
    `tenant_scoped_classes()` and therefore the global loader criteria of `app/core/db.py`,
    and paired with the composite foreign key below it makes "the message's tenant and its
    task's tenant agree" an invariant of the schema rather than discipline in a repository.

    **No `TimestampMixin`.** A message is immutable after insert — the port declares `add`
    and `list_for_task` and no `save` — so there is no `updated_at` to carry, the same
    reasoning `IncidentPhotoModel` records for itself. `created_at` is declared by hand and
    **without `server_default`**: a burst of messages inserted together would otherwise
    share one Postgres `now()` and collapse the chronological order the thread is read in.
    """

    __tablename__ = "cleaning_task_messages"
    __table_args__ = (
        # D1's invariant: the message's tenant and its task's tenant cannot diverge, because
        # no pair of values satisfies this constraint and disagrees. `ON DELETE RESTRICT`,
        # not CASCADE: a message is part of the task's record, not disposable with it.
        #
        # No separate single-column ForeignKey on `task_id`: the composite one already
        # enforces referential integrity.
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["cleaning_tasks.tenant_id", "cleaning_tasks.id"],
            ondelete="RESTRICT",
            name="fk_cleaning_task_messages_task_within_tenant",
        ),
        Index("ix_cleaning_task_messages_tenant_id_task_id", "tenant_id", "task_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: The author, from the verified token. A plain FK to `users.id` with no tenant
    #: qualification, exactly like `cleaning_photos.uploaded_by`; the precondition that it
    #: names a user of this tenant is the caller's.
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    #: The persisted `UserRole` of the author, frozen at write time (design D2). A plain
    #: `VARCHAR`, not the native `user_role` Postgres type: reusing that type across a second
    #: table's migration is complexity this design does not ask for. `native_enum=False`
    #: gives the column while keeping the Python-side `UserRole` round-trip.
    author_role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=32))
    content: Mapped[str] = mapped_column(String(MAX_CLEANING_TASK_MESSAGE_LENGTH))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
