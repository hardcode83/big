"""Checklist template endpoints (R1).

**Not in PRD §23**, and that is deliberate rather than an oversight of ours:
`cleaning_tasks.checklist_template_id` is NOT NULL (`infrastructure/models.py:21-23`) while
§23 declares no template endpoint and §27 seeds no template, so without these two routes the
automatic creation of R2 has nothing to point a task at. The deviation is registered in the
proposal (R1, marked `ASSUMPTION`) following the convention of ADR 0005.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which is what `tests/test_route_authorization.py` walks — an endpoint
added here without one fails the suite.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.api.dependencies import AuthenticatedRequest, now_utc, require
from app.auth.domain.policy import Permission
from app.cleaning.api.dependencies import (
    get_create_checklist_template_use_case,
    get_list_checklist_templates_use_case,
)
from app.cleaning.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    ChecklistTemplatePageResponse,
    ChecklistTemplateResponse,
    CreateChecklistTemplateRequest,
)
from app.cleaning.application.use_cases import (
    CreateChecklistTemplateCommand,
    CreateChecklistTemplateUseCase,
    ListChecklistTemplatesUseCase,
)
from app.core.openapi import AUTHENTICATED_RESPONSES

router = APIRouter(
    prefix="/cleaning-checklist-templates",
    tags=["cleaning"],
    responses=AUTHENTICATED_RESPONSES,
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_CLEANING_TEMPLATES))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_CLEANING_TEMPLATES))
]


@router.get(
    "",
    response_model=ChecklistTemplatePageResponse,
    summary="List the tenant's checklist templates",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). A template with `property_id` applies "
        "to that property only; one without it is the tenant-wide default, and the "
        "property-level template wins when both exist."
    ),
)
async def list_templates(
    authenticated: ReadDep,
    use_case: Annotated[
        ListChecklistTemplatesUseCase, Depends(get_list_checklist_templates_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
) -> ChecklistTemplatePageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, page=page, per_page=per_page
    )
    return ChecklistTemplatePageResponse.build(result.items, result.total, page, per_page)


@router.post(
    "",
    response_model=ChecklistTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a checklist template",
    description=(
        "`items[].item_id` becomes the key a checklist is completed by and travels as a URL "
        "path segment, so it is restricted to letters, digits, `.`, `_` and `-`, capped at "
        "100 characters and unique within the template."
    ),
)
async def create_template(
    authenticated: ManageDep,
    body: CreateChecklistTemplateRequest,
    use_case: Annotated[
        CreateChecklistTemplateUseCase, Depends(get_create_checklist_template_use_case)
    ],
) -> ChecklistTemplateResponse:
    template = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        command=CreateChecklistTemplateCommand(
            name=body.name,
            items=[item.model_dump() for item in body.items],
            required_photos=[photo.model_dump() for photo in body.required_photos],
            property_id=body.property_id,
        ),
        now=now_utc(),
    )
    return ChecklistTemplateResponse.from_domain(template)
