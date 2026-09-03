"""R1, R3, R4, R5 — `POST`/`GET /api/v1/cleaning-tasks/{id}/messages`, end to end over ASGI.

What only this level can show: that the two permissions of `require_any` really do let both
a `CLEANER` and a `PROPERTY_MANAGER` write, that a third role is refused, that a `CLEANER`
reaching for another cleaner's thread gets the same `404` an unknown id gets (never `403`),
that the response body is the field allowlist of `app/cleaning/api/schemas.py` and not a raw
entity dump, and that the write really does land a `NotificationLog` row for the right
recipient. The unit tests of `test_task_messages_use_case.py` cover the notification
branching and the pagination arithmetic against fakes.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.entities import MAX_CLEANING_TASK_MESSAGE_LENGTH
from app.cleaning.domain.exceptions import TASK_NOT_FOUND_MESSAGE
from app.cleaning.infrastructure.models import CleaningTaskMessageModel
from app.notifications.domain.enums import NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"


async def _insert_cleaner(session, tenant, *, status=UserStatus.ACTIVE) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=status,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def cleaner_b(db_session, tenant_b):
    return await _insert_cleaner(db_session, tenant_b)


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, property_a, template_a, cleaner_a):
    task = await insert_task(db_session, tenant_a, property_a, template_a, cleaner=cleaner_a)
    await db_session.flush()
    return task


@pytest_asyncio.fixture
async def task_b(db_session, tenant_b, property_b, template_b, cleaner_b):
    task = await insert_task(db_session, tenant_b, property_b, template_b, cleaner=cleaner_b)
    await db_session.flush()
    return task


async def _post_message(api, task_id, user, content="Falta jabón en el baño"):
    return await api.post(
        f"{TASKS}/{task_id}/messages",
        json={"content": content},
        headers=auth_header(api, user),
    )


async def _get_messages(api, task_id, user, **params):
    return await api.get(
        f"{TASKS}/{task_id}/messages", params=params, headers=auth_header(api, user)
    )


async def _notifications_for(db_session, tenant_id, task_id):
    rows = await db_session.execute(
        select(NotificationLogModel).where(
            NotificationLogModel.tenant_id == tenant_id,
            NotificationLogModel.notification_type == NotificationType.CLEANING_TASK_MESSAGE.value,
            NotificationLogModel.related_id == task_id,
        )
    )
    return list(rows.scalars())


# --- the happy path --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_sends_a_message_and_notifies_every_active_manager(
    api, db_session, task_a, cleaner_a, users_by_role_a
):
    response = await _post_message(api, task_a.id, cleaner_a)

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "Falta jabón en el baño"
    assert body["author_id"] == str(cleaner_a.id)
    assert body["author_role"] == "CLEANER"
    assert uuid.UUID(body["id"])
    assert body["created_at"]

    row = await db_session.scalar(
        select(CleaningTaskMessageModel).where(
            CleaningTaskMessageModel.id == uuid.UUID(body["id"])
        )
    )
    assert row is not None
    assert row.task_id == task_a.id
    assert row.tenant_id == task_a.tenant_id

    notifications = await _notifications_for(db_session, task_a.tenant_id, task_a.id)
    assert len(notifications) == 1
    assert notifications[0].recipient_user_id == users_by_role_a[UserRole.PROPERTY_MANAGER].id


@pytest.mark.asyncio
async def test_the_manager_sends_a_message_and_notifies_the_assigned_cleaner(
    api, db_session, task_a, cleaner_a, users_by_role_a
):
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await _post_message(api, task_a.id, manager, content="Revisa la nevera, por favor")

    assert response.status_code == 201
    body = response.json()
    assert body["author_id"] == str(manager.id)
    assert body["author_role"] == "PROPERTY_MANAGER"

    notifications = await _notifications_for(db_session, task_a.tenant_id, task_a.id)
    assert len(notifications) == 1
    assert notifications[0].recipient_user_id == cleaner_a.id


@pytest.mark.asyncio
async def test_the_manager_messages_an_unassigned_task_and_notifies_nobody(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R1.4 — `PROPERTY_MANAGER` is unrestricted "including unassigned"; R4.3 — no assigned
    cleaner means the notification is skipped, not failed. Every other `PROPERTY_MANAGER`
    test in this file starts from `task_a` (assigned to `cleaner_a`), so this HTTP layer
    never drove this branch before, even though `test_task_messages_use_case.py` already
    covers it against fakes."""
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    await db_session.flush()
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await _post_message(api, task.id, manager, content="Nota para cuando se asigne")

    assert response.status_code == 201
    body = response.json()
    row = await db_session.scalar(
        select(CleaningTaskMessageModel).where(
            CleaningTaskMessageModel.id == uuid.UUID(body["id"])
        )
    )
    assert row is not None
    assert row.task_id == task.id

    notifications = await _notifications_for(db_session, task.tenant_id, task.id)
    assert notifications == []


@pytest.mark.asyncio
async def test_the_response_body_is_the_allowlist_and_not_a_raw_dump(api, task_a, cleaner_a):
    response = await _post_message(api, task_a.id, cleaner_a)

    assert set(response.json()) == {"id", "author_id", "content", "author_role", "created_at"}
    assert "tenant_id" not in response.text
    assert "task_id" not in response.text


