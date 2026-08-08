"""Access record endpoints (PRD §15, §23; R2, R3).

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which `tests/test_route_authorization.py` walks.

**Read and write are different permissions** (`policy.py`): the owner sees how her guests get
in, the manager operates it. `CLEANER` and `TECHNICIAN` hold neither — a guest's door code is
not part of doing a cleaning or a repair.

PRD §23 declares no routes for this module, so the paths are this change's: `/access-records`
as a top-level collection, filtered by `reservation_id`/`property_id`, plus one POST per
transition. Deliberately not `PATCH /access-records/{id}` with a `status` field — that shape
invites a client to pick the target state, and the state machine of design D14 is what
decides which moves exist.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.access.api.dependencies import (
    get_access_record_use_case,
    get_list_access_records_use_case,
    get_mark_access_delivered_use_case,
    get_mark_access_externally_managed_use_case,
    get_register_manual_access_code_use_case,
)
from app.access.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    AccessRecordPageResponse,
    AccessRecordResponse,
    MarkExternalRequest,
    RegisterCodeRequest,
)
from app.access.application.use_cases import (
    AccessActor,
    GetAccessRecordUseCase,
    ListAccessRecordsUseCase,
    MarkAccessDeliveredUseCase,
    MarkAccessExternallyManagedUseCase,
    RegisterManualAccessCodeUseCase,
)
from app.access.domain.enums import AccessRecordStatus
from app.access.domain.repositories import AccessRecordFilters
from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES

router = APIRouter(
    prefix="/access-records", tags=["access"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_ACCESS_RECORDS))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_ACCESS_RECORDS))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> AccessActor:
    return AccessActor(user_id=authenticated.context.user_id, ip=ip or None)


@router.get(
    "",
    response_model=AccessRecordPageResponse,
    summary="List the tenant's access records",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). Filterable by `property_id`, "
        "`reservation_id` and `status`. Access codes appear only in their masked `****XX` "
        "form — the plaintext is never stored (PRD §15: the provider creates and delivers it)."
    ),
)
async def list_access_records(
    authenticated: ReadDep,
    use_case: Annotated[ListAccessRecordsUseCase, Depends(get_list_access_records_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    status_filter: Annotated[AccessRecordStatus | None, Query(alias="status")] = None,
) -> AccessRecordPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=AccessRecordFilters(
            property_id=property_id, reservation_id=reservation_id, status=status_filter
        ),
        page=page,
        per_page=per_page,
    )
    return AccessRecordPageResponse.build(result.items, result.total, page, per_page)


@router.get(
    "/{record_id}",
    response_model=AccessRecordResponse,
    summary="Read one access record",
    description=(
        "Responds `404` for a record of another tenant with a body identical to the one for "
        "an id that does not exist (R3.3)."
    ),
)
async def get_access_record(
    record_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetAccessRecordUseCase, Depends(get_access_record_use_case)],
) -> AccessRecordResponse:
    record = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, record_id=record_id
    )
    return AccessRecordResponse.from_domain(record)


@router.post(
    "/{record_id}/manual-code",
    response_model=AccessRecordResponse,
    summary="Register an access code arranged by hand",
    description=(
        "PRD §15's `ManualAccessAdapter`. **Only the masked form is stored**: the plaintext "
        "reaches the domain, is reduced to `****XX` and is discarded — there is no column, "
        "no response field and no log line that can hold it. Responds `409` if the record is "
        "not `PENDING`."
    ),
)
async def register_manual_code(
    record_id: uuid.UUID,
    payload: RegisterCodeRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        RegisterManualAccessCodeUseCase, Depends(get_register_manual_access_code_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> AccessRecordResponse:
    record = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        record_id=record_id,
        code=payload.code,
        notes=payload.notes,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return AccessRecordResponse.from_domain(record)


@router.post(
    "/{record_id}/external",
    response_model=AccessRecordResponse,
    summary="Declare that the provider manages this access",
    description=(
        "PRD §15: GrinPass imports the reservation from the PMS and creates the code itself. "
        "Responds `409` if the record is not `PENDING`."
    ),
)
async def mark_external(
    record_id: uuid.UUID,
    payload: MarkExternalRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        MarkAccessExternallyManagedUseCase,
        Depends(get_mark_access_externally_managed_use_case),
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> AccessRecordResponse:
    record = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        record_id=record_id,
        notes=payload.notes,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return AccessRecordResponse.from_domain(record)


@router.post(
    "/{record_id}/delivered",
    response_model=AccessRecordResponse,
    summary="Confirm the guest received the access instructions",
    description=(
        "Responds `409` unless the record is `MANUAL_ADDED` or `CREATED_EXTERNAL`: confirming "
        "delivery of a code nobody registered would be an assertion about a guest that has no "
        "basis."
    ),
)
async def mark_delivered(
    record_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[
        MarkAccessDeliveredUseCase, Depends(get_mark_access_delivered_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> AccessRecordResponse:
    record = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        record_id=record_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return AccessRecordResponse.from_domain(record)
