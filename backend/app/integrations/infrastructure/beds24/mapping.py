"""Beds24 booking payload -> `ReservationDTO` (R2, R4, design D11).

Written against the payload **captured from the real API**
(`tests/integrations/fixtures/beds24/bookings.json`), the same discipline
`channex/mapping.py` follows and for the same reason: that change found four rules its
provider's documentation implied wrongly.

This module is where Beds24's vocabulary dies. The port promises `ReservationDTO` with
`Decimal | None` amounts and `ReservationStatus` names, so everything peculiar to this
provider is absorbed here and the domain never learns Beds24 exists.

**A Beds24 booking carries 73 fields.** The ones the mapping reads are listed in
`docs/beds24-spike.md`; the rest travel in `raw_payload`, minus their cardholder data (rule 13
of `steering/security.md`, applied through `card_data.scrub_card_data`).
"""

from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.domain.dtos import ReservationDTO
from app.integrations.infrastructure.card_data import scrub_card_data
from app.integrations.infrastructure.free_text import redact_long_digit_runs

# Beds24's `channel` values, mapped to our vocabulary. Anything absent falls to `OTHER` rather
# than raising: `ReservationChannel.parse` rejects unknown values and the ingestor turns that
# into a skipped row, so propagating a new OTA's literal name would silently DISCARD valid
# reservations. Same asymmetry `channex/mapping.py` fixed — a channel drives nothing.
#
# `direct` is what the provider reports for a booking created through the API, which is the
# only kind the measurement account can produce (`docs/beds24-spike.md`).
CHANNEL_BY_BEDS24_CHANNEL = {
    "direct": "DIRECT",
    "airbnb": "AIRBNB",
    "booking": "BOOKING",
    "booking.com": "BOOKING",
    "bookingcom": "BOOKING",
    "expedia": "EXPEDIA",
    "manual": "MANUAL",
}
UNKNOWN_CHANNEL = "OTHER"

# Beds24's own status vocabulary. `ReservationStatus` has no `new` and no `request`, and
# `parse_ingested` RAISES on an unknown value — without this table a sync would import zero
# reservations while reporting every one as a failed row, which is exactly what
# `channex-staging-adapter` measured for its own provider.
#
# `black` is deliberately ABSENT: it is a calendar block, not a booking. See `is_blocked_dates`.
STATUS_BY_BEDS24_STATUS = {
    "new": "CONFIRMED",
    "confirmed": "CONFIRMED",
    "request": "PENDING",
    "inquiry": "PENDING",
    "cancelled": "CANCELLED",
}

BLOCKED_DATES_STATUS = "black"


def is_blocked_dates(element: dict[str, Any]) -> bool:
    """Whether this element is a calendar block rather than a reservation (design D10).

    Beds24 serves owner blocks from the same `/bookings` endpoint under `status: black`.
    Importing one would create a stay with an invented guest and drive the
    `PropertyStateMachine` on a property nobody booked — `steering/architecture.md` calls the
    state machine the single place transitions happen, and feeding it fiction is worse than
    dropping a row.

    Kept as a predicate the adapter calls rather than a silent branch inside the mapping,
    because the adapter has to COUNT what it excluded. Dropping rows without saying so is the
    failure the rest of this module is built to avoid.
    """
    return str(element.get("status", "")).strip().lower() == BLOCKED_DATES_STATUS


