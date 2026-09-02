"""The in-app inbox endpoints (`access-notifications` R4 design D6, and
`notifications-inbox-web`).

Three things were worth an endpoint test when the listing was the only route, and only one
of them is the happy path: the scoping is **per user**, not per tenant, and the response
must not publish `recipient_contact` or `last_error`.

`notifications-inbox-web` adds the three that close the cycle, and what they are worth
testing for is the same shape of thing: the acknowledgement is idempotent (R1.3), its three
failure cases answer one indistinguishable `404` (R1.4), and the counter does not depend on
the page size (R2.2).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.infrastructure.models import NotificationLogModel
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
async def test_activating_email_does_not_change_how_many_items_the_inbox_returns(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R5.4: `notification_email_enabled` changes what channels a notification fans out
    to, never what `GET /api/v1/notifications` shows for a given set of avisos.

    Two notifications, each fanned out to all three channels — the shape production
    writes once the tenant's email and WhatsApp flags are both on. The inbox reads
    `channel = IN_APP` regardless, so the item count it returns is the count of avisos,
    not of rows: activating email must not double it.
    """
    manager = users_by_role_a["PROPERTY_MANAGER"]
    for _ in range(2):
        related_id = uuid.uuid4()
        for channel in (
            NotificationChannel.IN_APP,
            NotificationChannel.EMAIL,
            NotificationChannel.WHATSAPP,
        ):
            db_session.add(
                NotificationLogModel(
                    tenant_id=tenant_a.id,
                    recipient_user_id=manager.id,
                    recipient_contact=manager.email,
                    channel=channel,
                    notification_type="CLEANING_TASK_ASSIGNED",
                    related_type="cleaning_task",
                    related_id=related_id,
                    status=NotificationStatus.SENT,
                )
            )
    await db_session.flush()

    response = await api.get("/api/v1/notifications", headers=auth_header(api, manager))

    payload = response.json()
    # Two avisos, each fanned out to three rows — the endpoint shows two, not six.
    assert payload["total"] == 2
    assert len(payload["data"]) == 2


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


# --- `notifications-inbox-web`: acknowledging, counting, filtering -----------------------


