"""Property endpoints (PRD §23:1938-1941, R1, R2, R3, R6).

The four operations PRD §23 lists, and only those. There is deliberately **no `DELETE`**: §23
does not list one, `domain-foundation-core.md` records that the PRD models removal through
`status`, and the physical delete is impossible anyway because `property_state_transitions`,
`cleaning_tasks`, `incidents` and `access_records` all reference `properties.id` with
`ON DELETE RESTRICT`. Retirement is `PATCH {"status": "INACTIVE"}` (R3.4).

Also absent: `GET /{id}/state` and `GET /{id}/dashboard` from §23:1942-1943. Those are the read
surface of `dashboard-web`, and fixing their shape from here would pre-empt it.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission with
`require(...)`, which is what `tests/test_route_authorization.py` walks — an endpoint added here
without one fails the suite.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
)
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.properties.api.dependencies import (
    get_create_property_use_case,
    get_list_properties_use_case,
    get_property_use_case,
    get_update_property_use_case,
)
from app.properties.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    CreatePropertyRequest,
    PropertyPageResponse,
    PropertyResponse,
    UpdatePropertyRequest,
)
from app.properties.application.property_admin import (
    CreatePropertyCommand,
    CreatePropertyUseCase,
    GetPropertyUseCase,
    ListPropertiesUseCase,
    UpdatePropertyUseCase,
)
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.repositories import PropertyFilters

router = APIRouter(
    prefix="/properties", tags=["properties"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_PROPERTIES))]
ManageDep = Annotated[AuthenticatedRequest, Depends(require(Permission.MANAGE_PROPERTIES))]
ClientIpDep = Annotated[str, Depends(get_client_ip)]


@router.get(
    "",
    response_model=PropertyPageResponse,
    summary="List the tenant's properties",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). Filters combine with AND. Ordered by "
        "name with the id as tiebreaker, so paging neither repeats a row nor skips one when "
        "two properties share a name. The wifi password is never in the response — "
        "`has_wifi_password` reports whether one is stored."
    ),
)
async def list_properties(
    authenticated: ReadDep,
    use_case: Annotated[ListPropertiesUseCase, Depends(get_list_properties_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    status_filter: Annotated[PropertyStatus | None, Query(alias="status")] = None,
    current_operational_state: PropertyOperationalState | None = None,
) -> PropertyPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=PropertyFilters(
            status=status_filter,
            current_operational_state=current_operational_state,
        ),
        page=page,
        per_page=per_page,
    )
    return PropertyPageResponse.build(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "",
    response_model=PropertyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a property",
    description=(
        "`internal_code` must be unique within the tenant and `pms_external_id` unique "
        "within the tenant AND the provider, both answering `409` on collision. "
        "`current_operational_state` cannot be chosen: a new property starts `VACANT_READY` "
        "and only `PropertyStateMachine` moves it. A `wifi_password` is encrypted before "
        "storage and can never be read back."
    ),
)
async def create_property(
    body: CreatePropertyRequest,
    authenticated: ManageDep,
    client_ip: ClientIpDep,
    use_case: Annotated[CreatePropertyUseCase, Depends(get_create_property_use_case)],
) -> PropertyResponse:
    property = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        command=CreatePropertyCommand(
            name=body.name,
            internal_code=body.internal_code,
            pms_external_id=body.pms_external_id,
            pms_provider=body.pms_provider,
            address_line1=body.address_line1,
            address_line2=body.address_line2,
            city=body.city,
            province=body.province,
            postal_code=body.postal_code,
            country=body.country,
            timezone=body.timezone,
            max_guests=body.max_guests,
            bedrooms=body.bedrooms,
            bathrooms=body.bathrooms,
            default_check_in_time=body.default_check_in_time,
            default_check_out_time=body.default_check_out_time,
            wifi_name=body.wifi_name,
            wifi_password=body.wifi_password,
            access_notes=body.access_notes,
            cleaning_notes=body.cleaning_notes,
            emergency_notes=body.emergency_notes,
            status=body.status,
        ),
        now=now_utc(),
    )
    return PropertyResponse.from_domain(property)


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="One property",
    description=(
        "A property of another tenant answers `404`, with a body indistinguishable from one "
        "that does not exist. The wifi password is not returned in any form, masked included; "
        "`has_wifi_password` reports whether one is stored."
    ),
)
async def get_property(
    property_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetPropertyUseCase, Depends(get_property_use_case)],
) -> PropertyResponse:
    property = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, property_id=property_id
    )
    return PropertyResponse.from_domain(property)


@router.patch(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Update a property partially",
    description=(
        "Only the fields present in the body are applied. `current_operational_state` is not "
        "among them and is rejected with `422`. A body that changes nothing writes nothing "
        "and records no audit entry — except `wifi_password`, whose no-op cannot be detected "
        "because the stored value has no reader, so sending it always counts as a change. "
        "Retire a property with `{\"status\": \"INACTIVE\"}`; there is no `DELETE`."
    ),
)
async def update_property(
    property_id: uuid.UUID,
    body: UpdatePropertyRequest,
    authenticated: ManageDep,
    client_ip: ClientIpDep,
    use_case: Annotated[UpdatePropertyUseCase, Depends(get_update_property_use_case)],
) -> PropertyResponse:
    property = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        property_id=property_id,
        changes=body.changes(),
        now=now_utc(),
    )
    return PropertyResponse.from_domain(property)