@pytest.mark.asyncio
async def test_a_cleaner_reads_her_own_task_thread(api, db_session, task_a, cleaner_a):
    await _post_message(api, task_a.id, cleaner_a, content="Primero")
    await _post_message(api, task_a.id, cleaner_a, content="Segundo")

    response = await _get_messages(api, task_a.id, cleaner_a)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["content"] for item in body["data"]] == ["Primero", "Segundo"]
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert body["total_pages"] == 1


@pytest.mark.asyncio
async def test_a_manager_reads_the_thread_of_any_task(api, task_a, users_by_role_a, cleaner_a):
    await _post_message(api, task_a.id, cleaner_a)

    response = await _get_messages(api, task_a.id, users_by_role_a[UserRole.PROPERTY_MANAGER])

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_pagination_bounds_and_paginates(api, task_a, cleaner_a):
    for i in range(3):
        await _post_message(api, task_a.id, cleaner_a, content=f"mensaje {i}")

    response = await _get_messages(api, task_a.id, cleaner_a, page=2, per_page=2)

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["per_page"] == 2
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["data"]) == 1


# --- the refusals ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_over_the_maximum_length_is_422(api, db_session, task_a, cleaner_a):
    response = await _post_message(api, task_a.id, cleaner_a, content="x" * (MAX_CLEANING_TASK_MESSAGE_LENGTH + 1))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await db_session.scalar(select(CleaningTaskMessageModel.id)) is None


@pytest.mark.asyncio
async def test_content_at_exactly_the_maximum_length_is_accepted(api, task_a, cleaner_a):
    response = await _post_message(api, task_a.id, cleaner_a, content="x" * MAX_CLEANING_TASK_MESSAGE_LENGTH)

    assert response.status_code == 201
    assert len(response.json()["content"]) == MAX_CLEANING_TASK_MESSAGE_LENGTH


@pytest.mark.asyncio
async def test_empty_content_is_422(api, task_a, cleaner_a):
    response = await _post_message(api, task_a.id, cleaner_a, content="   ")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unexpected_field_is_422(api, task_a, cleaner_a):
    response = await api.post(
        f"{TASKS}/{task_a.id}/messages",
        json={"content": "hola", "author_id": str(uuid.uuid4())},
        headers=auth_header(api, cleaner_a),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_technician_is_refused_on_both_routes(api, task_a, users_by_role_a):
    technician = users_by_role_a[UserRole.TECHNICIAN]

    post_response = await _post_message(api, task_a.id, technician)
    get_response = await _get_messages(api, task_a.id, technician)

    assert post_response.status_code == 403
    assert get_response.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_can_read_but_not_write(api, task_a, users_by_role_a):
    """`TENANT_OWNER` holds `READ_CLEANING_TASKS` but neither `EXECUTE_` nor
    `MANAGE_CLEANING_TASKS` (`auth/domain/policy.py`), so the read half of `require_any`'s
    point is exactly this asymmetry."""
    owner = users_by_role_a[UserRole.TENANT_OWNER]

    get_response = await _get_messages(api, task_a.id, owner)
    post_response = await _post_message(api, task_a.id, owner)

    assert get_response.status_code == 200
    assert post_response.status_code == 403


@pytest.mark.asyncio
async def test_an_anonymous_request_is_401(api, task_a):
    post_response = await api.post(f"{TASKS}/{task_a.id}/messages", json={"content": "hola"})
    get_response = await api.get(f"{TASKS}/{task_a.id}/messages")

    assert post_response.status_code == 401
    assert get_response.status_code == 401


# --- isolation (R3.2) ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messaging_another_tenants_task_is_the_same_404_as_an_unknown_id(
    api, task_b, cleaner_a
):
    foreign = await _post_message(api, task_b.id, cleaner_a)
    unknown = await _post_message(api, uuid.uuid4(), cleaner_a)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert foreign.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_reading_another_tenants_task_is_the_same_404_as_an_unknown_id(api, task_b, cleaner_a):
    foreign = await _get_messages(api, task_b.id, cleaner_a)
    unknown = await _get_messages(api, uuid.uuid4(), cleaner_a)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content


@pytest.mark.asyncio
async def test_a_cleaner_cannot_message_a_task_that_is_not_hers(
    api, db_session, tenant_a, task_a, cleaner_a
):
    other_cleaner = await _insert_cleaner(db_session, tenant_a)

    response = await _post_message(api, task_a.id, other_cleaner)
    unknown = await _post_message(api, uuid.uuid4(), other_cleaner)

    assert response.status_code == 404
    assert response.content == unknown.content


@pytest.mark.asyncio
async def test_a_cleaner_cannot_read_a_task_that_is_not_hers(
    api, db_session, tenant_a, task_a, cleaner_a
):
    other_cleaner = await _insert_cleaner(db_session, tenant_a)

    response = await _get_messages(api, task_a.id, other_cleaner)
    unknown = await _get_messages(api, uuid.uuid4(), other_cleaner)

    assert response.status_code == 404
    assert response.content == unknown.content
