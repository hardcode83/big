"""No card data survives the receiving boundary (`reservations-webhooks` R4.1-R4.3, R4.5; D7).

`tests/integrations/test_card_data.py` already proves `scrub_card_data` works. What is proved
**here** is different and is the thing that actually protects the column: that the receiver
*calls* it, on the real captured bodies of both providers, and that what lands in
`webhook_events.payload` carries no needle. A scrubber nobody invoked passes every unit test it
has.

The fixtures are the ones already versioned and anonymised at capture time. Running them through
the whole receiver — rather than through the function — is what makes this an integration
assertion about the sink rule 11 names.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from app.core.crypto import encrypt
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.application.webhooks import ReceiveWebhookUseCase
from app.integrations.domain.entities import (
    UNMAPPABLE,
    WebhookEndpoint,
    WebhookEventFailure,
)
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.webhook_auth import (
    generate_webhook_token,
    hash_webhook_token,
)
from app.integrations.infrastructure.card_data import (
    CARD_DATA_REMOVED,
    CARD_NEEDLES,
    OPAQUE_BRANCHES,
    scrub_card_data,
)
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookEventRepository,
)
from tests.auth.conftest import utc_now
from tests.integrations.conftest import beds24_fixture, channex_fixture

HEADER_NAME = "X-Provider-Secret"
SECRET = "paste-me"


def _use_case(db_session) -> ReceiveWebhookUseCase:
    return ReceiveWebhookUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(db_session),
        events=SqlAlchemyWebhookEventRepository(db_session),
        scrub=scrub_card_data,
        uow=SqlAlchemyUnitOfWork(db_session),
    )


async def _receive(db_session, tenant, provider: PMSProvider, payload: dict) -> dict:
    """Put one body through the real receiver and hand back what the DATABASE holds."""
    token = generate_webhook_token()
    await SqlAlchemyWebhookEndpointRepository(db_session).upsert(
        tenant.id,
        WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            provider=provider,
            token_hash=hash_webhook_token(token),
            header_name=HEADER_NAME,
            header_secret=encrypt(SECRET),
        ),
    )
    await db_session.flush()

    event_id = await _use_case(db_session).execute(
        provider=provider.value.lower(),
        token=token,
        get_header=lambda name: SECRET if name.lower() == HEADER_NAME.lower() else None,
        payload=payload,
        now=utc_now(),
    )

    return (
        await db_session.execute(
            text("SELECT payload FROM webhook_events WHERE id = :id"), {"id": str(event_id)}
        )
    ).scalar_one()


def _unredacted(value, path="", found=None) -> set[str]:
    """Paths whose key is card- or opacity-shaped and whose value SURVIVED.

    Keyed on the value, not the key, because that is what the rule governs: `scrub_card_data`
    replaces the value with `CARD_DATA_REMOVED` and keeps the key, which is the structured form
    rule 11 asks for ("el valor no sobrevive en absoluto") and is strictly more useful than
    deleting the key — it distinguishes "the provider did not send this" from "we removed it".
    A first draft of this file asserted the key was gone and failed against correct code.
    """
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, nested in value.items():
            name = str(key)
            here = f"{path}.{name}"
            sensitive = any(needle in name.lower() for needle in CARD_NEEDLES) or (
                name.lower() in OPAQUE_BRANCHES
            )
            if sensitive and nested != CARD_DATA_REMOVED:
                found.add(here)
            _unredacted(nested, here, found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _unredacted(item, f"{path}[{index}]", found)
    return found


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        (PMSProvider.BEDS24, beds24_fixture("bookings")),
        (PMSProvider.BEDS24, beds24_fixture("bookings_modified")),
        (PMSProvider.BEDS24, beds24_fixture("bookings_cancelled")),
        (PMSProvider.CHANNEX, channex_fixture("bookings")),
        (PMSProvider.CHANNEX, channex_fixture("revisions")),
    ],
    ids=["beds24-bookings", "beds24-modified", "beds24-cancelled", "channex-bookings",
         "channex-revisions"],
)
@pytest.mark.asyncio
async def test_no_card_shaped_key_survives_into_the_payload_column(
    db_session, tenant_a, provider, payload
) -> None:
    """R4.1, R4.2: recursive, through lists, fail-closed on a key that matches the pattern."""
    stored = await _receive(db_session, tenant_a, provider, payload)

    assert _unredacted(stored) == set()


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        (PMSProvider.BEDS24, beds24_fixture("bookings")),
        (PMSProvider.CHANNEX, channex_fixture("bookings")),
    ],
    ids=["beds24", "channex"],
)
@pytest.mark.asyncio
async def test_no_opaque_free_text_branch_survives_either(
    db_session, tenant_a, provider, payload
) -> None:
    """The second category, and the one a key-only denylist cannot see.

    `channex-staging-adapter` measured it: `attributes.raw_message` is the OTA's ORIGINAL message,
    which is what the provider parses `guarantee.card_number` **out of**. An element whose
    `guarantee` is neatly redacted can carry the same PAN one key over, in XML. It matches no card
    needle, so only replacing the branch wholesale removes it.
    """
    stored = await _receive(db_session, tenant_a, provider, payload)

    assert _unredacted(stored) == set()


@pytest.mark.asyncio
async def test_a_planted_card_object_is_gone_from_the_column(db_session, tenant_a) -> None:
    """The fixtures are anonymised at capture, so on their own they cannot prove much.

    This plants the exact shape `specs/pms-channex-staging.md` measured on a live account — every
    OTA booking arrives with it — nested inside a list, which is where a non-recursive scrubber
    passes its own unit tests and fails here.
    """
    payload = {
        "event": "booking.created",
        "data": [
            {
                "id": "abc",
                "guarantee": {
                    "card_number": "4111111111111111",
                    "card_type": "visa",
                    "cvv": "737",
                    "cardholder_name": "A Real Person",
                    "expiration_date": "12/2030",
                },
            }
        ],
    }

    stored = await _receive(db_session, tenant_a, PMSProvider.CHANNEX, payload)

    rendered = json.dumps(stored)
    for needle in ("4111111111111111", "737", "A Real Person", "12/2030"):
        assert needle not in rendered
    # The surrounding notice survives: this is a discard of card data, not of the message.
    assert stored["data"][0]["id"] == "abc"


@pytest.mark.asyncio
async def test_the_discard_happens_before_the_row_exists_not_after(
    db_session, tenant_a
) -> None:
    """Rule 13(a) says eliminate, not encrypt and not mask — so there is no "after".

    Asserted by reading the column: an implementation that wrote the raw body and cleaned it in a
    second statement would leave the value recoverable from the WAL and from any replica, and
    would satisfy a test that only checked the final state through the ORM identity map.
    """
    stored = await _receive(
        db_session,
        tenant_a,
        PMSProvider.BEDS24,
        {"event": "booking.new", "card_number": "4111111111111111"},
    )

    assert stored["card_number"] == CARD_DATA_REMOVED
    raw = (
        await db_session.execute(
            text("SELECT payload::text FROM webhook_events ORDER BY received_at DESC LIMIT 1")
        )
    ).scalar_one()
    assert "4111111111111111" not in raw


# --- The other half of rule 11's contract on this table: `error` (R4.3) ---


def test_a_failure_renders_as_a_code_and_a_field_name_only() -> None:
    """R4.3: structured, so the value cannot survive in the text column.

    `error` is the sibling sink of `payload`, and the easier one to get wrong — the natural
    diagnostic message interpolates whatever failed, which is how a PAN dropped from `payload`
    walks back in one column over.
    """
    rendered = WebhookEventFailure(code=UNMAPPABLE, field="guarantee").render()

    assert json.loads(rendered) == {"code": "UNMAPPABLE", "field": "guarantee"}


def test_a_failure_cannot_carry_free_text() -> None:
    """The guarantee is structural: there is no field to put prose in, and the code is closed.

    A writer that wants to explain more has to add a code, which is a visible diff — the same
    mechanism `app/audit/domain/actions.py` uses for `audit_logs.action`.
    """
    with pytest.raises(ValueError):
        WebhookEventFailure(code="could not map booking 4111111111111111")

    assert not any(
        isinstance(getattr(WebhookEventFailure, name, None), str) for name in ("message", "detail")
    )
