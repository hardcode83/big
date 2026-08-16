"""The four forms `messages` promises to the rule-11 census (R3.2-R3.7).

Calqued on `tests/maintenance/test_free_text_sink_contract.py`. The census in
`sdd/steering/security.md` is the **only** home of the contract; this file is what makes each
row of it a fact rather than a claim, and it is deliberately written against the **persisted**
value rather than against the object that produced it.

The four forms, one section each:

* prose written by the guest — bounded by type and length, and nothing more, because there is
  nothing more to promise (excepción 4);
* the closed form of our own reply — literally a member of `RESPONSE_VOCABULARY`;
* the closed form of `messages.intent` — a member of `MessageIntent`, degrading to `UNKNOWN`;
* the structured form of `messages.metadata` — six keys, and no seventh.

A fifth section covers R3.6: none of it propagates.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.messaging.domain.entities import MAX_MESSAGE_CONTENT_LENGTH, Message
from app.messaging.domain.enums import MessageIntent, MessageSenderType
from app.messaging.domain.exceptions import MessagingValidationError
from app.messaging.domain.templates import RESPONSE_VOCABULARY
from app.messaging.domain.value_objects import MessageMetadata
from app.messaging.infrastructure.models import MessageModel
from app.audit.infrastructure.models import AuditLogModel
from app.timeline.infrastructure.models import TimelineEventModel
from tests.messaging.conftest import (  # noqa: F401
    api,
    auth_header,
    seed_property,
    seed_tenant,
    world,
)

CONVERSATIONS = "/api/v1/conversations"

#: A guest's own words carrying exactly the rule-3 values the census worries about: an
#: identity document, a phone number and a door code. Every assertion below about a value
#: *not* appearing is therefore about a real value and not about an empty string.
LEAKY = (
    "No puedo entrar. Mi DNI es 12345678Z, mi telefono es +34600123456 y el codigo "
    "que me disteis, 4471, no funciona. La caldera esta rota tambien."
)
#: What the **manager** types back, carrying its own rule-3 values. The third census row for
#: `messages.content` is the authenticated person's, and until this existed every sweep in
#: this file ran over guest-written and AI-written rows only — so the row's claim that its
#: text does not propagate was asserted rather than pinned. Found by the security panel of
#: sections 7-9, which noticed the census cited this file for something it never exercised.
HUMAN_LEAKY = "Le paso el codigo 4471 y su DNI 12345678Z queda registrado, no se preocupe."

LEAK_MARKERS = ("12345678Z", "+34600123456", "4471", "DNI", "codigo")


async def transcribe(api, world, content: str = LEAKY) -> str:
    """Open a conversation, put `content` in it as the guest said it, and answer as a person.

    **Both writers of `messages.content` that are not the AI**, in one helper, so every sweep
    below covers all three census rows rather than two of them.
    """
    opened = await api.post(
        CONVERSATIONS,
        json={"property_id": str(world.property.id), "channel": "MANUAL"},
        headers=auth_header(api, world.manager),
    )
    conversation_id = opened.json()["id"]
    sent = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": content, "sender_type": "GUEST"},
        headers=auth_header(api, world.manager),
    )
    assert sent.status_code == 201, sent.text
    replied = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": HUMAN_LEAKY},
        headers=auth_header(api, world.manager),
    )
    assert replied.status_code == 201, replied.text
    return conversation_id


# --- Form 1: the guest's prose (R3.2, excepción 4) ---------------------------------------


@pytest.mark.asyncio
async def test_the_guests_words_are_stored_verbatim(api, world, db_session) -> None:
    """The excepción-4 half. It is **not** a promise that the column is structured — that would
    be a census row that lies, which the census itself calls worse than a column uncensed."""
    await transcribe(api, world)

    rows = await db_session.execute(
        select(MessageModel.content).where(
            MessageModel.sender_type == MessageSenderType.GUEST
        )
    )
    assert list(rows.scalars()) == [LEAKY]


@pytest.mark.asyncio
async def test_a_persons_reply_is_stored_verbatim_under_its_own_row(
    api, world, db_session
) -> None:
    """The third census row for `messages.content`, which goes under excepción 3.

    Its writer is an authenticated person with `MANAGE_CONVERSATIONS`, so the value is theirs
    and not ours — and the `sender_type` comes from their role, never from the request body.
    """
    await transcribe(api, world)

    rows = await db_session.execute(
        select(MessageModel.content, MessageModel.sender_user_id).where(
            MessageModel.sender_type == MessageSenderType.MANAGER
        )
    )
    stored = rows.all()

    assert [content for content, _ in stored] == [HUMAN_LEAKY]
    assert stored[0].sender_user_id is not None


def test_the_guests_prose_is_bounded_by_type_and_length_and_nothing_else() -> None:
    """"Se acota con tipos y longitud máxima, no pretendiendo que la columna sea
    estructurada" — the requirement's own words (R3.2)."""
    with pytest.raises(MessagingValidationError):
        Message(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            sender_type=MessageSenderType.GUEST,
            content="a" * (MAX_MESSAGE_CONTENT_LENGTH + 1),
            created_at=datetime.now(UTC),
        )


