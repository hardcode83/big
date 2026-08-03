"""Mapping and adapter, against payloads captured from the real Channex staging API.

Fed by `tests/integrations/fixtures/channex/*.json` (task 2.3) rather than by hand-written
dictionaries: the whole point of this change is that the provider's real field names are not
the ones its documentation implies, and a synthetic fixture would have preserved the mistake.

No network (R2.5) — the HTTP layer is driven through `httpx.MockTransport`.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.integrations.infrastructure.channex.adapter import ChannexAdapter, _channex_timestamp
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.channex.mapping import to_reservation_dto
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from tests.integrations.conftest import channex_booking, channex_fixture

BOOKING_COM = "Booking.com"
OFFLINE = "Offline"


# --- Identity and shape (R2.1, task 4.1) ---


def test_external_id_comes_from_unique_id():
    """Idempotency by `(tenant_id, external_pms_id)` rests on this being stable.

    `unique_id` combines the OTA code with the reservation code and survives revisions;
    `booking_id`/`revision_id` do not. Captured values look like `BDC-…` and `OFL-…`.
    """
    element = channex_booking(ota_name=BOOKING_COM)
    dto = to_reservation_dto(element)

    assert dto.external_id == element["attributes"]["unique_id"]
    assert dto.external_id.startswith("BDC-")
    assert dto.external_id not in (
        element["attributes"]["booking_id"],
        element["attributes"]["revision_id"],
    )


def test_system_id_is_absent_from_the_bookings_collection():
    """Design D7 warned against `system_id`; `/bookings` does not even have it.

    It exists in `/booking_revisions`, where it really is per-revision — so the warning was
    right about the other collection. Pinned as a test because if Channex ever adds it here,
    somebody will reach for it.
    """
    assert "system_id" not in channex_booking(ota_name=BOOKING_COM)["attributes"]
    assert "system_id" in channex_fixture("revisions")["data"][0]["attributes"]


def test_property_and_dates_map_from_the_real_field_names():
    dto = to_reservation_dto(channex_booking(ota_name=BOOKING_COM))

    assert dto.property_external_id == "7963f1e3-72f5-4edd-a0fb-199e9b919d26"
    assert dto.check_in_date.isoformat() == "2026-09-15"
    assert dto.check_out_date.isoformat() == "2026-09-18"
    assert dto.currency == "EUR"
    assert dto.gross_amount == Decimal("360.00")
    assert dto.adults == 2
    assert dto.children == 0


def test_raw_payload_keeps_the_element_untouched():
    element = channex_booking(ota_name=BOOKING_COM)
    assert to_reservation_dto(element).raw_payload == element


def test_absent_provider_fields_become_none_not_invented_values():
    """R2.4. `arrival_hour` is null on every captured booking and Channex has no departure
    hour at all, so the port's optionality is doing real work here."""
    dto = to_reservation_dto(channex_booking(ota_name=BOOKING_COM))

    assert dto.check_in_time is None
    assert dto.check_out_time is None


# --- Channel (task 4.2) ---


@pytest.mark.parametrize(
    ("ota_name", "expected"),
    [
        ("Booking.com", ReservationChannel.BOOKING),
        ("BookingCom", ReservationChannel.BOOKING),
        ("Airbnb", ReservationChannel.AIRBNB),
        ("Expedia", ReservationChannel.EXPEDIA),
        ("Offline", ReservationChannel.MANUAL),
    ],
)
def test_known_otas_map_to_our_channel_vocabulary(ota_name, expected):
    element = {"attributes": {**_minimal_attributes(), "ota_name": ota_name}}
    assert ReservationChannel.parse(to_reservation_dto(element).channel) is expected


def test_an_unknown_ota_becomes_other_rather_than_losing_the_reservation():
    """`ReservationChannel.parse` raises on unknown values and the ingestor turns that into a
    skipped row — so propagating the literal would DISCARD valid reservations the day a new
    channel appears."""
    element = {"attributes": {**_minimal_attributes(), "ota_name": "SomeNewOTA2027"}}
    dto = to_reservation_dto(element)

    assert ReservationChannel.parse(dto.channel) is ReservationChannel.OTHER


