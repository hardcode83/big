"""R2 — `UploadIncidentPhotoUseCase`, against fakes of every port it holds.

No database and no disk: what is under test is the ORDER of the operations and the outcome of
each refusal, and both are properties of the use case rather than of any adapter. The two that
only a fake can pin are the ones design D7 argues hardest for:

* **object first, row second, and the object is deleted when anything after it fails.** A real
  session would make "did the row survive?" observable and leave "was the object removed?"
  invisible, which is the half R2.7 is about. Design D7's `try` wraps **three** steps — the row
  insert, the audit write and the commit — and each of the three has its own test here, because
  they share one `except` and a regression on any single branch would otherwise be invisible.
* **the size ceiling is applied while consuming the stream**, not after buffering it. The fake
  upload below counts how much was asked for, so a use case that read the file whole and then
  measured it would fail here even though the status code came out right.

Modelled on `tests/cleaning/test_photo_upload_use_case.py`, deliberately: the two use cases are
near-identical by design, and keeping the test shapes aligned is what makes a divergence between
them visible.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions as audit_actions
from app.auth.domain.enums import UserRole
from app.integrations.domain.storage import StorageWriteError
from app.maintenance.application.use_cases import (
    _UPLOAD_CHUNK_BYTES,
    IncidentActor,
    UploadIncidentPhotoUseCase,
)
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import (
    IncidentPhotoStage,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentBlockedByPendingApprovalError,
    IncidentNotFoundError,
    IncidentPhotoStorageUnavailableError,
    IncidentPhotoTooLargeError,
    InvalidIncidentTransitionError,
    UnsupportedIncidentPhotoFormatError,
)
from app.tenants.domain.enums import StorageType

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
PROPERTY = uuid.uuid4()
TECHNICIAN = uuid.uuid4()
OTHER_TECHNICIAN = uuid.uuid4()
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


class FakeIncidentRepository:
    def __init__(self, incident: Incident | None) -> None:
        self._incident = incident

    async def get(self, tenant_id, incident_id):
        if (
            self._incident is None
            or tenant_id != TENANT
            or incident_id != self._incident.id
        ):
            return None
        return self._incident


class FakePhotoRepository:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.added: list = []
        self._fail = fail

    async def add(self, tenant_id, photo) -> None:
        if self._fail is not None:
            raise self._fail
        self.added.append((tenant_id, photo))

    async def list_for_incident(self, tenant_id, incident_id):
        return [photo for _, photo in self.added]


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
        return f"/api/v1/incident-photos/{key}?sig=fake"

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


def _incident(
    status: IncidentStatus = IncidentStatus.IN_PROGRESS,
    *,
    assigned_to: uuid.UUID | None = TECHNICIAN,
) -> Incident:
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=PROPERTY,
        source=IncidentSource.CLEANER,
        title="Broken AC",
        description="The AC unit is not cooling.",
        created_at=NOW,
        updated_at=NOW,
    )
    incident.status = status
    incident.assigned_technician_id = assigned_to
    return incident


def _actor(role: UserRole = UserRole.TECHNICIAN, user_id: uuid.UUID = TECHNICIAN):
    return IncidentActor(user_id=user_id, role=role, ip="203.0.113.7")


def _build(
    *,
    incident: Incident | None = None,
    storage_type: StorageType = StorageType.LOCAL,
    fail_put: bool = False,
    fail_delete: bool = False,
    photo_add_error: Exception | None = None,
    commit_fails: bool = False,
    max_bytes: int = MAX_BYTES,
):
    storage = FakeStorage(fail_put=fail_put, fail_delete=fail_delete)
    factory = FakeStorageFactory(storage)
    photos = FakePhotoRepository(fail=photo_add_error)
    audit = FakeAuditRepository()
    uow = FakeUnitOfWork(fail=commit_fails)
    use_case = UploadIncidentPhotoUseCase(
        incidents=FakeIncidentRepository(incident),
        photos=photos,
        configs=FakeConfigRepository(storage_type),
        storage=factory,
        audit=audit,
        uow=uow,
        max_bytes=max_bytes,
    )
    return use_case, storage, photos, audit, uow, factory


async def _upload(
    use_case,
    incident,
    *,
    content: bytes = JPEG,
    stage: IncidentPhotoStage = IncidentPhotoStage.BEFORE,
    actor=None,
):
    return await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        stage=stage,
        upload=FakeUpload(content),
        actor=actor or _actor(),
        now=NOW,
    )


# --- the happy path -------------------------------------------------------------------


@pytest.mark.parametrize(
    "status", [IncidentStatus.IN_PROGRESS, IncidentStatus.WAITING_EXTERNAL_PARTS]
)
@pytest.mark.asyncio
async def test_the_two_working_statuses_accept_an_upload(status: IncidentStatus) -> None:
    """R2.1/R2.4 — both states in which the technician's work is under way."""
    incident = _incident(status)
    use_case, storage, photos, audit, uow, _ = _build(incident=incident)

    result = await _upload(use_case, incident)

    assert len(storage.puts) == 1
    assert len(photos.added) == 1
    assert len(audit.entries) == 1
    assert uow.commits == 1
    assert result.photo.stage is IncidentPhotoStage.BEFORE
    assert result.url.startswith("/api/v1/incident-photos/")


