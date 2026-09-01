"""One tenant never reads or writes another's reviews (R1.3).

Required of every new module by DoD §28.18 and rule 1 of `sdd/steering/security.md`,
and **load-bearing rather than ceremonial**: on a marked session the global listener
filters ORM reads by tenant, so a test that ran on a marked session could not fail
against a repository that had forgotten its `WHERE`. Marking would make this file
decorative.

The reviews module splits the isolation in two: `reviews` carries its own `tenant_id`
column (R1.1, an explicit divergence from `messages`/`review_response_drafts`),
and `review_response_drafts` joins `reviews` for the filter (D10). R1.3 enumerates the
paths: high (create, detail, list), approve/ignore/posted, regenerate/edit, summary.
"""

import pytest

from app.auth.domain.enums import UserRole
from app.reviews.domain.exceptions import ReviewNotFoundError
from app.reviews.infrastructure.models import ReviewModel, ReviewResponseDraftModel
from app.reviews.infrastructure.repositories import (
    SqlAlchemyReviewRepository,
    SqlAlchemyReviewResponseDraftRepository,
)
from tests.reviews.conftest import (
    auth_header,
    seed_draft,
    seed_property,
    seed_review,
    seed_tenant,
    seed_user,
)


async def two_tenants(db_session):
    """Tenant A with a review and a draft; tenant B with its own."""
    a = await seed_tenant(db_session, "TenantA")
    b = await seed_tenant(db_session, "TenantB")
    a_prop = await seed_property(db_session, a, "REDES11")
    b_prop = await seed_property(db_session, b, "PAJARITOS8")
    a_review = await seed_review(
        db_session, a, a_prop, content="Mensaje de A", language="es"
    )
    b_review = await seed_review(
        db_session, b, b_prop, content="Mensaje de B", language="es"
    )
    a_draft = await seed_draft(db_session, a_review)
    b_draft = await seed_draft(db_session, b_review)
    return a, b, a_review, b_review, a_draft, b_draft


async def _ensure_a_manager(db_session, a):
    from app.auth.domain.enums import UserRole

    return await seed_user(
        db_session, a, "manager-a@example.com", role=UserRole.PROPERTY_MANAGER
    )


