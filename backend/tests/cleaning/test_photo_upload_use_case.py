"""R2 — `UploadCleaningPhotoUseCase`, against fakes of every port it holds.

No database and no disk: what is under test is the ORDER of the operations and the outcome of
each refusal, and both are properties of the use case rather than of any adapter. The two that
only a fake can pin are the ones design D4 and D11 argue hardest for:

* **object first, row second, and the object is deleted when the commit fails.** A real
  session would make "did the row survive?" observable and leave "was the object removed?"
  invisible, which is the half R1.5 is about.
* **the size ceiling is applied while consuming the stream**, not after buffering it. The fake
  upload below counts how much was asked for, so a use case that read the file whole and then
  measured it would fail here even though the status code came out right.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions as audit_actions
from app.cleaning.application.use_cases import (
    _UPLOAD_CHUNK_BYTES,
    CleaningActor,
    UploadCleaningPhotoUseCase,
)
from app.cleaning.domain.entities import CleaningChecklistTemplate, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    TASK_NOT_FOUND_MESSAGE,
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
    PhotoStorageUnavailableError,
    PhotoTooLargeError,
    PhotoTypeNotFoundError,
    UnsupportedPhotoFormatError,
)
from app.integrations.domain.storage import StorageWriteError
from app.auth.domain.enums import UserRole
from app.tenants.domain.enums import StorageType

NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()
MANAGER = uuid.uuid4()

#: The JPEG signature on its own, so the boundary tests can build a file of an EXACT size
#: without arithmetic over a padded constant.
JPEG_MAGIC = b"\xff\xd8\xff"

JPEG = JPEG_MAGIC + b"padding-that-is-not-inspected"
PNG = b"\x89PNG\r\n\x1a\n" + b"more"
PDF = b"%PDF-1.7\nnot an image at all"

MAX_BYTES = 1024


# --- fakes ---------------------------------------------------------------------------


class FakeUpload:
    """A file that hands out bytes in chunks and remembers how much was asked for."""

    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self._content) if size < 0 else min(self._offset + size, len(self._content))
        chunk = self._content[self._offset : end]
        self._offset = end
        self.bytes_served += len(chunk)
        return chunk


class FakeTaskRepository:
    def __init__(self, task: CleaningTask | None) -> None:
        self._task = task

    async def get(self, tenant_id, task_id):
        if self._task is None or tenant_id != TENANT or task_id != self._task.id:
            return None
        return self._task


class FakeTemplateRepository:
    def __init__(self, template: CleaningChecklistTemplate | None) -> None:
        self._template = template

    async def get(self, tenant_id, template_id):
        return self._template


class FakePhotoRepository:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.added: list = []
        self._fail = fail

    async def add(self, tenant_id, photo) -> None:
        if self._fail is not None:
            raise self._fail
        self.added.append((tenant_id, photo))


class FakeConfigRepository:
    def __init__(self, storage_type: StorageType = StorageType.LOCAL) -> None:
        self._storage_type = storage_type

    async def get_or_create(self, tenant_id, now):
        class _Config:
            storage_type = self._storage_type

        return _Config()


class FakeStorage:
    """Records the calls in order, so "object before row" is checkable and not assumed."""

    def __init__(self, *, fail_put: bool = False, fail_delete: bool = False) -> None:
        self.puts: list[tuple[str, bytes, str]] = []
        self.deletes: list[str] = []
        self._fail_put = fail_put
        self._fail_delete = fail_delete

    async def put(self, key, content, *, content_type) -> None:
        if self._fail_put:
            raise StorageWriteError("the disk is full")
        self.puts.append((key, content, content_type))

    def signed_url(self, key, *, expires_in=3600) -> str:
        return f"/api/v1/cleaning-photos/{key}?sig=fake"

    async def delete(self, key) -> None:
        if self._fail_delete:
            raise StorageWriteError("cannot delete either")
        self.deletes.append(key)


class FakeStorageFactory:
    def __init__(self, storage: FakeStorage) -> None:
        self._storage = storage
        self.resolved: list[StorageType] = []

    def storage_for(self, storage_type):
        self.resolved.append(storage_type)
        return self._storage


class FakeAuditRepository:
    def __init__(self) -> None:
        self.entries: list = []

    async def add(self, tenant_id, entry) -> None:
        self.entries.append(entry)


class FakeUnitOfWork:
    def __init__(self, *, fail: bool = False) -> None:
        self.commits = 0
        self._fail = fail

    async def commit(self) -> None:
        if self._fail:
            raise RuntimeError("the transaction could not be committed")
        self.commits += 1


# --- builders ------------------------------------------------------------------------


def _template(photo_types=("kitchen",)) -> CleaningChecklistTemplate:
    return CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Estándar",
        items=[{"item_id": "kitchen", "label": "Cocina", "required": True}],
        required_photos=[
            {"photo_type": kind, "label": kind, "required": True} for kind in photo_types
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def _task(status=CleaningTaskStatus.IN_PROGRESS, template_id=None) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=uuid.uuid4(),
        checklist_template_id=template_id or uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status=status,
        assigned_cleaner_id=CLEANER,
    )


def _build(
    *,
    task=None,
    template=None,
    photos=None,
    storage=None,
    uow=None,
    audit=None,
    max_bytes=MAX_BYTES,
    storage_type=StorageType.LOCAL,
):
    template = template if template is not None else _template()
    task = task if task is not None else _task(template_id=template.id)
    storage = storage if storage is not None else FakeStorage()
    photos = photos if photos is not None else FakePhotoRepository()
    uow = uow if uow is not None else FakeUnitOfWork()
    audit = audit if audit is not None else FakeAuditRepository()
    factory = FakeStorageFactory(storage)
    use_case = UploadCleaningPhotoUseCase(
        tasks=FakeTaskRepository(task),
        templates=FakeTemplateRepository(template),
        photos=photos,
        configs=FakeConfigRepository(storage_type),
        storage=factory,
        audit=audit,
        uow=uow,
        max_bytes=max_bytes,
    )
    return use_case, task, storage, photos, uow, audit, factory


def _cleaner() -> CleaningActor:
    return CleaningActor(user_id=CLEANER, role=UserRole.CLEANER, ip="10.0.0.9")


async def _upload(use_case, task, content=JPEG, photo_type="kitchen", actor=None):
    return await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        photo_type=photo_type,
        upload=FakeUpload(content),
        actor=actor or _cleaner(),
        now=NOW,
    )


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_happy_path_writes_the_object_then_the_row():
    use_case, task, storage, photos, uow, _, factory = _build()

    result = await _upload(use_case, task)

    assert len(storage.puts) == 1
    key, content, content_type = storage.puts[0]
    assert content == JPEG
    # From the CONTENT, never from anything the caller declared (R2.4, design D5).
    assert content_type == "image/jpeg"
    assert uow.commits == 1
    assert photos.added[0][1].storage_key == key
    assert result.url.startswith("/api/v1/cleaning-photos/")
    # R1.2: the backend was resolved from the tenant's stored configuration.
    assert factory.resolved == [StorageType.LOCAL]


@pytest.mark.asyncio
async def test_the_storage_key_is_derived_and_never_carries_client_input():
    """The obligation inherited from the section 1 panel, asserted rather than described.

    Every segment is something this system generated: the SESSION's tenant, the task that
    resolved inside it, a fresh photo id and an extension from the detected MIME. There is no
    request field that can reach any of them.
    """
    use_case, task, storage, photos, _, _, _ = _build()

    await _upload(use_case, task, content=PNG)

    key = storage.puts[0][0]
    photo = photos.added[0][1]
    assert key == f"tenants/{TENANT}/cleaning-tasks/{task.id}/{photo.id}.png"
    assert str(OTHER_TENANT) not in key


@pytest.mark.asyncio
async def test_uploaded_by_comes_from_the_authenticated_principal():
    """The obligation inherited from the section 2 panel.

    `cleaning_photos.uploaded_by` is an unrestricted FK to `users.id` and the repository
    writes it verbatim, so the only thing keeping a neighbour's user id out of it is that the
    use case reads the actor. There is no parameter through which a caller could supply one.
    """
    use_case, task, _, photos, _, _, _ = _build()

    await _upload(use_case, task)

    assert photos.added[0][1].uploaded_by == CLEANER


@pytest.mark.asyncio
async def test_uploaded_by_is_the_actor_and_not_the_task_s_assignee():
    """The same obligation, but built so that the two candidate sources DISAGREE.

    The test above cannot tell them apart, and that is not a flaw in how it was written — it
    is a property of the system. Mutating `uploaded_by=actor.user_id` to
    `task.assigned_cleaner_id` in `UploadCleaningPhotoUseCase.execute` kills no test reachable
    over HTTP, because only `CLEANER` holds `EXECUTE_CLEANING_TASKS` and `_load_task` then
    refuses any task whose `assigned_cleaner_id` is not the caller's own. On every path a
    request can take today the two values are the same object, so the mutant is **equivalent by
    construction** and no HTTP-level test can be written that distinguishes them.

    So this one goes under HTTP and builds the state the wiring cannot reach: a
    `PROPERTY_MANAGER` acting on a task assigned to somebody else. `restrict_to_cleaner_id`
    returns `None` for that role, so `_load_task` lets it through and `actor.user_id !=
    task.assigned_cleaner_id` for the first time.

    **This is a guard, not a description of today's behaviour.** No role other than `CLEANER`
    can reach this endpoint right now, and R6.4 says so. It is here for the day one does —
    `MANAGE_CLEANING_TASKS` growing an upload path, an admin backfill, a second use case
    reusing this one — because on that day `uploaded_by` silently starts recording the cleaner
    who was assigned instead of the person who actually uploaded, and `cleaning_photos` is the
    evidence trail for a dispute about who did what. The row must name the uploader.
    """
    template = _template()
    assigned_to_someone_else = _task(template_id=template.id)
    use_case, task, _, photos, _, audit, _ = _build(
        template=template, task=assigned_to_someone_else
    )
    manager = CleaningActor(user_id=MANAGER, role=UserRole.PROPERTY_MANAGER, ip="10.0.0.7")

    await _upload(use_case, task, actor=manager)

    assert task.assigned_cleaner_id == CLEANER
    assert MANAGER != CLEANER
    photo = photos.added[0][1]
    assert photo.uploaded_by == MANAGER
    assert photo.uploaded_by != task.assigned_cleaner_id
    # The audit row is derived from the same actor, so it must not diverge from the FK either.
    assert audit.entries[0].actor_user_id == MANAGER


@pytest.mark.asyncio
async def test_the_upload_is_audited_against_the_photo_with_actor_and_ip():
    """R2.7 and rule 9 of steering/security.md."""
    use_case, task, _, photos, _, audit, _ = _build()

    await _upload(use_case, task)

    entry = audit.entries[0]
    assert entry.action == audit_actions.CLEANING_PHOTO_UPLOADED
    assert entry.entity_type == audit_actions.ENTITY_CLEANING_PHOTO
    assert entry.entity_id == photos.added[0][1].id
    assert entry.actor_user_id == CLEANER
    assert entry.actor_ip == "10.0.0.9"


@pytest.mark.asyncio
async def test_the_audited_diff_never_carries_the_storage_key():
    """Rule 11 — `audit_logs.changes` is a cleartext sink, and R3.2's key is not going in it."""
    use_case, task, storage, _, _, audit, _ = _build()

    await _upload(use_case, task)

    assert storage.puts[0][0] not in str(audit.entries[0].changes)
    assert set(audit.entries[0].changes) == {
        "photo_type",
        "cleaning_task_id",
        "uploaded_by",
    }


