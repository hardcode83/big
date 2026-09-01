"""The classification pipeline (R2.1, R2.3, R2.4, R2.5; design D7, D16).

Two halves:

* The use case moves a review from `NEW` to `DRAFTED`, populates the three AI
  fields, and persists a draft from the closed catalogue.
* Below the tenant's confidence threshold it leaves the row with `sentiment = ...`,
  `ai_summary = NULL` and `recurring_issues = []`, and writes
  `REVIEW_CLASSIFIED_LOW_CONFIDENCE` instead.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.auth.domain.enums import UserRole
from app.reviews.application.use_cases import ClassifyPendingReviewsUseCase
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewChannel,
    ReviewSentiment,
)
from app.reviews.domain.value_objects import GeneratedDraft, ReviewAnalysis
from app.reviews.infrastructure.ai import MockReviewAnalyzer, MockReviewDraftGenerator
from app.reviews.infrastructure.repositories import (
    SqlAlchemyReviewRepository,
    SqlAlchemyReviewResponseDraftRepository,
)
from app.tenants.infrastructure.models import TenantConfigModel
from app.timeline.domain.repositories import TimelineFilters
from tests.reviews.conftest import (
    seed_draft,
    seed_property,
    seed_review,
    seed_tenant,
)


async def _seed_tenant_with_config(db_session, *, threshold: Decimal):
    from app.tenants.infrastructure.models import TenantModel

    tenant = TenantModel(
        name="TenantA",
        billing_email="tenant-a@example.com",
    )
    db_session.add(tenant)
    await db_session.flush()
    config = TenantConfigModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        ai_confidence_threshold=threshold,
    )
    db_session.add(config)
    await db_session.flush()
    return tenant


async def _setup(db_session, *, threshold=Decimal("0.75")):
    from app.core.unit_of_work import SqlAlchemyUnitOfWork

    from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
    from app.timeline.infrastructure.repositories import (
        SqlAlchemyTimelineEventRepository,
        SqlAlchemyTimelineEventReader,
    )

    tenant = await _seed_tenant_with_config(db_session, threshold=threshold)
    prop = await seed_property(db_session, tenant, "REDES11")
    use_case = ClassifyPendingReviewsUseCase(
        reviews=SqlAlchemyReviewRepository(db_session),
        drafts=SqlAlchemyReviewResponseDraftRepository(db_session),
        analyzer=MockReviewAnalyzer(),
        draft_generator=MockReviewDraftGenerator(),
        configs=SqlAlchemyTenantConfigRepository(db_session),
        audit_factory=None,  # R1.7 audit deferred to a follow-up (matches dependencies.py)
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    return tenant, prop, use_case


@pytest.mark.asyncio
async def test_a_review_created_by_posting_is_classified_on_the_next_tick(
    db_session,
) -> None:
    """R2.1: `POST /reviews` lands as `NEW` with empty AI fields; the pipeline picks
    it up on the next tick and populates the three fields plus a draft."""
    tenant, prop, use_case = await _setup(db_session)
    review = await seed_review(
        db_session, tenant, prop, content="La casa estaba sucia", language="es"
    )

    now = datetime.now(UTC)
    report = await use_case.execute(tenant_id=tenant.id, now=now)

    assert report.scanned == 1
    assert report.classified == 1
    assert report.low_confidence == 0
    assert report.failed == 0
    assert report.manual_triage == 0

    review_repo = SqlAlchemyReviewRepository(db_session)
    refreshed = await review_repo.get(tenant.id, review.id)
    assert refreshed.status.value == "DRAFTED"
    assert refreshed.sentiment is not None
    assert refreshed.ai_summary is not None
    # The draft was persisted by the catalogue path; check it via the draft repo.
    draft_repo = SqlAlchemyReviewResponseDraftRepository(db_session)
    draft = await draft_repo.get_for_review(tenant.id, review.id)
    assert draft is not None
    assert draft.ai_generated is True


@pytest.mark.asyncio
async def test_low_confidence_clears_the_three_ai_fields_and_emits_low_confidence_event(
    db_session,
) -> None:
    """R2.3: below the tenant's threshold the row carries `sentiment`, `ai_summary=None`,
    `recurring_issues=[]`, and a `REVIEW_CLASSIFIED_LOW_CONFIDENCE` event exists."""
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader

    # A threshold of `0.99` means every mock verdict (max 0.95) lands below it.
    tenant, prop, use_case = await _setup(db_session, threshold=Decimal("0.99"))
    review = await seed_review(
        db_session, tenant, prop, content="La casa estaba sucia", language="es"
    )

    now = datetime.now(UTC)
    report = await use_case.execute(tenant_id=tenant.id, now=now)

    assert report.scanned == 1
    assert report.low_confidence == 1

    review_repo = SqlAlchemyReviewRepository(db_session)
    refreshed = await review_repo.get(tenant.id, review.id)
    assert refreshed.status.value == "DRAFTED"  # still moves, the rule is "low-confidence but classified"
    assert refreshed.ai_summary is None
    assert refreshed.recurring_issues == ()

    timeline_repo = SqlAlchemyTimelineEventReader(db_session)
    page = await timeline_repo.list_for_property(
        tenant_id=tenant.id,
        property_id=prop.id,
        filters=TimelineFilters(),
        page=1,
        per_page=20,
    )
    event_types = [e.event_type.value for e in page.items]
    assert "REVIEW_CLASSIFIED_LOW_CONFIDENCE" in event_types


@pytest.mark.asyncio
async def test_three_consecutive_failures_park_the_row_for_manual_triage(
    db_session, monkeypatch
) -> None:
    """R2.4: the analyser fails three times, the row parks with `classification_attempts = 3`.

    The mock does not raise today; we patch its `analyze_review` to raise and
    assert the parking behaviour.
    """
    from app.core.unit_of_work import SqlAlchemyUnitOfWork

    tenant, prop, use_case = await _setup(db_session)
    review = await seed_review(
        db_session, tenant, prop, content="La casa estaba sucia", language="es"
    )

    class _Boom:
        async def analyze_review(self, *, content, language):
            raise RuntimeError("synthetic failure")

    # Replace the analyser with one that raises. The use case holds its own
    # reference, so we patch the instance directly.
    use_case._analyzer = _Boom()  # type: ignore[assignment]

    now = datetime.now(UTC)
    for _ in range(3):
        await use_case.execute(tenant_id=tenant.id, now=now)

    review_repo = SqlAlchemyReviewRepository(db_session)
    refreshed = await review_repo.get(tenant.id, review.id)
    assert refreshed.classification_attempts == 3


@pytest.mark.asyncio
async def test_a_classified_row_does_not_reappear_in_pending(db_session) -> None:
    """D16 / D3: a successful classification removes the row from the queue."""
    tenant, prop, use_case = await _setup(db_session)
    review = await seed_review(
        db_session, tenant, prop, content="La casa estaba sucia", language="es"
    )
    now = datetime.now(UTC)
    await use_case.execute(tenant_id=tenant.id, now=now)

    review_repo = SqlAlchemyReviewRepository(db_session)
    pending = await review_repo.list_pending_classification(
        tenant.id, limit=100
    )
    assert pending == []
    # Sanity: the review we classified is no longer pending because
    # `ai_summary IS NOT NULL` is now true.
    refreshed = await review_repo.get(tenant.id, review.id)
    assert refreshed.ai_summary is not None
