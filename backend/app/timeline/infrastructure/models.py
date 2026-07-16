import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, UUIDPrimaryKeyMixin
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity


class TimelineEventModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "timeline_events"
    __table_args__ = (
        Index(
            "ix_timeline_events_property_id_created_at",
            "property_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_timeline_events_tenant_id_event_type_created_at",
            "tenant_id",
            "event_type",
            text("created_at DESC"),
        ),
        Index(
            "ix_timeline_events_reservation_id_created_at",
            "reservation_id",
            text("created_at DESC"),
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_type: Mapped[TimelineActorType] = mapped_column(
        Enum(TimelineActorType, name="timeline_actor_type", native_enum=True)
    )
    event_type: Mapped[TimelineEventType] = mapped_column(
        Enum(TimelineEventType, name="timeline_event_type", native_enum=True)
    )
    severity: Mapped[TimelineSeverity] = mapped_column(
        Enum(TimelineSeverity, name="timeline_severity", native_enum=True),
        default=TimelineSeverity.INFO,
        server_default=TimelineSeverity.INFO.value,
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(default=None)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