# --- the refusals --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_photo_type_is_a_404_and_writes_nothing():
    use_case, task, storage, photos, uow, _, _ = _build()

    with pytest.raises(PhotoTypeNotFoundError):
        await _upload(use_case, task, photo_type="garage")

    assert storage.puts == []
    assert photos.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_task_that_is_not_in_progress_is_a_409_and_writes_nothing():
    """R2.3 — "sin escribir nada: ni fila ni objeto en el almacén"."""
    template = _template()
    use_case, task, storage, photos, uow, _, _ = _build(
        template=template,
        task=_task(CleaningTaskStatus.ACCEPTED, template_id=template.id),
    )

    with pytest.raises(InvalidCleaningTransitionError):
        await _upload(use_case, task)

    assert storage.puts == []
    assert photos.added == []


@pytest.mark.asyncio
async def test_a_file_that_is_not_an_accepted_image_is_a_422():
    use_case, task, storage, _, _, _, _ = _build()

    with pytest.raises(UnsupportedPhotoFormatError):
        await _upload(use_case, task, content=PDF)

    assert storage.puts == []


@pytest.mark.asyncio
async def test_a_pdf_renamed_to_jpg_is_still_refused():
    """R2.4 — the extension and the declared type are not consulted anywhere."""
    use_case, task, _, _, _, _, _ = _build()

    with pytest.raises(UnsupportedPhotoFormatError):
        await _upload(use_case, task, content=PDF + b".jpg")


