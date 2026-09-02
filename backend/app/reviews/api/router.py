"""The seven review endpoints of PRD §18 (R5, R3.5, R4.2; design D11, D12).

| Route | Method | Permission |
|---|---|---|
| `/api/v1/reviews` | `POST` | `CREATE_REVIEW` |
| `/api/v1/reviews` | `GET` | `READ_REVIEWS` |
| `/api/v1/reviews/{id}` | `GET` | `READ_REVIEWS` |
| `/api/v1/reviews/{id}/response` | `GET` | `READ_REVIEWS` |
| `/api/v1/reviews/{id}/response` | `POST` | `APPROVE_REVIEW` (regenerate) |
| `/api/v1/reviews/{id}/response` | `PATCH` | `APPROVE_REVIEW` / `IGNORE_REVIEW` / `MARK_REVIEW_POSTED` |
| `/api/v1/properties/{id}/reviews/summary` | `GET` | `READ_REVIEWS` |

Seven endpoints, each one declaring its permission with `require(...)`. The
indistinguishable `404` of R1.3 is the use case's, not the router's — see
`api/errors.py`.
"""

import uuid
from typing import Annotated, Mapping

from fastapi import APIRouter, Depends, Query, Request

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
)
from app.auth.domain.policy import Permission, is_allowed
from app.core.errors import ForbiddenError
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.reviews.api.dependencies import (
    get_approve_review_use_case,
    get_create_review_use_case,
    get_edit_review_draft_use_case,
    get_get_review_draft_use_case,
    get_get_review_use_case,
    get_ignore_review_use_case,
    get_list_reviews_summary_use_case,
    get_list_reviews_use_case,
    get_mark_posted_manually_use_case,
    get_regenerate_review_draft_use_case,
)
from app.reviews.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    CreateReviewRequest,
    RegenerateReviewDraftRequest,
    ReviewDraftResponse,
    ReviewPageResponse,
    ReviewResponse,
    ReviewResponseActionRequest,
    ReviewSummaryResponse,
)
from app.reviews.application.use_cases import (
    ApproveReviewUseCase,
    CreateReviewUseCase,
    EditReviewDraftUseCase,
    GetReviewDraftUseCase,
    GetReviewUseCase,
    IgnoreReviewUseCase,
    ListReviewsSummaryForPropertyUseCase,
    ListReviewsUseCase,
    MarkPostedManuallyUseCase,
    RegenerateReviewDraftUseCase,
)
from app.reviews.domain.enums import (
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)
from app.reviews.domain.ports import ReviewFilters

router = APIRouter(prefix="/reviews", tags=["reviews"], responses=AUTHENTICATED_RESPONSES)

#: Each route declares its permission with `require(...)`, which
#: `tests/test_route_authorization.py` walks. The annotated dependency is the public name
#: the router reaches for.
ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_REVIEWS))]
CreateDep = Annotated[AuthenticatedRequest, Depends(require(Permission.CREATE_REVIEW))]
# `ApproveDep` is the single signature-level gate that the regenerate-draft route
# declares — regenerating a draft requires approval rights per the proposal. The
# `act_on_review_response` PATCH route does NOT use any of these named deps: each
# PATCH verb is gated on its own permission (R4.2) and declaring three
# `Depends(require(...))` would make FastAPI resolve all three regardless of
# `body.action`. The per-action mapping lives in `PATCH_ACTION_PERMISSIONS`
# below and is enforced inside the handler with `is_allowed(role, permission)`.
ApproveDep = Annotated[AuthenticatedRequest, Depends(require(Permission.APPROVE_REVIEW))]


#: Per-action permission gate (R4.2). `body.action` is the `Literal["APPROVE" | …]`
#: from `ReviewResponseActionRequest` — keys are exactly those literals. The
#: `EDIT` branch shares `APPROVE_REVIEW` because editing the draft is a permission
#: the proposal reserves to whoever can approve; the design D5 wording ties the two.
PATCH_ACTION_PERMISSIONS: Mapping[str, Permission] = {
    "APPROVE": Permission.APPROVE_REVIEW,
    "IGNORE": Permission.IGNORE_REVIEW,
    "MARK_POSTED": Permission.MARK_REVIEW_POSTED,
    "EDIT": Permission.APPROVE_REVIEW,
}


