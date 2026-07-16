import enum


class GuestDocumentType(str, enum.Enum):
    DNI = "DNI"
    NIE = "NIE"
    PASSPORT = "PASSPORT"
    RESIDENCE_CARD = "RESIDENCE_CARD"
    OTHER = "OTHER"


class GuestDocumentStatus(str, enum.Enum):
    NOT_PROVIDED = "NOT_PROVIDED"
    PENDING = "PENDING"
    PROVIDED = "PROVIDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LegalRegistrationStatus(str, enum.Enum):
    """Shared with reservations/ — PRD §7.6 and §7.7 define the identical enum
    on both Guest and Reservation. Owned here (guests/) since it's
    conceptually the guest's legal registration state; reservations/ imports
    it rather than redefining it (see design.md Risks)."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_GUEST_DATA = "PENDING_GUEST_DATA"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
