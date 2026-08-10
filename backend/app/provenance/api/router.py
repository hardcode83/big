from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth.api.dependencies import AuthenticatedRequest, require
from app.auth.domain.policy import Permission
from app.core.config import settings
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.core.version import package_version
from app.provenance.application.provenance import PrivateProvenance
from app.provenance.api.schemas import BuildProvenanceResponse, PrivateProvenanceResponse


router = APIRouter(
    prefix="/provenance",
    tags=["provenance"],
    responses=AUTHENTICATED_RESPONSES,
)
ReadProvenanceDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.READ_BUILD_PROVENANCE))
]


@router.get(
    "",
    response_model=BuildProvenanceResponse,
    responses=AUTHENTICATED_RESPONSES,
    summary="Read the authenticated build provenance",
    description=(
        "Returns build provenance to authorized operational users only. "
        "The public app_version may exist independently; the private provenance "
        "block is atomic and may be unavailable when any field is missing or invalid. "
        "The response is produced from deployment configuration and does not query GitHub at runtime."
    ),
)
async def get_provenance(
    response: Response, _authenticated: ReadProvenanceDep
) -> BuildProvenanceResponse:
    response.headers["Cache-Control"] = "private, no-store"
    provenance = PrivateProvenance.from_settings(settings)
    return BuildProvenanceResponse(
        app_version=package_version(),
        provenance=(
            PrivateProvenanceResponse(**provenance.__dict__) if provenance is not None else None
        ),
    )