# --- Commission (R2.6, task 4.3) ---


def test_a_non_zero_commission_is_kept():
    dto = to_reservation_dto(channex_booking(ota_name=BOOKING_COM))
    assert dto.ota_commission == Decimal("54.00")


def test_a_real_booking_com_reservation_reporting_zero_maps_to_none():
    """The measurement that killed the OTA allowlist (R2.6, revised).

    A genuine Booking.com reservation off the test hotel arrived with `ota_commission: "0.00"`,
    and Booking.com always charges commission. So no rule keyed on WHICH OTA sent the value can
    tell a real zero from missing data — the zero has to mean "unknown".
    """
    # Selected by `ota_name`, NOT by `channel_id`. The first version keyed on `channel_id`
    # being populated — the marker that tells an OTA reservation from a CRS one — and that
    # marker is **not durable**: when the shared test hotel's lease expired, Channex deleted
    # the channel and every booking's `channel_id` went to `null`. The committed fixture still
    # has it (captured in time), but a re-capture would have made this test unable to find its
    # own subject.
    real = next(
        row
        for row in channex_fixture("bookings")["data"]
        if (row.get("attributes") or {}).get("ota_name") == "BookingCom"
    )
    assert real["attributes"]["ota_commission"] == "0.00"
    assert to_reservation_dto(real).ota_commission is None


def test_a_non_reporting_ota_gets_none_even_though_channex_sent_zero():
    """The first measured contradiction (design D7 bis §2).

    The Offline booking was created WITHOUT a commission and Channex stored `"0.00"`. This is
    where the ambiguity was first seen; the real Booking.com reservation above is what proved
    the OTA cannot resolve it either. Zero means unknown, full stop.
    """
    element = channex_booking(ota_name=OFFLINE)

    assert element["attributes"]["ota_commission"] == "0.00"
    assert to_reservation_dto(element).ota_commission is None


def test_zero_is_none_for_every_ota_including_the_reporting_ones():
    """Deliberately gives up a genuine zero. `None` says "unknown", which is true; `0` would be
    a claim, and R2.4 forbids that claim."""
    for ota in ("Booking.com", "BookingCom", "Airbnb", "Offline", "Whatever"):
        element = {
            "attributes": {**_minimal_attributes(), "ota_name": ota, "ota_commission": "0.00"}
        }
        assert to_reservation_dto(element).ota_commission is None, ota


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "sNaN", "", "  ", "abc", None])
def test_non_finite_or_unparseable_amounts_become_none_and_never_raise(raw):
    """R2.6/R2.2, from the feature-scale QA panel.

    `Decimal("NaN")` and `Decimal("Infinity")` construct successfully, so an earlier version let
    them straight into the DTO — a `NaN` amount poisons every downstream comparison instead of
    being visibly absent. And `Decimal("sNaN")` made the `== 0` test inside `_ota_commission`
    raise `InvalidOperation` **uncaught**: `get_reservation` has no per-element guard, so one
    malformed value broke the `None`-on-unknown-id promise the port makes.
    """
    element = {
        "attributes": {**_minimal_attributes(), "ota_commission": raw, "amount": raw}
    }
    dto = to_reservation_dto(element)

    assert dto.ota_commission is None
    assert dto.gross_amount is None