@router.get(
    "",
    response_model=ReviewPageResponse,
    summary="List reviews",
    description=(
        "The inbox. Filtered by `property_id`, `channel`, `sentiment`, `status`, "
        "`rating_min`/`rating_max` and `date_from`/`date_to`, paginated with "
        "`page`/`per_page` (PRD §23). Ordered by `published_at` descending with "
        "**nulls last** — a review without a publication date must not sit above the "
        "ones that do."
    ),
)
async def list_reviews(
    authenticated: ReadDep,
    use_case: Annotated[ListReviewsUseCase, Depends(get_list_reviews_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    channel_filter: Annotated[ReviewChannel | None, Query(alias="channel")] = None,
    sentiment: ReviewSentiment | None = None,
    status_filter: Annotated[ReviewStatus | None, Query(alias="status")] = None,
    rating_min: float | None = None,
    rating_max: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ReviewPageResponse:
    from datetime import datetime

    filters = ReviewFilters(
        property_id=property_id,
        channel=channel_filter,
        sentiment=sentiment,
        status=status_filter,
        rating_min=None if rating_min is None else __import__("decimal").Decimal(str(rating_min)),
        rating_max=None if rating_max is None else __import__("decimal").Decimal(str(rating_max)),
        date_from=None if date_from is None else datetime.fromisoformat(date_from),
        date_to=None if date_to is None else datetime.fromisoformat(date_to),
    )
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=filters,
        page=page,
        per_page=per_page,
        property_id=property_id,
    )
    return ReviewPageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
    summary="Create a review",
    description=(
        "R5.1 — the manager creates a review manually (no PMS adapter in this change). "
        "The pipeline runs asynchronously; the row is born `NEW` with `sentiment = "
        "NEUTRAL`, `ai_summary = NULL` and `recurring_issues = []`."
    ),
)
async def create_review(
    authenticated: CreateDep,
    request: Request,
    use_case: Annotated[CreateReviewUseCase, Depends(get_create_review_use_case)],
    body: CreateReviewRequest,
) -> ReviewResponse:
    review = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        property_id=body.property_id,
        channel=body.channel,
        actor_ip=get_client_ip(request),
        reviewer_name=body.reviewer_name,
        rating=body.rating,
        content=body.content,
        language=body.language,
        reservation_id=body.reservation_id,
        now=now_utc(),
    )
    return ReviewResponse.from_domain(review)


@router.get(
    "/{review_id}",
    response_model=ReviewResponse,
    summary="Get a review",
    description="R5.4 — one review, with the `404` indistinguishability of R1.3.",
)
async def get_review(
    authenticated: ReadDep,
    use_case: Annotated[GetReviewUseCase, Depends(get_get_review_use_case)],
    review_id: uuid.UUID,
) -> ReviewResponse:
    review = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, review_id=review_id
    )
    return ReviewResponse.from_domain(review)


@router.get(
    "/{review_id}/response",
    response_model=ReviewDraftResponse,
    summary="Get the draft of a review",
    description=(
        "R5.4 — the draft of one review, or `404` indistinguishably (the same response "
        "is the answer for 'no review', 'another tenant' and 'role cannot read')."
    ),
)
async def get_review_draft(
    authenticated: ReadDep,
    use_case: Annotated[GetReviewDraftUseCase, Depends(get_get_review_draft_use_case)],
    review_id: uuid.UUID,
) -> ReviewDraftResponse:
    draft = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, review_id=review_id
    )
    return ReviewDraftResponse.from_domain(draft)


@router.post(
    "/{review_id}/response",
    response_model=ReviewDraftResponse,
    summary="Regenerate the draft of a review",
    description=(
        "R3.5 / D5 — replace the existing draft with a new one in a single transaction. "
        "`ai_generated` stays `TRUE`."
    ),
)
async def regenerate_review_draft(
    authenticated: ApproveDep,
    use_case: Annotated[
        RegenerateReviewDraftUseCase, Depends(get_regenerate_review_draft_use_case)
    ],
    review_id: uuid.UUID,
    body: RegenerateReviewDraftRequest | None = None,
) -> ReviewDraftResponse:
    _ = body  # R3.5 currently ignores the optional language override.
    draft = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        review_id=review_id,
        now=now_utc(),
    )
    return ReviewDraftResponse.from_domain(draft)


