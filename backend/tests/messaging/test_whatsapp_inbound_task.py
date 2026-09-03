"""The dispatched task and the whole round trip (R3.4, R3.5, R4.1, R5.1-R5.3; D7, task 7.4/7.5).

Two things live here, and the second is the point of the whole change:

* **the task as it is actually wired** — the part only a composition root can get wrong: that
  the event is located on a session the worker never marks, that the tenant's work then runs
  on one marked for it, and that a second run of the same task does nothing;
* **the round trip**, from a signed Meta delivery on the anonymous route to the AI's reply
  leaving through section 1/2's adapter from the number the guest wrote to, inside the 24 h
  session window.

In `tests/messaging/` rather than `tests/scheduler/` — where its sibling
`test_webhook_task.py` lives — because task 7.5 puts this change's tests here and because the
round trip is a messaging property that happens to pass through a task. The worker's session
factory is swapped for the test one exactly as that sibling does it: `conftest.py` builds a
`NullPool` engine on a throwaway database per test, while the worker's own factory points at
the development database.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.db import TENANT_ID_SESSION_KEY, get_db_session
from app.main import create_app
from app.messaging.domain.enums import ConversationChannel, MessageSenderType
from app.messaging.infrastructure import channels
from app.messaging.infrastructure.models import (
    ConversationModel,
    MessageModel,
    WhatsAppInboundEventModel,
    WhatsAppPhoneNumberModel,
)
from app.notifications.domain.results import NotificationResult
from app.scheduler import runner, whatsapp_tasks
from tests.messaging.conftest import seed_guest, seed_property, seed_reservation, seed_tenant
from tests.messaging.test_whatsapp_inbound_provider import (
    APP_SECRET,
    GUEST_TEXT,
    PHONE_NUMBER_ID,
    SENDER_PHONE,
    headers_for,
    raw,
    webhook_payload,
)

WEBHOOK_URL = "/api/v1/webhooks/whatsapp"

#: The guest's number as `guests.phone` stores it — E.164, which is `SENDER_PHONE` with a `+`.
#: Section 4's notes are explicit that Meta's `from` is bare digits, and section 5 prepends
#: the `+` before looking a guest up; if that ever stops being true, the round trip below
#: stops resolving a guest and this constant is where a reader will look.
GUEST_PHONE_E164 = f"+{SENDER_PHONE}"


class _RecordingWhatsApp:
    """Stands in for the WhatsApp delegate and keeps every kwarg it was sent.

    Substituted into `app/messaging/infrastructure/channels.py`'s namespace, which is where
    `outbound_registry()` looks the classes up — so the delegate the real
    `DelegatingOutboundAdapter` wraps is this one, and everything between the pipeline and it
    is the production path. **Both** names are replaced, and that is deliberate: which one
    `outbound_registry` picks depends on `settings.whatsapp_provider`, and a spy installed
    over only one of them would silently stop being consulted the day a test moved that
    setting — which is exactly what happened while this file was being written.

    It accepts `WhatsAppCloudAdapter`'s constructor keywords so it can stand in for the
    `meta` branch too, and ignores them: what this file asserts about is the *send*.
    """

    sends: list[dict] = []

    def __init__(self, **_construction: object) -> None:
        pass

    async def send(self, **kwargs) -> NotificationResult:
        type(self).sends.append(kwargs)
        return NotificationResult.ok()


@pytest.fixture
def recording_whatsapp(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingWhatsApp]:
    _RecordingWhatsApp.sends = []
    monkeypatch.setattr(channels, "MockWhatsAppAdapter", _RecordingWhatsApp)
    monkeypatch.setattr(channels, "WhatsAppCloudAdapter", _RecordingWhatsApp)
    return _RecordingWhatsApp


@pytest.fixture
def worker_sessions(test_engine, monkeypatch: pytest.MonkeyPatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "_session_factory", factory)
    return factory


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_provider", "meta")
    monkeypatch.setattr(settings, "whatsapp_app_secret", APP_SECRET)
    monkeypatch.setattr(settings, "whatsapp_webhook_verify_token", "irrelevant-here")
    # `meta` is what `whatsapp_signing_secret()` requires before it hands the receiver a real
    # key (task 7.1), so the round trip has to run in that mode — which also means
    # `outbound_registry` takes the `WhatsAppCloudAdapter` branch. These two keep its
    # constructor happy; `recording_whatsapp` is what replaces the class itself.
    monkeypatch.setattr(settings, "whatsapp_access_token", "a-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "9990001")


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def __call__(self, event_id: uuid.UUID) -> None:
        self.calls.append(event_id)


@pytest_asyncio.fixture
async def world(db_session):
    """A tenant with a provisioned number, a guest on that phone, and an active stay.

    The single-guest, single-stay branch of section 5's table — the one that resolves a real
    property — because the round trip is about the *answered* path. The other four branches
    have their own tests in `test_whatsapp_inbound.py`.
    """
    tenant = await seed_tenant(db_session, "TenantRoundTrip")
    prop = await seed_property(db_session, tenant, "RT-1")
    guest = await seed_guest(db_session, tenant, full_name="Ada", phone=GUEST_PHONE_E164)
    reservation = await seed_reservation(
        db_session, tenant, prop, check_in=datetime.now(UTC).date()
    )
    reservation.guest_id = guest.id
    db_session.add(
        WhatsAppPhoneNumberModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            phone_number_id=PHONE_NUMBER_ID,
            default_property_id=prop.id,
        )
    )
    await db_session.commit()
    return tenant, prop, guest, reservation


async def _deliver(db_session, dispatcher, *, payload=None) -> uuid.UUID | None:
    """POST a signed delivery through the real route and return the dispatched event id."""
    from app.integrations.api.dependencies import get_webhook_throttle
    from app.messaging.api.dependencies import get_whatsapp_inbound_dispatcher

    class _AllowAll:
        async def probe_allowed(self, client_ip: str) -> bool:
            return True

        async def delivery_allowed(self, key: str) -> bool:
            return True

        async def record_failed_attempt(self, client_ip: str) -> None:
            return None

    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_webhook_throttle] = _AllowAll
    app.dependency_overrides[get_whatsapp_inbound_dispatcher] = lambda: dispatcher

    body = raw(payload if payload is not None else webhook_payload())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=headers_for(body))

    assert response.status_code == 202
    return dispatcher.calls[-1] if dispatcher.calls else None


async def _messages(db_session, conversation_id) -> list[MessageModel]:
    result = await db_session.execute(
        select(MessageModel)
        .where(MessageModel.conversation_id == conversation_id)
        .order_by(MessageModel.created_at)
    )
    return list(result.scalars())


# --- The task's own wiring (task 7.4) ------------------------------------------------------


def test_the_task_is_registered_and_has_no_cadence() -> None:
    """Design D7: `.delay(...)` starts it, and nothing else does."""
    from app.scheduler.schedule import CADENCES, DAILY_JOBS, ON_DEMAND_TASKS, beat_schedule
    from app.worker import celery_app

    assert whatsapp_tasks.WHATSAPP_INBOUND_TASK in celery_app.tasks
    assert whatsapp_tasks.WHATSAPP_INBOUND_TASK not in CADENCES
    assert whatsapp_tasks.WHATSAPP_INBOUND_TASK not in DAILY_JOBS
    assert whatsapp_tasks.WHATSAPP_INBOUND_TASK in ON_DEMAND_TASKS
    assert whatsapp_tasks.WHATSAPP_INBOUND_TASK not in {
        entry["task"] for entry in beat_schedule().values()
    }


@pytest.mark.asyncio
async def test_an_event_id_that_resolves_to_nothing_is_not_retried_for_ever(
    worker_sessions,
) -> None:
    """A missing row is reported, not raised: no redelivery will bring it back."""
    result = await whatsapp_tasks._process_inbound_whatsapp_message(uuid.uuid4())

    assert result["processed"] is False
    assert result["reason"] == "missing"


@pytest.mark.asyncio
async def test_an_unresolved_event_is_refused_rather_than_guessed_at(
    db_session, worker_sessions
) -> None:
    """The receiver never dispatches one of these, so arriving here means a caller is wrong.

    There is no tenant to run it for, and inventing one is what R4.1 forbids in as many words.
    """
    event = WhatsAppInboundEventModel(
        id=uuid.uuid4(),
        phone_number_id=PHONE_NUMBER_ID,
        provider_message_id=f"wamid.{uuid.uuid4().hex}",
        sender_phone=GUEST_PHONE_E164,
        message_text=GUEST_TEXT,
        received_at=datetime.now(UTC),
    )
    db_session.add(event)
    await db_session.commit()

    result = await whatsapp_tasks._process_inbound_whatsapp_message(event.id)

    assert result["processed"] is False
    assert result["reason"] == "unresolved"


@pytest.mark.asyncio
async def test_the_event_is_located_unmarked_and_the_work_runs_marked(
    db_session, world, worker_sessions, recording_whatsapp, monkeypatch
) -> None:
    """The pair a refactor is most likely to collapse, so both halves are captured.

    The lookup cannot be scoped — the row is what names the tenant, and an unprovisioned one
    names none — while the work must be, because everything it touches is that tenant's.
    """
    tenant, *_ = world
    dispatcher = _Dispatcher()
    event_id = await _deliver(db_session, dispatcher)

    markers: list[object] = []
    original = whatsapp_tasks.SqlAlchemyWhatsAppInboundEventRepository

    class _Watching(original):  # type: ignore[misc,valid-type]
        def __init__(self, session):
            markers.append(session.info.get(TENANT_ID_SESSION_KEY))
            super().__init__(session)

    monkeypatch.setattr(whatsapp_tasks, "SqlAlchemyWhatsAppInboundEventRepository", _Watching)

    result = await whatsapp_tasks._process_inbound_whatsapp_message(event_id)

    assert result["processed"] is True
    # First construction is the lookup's, on a session nothing marked; the second is the
    # claim's, on the session `run_in_marked_session` bound to this tenant.
    assert markers == [None, tenant.id]


@pytest.mark.asyncio
async def test_a_second_run_of_the_same_task_changes_nothing(
    db_session, world, worker_sessions, recording_whatsapp
) -> None:
    """Celery's delivery is at-least-once, and the guest must not see their message twice.

    R3.5 is written about the provider redelivering; this is the same outcome by the other
    route, and the conditional claim is what closes it.
    """
    dispatcher = _Dispatcher()
    event_id = await _deliver(db_session, dispatcher)

    first = await whatsapp_tasks._process_inbound_whatsapp_message(event_id)
    second = await whatsapp_tasks._process_inbound_whatsapp_message(event_id)

    assert first["processed"] is True
    assert second["processed"] is False

    db_session.expire_all()
    conversation = (
        await db_session.execute(select(ConversationModel))
    ).scalars().one()
    guest_messages = [
        m
        for m in await _messages(db_session, conversation.id)
        if m.sender_type is MessageSenderType.GUEST
    ]
    assert len(guest_messages) == 1


def test_the_celery_entrypoint_parses_the_id_it_was_given_as_a_string(
    worker_sessions,
) -> None:
    """Celery serialises arguments as JSON, which has no UUID — hence the `str` round trip.

    **Not an `asyncio` test**, unlike everything else here: the Celery entrypoint is
    synchronous and calls `asyncio.run` itself (`run_sync`), which refuses to nest inside a
    loop pytest-asyncio has already started.
    """
    missing = uuid.uuid4()

    result = whatsapp_tasks.process_inbound_whatsapp_message(str(missing))

    assert result == {"event_id": str(missing), "processed": False, "reason": "missing"}


def test_a_malformed_id_is_not_swallowed(worker_sessions) -> None:
    """It can only be a bug in the dispatcher, and a silent return would hide it."""
    with pytest.raises(ValueError):
        whatsapp_tasks.process_inbound_whatsapp_message("not-a-uuid")


# --- The round trip (R5.1, R5.2, R5.3, task 7.5) -------------------------------------------


@pytest.mark.asyncio
async def test_a_guests_message_becomes_a_thread_a_reply_and_an_outbound_send(
    db_session, world, worker_sessions, recording_whatsapp
) -> None:
    """The whole change, end to end, through the real route and the real pipeline.

    What each assertion is for:

    * the conversation is `WHATSAPP` and carries the number the guest wrote **to** (D4), which
      is what a reply leaves from for the life of the thread;
    * the guest's words reach `messages.content` verbatim through
      `ProcessInboundGuestMessageUseCase` — R5.2's "sin duplicarlas", since nothing in this
      change writes that column itself;
    * the AI's reply is sent through section 1/2's adapter with `phone_number_id` set to the
      conversation's business number rather than the platform default (task 2.6), and with a
      `last_inbound_at` inside the 24 h window, which is what lets it go as free text (R2.1).
    """
    tenant, prop, guest, _reservation = world
    # Captured into plain locals BEFORE anything expires the session's objects: `expire_all()`
    # below detaches every ORM value the fixture handed over, and reloading one from a sync
    # attribute access raises `MissingGreenlet` rather than doing the IO. Section 6's notes
    # record the same trap one rollback over.
    tenant_id, property_id, guest_id = tenant.id, prop.id, guest.id
    dispatcher = _Dispatcher()
    event_id = await _deliver(db_session, dispatcher)

    assert await whatsapp_tasks._process_inbound_whatsapp_message(event_id) == {
        "event_id": str(event_id),
        "processed": True,
    }

    db_session.expire_all()
    conversation = (await db_session.execute(select(ConversationModel))).scalars().one()
    assert conversation.tenant_id == tenant_id
    assert conversation.channel is ConversationChannel.WHATSAPP
    assert conversation.business_phone_number == PHONE_NUMBER_ID
    # The single-guest, single-stay branch: the stay's property, not the tenant's default.
    assert conversation.guest_id == guest_id
    assert conversation.property_id == property_id

    messages = await _messages(db_session, conversation.id)
    assert [m.sender_type for m in messages][0] is MessageSenderType.GUEST
    assert messages[0].content == GUEST_TEXT
    assert any(m.ai_generated for m in messages)

    (send,) = _RecordingWhatsApp.sends
    assert send["phone_number_id"] == PHONE_NUMBER_ID
    assert send["last_inbound_at"] is not None
    assert datetime.now(UTC) - send["last_inbound_at"] < timedelta(hours=24)
    assert send["body"]


@pytest.mark.asyncio
async def test_the_event_is_marked_processed_in_the_same_transaction_as_the_message(
    db_session, world, worker_sessions, recording_whatsapp
) -> None:
    """One commit, the pipeline's (R4.7): a processed flag without a message, or the other way
    round, is the split this ordering exists to prevent."""
    dispatcher = _Dispatcher()
    event_id = await _deliver(db_session, dispatcher)

    await whatsapp_tasks._process_inbound_whatsapp_message(event_id)

    db_session.expire_all()
    event = (
        await db_session.execute(
            select(WhatsAppInboundEventModel).where(WhatsAppInboundEventModel.id == event_id)
        )
    ).scalars().one()
    conversation = (await db_session.execute(select(ConversationModel))).scalars().one()

    assert event.processed_at is not None
    assert await _messages(db_session, conversation.id)


@pytest.mark.asyncio
async def test_a_providers_redelivery_never_reaches_the_task_twice(
    db_session, world, worker_sessions, recording_whatsapp
) -> None:
    """R3.5 from the outside: two identical POSTs, one row, one dispatch, one message."""
    dispatcher = _Dispatcher()
    await _deliver(db_session, dispatcher)
    await _deliver(db_session, dispatcher)

    assert len(dispatcher.calls) == 1
    assert len(
        (await db_session.execute(select(WhatsAppInboundEventModel))).scalars().all()
    ) == 1

    await whatsapp_tasks._process_inbound_whatsapp_message(dispatcher.calls[0])

    db_session.expire_all()
    conversation = (await db_session.execute(select(ConversationModel))).scalars().one()
    guest_messages = [
        m
        for m in await _messages(db_session, conversation.id)
        if m.sender_type is MessageSenderType.GUEST
    ]
    assert len(guest_messages) == 1


@pytest.mark.asyncio
async def test_the_guests_words_reach_only_the_two_columns_the_census_declares(
    db_session, world, worker_sessions, recording_whatsapp
) -> None:
    """The rule-11 sweep for this path, in the shape `test_free_text_sink_contract.py` uses.

    The guest's prose is allowed in `messages.content` (its own census row) and in
    `whatsapp_inbound_events.message_text` (the row this change adds — a second persisted copy
    one hop earlier, in the queue that crosses the Celery boundary). Anywhere else in the
    schema is a leak, and the sweep is driven off the ORM registry rather than a list somebody
    thought of, so a column added later joins it by existing.
    """
    from sqlalchemy import JSON, String, Text
    from sqlalchemy.dialects.postgresql import JSONB

    from app.core.db import Base

    dispatcher = _Dispatcher()
    event_id = await _deliver(db_session, dispatcher)
    await whatsapp_tasks._process_inbound_whatsapp_message(event_id)
    db_session.expire_all()

    declared = {
        ("messages", "content"),
        ("whatsapp_inbound_events", "message_text"),
    }
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
                assert GUEST_TEXT.lower() not in str(value).lower(), (
                    f"{table.name}.{column.name} carries the guest's words, which the "
                    "rule-11 census does not declare"
                )

    assert swept > 50, "the sweep must reach the schema, not an empty registry"
    # And the two places it may be, so the sweep above is not passing for want of data.
    texts = (
        await db_session.execute(select(WhatsAppInboundEventModel.message_text))
    ).scalars().all()
    assert texts == [GUEST_TEXT]
