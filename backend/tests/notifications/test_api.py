"""`GET /api/v1/notifications` — the in-app inbox (R4, design D6).

Three things are worth an endpoint test here, and only one of them is the happy path:
the scoping is **per user**, not per tenant, and the response must not publish
`recipient_contact` or `last_error`.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.notifications.domain.enums import NotificationStatus
from tests.notifications.conftest import auth_header, insert_notification

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_user_sees_their_own_notifications_newest_first(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    manager = users_by_role_a["PROPERTY_MANAGER"]
    older = await insert_notification(
        db_session,
        tenant_a,
        recipient=manager,
        subject="first",
        created_at=NOW - timedelta(hours=1),
    )
    newer = await insert_notification(
        db_session, tenant_a, recipient=manager, subject="second", created_at=NOW
    )

    response = await api.get("/api/v1/notifications", headers=auth_header(api, manager))

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["id"] for item in payload["data"]] == [str(newer.id), str(older.id)]


@pytest.mark.asyncio
async def test_a_user_never_sees_a_colleagues_notifications(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Scoped by recipient, not by tenant. A cleaner and a manager share a tenant."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    cleaner = users_by_role_a["CLEANER"]
    await insert_notification(db_session, tenant_a, recipient=manager, subject="for the manager")

    response = await api.get("/api/v1/notifications", headers=auth_header(api, cleaner))

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_a_user_never_sees_another_tenants_notifications(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    await insert_notification(db_session, tenant_b, recipient=theirs, subject="theirs")
    mine = users_by_role_a["PROPERTY_MANAGER"]

    response = await api.get("/api/v1/notifications", headers=auth_header(api, mine))

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_the_response_publishes_the_message_and_nothing_operational(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`recipient_contact` and `last_error` stay server-side (`api/schemas.py`).

    `body` DOES travel, carrying the masked access code shape rule 11 of
    `steering/security.md` sanctions — that exception exists so the recipient can read it.
    """
    manager = users_by_role_a["PROPERTY_MANAGER"]
    await insert_notification(
        db_session,
        tenant_a,
        recipient=manager,
        body="Your door code is ****23.",
        status=NotificationStatus.FAILED,
        last_error='{"code": "TIMEOUT", "channel": "IN_APP", "attempt": 3}',
    )

    response = await api.get("/api/v1/notifications", headers=auth_header(api, manager))

    [item] = response.json()["data"]
    assert item["body"] == "Your door code is ****23."
    assert "recipient_contact" not in item
    assert "last_error" not in item
    assert "sla_deadline_at" not in item
    assert "sla_breached" not in item
    assert manager.email not in response.text


@pytest.mark.asyncio
async def test_the_page_envelope_is_the_one_prd_23_declares(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    manager = users_by_role_a["PROPERTY_MANAGER"]
    for index in range(3):
        await insert_notification(
            db_session, tenant_a, recipient=manager, subject=f"n{index}"
        )

    response = await api.get(
        "/api/v1/notifications?page=2&per_page=2", headers=auth_header(api, manager)
    )

    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["per_page"] == 2
    assert payload["total_pages"] == 2
    assert len(payload["data"]) == 1


@pytest.mark.asyncio
async def test_every_authenticated_role_may_read_its_own_inbox(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`READ_OWN_NOTIFICATIONS` is self-service: a cleaner is notified as much as an owner,
    and the scoping that makes it safe lives in the repository, not in the permission."""
    for role in ("TENANT_OWNER", "PROPERTY_MANAGER", "CLEANER", "TECHNICIAN"):
        user = users_by_role_a[role]
        response = await api.get("/api/v1/notifications", headers=auth_header(api, user))
        assert response.status_code == 200, role


@pytest.mark.asyncio
async def test_an_anonymous_request_is_refused(api) -> None:
    response = await api.get("/api/v1/notifications")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_page_and_per_page_are_bounded(api, users_by_role_a) -> None:
    manager = users_by_role_a["PROPERTY_MANAGER"]

    too_large = await api.get(
        "/api/v1/notifications?per_page=1000", headers=auth_header(api, manager)
    )
    huge_page = await api.get(
        "/api/v1/notifications?page=99999999999999999999", headers=auth_header(api, manager)
    )

    assert too_large.status_code == 422
    assert huge_page.status_code == 422
