"""R2, R6 — `POST /api/v1/cleaning-tasks/{id}/photos`, end to end over ASGI.

What only this level can show: that the multipart request really reaches the use case with the
right actor, that the response body carries no internal path, that the object lands on disk and
the row in the database in the same request, and that the two isolation answers of R6 are
**byte-identical** to the answer an unknown id gets. The unit tests of
`test_photo_upload_use_case.py` cover the ordering and the compensation; the middleware ceiling
is `test_photo_body_limit.py`'s.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.audit.domain import actions as audit_actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.api.dependencies import (
    SessionDep,
    StorageFactoryDep,
    get_file_storage_factory,
    get_upload_cleaning_photo_use_case,
)
from app.cleaning.application.use_cases import UploadCleaningPhotoUseCase
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import TASK_NOT_FOUND_MESSAGE
from app.cleaning.infrastructure.models import CleaningPhotoModel
from app.integrations.domain.storage import StorageWriteError
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"

JPEG = b"\xff\xd8\xff" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64


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
    """A task of tenant A, in progress, assigned to `cleaner_a` — the only state that uploads."""
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


def _multipart(content=JPEG, *, filename="photo.jpg", declared="image/jpeg"):
    return {"file": (filename, content, declared)}


async def _post(api, task_id, user, *, photo_type="kitchen", **kwargs):
    return await api.post(
        f"{TASKS}/{task_id}/photos",
        data={"photo_type": photo_type},
        files=_multipart(**kwargs),
        headers=auth_header(api, user),
    )


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_uploads_a_photo(
    api, db_session, live_task_a, cleaner_a, media_root
):
    response = await _post(api, live_task_a.id, cleaner_a)

    assert response.status_code == 201
    body = response.json()
    assert body["cleaning_task_id"] == str(live_task_a.id)
    assert body["photo_type"] == "kitchen"
    assert body["uploaded_by"] == str(cleaner_a.id)
    assert body["url"].startswith("/api/v1/cleaning-photos/")

    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(body["id"]))
    )
    assert row is not None
    assert row.cleaning_task_id == live_task_a.id
    # The object is really there, and under the key the row points at (R1.5, design D4).
    assert (media_root / row.storage_key).read_bytes() == JPEG


@pytest.mark.asyncio
async def test_the_response_never_carries_the_storage_key(api, db_session, live_task_a, cleaner_a):
    """R3.2 — checked against the SERIALISED body, not against the schema's field list.

    A response model that omits the field is the intention; a body that does not contain the
    string is the guarantee. They come apart the day somebody adds a debug field or a header.
    """
    response = await _post(api, live_task_a.id, cleaner_a)

    row = await db_session.scalar(
        select(CleaningPhotoModel).where(
            CleaningPhotoModel.id == uuid.UUID(response.json()["id"])
        )
    )
    assert row.storage_key not in response.text
    assert "storage_key" not in response.text
    assert row.storage_key not in str(dict(response.headers))


@pytest.mark.asyncio
async def test_the_stored_key_ignores_the_file_name_the_client_sent(
    api, db_session, live_task_a, cleaner_a
):
    """Design D3 — the client's name is untrusted input and does not touch the key."""
    response = await _post(
        api, live_task_a.id, cleaner_a, filename="../../../etc/passwd", declared="text/html"
    )

    assert response.status_code == 201
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(
            CleaningPhotoModel.id == uuid.UUID(response.json()["id"])
        )
    )
    assert row.storage_key == (
        f"tenants/{live_task_a.tenant_id}/cleaning-tasks/{live_task_a.id}/{row.id}.jpg"
    )
    assert "passwd" not in row.storage_key


@pytest.mark.asyncio
async def test_the_extension_comes_from_the_content_not_from_the_declared_type(
    api, db_session, live_task_a, cleaner_a
):
    """R2.4, design D5 — a PNG announced as a JPEG is stored as what it is."""
    response = await _post(
        api, live_task_a.id, cleaner_a, content=PNG, filename="x.jpg", declared="image/jpeg"
    )

    row = await db_session.scalar(
        select(CleaningPhotoModel).where(
            CleaningPhotoModel.id == uuid.UUID(response.json()["id"])
        )
    )
    assert row.storage_key.endswith(".png")


@pytest.mark.asyncio
async def test_several_photos_of_the_same_type_are_allowed(api, db_session, live_task_a, cleaner_a):
    """R2.6 — two angles of the same bathroom is a normal thing to do."""
    first = await _post(api, live_task_a.id, cleaner_a)
    second = await _post(api, live_task_a.id, cleaner_a)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.asyncio
async def test_the_upload_writes_its_audit_row(api, db_session, live_task_a, cleaner_a):
    """R2.7 and rule 9 of `steering/security.md` — actor and IP, like every other operation."""
    response = await _post(api, live_task_a.id, cleaner_a)

    entry = await db_session.scalar(
        select(AuditLogModel).where(
            AuditLogModel.action == audit_actions.CLEANING_PHOTO_UPLOADED
        )
    )
    assert entry is not None
    assert entry.entity_type == audit_actions.ENTITY_CLEANING_PHOTO
    assert entry.entity_id == uuid.UUID(response.json()["id"])
    assert entry.actor_user_id == cleaner_a.id
    assert entry.actor_ip
    assert entry.changes["photo_type"]["new"] == "kitchen"
    # Rule 11: `audit_logs.changes` is a cleartext sink and the internal key stays out of it.
    assert "storage_key" not in entry.changes


