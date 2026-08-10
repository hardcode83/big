"""R3.1, R3.2, R6 — `GET /api/v1/cleaning-tasks/{id}/photos`, end to end over ASGI.

What only this level can show, and the reason task 4.1 insists on it: that **`storage_key` is
absent from the SERIALISED body**. A response model that omits the field is an intention; a
body that does not contain the string is the guarantee, and the two come apart the moment
somebody reaches for `model_validate`/`from_attributes` over `CleaningPhoto` — which carries
`storage_key`, because the signer needs it. So the assertions below search the real bytes that
went out, and the last one demonstrates that the search is not vacuous by finding the key in a
body that was built the convenient way.

The row-level rules themselves are pinned per-branch in `test_photo_listing_use_case.py`; here
they are checked to survive the wiring, and the two 404s are compared byte for byte.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.api.schemas import CleaningPhotoResponse
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import TASK_NOT_FOUND_MESSAGE
from app.cleaning.infrastructure.models import CleaningPhotoModel
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"

JPEG = b"\xff\xd8\xff" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _insert_cleaner(session, tenant) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=UserStatus.ACTIVE,
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
async def live_task_a(db_session, tenant_a, property_a, template_a, cleaner_a):
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_a,
    )
    await db_session.flush()
    return task


@pytest_asyncio.fixture
async def live_task_b(db_session, tenant_b, property_b, template_b, cleaner_b):
    task = await insert_task(
        db_session,
        tenant_b,
        property_b,
        template_b,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_b,
    )
    await db_session.flush()
    return task


async def _upload(api, task_id, user, *, content=JPEG, filename="photo.jpg"):
    response = await api.post(
        f"{TASKS}/{task_id}/photos",
        data={"photo_type": "kitchen"},
        files={"file": (filename, content, "image/jpeg")},
        headers=auth_header(api, user),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _list(api, task_id, user):
    return await api.get(f"{TASKS}/{task_id}/photos", headers=auth_header(api, user))


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_lists_her_photos_with_signed_urls(
    api, live_task_a, cleaner_a
):
    first = await _upload(api, live_task_a.id, cleaner_a)
    second = await _upload(api, live_task_a.id, cleaner_a, content=PNG)

    response = await _list(api, live_task_a.id, cleaner_a)

    assert response.status_code == 200
    data = response.json()["data"]
    # Oldest first, which is the repository's `ORDER BY created_at, id`.
    assert [item["id"] for item in data] == [first["id"], second["id"]]
    for item in data:
        assert item["url"].startswith("/api/v1/cleaning-photos/")
        assert "exp=" in item["url"] and "sig=" in item["url"]
        assert item["cleaning_task_id"] == str(live_task_a.id)
        assert item["uploaded_by"] == str(cleaner_a.id)


@pytest.mark.asyncio
async def test_a_manager_lists_the_photos_of_a_task_that_is_not_hers(
    api, live_task_a, cleaner_a, users_by_role_a
):
    """R3.1 — `READ_CLEANING_TASKS`, which the manager holds and the upload permission is not."""
    await _upload(api, live_task_a.id, cleaner_a)

    response = await _list(api, live_task_a.id, users_by_role_a[UserRole.PROPERTY_MANAGER])

    assert response.status_code == 200
    assert len(response.json()["data"]) == 1


@pytest.mark.asyncio
async def test_a_task_with_no_photos_lists_an_empty_array(api, live_task_a, cleaner_a):
    response = await _list(api, live_task_a.id, cleaner_a)

    assert response.status_code == 200
    assert response.json() == {"data": []}


# --- R3.2, against the bytes that actually went out ----------------------------------


@pytest.mark.asyncio
async def test_the_listing_never_carries_the_storage_key(
    api, db_session, live_task_a, cleaner_a
):
    """R3.2 — checked against the SERIALISED body, not against the schema's field list.

    Two photos, so a per-item leak has two chances to show. Both the literal key and the field
    name are searched: the first catches a value that escaped, the second an empty or renamed
    field that would leak the *shape* and be one commit away from leaking the value.
    """
    await _upload(api, live_task_a.id, cleaner_a)
    await _upload(api, live_task_a.id, cleaner_a, content=PNG)

    response = await _list(api, live_task_a.id, cleaner_a)

    keys = list(
        (await db_session.execute(select(CleaningPhotoModel.storage_key))).scalars()
    )
    assert len(keys) == 2
    for key in keys:
        assert key not in response.text
        assert key not in str(dict(response.headers))
    assert "storage_key" not in response.text
    # The tenant prefix is the part of the key that would let a caller pivot; not even its
    # first segment survives (design D3 puts the tenant id at the front for that reason).
    assert str(live_task_a.tenant_id) not in response.text


@pytest.mark.asyncio
async def test_the_key_search_would_actually_find_a_leak(api, db_session, live_task_a, cleaner_a):
    """The guard on the guard above — a substring search that can never match proves nothing.

    Builds the response body the "convenient" way task 4.1 forbids: a dump of the entity
    instead of the allowlist DTO. The key appears, and the same assertion that passes above
    fails here — which is what makes the one above evidence rather than decoration.
    """
    await _upload(api, live_task_a.id, cleaner_a)
    row = await db_session.scalar(select(CleaningPhotoModel))

    dumped = str(
        {
            "id": str(row.id),
            "cleaning_task_id": str(row.cleaning_task_id),
            "photo_type": row.photo_type,
            "storage_key": row.storage_key,
        }
    )

    assert row.storage_key in dumped
    # And the DTO that the route really uses does not even declare the field, so there is no
    # way to populate it by accident.
    assert "storage_key" not in CleaningPhotoResponse.model_fields


# --- isolation (R6) ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_another_tenants_task_is_the_same_404_as_an_unknown_id(
    api, live_task_b, cleaner_a
):
    """R6.3 — identical body, not merely an identical status code.

    An empty `200` would be the subtler failure here and is the one this pins: it would confirm
    that the task id exists somewhere, which is exactly what the 404 is careful to hide.
    """
    foreign = await _list(api, live_task_b.id, cleaner_a)
    unknown = await _list(api, uuid.uuid4(), cleaner_a)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert foreign.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_a_manager_cannot_list_another_tenants_task(api, live_task_b, users_by_role_a):
    """R6.3 for the one actor no other test here uses: a manager crossing tenants.

    Every other cross-tenant assertion in this file and in `test_photos_api.py` acts as a
    `CLEANER`, who meets *two* refusals on a foreign task — the tenant scoping, and
    `restrict_to_cleaner_id` in `_load_task` — both answering with the same
    `CleaningTaskNotFoundError` and therefore the same body. A `PROPERTY_MANAGER` has
    `MANAGE_CLEANING_TASKS` and no per-cleaner restriction, so tenant scoping is the only thing
    between it and the neighbour's task. That is the gap this covers.

    **What it does not claim.** It is not "the test that dies if isolation breaks", because
    `cleaning_tasks` carries a `tenant_id` column and is therefore covered twice: by the
    explicit filter every repository method applies (design D6) and by the global
    `do_orm_execute` listener (`core/db.py`, design D16). Removing either one alone leaves the
    other enforcing, so no single-layer mutation turns this red — measured, after a first
    version of this docstring claimed otherwise. The table that really has one layer is
    `cleaning_photos`, which has no `tenant_id` at all (R6.1), and its isolation is pinned where
    the single layer lives: the repository tests in `test_repositories.py`, which a mutation of
    the join does kill.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    foreign = await _list(api, live_task_b.id, manager)
    unknown = await _list(api, uuid.uuid4(), manager)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert foreign.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_a_cleaner_cannot_list_a_task_that_is_not_hers(
    api, db_session, tenant_a, live_task_a, cleaner_a
):
    """R6.4 — derived from the persisted role, and answered as absence rather than as 403."""
    await _upload(api, live_task_a.id, cleaner_a)
    other_cleaner = await _insert_cleaner(db_session, tenant_a)

    response = await _list(api, live_task_a.id, other_cleaner)
    unknown = await _list(api, uuid.uuid4(), other_cleaner)

    assert response.status_code == 404
    assert response.content == unknown.content


@pytest.mark.asyncio
async def test_an_anonymous_listing_is_401(api, live_task_a):
    response = await api.get(f"{TASKS}/{live_task_a.id}/photos")

    assert response.status_code == 401
