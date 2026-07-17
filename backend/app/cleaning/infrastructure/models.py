import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CleaningTaskModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "cleaning_tasks"
    __table_args__ = (
        Index("ix_cleaning_tasks_property_id_status", "property_id", "status"),
        Index("ix_cleaning_tasks_assigned_cleaner_id_status", "assigned_cleaner_id", "status"),
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