@pytest.mark.asyncio
async def test_a_file_over_the_ceiling_is_a_413():
    use_case, task, storage, _, _, _, _ = _build()

    with pytest.raises(PhotoTooLargeError):
        await _upload(use_case, task, content=JPEG + b"\x00" * MAX_BYTES)

    assert storage.puts == []


@pytest.mark.asyncio
async def test_a_file_of_exactly_the_ceiling_is_accepted():
    """The exact boundary, asked for by the section 3 review panel. **Nobody pinned it.**

    `_read_within_limit` compares `received > self._max_bytes`, so `max_bytes` bytes are legal
    and `max_bytes + 1` is not. That strict `>` is the whole of the boundary and it was
    unasserted: every size test above works with a file several times the ceiling, so flipping
    the comparison to `>=` — an entirely plausible edit, and the direction a "surely it should
    reject *at* the limit" reading would push it — would keep all of them green while silently
    refusing every upload of exactly the configured maximum.

    Paired with the test below so the two sit one byte apart. A single test on either side
    would pin a threshold *somewhere*, not this one.
    """
    use_case, task, storage, photos, uow, _, _ = _build()
    exactly = JPEG_MAGIC + b"\x00" * (MAX_BYTES - len(JPEG_MAGIC))
    assert len(exactly) == MAX_BYTES

    await _upload(use_case, task, content=exactly)

    assert storage.puts[0][1] == exactly
    assert len(photos.added) == 1
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_a_file_one_byte_over_the_ceiling_is_a_413():
    """The other side of the same boundary — and nothing is written, not even the object."""
    use_case, task, storage, photos, uow, _, _ = _build()
    one_over = JPEG_MAGIC + b"\x00" * (MAX_BYTES + 1 - len(JPEG_MAGIC))
    assert len(one_over) == MAX_BYTES + 1

    with pytest.raises(PhotoTooLargeError):
        await _upload(use_case, task, content=one_over)

    assert storage.puts == []
    assert photos.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_the_ceiling_is_applied_while_streaming_not_after_buffering():
    """D11's actual claim: the read stops early, so a lying client cannot make us hold 50 MB.

    A use case that buffered the whole file and measured afterwards would raise the same
    `PhotoTooLargeError` and pass the test above. This one fails it.

    Sized in chunks, not in bytes: the claim is "it stops reading", and with a file smaller
    than one chunk there is nothing to stop before.
    """
    oversized = JPEG + b"\x00" * (_UPLOAD_CHUNK_BYTES * 8)
    upload = FakeUpload(oversized)
    use_case, task, _, _, _, _, _ = _build()

    with pytest.raises(PhotoTooLargeError):
        await use_case.execute(
            tenant_id=TENANT,
            task_id=task.id,
            photo_type="kitchen",
            upload=upload,
            actor=_cleaner(),
            now=NOW,
        )

    assert upload.bytes_served <= MAX_BYTES + _UPLOAD_CHUNK_BYTES
    assert upload.bytes_served < len(oversized)