@pytest.mark.asyncio
async def test_listing_reviews_for_property_never_shows_another_tenants(db_session) -> None:
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    page = await SqlAlchemyReviewRepository(db_session).list_for_property(
        a.id, a_review.property_id, filters=_filters(), page=1, per_page=50
    )
    assert [item.id for item in page.items] == [a_review.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_listing_reviews_for_tenant_never_shows_another_tenants(db_session) -> None:
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    page = await SqlAlchemyReviewRepository(db_session).list_for_tenant(
        a.id, _filters(), page=1, per_page=50
    )
    assert [item.id for item in page.items] == [a_review.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_reading_another_tenants_review_answers_none(db_session) -> None:
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewRepository(db_session)
    fetched = await repo.get(a.id, b_review.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_an_unknown_id_and_another_tenants_id_are_indistinguishable(
    db_session,
) -> None:
    """The `404` indistinguishability of R1.3: both are `None` here and `404` to the API.

    A repository that answered `None` only for unknown ids and raised for cross-tenant
    references would tell the caller that B's review exists, which is precisely the
    distinction R1.3 forbids.
    """
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewRepository(db_session)
    unknown_id = __import__("uuid").uuid4()
    assert await repo.get(a.id, unknown_id) is None
    assert await repo.get(a.id, b_review.id) is None


@pytest.mark.asyncio
async def test_reading_another_tenants_draft_is_refused(db_session) -> None:
    """`review_response_drafts` joins `reviews` to filter (D10); the raise is the
    only thing the adapter does that is not `None` — for an unknown parent AND for a
    parent of another tenant, the same `ReviewNotFoundError`.
    """
    a, b, a_review, b_review, a_draft, b_draft, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewResponseDraftRepository(db_session)
    with pytest.raises(ReviewNotFoundError):
        await repo.get(a.id, b_draft.id)


@pytest.mark.asyncio
async def test_an_unknown_draft_id_and_another_tenants_draft_are_indistinguishable(
    db_session,
) -> None:
    a, b, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewResponseDraftRepository(db_session)
    unknown_draft = __import__("uuid").uuid4()
    with pytest.raises(ReviewNotFoundError):
        await repo.get(a.id, unknown_draft)


@pytest.mark.asyncio
async def test_get_for_review_never_returns_another_tenants_draft(
    db_session,
) -> None:
    a, b, a_review, b_review, a_draft, b_draft, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewResponseDraftRepository(db_session)
    assert await repo.get_for_review(a.id, b_review.id) is None


@pytest.mark.asyncio
async def test_writing_a_review_into_another_tenants_property_is_refused(
    db_session,
) -> None:
    """The repository `save` raises `CrossTenantWriteError` when the entity carries
    a tenant id that does not match the acting tenant. Same defence as
    `SqlAlchemyConversationRepository.save`."""
    from app.core.tenancy import CrossTenantWriteError

    a, b, a_review, *_ = await two_tenants(db_session)
    repo = SqlAlchemyReviewRepository(db_session)
    a_review.sentiment = __import__(
        "app.reviews.domain.enums"
    ).ReviewSentiment.POSITIVE
    with pytest.raises(CrossTenantWriteError):
        await repo.save(b.id, a_review)


@pytest.mark.asyncio
async def test_reviews_still_has_a_tenant_column(db_session) -> None:
    """R1.1: `reviews.tenant_id` is its own column, **not** scoped transitively through a
    parent. The test is a tripwire — if a future migration drops the column, every
    listing becomes a tenant leak."""
    assert "tenant_id" in ReviewModel.__table__.columns


@pytest.mark.asyncio
async def test_review_response_drafts_still_has_no_tenant_column(db_session) -> None:
    """The asymmetry with `messages`: `review_response_drafts` carries no `tenant_id`
    and the join in `get_for_review` is the only isolation. A future migration that
    adds the column is welcome — but the test pins the design choice."""
    assert "tenant_id" not in ReviewResponseDraftModel.__table__.columns


@pytest.mark.asyncio
async def test_approving_another_tenants_review_is_indistinguishable_from_missing(
    api,
    db_session,
) -> None:
    """The `PATCH /reviews/{id}/response` route answers `404` for both, and the body
    must not let the caller tell which. R1.3 again."""
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    a_manager = await _ensure_a_manager(db_session, a)
    headers = auth_header(api, a_manager)
    response = await api.patch(
        f"/api/v1/reviews/{b_review.id}/response",
        headers=headers,
        json={"action": "APPROVE"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_summary_never_includes_another_tenants_review(
    api,
    db_session,
) -> None:
    a, b, a_review, b_review, *_ = await two_tenants(db_session)
    a_manager = await _ensure_a_manager(db_session, a)
    headers = auth_header(api, a_manager)
    response = await api.get(
        f"/api/v1/properties/{a_review.property_id}/reviews/summary",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["by_sentiment"] == {}
    assert body["by_recurring_issue"] == {}


# --- helpers ---


def _filters():
    from app.reviews.domain.ports import ReviewFilters

    return ReviewFilters()


@pytest.mark.asyncio
async def test_the_session_these_tests_run_on_is_not_tenant_marked(db_session) -> None:
    """On a marked session the global listener filters by tenant, so this whole file
    would be decorative. Pin the assumption."""
    from sqlalchemy import select

    from app.reviews.infrastructure.models import ReviewModel

    bound = await db_session.execute(
        select(ReviewModel).execution_options(populate_existing=True)
    )
    rows = bound.scalars().all()
    # The two tenants seeded above produced two reviews; if the session were marked
    # the listener would filter to one. Both being visible is the property under test.
    tenant_ids = {r.tenant_id for r in rows}
    assert len(tenant_ids) >= 2