@pytest.mark.asyncio
async def test_the_key_is_built_from_the_session_tenant_and_the_detected_extension() -> None:
    """R1.5 and design D4: no client input reaches the key, and the extension comes from bytes."""
    incident = _incident()
    use_case, storage, _, _, _, _ = _build(incident=incident)

    result = await _upload(use_case, incident, content=PNG)

    key, _, content_type = storage.puts[0]
    assert key.startswith(f"tenants/{TENANT}/incidents/{incident.id}/")
    assert key.endswith(".png")
    assert content_type == "image/png"
    # And the key never comes back in the entity's place in the response contract's stead:
    # the use case returns it inside the entity, which the schema is responsible for not dumping.
    assert result.photo.storage_key == key


@pytest.mark.asyncio
async def test_uploaded_by_comes_from_the_token_and_not_the_request() -> None:
    """The guarantee the use case docstring claims: `actor.user_id`, never a body field.

    Driven with a `PROPERTY_MANAGER`, whose id differs from the assignee's, so a use case that
    took the uploader from the incident's `assigned_technician_id` would fail here.
    """
    incident = _incident()
    use_case, _, photos, _, _, _ = _build(incident=incident)

    await _upload(use_case, incident, actor=_actor(UserRole.PROPERTY_MANAGER, MANAGER))

    _, photo = photos.added[0]
    assert photo.uploaded_by == MANAGER
    assert photo.uploaded_by != incident.assigned_technician_id


@pytest.mark.asyncio
async def test_the_stage_is_persisted_as_given() -> None:
    incident = _incident()
    use_case, _, photos, _, _, _ = _build(incident=incident)

    await _upload(use_case, incident, stage=IncidentPhotoStage.AFTER)

    _, photo = photos.added[0]
    assert photo.stage is IncidentPhotoStage.AFTER


# --- row-level scoping (R2.3) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_technician_who_is_not_the_assignee_gets_the_same_404() -> None:
    """R2.3 — indistinguishable from "no such incident", and derived from the token's role.

    The refusal comes from `_load_incident_in_scope` via `IncidentActor.restrict_to_technician_id`,
    so there is no request field through which the restriction could be widened.
    """
    incident = _incident(assigned_to=OTHER_TECHNICIAN)
    use_case, storage, photos, _, _, _ = _build(incident=incident)

    with pytest.raises(IncidentNotFoundError):
        await _upload(use_case, incident)

    # Nothing was written anywhere: the refusal precedes every side effect.
    assert storage.puts == []
    assert photos.added == []


@pytest.mark.asyncio
async def test_an_unknown_incident_raises_the_same_error_as_a_foreign_one() -> None:
    use_case, _, _, _, _, _ = _build(incident=None)

    with pytest.raises(IncidentNotFoundError):
        await _upload(use_case, _incident())


