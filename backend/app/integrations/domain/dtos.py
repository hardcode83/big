"""What an external PMS hands over (PRD §16, R3.1).

The field names are PRD §16's `ReservationDTO` verbatim, including `external_id` rather
than `external_pms_id`: this is the provider's vocabulary, and the translation to ours
happens in the ingest use case. Copying the PRD's shape is what makes the eventual
`OctorateAdapter` a drop-in — if the DTO drifted, every adapter would need its own mapping.

`raw_payload` keeps the untouched provider response. It is not decoration: when an import
produces something unexpected, the only way to tell a provider bug from ours is the
original body.
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
