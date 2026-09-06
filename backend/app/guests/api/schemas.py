"""Request/response DTOs for the guest-document and legal-registration endpoints (PRD §17).

**`GuestDocumentResponse` is the only response model in this codebase that carries a document
number**, and it exists because PRD §17 grants exactly three roles the right to see one. Every
other surface — `GuestSummary`, the reservation detail, any listing — carries `document_status`
and nothing else, which is rule 4 of `steering/security.md` word for word.

That is why there is no `GuestResponse` here: adding a general-purpose guest serialiser next
to this one is how the exception becomes the rule.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.guests.application.portal import GuestAccessTokenStatus
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


class GuestAccessTokenIssuedResponse(BaseModel):
    """The **only** place the cleartext guest token ever appears (`guest-portal-api` D14).

    Rule 3(a) of `steering/security.md` names this exception in so many words: a secret we
    mint for a third party to authenticate with "se puede devolver **una sola vez en el
    momento de generarlo y en cada rotación, nunca en una lectura posterior**". There is no
    later read to worry about — `GuestAccessTokenRepository` offers none, and the row stores
    only a digest — so the exception is bounded by the schema rather than by discipline.

    No `id`, no `token_hash`, no `reservation_id`: the operator needs the value and the
    stay's identity is already in the path they called. Every field here is one more thing a
    proxy log or a browser cache can keep.
    """

    token: str


class GuestAccessTokenStatusResponse(BaseModel):
    """Presence and issuance instant of a stay's live portal token (`guest-link-delivery` R2).

    Deliberately **not** `token_hash` or anything that could reconstruct it: this is the
    surface R2.2 asks for precisely so a frontend need not mint a token merely to learn
    whether one already exists. `issued_at` is `None` exactly when `is_live` is `False`,
    mirroring `GuestAccessTokenStatus` (`application/portal.py`) field for field — this class
    exists only to give that dataclass a JSON shape, not to widen it.
    """

    is_live: bool
    issued_at: datetime | None

    @classmethod
    def from_domain(cls, status: GuestAccessTokenStatus) -> "GuestAccessTokenStatusResponse":
        return cls(is_live=status.is_live, issued_at=status.issued_at)


class GuestAccessTokenSentResponse(BaseModel):
    """Whether the email adapter accepted the delivery (`guest-link-delivery` R3.5, D5).

    **Never** the cleartext token — R1 keeps "copy it yourself" (the existing `POST`) and
    "email it to the guest" (this route) as two distinct operator actions, and an operator who
    triggered a send has no reason to also see the value in their own browser.
    """

    delivered: bool


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