@pytest.mark.asyncio
async def test_a_manager_is_not_restricted_to_an_assignment() -> None:
    """R2.2 — `PROPERTY_MANAGER` drives the whole technician cycle "para desatascar"."""
    incident = _incident(assigned_to=OTHER_TECHNICIAN)
    use_case, storage, _, _, _, _ = _build(incident=incident)

    await _upload(use_case, incident, actor=_actor(UserRole.PROPERTY_MANAGER, MANAGER))

    assert len(storage.puts) == 1


# --- the three distinguishable state refusals (R2.4, R2.5, R2.6) ----------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (IncidentStatus.RESOLVED, IncidentAlreadyClosedError),
        (IncidentStatus.CANCELLED, IncidentAlreadyClosedError),
        (IncidentStatus.AWAITING_OWNER_APPROVAL, IncidentBlockedByPendingApprovalError),
        (IncidentStatus.OPEN, InvalidIncidentTransitionError),
        (IncidentStatus.CLASSIFIED, InvalidIncidentTransitionError),
        (IncidentStatus.ASSIGNED, InvalidIncidentTransitionError),
        (IncidentStatus.ACCEPTED, InvalidIncidentTransitionError),
    ],
)
@pytest.mark.asyncio
async def test_each_refused_status_raises_its_own_error(
    status: IncidentStatus, expected: type[Exception]
) -> None:
    """R2.4/R2.5/R2.6 — three distinguishable refusals, and the use case does not flatten them.

    The entity decides (design D6); what this pins is that the use case propagates the specific
    type rather than catching and re-raising something generic.
    """
    incident = _incident(status)
    use_case, storage, photos, _, uow, _ = _build(incident=incident)

    with pytest.raises(expected):
        await _upload(use_case, incident)

    assert storage.puts == []
    assert photos.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_refused_status_writes_nothing_at_all() -> None:
    """R2.4's "sin escribir nada: ni fila ni objeto en el almacén", asserted over every sink."""
    incident = _incident(IncidentStatus.RESOLVED)
    use_case, storage, photos, audit, uow, factory = _build(incident=incident)

    with pytest.raises(IncidentAlreadyClosedError):
        await _upload(use_case, incident)

    assert (storage.puts, storage.deletes, photos.added, audit.entries, uow.commits) == (
        [],
        [],
        [],
        [],
        0,
    )
    # The tenant's backend was never even resolved: the gate is before the storage lookup.
    assert factory.resolved == []


# --- format and size (R2.9, R5.1) -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_non_image_is_refused_by_its_bytes() -> None:
    """R2.9 — the format is decided by the content, never by a declared `Content-Type`.

    The fake upload carries no content type at all, which is the point: there is nothing for the
    use case to be fooled by, because it never asks.
    """
    incident = _incident()
    use_case, storage, photos, _, _, _ = _build(incident=incident)

    with pytest.raises(UnsupportedIncidentPhotoFormatError):
        await _upload(use_case, incident, content=PDF)

    assert storage.puts == []
    assert photos.added == []


@pytest.mark.asyncio
async def test_an_empty_upload_is_refused_as_an_unsupported_format() -> None:
    """A zero-byte file cannot match any signature, and slicing past the end yields a short
    slice rather than raising — so it falls through to the format refusal, not a crash."""
    incident = _incident()
    use_case, _, _, _, _, _ = _build(incident=incident)

    with pytest.raises(UnsupportedIncidentPhotoFormatError):
        await _upload(use_case, incident, content=b"")


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused() -> None:
    incident = _incident()
    use_case, storage, photos, _, _, _ = _build(incident=incident, max_bytes=16)

    with pytest.raises(IncidentPhotoTooLargeError):
        await _upload(use_case, incident, content=JPEG_MAGIC + b"x" * 64)

    assert storage.puts == []
    assert photos.added == []


