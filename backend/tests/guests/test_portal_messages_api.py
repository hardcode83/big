"""`GET`/`POST /api/v1/guest/messages/{token}` over HTTP (R1.1-R1.7, R2.1-R2.5; D2, D4, D9).

The fifth and sixth routes of the portal, and the first ones that let a stranger's free text
run the whole `messaging-ai` pipeline. So the assertions that carry the weight are about what
the `POST` refuses before writing anything, what the `GET` never says, and that both answer
the same indistinguishable `404` the other four already do.

**Their own file rather than more cases in `test_portal_api.py`**, following the precedent
`test_portal_incident_api.py` set for the fourth route: that one is already a thousand lines
about the stay, the check-in and the five rejections, and a route whose setup is a
conversation and a pipeline does not share its fixtures. `tasks.md` 7.4 named the older file
before the precedent was weighed; the split is recorded there.

The throttle is a fake, as in both sibling files: what these tests need from it is the
**order** the security panel made binding, and a fake is the only way to observe an order
rather than infer it from a counter.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import get_db_session
from app.guests.api.portal_dependencies import get_guest_portal_throttle
from app.guests.api.portal_router import _NOT_FOUND
from app.guests.domain.enums import LegalRegistrationStatus
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.main import create_app
from app.messaging.domain.entities import MAX_MESSAGE_CONTENT_LENGTH
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    MessageSenderType,
)
from app.messaging.infrastructure.models import ConversationModel, MessageModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.conftest import request_session_override
from tests.auth.conftest import tenant_a, tenant_b, utc_now  # noqa: F401

pytestmark = pytest.mark.asyncio

#: Far enough inside the window that the grace period cannot expire it mid-suite.
CHECK_OUT = datetime.now(UTC).date() + timedelta(days=3)

MESSAGE = {"content": "Hola, ¿a qué hora puedo entrar?"}


class _AllowAll:
    """Records what it was asked, in the order it was asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def probe_allowed(self, client_ip: str) -> bool:
        self.calls.append("probe")
        return True

    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return True

    async def record_failed_authorisation(self, client_ip: str) -> None:
        self.calls.append("failure")


class _RefuseRequests(_AllowAll):
    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return False


@pytest.fixture
def throttle() -> _AllowAll:
    return _AllowAll()


def _build_app(db_session, throttle):
    """The real app, with the tenant marker cleared when each request ends.

    `request_session_override` and not a bare `yield db_session`: every portal route resolves
    the token through `find_live_by_token_hash`, which must run on an **unmarked** session, and
    the suite hands every request of a test the same session. Without the reset, the second
    request of any test dies on `TenantMarkedSessionError` — a sequence production cannot
    perform, since it opens one session per request. `test_portal_api.py` documents the whole
    trade.
    """
    app = create_app()
    override = request_session_override(db_session)
    app.dependency_overrides[get_db_session] = override
    app.dependency_overrides[get_guest_portal_throttle] = lambda: throttle
    app.bound_tenants = override.bound_tenants  # type: ignore[attr-defined]
    return app


@pytest_asyncio.fixture
async def api(db_session, throttle):
    app = _build_app(db_session, throttle)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # The tenant each request bound its session to, in order (see `_build_app`).
        client.bound_tenants = app.bound_tenants  # type: ignore[attr-defined]
        yield client


async def _stay(db_session, tenant, *, name="Casa Redes", **overrides):
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=name,
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()

    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()

    values = {
        "check_in_date": CHECK_OUT - timedelta(days=2),
        "check_out_date": CHECK_OUT,
        "status": ReservationStatus.CONFIRMED,
        "legal_registration_status": LegalRegistrationStatus.PENDING_GUEST_DATA,
    }
    values.update(overrides)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        guest_id=guest.id,
        channel="DIRECT",
        nights=2,
        **values,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation, prop


async def _token(db_session, tenant, reservation) -> str:
    token = generate_guest_token()
    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            token_hash=hash_guest_token(token),
        )
    )
    await db_session.flush()
    return token


