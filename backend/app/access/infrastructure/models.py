import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AccessRecordModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "access_records"
    __table_args__ = (
        Index("ix_access_records_reservation_id", "reservation_id"),
        Index("ix_access_records_property_id_valid_from_valid_to", "property_id", "valid_from", "valid_to"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("properties.id", ondelete="RESTRICT"))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    provider: Mapped[AccessProvider] = mapped_column(
        Enum(AccessProvider, name="access_provider", native_enum=True),
        default=AccessProvider.MANUAL,
        server_default=AccessProvider.MANUAL.value,
    )
    external_id: Mapped[str | None] = mapped_column(String(200), default=None)
    status: Mapped[AccessRecordStatus] = mapped_column(
        Enum(AccessRecordStatus, name="access_record_status", native_enum=True),
        default=AccessRecordStatus.PENDING,
        server_default=AccessRecordStatus.PENDING.value,
    )
    code_masked: Mapped[str | None] = mapped_column(String(50), default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_mode: Mapped[AccessCreatedMode] = mapped_column(
        Enum(AccessCreatedMode, name="access_created_mode", native_enum=True),
        default=AccessCreatedMode.MANUAL,
        server_default=AccessCreatedMode.MANUAL.value,
    )
    notes: Mapped[str | None] = mapped_column(default=None)
