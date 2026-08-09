"""Authenticating an incoming notice (`reservations-webhooks` R1.1-R1.6, R4.1; D1, D4, D5).

**Without FastAPI in the way, on purpose** (D5). The rule these assert — which token resolves which
tenant, and that every way of failing looks the same — is a business rule, so it is checked against
the function that decides it. Driving it through HTTP would let a router change turn four
indistinguishable answers into two while these still passed; the endpoint's own concerns (status
codes, the rate limits) are task 2.5.
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.crypto import encrypt
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.application.webhooks import (
    UNKNOWN_EVENT_TYPE,
    ReceiveWebhookUseCase,
)
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import WebhookAuthenticationError
from app.integrations.domain.webhook_auth import (
    generate_webhook_token,
    hash_webhook_token,
)
from app.integrations.infrastructure.card_data import scrub_card_data
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookEventRepository,
)
from tests.auth.conftest import utc_now

HEADER_NAME = "X-Beds24-Secret"
SECRET = "paste-me-into-the-panel"
BODY = {"event": "booking.modified", "bookingId": "42"}


def _use_case(db_session) -> ReceiveWebhookUseCase:
    return ReceiveWebhookUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(db_session),
        events=SqlAlchemyWebhookEventRepository(db_session),
        scrub=scrub_card_data,
        uow=SqlAlchemyUnitOfWork(db_session),
    )


def _headers(**values):
    """A case-insensitive lookup, the way Starlette gives it to the router."""
    lowered = {key.lower(): value for key, value in values.items()}
    return lambda name: lowered.get(name.lower())


async def _provision(db_session, tenant, *, provider=PMSProvider.BEDS24, secret=SECRET) -> str:
    token = generate_webhook_token()
    await SqlAlchemyWebhookEndpointRepository(db_session).upsert(
        tenant.id,
        WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            provider=provider,
            token_hash=hash_webhook_token(token),
            header_name=HEADER_NAME,
            header_secret=encrypt(secret),
        ),
    )
    await db_session.flush()
    return token


async def _rows(db_session) -> int:
    return (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()


# --- The happy path (R1.1, R1.8) ---


@pytest.mark.asyncio
async def test_a_valid_notice_is_queued_against_the_resolved_tenant(
    db_session, tenant_a
) -> None:
    """R1.1: `processed=FALSE`, the provider, the event type and the tenant the TOKEN resolved.

    The tenant is asserted explicitly because it is the one field no part of the request supplies —
    it comes from the stored endpoint, which is what makes a forged `tenant_id` impossible.
    """
    token = await _provision(db_session, tenant_a)

    event_id = await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload=BODY,
        now=utc_now(),
    )

    stored = (
        await db_session.execute(
            text(
                "SELECT tenant_id, provider, event_type, processed, processed_at, error "
                "FROM webhook_events WHERE id = :id"
            ),
            {"id": str(event_id)},
        )
    ).one()
    assert stored.tenant_id == tenant_a.id
    assert stored.provider == PMSProvider.BEDS24.value
    assert stored.event_type == "booking.modified"
    assert stored.processed is False
    assert stored.processed_at is None
    assert stored.error is None


@pytest.mark.asyncio
async def test_the_provider_segment_is_case_insensitive(db_session, tenant_a) -> None:
    """The route carries `beds24`; the enum spells it `BEDS24`."""
    token = await _provision(db_session, tenant_a)

    assert await _use_case(db_session).execute(
        provider="BeDs24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload=BODY,
        now=utc_now(),
    )


@pytest.mark.asyncio
async def test_the_header_lookup_is_case_insensitive(db_session, tenant_a) -> None:
    """HTTP header names are case-insensitive; a provider may send any casing."""
    token = await _provision(db_session, tenant_a)

    assert await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{"x-beds24-secret": SECRET}),
        payload=BODY,
        now=utc_now(),
    )


@pytest.mark.asyncio
async def test_a_body_without_a_recognisable_event_type_is_still_recorded(
    db_session, tenant_a
) -> None:
    """`event_type` is NOT NULL, and discarding a real notice over a missing label would be worse.

    The body is an advisory (D13), so the label is for an operator reading the queue, never for
    the job to branch on.
    """
    token = await _provision(db_session, tenant_a)

    event_id = await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload={"nothing": "recognisable"},
        now=utc_now(),
    )

    stored = (
        await db_session.execute(
            text("SELECT event_type FROM webhook_events WHERE id = :id"), {"id": str(event_id)}
        )
    ).scalar_one()
    assert stored == UNKNOWN_EVENT_TYPE


@pytest.mark.asyncio
async def test_an_absurdly_long_event_type_cannot_abort_the_insert(
    db_session, tenant_a
) -> None:
    """The value comes from an anonymous caller and the column is `String(200)`.

    Unbounded, a 10 KB label would raise inside the driver and take down the transaction that was
    recording the notice — a write the caller controls, turned into a denial of the whole queue.
    """
    token = await _provision(db_session, tenant_a)

    event_id = await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload={"event": "x" * 10_000},
        now=utc_now(),
    )

    stored = (
        await db_session.execute(
            text("SELECT event_type FROM webhook_events WHERE id = :id"), {"id": str(event_id)}
        )
    ).scalar_one()
    assert len(stored) == 200


@pytest.mark.parametrize(
    "label",
    [
        "4111111111111111",  # a bare PAN under `event`
        "4111 1111 1111 1111",  # the way it is printed; the shape stops at the first space
        "card4111111111111111",  # well-shaped name, PAN glued to it
        "4111111111111111 booking.modified",  # a real label hiding behind one
    ],
)
@pytest.mark.asyncio
async def test_a_card_number_cannot_ride_into_the_label_column(
    db_session, tenant_a, label
) -> None:
    """`webhook_events.event_type` is a rule 11 sink too, and it was the one nobody had claimed.

    The column reads like an enum and is filled from whatever the body puts under
    `event`/`type`/`action` — so it was a 200-character free-text column written from outside, and
    `scrub_card_data` could not help: those keys are not card-shaped, so a denylist has nothing to
    look at. Rule 13(a) kills cardholder data before **anything** persists it, and a diagnostic
    label is a thing.

    Closed structurally, not by denylist: a label is a name, and none of these four are. The last
    two are the ones a shape check alone would have let through — a prefix search would have
    recorded `booking.modified` for a value that is a PAN, and a bare shape check would have taken
    `card4111111111111111` whole.
    """
    token = await _provision(db_session, tenant_a)

    event_id = await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload={"event": label},
        now=utc_now(),
    )

    stored = (
        await db_session.execute(
            text("SELECT event_type FROM webhook_events WHERE id = :id"), {"id": str(event_id)}
        )
    ).scalar_one()
    assert stored == UNKNOWN_EVENT_TYPE
    assert "4111" not in stored


@pytest.mark.asyncio
async def test_a_provider_vocabulary_with_digits_in_it_still_works(db_session, tenant_a) -> None:
    """The other half of the rule above: rejecting digits outright would have been wrong.

    `beds24` is a provider name with digits in it, so the label rule has to admit them and draw the
    line at a **run** long enough to be a card — deliberately far below the 13 that
    `free_text.py` uses for prose, because a label has no false-positive budget to protect.
    """
    token = await _provision(db_session, tenant_a)

    event_id = await _use_case(db_session).execute(
        provider="beds24",
        token=token,
        get_header=_headers(**{HEADER_NAME: SECRET}),
        payload={"event": "beds24.booking.modified"},
        now=utc_now(),
    )

    stored = (
        await db_session.execute(
            text("SELECT event_type FROM webhook_events WHERE id = :id"), {"id": str(event_id)}
        )
    ).scalar_one()
    assert stored == "beds24.booking.modified"


# --- Every failure is the same failure (R1.2, R1.3, R1.6, D4) ---


@pytest.mark.asyncio
async def test_the_four_ways_to_fail_are_indistinguishable(db_session, tenant_a) -> None:
    """R1.2, R1.3 and R1.6 in one place, because the requirement is that they cannot be told apart.

    Asserted as one test deliberately: four separate tests would each pass against an
    implementation that raised four *different* exceptions, which is precisely the oracle D4
    closes. What matters is that the same class, with the same message, comes out of all four.
    """
    good = await _provision(db_session, tenant_a)
    use_case = _use_case(db_session)

    attempts = {
        "unknown token": (
            "beds24",
            generate_webhook_token(),
            _headers(**{HEADER_NAME: SECRET}),
        ),
        "unknown provider": ("octorate", good, _headers(**{HEADER_NAME: SECRET})),
        "missing header": ("beds24", good, _headers()),
        "wrong header": ("beds24", good, _headers(**{HEADER_NAME: "not-it"})),
    }

    raised = {}
    for label, (provider, token, get_header) in attempts.items():
        with pytest.raises(WebhookAuthenticationError) as caught:
            await use_case.execute(
                provider=provider,
                token=token,
                get_header=get_header,
                payload=BODY,
                now=utc_now(),
            )
        raised[label] = str(caught.value)

    assert len(set(raised.values())) == 1, raised
    assert await _rows(db_session) == 0


@pytest.mark.asyncio
async def test_a_token_minted_for_one_provider_does_not_authenticate_another(
    db_session, tenant_a
) -> None:
    """Otherwise `webhook_events.provider` becomes a column the caller chooses."""
    token = await _provision(db_session, tenant_a, provider=PMSProvider.BEDS24)

    with pytest.raises(WebhookAuthenticationError):
        await _use_case(db_session).execute(
            provider="channex",
            token=token,
            get_header=_headers(**{HEADER_NAME: SECRET}),
            payload=BODY,
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_one_tenants_secret_does_not_authenticate_anothers_token(
    db_session, tenant_a, tenant_b
) -> None:
    """The per-tenant secret of rule 12(a), stated as the attack it prevents.

    A tenant who legitimately holds their own secret must not be able to post as their neighbour
    by pairing it with the neighbour's route.
    """
    theirs = await _provision(db_session, tenant_b, secret="theirs")
    await _provision(db_session, tenant_a, secret="mine")

    with pytest.raises(WebhookAuthenticationError):
        await _use_case(db_session).execute(
            provider="beds24",
            token=theirs,
            get_header=_headers(**{HEADER_NAME: "mine"}),
            payload=BODY,
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_a_row_that_cannot_be_decrypted_looks_like_an_unknown_token(
    db_session, tenant_a
) -> None:
    """A broken row authenticates nobody, and must not say so (D4).

    Surfacing `SecretDecryptionError` here would answer an anonymous caller with a `500`, telling
    them this exact route is real and its material is damaged.
    """
    token = generate_webhook_token()
    await db_session.execute(
        text(
            "INSERT INTO webhook_endpoints "
            "(id, tenant_id, provider, token_hash, header_name, header_secret_encrypted) "
            "VALUES (:id, :t, 'BEDS24', :h, :n, :s)"
        ),
        {
            "id": str(uuid.uuid4()),
            "t": str(tenant_a.id),
            "h": hash_webhook_token(token),
            "n": HEADER_NAME,
            "s": "not-ciphertext-at-all",
        },
    )
    await db_session.flush()

    with pytest.raises(WebhookAuthenticationError):
        await _use_case(db_session).execute(
            provider="beds24",
            token=token,
            get_header=_headers(**{HEADER_NAME: SECRET}),
            payload=BODY,
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_nothing_is_written_when_authentication_fails(db_session, tenant_a) -> None:
    """R1.2 and R1.3 both say "sin escribir nada", and it is worth its own assertion.

    A receiver that queued first and authenticated afterwards would let an anonymous caller fill
    the table, which is the amplifier rule 12 exists to prevent.
    """
    await _provision(db_session, tenant_a)

    with pytest.raises(WebhookAuthenticationError):
        await _use_case(db_session).execute(
            provider="beds24",
            token=generate_webhook_token(),
            get_header=_headers(**{HEADER_NAME: SECRET}),
            payload=BODY,
            now=utc_now(),
        )

    assert await _rows(db_session) == 0


# --- Constant time (R1.4) ---


def test_the_comparison_is_constant_time_and_not_an_equality() -> None:
    """R1.4 names the mechanism, so the test reads the mechanism.

    A behavioural test cannot distinguish `==` from `compare_digest` — both return the same
    booleans — and timing assertions are flaky by nature. What is checkable, and what actually
    fails if someone "simplifies" it, is that the source uses `hmac.compare_digest`.
    """
    import inspect

    from app.integrations.domain import webhook_auth

    source = inspect.getsource(webhook_auth.secrets_match)

    assert "hmac.compare_digest" in source
    assert "==" not in source.split('"""')[-1]
