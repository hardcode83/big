"""Guest documents, the legal registration of a stay, and the portal credential
(PRD §17, §23; `access-notifications` R6, R7; `guest-portal-api` R1).

Five routes, and every one of them is a review trigger under `steering/security.md` —
the first three under "manejo de documentos de huésped", the last two under "endpoints
nuevos" and "cambios de auth/RBAC". What that means concretely:

* `GET /guests/{id}/document` is the **only** endpoint in the system that returns an identity
  document, it requires `READ_GUEST_DOCUMENTS`, and it writes an `AuditLog` row before it
  answers (rule 9's "acceso").
* `PATCH /guests/{id}/document` requires `MANAGE_GUEST_DOCUMENTS` and echoes nothing back.
* `POST /reservations/{id}/legal-registration/submit` lives on this router rather than on the
  reservations one so that everything touching SES.Hospedajes is in a single file, which is
  the file a reviewer opens when Chekin arrives.
* `POST /reservations/{id}/guest-access-token` is the **only** endpoint in the system that
  returns a secret it just minted — rule 3(a)'s single named exception (`guest-portal-api`
  D14). It requires `MANAGE_GUEST_ACCESS_TOKENS`.
* `DELETE /reservations/{id}/guest-access-token` withdraws it (R1.4), same permission.

The last two live here rather than on the reservations router for the reason the submission
one does: the credential belongs to the guest's stay, and keeping every route that can reach
a guest's identity — directly or by handing out a link to it — in one file is what makes this
the file a security reviewer opens.

PRD §23 declares no paths for the document or submission routes; those are
`access-notifications`'. It *does* declare the anonymous `{token}` ones, which are
deliberately **not** here — they carry no `Authorization` header and live in
`portal_router.py` (D1), because hiding an unauthenticated route inside a router that
declares `AUTHENTICATED_RESPONSES` is what `app/main.py` describes as "esconder un endpoint
sin autenticar dentro de una forma que dice lo contrario".
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.guests.api.dependencies import (
    get_issue_guest_access_token_use_case,
    get_read_guest_document_use_case,
    get_revoke_guest_access_token_use_case,
    get_set_guest_document_use_case,
    get_submit_legal_registration_use_case,
)
from app.guests.api.schemas import (
    DocumentStoredResponse,
    GuestAccessTokenIssuedResponse,
    GuestDocumentResponse,
    LegalRegistrationResponse,
    SetDocumentRequest,
)
from app.guests.application.portal import (
    IssueGuestAccessTokenUseCase,
    RevokeGuestAccessTokenUseCase,
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
ManageAccessTokenDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_GUEST_ACCESS_TOKENS))
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
    "/reservations/{reservation_id}/guest-access-token",
    response_model=GuestAccessTokenIssuedResponse,
    status_code=201,
    summary="Mint the guest's portal token for a stay",
    description=(
        "Returns the token **in clear, once and only once** — the single named exception of "
        "rule 3(a) of the security steering, because an operator has to be able to hand the "
        "link to the guest and only its digest is stored. No later call returns it, and no "
        "endpoint reads it back. If the stay already had a live token this **replaces** it: "
        "the previous one is revoked in the same transaction, so a guest holding the old "
        "link stops being authorised the moment the new one is minted. Responds `404` for a "
        "stay of another tenant with a body identical to the one for an id that does not "
        "exist."
    ),
)
async def issue_guest_access_token(
    reservation_id: uuid.UUID,
    authenticated: ManageAccessTokenDep,
    use_case: Annotated[
        IssueGuestAccessTokenUseCase, Depends(get_issue_guest_access_token_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> GuestAccessTokenIssuedResponse:
    token = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        reservation_id=reservation_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return GuestAccessTokenIssuedResponse(token=token)


@router.delete(
    "/reservations/{reservation_id}/guest-access-token",
    status_code=204,
    summary="Revoke the guest's portal token for a stay",
    description=(
        "Withdraws the stay's live token, if it has one. Idempotent: revoking twice answers "
        "`204` both times and leaves the first revocation's instant untouched, because that "
        "timestamp is what records *when* access was withdrawn. Always permitted — a "
        "withdrawal does not depend on the stay's state. Responds `404` for a stay of "
        "another tenant."
    ),
)
async def revoke_guest_access_token(
    reservation_id: uuid.UUID,
    authenticated: ManageAccessTokenDep,
    use_case: Annotated[
        RevokeGuestAccessTokenUseCase, Depends(get_revoke_guest_access_token_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> None:
    # The return value — whether there was anything to revoke — is deliberately not
    # surfaced. Answering "there was no live token" would tell a caller something about a
    # stay's state that they can learn no other way, and the operator's intent ("this link
    # must stop working") is satisfied either way.
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        reservation_id=reservation_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )


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
