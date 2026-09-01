"""The dashboard endpoints (PRD §9.1, §9.2, §23:1943, `dashboard-api` R1, R2).

**Two routes on two prefixes, from one router.** `GET /api/v1/properties/{id}/dashboard` is
named literally by PRD §23:1943, so it stays where the PRD put it even though it is served
here — the arrangement `users_router` already uses, living in `auth` and serving `/users`
(`main.py:66-69`). The collection is this change's own invention (R1 says so), so it goes
under its own prefix.

**Why the collection is `/dashboard/properties` and not `/properties/dashboard`** (design
D7): the second collides with `/properties/{id}`, which FastAPI resolves by registration
order — `dashboard` would parse as an id and the endpoint would answer `422` instead of
existing, depending on which of two lines in `main.py` came first. A contract guarantee
should not rest on that. Being the only route the PRD does not name, it is also the only one
free to move.

The aggregate lives here rather than in `properties` because it composes seven domains
(design D1); putting it in `properties` would make the module that guards the state-machine
invariant import six that do not.
"""

import uuid
from datetime import UTC, date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.dashboard.api.dependencies import (
    get_dashboard_cards_use_case,
    get_operational_kpis_use_case,
    get_property_dashboard_use_case,
)
from app.dashboard.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    OperationalKpisResponse,
    PropertyDashboardPageResponse,
    PropertyDetailResponse,
)
from app.dashboard.application.use_cases import (
    GetDashboardCardsUseCase,
    GetOperationalKpisUseCase,
    GetPropertyDashboardUseCase,
)

router = APIRouter(tags=["dashboard"], responses=AUTHENTICATED_RESPONSES)

# `READ_PROPERTIES` on both routes (design D10). The finer permissions are NOT enforced at
# the door — they decide, inside the use case, which blocks come back at all, because
# `require()` takes one permission and a route gated on one would otherwise hand over in a
# single response what four permissions protect separately. "Agregar no puede conceder".
ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_PROPERTIES))]


def _today() -> date:
    """The day the "current or next" reservation is judged against.

    A function so a test can override it through FastAPI, and UTC because that is the
    project's convention for every instant that crosses this boundary (PRD §23).
    """
    return now_utc().astimezone(UTC).date()


TodayDep = Annotated[date, Depends(_today)]


@router.get(
    "/dashboard/properties",
    response_model=PropertyDashboardPageResponse,
    summary="The dashboard card of every property",
    description=(
        "One card per property of the caller's tenant (PRD §9.1), in the pagination "
        "envelope of PRD §23, with the same `page`/`per_page` bounds as "
        "`GET /api/v1/properties`. Resolved in a fixed number of queries whatever the page "
        "size — never one per property. `operational_state` is the canonical literal and "
        "carries no colour: the colour mapping belongs to the client. `cleaning_status`, "
        "`next_action.label` and `last_event_label` arrive already composed in the "
        "authenticated user's language. A block whose source the caller's role may not read "
        "comes back `null`, indistinguishable from having none — `current_or_next_reservation` "
        "is always present as a key, `null` included. Amounts are decimal strings so no cent "
        "is lost to a float. This route is not in PRD §23; it is an explicit extension, which "
        "is why it sits under `/dashboard` rather than under `/properties`."
    ),
)
async def list_dashboard_cards(
    authenticated: ReadDep,
    today: TodayDep,
    use_case: Annotated[GetDashboardCardsUseCase, Depends(get_dashboard_cards_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
) -> PropertyDashboardPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        role=authenticated.context.role,
        locale=authenticated.context.preferred_language,
        page=page,
        per_page=per_page,
        today=today,
    )
    return PropertyDashboardPageResponse.build(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.get(
    "/properties/{property_id}/dashboard",
    response_model=PropertyDetailResponse,
    summary="Everything happening on one property",
    description=(
        "The aggregate of PRD §9.2: reservation, guest, access, cleaning, incidents, "
        "financial, notes and pending approvals in one call. The guest is a name and the "
        "access a status label — never a document number, never an access code in any form, "
        "masked included. `last_cleaning_photos` is always empty until signed URLs exist; "
        "the blocks whose writing domain has not shipped yet (`incidents`, "
        "`owner_approvals`, `expenses`) query their real tables and come back empty, so the "
        "contract will not change when those changes land. `notes` is always `null` for now "
        "and deliberately so — no column owns it, and the candidates are free text an "
        "operator can paste a door code into. A property of another tenant answers `404`, "
        "indistinguishable from one that does not exist."
    ),
)
async def get_property_dashboard(
    property_id: uuid.UUID,
    authenticated: ReadDep,
    today: TodayDep,
    use_case: Annotated[
        GetPropertyDashboardUseCase, Depends(get_property_dashboard_use_case)
    ],
) -> PropertyDetailResponse:
    detail = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        property_id=property_id,
        role=authenticated.context.role,
        locale=authenticated.context.preferred_language,
        today=today,
    )
    return PropertyDetailResponse.from_domain(detail)


@router.get(
    "/dashboard/operational-kpis",
    response_model=OperationalKpisResponse,
    summary="Tenant-wide operational counts",
    description=(
        "Three tenant-wide counts (`dashboard-operational-kpis` R1, R2, R3): today's live "
        "cleaning tasks, check-ins in the next 7 days, and open incidents with their "
        "urgent (HIGH/CRITICAL) breakdown. All three keys are always present, `null` "
        "included: a field comes back `null` when the caller's role lacks the permission "
        "that guards its source domain (`READ_CLEANING_TASKS`, `READ_RESERVATIONS`, "
        "`READ_INCIDENTS` respectively), indistinguishable from having nothing to count — "
        "the same 'agregar no concede' rule the other two dashboard routes apply. "
        "`open_incidents` is one nested object, redacted as a whole."
    ),
)
async def get_operational_kpis(
    authenticated: ReadDep,
    today: TodayDep,
    use_case: Annotated[GetOperationalKpisUseCase, Depends(get_operational_kpis_use_case)],
) -> OperationalKpisResponse:
    kpis = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        role=authenticated.context.role,
        today=today,
    )
    return OperationalKpisResponse.from_domain(kpis)