async def _conversations(db_session) -> list[ConversationModel]:
    db_session.expunge_all()
    return list((await db_session.execute(select(ConversationModel))).scalars().all())


async def _messages(db_session) -> list[MessageModel]:
    db_session.expunge_all()
    return list(
        (
            await db_session.execute(
                select(MessageModel).order_by(MessageModel.created_at, MessageModel.id)
            )
        )
        .scalars()
        .all()
    )


# --- The happy path (R1.1, R1.4, R3.3) -------------------------------------------------


async def test_the_first_message_opens_the_stays_portal_thread(
    api, db_session, tenant_a
) -> None:
    """R1.1 and R3.3 together: the row the guest writes is also what creates the thread."""
    reservation, prop = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)

    assert response.status_code == 201, response.text
    conversations = await _conversations(db_session)
    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.channel is ConversationChannel.PORTAL
    assert conversation.tenant_id == tenant_a.id
    assert conversation.property_id == prop.id
    assert conversation.reservation_id == reservation.id


async def test_the_acknowledgement_is_the_message_as_the_thread_will_show_it(
    api, db_session, tenant_a
) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    body = (await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)).json()

    stored = [m for m in await _messages(db_session) if m.sender_type is MessageSenderType.GUEST]
    assert len(stored) == 1
    assert body["id"] == str(stored[0].id)
    assert body["content"] == MESSAGE["content"]
    assert body["sender"] == "GUEST"


async def test_a_second_message_reuses_the_same_thread(api, db_session, tenant_a) -> None:
    """R3.4 over the wire: one conversation per stay, whatever the guest sends afterwards."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
    await api.post(f"/api/v1/guest/messages/{token}", json={"content": "Otra pregunta"})

    assert len(await _conversations(db_session)) == 1


async def test_the_whole_pipeline_runs_on_the_guests_message(
    api, db_session, tenant_a
) -> None:
    """R1.4: the route delegates to the pipeline rather than persisting a message itself.

    Asserted through the pipeline's *side effects* on the guest's own row and on the timeline,
    which is what distinguishes running it from storing the text: a route that merely inserted
    a `Message` would leave `language` and `intent` null and write no `GUEST_MESSAGE_RECEIVED`
    entry, while every positive assertion above stayed green. The reply is deliberately not
    what is asserted — whether one is written depends on the classification, and pinning it
    here would make this test about `MockAIAdapter`'s catalogue.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)

    written = [m for m in await _messages(db_session) if m.sender_type is MessageSenderType.GUEST]
    assert [m.language for m in written] == ["es"]
    assert written[0].intent is not None
    events = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.event_type == TimelineEventType.GUEST_MESSAGE_RECEIVED
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


# --- What the body may carry, and what it may not (R1.5, R1.6) -------------------------


@pytest.mark.parametrize(
    "field",
    [
        "sender_type",
        "tenant_id",
        "reservation_id",
        "property_id",
        "conversation_id",
        "ai_generated",
    ],
)
async def test_the_six_forbidden_fields_are_refused_and_not_dropped(
    api, db_session, tenant_a, field
) -> None:
    """R1.5 field by field.

    A `422` and not a quiet drop: a caller who sent `sender_type` and got a `201` would have
    every reason to believe it had been honoured.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/messages/{token}", json={**MESSAGE, field: "GUEST"}
    )

    assert response.status_code == 422
    assert await _messages(db_session) == []


async def test_content_above_the_product_limit_is_refused_before_anything_is_created(
    api, db_session, tenant_a
) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/messages/{token}",
        json={"content": "a" * (MAX_MESSAGE_CONTENT_LENGTH + 1)},
    )

    assert response.status_code == 422
    assert await _conversations(db_session) == []
    assert await _messages(db_session) == []


@pytest.mark.parametrize("content", ["with a \x00 null", "   "])
async def test_text_the_database_cannot_hold_is_a_422_and_never_a_500(
    api, db_session, tenant_a, content
) -> None:
    """R1.6 through `MultiLineText`.

    Without the guard a `U+0000` reaches the driver and comes back as an unhandled `500`,
    measured twice on the sibling portal routes. The whitespace-only case is the same schema
    clause from the other side: `str_strip_whitespace` plus `min_length=1`.

    The lone-surrogate half of the same class needs a raw body and lives below.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/messages/{token}", json={"content": content})

    assert response.status_code == 422
    assert await _messages(db_session) == []


