"""In-memory doubles of the ports the messaging use cases depend on.

`steering/backend-architecture.md`: "`application/`: unit tests con **fakes** en memoria de
los puertos (no la DB real, no mocks de SQLAlchemy)". Fakes and not mocks, so the tests assert
on state the pipeline actually produced rather than on calls it happened to make — the one
exception being the counters below, which exist because "how many times" is the assertion for
R5.4 (one notification) and R4.7 (one commit).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import UserFilters, UserPage
from app.guests.domain.value_objects import GuestSummary
from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.enums import MessageIntent, MessageSenderType
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
from app.tenants.domain.entities import TenantConfig


class FakeConversationRepository:
    def __init__(self, *conversations: Conversation) -> None:
        self.rows: dict[uuid.UUID, Conversation] = {c.id: c for c in conversations}
        self.saves = 0

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
        self, *, channel, conversation_id, recipient_contact, content, language
    ) -> ChannelSendResult:
        self.sends.append(
            {
                "channel": channel,
                "conversation_id": conversation_id,
                "recipient_contact": recipient_contact,
                "content": content,
                "language": language,
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
        actor_user_id,
        ip,
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
                "actor_user_id": actor_user_id,
                "ip": ip,
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
    def __init__(self, *guests: GuestSummary) -> None:
        self.rows = {guest.id: guest for guest in guests}

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        return self.rows.get(guest_id)


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
