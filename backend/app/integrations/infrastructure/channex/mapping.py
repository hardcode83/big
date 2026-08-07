"""Channex booking payload -> `ReservationDTO` (R2, design D7 and D7 bis).

Every rule here was written against payloads **captured from the real staging API**
(`tests/integrations/fixtures/channex/bookings.json`), not against the documentation. Four of
them contradict what the docs implied, and each is marked below with the reality that forced
it. That contradiction is the deliverable of this change, not an inconvenience.

This module is where Channex's vocabulary dies. The port promises `ReservationDTO` with
`Decimal | None` amounts and `ReservationStatus` names; anything peculiar to this provider is
absorbed here so the domain never learns that Channex exists — which is what lets
`pms-beds24-adapter` add a second provider without touching a single domain module.
"""

from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.domain.dtos import ReservationDTO
from app.integrations.infrastructure.card_data import scrub_card_data

# `ota_name` values Channex reports, mapped to our vocabulary. Anything absent falls to
# `OTHER` rather than raising: `ReservationChannel.parse` rejects unknown values and the
# ingestor turns that into a skipped row, so propagating a new OTA's literal name would
# silently DISCARD valid reservations. `OTHER` imports them with a generic channel instead.
CHANNEL_BY_OTA = {
    "booking.com": "BOOKING",
    "bookingcom": "BOOKING",
    "airbnb": "AIRBNB",
    "expedia": "EXPEDIA",
    # Channex's word for a reservation entered by hand rather than received from a channel.
    "offline": "MANUAL",
    "direct": "DIRECT",
}
UNKNOWN_CHANNEL = "OTHER"

# Channex's own status vocabulary. **Not** ours: `ReservationStatus` has no `new`, and
# `parse_ingested("new")` RAISES — without this table the sync would import zero reservations
# while reporting every one of them as a failed row (measured, design D7 bis §3).
#
# `new` -> `CONFIRMED` because a reservation arriving from an OTA is already accepted; the
# argument is written out in `ReservationStatus.parse_ingested`'s own docstring, which exists
# precisely for feeds like this one.
STATUS_BY_CHANNEX_STATUS = {
    "new": "CONFIRMED",
    "modified": "CONFIRMED",
    "cancelled": "CANCELLED",
}

# NO OTA allowlist here, and the reason is measured. An earlier version kept
# `OTAS_REPORTING_COMMISSION = {"booking.com", "bookingcom", "airbnb"}` on the docs' claim that
# Channex populates `ota_commission` only for those, so a `"0.00"` from one of them had to be a
# genuine zero. **A real Booking.com reservation off the test hotel arrived with
# `ota_commission: "0.00"`** (BDC-6558139322, 2026-08-03), and Booking.com always charges
# commission. The field therefore fails to distinguish "no commission" from "no data" even for
# the OTAs that supposedly report it — the allowlist relocated the ambiguity instead of
# resolving it. See `_ota_commission`.


def to_reservation_dto(element: dict[str, Any]) -> ReservationDTO:
    """Map one `data` element of `GET /bookings` to the port's DTO."""
    attributes = element.get("attributes") or {}
    customer = attributes.get("customer") or {}
    occupancy = attributes.get("occupancy") or {}
    ota_name = (attributes.get("ota_name") or "").strip()

    return ReservationDTO(
        # `unique_id`, never `booking_id` or `revision_id`. It combines the OTA code with the
        # reservation code (`BDC-…`, `OFL-…`) and is stable across revisions, which is what
        # `ReservationIngestor`'s idempotency by `(tenant_id, external_pms_id)` rests on.
        #
        # D7 warned against `system_id` for exactly this reason. Worth recording: `/bookings`
        # has no `system_id` at all — it only appears in `/booking_revisions`, where it is
        # indeed per-revision. The warning was right, about the other collection.
        external_id=str(attributes.get("unique_id") or ""),
        channel=CHANNEL_BY_OTA.get(ota_name.lower(), UNKNOWN_CHANNEL),
        property_external_id=str(attributes.get("property_id") or ""),
        external_channel_id=_text(attributes.get("ota_reservation_code")),
        guest_name=_guest_name(customer),
        guest_email=_text(customer.get("mail")),
        guest_phone=_text(customer.get("phone")),
        check_in_date=_date(attributes.get("arrival_date"), field="arrival_date"),
        check_out_date=_date(attributes.get("departure_date"), field="departure_date"),
        # `arrival_hour`, not `check_in_time` — and it arrives `null` on every captured
        # booking, so the port's optionality is load-bearing rather than decorative.
        check_in_time=_time(attributes.get("arrival_hour")),
        # EXTERNAL_DEPENDENCY: Channex exposes no departure hour on a booking. `None` rather
        # than a guessed check-out time (R2.4).
        check_out_time=None,
        adults=_count(occupancy.get("adults"), default=1),
        children=_count(occupancy.get("children"), default=0),
        gross_amount=_decimal(attributes.get("amount")),
        ota_commission=_ota_commission(ota_name, attributes.get("ota_commission")),
        currency=(attributes.get("currency") or "EUR").upper(),
        status=_status(attributes.get("status")),
        special_requests=_text(attributes.get("notes")),
        # The element as the DTO's docstring requires — when an import produces something
        # unexpected, this is the only way to tell a provider bug from ours — minus its
        # cardholder data, which rule 13 of `steering/security.md` says is DISCARDED at the
        # boundary rather than encrypted (PCI DSS forbids retaining the CVV).
        #
        # This used to pass `element` whole, `guarantee` included, and a test pinned it that
        # way. It was safe only by omission: nothing reads `raw_payload` and no column stores
        # it. Rule 13(b) names this exact field as the trap for the day a change persists it,
        # and `pms-beds24-adapter` is where the omission became a scrubber.
        raw_payload=scrub_card_data(element),
    )


