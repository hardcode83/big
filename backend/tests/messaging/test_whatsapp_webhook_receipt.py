"""Receiving one Meta delivery, at the use-case level (R3.2-R3.5, R4.1; design D3a, D7).

The same split `tests/integrations/test_webhook_receipt.py` established, and for the same
reason: what R3.3 promises — "indistinguible entre esos motivos, sin escribir nada" — is a
property of the code that decides, and asserting it only over HTTP would let it pass because a
router happened to answer the same status for two different reasons. The route's own concerns
(the two rate limits, the statuses, the empty body, the `GET` handshake) live in
`test_whatsapp_webhook_api.py`.

The signatures are computed with `hmac` against the very bytes they accompany — never
hard-coded — reusing section 4's builders, so a payload change cannot leave a stale digest
passing beside it.
"""

import ast
import inspect
import logging
import textwrap
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.messaging.application.webhooks import (
    ReceiveWhatsAppWebhookUseCase,
    WhatsAppDeliveryOutcome,
)
from app.messaging.domain.entities import InboundWhatsAppEvent
from app.messaging.domain.exceptions import (
    MessagingValidationError,
    WhatsAppWebhookAuthenticationError,
)
from app.messaging.domain.value_objects import InboundWhatsAppMessage
from app.messaging.infrastructure.models import (
    WhatsAppInboundEventModel,
    WhatsAppPhoneNumberModel,
)
from app.messaging.infrastructure.repositories import (
    SqlAlchemyWhatsAppInboundEventRepository,
    SqlAlchemyWhatsAppPhoneNumberRepository,
)
from app.messaging.infrastructure.whatsapp_providers import (
    SIGNATURE_HEADER,
    MetaInboundAdapter,
)
from tests.messaging.conftest import seed_property, seed_tenant
from tests.messaging.test_whatsapp_inbound_provider import (
    APP_SECRET,
    GUEST_TEXT,
    PHONE_NUMBER_ID,
    PROVIDER_MESSAGE_ID,
    SENDER_PHONE,
    TIMESTAMP_SECONDS,
    headers_for,
    raw,
    webhook_payload,
)

CALLBACK_URL = "https://api.example.com/api/v1/webhooks/whatsapp"
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


class _Dispatcher:
    """A spy for the injected `dispatch`, which also records whether the row was committed.

    The "committed first" half is what makes task 7.5's "el task se encola tras el commit y no
    antes" checkable at all: the worker is another process on another connection, so an id
    handed over inside the transaction resolves to no row. Reading the row on a **separate**
    session at dispatch time is what distinguishes the two orders — the receiving session's own
    identity map would answer either way.
    """

    def __init__(self, engine) -> None:
        self._engine = engine
        self.calls: list[uuid.UUID] = []
        self.visible_when_dispatched: list[bool] = []

    async def observe(self, event_id: uuid.UUID) -> bool:
        async with AsyncSession(self._engine) as onlooker:
            found = await onlooker.execute(
                select(WhatsAppInboundEventModel.id).where(
                    WhatsAppInboundEventModel.id == event_id
                )
            )
            return found.scalar_one_or_none() is not None

    def __call__(self, event_id: uuid.UUID) -> None:
        self.calls.append(event_id)


@pytest.fixture
def dispatcher(test_engine) -> _Dispatcher:
    return _Dispatcher(test_engine)


def _use_case(db_session, dispatcher, *, secret: str = APP_SECRET):
    return ReceiveWhatsAppWebhookUseCase(
        provider=MetaInboundAdapter(),
        secret=secret,
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(db_session),
        events=SqlAlchemyWhatsAppInboundEventRepository(db_session),
        dispatch=dispatcher,
        uow=SqlAlchemyUnitOfWork(db_session),
    )


@pytest_asyncio.fixture
async def provisioned(db_session):
    """A tenant that has associated `PHONE_NUMBER_ID`, with its default property."""
    tenant = await seed_tenant(db_session, "TenantWhatsApp")
    prop = await seed_property(db_session, tenant, "WA-1")
    db_session.add(
        WhatsAppPhoneNumberModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            phone_number_id=PHONE_NUMBER_ID,
            default_property_id=prop.id,
        )
    )
    await db_session.commit()
    return tenant, prop


