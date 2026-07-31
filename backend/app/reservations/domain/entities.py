import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.guests.domain.enums import LegalRegistrationStatus
from app.reservations.domain.enums import (
    PaymentStatus,
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)
from app.reservations.domain.exceptions import ReservationValidationError

# What `PATCH /reservations/{id}` is allowed to touch (R1.5). Everything else is either
# derived (`nights`, `total_guests`), owned by another module (`access_status`,
# `legal_registration_status`) or immutable identity (`id`, `tenant_id`, `property_id`,
# `external_pms_id`). Keeping the list here rather than in the schema means the rule
# holds for the CSV/PMS ingest paths too, not just for the HTTP one.
UPDATABLE_FIELDS = frozenset(
    {
        "guest_id",
        "channel",
        "status",
        "check_in_date",
        "check_out_date",
        "check_in_time",
        "check_out_time",
        "adults",
        "children",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "currency",
        "payment_status",
        "cleaning_required",
        "special_requests",
        "internal_notes",
    }
)

# Free-text fields whose CONTENT never reaches the timeline (R2.2, panel de seguridad de
# la sección 2). R2.2 asks the event to record "los campos cambiados" — the fields, not
# their values — and `timeline_events` is append-only by rule ("nunca se editan eventos
# pasados", `steering/architecture.md`), so anything written there cannot be redacted
# later. A manager pasting a door code or a WiFi password into `internal_notes` would
# otherwise leave it in clear text, permanently, in the one store designed never to be
# edited — while rules 3 and 4 of `steering/security.md` require exactly those values to
# be encrypted and masked everywhere else.
OPAQUE_IN_TIMELINE = frozenset({"special_requests", "internal_notes"})

# What an ingest run (PMS sync or CSV import) may overwrite on a reservation it already knows
# (R3.2). A subset of `UPDATABLE_FIELDS`: only the fields the **provider** owns.
#
# `internal_notes` is ours — a manager's note must not be wiped by the next sync — and
# `payment_status`/`cleaning_required` are operational decisions taken on this side. `status` IS
# included, because a cancellation upstream has to reach us.
#
# Lives in the domain rather than in the ingest use case where it started (the architecture
# review of the feature moved it): which fields an external system is allowed to own is a
# business rule, not orchestration.
INGEST_OWNED_FIELDS = frozenset(
    {
        "guest_id",
        "channel",
        "status",
        "check_in_date",
        "check_out_date",
        "check_in_time",
        "check_out_time",
        "adults",
        "children",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "currency",
        "special_requests",
    }
)
assert INGEST_OWNED_FIELDS <= UPDATABLE_FIELDS  # an ingest can never exceed what a PATCH may do


