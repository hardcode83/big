"""Beds24 mapping and adapter, against the payload captured from the real API.

Fed by `tests/integrations/fixtures/beds24/bookings.json` rather than hand-written dicts: the
provider's real field names are not the ones its documentation implies, and a synthetic fixture
would preserve the mistake. No network (R2.6) — the HTTP layer is `httpx.MockTransport`.

**One honest limitation, and it is recorded rather than papered over.** The captured booking is
`confirmed`; there is no captured *modified* or *cancelled* one, because producing them needs
the measurement account and nobody had the credential when this was written (`BLOCKED.md`, item
4). The tests that need those states derive them from the real element with explicit overrides
through `_derived`, which is weaker evidence than a capture and says so at the call site. Task
1.4 replaces them.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.infrastructure.beds24.adapter import (
    NO_REFERENCE,
    Beds24Adapter,
    _beds24_instant,
    _element_reference,
    _skip_reason,
)
from app.integrations.infrastructure.beds24.client import Beds24Client
from app.integrations.infrastructure.beds24.mapping import (
    UnmappableField,
    is_blocked_dates,
    to_reservation_dto,
)
from app.integrations.infrastructure.card_data import CARD_DATA_REMOVED
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from tests.integrations.conftest import beds24_fixture

SINCE = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def beds24_booking() -> dict:
    """The one real booking element in the captured collection."""
    return beds24_fixture("bookings")["payload"]["data"][0]


def _derived(**overrides) -> dict:
    """The real element with fields overridden — **weaker evidence than a capture**.

    Used only for booking states the measurement account has not produced yet (modified,
    cancelled, blocked dates). It is a derivation from a real payload, not an invention, and
    task 1.4 replaces its users with captures of the real thing.
    """
    return beds24_booking() | overrides


# --- Identity and shape (R2) -------------------------------------------------------------------


def test_the_provider_id_is_what_identifies_a_reservation():
    """Idempotency by `(tenant_id, external_pms_id)` rests on this, and it must survive the
    whole create -> modify -> cancel cycle, which is what makes the modification window useful.

    Not `apiReference` (empty on API-created bookings) and not `masterId` (groups a multi-room
    booking, so not unique per reservation).
    """
    assert to_reservation_dto(beds24_booking()).external_id == "90923575"


def test_the_property_is_identified_by_property_id():
    """Design D11 / OQ2: the operating contract is one dwelling = one Beds24 property."""
    assert to_reservation_dto(beds24_booking()).property_external_id == "345754"


def test_dates_and_occupancy_map_from_the_real_field_names():
    dto = to_reservation_dto(beds24_booking())

    assert dto.check_in_date.isoformat() == "2026-09-03"
    assert dto.check_out_date.isoformat() == "2026-09-05"
    assert dto.adults == 1
    assert dto.children == 0
    assert dto.gross_amount == Decimal("0")


def test_absent_provider_fields_become_none_not_invented_values():
    """MEASURED: `arrivalTime` is an empty string, and Beds24 has no departure hour at all."""
    dto = to_reservation_dto(beds24_booking())

    assert dto.check_in_time is None
    assert dto.check_out_time is None


def test_the_currency_falls_back_because_the_provider_sends_none():
    """EXTERNAL_DEPENDENCY: none of the 73 fields names a currency — it lives on the account."""
    assert "currency" not in beds24_booking()
    assert to_reservation_dto(beds24_booking()).currency == "EUR"


# --- Status and channel (R2) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("confirmed", ReservationStatus.CONFIRMED),
        ("new", ReservationStatus.CONFIRMED),
        ("request", ReservationStatus.PENDING),
        ("inquiry", ReservationStatus.PENDING),
        ("cancelled", ReservationStatus.CANCELLED),
    ],
)
def test_every_beds24_status_translates_to_our_vocabulary(raw, expected):
    """`parse_ingested` RAISES on an unknown value, so a missing entry here means a sync that
    imports zero reservations while reporting every one as a failed row."""
    dto = to_reservation_dto(_derived(status=raw))

    assert ReservationStatus.parse_ingested(dto.status) is expected


def test_an_unknown_status_is_passed_through_untranslated_so_the_row_is_reported():
    """Deliberately asymmetric with the channel below: a status drives the
    `PropertyStateMachine`, and guessing one means driving a real property into the wrong state.
    """
    dto = to_reservation_dto(_derived(status="teleported"))

    assert dto.status == "teleported"
    with pytest.raises(Exception):
        ReservationStatus.parse_ingested(dto.status)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("direct", ReservationChannel.DIRECT),
        ("airbnb", ReservationChannel.AIRBNB),
        ("booking", ReservationChannel.BOOKING),
        ("expedia", ReservationChannel.EXPEDIA),
        ("something-new", ReservationChannel.OTHER),
    ],
)
def test_an_unknown_channel_falls_back_instead_of_discarding_the_reservation(raw, expected):
    """A channel drives nothing, so an unmapped one must not cost a valid reservation."""
    dto = to_reservation_dto(_derived(channel=raw))

    assert ReservationChannel.parse(dto.channel) is expected


# --- Rule 13 (R4) --------------------------------------------------------------------------------


def test_the_payment_token_fields_do_not_reach_the_dto():
    """MEASURED: Beds24 carries `stripeToken` and `pcibookingToken`. They are `null` on the
    measurement account, which has no channels and therefore no payments — and present in the
    schema, so rule 13 applies before the account that HAS payments arrives."""
    element = _derived(stripeToken="tok_live_4111111111111111", pcibookingToken="pci_x")

    raw = to_reservation_dto(element).raw_payload

    assert raw["stripeToken"] == CARD_DATA_REMOVED
    assert raw["pcibookingToken"] == CARD_DATA_REMOVED
    assert "4111111111111111" not in json.dumps(raw)


def test_the_free_text_fields_do_not_reach_raw_payload():
    """`OPAQUE_BRANCHES` — a key-only denylist cannot see inside a string, and these are where a
    guest or an operator can type anything (`docs/beds24-spike.md` names `custom1..10`)."""
    element = _derived(comments="card 4111111111111111", custom1="cvv 737", notes="x")

    raw = to_reservation_dto(element).raw_payload

    assert "4111111111111111" not in json.dumps(raw)
    assert "737" not in json.dumps(raw)


def test_the_business_fields_still_travel_in_raw_payload():
    """Scrubbing must not gut the field: its purpose is showing the unexpected."""
    raw = to_reservation_dto(beds24_booking()).raw_payload

    assert raw["id"] == 90923575
    assert raw["arrival"] == "2026-09-03"
    assert raw["roomId"] == 713992


# --- Blocked dates (design D10) -------------------------------------------------------------------


def test_a_calendar_block_is_recognised():
    """Beds24 serves owner blocks from the same endpoint under `status: black`."""
    assert is_blocked_dates(_derived(status="black"))
    assert not is_blocked_dates(beds24_booking())


# --- Unmappable rows (R2.4) -------------------------------------------------------------------------


def test_a_missing_date_names_the_field_and_never_its_content():
    """Rule 13(a): `date.fromisoformat` puts the offending value in its own message, and the
    adapter folds that text into the report an operator reads."""
    with pytest.raises(UnmappableField) as caught:
        to_reservation_dto(_derived(arrival={"card_number": "4111111111111111"}))

    assert "arrival" in str(caught.value)
    assert "4111111111111111" not in str(caught.value)


def test_the_skip_reason_is_a_closed_vocabulary():
    assert _skip_reason(UnmappableField("arrival")) == "UnmappableField: arrival"
    assert _skip_reason(ValueError("cvv is 737")) == "ValueError"


@pytest.mark.parametrize(
    "element",
    [
        {"id": {"card_number": "4111111111111111"}},
        {"id": "x" * 500},
        {"id": "9092\n beds24: cvv=737"},
        {"id": None},
        "not a dict",
    ],
)
def test_the_reference_never_carries_a_payload_or_forges_a_log_line(element):
    reference = _element_reference(element)

    assert len(reference) <= 64
    assert "\n" not in reference
    assert "4111111111111111" not in reference


def test_a_usable_id_is_kept():
    assert _element_reference({"id": 90923575}) == "90923575"
    assert _element_reference({}) == NO_REFERENCE


# --- The adapter over the transport (R2) -------------------------------------------------------------


def _adapter(handler, **kwargs):
    client = Beds24Client(
        refresh_token="refresh-secret",
        max_pages=5,
        page_limit=100,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    return Beds24Adapter(client)


def _serving(rows, *, capture=None):
    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return httpx.Response(200, json={"token": "access", "expiresIn": 86400})
        if capture is not None:
            capture.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={"success": True, "pages": {"nextPageExists": False}, "data": rows},
            headers={"X-Request-Cost": "1"},
        )

    return handler


@pytest.mark.asyncio
async def test_the_window_is_asked_for_by_modification_date():
    """R2.1 — the whole reason this adapter is not a copy of the Channex one.

    Channex can only filter on `inserted_at`, so a booking modified or cancelled after `since`
    is invisible to it. This asks by modification date, which is what makes a cancellation
    visible at all.
    """
    seen = []

    await _adapter(_serving([], capture=seen)).list_reservations(SINCE)

    assert seen[0]["modifiedFrom"] == "2026-08-01T09:00:00Z"


@pytest.mark.asyncio
async def test_a_property_filter_narrows_the_request():
    seen = []

    await _adapter(_serving([], capture=seen)).list_reservations(SINCE, "345754")

    assert seen[0]["propertyId"] == "345754"


@pytest.mark.asyncio
async def test_a_cancelled_reservation_comes_back_through_the_window():
    """The behaviour R2.1 exists for, at the adapter's own level."""
    cancelled = _derived(status="cancelled", cancelTime="2026-08-05T10:00:00Z")

    fetched = await _adapter(_serving([cancelled])).list_reservations(SINCE)

    [dto] = fetched.reservations
    assert ReservationStatus.parse_ingested(dto.status) is ReservationStatus.CANCELLED
    assert dto.external_id == "90923575"