async def _events(db_session) -> list[WhatsAppInboundEventModel]:
    result = await db_session.execute(select(WhatsAppInboundEventModel))
    return list(result.scalars())


# --- R3.2/R3.3: the four ways authentication fails, and the one answer ---------------------


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("no signature header at all", lambda body, headers: {}),
        (
            "a header that is not sha256=<hex>",
            lambda body, headers: {SIGNATURE_HEADER: "not-a-signature"},
        ),
        (
            "Meta's superseded sha1 algorithm",
            lambda body, headers: {
                SIGNATURE_HEADER: headers[SIGNATURE_HEADER].replace("sha256=", "sha1=")
            },
        ),
        (
            "a digest computed under another key",
            lambda body, headers: headers_for(body, "someone-elses-secret"),
        ),
        (
            "a body altered after it was signed",
            lambda body, headers: headers_for(body + b" ", APP_SECRET),
        ),
    ],
)
@pytest.mark.asyncio
async def test_every_authentication_failure_raises_the_same_bare_error(
    db_session, dispatcher, case, mutate
) -> None:
    """R3.3: one class, no reason on it, and no way to tell the five cases apart."""
    payload = webhook_payload()
    body = raw(payload)
    use_case = _use_case(db_session, dispatcher)

    with pytest.raises(WhatsAppWebhookAuthenticationError) as raised:
        use_case.authenticate(
            raw_body=body, headers=mutate(body, headers_for(body)), url=CALLBACK_URL
        )

    assert str(raised.value) == "", f"{case} leaked a reason"
    assert raised.value.args == ()


@pytest.mark.asyncio
async def test_a_failed_authentication_writes_nothing(db_session, dispatcher) -> None:
    """R3.3's "sin escribir nada", asserted against the database and not against a promise."""
    body = raw(webhook_payload())
    use_case = _use_case(db_session, dispatcher)

    with pytest.raises(WhatsAppWebhookAuthenticationError):
        use_case.authenticate(raw_body=body, headers={}, url=CALLBACK_URL)

    assert await _events(db_session) == []
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_a_blank_secret_authenticates_nobody(db_session, dispatcher) -> None:
    """`mock` mode, and a half-configured `meta` one, refuse every delivery (task 7.1).

    An HMAC under an empty key is one anybody can compute, so this is the one configuration
    where "verifies correctly" would be a hole rather than a check.
    """
    body = raw(webhook_payload())
    use_case = _use_case(db_session, dispatcher, secret="")

    with pytest.raises(WhatsAppWebhookAuthenticationError):
        use_case.authenticate(
            raw_body=body, headers=headers_for(body, ""), url=CALLBACK_URL
        )


@pytest.mark.asyncio
async def test_a_valid_signature_authenticates_and_touches_no_repository(
    db_session, dispatcher
) -> None:
    """`authenticate` is the half that must be answerable without interpreting the body."""
    body = raw(webhook_payload())

    _use_case(db_session, dispatcher).authenticate(
        raw_body=body, headers=headers_for(body), url=CALLBACK_URL
    )

    assert await _events(db_session) == []


@pytest.mark.asyncio
async def test_the_raw_bytes_are_what_is_verified_not_a_reserialisation(
    db_session, dispatcher
) -> None:
    """Re-serialising a parsed body changes separators, and the signature dies with them.

    The reason `authenticate` takes `bytes` and the router calls `await request.body()`.
    """
    import json

    payload = webhook_payload()
    arrived = json.dumps(payload, separators=(",", ":")).encode()
    headers = headers_for(arrived)
    reserialised = json.dumps(payload, indent=2).encode()

    _use_case(db_session, dispatcher).authenticate(
        raw_body=arrived, headers=headers, url=CALLBACK_URL
    )
    with pytest.raises(WhatsAppWebhookAuthenticationError):
        _use_case(db_session, dispatcher).authenticate(
            raw_body=reserialised, headers=headers, url=CALLBACK_URL
        )