# --- Form 2: our own reply is a catalogue constant (R3.3) --------------------------------


@pytest.mark.asyncio
async def test_what_we_write_is_literally_a_member_of_the_catalogue(
    api, world, db_session
) -> None:
    """**The assertion the census row points at.** Not "resembles a template", not "came from
    an adapter that declared a vocabulary" — the persisted string is a member of
    `RESPONSE_VOCABULARY`."""
    await transcribe(api, world, "El wifi no funciona")

    rows = await db_session.execute(
        select(MessageModel.content).where(MessageModel.ai_generated.is_(True))
    )
    written = list(rows.scalars())

    assert written
    for content in written:
        assert content in RESPONSE_VOCABULARY


@pytest.mark.asyncio
async def test_our_reply_never_quotes_the_guest(api, world, db_session) -> None:
    await transcribe(api, world)

    rows = await db_session.execute(
        select(MessageModel.content).where(MessageModel.ai_generated.is_(True))
    )
    for content in rows.scalars():
        for marker in LEAK_MARKERS:
            assert marker.lower() not in content.lower()


# --- Form 3: the closed form of `messages.intent` (R3.4) ---------------------------------


@pytest.mark.asyncio
async def test_every_persisted_intent_is_a_member_of_the_enum(
    api, world, db_session
) -> None:
    await transcribe(api, world)

    rows = await db_session.execute(
        select(MessageModel.intent).where(MessageModel.intent.is_not(None))
    )
    values = {member.value for member in MessageIntent}

    stored = list(rows.scalars())
    assert stored
    for intent in stored:
        assert intent in values


def test_an_unrecognised_intent_degrades_rather_than_being_stored() -> None:
    """The column is a `VARCHAR(100)` that *looks* like an enum — the appearance that got
    `webhook_events.event_type` left out of the census."""
    message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        sender_type=MessageSenderType.GUEST,
        content="hola",
        created_at=datetime.now(UTC),
        intent="mi DNI es 12345678Z",
    )

    assert message.intent == MessageIntent.UNKNOWN.value


# --- Form 4: the structured form of `messages.metadata` (R3.5) ---------------------------


@pytest.mark.asyncio
async def test_every_persisted_metadata_key_is_one_of_the_six(
    api, world, db_session
) -> None:
    await transcribe(api, world, "El wifi no funciona")

    rows = await db_session.execute(
        select(MessageModel.metadata_)
    )
    closed = set(MessageMetadata.__dataclass_fields__)

    # Filtered in Python, not with `is_not(None)`: on a JSONB column that predicate compares
    # against the JSON value `null` rather than against SQL NULL, so it lets the guest's own
    # message — which legitimately has no metadata — through as a `None` row.
    stored = [metadata for metadata in rows.scalars() if metadata is not None]
    assert stored
    for metadata in stored:
        assert set(metadata) <= closed


