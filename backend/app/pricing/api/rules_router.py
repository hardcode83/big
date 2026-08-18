"""The four pricing-rule endpoints (PRD §23, R1; design D1, D11, D20).

Thin by contract: Pydantic → use case → Pydantic. Every route hangs off its own
`require(...)`, which `tests/test_route_authorization.py` walks structurally.

**This file is the gate D20 describes, and that is why it exists as its own task.** Section 3
left the *capability* of re-pointing a rule at another tenant's property in place —
`property_id` is a mutable column, and the foreign key is global rather than composite with
`tenant_id` — with the guard living outside the module. That was only safe while there was no
caller. These routes are the caller, so they are mounted only now that `CreatePricingRule`
and `UpdatePricingRule` resolve the body's `property_id` inside the acting tenant. Conditioned
this way by the section-3 security panel on re-review: the gate is the routes, not the use
cases.

**A rule of another tenant answers `404`, never `403`** (R1.7). That falls out of the ports
returning `None` outside the tenant and the use case raising `PricingRuleNotFoundError` from
its constant message — the endpoint never asks "does this exist somewhere else?", because
answering differently for the two cases is a tenant-enumeration probe.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.pricing.api.dependencies import (
    get_create_pricing_rule_use_case,
    get_list_pricing_rules_use_case,
    get_pricing_rule_use_case,
    get_update_pricing_rule_use_case,
)
from app.pricing.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    CreatePricingRuleRequest,
    PricingRulePageResponse,
    PricingRuleResponse,
    UpdatePricingRuleRequest,
)
from app.pricing.application.use_cases import (
    CreatePricingRuleUseCase,
    GetPricingRuleUseCase,
    ListPricingRulesUseCase,
    PricingActor,
    UpdatePricingRuleUseCase,
)
from app.pricing.domain.repositories import PricingRuleFilters

router = APIRouter(
    prefix="/pricing-rules", tags=["pricing"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_PRICING_RULES))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_PRICING_RULES))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> PricingActor:
    """Who is acting, and from where — the two things rule 9 records.

    No role, unlike `maintenance`'s: D11 gives `TENANT_OWNER` and `PROPERTY_MANAGER` the same
    four permissions, so once `require(...)` has let a caller through this module draws no
    further distinction between them.
    """
    return PricingActor(user_id=authenticated.context.user_id, ip=ip or None)


@router.get(
    "",
    response_model=PricingRulePageResponse,
    summary="List the tenant's pricing rules",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). `property_id` narrows to one property's "
        "own rules and `active` to the ones in force; both are combined with AND. Only rules "
        "of the caller's tenant are ever returned (R1.2)."
    ),
)
async def list_pricing_rules(
    authenticated: ReadDep,
    use_case: Annotated[ListPricingRulesUseCase, Depends(get_list_pricing_rules_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    active: bool | None = None,
) -> PricingRulePageResponse:
    result = await use_case.execute(
        authenticated.context.tenant_id,
        PricingRuleFilters(property_id=property_id, active=active),
        page=page,
        per_page=per_page,
    )
    return PricingRulePageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "",
    response_model=PricingRuleResponse,
    status_code=201,
    summary="Create a pricing rule",
    description=(
        "`201` with the stored rule, whose `id` is what the other three routes take (R1.1). "
        "Omitting `property_id` makes the rule tenant-wide: it applies to every property that "
        "has no active rule of its own (R1.5). A `property_id` the tenant does not own is a "
        "`422` — the body names something that is not there (design D20).\n\n"
        "Every invariant of R1.3 and R1.4 is checked in the domain and the `422` names the "
        "field that failed, so a crossed `min_price`/`max_price` pair or a malformed entry in "
        "any of the five JSONB columns is refused without persisting anything."
    ),
)
async def create_pricing_rule(
    payload: CreatePricingRuleRequest,
    authenticated: ManageDep,
    use_case: Annotated[CreatePricingRuleUseCase, Depends(get_create_pricing_rule_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> PricingRuleResponse:
    rule = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        name=payload.name,
        base_price=payload.base_price,
        min_price=payload.min_price,
        max_price=payload.max_price,
        property_id=payload.property_id,
        active=payload.active,
        max_daily_change_pct=payload.max_daily_change_pct,
        weekday_modifiers=payload.weekday_modifiers,
        lead_time_rules=payload.lead_time_rules,
        occupancy_rules=payload.occupancy_rules,
        seasonality_rules=payload.seasonality_rules,
        event_rules=payload.event_rules,
    )
    return PricingRuleResponse.from_domain(rule)


@router.get(
    "/{rule_id}",
    response_model=PricingRuleResponse,
    summary="Read one pricing rule",
    description=(
        "A rule of another tenant answers the same `404` as one that does not exist, with the "
        "same body (R1.7)."
    ),
)
async def get_pricing_rule(
    rule_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetPricingRuleUseCase, Depends(get_pricing_rule_use_case)],
) -> PricingRuleResponse:
    rule = await use_case.execute(authenticated.context.tenant_id, rule_id)
    return PricingRuleResponse.from_domain(rule)


@router.patch(
    "/{rule_id}",
    response_model=PricingRuleResponse,
    summary="Adjust a pricing rule",
    description=(
        "Partial: only the fields present in the body move, and the whole rule is re-validated "
        "afterwards — so raising `min_price` is judged against the stored `max_price` (R1.3). "
        "A refused update leaves the rule and its `updated_at` exactly as they were.\n\n"
        "Sending `property_id: null` turns a per-property rule into a tenant-wide one, which is "
        "why absent and null are different here. A `property_id` the tenant does not own is a "
        "`422`, as it is on creation (design D20)."
    ),
)
async def update_pricing_rule(
    rule_id: uuid.UUID,
    payload: UpdatePricingRuleRequest,
    authenticated: ManageDep,
    use_case: Annotated[UpdatePricingRuleUseCase, Depends(get_update_pricing_rule_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> PricingRuleResponse:
    rule = await use_case.execute(
        authenticated.context.tenant_id,
        rule_id,
        # `exclude_unset` and not `exclude_none`: a caller sending `property_id: null` is
        # asking for a tenant-wide rule (R1.5), and `exclude_none` would silently drop that
        # request instead of performing it.
        payload.model_dump(exclude_unset=True),
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return PricingRuleResponse.from_domain(rule)
