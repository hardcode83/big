"""The read path coerces unknown `recurring_issues` tags the same way the entity does (R2.2, design D7).

`_coerce_recurring_issues` lives in `app/reviews/domain/entities.py` and the SQLAlchemy
adapter reuses it on the way out (`SqlAlchemyReviewRepository._to_review`). This file is the
contract that keeps the two paths on the same degradation rule: a row that landed with a tag
outside `RecurringIssueTag` — because the entity guard was added later, or because a writer
bypassed the type — has to come back as `(..., OTHER, ...)` with a `logger.warning`, not blow
the whole read with `ValueError`. The vocabulary sweep in `test_recurring_issues_vocabulary.py`
covers the writer side; this one closes the read-side half of D7.
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest

from app.reviews.domain.enums import RecurringIssueTag
from app.reviews.infrastructure.models import ReviewModel
from app.reviews.infrastructure.repositories import SqlAlchemyReviewRepository
from app.tenants.infrastructure.models import TenantModel
from app.properties.infrastructure.models import PropertyModel


async def _seed_row(db_session, *, recurring_issues: list | None) -> ReviewModel:
    tenant = TenantModel(
        id=uuid.uuid4(),
        name="TenantA",
        billing_email="tenant-a@example.com",
    )
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="REDES11",
        internal_code="REDES11",
    )
    db_session.add(prop)
    await db_session.flush()
    now = datetime.now(UTC)
    review = ReviewModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="MANUAL",
        status="NEW",
        reviewer_name="Anonymous",
        content="Some body",
        language="es",
        recurring_issues=recurring_issues,
        created_at=now,
        updated_at=now,
    )
    db_session.add(review)
    await db_session.flush()
    return review


@pytest.mark.asyncio
async def test_read_coerces_unknown_tag_to_other_with_warning(db_session, caplog) -> None:
    """A row that landed with `recurring_issues=["NOT_A_TAG", "WIFI"]` reads back as
    `(OTHER, WIFI)` — the same shape the entity guard produces at construction time —
    and the warning D7 names is emitted exactly once for the unknown value."""
    seeded = await _seed_row(
        db_session,
        recurring_issues=["NOT_A_TAG", RecurringIssueTag.WIFI.value],
    )
    with caplog.at_level(
        logging.WARNING, logger="app.reviews.domain.entities"
    ):
        fetched = await SqlAlchemyReviewRepository(db_session).get(
            seeded.tenant_id, seeded.id
        )
    assert fetched is not None
    assert tuple(fetched.recurring_issues) == (
        RecurringIssueTag.OTHER,
        RecurringIssueTag.WIFI,
    )
    warnings = [
        record
        for record in caplog.records
        if record.message == "reviews.recurring_issues.dropped_unknown_tag"
    ]
    assert len(warnings) == 1, (
        "D7 names the warning as the read-side degradation signal; "
        f"got {len(warnings)}: {[r.message for r in warnings]}"
    )
    assert getattr(warnings[0], "unknown_value", None) == repr("NOT_A_TAG")


@pytest.mark.asyncio
async def test_read_with_clean_tags_does_not_warn(db_session, caplog) -> None:
    """The coercer is silent for a row that only carries known tags — a warning per read
    would be noise that hides the real degradation signal."""
    seeded = await _seed_row(
        db_session,
        recurring_issues=[RecurringIssueTag.WIFI.value, RecurringIssueTag.NOISE.value],
    )
    with caplog.at_level(
        logging.WARNING, logger="app.reviews.domain.entities"
    ):
        fetched = await SqlAlchemyReviewRepository(db_session).get(
            seeded.tenant_id, seeded.id
        )
    assert fetched is not None
    assert set(fetched.recurring_issues) == {
        RecurringIssueTag.WIFI,
        RecurringIssueTag.NOISE,
    }
    assert not [
        r
        for r in caplog.records
        if r.message == "reviews.recurring_issues.dropped_unknown_tag"
    ]


@pytest.mark.asyncio
async def test_read_with_null_recurring_issues_does_not_coerce(db_session) -> None:
    """`NULL` is a real value (R2.1: the row was created and the classification hasn't run
    yet). The coercer returns `()` rather than `None`, so the read path keeps the empty
    tuple shape downstream — same as the entity at construction."""
    seeded = await _seed_row(db_session, recurring_issues=None)
    fetched = await SqlAlchemyReviewRepository(db_session).get(
        seeded.tenant_id, seeded.id
    )
    assert fetched is not None
    assert fetched.recurring_issues == ()