def to_reservation_dto(element: dict[str, Any]) -> ReservationDTO:
    """Map one element of `GET /bookings` to the port's DTO."""
    return ReservationDTO(
        # The provider's numeric `id`, as a string. It is what
        # `ReservationIngestor`'s idempotency by `(tenant_id, external_pms_id)` rests on, and it
        # is stable across modification and cancellation — the same booking keeps its id through
        # the whole cycle, which is what makes the modification window (R2.1) useful at all.
        #
        # NOT `apiReference`, which is empty on API-created bookings, and not `masterId`, which
        # groups a multi-room booking and is therefore not unique per reservation.
        external_id=_text(element.get("id")) or "",
        channel=CHANNEL_BY_BEDS24_CHANNEL.get(
            str(element.get("channel", "")).strip().lower(), UNKNOWN_CHANNEL
        ),
        # `propertyId`, per design D11 and OQ2: the operating contract is one dwelling = one
        # Beds24 property, so this is what an operator stores in `properties.pms_external_id`.
        # If two of our properties ever shared it, `_index_by_external_id` raises
        # `AmbiguousPropertyExternalIdError` rather than adjudicating a booking to the wrong
        # home — the case `application/use_cases.py` documents as becoming reachable with this
        # very change.
        property_external_id=_text(element.get("propertyId")) or "",
        external_channel_id=_text(element.get("apiReference")),
        guest_name=_guest_name(element),
        guest_email=_text(element.get("email")),
        # `mobile` before `phone`: the captured payload carries both, and a mobile is the one
        # that can receive the check-in instructions `access-notifications` will send.
        guest_phone=_text(element.get("mobile")) or _text(element.get("phone")),
        check_in_date=_date(element.get("arrival"), field="arrival"),
        check_out_date=_date(element.get("departure"), field="departure"),
        # MEASURED: `arrivalTime` is an empty string on the captured booking, so the port's
        # optionality is load-bearing rather than decorative.
        check_in_time=_time(element.get("arrivalTime")),
        # EXTERNAL_DEPENDENCY: Beds24 exposes no departure hour on a booking. `None` rather
        # than a guessed check-out time, the same call `channex/mapping.py` made.
        check_out_time=None,
        adults=_count(element.get("numAdult"), default=1),
        children=_count(element.get("numChild"), default=0),
        gross_amount=_decimal(element.get("price")),
        ota_commission=_decimal(element.get("commission")),
        # EXTERNAL_DEPENDENCY: a Beds24 booking carries **no currency field** — the 73 fields of
        # the captured payload include `price`, `deposit`, `tax` and `commission`, and none of
        # them names a currency, which lives on the account/property instead. `EUR` is the DTO's
        # own default and the only currency this portfolio uses; a multi-currency account would
        # need it read from `/properties`, which is a request this sync does not make.
        currency="EUR",
        status=_status(element.get("status")),
        # `comments` is where the guest's own note lands. NOT `custom1`..`custom10`: those are
        # free-text operator fields (`docs/beds24-spike.md`), and NOT `notes`, which is internal.
        #
        # Redacted because this is an EXTERNAL source (design D8). `scrub_card_data` cannot help
        # on the way to this column — it judges keys, and here the whole value is unstructured
        # guest text — so the long-digit-run rule is what keeps a pasted PAN out of a column that
        # persists and that the API returns. Text typed through the authenticated API is left
        # alone; see `free_text.py`.
        special_requests=redact_long_digit_runs(_text(element.get("comments"))),
        # The element as the DTO's docstring requires, minus its cardholder data. Beds24 carries
        # `stripeToken` and `pcibookingToken` — `null` on the measurement account, which has no
        # channels and therefore no payments, but present in the schema. Rule 13 applies even
        # when they arrive empty, because the account that has channels is the one that fills
        # them (`steering/security.md` rule 13, design D9).
        raw_payload=scrub_card_data(element),
    )


def _status(raw: Any) -> str | None:
    """Translate Beds24's status, or hand the original over to be rejected.

    Deliberately asymmetric with the channel above, and the asymmetry is `channex/mapping.py`'s:
    an unmapped channel becomes `OTHER` and the reservation still imports, because a channel
    drives nothing. An unmapped **status** is passed through untranslated so
    `ReservationStatus.parse_ingested` raises and the ingestor reports the row — a status drives
    the `PropertyStateMachine`, and guessing one means driving a real property into the wrong
    state.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    return STATUS_BY_BEDS24_STATUS.get(text.lower(), text)


def _guest_name(element: dict[str, Any]) -> str | None:
    """`firstName` + `lastName`, because the DTO carries one name field."""
    parts = [_text(element.get("firstName")), _text(element.get("lastName"))]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class UnmappableField(ValueError):
    """A required field could not be parsed. Names the FIELD and never its content.

    Exists for the reason `channex/mapping.py`'s twin does, measured there by two review panels:
    `date.fromisoformat` puts the offending value in its own message (`Invalid isoformat string:
    '...'`), and the adapter folds the exception text into the skip reason that reaches a log
    line and the operator's report. Rule 13(a) of `steering/security.md` forbids cardholder data
    from being logged or forwarded, and an element malformed enough to fail here can be
    malformed by carrying an object where a date belongs.

    So the original message is **discarded, not wrapped** — `raise ... from None`, because
    chaining would carry it into any traceback that reaches a log.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"could not parse required field {field!r}")


def _date(value: Any, *, field: str) -> date:
    """Dates are required by the DTO, so a missing one is a broken row, not a `None`.

    Safe to raise because the adapter maps **per element** and reports the skip; do not "fix"
    this by returning `None`, since a reservation without dates is not a reservation.
    """
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
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

    `Decimal("NaN")` and `Decimal("Infinity")` construct just fine, and a `NaN` amount poisons
    every downstream comparison and DB write instead of being visibly absent. Measured against
    the other provider by a QA panel, which is why it is here before anyone hits it.
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
