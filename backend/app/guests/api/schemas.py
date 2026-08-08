"""Request/response DTOs for the guest-document and legal-registration endpoints (PRD §17).

**`GuestDocumentResponse` is the only response model in this codebase that carries a document
number**, and it exists because PRD §17 grants exactly three roles the right to see one. Every
other surface — `GuestSummary`, the reservation detail, any listing — carries `document_status`
and nothing else, which is rule 4 of `steering/security.md` word for word.

That is why there is no `GuestResponse` here: adding a general-purpose guest serialiser next
to this one is how the exception becomes the rule.
"""

import uuid
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.guests.application.use_cases import GuestDocument
from app.guests.domain.enums import (
    GuestDocumentStatus,
    GuestDocumentType,
    LegalRegistrationStatus,
)

MAX_DOCUMENT_NUMBER = 100
MAX_NATIONALITY = 2


class SetDocumentRequest(BaseModel):
    """The five document fields, all required together (R7.1).

    Not a partial patch: PRD §17 needs the set, and a guest with a number but no expiry date
    looks documented and cannot be reported. `check_in_date`/`check_out_date` — the other two
    of the eight — are the reservation's and are never accepted here.
    """

    model_config = ConfigDict(extra="forbid")

    nationality: Annotated[str, Field(min_length=2, max_length=MAX_NATIONALITY)]
    date_of_birth: date
    document_type: GuestDocumentType
    document_number: Annotated[str, Field(min_length=1, max_length=MAX_DOCUMENT_NUMBER)]
    document_expiry_date: date
    #: Optional: naming a stay re-evaluates **that** stay's readiness (R6.3). Left out, the
    #: document is stored and no booking is touched — a guest can have several, and fanning
    #: out across bookings the caller never mentioned is not something to do implicitly.
    reservation_id: uuid.UUID | None = None


class DocumentStoredResponse(BaseModel):
    """What a successful write returns: **no document number**.

    The caller just sent it; echoing it back would put it in one more response body, one more
    proxy log and one more browser cache for no benefit.
    """

    guest_id: uuid.UUID
    document_status: GuestDocumentStatus


class GuestDocumentResponse(BaseModel):
    guest_id: uuid.UUID
    full_name: str
    nationality: str | None
    date_of_birth: date | None
    document_type: GuestDocumentType | None
    document_number: str
    document_expiry_date: date | None
    document_status: GuestDocumentStatus

    @classmethod
    def from_domain(cls, document: GuestDocument) -> "GuestDocumentResponse":
        return cls(
            guest_id=document.guest_id,
            full_name=document.full_name,
            nationality=document.nationality,
            date_of_birth=document.date_of_birth,
            document_type=document.document_type,
            document_number=document.document_number,
            document_expiry_date=document.document_expiry_date,
            document_status=document.document_status,
        )


class LegalRegistrationResponse(BaseModel):
    reservation_id: uuid.UUID
    legal_registration_status: LegalRegistrationStatus