@pytest.mark.asyncio
async def test_one_unmappable_element_does_not_cost_the_whole_page():
    """R2.4 — mapping happens here, before any row reaches the ingestor's per-row guard, so a
    single malformed booking used to abort an entire sync on the Channex twin."""
    good = beds24_booking()
    bad = _derived(id=999, arrival=None)

    fetched = await _adapter(_serving([good, bad])).list_reservations(SINCE)

    assert [dto.external_id for dto in fetched.reservations] == ["90923575"]
    assert [f.external_id for f in fetched.failures] == ["999"]
    assert fetched.failures[0].reason == "UnmappableField: arrival"


@pytest.mark.asyncio
async def test_calendar_blocks_are_excluded_and_counted(caplog):
    """Design D10 — not a reservation and not a failure, but never silent either."""
    with caplog.at_level("INFO"):
        fetched = await _adapter(
            _serving([beds24_booking(), _derived(id=1, status="black")])
        ).list_reservations(SINCE)

    assert len(fetched.reservations) == 1
    assert fetched.failures == []
    assert any("calendar block" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_log_line_for_an_unmappable_row_carries_no_payload(caplog):
    with caplog.at_level("WARNING"):
        await _adapter(
            _serving([_derived(id=999, arrival=None, email="ana@example.com")])
        ).list_reservations(SINCE)

    [line] = [r.getMessage() for r in caplog.records if "could not map" in r.getMessage()]
    assert "999" in line
    assert "ana@example.com" not in line


@pytest.mark.asyncio
async def test_an_unknown_id_is_none_rather_than_an_error():
    """The port promises `None`, and `MockPMSAdapter` behaves that way."""
    assert await _adapter(_serving([])).get_reservation("nope") is None


@pytest.mark.asyncio
async def test_a_known_id_returns_its_reservation():
    dto = await _adapter(_serving([beds24_booking()])).get_reservation("90923575")

    assert dto is not None
    assert dto.external_id == "90923575"


@pytest.mark.asyncio
async def test_asking_for_a_calendar_block_by_id_returns_none():
    """Returning a fabricated stay for an id that names a block would be worse than nothing."""
    blocked = _derived(status="black")

    assert await _adapter(_serving([blocked])).get_reservation("90923575") is None


@pytest.mark.asyncio
async def test_a_provider_failure_travels_as_the_ports_own_error():
    """No caller learns that Beds24 is reached over HTTP."""

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return httpx.Response(200, json={"token": "access"})
        return httpx.Response(500)

    with pytest.raises(PmsUnavailableError):
        await _adapter(handler).list_reservations(SINCE)


# --- Timestamps ------------------------------------------------------------------------------------


def test_a_naive_datetime_is_assumed_to_be_utc():
    """Every caller builds it with `datetime.now(UTC)`; refusing one would fail a sync over a
    detail the operator cannot see."""
    assert _beds24_instant(datetime(2026, 8, 1, 9, 0)) == "2026-08-01T09:00:00Z"


def test_an_aware_datetime_is_converted_to_utc():
    from datetime import timedelta, timezone

    madrid = datetime(2026, 8, 1, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    assert _beds24_instant(madrid) == "2026-08-01T09:00:00Z"