def _ota_commission(ota_name: str, raw: Any) -> Decimal | None:
    """A zero commission is reported as **absent**, whatever the OTA (R2.6, revised).

    Channex never sends `null` here: it sends a string, and `"0.00"` both when there is no
    commission and when there is no data. Two measurements, a day apart in the same account:

    - an `Offline` booking created *without* a commission came back `"0.00"` — expected;
    - a **real Booking.com** reservation came back `"0.00"` too (BDC-6558139322) — not expected,
      because Booking.com always charges commission, and the docs say this field is populated
      precisely for Booking.com and Airbnb.

    So no rule based on WHICH OTA sent it can work. R2.4 forbids a zero that falsely asserts
    there was no commission, and honouring that leaves exactly one option: treat zero as "the
    provider did not tell us". The cost is a genuine zero-commission booking losing its zero —
    acceptable, because `None` means "unknown" and that is true, whereas `0` would be a claim.

    `ota_name` stays in the signature: it is the natural place to special-case a provider that
    someday reports commission honestly, and dropping it would hide that this is a *provider*
    decision rather than a numeric one.
    """
    commission = _decimal(raw)
    if commission is None or commission == 0:
        return None
    return commission


def _status(raw: Any) -> str | None:
    """Translate Channex's status, or hand the original over to be rejected.

    Deliberately asymmetric with the channel above. An unmapped channel becomes `OTHER` and
    the reservation still imports, because a channel drives nothing. An unmapped **status**
    is passed through untranslated so `ReservationStatus.parse_ingested` raises and the
    ingestor reports the row: a status drives the `PropertyStateMachine`, and guessing one
    means driving a real property into the wrong state.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    return STATUS_BY_CHANNEX_STATUS.get(text.lower(), text)


def _guest_name(customer: dict[str, Any]) -> str | None:
    """`customer.name` + `customer.surname`, because the DTO carries one name field."""
    parts = [_text(customer.get("name")), _text(customer.get("surname"))]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class UnmappableField(ValueError):
    """A required field could not be parsed. Names the FIELD and never its content.

    Exists because `date.fromisoformat` puts the offending value in its own message
    (`Invalid isoformat string: '...'`), and the adapter folds the exception text into the skip
    reason that reaches `logger.warning` and the operator's report. Measured by the security and
    QA panels of this change: a booking with `arrival_date` set to a nested object put
    `card_number` and `cvv` in that report, and one set to any string put its content there —
    which rule 13(a) of `steering/security.md` forbids outright ("eliminarlos en el adapter…
    antes de que nada pueda persistirlos, loguearlos o reenviarlos") and R6.4 restates.

    So the original error's message is **discarded, not wrapped**: `raise ... from None`, because
    chaining would carry it into any traceback that reaches a log. The field name is the part an
    operator needs and the part that is safe — combined with the booking id, it says exactly what
    to look at in the provider's panel.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"could not parse required field {field!r}")


def _date(value: Any, *, field: str) -> date:
    """Dates are required by the DTO, so a missing one is a broken row, not a `None`.

    Raising here is correct, but the reason this docstring used to give was **wrong** and the
    QA panel proved it. It claimed `ReservationIngestor` catches per-row failures and reports
    them — it does, but not for this: mapping runs inside `ChannexAdapter.list_reservations`,
    *before* any row reaches the ingestor's per-row `try/except`, so a single malformed booking
    used to abort the entire sync with an unhandled traceback.

    What makes raising safe now is that the adapter catches per element and reports the skip
    (see `adapter.list_reservations`). Do not "fix" this by returning `None`: the DTO's dates are
    not optional, and a reservation without them is not a reservation.

    Raises `UnmappableField`, never the underlying `ValueError`: that one carries the offending
    value in its message. See that class for the measurement that forced this.
    """
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        # `from None` on purpose: the original message holds the provider's value, and chaining
        # would put it back in every traceback this reaches.
        raise UnmappableField(field) from None


def _time(value: Any) -> time | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        # A provider hour we cannot parse is not worth failing a whole reservation over — the
        # date is what the operation runs on.
        return None


def _decimal(value: Any) -> Decimal | None:
    """A finite `Decimal`, or `None`. **Non-finite is rejected, not passed through.**

    `Decimal("NaN")` and `Decimal("Infinity")` construct just fine, so catching only
    `InvalidOperation` let them into the DTO — worse than an invented value, because a `NaN`
    amount poisons every downstream comparison and DB write instead of being visibly absent.
    And `Decimal("sNaN")` made the `commission == 0` test inside `_ota_commission` raise
    `InvalidOperation` **uncaught**, which `get_reservation` (unlike `list_reservations`) has no
    per-element guard to absorb — so a single malformed value broke the `None`-on-unknown-id
    promise R2.2 makes. Found by the feature-scale QA panel, reproduced against the container.
    """
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _count(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