@pytest.mark.asyncio
async def test_get_reservation_survives_a_malformed_amount():
    """The path with no per-element guard: it must return a DTO, not raise."""
    element = {
        "type": "booking",
        "id": "x",
        "attributes": {**_minimal_attributes(), "ota_commission": "sNaN"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": element})

    dto = await ChannexAdapter(_client(handler)).get_reservation("TEST-0001")
    assert dto is not None
    assert dto.ota_commission is None


def test_an_unknown_ota_still_keeps_a_non_zero_commission():
    """Changed by the revision: the OTA no longer gates the value, only zero does."""
    element = {
        "attributes": {**_minimal_attributes(), "ota_name": "Whatever", "ota_commission": "9.99"}
    }
    assert to_reservation_dto(element).ota_commission == Decimal("9.99")


# --- Status (R2.7, task 4.6) ---


@pytest.mark.parametrize(
    ("channex_status", "expected"),
    [
        ("new", ReservationStatus.CONFIRMED),
        ("modified", ReservationStatus.CONFIRMED),
        ("cancelled", ReservationStatus.CANCELLED),
    ],
)
def test_channex_statuses_translate_to_our_vocabulary(channex_status, expected):
    """Without this the sync imports ZERO reservations: every captured booking arrives with
    `status: "new"`, and `parse_ingested("new")` raises."""
    element = {"attributes": {**_minimal_attributes(), "status": channex_status}}
    dto = to_reservation_dto(element)

    assert ReservationStatus.parse_ingested(dto.status) is expected


def test_the_captured_bookings_really_carry_status_new():
    assert channex_booking(ota_name=BOOKING_COM)["attributes"]["status"] == "new"


def test_an_unknown_status_is_left_to_fail_loudly():
    """Deliberately asymmetric with the channel: a status drives the PropertyStateMachine, so
    guessing one drives a real property into the wrong state. Better a reported row."""
    from app.reservations.domain.exceptions import ReservationValidationError

    element = {"attributes": {**_minimal_attributes(), "status": "quantum_superposition"}}
    dto = to_reservation_dto(element)

    assert dto.status == "quantum_superposition"
    with pytest.raises(ReservationValidationError):
        ReservationStatus.parse_ingested(dto.status)


# --- Guest data ---


def test_guest_name_joins_name_and_surname():
    dto = to_reservation_dto(channex_booking(ota_name=BOOKING_COM))
    assert dto.guest_name is not None and " " in dto.guest_name
    assert dto.guest_email is not None
    assert dto.guest_phone is not None


def test_a_customer_without_a_surname_still_produces_a_name():
    element = {
        "attributes": {**_minimal_attributes(), "customer": {"name": "Solo", "surname": None}}
    }
    assert to_reservation_dto(element).guest_name == "Solo"


# --- The UTC filter (R2.8, task 4.7) ---


def test_the_timestamp_filter_is_utc_without_an_offset():
    madrid_summer = timezone(timedelta(hours=2))
    moment = datetime(2026, 8, 3, 11, 0, 0, tzinfo=madrid_summer)

    rendered = _channex_timestamp(moment)

    # 11:00+02:00 is 09:00 UTC. Channex compares the wall clock literally, so sending the
    # original string would have skipped everything inserted between 09:00 and 11:00.
    assert rendered == "2026-08-03T09:00:00"
    assert "+" not in rendered and not rendered.endswith("Z")


def test_a_naive_timestamp_is_taken_as_utc_rather_than_refused():
    assert _channex_timestamp(datetime(2026, 8, 3, 9, 0, 0)) == "2026-08-03T09:00:00"


@pytest.mark.asyncio
async def test_list_reservations_sends_the_converted_filter_and_maps_every_row():
    seen: dict[str, str] = {}
    payload = channex_fixture("bookings")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=payload)

    adapter = ChannexAdapter(_client(handler))
    since = datetime(2026, 8, 3, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    rows = await adapter.list_reservations(since)

    assert seen["filter[inserted_at][gte]"] == "2026-08-03T09:00:00"
    assert len(rows) == len(payload["data"])
    assert {row.external_id for row in rows} == {
        row["attributes"]["unique_id"] for row in payload["data"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broken", "label"),
    [
        ({"arrival_date": None}, "missing arrival_date"),
        ({"arrival_date": "not-a-date"}, "malformed arrival_date"),
        ({"occupancy": ["hostile", "shape"]}, "occupancy as a list"),
        ({"customer": "a string, not an object"}, "customer as a string"),
    ],
)
async def test_one_malformed_booking_does_not_take_the_whole_sync_down(broken, label):
    """The QA panel's finding, pinned. A bare list comprehension used to raise out of
    `list_reservations` and lose every good row in the page — surfacing as a raw traceback,
    because `pms_sync.main` catches only `UnknownTenantError` and `PmsUnavailableError`.

    The good row must survive, and the bad one must be **reported, not silently dropped**.
    """
    good = channex_booking(ota_name=BOOKING_COM)
    bad = {
        "type": "booking",
        "id": "bad-one",
        "attributes": {**_minimal_attributes(), "unique_id": "BROKEN-0001", **broken},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"total": 2, "page": 1}, "data": [good, bad]})

    adapter = ChannexAdapter(_client(handler))
    rows = await adapter.list_reservations(datetime.now(UTC))

    assert len(rows) == 1, label
    assert rows[0].external_id == good["attributes"]["unique_id"]
    assert len(adapter.unmappable_rows) == 1, label
    assert "BROKEN-0001" in adapter.unmappable_rows[0]


@pytest.mark.asyncio
async def test_the_skip_reason_never_carries_the_payload():
    """A skip reason is a log line and a CLI message — a plain-text sink. It gets the provider's
    id and the error class, never the booking, which holds guest name, email, phone and address.
    """
    bad = {
        "type": "booking",
        "id": "bad-one",
        "attributes": {
            **_minimal_attributes(),
            "unique_id": "BROKEN-0002",
            "arrival_date": None,
            "customer": {"name": "Ana Real", "mail": "ana.real@gmail.com"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"total": 1, "page": 1}, "data": [bad]})

    adapter = ChannexAdapter(_client(handler))
    await adapter.list_reservations(datetime.now(UTC))

    reported = " ".join(adapter.unmappable_rows)
    assert "BROKEN-0002" in reported
    assert "Ana Real" not in reported
    assert "ana.real@gmail.com" not in reported


@pytest.mark.asyncio
async def test_unmappable_rows_resets_between_calls():
    """Otherwise a second sync inherits the first one's failures and reports them twice."""
    bad = {"type": "booking", "id": "b", "attributes": {"unique_id": "B-1"}}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        data = [bad] if calls["n"] == 1 else []
        return httpx.Response(200, json={"meta": {"total": len(data), "page": 1}, "data": data})

    adapter = ChannexAdapter(_client(handler))
    await adapter.list_reservations(datetime.now(UTC))
    assert len(adapter.unmappable_rows) == 1

    await adapter.list_reservations(datetime.now(UTC))
    assert adapter.unmappable_rows == []


@pytest.mark.asyncio
async def test_list_reservations_scopes_to_one_property_when_asked():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"meta": {"total": 0}, "data": []})

    await ChannexAdapter(_client(handler)).list_reservations(
        datetime.now(UTC), property_external_id="7963f1e3-72f5-4edd-a0fb-199e9b919d26"
    )
    assert seen["filter[property_id]"] == "7963f1e3-72f5-4edd-a0fb-199e9b919d26"