# --- Section 4's "nothing to do" bodies ----------------------------------------------------


@pytest.mark.parametrize(
    ("case", "payload"),
    [
        ("a delivery-status receipt", {"entry": [{"changes": [{"value": {"statuses": []}}]}]}),
        ("an empty entry", {"entry": []}),
        ("a non-text message", None),
    ],
)
@pytest.mark.asyncio
async def test_a_body_with_no_message_for_us_is_recorded_nowhere(
    db_session, dispatcher, case, payload
) -> None:
    """`NO_MESSAGE`: not an error, nothing to do, and the router answers `202` (section 4).

    Meta posts these to the very same URL, so any non-2xx would make every receipt of our own
    outbound replies retry for ever.
    """
    if payload is None:
        payload = webhook_payload(
            messages=[{"from": SENDER_PHONE, "id": "wamid.x", "timestamp": "1699999999",
                       "type": "image", "image": {"id": "media"}}]
        )
    body = raw(payload)

    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )

    assert receipt.outcome is WhatsAppDeliveryOutcome.NO_MESSAGE, case
    assert receipt.event_id is None
    assert await _events(db_session) == []
    assert dispatcher.calls == []


# --- R4.1: the tenant comes from the provisioning table, or from nowhere -------------------


@pytest.mark.asyncio
async def test_a_provisioned_number_resolves_both_anchors_and_queues(
    db_session, dispatcher, provisioned
) -> None:
    """R4.1 and task 7.2: one row of `whatsapp_phone_numbers` answers tenant AND property."""
    tenant, prop = provisioned
    body = raw(webhook_payload())

    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )

    assert receipt.outcome is WhatsAppDeliveryOutcome.QUEUED
    (event,) = await _events(db_session)
    assert event.id == receipt.event_id
    assert event.tenant_id == tenant.id
    assert event.default_property_id == prop.id
    assert event.phone_number_id == PHONE_NUMBER_ID
    assert event.provider_message_id == PROVIDER_MESSAGE_ID
    assert event.sender_phone == SENDER_PHONE
    assert event.message_text == GUEST_TEXT
    assert event.received_at == datetime.fromtimestamp(TIMESTAMP_SECONDS, tz=UTC)
    assert event.processed_at is None
    assert dispatcher.calls == [receipt.event_id]


@pytest.mark.asyncio
async def test_resolution_never_crosses_into_a_second_tenants_number(
    db_session, dispatcher
) -> None:
    """R4.1's single lookup, checked with two rows in the table instead of one.

    Every other fixture in this file provisions exactly one tenant/number pair, which cannot
    tell "resolves the right tenant" apart from "resolves the only tenant". Here two tenants
    each provision their own `phone_number_id`, a delivery arrives addressed to tenant A's, and
    the assertion is not just "the row says tenant A" — it is also that tenant B, who never
    appears anywhere in the request, has no row at all afterwards.
    """
    tenant_a = await seed_tenant(db_session, "TenantWhatsAppA")
    property_a = await seed_property(db_session, tenant_a, "WA-A")
    tenant_b = await seed_tenant(db_session, "TenantWhatsAppB")
    property_b = await seed_property(db_session, tenant_b, "WA-B")
    other_phone_number_id = "9999999999"
    db_session.add_all(
        [
            WhatsAppPhoneNumberModel(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                phone_number_id=PHONE_NUMBER_ID,
                default_property_id=property_a.id,
            ),
            WhatsAppPhoneNumberModel(
                id=uuid.uuid4(),
                tenant_id=tenant_b.id,
                phone_number_id=other_phone_number_id,
                default_property_id=property_b.id,
            ),
        ]
    )
    await db_session.commit()
    body = raw(webhook_payload())  # addressed to PHONE_NUMBER_ID, i.e. tenant A's number

    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )

    assert receipt.outcome is WhatsAppDeliveryOutcome.QUEUED
    (event,) = await _events(db_session)
    assert event.tenant_id == tenant_a.id
    assert event.default_property_id == property_a.id
    assert event.tenant_id != tenant_b.id
    assert event.default_property_id != property_b.id

    # Nothing at all lands for tenant B: no event row, whatever its tenant_id would need to be.
    tenant_b_events = await db_session.execute(
        select(WhatsAppInboundEventModel).where(
            WhatsAppInboundEventModel.tenant_id == tenant_b.id
        )
    )
    assert list(tenant_b_events.scalars()) == []