@pytest.mark.asyncio
async def test_a_storage_failure_is_a_502_and_leaves_no_row():
    """R1.5 — and note it needs no compensation: nothing had been inserted yet."""
    use_case, task, _, photos, uow, _, _ = _build(storage=FakeStorage(fail_put=True))

    with pytest.raises(PhotoStorageUnavailableError):
        await _upload(use_case, task)

    assert photos.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_failed_commit_deletes_the_object():
    """Design D4 — the compensating delete, and the only caller `FileStoragePort.delete` has.

    The accepted failure mode is an orphaned object; the forbidden one is a row pointing at
    nothing, because that is a broken `GET` for ever.
    """
    storage = FakeStorage()
    use_case, task, storage, _, _, _, _ = _build(
        storage=storage, uow=FakeUnitOfWork(fail=True)
    )

    with pytest.raises(RuntimeError):
        await _upload(use_case, task)

    assert storage.deletes == [storage.puts[0][0]]


@pytest.mark.asyncio
async def test_a_failed_row_insert_also_deletes_the_object():
    """The same compensation, one step earlier — `add` resolves the parent inside the tenant."""
    storage = FakeStorage()
    use_case, task, storage, _, _, _, _ = _build(
        storage=storage, photos=FakePhotoRepository(fail=CleaningTaskNotFoundError())
    )

    with pytest.raises(CleaningTaskNotFoundError):
        await _upload(use_case, task)

    assert storage.deletes == [storage.puts[0][0]]


@pytest.mark.asyncio
async def test_a_failing_compensation_does_not_replace_the_real_error():
    """Best effort by contract: the cleanup must not become the reported failure."""
    use_case, task, _, _, _, _, _ = _build(
        storage=FakeStorage(fail_delete=True), uow=FakeUnitOfWork(fail=True)
    )

    with pytest.raises(RuntimeError, match="could not be committed"):
        await _upload(use_case, task)


@pytest.mark.asyncio
async def test_a_task_of_another_tenant_is_the_same_404_as_an_unknown_id():
    """R6.3 — and the message is the shared constant, not a variant of it."""
    use_case, task, _, _, _, _, _ = _build()

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        await use_case.execute(
            tenant_id=OTHER_TENANT,
            task_id=task.id,
            photo_type="kitchen",
            upload=FakeUpload(JPEG),
            actor=_cleaner(),
            now=NOW,
        )

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_a_cleaner_cannot_upload_to_a_task_assigned_to_someone_else():
    """R6.4 — derived from the persisted role, with no request parameter in the path."""
    use_case, task, _, _, _, _, _ = _build()
    other_cleaner = CleaningActor(user_id=uuid.uuid4(), role=UserRole.CLEANER)

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        await _upload(use_case, task, actor=other_cleaner)

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE
