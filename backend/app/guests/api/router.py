"""Guest documents and the legal registration of a stay (PRD §17, §23; R6, R7).

Three routes, and every one of them is a review trigger under
`steering/security.md`'s "manejo de documentos de huésped". What that means concretely:

* `GET /guests/{id}/document` is the **only** endpoint in the system that returns an identity
  document, it requires `READ_GUEST_DOCUMENTS`, and it writes an `AuditLog` row before it
  answers (rule 9's "acceso").
* `PATCH /guests/{id}/document` requires `MANAGE_GUEST_DOCUMENTS` and echoes nothing back.
* `POST /reservations/{id}/legal-registration/submit` lives on this router rather than on the
  reservations one so that everything touching SES.Hospedajes is in a single file, which is
  the file a reviewer opens when Chekin arrives.

PRD §23 declares no paths for any of this; they are this change's.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.guests.api.dependencies import (
    get_read_guest_document_use_case,
    get_set_guest_document_use_case,
    get_submit_legal_registration_use_case,
)
from app.guests.api.schemas import (
    DocumentStoredResponse,
    GuestDocumentResponse,
    LegalRegistrationResponse,
    SetDocumentRequest,
)
from app.guests.application.use_cases import (
    DocumentInput,
    GuestActor,
    ReadGuestDocumentUseCase,
    SetGuestDocumentUseCase,
    SubmitLegalRegistrationUseCase,
)

router = APIRouter(tags=["legal"], responses=AUTHENTICATED_RESPONSES)

ReadDocumentDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.READ_GUEST_DOCUMENTS))
]
ManageDocumentDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_GUEST_DOCUMENTS))
]
SubmitDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.SUBMIT_LEGAL_REGISTRATION))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> GuestActor:
    return GuestActor(user_id=authenticated.context.user_id, ip=ip or None)


@router.patch(
    "/guests/{guest_id}/document",
    response_model=DocumentStoredResponse,
    summary="Store a guest's identity document",
    description=(
        "The five fields PRD §17 requires of the guest, all together. The number is encrypted "
        "at rest (Fernet) and **is not echoed back**. Naming a `reservation_id` re-evaluates "
        "that stay's readiness to be reported; omitting it stores the document and touches no "
        "booking. Every call writes an `AuditLog` row recording which fields changed, never "
        "their values."
    ),
)
async def set_guest_document(
    guest_id: uuid.UUID,
    payload: SetDocumentRequest,
    authenticated: ManageDocumentDep,
    use_case: Annotated[SetGuestDocumentUseCase, Depends(get_set_guest_document_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> DocumentStoredResponse:
    guest = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        guest_id=guest_id,
        document=DocumentInput(
            nationality=payload.nationality,
            date_of_birth=payload.date_of_birth,
            document_type=payload.document_type,
            document_number=payload.document_number,
            document_expiry_date=payload.document_expiry_date,
        ),
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        reservation_id=payload.reservation_id,
    )
    return DocumentStoredResponse(
        guest_id=guest.id, document_status=guest.document_status
    )


@router.get(
    "/guests/{guest_id}/document",
    response_model=GuestDocumentResponse,
    summary="Read a guest's full identity document",
    description=(
        "The only endpoint that returns a document number. Restricted to the roles PRD §17 "
        "names, and **audited**: the `AuditLog` row is written before the response is built, "
        "so a read that could not be recorded does not happen. Responds `404` for a guest of "
        "another tenant with a body identical to the one for an id that does not exist."
    ),
)
async def read_guest_document(
    guest_id: uuid.UUID,
    authenticated: ReadDocumentDep,
    use_case: Annotated[ReadGuestDocumentUseCase, Depends(get_read_guest_document_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> GuestDocumentResponse:
    document = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        guest_id=guest_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return GuestDocumentResponse.from_domain(document)


@router.post(
    "/reservations/{reservation_id}/legal-registration/submit",
    response_model=LegalRegistrationResponse,
    summary="Report a stay to SES.Hospedajes",
    description=(
        "PRD §17 step 4. Runs against `MockSESHospedajesAdapter` — real submission is a "
        "declared MVP non-goal (PRD §29) and needs credentials, a DPA with the provider and a "
        "retention policy first. Responds `409` unless the stay is `READY_TO_SUBMIT`, without "
        "invoking the adapter. On failure the stay becomes `FAILED` and the managers are "
        "notified."
    ),
)
async def submit_legal_registration(
    reservation_id: uuid.UUID,
    authenticated: SubmitDep,
    use_case: Annotated[
        SubmitLegalRegistrationUseCase, Depends(get_submit_legal_registration_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> LegalRegistrationResponse:
    status = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        reservation_id=reservation_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return LegalRegistrationResponse(
        reservation_id=reservation_id, legal_registration_status=status
    )
