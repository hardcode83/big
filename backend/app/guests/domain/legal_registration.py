"""When a stay is ready to be reported to SES.Hospedajes (PRD §17, R6.3, design D11).

> ### Datos mínimos requeridos para submission
> `full_name`, `nationality`, `date_of_birth`, `document_type`, `document_number`,
> `document_expiry_date`, `check_in_date`, `check_out_date`

Eight fields, and **they do not all live on the guest**: the last two are the reservation's.
That is the whole reason this is a domain service and not a method on `Guest` —
`steering/backend-architecture.md` puts logic that spans aggregates exactly here, next to
`PropertyStateMachine`.

Pure: no session, no clock, no ciphertext. It is handed a description of what is present and
answers whether the set is complete. **It never sees the document number itself**, only
whether one is stored — which is what keeps the readiness check out of the small list of
places that touch decrypted PII.
"""

from dataclasses import dataclass
from datetime import date

from app.guests.domain.entities import Guest
from app.guests.domain.enums import LegalRegistrationStatus

#: The eight of PRD §17, by the names they carry in this codebase. The two reservation ones
#: are last, in the PRD's own order, so the list can be read against §17 line by line.
REQUIRED_FIELDS: tuple[str, ...] = (
    "full_name",
    "nationality",
    "date_of_birth",
    "document_type",
    "document_number",
    "document_expiry_date",
    "check_in_date",
    "check_out_date",
)


@dataclass(frozen=True)
class LegalRegistrationSubject:
    """What the readiness check is allowed to know.

    `has_document_number` is a **boolean**, deliberately: the check needs to know a number is
    stored, never what it is. A signature taking the value would put the most sensitive field
    in the system into a pure function that has no audit trail behind it.
    """

    full_name: str | None
    nationality: str | None
    date_of_birth: date | None
    document_type: object | None
    has_document_number: bool
    document_expiry_date: date | None
    check_in_date: date | None
    check_out_date: date | None

    @classmethod
    def of(cls, guest: Guest, *, check_in_date: date, check_out_date: date):
        return cls(
            full_name=guest.full_name or None,
            nationality=guest.nationality,
            date_of_birth=guest.date_of_birth,
            document_type=guest.document_type,
            has_document_number=guest.document_number_encrypted is not None,
            document_expiry_date=guest.document_expiry_date,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
        )


def missing_fields(subject: LegalRegistrationSubject) -> tuple[str, ...]:
    """Which of the eight are absent, in PRD §17's order.

    Returned rather than a bare boolean so an operator can be told *what* is missing — the
    whole point of `PENDING_GUEST_DATA` is that somebody has to go and get something.
    """
    present = {
        "full_name": bool(subject.full_name and subject.full_name.strip()),
        "nationality": subject.nationality is not None,
        "date_of_birth": subject.date_of_birth is not None,
        "document_type": subject.document_type is not None,
        "document_number": subject.has_document_number,
        "document_expiry_date": subject.document_expiry_date is not None,
        "check_in_date": subject.check_in_date is not None,
        "check_out_date": subject.check_out_date is not None,
    }
    return tuple(field for field in REQUIRED_FIELDS if not present[field])


def status_for(
    subject: LegalRegistrationSubject, *, current: LegalRegistrationStatus
) -> LegalRegistrationStatus:
    """The status a stay should carry given what is on file (R6.3).

    **Only ever moves between `PENDING_GUEST_DATA` and `READY_TO_SUBMIT`.** A stay already
    `SUBMITTED`, `FAILED` or `MANUAL_REVIEW` is past this question — the submission happened,
    or a person is dealing with it — and recomputing it from field presence would let an edit
    to a guest's phone number silently undo a filing with the police.

    `NOT_REQUIRED` is left alone too: it means nobody has decided this stay needs reporting,
    which is the reconciler's call (PRD §17 step 1), not this function's.
    """
    if current not in (
        LegalRegistrationStatus.PENDING_GUEST_DATA,
        LegalRegistrationStatus.READY_TO_SUBMIT,
    ):
        return current
    return (
        LegalRegistrationStatus.READY_TO_SUBMIT
        if not missing_fields(subject)
        else LegalRegistrationStatus.PENDING_GUEST_DATA
    )
