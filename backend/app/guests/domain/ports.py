"""The SES.Hospedajes port of PRD §17 (`access-notifications` design D12).

> NO implementar submission oficial a SES.Hospedajes sin credenciales y proceso legal.
> Implementar la capa operativa completa para que cuando se tengan credenciales, solo haya
> que conectar el adapter real. (PRD §17)

So this interface is the deliverable, and `MockSESHospedajesAdapter` is the only
implementation. PRD §29 lists real submission among the MVP non-goals.

**What lands here when the real one arrives is not just an HTTP client.** ADR 0006 decision 4
picks **Chekin** (~€3.95/property/month, the only evaluated provider covering both halves of
RD 933/2021 by API), and adopting it makes them a **sub-processor of personal data** to whom
`document_number` and date of birth are sent — the PII `steering/security.md` calls the most
sensitive in the system. Before any real integration: a DPA, a retention policy, a check of
what PII actually leaves, and rule 12 for their `PoliceRegistration.*` webhooks, which are a
second unsigned inbound endpoint over police-registration data. None of that is in scope
here, and none of it is made easier by pretending this port is neutral plumbing.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.guests.domain.enums import GuestDocumentType, LegalRegistrationStatus


class SubmissionStatus(str, enum.Enum):
    """What the provider says about a submission it already has.

    ASSUMPTION: names invented — PRD §17 declares `get_submission_status` without naming its
    return values, and Chekin's own vocabulary (`PoliceRegistration.created|complete|error|
    retry_error`) is not adopted here because the port must not take the shape of one
    undecided provider.
    """

    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LegalSubmission:
    """The eight fields of PRD §17, assembled for one stay.

    **The one place the decrypted document number legitimately travels.** Everything else in
    this codebase handles it encrypted or not at all, so this type is deliberately small,
    frozen and built at the last moment inside the submit use case — the shorter its life,
    the fewer places can accidentally persist or log it.
    """

    reservation_id: uuid.UUID
    guest_id: uuid.UUID
    full_name: str
    nationality: str
    date_of_birth: date
    document_type: GuestDocumentType
    document_number: str
    document_expiry_date: date
    check_in_date: date
    check_out_date: date


@dataclass(frozen=True)
class SubmissionResult:
    """The outcome of one submission.

    `error_code` is a closed-vocabulary string and not the provider's message, the same
    discipline `NotificationResult` applies for the same reason: whatever a submission API
    says on failure tends to quote back what was submitted, and here that is a document
    number.
    """

    accepted: bool
    external_id: str | None = None
    error_code: str | None = None


class SESHospedajesAdapter(Protocol):
    async def submit_guest(self, *, submission: LegalSubmission) -> SubmissionResult:
        """Report one stay. Never raises for a rejection — that comes back as a result."""
        ...

    async def get_submission_status(self, external_id: str) -> SubmissionStatus:
        ...


@dataclass(frozen=True)
class LegalRegistrationStay:
    """The part of a reservation the legal registration cares about (design D10).

    A projection and not the `Reservation` entity, for the reason `GuestSummary` exists: the
    aggregate carries `special_requests` and `internal_notes`, and a use case that holds it
    is one edit away from reaching them from a context that has no business with them.
    """

    reservation_id: uuid.UUID
    property_id: uuid.UUID
    guest_id: uuid.UUID | None
    check_in_date: date
    check_out_date: date
    status: LegalRegistrationStatus


class LegalRegistrationStayStore(Protocol):
    """Read and move `reservations.legal_registration_status` (design D10).

    Deliberately **not** `ReservationRepository`: that port serves the reservations aggregate
    and its `save` writes the whole row. This one reaches exactly one column, which is the
    same narrowing `NotificationLogRepository.mark_breached` applies for the same reason —
    the module that owns the legal registration has no business rewriting a booking.
    """

    async def get(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> LegalRegistrationStay | None:
        ...

    async def set_status(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        status: LegalRegistrationStatus,
    ) -> None:
        ...

    async def set_guest(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID, guest_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Claim a stay that had **no** guest, and answer who holds it afterwards (R4.2, OQ3).

        `POST /reservations` allows a booking with no guest, so the portal's check-in has to
        cope: OQ3 decided it creates the `Guest` from the submitted `full_name` and links it
        here, rather than refusing and leaving a stay that can never complete its legal
        registration with no signal to the operator.

        **A second narrow method rather than widening this port to the reservation**, which
        is the whole reason the port is narrow: the class docstring above says it is
        deliberately not `ReservationRepository` because that one's `save` writes the whole
        row. Reaching one more column keeps that boundary; reaching the aggregate would erase
        it. This writes `reservations.guest_id` and nothing else — not the dates, not the
        status, not the legal state.

        **A claim, not an assignment**, and the return type is what says so. Two concurrent
        submissions of the same form — the retry R4.5 names — must not both link a `Guest`,
        because the loser's row would be orphaned with the encrypted document already inside
        it. So an implementation writes only where there is no guest yet and returns whoever
        holds the stay: the caller's id on a win, the winner's on a loss, `None` when the
        stay does not exist in this tenant. The caller writes the document to whatever comes
        back, never to what it passed in.
        """
        ...