async def test_a_body_carrying_a_lone_surrogate_is_refused_before_the_field_is_reached(
    api, db_session, tenant_a
) -> None:
    """A `\\uD800` escape in an ASCII body: `422` and no row, exactly as on the incident route.

    Refused by pydantic-core's `jiter` while parsing the body, before any `AfterValidator` runs
    — so the error is `json_invalid` and not the `value_error` `_storable_text` raises. That
    distinction was measured on the incident route, where the first version of the test claimed
    the opposite; the guard's own branch is pinned in its own unit tests.

    Sent as a raw body because this case cannot travel through `json=`: httpx serialises with
    `ensure_ascii=False` and dies in the client before a request exists.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/messages/{token}",
        content='{"content": "hola\\ud800"}'.encode("ascii"),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert await _messages(db_session) == []


async def test_the_rejection_does_not_echo_the_value(api, db_session, tenant_a) -> None:
    """R1.6: `_serialisable_validation_errors` publishes `loc`, `type` and `msg`, never `input`."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    secret = "correct-horse-battery-staple"

    response = await api.post(
        f"/api/v1/guest/messages/{token}",
        json={"content": secret + "a" * MAX_MESSAGE_CONTENT_LENGTH},
    )

    assert response.status_code == 422
    assert secret not in response.text


# --- The one refusal, on both routes (R1.7, D5) ----------------------------------------


async def _five_rejected_tokens(db_session, tenant) -> list[str]:
    revoked_stay, _ = await _stay(db_session, tenant)
    revoked = await _token(db_session, tenant, revoked_stay)
    (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == revoked_stay.id
            )
        )
    ).scalar_one().revoked_at = datetime.now(UTC)

    expired_stay, _ = await _stay(
        db_session, tenant, check_in_date=date(2020, 1, 1), check_out_date=date(2020, 1, 3)
    )
    expired = await _token(db_session, tenant, expired_stay)

    cancelled_stay, _ = await _stay(db_session, tenant, status=ReservationStatus.CANCELLED)
    cancelled = await _token(db_session, tenant, cancelled_stay)
    await db_session.flush()
    return [generate_guest_token(), "not-a-token", revoked, expired, cancelled]


async def test_every_rejection_of_the_write_is_the_same_404(api, db_session, tenant_a) -> None:
    """R1.7: five causes, one status **and one body**, on the route that writes."""
    answers = set()
    for token in await _five_rejected_tokens(db_session, tenant_a):
        response = await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
        answers.add((response.status_code, response.text))

    assert len(answers) == 1
    assert answers.pop() == (404, __import__("json").dumps(_NOT_FOUND, separators=(",", ":")))


async def test_every_rejection_of_the_read_is_the_same_404(api, db_session, tenant_a) -> None:
    """R1.7 on the route that reads — the same five causes, answered identically."""
    answers = set()
    for token in await _five_rejected_tokens(db_session, tenant_a):
        response = await api.get(f"/api/v1/guest/messages/{token}")
        answers.add((response.status_code, response.text))

    assert len(answers) == 1
    assert answers.pop()[0] == 404


async def test_a_rejected_write_creates_nothing(api, db_session, tenant_a) -> None:
    for token in await _five_rejected_tokens(db_session, tenant_a):
        await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)

    assert await _conversations(db_session) == []
    assert await _messages(db_session) == []