@pytest.mark.asyncio
async def test_the_task_is_dispatched_only_after_the_row_is_committed(
    db_session, dispatcher, provisioned
) -> None:
    """Task 7.5's ordering, watched from a session that is not the receiver's.

    A worker on another connection cannot see an uncommitted row, so an id dispatched too
    early is an id that resolves to nothing — and the symptom is an inbound message the guest
    never gets an answer to, once, in a worker log.
    """
    body = raw(webhook_payload())

    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )

    assert dispatcher.calls == [receipt.event_id]
    assert await dispatcher.observe(receipt.event_id) is True


def test_the_commit_call_precedes_the_dispatch_call_in_source_order() -> None:
    """Task 7.5's ordering, pinned by the *shape* of `record` rather than by `_Dispatcher`'s
    timing.

    `_Dispatcher.__call__` above is synchronous, does no I/O, and is only inspected after
    `record` has fully returned — nothing between the dispatch call and `await
    self._uow.commit()` inside `record` yields control, so
    `test_the_task_is_dispatched_only_after_the_row_is_committed` would stay green even if
    `record` called `self._dispatch(...)` one line *before* `self._uow.commit()` instead of
    after: `dispatcher.calls == [receipt.event_id]` holds either way, and `observe` only ever
    runs once `record` — and therefore the commit — has already completed.

    This is the same "pin the shape, not a name" approach
    `test_whatsapp_inbound_provider.py::test_the_verdict_is_returned_by_the_one_constant_time_comparison`
    uses for `verify_signature`: parse `record`'s own source and assert, structurally, that the
    call to `self._uow.commit()` appears before the call to `self._dispatch(...)`.
    """
    source = textwrap.dedent(inspect.getsource(ReceiveWhatsAppWebhookUseCase.record))
    tree = ast.parse(source)

    def _sole_call_lineno(attr: str) -> int:
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ]
        assert len(calls) == 1, f"expected exactly one call to `.{attr}(...)` in `record`"
        return calls[0].lineno

    commit_lineno = _sole_call_lineno("commit")
    dispatch_lineno = _sole_call_lineno("_dispatch")

    assert commit_lineno < dispatch_lineno, (
        "`record` calls `self._dispatch(...)` before `self._uow.commit()` — task 7.5 and "
        "design D7 require the commit to land first, since the worker reads the event row "
        "from a separate connection that cannot see an uncommitted transaction"
    )


@pytest.mark.asyncio
async def test_an_unprovisioned_number_is_recorded_visibly_and_never_dispatched(
    db_session, dispatcher, caplog
) -> None:
    """R3.3 as amended: a distinct, non-adversarial case, handled by R4.3's criterion.

    Not discarded (there is a row), not confused with a signature failure (no exception, and
    an `event_id` comes back), and not dispatched — there is no tenant to run it for.
    """
    body = raw(webhook_payload())

    with caplog.at_level(logging.WARNING, logger="app.messaging.application.webhooks"):
        receipt = await _use_case(db_session, dispatcher).record(
            raw_body=body, headers=headers_for(body), now=NOW
        )

    assert receipt.outcome is WhatsAppDeliveryOutcome.UNPROVISIONED_NUMBER
    (event,) = await _events(db_session)
    assert event.tenant_id is None
    assert event.default_property_id is None
    assert event.message_text == GUEST_TEXT
    assert dispatcher.calls == []

    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.message == "messaging.whatsapp_webhook_unprovisioned_number"
    assert record.phone_number_id == PHONE_NUMBER_ID
    # Rule 11: the operator needs the number to provision, never the guest's words or number.
    assert GUEST_TEXT not in caplog.text
    assert SENDER_PHONE not in caplog.text