# --- get_reservation (task 4.5) ---


@pytest.mark.asyncio
async def test_get_reservation_returns_none_for_an_unknown_id_like_the_mock_does():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": {"code": "not_found", "title": "Not Found"}})

    assert await ChannexAdapter(_client(handler)).get_reservation("nope") is None


@pytest.mark.asyncio
async def test_get_reservation_maps_the_resource():
    element = channex_booking(ota_name=BOOKING_COM)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/bookings/{element['attributes']['unique_id']}")
        return httpx.Response(200, json={"data": element})

    dto = await ChannexAdapter(_client(handler)).get_reservation(
        element["attributes"]["unique_id"]
    )
    assert dto is not None
    assert dto.external_id == element["attributes"]["unique_id"]


# --- helpers ---


def _client(handler) -> ChannexClient:
    return ChannexClient(
        api_key="test-key",
        base_url="https://staging.channex.io/api/v1",
        max_pages=10,
        page_limit=100,
        transport=httpx.MockTransport(handler),
    )


def _minimal_attributes() -> dict:
    """Only what the DTO requires, so each test varies exactly one thing."""
    return {
        "unique_id": "TEST-0001",
        "property_id": "7963f1e3-72f5-4edd-a0fb-199e9b919d26",
        "arrival_date": "2026-09-15",
        "departure_date": "2026-09-18",
        "currency": "EUR",
        "status": "new",
        "ota_name": "Offline",
    }