@pytest.mark.parametrize("method", ["get", "post"])
async def test_the_per_token_budget_refuses_with_429(db_session, tenant_a, method) -> None:
    """R4.3: the limit on the route, charged only to a caller that proved it holds the token."""
    throttle = _RefuseRequests()
    app = _build_app(db_session, throttle)

    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await getattr(client, method)(
            f"/api/v1/guest/messages/{token}", **({"json": MESSAGE} if method == "post" else {})
        )

    assert response.status_code == 429
    assert throttle.calls == ["probe", "request"]
    assert await _messages(db_session) == []


# --- What the thread shows, and what it never does (R2.1-R2.5) -------------------------


async def test_a_stay_that_has_not_written_reads_an_empty_thread(
    api, db_session, tenant_a
) -> None:
    """R2.5: `200` with nothing in it — never a `404`, and never a freshly minted row."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.get(f"/api/v1/guest/messages/{token}")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert await _conversations(db_session) == []


async def test_the_thread_is_oldest_first_within_the_window(api, db_session, tenant_a) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
    await api.post(f"/api/v1/guest/messages/{token}", json={"content": "Segunda"})

    items = (await api.get(f"/api/v1/guest/messages/{token}")).json()["items"]

    assert [item["created_at"] for item in items] == sorted(
        item["created_at"] for item in items
    )
    assert MESSAGE["content"] in [item["content"] for item in items]


async def test_the_message_has_the_four_fields_of_d4_and_no_others(
    api, db_session, tenant_a
) -> None:
    """R2.2 and R2.4 over the wire.

    Pinned as an exact key set rather than field by field, because the failure mode is a field
    *appearing*: a later serialiser that added `intent` or `sender_user_id` would keep every
    positive assertion green.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)

    body = (await api.get(f"/api/v1/guest/messages/{token}")).json()

    assert set(body) == {"items", "total", "page", "per_page", "state"}
    for item in body["items"]:
        assert set(item) == {"id", "sender", "content", "created_at"}


async def test_the_reply_is_attributed_to_the_accommodation_and_to_nothing_finer(
    api, db_session, tenant_a
) -> None:
    """R2.2: `AI` and `MANAGER` collapse to one value, so the payload cannot tell them apart."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)

    items = (await api.get(f"/api/v1/guest/messages/{token}")).json()["items"]

    assert {item["sender"] for item in items} <= {"GUEST", "PROPERTY"}


async def _set_escalation(db_session, escalation: ConversationEscalationStatus) -> None:
    """Move the only conversation to `escalation`, and forget what the session had cached.

    The `expunge_all` is not decoration: the route reads through the same session, so without
    it the repository answers from the identity map with the status the pipeline left.
    """
    conversation = (await _conversations(db_session))[0]
    await db_session.execute(
        ConversationModel.__table__.update()
        .where(ConversationModel.id == conversation.id)
        .values(escalation_status=escalation)
    )
    await db_session.flush()
    db_session.expunge_all()


@pytest.mark.parametrize(
    "escalation",
    [ConversationEscalationStatus.PENDING_HUMAN, ConversationEscalationStatus.HUMAN_HANDLING],
)
async def test_a_handed_over_thread_declares_the_wait_and_never_its_reason(
    api, db_session, tenant_a, escalation
) -> None:
    """R2.3: both members mean the same thing to the guest — a person will reply.

    That a manager has already taken it over is our business, not theirs, which is why
    `HUMAN_HANDLING` is not a third state. The reason itself is not a field of the projection
    at all, which the exact key set above already pins.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
    await _set_escalation(db_session, escalation)

    body = (await api.get(f"/api/v1/guest/messages/{token}")).json()

    assert body["state"] == "AWAITING_HUMAN"
    assert set(body) == {"items", "total", "page", "per_page", "state"}


async def test_an_automatic_thread_says_so(api, db_session, tenant_a) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
    await _set_escalation(db_session, ConversationEscalationStatus.NONE)

    assert (await api.get(f"/api/v1/guest/messages/{token}")).json()["state"] == "AUTOMATIC"