@router.patch(
    "/{review_id}/response",
    response_model=ReviewResponse,
    summary="Act on the review response (approve / ignore / mark posted / edit)",
    description=(
        "R3.5 / R4.2 — `action` picks the verb. `EDIT` requires `draft_content`; the "
        "others do not."
    ),
)
async def act_on_review_response(
    authenticated: Annotated[
        AuthenticatedRequest,
        Depends(
            require(Permission.APPROVE_REVIEW)  # narrowest; the use case does the rest
        ),
    ],
    use_case_approve: Annotated[
        ApproveReviewUseCase, Depends(get_approve_review_use_case)
    ],
    use_case_ignore: Annotated[
        IgnoreReviewUseCase, Depends(get_ignore_review_use_case)
    ],
    use_case_posted: Annotated[
        MarkPostedManuallyUseCase, Depends(get_mark_posted_manually_use_case)
    ],
    use_case_edit: Annotated[
        EditReviewDraftUseCase, Depends(get_edit_review_draft_use_case)
    ],
    use_case_get: Annotated[
        GetReviewUseCase, Depends(get_get_review_use_case)
    ],
    review_id: uuid.UUID,
    body: ReviewResponseActionRequest,
    request: Request,
) -> ReviewResponse | ReviewDraftResponse:
    """One route, four verbs, each gated on its **own** permission (R4.2).

    The signature declares the **broadest** required gate (`APPROVE_REVIEW`) so the
    route walk in `tests/test_route_authorization.py` sees an authenticated route,
    but the body enforces the action-specific permission with `is_allowed(role, ...)`
    — so a manager who only holds `IGNORE_REVIEW` is allowed through to do exactly
    that, not blocked because they do not also hold `APPROVE_REVIEW` and
    `MARK_REVIEW_POSTED`. That was the original panel finding the review caught.
    """
    role = authenticated.context.role
    required = PATCH_ACTION_PERMISSIONS[body.action]
    if not is_allowed(role, required):
        raise ForbiddenError(
            f"action {body.action.value} requires permission {required.name}"
        )

    tenant_id = authenticated.context.tenant_id
    actor_user_id = authenticated.context.user_id
    now = now_utc()
    actor_ip = get_client_ip(request)

    if body.action == "APPROVE":
        review = await use_case_approve.execute(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            review_id=review_id,
            now=now,
        )
        return ReviewResponse.from_domain(review)

    if body.action == "IGNORE":
        review = await use_case_ignore.execute(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            review_id=review_id,
            now=now,
        )
        return ReviewResponse.from_domain(review)

    if body.action == "MARK_POSTED":
        review = await use_case_posted.execute(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            review_id=review_id,
            now=now,
        )
        return ReviewResponse.from_domain(review)

    # `EDIT` — the draft body is required and the response shape is the draft, not
    # the review. The draft row is read back through a use case (`GetReviewUseCase`)
    # rather than reaching into the `_drafts` repository, so the route stays a
    # one-line dispatch on `body.action`.
    if body.draft_content is None:
        from app.reviews.domain.exceptions import ReviewValidationError

        raise ReviewValidationError(
            "draft_content is required when action = EDIT"
        )
    await use_case_edit.execute(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        review_id=review_id,
        new_content=body.draft_content,
        now=now,
    )
    draft = await use_case_get.execute(
        tenant_id=tenant_id,
        review_id=review_id,
        now=now,
    )
    return ReviewDraftResponse.from_domain(draft)


#: A second router for `/properties/{id}/reviews/summary` — R5.5. Mounted separately
#: from `reviews_router` because a literal segment under `/properties` collides with
#: `/properties/{id}` and the registration order would decide which wins
#: (`cleaning-stall-blocks-next-stay` D7 makes the same point for `/properties`).
summary_router = APIRouter(
    prefix="/properties",
    tags=["reviews"],
    responses=AUTHENTICATED_RESPONSES,
)


@summary_router.get(
    "/{property_id}/reviews/summary",
    response_model=ReviewSummaryResponse,
    summary="Per-property review summary",
    description=(
        "R5.5 — sentiment histogram and top-N recurring-issue counts of the property's "
        "reviews in the last 90 days. `top_n` defaults to the tenant's "
        "`review_recurring_issues_top_n`."
    ),
)
async def list_reviews_summary_for_property(
    authenticated: ReadDep,
    use_case: Annotated[
        ListReviewsSummaryForPropertyUseCase, Depends(get_list_reviews_summary_use_case)
    ],
    property_id: uuid.UUID,
    window_days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> ReviewSummaryResponse:
    summary = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        property_id=property_id,
        window_days=window_days,
        now=now_utc(),
    )
    return ReviewSummaryResponse(**summary)
