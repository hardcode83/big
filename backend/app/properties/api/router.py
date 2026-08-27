"""Property endpoints (PRD §23:1938-1942, R1, R2, R3, R6).

The four operations PRD §23:1938-1941 lists, and only those. There is deliberately **no
`DELETE`**: §23 does not list one, `domain-foundation-core.md` records that the PRD models
removal through `status`, and the physical delete is impossible anyway because
`property_state_transitions`, `cleaning_tasks`, `incidents` and `access_records` all reference
`properties.id` with `ON DELETE RESTRICT`. Retirement is `PATCH {"status": "INACTIVE"}` (R3.4).

Plus `GET /{id}/state` (§23:1942), added by `dashboard-api`. It lives here and not in that
change's own module because `properties` owns the column it reports and the history it dates
it from — a read of one domain belongs to that domain (its design D7). The route reads; it
does not resolve. `steering/backend.md` forbids bypassing `PropertyStateMachine`, and
recomputing a state in a read layer would be exactly that.

Still absent: `GET /{id}/dashboard` (§23:1943). It is a **multi-domain aggregate** composing
seven modules, so it is served by `app/dashboard/api/router.py` under this same `/properties`
prefix — the arrangement `users_router` already uses for `/users`. `dashboard-web` consumes
it; it does not own it.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission with
`require(...)`, which is what `tests/test_route_authorization.py` walks — an endpoint added here
without one fails the suite.
"""

import uuid
from datetime import datetime
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
    get_list_blocked_transitions_use_case,
    get_list_properties_use_case,
    get_property_state_use_case,
    get_property_use_case,
    get_update_property_use_case,
)
from app.properties.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    BlockedTransitionListQuery,
    BlockedTransitionPageResponse,
    CreatePropertyRequest,
    PropertyPageResponse,
    PropertyResponse,
    PropertyStateResponse,
    UpdatePropertyRequest,
)
from app.properties.application.use_cases import ListBlockedTransitionsUseCase
from app.properties.application.property_admin import (
    CreatePropertyCommand,
    CreatePropertyUseCase,
    GetPropertyStateUseCase,
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


@router.get(
    "/{property_id}/state",
    response_model=PropertyStateResponse,
    summary="A property's operational state",
    description=(
        "The light endpoint of PRD §23:1942, for refreshing an indicator without fetching "
        "the aggregate. Returns the canonical `PropertyOperationalState` literal — never "
        "translated — and the ISO-8601 UTC instant of the last transition, both **read** "
        "and neither recomputed: the state is whatever `PropertyStateMachine` last wrote. "
        "`last_transition_at` is `null` for a property that has never moved, because "
        "creation is not a transition. A property of another tenant answers `404`, "
        "indistinguishable from one that does not exist."
    ),
)
async def get_property_state(
    property_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetPropertyStateUseCase, Depends(get_property_state_use_case)],
) -> PropertyStateResponse:
    state = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, property_id=property_id
    )
    return PropertyStateResponse.from_domain(state)


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


blocked_transitions_router = APIRouter(
    prefix="/blocked-transitions",
    tags=["properties"],
    responses=AUTHENTICATED_RESPONSES,
)
"""A router of its own, and not a path under `/properties` (design D5).

`dashboard-api` D7 already recorded why: a literal segment under `prefix="/properties"` collides
with `/properties/{id}` and is resolved by registration order, and "una garantía de contrato no
debe depender de eso". Registered in `main.py` as a second `include_router`, the same way
`dashboard` serves its two prefixes from one module.
"""


@blocked_transitions_router.get(
    "",
    response_model=BlockedTransitionPageResponse,
    summary="List the tenant's blocked transitions",
    description=(
        "Flats the calendar wanted to move and whose state would not admit it: the hour came, "
        "the state is not a source of the trigger, and no transition is recorded for that "
        "reservation. Derived on every read and never stored, so a stall disappears by itself "
        "once it is resolved. Oldest first. `total` counts stalls, not properties — the "
        "pagination is of the result, so a stalled flat cannot hide on page 3 of the portfolio. "
        "`trigger` and `blocking_state` are canonical literals; the detection window is the same "
        "30 days back that bounds the clock jobs, so a stall older than that stops appearing "
        "(`docs/celery-jobs.md`)."
    ),
)
async def list_blocked_transitions(
    authenticated: ReadDep,
    use_case: Annotated[
        ListBlockedTransitionsUseCase, Depends(get_list_blocked_transitions_use_case)
    ],
    now: Annotated[datetime, Depends(now_utc)],
    # `extra="forbid"` on `BlockedTransitionListQuery` rejects `?tenant_id=…` with 422 (R3.3,
    # R4.4 of `blocked-transition-response-ids`); the per-parameter `Query(ge=…, le=…)` would
    # silently drop unknown keys and rely on FastAPI's default — see the schema docstring for
    # why a model is required.
    query: Annotated[BlockedTransitionListQuery, Query()],
) -> BlockedTransitionPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        now=now,
        page=query.page,
        per_page=query.per_page,
    )
    return BlockedTransitionPageResponse.build(
        result.items, total=result.total, page=query.page, per_page=query.per_page
    )