async def test_without_page_the_last_window_comes_back(api, db_session, tenant_a) -> None:
    """D9: a thread is read from its end, so the unasked-for window is the most recent one."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    for index in range(3):
        await api.post(f"/api/v1/guest/messages/{token}", json={"content": f"Mensaje {index}"})

    total = (await api.get(f"/api/v1/guest/messages/{token}")).json()["total"]
    body = (await api.get(f"/api/v1/guest/messages/{token}?per_page=1")).json()

    assert body["page"] == total
    assert body["per_page"] == 1
    first = (await api.get(f"/api/v1/guest/messages/{token}?page=1&per_page=1")).json()
    assert first["items"][0]["content"] == "Mensaje 0"
    assert body["items"][0] != first["items"][0]


async def test_no_internal_field_reaches_the_guest_even_when_a_person_holds_the_thread(
    api, db_session, tenant_a
) -> None:
    """R2.2, R2.3 and R2.4 named field by field, against the serialised body.

    The exact key set above is the structural assertion; this is the one a reader can check
    against the requirement without holding the projection in their head, and it runs on a
    conversation that has an intent, a confidence score and a handover — so every value it
    denies actually exists in the database at the moment of the read.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    await api.post(f"/api/v1/guest/messages/{token}", json=MESSAGE)
    await _set_escalation(db_session, ConversationEscalationStatus.PENDING_HUMAN)

    response = await api.get(f"/api/v1/guest/messages/{token}")

    stored = [m for m in await _messages(db_session) if m.intent is not None]
    assert stored, "the fixture must have an intent for this test to deny publishing it"
    for field in (
        "sender_user_id",
        "ai_generated",
        "confidence_score",
        "intent",
        "metadata",
        "conversation_id",
        "escalation_reason",
    ):
        assert field not in response.text
    assert response.json()["state"] == "AWAITING_HUMAN"


# --- Tenant isolation, one test per new way in (R4.5) ----------------------------------
#
# The neighbour's fixture is built **before** any request binds the session, which is the
# caution `design.md` fixes: a stay seeded after a bind would be invisible to the read under
# test for reasons that have nothing to do with the isolation being asserted, and the test
# would pass whatever the code did. Both drive the **real route** with the other tenant's
# token, because that is where the identifiers actually come from.


async def test_reading_a_thread_never_reaches_another_tenants_conversation(
    api, db_session, tenant_a, tenant_b
) -> None:
    theirs, _ = await _stay(db_session, tenant_a, name="Casa Redes")
    their_token = await _token(db_session, tenant_a, theirs)
    ours, _ = await _stay(db_session, tenant_b, name="Piso Riazor")
    our_token = await _token(db_session, tenant_b, ours)

    await api.post(f"/api/v1/guest/messages/{their_token}", json=MESSAGE)
    body = (await api.get(f"/api/v1/guest/messages/{our_token}")).json()

    assert body["items"] == []
    assert body["total"] == 0
    assert MESSAGE["content"] not in str(body)
    assert api.bound_tenants == [tenant_a.id, tenant_b.id]


async def test_writing_a_message_never_lands_in_another_tenants_conversation(
    api, db_session, tenant_a, tenant_b
) -> None:
    theirs, _ = await _stay(db_session, tenant_a, name="Casa Redes")
    their_token = await _token(db_session, tenant_a, theirs)
    ours, _ = await _stay(db_session, tenant_b, name="Piso Riazor")
    our_token = await _token(db_session, tenant_b, ours)

    await api.post(f"/api/v1/guest/messages/{their_token}", json=MESSAGE)
    await api.post(f"/api/v1/guest/messages/{our_token}", json={"content": "Buenas tardes"})

    conversations = await _conversations(db_session)
    assert {c.tenant_id for c in conversations} == {tenant_a.id, tenant_b.id}
    assert len(conversations) == 2
    by_tenant = {c.tenant_id: c for c in conversations}
    assert by_tenant[tenant_b.id].reservation_id == ours.id
    ours_messages = [
        m.content
        for m in await _messages(db_session)
        if m.conversation_id == by_tenant[tenant_b.id].id
    ]
    assert MESSAGE["content"] not in ours_messages
