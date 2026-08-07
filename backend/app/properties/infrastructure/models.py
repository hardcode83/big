import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.models import pms_provider_enum
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)

property_operational_state_enum = Enum(
    PropertyOperationalState, name="property_operational_state", native_enum=True
)


class PropertyModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "internal_code", name="uq_properties_tenant_id_internal_code"),
        Index("ix_properties_tenant_id_current_operational_state", "tenant_id", "current_operational_state"),
        Index("ix_properties_tenant_id_pms_external_id", "tenant_id", "pms_external_id"),
        # Uniqueness of `pms_external_id` is scoped PER PROVIDER, not per tenant. It exists
        # because `POST`/`PATCH /api/v1/properties` can otherwise create the shared id that
        # `specs/reservations.md` requires the sync to reject, and an application-level
        # pre-check would lose the race between two concurrent writes.
        #
        # **Why per provider and not per tenant** (`properties-crud` design D5, corrected
        # during implementation): external ids are unique only WITHIN a provider. A tenant
        # mid-migration legitimately has one property on Beds24 and another on Channex that
        # happen to share an id — the scenario ADR 0006 decision 7 exists for, pinned by
        # `tests/integrations/test_sync.py::test_a_reservation_cannot_attach_to_a_property_of_another_provider`.
        # A tenant-wide unique index forbids that state, and the first version of this index
        # did exactly that and broke three tests.
        #
        # **Why `COALESCE` and not just the column in the key**: `pms_provider` is nullable and
        # NULL means "the bootstrap default", which `pms_factory.DEFAULT_PROVIDER` defines as
        # `MOCK`. Postgres treats NULLs as DISTINCT inside an index key, so a plain
        # `(tenant_id, pms_provider, pms_external_id)` would still let two provider-less
        # properties claim one id — precisely the ambiguity this index exists to prevent, left
        # open by the obvious fix. Folding NULL to `MOCK` closes it AND is what the values mean:
        # a NULL-provider property and an explicitly-MOCK one are served by the same adapter, so
        # they are the same group and sharing an id between them *is* the ambiguity.
        #
        # The literal is the enum member rather than the string so a rename travels; the coupling
        # to `DEFAULT_PROVIDER` living in another module is guarded by
        # `tests/properties/test_models.py`, which fails if the default stops being `MOCK`.
        # `CAST(... AS TEXT)` was tried first and Postgres rejects it: an enum-to-text cast is
        # STABLE, not IMMUTABLE, because enum labels can be renamed, and index expressions must
        # be immutable.
        #
        # Partial because most properties carry no external id at all, and rows the invariant
        # says nothing about do not belong in the index.
        Index(
            "uq_properties_tenant_id_pms_external_id",
            "tenant_id",
            func.coalesce(column("pms_provider"), text(f"'{PMSProvider.MOCK.value}'")),
            "pms_external_id",
            unique=True,
            postgresql_where=text("pms_external_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    internal_code: Mapped[str] = mapped_column(String(50))
    pms_external_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # Which PMS this property talks to (ADR 0006 decision 7). NULL means "the bootstrap
    # default", i.e. the mock — so every existing row keeps working with no data migration and
    # the suite's behaviour still depends on no configuration.
    #
    # The credentials are NOT here: they live in `pms_credentials`, because the real credential
    # of every provider evaluated is account-scoped and columns here would duplicate it once per
    # property. The enum type object is imported rather than redeclared so Postgres gets one
    # `pms_provider` type instead of two.
    pms_provider: Mapped[PMSProvider | None] = mapped_column(
        pms_provider_enum, nullable=True, default=None
    )
    address_line1: Mapped[str | None] = mapped_column(String(200), default=None)
    address_line2: Mapped[str | None] = mapped_column(String(200), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    province: Mapped[str | None] = mapped_column(String(100), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(20), default=None)
    country: Mapped[str] = mapped_column(String(2), default="ES", server_default="ES")
    timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Madrid", server_default="Europe/Madrid"
    )
    max_guests: Mapped[int] = mapped_column(default=2, server_default="2")
    bedrooms: Mapped[int] = mapped_column(default=1, server_default="1")
    bathrooms: Mapped[int] = mapped_column(default=1, server_default="1")
    current_operational_state: Mapped[PropertyOperationalState] = mapped_column(
        property_operational_state_enum,
        default=PropertyOperationalState.VACANT_READY,
        server_default=PropertyOperationalState.VACANT_READY.value,
    )
    default_check_in_time: Mapped[time] = mapped_column(
        Time, default=time(15, 0), server_default="15:00:00"
    )
    default_check_out_time: Mapped[time] = mapped_column(
        Time, default=time(11, 0), server_default="11:00:00"
    )
    wifi_name: Mapped[str | None] = mapped_column(String(200), default=None)
    wifi_password_encrypted: Mapped[str | None] = mapped_column(default=None)
    access_notes: Mapped[str | None] = mapped_column(default=None)
    cleaning_notes: Mapped[str | None] = mapped_column(default=None)
    emergency_notes: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(PropertyStatus, name="property_status", native_enum=True),
        default=PropertyStatus.ACTIVE,
        server_default=PropertyStatus.ACTIVE.value,
    )


class PropertyStateTransitionModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "property_state_transitions"
    __table_args__ = (
        Index(
            "ix_property_state_transitions_property_id_created_at",
            "property_id",
            text("created_at DESC"),
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    to_state: Mapped[PropertyOperationalState] = mapped_column(property_operational_state_enum)
    triggered_by: Mapped[StateTransitionTriggeredBy] = mapped_column(
        Enum(StateTransitionTriggeredBy, name="state_transition_triggered_by", native_enum=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    from_state: Mapped[PropertyOperationalState | None] = mapped_column(
        property_operational_state_enum, default=None
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reason: Mapped[str | None] = mapped_column(String(500), default=None)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
