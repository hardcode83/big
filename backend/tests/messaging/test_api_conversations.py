"""The seven endpoints over HTTP (R7.1, R7.3, R7.4, R7.6; design D17, D18).

Through the real app, not the use cases: what these add over `test_use_cases.py` is the half
that only exists at this layer — `require(...)`, the PRD §23 error envelope, the response
schema's field list, the pagination bounds, and the `sender_type` contract of D18.
"""

import uuid

import pytest
from sqlalchemy import select

from app.messaging.domain.enums import (
    ConversationEscalationStatus,
    ConversationStatus,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.entities import MAX_MESSAGE_CONTENT_LENGTH
from app.messaging.infrastructure.models import MessageModel
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.messaging.conftest import (  # noqa: F401
    api,
    auth_header,
    seed_conversation,
    seed_message,
    seed_property,
    seed_tenant,
    world,
)

pytestmark = pytest.mark.asyncio

CONVERSATIONS = "/api/v1/conversations"


async def open_conversation(api, world, **overrides) -> str:
    payload = {
        "property_id": str(world.property.id),
        "channel": "MANUAL",
    }
    payload.update(overrides)
    response = await api.post(
        CONVERSATIONS, json=payload, headers=auth_header(api, world.manager)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- POST /conversations (R7.1, D19) -----------------------------------------------------


async def test_opening_a_conversation_returns_its_shape(api, world) -> None:
    response = await api.post(
        CONVERSATIONS,
        json={"property_id": str(world.property.id), "channel": "WHATSAPP"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["property_id"] == str(world.property.id)
    assert body["status"] == "OPEN"
    assert body["escalation_status"] == "NONE"
    assert body["ai_enabled"] is True
    assert body["last_message_at"] is None


async def test_a_conversation_without_a_property_is_refused(api, world) -> None:
    """D19 at this layer: the field is required by the schema, so it is a 422 before any use
    case runs."""
    response = await api.post(
        CONVERSATIONS,
        json={"channel": "MANUAL"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_a_property_of_another_tenant_is_refused(api, world, db_session) -> None:
    """The foreign keys of `conversations` are global, so without this a conversation of one
    tenant could be anchored to another's property for ever."""
    other = await seed_tenant(db_session, "TenantB")
    stranger = await seed_property(db_session, other, "PAJARITOS8")

    response = await api.post(
        CONVERSATIONS,
        json={"property_id": str(stranger.id), "channel": "MANUAL"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_an_unsupported_language_is_refused(api, world) -> None:
    response = await api.post(
        CONVERSATIONS,
        json={"property_id": str(world.property.id), "channel": "MANUAL", "language": "fr"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_an_unknown_field_in_the_body_is_refused(api, world) -> None:
    """`extra="forbid"` is what makes sending `ai_generated` a 422 rather than a silently
    ignored key (R7.2's spirit at the schema layer)."""
    response = await api.post(
        CONVERSATIONS,
        json={
            "property_id": str(world.property.id),
            "channel": "MANUAL",
            "ai_enabled": False,
        },
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


# --- GET /conversations (R7.3) -----------------------------------------------------------


async def test_the_inbox_is_paginated_and_shaped(api, world, db_session) -> None:
    for _ in range(3):
        await seed_conversation(db_session, world.tenant, world.property)

    response = await api.get(
        CONVERSATIONS,
        params={"page": 1, "per_page": 2},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 2
    assert len(body["items"]) == 2


async def test_the_inbox_filters_by_status_and_escalation(api, world, db_session) -> None:
    wanted = await seed_conversation(
        db_session,
        world.tenant,
        world.property,
        status=ConversationStatus.ESCALATED,
        escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
    )
    await seed_conversation(db_session, world.tenant, world.property)

    response = await api.get(
        CONVERSATIONS,
        params={"status": "ESCALATED", "escalation_status": "PENDING_HUMAN"},
        headers=auth_header(api, world.manager),
    )

    assert [item["id"] for item in response.json()["items"]] == [str(wanted.id)]


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"per_page": 0}, {"per_page": 101}, {"page": 999_999_999}],
)
async def test_the_pagination_bounds_are_declared_on_the_route(api, world, params) -> None:
    """`page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET and a
    20-digit page number overflows int8 — a driver error instead of a 422."""
    response = await api.get(
        CONVERSATIONS, params=params, headers=auth_header(api, world.manager)
    )

    assert response.status_code == 422


# --- GET /conversations/{id} (R1.5) ------------------------------------------------------


async def test_reading_an_unknown_conversation_is_a_404_envelope(api, world) -> None:
    response = await api.get(
        f"{CONVERSATIONS}/{uuid.uuid4()}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_another_tenants_conversation_is_the_same_404(api, world, db_session) -> None:
    """R1.5 at the HTTP layer: the body must not tell the two apart either."""
    other = await seed_tenant(db_session, "TenantB")
    stranger_property = await seed_property(db_session, other, "PAJARITOS8")
    stranger = await seed_conversation(db_session, other, stranger_property)

    unknown = await api.get(
        f"{CONVERSATIONS}/{uuid.uuid4()}", headers=auth_header(api, world.manager)
    )
    foreign = await api.get(
        f"{CONVERSATIONS}/{stranger.id}", headers=auth_header(api, world.manager)
    )

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json()


# --- POST /messages, the two behaviours of D18 -------------------------------------------


async def test_a_guest_message_runs_the_whole_pipeline(api, world, db_session) -> None:
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "El wifi no funciona", "sender_type": "GUEST"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sender_type"] == "GUEST"
    assert body["intent"] == MessageIntent.WIFI.value
    assert body["language"] == "es"

    rows = await db_session.execute(
        select(MessageModel).where(MessageModel.conversation_id == uuid.UUID(conversation_id))
    )
    stored = list(rows.scalars())
    assert {row.sender_type for row in stored} == {
        MessageSenderType.GUEST,
        MessageSenderType.AI,
    }

    events = await db_session.execute(select(TimelineEventModel.event_type))
    types = set(events.scalars())
    assert TimelineEventType.GUEST_MESSAGE_RECEIVED in types
    assert TimelineEventType.AI_RESPONSE_SENT in types


async def test_a_reply_omits_the_sender_type_and_is_attributed_to_the_role(
    api, world, db_session
) -> None:
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "Lo miramos ahora"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sender_type"] == "MANAGER"
    assert body["sender_user_id"] == str(world.manager.id)
    assert body["ai_generated"] is False
    assert body["intent"] is None


@pytest.mark.parametrize("sender_type", ["AI", "SYSTEM", "MANAGER", "OWNER", "guest"])
async def test_a_client_cannot_declare_any_other_sender_type(
    api, world, sender_type
) -> None:
    """**D18's whole point.** `Literal["GUEST"]` is what turns this into a 422 at the edge
    rather than a check somebody has to remember inside: a client must not be able to say that
    a message was written by the AI."""
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "hola", "sender_type": sender_type},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field", ["ai_generated", "confidence_score", "intent", "metadata", "language"]
)
async def test_the_pipeline_owned_fields_are_not_inputs(api, world, field) -> None:
    """D18: "`ai_generated`, `confidence_score`, `intent` y `metadata` **no son campos de
    entrada** en ningún caso: los escribe el pipeline"."""
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "hola", field: "x"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_a_body_over_the_ceiling_is_refused(api, world) -> None:
    """R7.6 and D21: the schema rejects it before any use case runs. The entity is the ceiling
    for a caller with no HTTP in front of it — two checks on purpose."""
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "a" * (MAX_MESSAGE_CONTENT_LENGTH + 1)},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_an_empty_body_is_refused(api, world) -> None:
    conversation_id = await open_conversation(api, world)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": ""},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_an_ota_channel_answers_422_rather_than_pretending_to_send(
    api, world
) -> None:
    """R6.3 end to end: a conversation on `BOOKING_MSG` is accepted and is mute by design.
    `docs/messaging-ai.md` says so, so an operator does not read it as a fault."""
    conversation_id = await open_conversation(api, world, channel="BOOKING_MSG")

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "El wifi no funciona", "sender_type": "GUEST"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- GET /messages (R7.4) ----------------------------------------------------------------


async def test_the_thread_is_ascending_and_paginated(api, world, db_session) -> None:
    conversation_id = await open_conversation(api, world)
    for index in range(3):
        await api.post(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            json={"content": f"mensaje {index}"},
            headers=auth_header(api, world.manager),
        )

    response = await api.get(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        params={"page": 1, "per_page": 2},
        headers=auth_header(api, world.manager),
    )

    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    created = [item["created_at"] for item in body["items"]]
    assert created == sorted(created)


async def test_the_thread_of_an_unknown_conversation_is_a_404_not_an_empty_page(
    api, world
) -> None:
    response = await api.get(
        f"{CONVERSATIONS}/{uuid.uuid4()}/messages", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404


# --- escalate / resolve (R7.1) -----------------------------------------------------------


async def test_escalating_and_resolving_move_both_axes(api, world, db_session) -> None:
    conversation_id = await open_conversation(api, world)

    escalated = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/escalate",
        headers=auth_header(api, world.manager),
    )
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "ESCALATED"
    assert escalated.json()["escalation_status"] == "PENDING_HUMAN"

    resolved = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/resolve",
        headers=auth_header(api, world.manager),
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["escalation_status"] == "RESOLVED"


async def test_escalating_twice_is_a_conflict(api, world) -> None:
    conversation_id = await open_conversation(api, world)
    await api.post(
        f"{CONVERSATIONS}/{conversation_id}/escalate",
        headers=auth_header(api, world.manager),
    )

    response = await api.post(
        f"{CONVERSATIONS}/{conversation_id}/escalate",
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_resolving_an_unknown_conversation_is_a_404(api, world) -> None:
    response = await api.post(
        f"{CONVERSATIONS}/{uuid.uuid4()}/resolve", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404


# --- What the payload must never carry ---------------------------------------------------


async def test_the_message_payload_carries_only_the_closed_metadata_keys(
    api, world
) -> None:
    """R3.5 on the serialised payload, not on the entity — the layer a client actually sees."""
    conversation_id = await open_conversation(api, world)
    await api.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"content": "El wifi no funciona", "sender_type": "GUEST"},
        headers=auth_header(api, world.manager),
    )

    response = await api.get(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        headers=auth_header(api, world.manager),
    )

    closed = {
        "escalation_reason",
        "template_key",
        "template_version",
        "delivery_status",
        "delivery_error_code",
        "source_message_id",
    }
    for item in response.json()["items"]:
        if item["metadata"] is not None:
            assert set(item["metadata"]) <= closed


async def test_the_conversation_payload_has_exactly_the_declared_fields(
    api, world
) -> None:
    """Enumerated rather than dumped from the entity: a `from_attributes` dump would publish
    whatever `Conversation` grows next, which is how a projection stops being one."""
    conversation_id = await open_conversation(api, world)

    response = await api.get(
        f"{CONVERSATIONS}/{conversation_id}", headers=auth_header(api, world.manager)
    )

    assert set(response.json()) == {
        "id",
        "property_id",
        "reservation_id",
        "guest_id",
        "channel",
        "status",
        "escalation_status",
        "language",
        "ai_enabled",
        "last_message_at",
        "created_at",
        "updated_at",
    }
    assert "tenant_id" not in response.json()
