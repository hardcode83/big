"""In-memory doubles of the ports the messaging use cases depend on.

`steering/backend-architecture.md`: "`application/`: unit tests con **fakes** en memoria de
los puertos (no la DB real, no mocks de SQLAlchemy)". Fakes and not mocks, so the tests assert
on state the pipeline actually produced rather than on calls it happened to make — the one
exception being the counters below, which exist because "how many times" is the assertion for
R5.4 (one notification) and R4.7 (one commit).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import UserFilters, UserPage
from app.guests.domain.value_objects import GuestSummary
from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.enums import (
    ConversationChannel,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import ConversationNotFoundError
from app.messaging.domain.repositories import (
    ConversationFilters,
    ConversationPage,
    MessagePage,
)
from app.messaging.domain.templates import (
    RESPONSE_TEMPLATES,
    RESPONSE_VOCABULARY,
    template_key,
)
from app.messaging.domain.value_objects import (
    ChannelSendResult,
    GeneratedResponse,
    MessageClassification,
)
from app.reservations.domain.repositories import RESERVATION_MATCH_GRACE_DAYS
from app.tenants.domain.entities import TenantConfig


class FakeConversationRepository:
    def __init__(self, *conversations: Conversation) -> None:
        self.rows: dict[uuid.UUID, Conversation] = {c.id: c for c in conversations}
        self.saves = 0
        #: Recorded whole so a test can assert **which** anchors the caller passed — R1.3 says
        #: they come from the `GuestSession` and from nowhere else, and `ensure_portal` does not
        #: check them itself.
        self.ensure_portal_calls: list[dict] = []
        #: Same, for the WhatsApp twin: R4.1 forbids resolving the tenant from the body and
        #: R4.4 forbids naming a guest that was not unambiguous, so *which* anchors the use
        #: case passed is the assertion, not just the row that came back.
        self.ensure_whatsapp_calls: list[dict] = []

    async def add(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        self.rows[conversation.id] = conversation

    async def get(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        conversation = self.rows.get(conversation_id)
        if conversation is None or conversation.tenant_id != tenant_id:
            return None
        return conversation

    async def save(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        self.saves += 1
        self.rows[conversation.id] = conversation

    async def ensure_portal(
        self,
        tenant_id: uuid.UUID,
        *,
        reservation_id: uuid.UUID,
        property_id: uuid.UUID,
        guest_id: uuid.UUID | None,
        language: str,
        now,
    ) -> Conversation:
        """The in-memory twin of `INSERT … ON CONFLICT DO NOTHING` + `SELECT`.

        Idempotent like the real one, and — the half worth copying — it does **not** overwrite
        the language of an existing row, because that is what R3.3 turns on and what a
        `DO UPDATE` would silently change. The race itself is not modelled here: the real
        adapter's concurrency contract is proved against Postgres in `test_repositories.py`,
        which is the only place it can be.
        """
        self.ensure_portal_calls.append(
            {
                "tenant_id": tenant_id,
                "reservation_id": reservation_id,
                "property_id": property_id,
                "guest_id": guest_id,
                "language": language,
            }
        )
        existing = await self.find_portal(tenant_id, reservation_id)
        if existing is not None:
            return existing
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel=ConversationChannel.PORTAL,
            created_at=now,
            updated_at=now,
            property_id=property_id,
            reservation_id=reservation_id,
            guest_id=guest_id,
            language=language,
        )
        self.rows[conversation.id] = conversation
        return conversation

    async def ensure_whatsapp(
        self,
        tenant_id: uuid.UUID,
        *,
        guest_id: uuid.UUID | None,
        property_id: uuid.UUID | None,
        reservation_id: uuid.UUID | None,
        language: str,
        business_phone_number: str,
        now,
    ) -> Conversation:
        """The in-memory twin of the `(tenant_id, guest_id, property_id) WHERE channel =
        'WHATSAPP'` partial unique index (`whatsapp-cloud-adapter` R4.5, D4).

        Two halves are copied because the use case's behaviour turns on them: an existing row
        is returned **without** its `language` or `business_phone_number` being overwritten
        (`DO NOTHING`, not `DO UPDATE`), and **a `NULL` `guest_id` never matches another
        `NULL`** — so a sender nobody recognised opens a row per message, which is the
        accepted limitation D4 records and which a `==` over two `None`s would silently fix
        here while production kept doing the opposite.

        The race itself is not modelled: the concurrency contract is proved against Postgres
        in `test_repositories.py`, which is the only place it can be.
        """
        self.ensure_whatsapp_calls.append(
            {
                "tenant_id": tenant_id,
                "guest_id": guest_id,
                "property_id": property_id,
                "reservation_id": reservation_id,
                "language": language,
                "business_phone_number": business_phone_number,
            }
        )
        if guest_id is not None:
            for row in self.rows.values():
                if (
                    row.tenant_id == tenant_id
                    and row.guest_id == guest_id
                    and row.property_id == property_id
                    and row.channel is ConversationChannel.WHATSAPP
                ):
                    return row
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel=ConversationChannel.WHATSAPP,
            created_at=now,
            updated_at=now,
            property_id=property_id,
            reservation_id=reservation_id,
            guest_id=guest_id,
            language=language,
            business_phone_number=business_phone_number,
        )
        self.rows[conversation.id] = conversation
        return conversation

    async def find_portal(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Conversation | None:
        for row in self.rows.values():
            if (
                row.tenant_id == tenant_id
                and row.reservation_id == reservation_id
                and row.channel is ConversationChannel.PORTAL
            ):
                return row
        return None

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: ConversationFilters,
        *,
        page: int,
        per_page: int,
    ) -> ConversationPage:
        items = tuple(
            row
            for row in self.rows.values()
            if row.tenant_id == tenant_id
            and (filters.status is None or row.status is filters.status)
            and (
                filters.escalation_status is None
                or row.escalation_status is filters.escalation_status
            )
            and (filters.property_id is None or row.property_id == filters.property_id)
        )
        start = (page - 1) * per_page
        return ConversationPage(items=items[start : start + per_page], total=len(items))


class FakeMessageRepository:
    def __init__(self) -> None:
        self.rows: list[Message] = []
        self.known_conversations: set[uuid.UUID] = set()

    async def add(self, tenant_id: uuid.UUID, message: Message) -> None:
        if message.conversation_id not in self.known_conversations:
            raise ConversationNotFoundError()
        self.rows.append(message)

    async def list_for_conversation(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        page: int,
        per_page: int,
    ) -> MessagePage:
        items = tuple(row for row in self.rows if row.conversation_id == conversation_id)
        start = (page - 1) * per_page
        return MessagePage(items=items[start : start + per_page], total=len(items))

    async def count_guest_messages(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> int:
        return sum(
            1
            for row in self.rows
            if row.conversation_id == conversation_id
            and row.sender_type is MessageSenderType.GUEST
        )

    async def count_unresolved_guest_messages_with_intent(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID, intent: MessageIntent
    ) -> int:
        return sum(
            1
            for row in self.rows
            if row.conversation_id == conversation_id
            and row.sender_type is MessageSenderType.GUEST
            and row.intent == intent.value
        )

    async def last_guest_message_at(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> datetime | None:
        """`whatsapp-cloud-adapter` R2.4, D2 — the most recent guest message's `created_at`,
        `None` if the guest never wrote. Same filter as `count_guest_messages` above; `max`
        over an in-memory list rather than a query."""
        candidates = [
            row.created_at
            for row in self.rows
            if row.conversation_id == conversation_id
            and row.sender_type is MessageSenderType.GUEST
        ]
        return max(candidates) if candidates else None

    def by_sender(self, sender_type: MessageSenderType) -> list[Message]:
        return [row for row in self.rows if row.sender_type is sender_type]


@dataclass
class StubAIAdapter:
    """An `AIAdapter` whose verdict the test chooses.

    The real `MockAIAdapter` is exercised in `test_ai_adapter.py`; here the point is to drive
    the pipeline through each branch, and deriving the branch from keyword matching would make
    every test in `test_use_cases.py` depend on the keyword table.
    """

    intent: MessageIntent = MessageIntent.WIFI
    confidence: Decimal = Decimal("0.80")
    generated_content: str | None = None
    classify_calls: int = 0
    generate_calls: list[MessageIntent] = field(default_factory=list)

    async def classify_message(self, *, content: str, language: str, context) -> MessageClassification:
        self.classify_calls += 1
        return MessageClassification(intent=self.intent, confidence=self.confidence)

    async def generate_response(self, *, intent: MessageIntent, language: str, context) -> GeneratedResponse:
        self.generate_calls.append(intent)
        content = self.generated_content or RESPONSE_TEMPLATES[(intent, language)]
        return GeneratedResponse(
            content=content,
            language=language,
            template_key=template_key(intent, language),
            vocabulary=RESPONSE_VOCABULARY | {content},
        )


@dataclass
class FakeOutboundAdapter:
    """An `OutboundMessagePort` whose outcome the test chooses (R6.5)."""

    result: ChannelSendResult = field(default_factory=ChannelSendResult.ok)
    sends: list[dict] = field(default_factory=list)

    async def send(
        self,
        *,
        channel,
        conversation_id,
        recipient_contact,
        content,
        language,
        tenant_id,
        last_inbound_at=None,
        template_id=None,
        phone_number_id=None,
    ) -> ChannelSendResult:
        self.sends.append(
            {
                "channel": channel,
                "conversation_id": conversation_id,
                "recipient_contact": recipient_contact,
                "content": content,
                "language": language,
                "tenant_id": tenant_id,
                "last_inbound_at": last_inbound_at,
                "template_id": template_id,
                "phone_number_id": phone_number_id,
            }
        )
        return self.result


@dataclass
class FakeIncidentReportingPort:
    reports: list[dict] = field(default_factory=list)

    async def report(
        self,
        *,
        tenant_id,
        property_id,
        reservation_id,
        title,
        description,
        actor,
        now,
    ) -> uuid.UUID:
        incident_id = uuid.uuid4()
        self.reports.append(
            {
                "id": incident_id,
                "tenant_id": tenant_id,
                "property_id": property_id,
                "reservation_id": reservation_id,
                "title": title,
                "description": description,
                # Recorded whole (`guest-portal-messaging` R4.1, D8), so a test can assert
                # which of the two actors the pipeline handed down without this fake having
                # an opinion about which one is legitimate.
                "actor": actor,
            }
        )
        return incident_id


class FakeTimelineRepository:
    def __init__(self) -> None:
        self.events: list = []

    async def add(self, tenant_id: uuid.UUID, event) -> None:
        self.events.append(event)

    def of_type(self, event_type) -> list:
        return [event for event in self.events if event.event_type is event_type]


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.rows: list = []

    async def add(self, tenant_id: uuid.UUID, notification) -> None:
        self.rows.append(notification)


class FakeUserRepository:
    def __init__(self, *users: User) -> None:
        self.users = list(users)

    async def list(
        self, tenant_id: uuid.UUID, filters: UserFilters, *, page: int, per_page: int
    ) -> UserPage:
        items = tuple(
            user
            for user in self.users
            if user.tenant_id == tenant_id
            and (filters.role is None or user.role is filters.role)
            and (filters.status is None or user.status is filters.status)
        )
        return UserPage(items=items, total=len(items))


class FakeGuestRepository:
    def __init__(self, *guests: GuestSummary, tenants: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        self.rows = {guest.id: guest for guest in guests}
        #: Which tenant each guest belongs to, for the isolation test. `GuestSummary` carries
        #: no `tenant_id` (it is a projection of what a reservation may know about its guest),
        #: so the real repository's `WHERE tenant_id = :tenant_id` has to be modelled here
        #: rather than read off the row. Guests absent from this map belong to every tenant,
        #: which keeps every existing test that never passes it working unchanged.
        self.tenants = tenants or {}

    def _visible(self, tenant_id: uuid.UUID, guest: GuestSummary) -> bool:
        owner = self.tenants.get(guest.id)
        return owner is None or owner == tenant_id

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        guest = self.rows.get(guest_id)
        if guest is None or not self._visible(tenant_id, guest):
            return None
        return guest

    async def find_by_phone(self, tenant_id: uuid.UUID, phone: str) -> list[GuestSummary]:
        """Every guest of this tenant with that phone — plural, and unordered (R4.2, R4.4).

        A blank value matches nothing, the guard the real adapter states, and for the same
        reason: without it every guest stored with no phone would collide on `""`.
        """
        if not phone.strip():
            return []
        return [
            guest
            for guest in self.rows.values()
            if guest.phone == phone and self._visible(tenant_id, guest)
        ]


@dataclass
class FakeTenantConfigRepository:
    threshold: Decimal = Decimal("0.75")
    # `notification-channel-routing` — pinned off so the resolver returns `{IN_APP}` only
    # and this suite's single-row assertions stay valid. A test that wants both flags on
    # passes them explicitly.
    notification_email_enabled: bool = False
    notification_whatsapp_enabled: bool = False

    async def get_or_create(self, tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
        return TenantConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            ai_confidence_threshold=self.threshold,
            notification_email_enabled=self.notification_email_enabled,
            notification_whatsapp_enabled=self.notification_whatsapp_enabled,
        )


class FakePropertyRepository:
    def __init__(self, *properties) -> None:
        self.rows = {prop.id: prop for prop in properties}

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID):
        return self.rows.get(property_id)


class FakeReservationRepository:
    def __init__(self, *reservations) -> None:
        self.rows = {reservation.id: reservation for reservation in reservations}

    async def get(self, tenant_id: uuid.UUID, reservation_id: uuid.UUID):
        return self.rows.get(reservation_id)

    async def find_active_for_guest(self, tenant_id: uuid.UUID, guest_id: uuid.UUID, *, on_date):
        """The stay window widened by `RESERVATION_MATCH_GRACE_DAYS` on each side (D5).

        The grace days are **imported, not restated**: the whole point of the constant is that
        a later change can retune it in one place, and a fake carrying its own `2` would keep
        passing while the real query answered differently. No status filter either, matching
        the real adapter — which statuses count as "live" is the caller's policy, not this
        query's.
        """
        grace = timedelta(days=RESERVATION_MATCH_GRACE_DAYS)
        return [
            reservation
            for reservation in self.rows.values()
            if reservation.tenant_id == tenant_id
            and reservation.guest_id == guest_id
            and reservation.check_in_date - grace <= on_date <= reservation.check_out_date + grace
        ]


@dataclass
class FakeUnitOfWork:
    """Counts commits, because "one transaction" (R4.7) is a statement about how many."""

    commits: int = 0

    async def commit(self) -> None:
        self.commits += 1


def make_user(
    tenant_id: uuid.UUID,
    *,
    email: str = "manager@example.com",
    phone: str | None = None,
    role: UserRole = UserRole.PROPERTY_MANAGER,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    now = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=email,
        phone=phone,
        password_hash="x" * 60,
        name="Manager",
        role=role,
        status=status,
        created_at=now,
        updated_at=now,
    )
