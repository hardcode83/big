import enum

from app.reservations.domain.exceptions import ReservationValidationError


class ReservationChannel(str, enum.Enum):
    AIRBNB = "AIRBNB"
    BOOKING = "BOOKING"
    EXPEDIA = "EXPEDIA"
    DIRECT = "DIRECT"
    MANUAL = "MANUAL"
    OTHER = "OTHER"

    @classmethod
    def parse(cls, value: str) -> "ReservationChannel":
        """Translate the channel string an external provider or a CSV supplies.

        Lives in the domain, not in the ingest use case where it started: deciding what counts
        as a known channel is a business rule, and `steering/backend-architecture.md` is
        explicit that "si hay una regla … pertenece a `domain/`". The feature-scale architecture
        review caught it in `application/`.
        """
        if not value or not value.strip():
            raise ReservationValidationError("channel is required")
        try:
            return cls(value.strip().upper())
        except ValueError as error:
            raise ReservationValidationError(f"Unknown channel {value!r}") from error


class ReservationStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CHECKED_IN_ESTIMATED = "CHECKED_IN_ESTIMATED"
    CHECKED_OUT_ESTIMATED = "CHECKED_OUT_ESTIMATED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"

    @classmethod
    def parse_ingested(cls, value: str | None) -> "ReservationStatus":
        """Translate the status of an IMPORTED reservation, defaulting to `CONFIRMED`.

        The default is deliberate, and documented here rather than left implicit in the ingest
        code (the architecture review found it undocumented): a reservation that reaches us from
        a PMS feed or a CSV without a status is a booking somebody already accepted. Defaulting
        to `PENDING` — which is right for one created by hand — would put confirmed stays in the
        state the operation reads as "not agreed yet".
        """
        if value is None or not value.strip():
            return cls.CONFIRMED
        try:
            return cls(value.strip().upper())
        except ValueError as error:
            raise ReservationValidationError(f"Unknown reservation status {value!r}") from error


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    REFUNDED = "REFUNDED"


class ReservationAccessStatus(str, enum.Enum):
    PENDING = "PENDING"
    CREATED_EXTERNAL = "CREATED_EXTERNAL"
    MANUAL_ADDED = "MANUAL_ADDED"
    DELIVERED = "DELIVERED"
    EXPIRED = "EXPIRED"
    NOT_REQUIRED = "NOT_REQUIRED"
