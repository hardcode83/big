"""Request/response DTOs for the seven conversation endpoints (PRD §16, §23; R7).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`.** The effective tenant comes only from the verified
  token.
* **`sender_type` is not a field a client may set to whatever it likes** (D18). It is optional
  with **one admitted value, `GUEST`**, meaning "I am transcribing what the guest said"; any
  other value — `AI`, `SYSTEM`, or an explicit `MANAGER` — is a `422`. A client cannot declare
  that a message was written by the AI. Omitting it means "this is my own reply", and the
  `sender_type` is then derived from the caller's role inside the use case.
* **`ai_generated`, `confidence_score`, `intent` and `metadata` are not input fields at all.**
  The pipeline writes them; `extra="forbid"` is what makes sending one a `422` rather than a
  silently ignored key.

`content` carries `max_length` here **as well as** in `Message.__post_init__`, on purpose
(D21): this is where an over-long body is refused before a use case runs, and the entity is
the ceiling for a caller with no HTTP in front of it. Neither is "rejecting before reading the
body" — only `MaxBodySizeMiddleware` does that, and rule 14 of `steering/security.md` is
explicit about not presenting one as the other.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.messaging.domain.entities import (
    MAX_MESSAGE_CONTENT_LENGTH,
    Conversation,
    Message,
    WhatsAppPhoneNumberAssociation,
)
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

MAX_PER_PAGE = 100
#: `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET and a
#: 20-digit page number overflows int8, producing an unhandled driver error instead of a 422
#: in the PRD §23 envelope. Same bound and same reason as `maintenance` and `reservations`.
MAX_PAGE = 100_000


class ConversationResponse(BaseModel):
    """What an authenticated operator may see about one conversation.

    Fields are enumerated rather than dumped from the entity: a `from_attributes` dump would
    publish whatever `Conversation` grows next, which is how a projection stops being one.
    """

    id: uuid.UUID
    property_id: uuid.UUID | None
    reservation_id: uuid.UUID | None
    guest_id: uuid.UUID | None
    channel: ConversationChannel
    status: ConversationStatus
    escalation_status: ConversationEscalationStatus
    language: str
    ai_enabled: bool
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        return cls(
            id=conversation.id,
            property_id=conversation.property_id,
            reservation_id=conversation.reservation_id,
            guest_id=conversation.guest_id,
            channel=conversation.channel,
            status=conversation.status,
            escalation_status=conversation.escalation_status,
            language=conversation.language,
            ai_enabled=conversation.ai_enabled,
            last_message_at=conversation.last_message_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ConversationPageResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls,
        conversations: Sequence[Conversation],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> "ConversationPageResponse":
        return cls(
            items=[ConversationResponse.from_domain(row) for row in conversations],
            total=total,
            page=page,
            per_page=per_page,
        )


class MessageResponse(BaseModel):
    """One message of a thread.

    `metadata` is serialised through `MessageMetadata.to_dict()`, so what reaches a client is
    the same closed set of keys the column holds — never a dump of an entity attribute that
    could widen without anyone noticing.
    """

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: MessageSenderType
    sender_user_id: uuid.UUID | None
    content: str
    language: str | None
    ai_generated: bool
    confidence_score: Decimal | None
    intent: str | None
    metadata: dict[str, str] | None
    created_at: datetime

    @classmethod
    def from_domain(cls, message: Message) -> "MessageResponse":
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_type=message.sender_type,
            sender_user_id=message.sender_user_id,
            content=message.content,
            language=message.language,
            ai_generated=message.ai_generated,
            confidence_score=message.confidence_score,
            intent=message.intent,
            metadata=message.metadata.to_dict() if message.metadata is not None else None,
            created_at=message.created_at,
        )


class MessagePageResponse(BaseModel):
    items: list[MessageResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls, messages: Sequence[Message], *, total: int, page: int, per_page: int
    ) -> "MessagePageResponse":
        return cls(
            items=[MessageResponse.from_domain(row) for row in messages],
            total=total,
            page=page,
            per_page=per_page,
        )


class CreateConversationRequest(BaseModel):
    """`POST /conversations` (R7.1).

    `property_id` is **required**, which is where D19 lands for an HTTP caller;
    `Conversation.__post_init__` is where it lands for every other one. The column stays
    nullable, so this is a restriction of this change rather than of the schema.

    `channel` accepts `AIRBNB_MSG`/`BOOKING_MSG` because the enum has them — and a conversation
    created on one of those is **mute by design** (R6.3): every send fails with a named error
    until `beds24-messaging-adapter` implements `PMSMessagingPort`. `docs/messaging-ai.md`
    says so, so it does not read as a bug.
    """

    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID
    channel: ConversationChannel
    reservation_id: uuid.UUID | None = None
    guest_id: uuid.UUID | None = None
    language: Annotated[str, Field(min_length=2, max_length=5)] = "es"


class CreateMessageRequest(BaseModel):
    """`POST /conversations/{id}/messages` — one route, two behaviours (D18).

    With `sender_type = "GUEST"`: the caller is transcribing what the guest said, and the full
    pipeline of D11 runs. Omitted: the caller is answering, and their `sender_type` is derived
    from their role.

    **`Literal["GUEST"]` and not `MessageSenderType`**: the enum has five members and four of
    them are ours to write, so accepting the enum would let a client declare that the AI wrote
    a message. The narrow type is what turns that into a `422` at the edge rather than a check
    somebody has to remember inside.
    """

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)]
    sender_type: Literal["GUEST"] | None = None


def is_supported_language(value: str) -> bool:
    """Exposed for the route, which answers `422` rather than letting the entity raise a 500."""
    return value in SUPPORTED_LANGUAGES


class AssociateWhatsAppPhoneNumberRequest(BaseModel):
    """`POST /messaging/whatsapp-phone-number` (R6.1).

    `phone_number_id` is always operator-supplied — never generated (task 6.3's own words) —
    so it is a plain required string, not a value this schema invents a shape for. Meta's own
    identifiers are digit strings of about 15 characters; `min_length=1` is the only guard
    worth encoding here, because the real validation (does it authenticate real traffic) can
    only happen against Meta itself, out of this change's scope.

    `default_property_id` is required, not optional (design D8 addendum): `ensure_whatsapp`
    has nowhere to anchor an unresolved sender's thread without it.
    """

    model_config = ConfigDict(extra="forbid")

    phone_number_id: Annotated[str, Field(min_length=1, max_length=32)]
    display_phone_number: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    default_property_id: uuid.UUID


class WhatsAppPhoneNumberResponse(BaseModel):
    """What an authenticated operator may see about their tenant's association.

    No secret to withhold (D3/D8's whole point), so unlike `WebhookEndpointMaterialResponse`
    this carries nothing that is returnable "only once" — a `GET` of the tenant's own settings
    could show this back safely, the same point design D8 makes.
    """

    id: uuid.UUID
    phone_number_id: str
    display_phone_number: str | None
    default_property_id: uuid.UUID

    @classmethod
    def from_domain(
        cls, association: WhatsAppPhoneNumberAssociation
    ) -> "WhatsAppPhoneNumberResponse":
        return cls(
            id=association.id,
            phone_number_id=association.phone_number_id,
            display_phone_number=association.display_phone_number,
            default_property_id=association.default_property_id,
        )
