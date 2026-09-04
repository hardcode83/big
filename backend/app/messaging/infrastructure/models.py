import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)


class ConversationModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_id_status", "tenant_id", "status"),
        Index("ix_conversations_reservation_id", "reservation_id"),
        # At most one `PORTAL` thread per stay (`guest-portal-messaging` R3.4, D6). Declared
        # here as well as in `2b28c6b3f82a` because the test suite builds its schema from this
        # metadata and never runs the migrations — without this copy the index would not exist
        # in the tests and the concurrency test of R3.4 would prove nothing while still passing.
        #
        # The predicate is a plain enum comparison (`text()` below is SQLAlchemy's raw-SQL
        # helper, **not** a `::text` cast). It needs no autocommit block here, because
        # `create_all` *creates* `conversation_channel` in the same transaction rather than
        # extending it, and PostgreSQL 12+ allows using the labels of an enum created in the
        # transaction that created it. Why the migration cannot do the same, and what it pays
        # instead, is written once in `2b28c6b3f82a` and not re-derived here.
        Index(
            "uq_conversations_portal_reservation",
            "tenant_id",
            "reservation_id",
            unique=True,
            postgresql_where=text("channel = 'PORTAL'"),
        ),
        # At most one `WHATSAPP` thread per guest **and property**
        # (`whatsapp-cloud-adapter` R4.5, D4) — not one per guest for life: a message about
        # property B must not surface property A's unrelated history. Declared here as well
        # as in the migration for the same reason as its `PORTAL` sibling above: the suite
        # builds its schema from this metadata and never runs the migrations, so without this
        # copy the concurrency guarantee `ensure_whatsapp` rests on would not exist under
        # test while every test still passed.
        #
        # `property_id` is nullable and a `NULL` never equals another `NULL`, so the
        # unresolved rows of R4.3 do not dedupe against each other — accepted in D4 and in
        # the design's Risks, not an oversight of this index.
        Index(
            "uq_conversations_whatsapp_guest_property",
            "tenant_id",
            "guest_id",
            "property_id",
            unique=True,
            postgresql_where=text("channel = 'WHATSAPP'"),
        ),
    )

    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), default=None
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("guests.id", ondelete="RESTRICT"), default=None
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(ConversationChannel, name="conversation_channel", native_enum=True)
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", native_enum=True),
        default=ConversationStatus.OPEN,
        server_default=ConversationStatus.OPEN.value,
    )
    language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    escalation_status: Mapped[ConversationEscalationStatus] = mapped_column(
        Enum(ConversationEscalationStatus, name="conversation_escalation_status", native_enum=True),
        default=ConversationEscalationStatus.NONE,
        server_default=ConversationEscalationStatus.NONE.value,
    )
    # Meta's `phone_number_id` for the tenant's own number, written once by
    # `ensure_whatsapp` (`whatsapp-cloud-adapter` D4 addendum). A Graph API identifier, so a
    # digit string of ~15 characters; `String(32)` leaves room without pretending it is a
    # phone number that could be dialled. `NULL` on every non-`WHATSAPP` row, which
    # `Conversation.__post_init__` refuses to read back any other way.
    business_phone_number: Mapped[str | None] = mapped_column(String(32), default=None)


class MessageModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(MessageSenderType, name="message_sender_type", native_enum=True)
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str] = mapped_column()
    language: Mapped[str | None] = mapped_column(String(5), default=None)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), default=None)
    intent: Mapped[str | None] = mapped_column(String(100), default=None)
    # Mapped as `metadata_` to avoid colliding with SQLAlchemy's reserved
    # Base.metadata attribute — the real column name stays "metadata"
    # (same pattern as TimelineEventModel, D7).
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppPhoneNumberModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """The number-to-tenant association of section 6 (`whatsapp-cloud-adapter` R6.1-R6.3, D3/D8).

    **Rewritten mid-run**: Meta admits one App/WABA for the whole platform (built in section 1
    with the global `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_APP_SECRET`), and every tenant brings its
    own `phone_number_id` under that App. So there is no secret to mint per tenant here — only
    this association, which is why the table carries no encrypted column at all, unlike
    `WebhookEndpointModel` next door.

    One row per tenant (`uq_whatsapp_phone_numbers_tenant_id`), and `TenantScopedMixin` on
    purpose: every ordinary read is scoped by `tenant_id`, so it belongs inside the global
    tenant filter of `app/core/db.py` (rule 1). `phone_number_id` is the exception —
    **globally** unique (`ix_whatsapp_phone_numbers_phone_number_id`), because it is the column
    section 7's inbound webhook resolves the tenant FROM, with no tenant in hand yet. Its
    repository read runs on an unmarked session, the same shape `WebhookEndpointModel
    .token_hash`/`find_by_token_hash` already established.

    `default_property_id` is `NOT NULL` (design D8 addendum, 2026-09-02): `Conversation
    .property_id` can never be `None` (`guest-portal-messaging` D19), so `ensure_whatsapp`
    needs somewhere to anchor a thread whose sender resolves to no stay. `ondelete="RESTRICT"`
    on purpose — a property still named as a tenant's WhatsApp default cannot be deleted out
    from under it (properties are retired via `status` and never hard-deleted anyway, per
    `properties-crud`, so this is a defensive floor rather than a live concern).
    """

    __tablename__ = "whatsapp_phone_numbers"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_whatsapp_phone_numbers_tenant_id"),
    )

    # Meta's Graph API identifier for the tenant's number: a digit string of ~15 characters,
    # same shape and same `String(32)` headroom as `ConversationModel.business_phone_number`.
    # `index=True, unique=True` (rather than a bare `unique=True`) gives a unique *index*
    # (`ix_whatsapp_phone_numbers_phone_number_id`) rather than a unique *constraint* — the
    # same reason `WebhookEndpointModel.token_hash` spells it this way: `alembic check`
    # compares the two shapes and would report drift against the migration otherwise.
    phone_number_id: Mapped[str] = mapped_column(String(32), index=True, unique=True)
    # Operator-facing only (Meta's human-readable number, e.g. "+34 612 345 678"). Never used
    # to resolve anything — R3.1/R4.1 forbid resolving a tenant from anything but
    # `phone_number_id`.
    display_phone_number: Mapped[str | None] = mapped_column(String(32), default=None)
    default_property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )


class WhatsAppInboundEventModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The queue an authenticated Meta delivery lands in (section 7, R3.3-R3.5, design D7).

    **The second table in the schema whose `tenant_id` is nullable**, and the first one since
    `webhook_events` — whose docstring is where the consequences of that choice are written
    down, because they are identical here. It deliberately does NOT use `TenantScopedMixin`,
    which hard-codes `nullable=False`; the column is declared by hand instead, keeping the
    mixin's `Uuid` type, its FK to `tenants.id` and its index.

    Why nullable: R3.3 as amended on 2026-09-02 draws a line this table has to record. A
    delivery whose signature does not verify is refused and **nothing is written**. A delivery
    that *does* verify but names a `phone_number_id` no tenant has provisioned is not an
    attack — it is an operator halfway through setting up a number — so R3.3 sends it to
    R4.3's criterion: recorded where an operator can see it, never discarded in silence. With
    no tenant resolved there is no `tenant_id` to write, and inventing one is the thing R4.1
    forbids in as many words.

    **Consequence, and it is the same one `webhook_events` carries**: `tenant_scoped_classes()`
    selects by column presence rather than by mixin, so this table IS inside the global tenant
    filter — and on a session marked with a tenant, `tenant_id = X` hides exactly the `NULL`
    rows. Both the receiving route and the dispatched worker read this table from a session
    that was never marked, which is what `require_unmarked_session` on the repository's one
    read enforces rather than trusts.

    `provider_message_id` carries the unique index that makes R3.5 a schema guarantee: Meta
    redelivers on any non-2xx, and a redelivery must not become a second message in the
    guest's thread. `index=True, unique=True` rather than a bare `UniqueConstraint`, for the
    same `alembic check` reason `whatsapp_phone_numbers.phone_number_id` is spelled that way.

    `message_text` is a cleartext sink in the sense of rule 11 of `sdd/steering/security.md`:
    it is the guest's own prose, arriving from the open internet, and the census in that file
    is the only place its contract lives — do not restate it here. It is bounded by the same
    4000-character ceiling `messages.content` meets, applied by `InboundWhatsAppMessage`
    before a row can exist — by truncation, not refusal, so a delivery this long is not the
    endless-retry the redelivery contract would otherwise turn it into.

    `processed_at` is the worker's claim, and it is `NULL` for a row nobody has run yet: the
    dispatched task flips it inside the same transaction as the work, so a Celery redelivery
    of the same task finds it set and does nothing.
    """

    __tablename__ = "whatsapp_inbound_events"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=True, index=True, default=None
    )
    # Nullable for the same reason `tenant_id` is, and always in step with it: the entity
    # refuses one without the other. `RESTRICT` matches `whatsapp_phone_numbers`, the table
    # this value is copied from.
    default_property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=True, default=None
    )
    # Meta's `value.metadata.phone_number_id`: which of the platform's numbers received the
    # message. Indexed because it is what an operator looks a stuck, unprovisioned delivery
    # up by; the resolution itself reads `whatsapp_phone_numbers`, never this column.
    phone_number_id: Mapped[str] = mapped_column(String(32), index=True)
    # Meta's `wamid.…`, which is long and opaque; 128 is headroom, not a measured bound.
    provider_message_id: Mapped[str] = mapped_column(String(128), index=True, unique=True)
    sender_phone: Mapped[str] = mapped_column(String(32))
    message_text: Mapped[str] = mapped_column(Text)
    # Meta's own timestamp, not ours: `TimestampMixin.created_at` records when we received
    # the delivery, and the two differ by however long a redelivery took. The stay window is
    # asked about the guest's instant, so both are kept.
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
