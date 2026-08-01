from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.properties.infrastructure.models import PropertyModel
from app.reviews.domain.enums import ReviewChannel
from app.reviews.infrastructure.models import ReviewModel, ReviewResponseDraftModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant_property(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


async def _review(db_session) -> ReviewModel:
    tenant, prop = await _tenant_property(db_session)
    review = ReviewModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReviewChannel.AIRBNB,
        reviewer_name="Ana",
        rating=Decimal("4.5"),
        content="Great flat, noisy street.",
    )
    db_session.add(review)
    await db_session.flush()
    return review


@pytest.mark.asyncio
async def test_review_roundtrip_applies_the_prd_defaults(db_session) -> None:
    review = await _review(db_session)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(ReviewModel).where(ReviewModel.id == review.id))
    ).scalar_one()
    assert fetched.status.value == "NEW"
    assert fetched.sentiment is None
    assert fetched.reservation_id is None
    assert fetched.rating == Decimal("4.5")


@pytest.mark.asyncio
async def test_review_property_restrict_on_delete(db_session) -> None:
    """`reviews.property_id` is the model's own mandatory FK (R3.7, D8).

    Without this, dropping `ondelete="RESTRICT"` from it would leave the suite green:
    every other DB-level test in this file drives ReviewResponseDraftModel.
    """
    review = await _review(db_session)
    await db_session.commit()

    prop = await db_session.get(PropertyModel, review.property_id)
    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_review_response_draft_is_unique_per_review(db_session) -> None:
    review = await _review(db_session)

    for content in ("first draft", "second draft"):
        db_session.add(
            ReviewResponseDraftModel(review_id=review.id, draft_content=content, language="en")
        )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_review_response_draft_approver_set_null_on_user_delete(db_session) -> None:
    review = await _review(db_session)
    approver = UserModel(
        tenant_id=review.tenant_id,
        name="Manager Mar",
        email="mar@example.com",
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(approver)
    await db_session.flush()

    draft = ReviewResponseDraftModel(
        review_id=review.id,
        draft_content="Thank you for staying with us.",
        language="en",
        approved_by=approver.id,
    )
    db_session.add(draft)
    await db_session.commit()

    await db_session.delete(approver)
    await db_session.commit()
    await db_session.refresh(draft)

    assert draft.approved_by is None
    assert draft.ai_generated is True


@pytest.mark.asyncio
async def test_review_response_draft_review_restrict_on_delete(db_session) -> None:
    review = await _review(db_session)
    db_session.add(
        ReviewResponseDraftModel(review_id=review.id, draft_content="draft", language="es")
    )
    await db_session.commit()

    await db_session.delete(review)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_review_response_drafts_has_no_tenant_id_column(db_session) -> None:
    assert "tenant_id" not in ReviewResponseDraftModel.__table__.columns