@pytest.mark.asyncio
async def test_the_unprovisioned_outcome_is_not_the_signature_failure(
    db_session, dispatcher
) -> None:
    """The two are deliberately different, and this is what says so out loud.

    R3.3's indistinguishability covers forgeries. Producing a validly signed delivery requires
    the App secret, so an unmapped number is an operator's unfinished setup — answering it like
    an attack is what would leave the operator with nothing to look at.
    """
    body = raw(webhook_payload())
    use_case = _use_case(db_session, dispatcher)

    use_case.authenticate(raw_body=body, headers=headers_for(body), url=CALLBACK_URL)
    receipt = await use_case.record(raw_body=body, headers=headers_for(body), now=NOW)

    assert receipt.outcome is WhatsAppDeliveryOutcome.UNPROVISIONED_NUMBER
    assert receipt.event_id is not None
    assert len(await _events(db_session)) == 1


# --- R3.5: the provider redelivers -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_redelivery_of_the_same_message_creates_no_second_row(
    db_session, dispatcher, provisioned
) -> None:
    """R3.5. Meta redelivers on any non-2xx, and on nothing at all sometimes."""
    body = raw(webhook_payload())
    use_case = _use_case(db_session, dispatcher)

    first = await use_case.record(raw_body=body, headers=headers_for(body), now=NOW)
    second = await use_case.record(raw_body=body, headers=headers_for(body), now=NOW)

    assert first.outcome is WhatsAppDeliveryOutcome.QUEUED
    assert second.outcome is WhatsAppDeliveryOutcome.DUPLICATE
    assert second.event_id is None
    assert len(await _events(db_session)) == 1
    # And nothing was queued a second time: the first delivery's task is already in flight.
    assert dispatcher.calls == [first.event_id]


@pytest.mark.asyncio
async def test_a_redelivery_reaching_a_different_body_still_dedupes_on_the_id(
    db_session, dispatcher, provisioned
) -> None:
    """The key is the provider's id, not the bytes: Meta may re-send with different framing."""
    first_body = raw(webhook_payload())
    use_case = _use_case(db_session, dispatcher)
    await use_case.record(raw_body=first_body, headers=headers_for(first_body), now=NOW)

    second_body = raw(webhook_payload(contacts=[{"wa_id": SENDER_PHONE}]))
    second = await use_case.record(
        raw_body=second_body, headers=headers_for(second_body), now=NOW
    )

    assert second.outcome is WhatsAppDeliveryOutcome.DUPLICATE
    assert len(await _events(db_session)) == 1


@pytest.mark.asyncio
async def test_a_genuinely_new_message_is_not_mistaken_for_a_redelivery(
    db_session, dispatcher, provisioned
) -> None:
    """The dedupe must not be so eager that a guest's second message disappears."""
    use_case = _use_case(db_session, dispatcher)
    first = raw(webhook_payload())
    await use_case.record(raw_body=first, headers=headers_for(first), now=NOW)

    second = raw(
        webhook_payload(
            messages=[
                {
                    "from": SENDER_PHONE,
                    "id": "wamid.a-second-message",
                    "timestamp": str(TIMESTAMP_SECONDS + 60),
                    "type": "text",
                    "text": {"body": "Y otra cosa"},
                }
            ]
        )
    )
    receipt = await use_case.record(raw_body=second, headers=headers_for(second), now=NOW)

    assert receipt.outcome is WhatsAppDeliveryOutcome.QUEUED
    assert len(await _events(db_session)) == 2
    assert len(dispatcher.calls) == 2


# --- The entity's own invariant and the repository's two guards ---------------------------


def _message() -> InboundWhatsAppMessage:
    return InboundWhatsAppMessage(
        sender_phone=SENDER_PHONE,
        provider_message_id=PROVIDER_MESSAGE_ID,
        text=GUEST_TEXT,
        received_at=datetime.fromtimestamp(TIMESTAMP_SECONDS, tz=UTC),
        business_phone_number=PHONE_NUMBER_ID,
    )