@dataclass
class Reservation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    channel: ReservationChannel
    check_in_date: date
    check_out_date: date
    nights: int
    created_at: datetime
    updated_at: datetime
    guest_id: uuid.UUID | None = None
    external_pms_id: str | None = None
    external_channel_id: str | None = None
    status: ReservationStatus = ReservationStatus.PENDING
    check_in_time: time | None = None
    check_out_time: time | None = None
    adults: int = 1
    children: int = 0
    total_guests: int = 1
    gross_amount: Decimal | None = None
    ota_commission: Decimal | None = None
    net_amount: Decimal | None = None
    currency: str = "EUR"
    payment_status: PaymentStatus = PaymentStatus.PENDING
    access_status: ReservationAccessStatus = ReservationAccessStatus.PENDING
    legal_registration_status: LegalRegistrationStatus = LegalRegistrationStatus.NOT_REQUIRED
    cleaning_required: bool = True
    special_requests: str | None = None
    internal_notes: str | None = None

    def __post_init__(self) -> None:
        """Only the stay-length invariant, on purpose.

        This runs on every reconstruction from the database too, so validating more
        here would make an already-stored row unreadable instead of correctable — the
        occupancy rules belong to the paths that accept input (`create`,
        `update_details`). The date rule predates this change and stays.
        """
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")

    @classmethod
    def create(
        cls,
        *,
        id: uuid.UUID,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        channel: ReservationChannel,
        check_in_date: date,
        check_out_date: date,
        now: datetime,
        adults: int = 1,
        children: int = 0,
        **optional: Any,
    ) -> "Reservation":
        """The only way a reservation comes into existence (R1.2).

        `nights` and `total_guests` are derived here and never accepted from a caller:
        a client that could send them could contradict the dates it also sent, and then
        every consumer of the timeline would have to decide which one to believe.
        """
        _validate_occupancy(adults=adults, children=children)
        _validate_dates(check_in_date=check_in_date, check_out_date=check_out_date)
        return cls(
            id=id,
            tenant_id=tenant_id,
            property_id=property_id,
            channel=channel,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights=(check_out_date - check_in_date).days,
            created_at=now,
            updated_at=now,
            adults=adults,
            children=children,
            total_guests=adults + children,
            **optional,
        )

    def update_details(self, changes: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        """Apply the present fields and report what actually changed (R1.5, R2.2).

        The return value is the `metadata` of the `RESERVATION_UPDATED` timeline event:
        `{field: {"from": ..., "to": ...}}`, already JSON-serialisable. A field sent with
        the value it already had is not a change and does not appear — which is what
        makes an effectively-empty PATCH emit no event at all.

        Free-text fields report `{"changed": True}` and never their content: see
        `OPAQUE_IN_TIMELINE` for why the timeline must not become the one place where a
        door code lives in clear text for ever.

        Validation runs on the RESULT, not on the incoming fields: moving only
        `check_in_date` can invalidate a stay whose `check_out_date` was fine before,
        and checking the fields in isolation would let that through.
        """
        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise ReservationValidationError(
                f"Fields cannot be updated: {', '.join(sorted(unknown))}"
            )

        applied: dict[str, Any] = {}
        for field_name, new_value in changes.items():
            old_value = getattr(self, field_name)
            if old_value == new_value:
                continue
            applied[field_name] = (
                {"changed": True}
                if field_name in OPAQUE_IN_TIMELINE
                else {"from": _jsonable(old_value), "to": _jsonable(new_value)}
            )
            setattr(self, field_name, new_value)

        if not applied:
            return {}

        _validate_occupancy(adults=self.adults, children=self.children)
        _validate_dates(check_in_date=self.check_in_date, check_out_date=self.check_out_date)
        self.nights = (self.check_out_date - self.check_in_date).days
        self.total_guests = self.adults + self.children
        self.updated_at = now
        return applied

    def cancel(self, *, now: datetime) -> bool:
        """Cancel the reservation; `True` only if this call is what cancelled it (R1.6, R1.7).

        The boolean is the whole point: `DELETE` is idempotent, so the use case needs to
        know whether a `RESERVATION_CANCELLED` event corresponds to something that
        happened. Without it a client retrying a delete would append a cancellation to
        the timeline every time.
        """
        if self.status is ReservationStatus.CANCELLED:
            return False
        self.status = ReservationStatus.CANCELLED
        self.updated_at = now
        return True


def net_amount_from(gross_amount: Decimal | None, ota_commission: Decimal | None) -> Decimal | None:
    """What the host actually receives: gross minus the channel's cut.

    A domain rule, not a mapping detail (the architecture review moved it out of the ingest
    code): PRD §16's `ReservationDTO` carries no `net_amount`, so an import has to derive it,
    and deriving it in one place is what stops the three amounts of PRD §7.7 from
    contradicting each other. No commission means the host keeps the gross.
    """
    if gross_amount is None:
        return None
    if ota_commission is None:
        return gross_amount
    return gross_amount - ota_commission


def _validate_occupancy(*, adults: int, children: int) -> None:
    if adults < 1:
        raise ReservationValidationError("adults must be at least 1")
    if children < 0:
        raise ReservationValidationError("children cannot be negative")


def _validate_dates(*, check_in_date: date, check_out_date: date) -> None:
    if check_out_date <= check_in_date:
        raise ReservationValidationError("check_out_date must be after check_in_date")


def _jsonable(value: Any) -> Any:
    """Values that survive a round trip through the `metadata` JSONB column.

    `date`/`time`/`datetime` become ISO 8601 strings, `Decimal` a string (never a float:
    that would round money), enums their `.value`, UUIDs their canonical form. Anything
    else is returned as-is and, if it is not serialisable, fails loudly at insert time
    rather than being silently coerced here.
    """
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value") and hasattr(type(value), "__members__"):
        return value.value
    return value