@pytest.mark.asyncio
async def test_the_ceiling_is_applied_while_consuming_and_not_after_buffering() -> None:
    """R5.1's in-process half, and the assertion only a counting fake can make.

    A use case that read the whole file and then measured it would produce the same exception
    and the same status code, so the status code cannot tell the two apart. What distinguishes
    them is how much was ever asked for: at most the ceiling plus one chunk.
    """
    incident = _incident()
    use_case, _, _, _, _, _ = _build(incident=incident, max_bytes=MAX_BYTES)
    upload = FakeUpload(JPEG_MAGIC + b"x" * (MAX_BYTES * 8))

    with pytest.raises(IncidentPhotoTooLargeError):
        await use_case.execute(
            tenant_id=TENANT,
            incident_id=incident.id,
            stage=IncidentPhotoStage.BEFORE,
            upload=upload,
            actor=_actor(),
            now=NOW,
        )

    assert upload.bytes_served <= MAX_BYTES + _UPLOAD_CHUNK_BYTES


@pytest.mark.asyncio
async def test_a_file_exactly_at_the_ceiling_is_accepted() -> None:
    """The boundary is `>`, not `>=`: a photo of exactly the maximum size is legal."""
    incident = _incident()
    use_case, storage, _, _, _, _ = _build(incident=incident, max_bytes=64)

    await _upload(use_case, incident, content=JPEG_MAGIC + b"x" * (64 - len(JPEG_MAGIC)))

    assert len(storage.puts) == 1


# --- storage failure and the compensating delete (R2.7, R2.8, design D7) --------------


@pytest.mark.asyncio
async def test_a_storage_failure_leaves_no_row() -> None:
    """R2.8 — `502` territory, and nothing to compensate because the object goes first."""
    incident = _incident()
    use_case, storage, photos, audit, uow, _ = _build(incident=incident, fail_put=True)

    with pytest.raises(IncidentPhotoStorageUnavailableError):
        await _upload(use_case, incident)

    assert photos.added == []
    assert audit.entries == []
    assert uow.commits == 0
    # Nothing was stored, so nothing had to be removed.
    assert storage.deletes == []


@pytest.mark.asyncio
async def test_the_object_is_written_before_the_row() -> None:
    """Design D7's order, asserted as a fact about the sequence rather than inferred.

    Driven by making the row insert fail: if the row went first, the object would never have
    been written, and `storage.puts` would be empty.
    """
    incident = _incident()
    boom = RuntimeError("the insert exploded")
    use_case, storage, photos, _, _, _ = _build(
        incident=incident, photo_add_error=boom
    )

    with pytest.raises(RuntimeError):
        await _upload(use_case, incident)

    assert len(storage.puts) == 1
    assert photos.added == []
    # And the object did not survive the failure. Asserted here and not only in the
    # commit-failure test because the `try` of design D7 wraps **three** steps — the row, the
    # audit row and the commit — and a regression that broke the delete on this branch alone
    # (an early return before the `except`) would otherwise slip past the whole file. Raised by
    # the section 6 QA panel, which reproduced the fire on all three branches.
    assert storage.deletes == [storage.puts[0][0]]


@pytest.mark.asyncio
async def test_a_failed_audit_write_also_deletes_the_object() -> None:
    """The third branch of design D7's `try`, and the one nothing exercised.

    The module claims the compensating delete covers row-insert, audit-write and commit alike,
    because all three sit inside one `except Exception`. Two of the three had tests; this is the
    audit one. Raised by the section 6 QA panel, which confirmed by probe that the delete does
    fire here — so this pins behaviour that was already correct rather than fixing a bug.

    It matters beyond completeness: an audit failure is the one of the three that would
    otherwise leave a stored object with **no** record of who put it there, which is precisely
    the state rule 9 of `steering/security.md` exists to prevent.
    """
    incident = _incident()
    use_case, storage, photos, audit, uow, _ = _build(incident=incident)

    # Make the audit write fail, leaving the row insert already done inside the transaction.
    async def _explode(tenant_id, entry):
        raise RuntimeError("the audit row could not be written")

    audit.add = _explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="audit row could not be written"):
        await _upload(use_case, incident)

    assert len(storage.puts) == 1
    assert storage.deletes == [storage.puts[0][0]]
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_failed_commit_deletes_the_object() -> None:
    """R2.7 — the forbidden direction is a row pointing at an object that is not there, so the
    survivable failure is an orphaned object, and design D7 removes it."""
    incident = _incident()
    use_case, storage, _, _, uow, _ = _build(incident=incident, commit_fails=True)

    with pytest.raises(RuntimeError):
        await _upload(use_case, incident)

    assert len(storage.puts) == 1
    assert storage.deletes == [storage.puts[0][0]]
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_failed_compensating_delete_does_not_mask_the_real_failure() -> None:
    """Best effort by contract: the delete must not replace the original error on the way out.

    Without the `except Exception` inside `_delete_quietly`, the caller would see
    `StorageWriteError("cannot delete either")` and lose the fact that the commit failed.
    """
    incident = _incident()
    use_case, _, _, _, _, _ = _build(
        incident=incident, commit_fails=True, fail_delete=True
    )

    with pytest.raises(RuntimeError, match="could not be committed"):
        await _upload(use_case, incident)