@pytest.mark.parametrize(
    ("tenant_id", "default_property_id"),
    [(uuid.uuid4(), None), (None, uuid.uuid4())],
)
def test_an_event_naming_one_anchor_without_the_other_is_refused(
    tenant_id, default_property_id
) -> None:
    """Both come from one `whatsapp_phone_numbers` row, so one without the other is a bug.

    Refused here rather than discovered in the worker, where a tenant with no property would
    surface as `Conversation.__post_init__` complaining about a property.
    """
    with pytest.raises(MessagingValidationError):
        InboundWhatsAppEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            default_property_id=default_property_id,
            message=_message(),
        )


@pytest.mark.parametrize(
    ("tenant_id", "default_property_id", "resolved"),
    [(None, None, False), ("t", "p", True)],
)
def test_is_resolved_is_derived_from_the_pair_and_not_stored(
    tenant_id, default_property_id, resolved
) -> None:
    event = InboundWhatsAppEvent(
        id=uuid.uuid4(),
        tenant_id=None if tenant_id is None else uuid.uuid4(),
        default_property_id=None if default_property_id is None else uuid.uuid4(),
        message=_message(),
    )

    assert event.is_resolved is resolved


@pytest.mark.asyncio
async def test_the_dispatched_read_refuses_a_marked_session(db_session) -> None:
    """The census's guard, exercised rather than assumed (`tests/test_unscoped_reads.py`).

    On a marked session the query would be narrowed to that tenant — and, for the rows whose
    `tenant_id` is `NULL`, to nothing at all, without erroring. Refusing is what turns that
    silent wrong answer into a visible one.
    """
    tenant = await seed_tenant(db_session, "TenantMarked")
    bind_session_to_tenant(db_session, tenant.id)
    repository = SqlAlchemyWhatsAppInboundEventRepository(db_session)

    with pytest.raises(Exception) as raised:
        await repository.locate_without_tenant_scoping(uuid.uuid4())

    assert "locate_without_tenant_scoping" in str(raised.value)


@pytest.mark.asyncio
async def test_the_dispatched_read_returns_the_message_it_recorded(
    db_session, dispatcher, provisioned
) -> None:
    """The row round-trips through the value object the worker needs."""
    tenant, prop = provisioned
    body = raw(webhook_payload())
    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )

    event = await SqlAlchemyWhatsAppInboundEventRepository(
        db_session
    ).locate_without_tenant_scoping(receipt.event_id)

    assert event is not None
    assert event.tenant_id == tenant.id
    assert event.default_property_id == prop.id
    assert event.message == _message()
    assert event.is_resolved is True


@pytest.mark.asyncio
async def test_the_dispatched_read_answers_none_for_an_id_that_is_not_there(
    db_session,
) -> None:
    """A task whose row has gone is not worth retrying for ever."""
    repository = SqlAlchemyWhatsAppInboundEventRepository(db_session)

    assert await repository.locate_without_tenant_scoping(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_only_the_first_claim_of_an_event_succeeds(
    db_session, dispatcher, provisioned
) -> None:
    """Celery's delivery is at-least-once; the second run must find the claim taken.

    Without this, a redelivered *task* posts the guest's message into the thread a second
    time — the same outcome R3.5 forbids, reached by another route.
    """
    tenant, _ = provisioned
    body = raw(webhook_payload())
    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )
    repository = SqlAlchemyWhatsAppInboundEventRepository(db_session)

    assert await repository.mark_processed(tenant.id, receipt.event_id, now=NOW) is True
    assert await repository.mark_processed(tenant.id, receipt.event_id, now=NOW) is False


@pytest.mark.asyncio
async def test_a_claim_from_another_tenant_does_not_land(
    db_session, dispatcher, provisioned
) -> None:
    """`mark_processed` is scoped like every other write in this module (rule 1)."""
    body = raw(webhook_payload())
    receipt = await _use_case(db_session, dispatcher).record(
        raw_body=body, headers=headers_for(body), now=NOW
    )
    other = await seed_tenant(db_session, "TenantB")

    assert await SqlAlchemyWhatsAppInboundEventRepository(db_session).mark_processed(
        other.id, receipt.event_id, now=NOW
    ) is False
