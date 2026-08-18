"""The three price-recommendation endpoints (PRD §23, R4.5, R5; design D1, D10, D14).

Its own module rather than routes on `rules_router.py` because it acts on the other
aggregate: a rule is edited by a person, a horizon is rewritten every night, and the two
carry different permissions (D1).

**Nothing here reaches the `PMSAdapter`, and that is Mode 1 of PRD §19 rather than an
omission** (R5.5): the system recommends, and `APPLIED_EXTERNAL` is a human coming back to
say they published the price themselves. That is why the transition carries a
`TimelineEvent` — it records a fact about the world, not a change of our mind.

`POST /generate` runs **in the request** and not as a queued task (D10). R4.5 asks it to
report how many recommendations it created and how many it updated, and that is only known
when it finishes; a `202` with a job id would be answering a different question.
"""

# A tripwire worth knowing before you edit the docstring above, because it cost a debugging
# round once: `tests/maintenance/test_free_text_sink_contract.py` gates its rule-11 census on
# "any string literal containing the incidents table name plus a write verb", and every route
# below passes FastAPI a `description=` keyword — which that census reads as a write to
# `incidents.description`. So a docstring here that mentions that other module's table *and* a
# word like "updated" pulls this whole file into a census it has nothing to do with. The first
# draft of the docstring above did exactly that, via a decorative cross-reference. Said in a
# comment rather than in the docstring on purpose: the matcher walks string literals, so a
# comment is invisible to it and this note cannot trip the very gate it describes.
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.pricing.api.dependencies import (
    get_decide_price_recommendation_use_case,
    get_generate_price_recommendations_use_case,
    get_list_price_recommendations_use_case,
)
from app.pricing.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    DecidePriceRecommendationRequest,
    GeneratePriceRecommendationsRequest,
    GenerationReportResponse,
    PriceRecommendationPageResponse,
    PriceRecommendationResponse,
)
from app.pricing.application.use_cases import (
    DecidePriceRecommendationUseCase,
    GeneratePriceRecommendationsUseCase,
    ListPriceRecommendationsUseCase,
    PricingActor,
)
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.repositories import PriceRecommendationFilters

router = APIRouter(
    prefix="/price-recommendations", tags=["pricing"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.READ_PRICE_RECOMMENDATIONS))
]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_PRICE_RECOMMENDATIONS))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> PricingActor:
    return PricingActor(user_id=authenticated.context.user_id, ip=ip or None)


@router.get(
    "",
    response_model=PriceRecommendationPageResponse,
    summary="List the tenant's price recommendations",
    description=(
        "Paginated with `page`/`per_page` (PRD §23), filtered by `property_id`, by the "
        "`date_from`/`date_to` range and by `status`, all combined with AND. Only "
        "recommendations of the caller's tenant are ever returned (R5.1).\n\n"
        "Each item carries its `explanation`: the ordered modifiers with their percentages "
        "and whichever guardrails cut the price, so the recommendation can be approved with "
        "criterion rather than blind (R6.1)."
    ),
)
async def list_price_recommendations(
    authenticated: ReadDep,
    use_case: Annotated[
        ListPriceRecommendationsUseCase, Depends(get_list_price_recommendations_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[
        PriceRecommendationStatus | None, Query(alias="status")
    ] = None,
) -> PriceRecommendationPageResponse:
    result = await use_case.execute(
        authenticated.context.tenant_id,
        PriceRecommendationFilters(
            property_id=property_id,
            date_from=date_from,
            date_to=date_to,
            status=status_filter,
        ),
        page=page,
        per_page=per_page,
    )
    return PriceRecommendationPageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "/generate",
    response_model=GenerationReportResponse,
    summary="Generate the recommendations now",
    description=(
        "The manual door of the nightly job: the same generator, over the same 60-day "
        "horizon, so a rule that was just edited takes effect without waiting for 06:00 UTC "
        "(design D10). Naming a `property_id` limits it to that property; omitting it sweeps "
        "the tenant's whole **active** portfolio (OQ4).\n\n"
        "Idempotent by construction (R4.2), and a recommendation already `APPROVED` or "
        "`APPLIED_EXTERNAL` is left untouched and counted in `preserved` — a regeneration "
        "never undoes a human decision (R4.3). A property with no applicable active rule is "
        "counted in `skipped` without failing the run (R4.6).\n\n"
        "A `property_id` that is unknown, another tenant's, or not `ACTIVE` is a `422`: it is "
        "a field of the body naming something the tenant cannot reprice, not a missing "
        "resource in the path."
    ),
)
async def generate_price_recommendations(
    payload: GeneratePriceRecommendationsRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        GeneratePriceRecommendationsUseCase,
        Depends(get_generate_price_recommendations_use_case),
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> GenerationReportResponse:
    outcome = await use_case.execute(
        authenticated.context.tenant_id,
        now=now_utc(),
        property_id=payload.property_id,
        # **The actor is what makes this path audited**, and passing it is the whole
        # mechanism rather than a convenience: rule 9's fifth exception covers the clock and
        # only the clock, because "ausencia de actor" is true of the nightly run and false
        # here — this request carries a user and an IP. `_AuditWriter` is invoked exactly
        # when there is an actor, so a `None` slipped in here would silently buy the
        # exemption for a human (design D12/OQ1).
        actor=_actor(authenticated, client_ip),
    )
    return GenerationReportResponse(
        created=outcome.created,
        updated=outcome.updated,
        preserved=outcome.preserved,
        skipped=outcome.skipped,
    )


@router.patch(
    "/{recommendation_id}",
    response_model=PriceRecommendationResponse,
    summary="Approve, reject, or record a recommendation as published",
    description=(
        "Three moves and no others (R5.2, R5.3): `RECOMMENDED` → `APPROVED`, `RECOMMENDED` → "
        "`REJECTED`, and `APPROVED` → `APPLIED_EXTERNAL`. Anything else is a `409` with the "
        "status untouched (R5.4).\n\n"
        "`APPLIED_EXTERNAL` is the manager saying she published the price in the OTA herself: "
        "it puts a `PRICE_UPDATED_EXTERNAL` event on the property's timeline and writes its "
        "own audit action, because it records a fact rather than a decision (design D12, D14). "
        "**No transition calls the PMS** — Mode 1 recommends and never publishes (R5.5), and "
        "`current_price` stays `null` for the same reason."
    ),
)
async def decide_price_recommendation(
    recommendation_id: uuid.UUID,
    payload: DecidePriceRecommendationRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        DecidePriceRecommendationUseCase, Depends(get_decide_price_recommendation_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> PriceRecommendationResponse:
    recommendation = await use_case.execute(
        authenticated.context.tenant_id,
        recommendation_id,
        payload.status,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return PriceRecommendationResponse.from_domain(recommendation)