@pytest.mark.asyncio
async def test_acknowledging_an_unread_notification_marks_it_read(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R1.2. `204`, and the row moves — the second half is what makes the first true."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    log = await insert_notification(db_session, tenant_a, recipient=manager)

    response = await api.post(
        f"/api/v1/notifications/{log.id}/read", headers=auth_header(api, manager)
    )

    assert response.status_code == 204
    assert response.content == b""
    await db_session.refresh(log)
    assert log.read_at is not None


@pytest.mark.asyncio
async def test_acknowledging_twice_succeeds_and_does_not_move_read_at(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R1.3: `read_at` is the first read, not the last visit."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    log = await insert_notification(db_session, tenant_a, recipient=manager)
    headers = auth_header(api, manager)

    first = await api.post(f"/api/v1/notifications/{log.id}/read", headers=headers)
    await db_session.refresh(log)
    stamped = log.read_at
    second = await api.post(f"/api/v1/notifications/{log.id}/read", headers=headers)
    await db_session.refresh(log)

    assert first.status_code == second.status_code == 204
    assert log.read_at == stamped


@pytest.mark.asyncio
async def test_an_unknown_id_and_a_colleagues_id_answer_the_very_same_404(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R1.4. Not «both are 404» — **the same body**, or the endpoint is an existence oracle.

    Two different ids, so a message carrying the id would fail this: that is deliberate.
    """
    manager = users_by_role_a["PROPERTY_MANAGER"]
    cleaner = users_by_role_a["CLEANER"]
    theirs = await insert_notification(db_session, tenant_a, recipient=manager)
    headers = auth_header(api, cleaner)

    unknown = await api.post(
        f"/api/v1/notifications/{uuid.uuid4()}/read", headers=headers
    )
    colleagues = await api.post(
        f"/api/v1/notifications/{theirs.id}/read", headers=headers
    )

    assert unknown.status_code == colleagues.status_code == 404
    assert unknown.json() == colleagues.json()
    await db_session.refresh(theirs)
    assert theirs.read_at is None


@pytest.mark.asyncio
async def test_the_unread_count_ignores_the_requested_page_size(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R2.2: one request, independent of `per_page`, and it counts only the unread."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    for _ in range(3):
        await insert_notification(db_session, tenant_a, recipient=manager)
    await insert_notification(db_session, tenant_a, recipient=manager, read_at=NOW)
    headers = auth_header(api, manager)

    counted = await api.get("/api/v1/notifications/unread-count", headers=headers)
    with_a_tiny_page = await api.get(
        "/api/v1/notifications?per_page=1", headers=headers
    )

    assert counted.status_code == 200
    assert counted.json() == {"unread": 3}
    assert len(with_a_tiny_page.json()["data"]) == 1


@pytest.mark.asyncio
async def test_the_unread_count_is_the_callers_own(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    manager = users_by_role_a["PROPERTY_MANAGER"]
    await insert_notification(
        db_session, tenant_a, recipient=users_by_role_a["CLEANER"]
    )
    await insert_notification(
        db_session, tenant_b, recipient=users_by_role_b["PROPERTY_MANAGER"]
    )

    response = await api.get(
        "/api/v1/notifications/unread-count", headers=auth_header(api, manager)
    )

    assert response.json() == {"unread": 0}


@pytest.mark.asyncio
async def test_the_unread_filter_returns_only_the_unread_without_breaking_the_envelope(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R2.3: the envelope of PRD §23 survives the filter."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    unread = await insert_notification(db_session, tenant_a, recipient=manager)
    await insert_notification(db_session, tenant_a, recipient=manager, read_at=NOW)

    response = await api.get(
        "/api/v1/notifications?unread=true", headers=auth_header(api, manager)
    )

    payload = response.json()
    assert response.status_code == 200
    assert [item["id"] for item in payload["data"]] == [str(unread.id)]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["per_page"] == 20
    assert payload["total_pages"] == 1


@pytest.mark.asyncio
async def test_the_listing_publishes_read_at(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R2.1, and the four retained fields are still retained."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    await insert_notification(db_session, tenant_a, recipient=manager, read_at=NOW)

    response = await api.get("/api/v1/notifications", headers=auth_header(api, manager))

    [item] = response.json()["data"]
    assert item["read_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert "recipient_contact" not in item
    assert "last_error" not in item
    assert "sla_deadline_at" not in item
    assert "sla_breached" not in item


@pytest.mark.asyncio
async def test_read_all_on_an_empty_inbox_answers_zero(
    api, users_by_role_a
) -> None:
    """D6: zero rows is the normal case of an inbox already up to date, not an error."""
    manager = users_by_role_a["PROPERTY_MANAGER"]

    response = await api.post(
        "/api/v1/notifications/read-all", headers=auth_header(api, manager)
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 0}


@pytest.mark.asyncio
async def test_read_all_moves_every_unread_row_of_the_caller(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R5.2: all of them, not the page the client happens to be showing."""
    manager = users_by_role_a["PROPERTY_MANAGER"]
    cleaner = users_by_role_a["CLEANER"]
    for _ in range(3):
        await insert_notification(db_session, tenant_a, recipient=manager)
    colleagues = await insert_notification(db_session, tenant_a, recipient=cleaner)
    headers = auth_header(api, manager)

    response = await api.post("/api/v1/notifications/read-all", headers=headers)

    assert response.json() == {"updated": 3}
    counted = await api.get("/api/v1/notifications/unread-count", headers=headers)
    assert counted.json() == {"unread": 0}
    await db_session.refresh(colleagues)
    assert colleagues.read_at is None


@pytest.mark.asyncio
async def test_the_three_new_routes_need_a_token_and_admit_every_role_that_has_one(
    api, users_by_role_a
) -> None:
    """Rule 2 of `steering/security.md`, and the honest shape of it for this permission.

    Task 3.5 asked for "a role without `READ_OWN_NOTIFICATIONS` gets `403`", and **there is
    no such role**: the permission lives in `_SELF_SERVICE`
    (`app/auth/domain/policy.py`), which every one of the five members of `UserRole` holds,
    `SUPER_ADMIN` included — measured against `ROLE_PERMISSIONS`, not assumed. `require()`
    consults exactly that mapping, so no token this application can mint is refused here,
    and a test claiming otherwise would have to fabricate a role the enum does not have.

    What IS true, and what this pins: the routes are not anonymous, and every authenticated
    role reaches them. `access-notifications` reached the same place for the listing route —
    see `test_every_authenticated_role_may_read_its_own_inbox` above. The restriction that
    makes this safe is not the permission but the per-recipient scoping, which
    `test_read_isolation.py` and the repository tests are what prove.
    """
    for method, path in (
        ("get", "/api/v1/notifications/unread-count"),
        ("post", "/api/v1/notifications/read-all"),
        ("post", f"/api/v1/notifications/{uuid.uuid4()}/read"),
    ):
        anonymous = await getattr(api, method)(path)
        assert anonymous.status_code == 401, path

        for role in ("TENANT_OWNER", "PROPERTY_MANAGER", "CLEANER", "TECHNICIAN"):
            headers = auth_header(api, users_by_role_a[role])
            allowed = await getattr(api, method)(path, headers=headers)
            assert allowed.status_code != 403, (path, role)


@pytest.mark.asyncio
async def test_every_authenticated_role_may_acknowledge_its_own(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`READ_OWN_NOTIFICATIONS` is self-service (`_SELF_SERVICE` in `policy.py`)."""
    for role in ("TENANT_OWNER", "PROPERTY_MANAGER", "CLEANER", "TECHNICIAN"):
        user = users_by_role_a[role]
        log = await insert_notification(db_session, tenant_a, recipient=user)
        response = await api.post(
            f"/api/v1/notifications/{log.id}/read", headers=auth_header(api, user)
        )
        assert response.status_code == 204, role