# --- the audit row (R6.1, R6.2) -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_audit_row_points_at_the_photo_and_not_the_incident() -> None:
    """R6.1 — `entity_id` is what the audit index is built on."""
    incident = _incident()
    use_case, _, photos, audit, _, _ = _build(incident=incident)

    await _upload(use_case, incident)

    _, photo = photos.added[0]
    entry = audit.entries[0]
    assert entry.entity_type == audit_actions.ENTITY_INCIDENT_PHOTO
    assert entry.entity_id == photo.id
    assert entry.entity_id != incident.id
    assert entry.action == audit_actions.INCIDENT_PHOTO_UPLOADED


@pytest.mark.asyncio
async def test_the_audit_row_names_its_actor_and_ip() -> None:
    """R6.1 and rule 9: `actor_ip` is one of the two things `audit_logs` keeps that a
    domain-specific table cannot."""
    incident = _incident()
    use_case, _, _, audit, _, _ = _build(incident=incident)

    await _upload(use_case, incident)

    entry = audit.entries[0]
    assert entry.actor_user_id == TECHNICIAN
    assert entry.actor_ip == "203.0.113.7"


@pytest.mark.asyncio
async def test_the_audit_row_never_carries_the_storage_key() -> None:
    """R6.2 — asserted over the serialised diff, not over the allowlist.

    The allowlist is checked in `tests/audit/test_incident_photo_vocabulary.py`; what this pins
    is that the value the use case actually writes does not contain the key by some other route
    (a stray field name, a stringified entity).
    """
    incident = _incident()
    use_case, storage, _, audit, _, _ = _build(incident=incident)

    await _upload(use_case, incident)

    key = storage.puts[0][0]
    changes = audit.entries[0].changes
    assert "storage_key" not in changes
    assert key not in str(changes)


@pytest.mark.asyncio
async def test_the_audit_diff_carries_the_three_allowlisted_facts() -> None:
    incident = _incident()
    use_case, _, photos, audit, _, _ = _build(incident=incident)

    await _upload(use_case, incident, stage=IncidentPhotoStage.AFTER)

    _, photo = photos.added[0]
    changes = audit.entries[0].changes
    assert set(changes) == {"stage", "incident_id", "uploaded_by"}
    assert changes["stage"]["new"] == IncidentPhotoStage.AFTER.value
    assert changes["incident_id"]["new"] == str(photo.incident_id)


# --- the backend stays unknown to the use case (design D10) ---------------------------


@pytest.mark.parametrize("storage_type", [StorageType.LOCAL, StorageType.S3])
@pytest.mark.asyncio
async def test_the_use_case_does_not_learn_which_backend_answered(
    storage_type: StorageType,
) -> None:
    """The factory answers from the tenant's stored `storage_type`; the use case never branches
    on it, so both backends take the identical path through this code."""
    incident = _incident()
    use_case, storage, photos, _, _, factory = _build(
        incident=incident, storage_type=storage_type
    )

    result = await _upload(use_case, incident)

    assert factory.resolved == [storage_type]
    assert len(storage.puts) == 1
    assert len(photos.added) == 1
    assert result.url