# --- the refusals --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_photo_type_is_404(api, live_task_a, cleaner_a):
    response = await _post(api, live_task_a.id, cleaner_a, photo_type="garage")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_task_that_is_not_in_progress_is_409(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
):
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.ACCEPTED,
        cleaner=cleaner_a,
    )
    await db_session.flush()

    response = await _post(api, task.id, cleaner_a)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_a_file_that_is_not_an_image_is_422(api, db_session, live_task_a, cleaner_a):
    response = await _post(api, live_task_a.id, cleaner_a, content=PDF, filename="x.jpg")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await db_session.scalar(select(CleaningPhotoModel.id)) is None


def _use_case_with_a_tiny_ceiling(
    session: SessionDep, storage: StorageFactoryDep
) -> UploadCleaningPhotoUseCase:
    """The production builder, with the byte ceiling and nothing else replaced.

    Built by calling `get_upload_cleaning_photo_use_case` so the wiring stays single-sourced —
    a hand-assembled copy here would keep passing after somebody changed which repositories the
    use case takes. Only `_max_bytes` is reached into, which is exactly the one value under
    test, and reaching for it is what keeps the middleware at its real 10 MB.
    """
    use_case = get_upload_cleaning_photo_use_case(session, storage)
    use_case._max_bytes = 16
    return use_case


@pytest.mark.asyncio
async def test_a_file_over_the_use_cases_ceiling_is_413(api, live_task_a, cleaner_a):
    """D11's second check, over HTTP.

    The use case's ceiling is lowered on its own — the middleware keeps the real 10 MB — so
    what answers here is unambiguously the streaming counter and not the body-size middleware,
    which `test_photo_body_limit.py` already pins.
    """
    overrides = api.asgi_app.dependency_overrides
    overrides[get_upload_cleaning_photo_use_case] = _use_case_with_a_tiny_ceiling
    try:
        response = await _post(api, live_task_a.id, cleaner_a)
    finally:
        del overrides[get_upload_cleaning_photo_use_case]

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "16 byte" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_storage_failure_is_502(api, db_session, live_task_a, cleaner_a):
    """R1.5 — the store refused, so no row exists and the answer is a 502, not a 500."""

    class RefusingStorage:
        async def put(self, key, content, *, content_type):
            raise StorageWriteError("the bucket is on fire")

        def signed_url(self, key, *, expires_in=3600):  # pragma: no cover - never reached
            return ""

        async def delete(self, key):  # pragma: no cover - never reached
            return None

    class RefusingFactory:
        def storage_for(self, storage_type):
            return RefusingStorage()

        def read_for(self, storage_type):  # pragma: no cover - not used by the upload
            raise NotImplementedError

    api.asgi_app.dependency_overrides[get_file_storage_factory] = RefusingFactory
    try:
        response = await _post(api, live_task_a.id, cleaner_a)
    finally:
        del api.asgi_app.dependency_overrides[get_file_storage_factory]

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"
    assert await db_session.scalar(select(CleaningPhotoModel.id)) is None


# --- isolation (task 3.7, R6) --------------------------------------------------------


@pytest.mark.asyncio
async def test_uploading_to_another_tenants_task_is_the_same_404_as_an_unknown_id(
    api, live_task_b, cleaner_a
):
    """R6.3 — identical body, not merely an identical status code.

    Compared byte for byte: two 404s whose bodies differ is the same probe one layer down,
    and it would confirm that the id exists somewhere.
    """
    foreign = await _post(api, live_task_b.id, cleaner_a)
    unknown = await _post(api, uuid.uuid4(), cleaner_a)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert foreign.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_a_cleaner_cannot_upload_to_a_task_that_is_not_hers(
    api, db_session, tenant_a, property_a, template_a, cleaner_a, live_task_a
):
    """R6.4 — derived from the persisted role, and answered as absence rather than as 403."""
    other_cleaner = await _insert_cleaner(db_session, tenant_a)

    response = await _post(api, live_task_a.id, other_cleaner)
    unknown = await _post(api, uuid.uuid4(), other_cleaner)

    assert response.status_code == 404
    assert response.content == unknown.content


@pytest.mark.asyncio
async def test_a_manager_cannot_upload_at_all(api, live_task_a, users_by_role_a):
    """R2.6 — `EXECUTE_CLEANING_TASKS` is the cleaner's alone, so a manager gets 403 and not 404.

    The distinction is deliberate: a missing **permission** is a fact about the caller's role,
    which they already know, while a task belonging to someone else must read as absence.
    """
    response = await _post(api, live_task_a.id, users_by_role_a[UserRole.PROPERTY_MANAGER])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_an_anonymous_upload_is_401(api, live_task_a):
    response = await api.post(
        f"{TASKS}/{live_task_a.id}/photos",
        data={"photo_type": "kitchen"},
        files=_multipart(),
    )

    assert response.status_code == 401
