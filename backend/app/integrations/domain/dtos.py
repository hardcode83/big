"""What an external PMS hands over (PRD §16, R3.1).

The field names are PRD §16's `ReservationDTO` verbatim, including `external_id` rather
than `external_pms_id`: this is the provider's vocabulary, and the translation to ours
happens in the ingest use case. Copying the PRD's shape is what makes the eventual
`OctorateAdapter` a drop-in — if the DTO drifted, every adapter would need its own mapping.

`raw_payload` keeps the provider response **minus its cardholder data and its opaque free-text
branches**. It is not decoration: when an import produces something unexpected, the only way to
tell a provider bug from ours is the original body.

It used to say "untouched", and that stopped being true in `pms-beds24-adapter`: rule 13(b) of
`steering/security.md` names this field as *the* trap, because the day a change persists it,
card data reaches the database and no other rule prevents it. Adapters now pass the element
through `infrastructure/card_data.scrub_card_data` first. The docstring matters more than most
— rule 13(b) quotes it as the reason the field invites keeping the response whole.
"""

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ReservationDTO:
    external_id: str
    channel: str
    property_external_id: str
    check_in_date: date
    check_out_date: date
    external_channel_id: str | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    check_in_time: time | None = None
    check_out_time: time | None = None
    adults: int = 1
    children: int = 0
    gross_amount: Decimal | None = None
    ota_commission: Decimal | None = None
    currency: str = "EUR"
    status: str | None = None
    special_requests: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRow:
    """One row a parser could turn into a `ReservationDTO`, with the line it came from."""

    line: int
    reservation: ReservationDTO


@dataclass(frozen=True)
class RowFailure:
    """One row a parser could NOT use, with the line and the reason a person needs (R4.2)."""

    line: int
    reason: str


@dataclass(frozen=True)
class ParseResult:
    """What a `ReservationCsvParser` returns: what it could read, and what it could not.

    Lives in `domain/` rather than beside the CSV adapter so the port can describe its contract in
    the vocabulary of the domain instead of the vocabulary of one file format — the architecture
    review pointed out that a port whose return type only exists in `infrastructure/` still leaks
    the layer it was meant to hide.
    """

    rows: list[ParsedRow]
    failures: list[RowFailure]


@dataclass(frozen=True)
class PmsRowFailure:
    """One element the PMS returned that the adapter could not turn into a `ReservationDTO`.

    Deliberately NOT `RowFailure`: that one carries a mandatory `line`, which is meaningful for a
    CSV and meaningless for an API response. What identifies the element here is the provider's
    own id — and it is optional, because an element malformed enough to be unmappable may be
    malformed exactly in the field that would name it.

    **The two fields are separate on purpose, and both are constrained.** `reason` carries the
    error class and, at most, the NAME of the field that failed — never the provider id (that is
    `external_id`'s job) and never any value from the payload, which holds guest name, email,
    phone and, per rule 13 of `steering/security.md`, cardholder data. `external_id` carries a
    scalar identifier, bounded and stripped of control characters by the adapter.

    Keeping them apart is what makes the constraint enforceable: an earlier version concatenated
    the id into the reason, and the two could not then be bounded independently — the security
    panel of this change reproduced card data in both fields in turn, first through `reason`,
    then through `external_id` after only the first was fixed.
    """

    external_id: str | None
    reason: str


@dataclass(frozen=True)
class PmsFetchResult:
    """What `PMSAdapter.list_reservations` returns: what it could map, and what it could not.

    Replaces the `unmappable_rows: list[str]` attribute the port used to declare (design D10).
    That attribute was a mutable slot on the adapter, reset per call, which made the report a
    property of the object rather than of the call — two concurrent calls on one adapter would
    interleave their failures, and a caller that forgot to read it dropped rows in silence.

    Widening the return type is the shape `ParseResult` already established for the CSV port, and
    the asymmetry between the two was itself the argument: the same problem had two answers in one
    module.
    """

    reservations: list[ReservationDTO]
    failures: list[PmsRowFailure]
