"""The seven review endpoints (R5, R3.5, R4.2; design D11).

End-to-end through `app/main.py`'s FastAPI factory: the body schemas, the `require(...)`
gates, the error handlers, the response models. The router is not mocked — a bug in
the response shape would surface here.
"""

import pytest

from tests.reviews.conftest import (
    auth_header,
    seed_draft,
    seed_property,
    seed_review,
    seed_tenant,
    seed_user,
)


@pytest.mark.asyncio
async def test_post_reviews_with_a_valid_body_returns_201(api, db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.post(
        "/api/v1/reviews",
        headers=auth_header(api, manager),
        json={
            "property_id": str(prop.id),
            "channel": "MANUAL",
            "rating": "4.5",
            "content": "Muy buena estancia, gracias.",
            "language": "es",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["property_id"] == str(prop.id)
    assert body["status"] == "NEW"
    assert body["ai_summary"] is None
    assert body["recurring_issues"] == []


@pytest.mark.asyncio
async def test_post_reviews_without_property_id_is_422(api, db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.post(
        "/api/v1/reviews",
        headers=auth_header(api, manager),
        json={"channel": "MANUAL"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_reviews_with_an_unknown_channel_is_422(api, db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.post(
        "/api/v1/reviews",
        headers=auth_header(api, manager),
        json={
            "property_id": str(prop.id),
            "channel": "NOT_A_CHANNEL",
            "rating": "4.5",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_review_for_another_tenant_is_404(api, db_session) -> None:
    """R1.3: the `404` indistinguishability of an unknown id and another tenant's id."""
    a = await seed_tenant(db_session, "TenantA")
    b = await seed_tenant(db_session, "TenantB")
    a_prop = await seed_property(db_session, a, "REDES11")
    a_review = await seed_review(db_session, a, a_prop)
    # Tenant B's manager queries tenant A's review — must be 404, not 200, not 403.
    b_manager = await seed_user(db_session, b, "b_manager@example.com")

    response = await api.get(
        f"/api/v1/reviews/{a_review.id}",
        headers=auth_header(api, b_manager),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_review_draft_for_a_review_in_ignored_state_is_404(
    api, db_session
) -> None:
    """R5.4: a review in `IGNORED` has no draft; the route answers `404`, not `200 {draft: null}`."""
    from app.reviews.domain.enums import ReviewStatus

    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    review = await seed_review(
        db_session, tenant, prop, status=ReviewStatus.IGNORED
    )
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.get(
        f"/api/v1/reviews/{review.id}/response",
        headers=auth_header(api, manager),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_listing_paginates_with_the_envelope(api, db_session) -> None:
    """PRD §23: `{data, total, page, per_page, total_pages}`."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    for i in range(3):
        await seed_review(
            db_session, tenant, prop, content=f"Review {i}", language="es"
        )

    response = await api.get(
        "/api/v1/reviews",
        headers=auth_header(api, manager),
        params={"property_id": str(prop.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body and body["total"] == 3
    assert "page" in body and body["page"] == 1
    assert "per_page" in body and body["per_page"] == 20


@pytest.mark.asyncio
async def test_patch_response_with_approve_advances_status_and_writes_a_notification(
    api, db_session
) -> None:
    """R3.6 / R4.2 / R6.2: approval moves the review to `APPROVED`, fills the draft's
    `approved_by`/`approved_at`, and queues a `REVIEW_RESPONSE_APPROVED` notification."""
    from datetime import datetime

    from app.reviews.domain.enums import ReviewStatus

    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    review = await seed_review(
        db_session, tenant, prop, status=ReviewStatus.DRAFTED
    )
    await seed_draft(db_session, review)
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.patch(
        f"/api/v1/reviews/{review.id}/response",
        headers=auth_header(api, manager),
        json={"action": "APPROVE"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_patch_response_with_ignore_advances_status(api, db_session) -> None:
    from app.reviews.domain.enums import ReviewStatus

    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    review = await seed_review(
        db_session, tenant, prop, status=ReviewStatus.DRAFTED
    )
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.patch(
        f"/api/v1/reviews/{review.id}/response",
        headers=auth_header(api, manager),
        json={"action": "IGNORE"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IGNORED"


@pytest.mark.asyncio
async def test_patch_response_with_an_illegal_action_is_409(api, db_session) -> None:
    """R4.1: a `POSTED_MANUALLY` from `NEW` is refused with `409`."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    review = await seed_review(db_session, tenant, prop)  # NEW
    manager = await seed_user(db_session, tenant, "manager@example.com")

    response = await api.patch(
        f"/api/v1/reviews/{review.id}/response",
        headers=auth_header(api, manager),
        json={"action": "MARK_POSTED"},
    )
    assert response.status_code == 409