@pytest.mark.asyncio
async def test_no_persisted_metadata_carries_a_word_the_guest_said(
    api, world, db_session
) -> None:
    await transcribe(api, world)

    rows = await db_session.execute(select(MessageModel.metadata_))
    for metadata in rows.scalars():
        if metadata is None:
            continue
        for marker in LEAK_MARKERS:
            assert marker.lower() not in str(metadata).lower()


# --- R3.6: none of it propagates ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_timeline_never_receives_the_message(api, world, db_session) -> None:
    """R3.6 verbatim: "NEVER SHALL copiar el contenido del mensaje a `timeline_events`".

    Checked over **every** column of the table that could hold text, not only the one the
    pipeline happens to write: `timeline_events` is append-only, so a leak here could never be
    redacted afterwards.
    """
    await transcribe(api, world)

    rows = await db_session.execute(
        select(
            TimelineEventModel.title,
            TimelineEventModel.description,
            TimelineEventModel.metadata_,
        )
    )
    events = rows.all()

    assert events
    for title, description, metadata in events:
        rendered = f"{title} {description} {metadata}".lower()
        for marker in LEAK_MARKERS:
            assert marker.lower() not in rendered


@pytest.mark.asyncio
async def test_the_audit_log_never_receives_the_message(api, world, db_session) -> None:
    """R3.6's other half. The conversation carries `MAINTENANCE_ISSUE` here, so an incident is
    opened and an `AuditLog` written — which is the only audit row this flow produces, and the
    one that could carry the text if `AUDITABLE_FIELDS` allowed it."""
    await transcribe(api, world)

    rows = await db_session.execute(select(AuditLogModel.changes))
    changes = list(rows.scalars())

    assert changes, "the flow must have written an audit row for this test to mean anything"
    for change in changes:
        rendered = str(change).lower()
        for marker in LEAK_MARKERS:
            assert marker.lower() not in rendered


@pytest.mark.asyncio
async def test_the_message_reaches_exactly_the_columns_the_census_declares(
    api, world, db_session
) -> None:
    """The sweep the census's own excepción-2 paragraph describes: after a real message, look
    for the guest's words in every text and JSON column this flow writes, and confirm they
    appear **only** where a row of the table says they may — `messages.content` and, because
    the intent opened one, `incidents.description`."""
    from sqlalchemy import JSON, String, Text
    from sqlalchemy.dialects.postgresql import JSONB

    from app.core.db import Base
    from app.maintenance.infrastructure.models import IncidentModel

    await transcribe(api, world)

    #: Where the guest's words are **allowed** to be. Everything else in the schema is swept.
    declared = {("messages", "content"), ("incidents", "description")}

    #: Driven off the ORM registry rather than a hand-written list, which is the difference
    #: between "no leak in the six columns somebody thought of" and "no leak". A column added
    #: by a later change joins this sweep by existing — the security panel of sections 7-9
    #: pointed out that a literal list silently excuses whatever is not in it.
    swept = 0
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, (String, Text, JSON, JSONB)):
                continue
            if (table.name, column.name) in declared:
                continue
            rows = await db_session.execute(select(column))
            swept += 1
            for value in rows.scalars():
                if value is None:
                    continue
                rendered = str(value).lower()
                for marker in LEAK_MARKERS:
                    assert marker.lower() not in rendered, (
                        f"{table.name}.{column.name} carries {marker!r}, which the rule-11 "
                        "census does not declare"
                    )

    assert swept > 50, "the sweep must actually reach the schema, not an empty registry"

    # And the one place it may be besides `messages.content`, so the sweep above is not
    # passing for want of data.
    incident_descriptions = await db_session.execute(select(IncidentModel.description))
    assert LEAKY in list(incident_descriptions.scalars())
