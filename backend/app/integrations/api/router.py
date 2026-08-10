"""Integration endpoints (PRD §16, §23, R4; `reservations-webhooks` R2).

The CSV import, and the administration of the webhook material of rule 12(a)/(b): minting it and
rotating it. The PMS sync has no endpoint on purpose (design D10), and the webhook **receiver**
lives in its own router (`webhooks_router.py`, design D1/D5) because it is anonymous, has its own
transport concerns and must not inherit this one's authentication.

**Why these two exist as endpoints when `pms_credentials` deliberately does not.** That module is
a CLI precisely because rule 3(a) forbids serialising a provider credential in any response. Here
the material is the opposite direction of trust — we mint it so the provider can authenticate to
us — and rule 3 carries a narrow, named exception for exactly that: it may be returned once, at
creation and on each rotation. Without an endpoint that exception would have nothing to permit.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
)
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.core.config import settings
from app.integrations.api.dependencies import (
    get_create_webhook_endpoint_use_case,
    get_import_csv_use_case,
    get_rotate_webhook_endpoint_use_case,
)
from app.integrations.api.schemas import (
    CreateWebhookEndpointRequest,
    ImportReportResponse,
    WebhookEndpointMaterialResponse,
)
from app.integrations.application.use_cases import (
    CreateWebhookEndpointUseCase,
    ImportReservationsFromCsvUseCase,
    RotateWebhookEndpointUseCase,
)
from app.integrations.infrastructure.csv_parser import CsvFileError, CsvTooLargeError

router = APIRouter(
    prefix="/integrations", tags=["integrations"], responses=AUTHENTICATED_RESPONSES
)

# `MANAGE_TENANT_SETTINGS`, which PRD §6 gives the `TENANT_OWNER` alone, rather than the
# `MANAGE_RESERVATIONS` the CSV import next door uses. The two are not the same capability even
# though both feed reservations: importing a file moves data the tenant already has, while minting
# this material decides **who may write into the tenant from the internet**, tenant-wide and for
# every property at once. That is a configuration act, and the closest thing PRD §6 names is
# "configurar preferencias del tenant". No new permission, on the precedent the reservations
# module set: a permission nobody reasons about separately is one nobody administers.
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_TENANT_SETTINGS))
]
ClientIpDep = Annotated[str, Depends(get_client_ip)]

# The declared type is client-supplied, so it is a courtesy check, not the gate — the real gate
# is the UTF-8 + required-columns parse. But it is not opt-out either: an absent or empty type is
# refused rather than silently skipping the branch (the security review found that bypass).
ACCEPTED_CONTENT_TYPES = frozenset(
    {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"}
)


@router.post(
    "/pms/import-csv",
    response_model=ImportReportResponse,
    summary="Import reservations from a CSV file",
    description=(
        "Manual alternative to the PMS integration. Valid rows are imported and invalid ones "
        "are reported with their line number — one bad row never costs the good ones. Rows "
        "carrying an `external_pms_id` already known to the tenant are updated, not "
        "duplicated. The property is named by its `internal_code` (e.g. REDES11)."
    ),
)
async def import_reservations_csv(
    authenticated: Annotated[
        AuthenticatedRequest, Depends(require(Permission.MANAGE_RESERVATIONS))
    ],
    use_case: Annotated[ImportReservationsFromCsvUseCase, Depends(get_import_csv_use_case)],
    file: Annotated[UploadFile, File(description="UTF-8 CSV with the documented columns")],
) -> ImportReportResponse:
    if file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise CsvFileError(
            f"Unsupported content type {file.content_type or '(none)'!r}; expected CSV"
        )

    # The byte ceiling is enforced by `MaxBodySizeMiddleware` BEFORE the body is read — see
    # `app/core/http_limits.py`. Reading here with a ceiling as well is defence in depth for a
    # request whose body arrived in one chunk under a lying `Content-Length`.
    limit = settings.csv_import_max_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise CsvTooLargeError(f"The file exceeds the {limit} byte limit")
    if not raw:
        raise CsvFileError("The file is empty")

    report = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        raw=raw,
        now=now_utc(),
    )
    return ImportReportResponse.from_report(report)


@router.post(
    "/webhook-endpoints",
    response_model=WebhookEndpointMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint this tenant's webhook URL and header secret for one provider",
    description=(
        "Generates the route token and the static header secret the provider will authenticate "
        "with, and returns both **once** — they are stored hashed and encrypted, so no later "
        "call can retrieve them. Answers `409` if the tenant already has an endpoint for this "
        "provider: replacing live material is what `rotate` is for."
    ),
)
async def create_webhook_endpoint(
    authenticated: ManageDep,
    client_ip: ClientIpDep,
    request: Request,
    body: CreateWebhookEndpointRequest,
    use_case: Annotated[
        CreateWebhookEndpointUseCase, Depends(get_create_webhook_endpoint_use_case)
    ],
) -> WebhookEndpointMaterialResponse:
    material = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        provider=body.provider,
        header_name=body.header_name,
        now=now_utc(),
    )
    return WebhookEndpointMaterialResponse.of(material, base_url=str(request.base_url))


@router.post(
    "/webhook-endpoints/{endpoint_id}/rotate",
    response_model=WebhookEndpointMaterialResponse,
    summary="Replace both secrets of an existing webhook endpoint",
    description=(
        "Overwrites the route token and the header secret in one transaction. There is no grace "
        "window: the previous pair stops authenticating immediately, so notices sent to the old "
        "URL are lost until the provider's panel is updated — the `pms_sync` poll recovers them."
    ),
)
async def rotate_webhook_endpoint(
    authenticated: ManageDep,
    client_ip: ClientIpDep,
    request: Request,
    endpoint_id: uuid.UUID,
    use_case: Annotated[
        RotateWebhookEndpointUseCase, Depends(get_rotate_webhook_endpoint_use_case)
    ],
) -> WebhookEndpointMaterialResponse:
    material = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        endpoint_id=endpoint_id,
        now=now_utc(),
    )
    return WebhookEndpointMaterialResponse.of(material, base_url=str(request.base_url))
