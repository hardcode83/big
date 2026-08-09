"""R3.1, R6.4 — `ListCleaningPhotosUseCase` against fakes of every port it holds.

No database and no disk. What only this level can pin is that the use case **resolves the task
first** and asks the repository for photos second: over HTTP the two failures look the same
(an empty list and a 404 both mean "you get nothing"), and the difference is exactly R6.3 —
another tenant's task must be a 404 identical to an unknown id, never a successful empty list
that quietly confirms the task exists.

The serialised-body half of R3.2 is not here and cannot be: a fake returns objects, and
`storage_key` leaves this use case *inside* `UploadedCleaningPhoto.photo` on purpose, because
`signed_url` needs it. What this file pins is that the URL was minted from that key; that the
key does not reach the wire is `test_photo_listing_api.py`'s assertion, against the real body.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.application.use_cases import CleaningActor, ListCleaningPhotosUseCase
from app.cleaning.domain.entities import CleaningPhoto, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    TASK_NOT_FOUND_MESSAGE,
    CleaningTaskNotFoundError,
)
from app.tenants.domain.enums import StorageType

NOW = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()
MANAGER = uuid.uuid4()


class FakeTaskRepository:
    def __init__(self, task: CleaningTask) -> None:
        self._task = task

    async def get(self, tenant_id, task_id):
        if tenant_id != TENANT or task_id != self._task.id:
            return None
        return self._task


class FakePhotoRepository:
    """Records the (tenant, task) it was asked about, so scoping is checkable and not assumed."""

    def __init__(self, photos: list[CleaningPhoto]) -> None:
        self._photos = photos
        self.queried: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def list_for_task(self, tenant_id, task_id):
        self.queried.append((tenant_id, task_id))
        return list(self._photos)


class FakeConfigRepository:
    def __init__(self, storage_type: StorageType = StorageType.LOCAL) -> None:
        self._storage_type = storage_type

    async def get_or_create(self, tenant_id, now):
        class _Config:
            storage_type = self._storage_type

        return _Config()


class FakeStorage:
    def __init__(self) -> None:
        self.signed: list[str] = []

    def signed_url(self, key, *, expires_in=3600) -> str:
        self.signed.append(key)
        return f"/api/v1/cleaning-photos/{key}?exp=1&sig=fake"


class FakeStorageFactory:
    def __init__(self, storage: FakeStorage) -> None:
        self._storage = storage
        self.resolved: list[StorageType] = []

    def storage_for(self, storage_type):
        self.resolved.append(storage_type)
        return self._storage


def _task() -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status=CleaningTaskStatus.IN_PROGRESS,
        assigned_cleaner_id=CLEANER,
    )


def _photo(task: CleaningTask, *, photo_type="kitchen") -> CleaningPhoto:
    photo_id = uuid.uuid4()
    return CleaningPhoto(
        id=photo_id,
        cleaning_task_id=task.id,
        uploaded_by=CLEANER,
        photo_type=photo_type,
        storage_key=f"tenants/{TENANT}/cleaning-tasks/{task.id}/{photo_id}.jpg",
        created_at=NOW,
    )


def _build(*, task=None, photos=None, storage_type=StorageType.LOCAL):
    task = task if task is not None else _task()
    photos = photos if photos is not None else [_photo(task)]
    repository = FakePhotoRepository(photos)
    storage = FakeStorage()
    factory = FakeStorageFactory(storage)
    use_case = ListCleaningPhotosUseCase(
        tasks=FakeTaskRepository(task),
        photos=repository,
        configs=FakeConfigRepository(storage_type),
        storage=factory,
    )
    return use_case, task, repository, storage, factory


def _cleaner() -> CleaningActor:
    return CleaningActor(user_id=CLEANER, role=UserRole.CLEANER, ip="10.0.0.9")


def _manager() -> CleaningActor:
    return CleaningActor(user_id=MANAGER, role=UserRole.PROPERTY_MANAGER, ip="10.0.0.7")


@pytest.mark.asyncio
async def test_every_photo_comes_back_with_a_url_signed_over_its_own_key():
    use_case, task, _, storage, factory = _build(storage_type=StorageType.LOCAL)

    result = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner(), now=NOW
    )

    assert len(result) == 1
    # The URL was minted from the row's key, not from anything the caller could name.
    assert storage.signed == [result[0].photo.storage_key]
    assert result[0].url.startswith("/api/v1/cleaning-photos/")
    # R1.2 — the backend came from the tenant's stored configuration.
    assert factory.resolved == [StorageType.LOCAL]


@pytest.mark.asyncio
async def test_the_repository_is_asked_within_the_session_tenant():
    """R6.1 — the isolation of `cleaning_photos` is derived from the tenant, per query."""
    use_case, task, repository, _, _ = _build()

    await use_case.execute(tenant_id=TENANT, task_id=task.id, actor=_cleaner(), now=NOW)

    assert repository.queried == [(TENANT, task.id)]


@pytest.mark.asyncio
async def test_a_manager_lists_a_task_that_is_not_hers():
    """R3.1 — reading the evidence is the manager's and the owner's job, not only the cleaner's.

    `restrict_to_cleaner_id` is `None` for every role but `CLEANER`, so the task resolves even
    though `assigned_cleaner_id` names somebody else.
    """
    use_case, task, _, _, _ = _build()

    result = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_manager(), now=NOW
    )

    assert task.assigned_cleaner_id == CLEANER
    assert MANAGER != CLEANER
    assert len(result) == 1


@pytest.mark.asyncio
async def test_a_task_of_another_tenant_is_the_same_404_as_an_unknown_id():
    """R6.3 — and the repository is never even asked, so there is nothing to leak."""
    use_case, task, repository, _, _ = _build()

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        await use_case.execute(
            tenant_id=OTHER_TENANT, task_id=task.id, actor=_cleaner(), now=NOW
        )

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE
    assert repository.queried == []


@pytest.mark.asyncio
async def test_a_cleaner_cannot_list_a_task_assigned_to_someone_else():
    """R6.4 — derived from the persisted role, with no request parameter in the path.

    And it is a 404, not an empty list: an empty list would confirm the task exists.
    """
    use_case, task, repository, _, _ = _build()
    other_cleaner = CleaningActor(user_id=uuid.uuid4(), role=UserRole.CLEANER)

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        await use_case.execute(
            tenant_id=TENANT, task_id=task.id, actor=other_cleaner, now=NOW
        )

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE
    assert repository.queried == []


@pytest.mark.asyncio
async def test_a_task_with_no_photos_is_an_empty_list_and_not_an_error():
    use_case, task, _, storage, _ = _build(photos=[])

    result = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner(), now=NOW
    )

    assert result == ()
    assert storage.signed == []
