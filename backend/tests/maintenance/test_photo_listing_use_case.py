"""R3 — `ListIncidentPhotosUseCase`, against fakes of every port it holds.

Three properties, and the first two are the ones a status-code test cannot reach:

* **the order is oldest first** (R3.1), which is the whole point of a listing whose two stages
  are `BEFORE` and `AFTER`. Here the repository fake returns whatever it was given, so the
  ordering the use case is responsible for is *not* under test — the ordering belongs to the
  adapter's `ORDER BY` and is pinned in `tests/maintenance/test_repositories.py`. What this file
  pins is that the use case **preserves** what the repository handed it rather than re-sorting,
  grouping or reversing it.
* **the URL is minted per response** (R3.1), never read from the row. The fake storage stamps a
  counter into each URL, so a use case that cached or reused one would be visible.
* **the `404` is the shared, byte-identical one** (R3.4). Two of R3.4's three cases are
  separately observable at this layer — an incident that does not exist and one assigned to a
  different technician. The third, an incident of another tenant, is the *same branch*:
  `IncidentRepository.get` answers `None` for it, so only a real database can tell them apart,
  and `tests/maintenance/test_repositories.py` is where that happens.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.domain.enums import UserRole
from app.maintenance.application.use_cases import (
    IncidentActor,
    ListIncidentPhotosUseCase,
)
from app.maintenance.domain.entities import Incident, IncidentPhoto
from app.maintenance.domain.enums import (
    IncidentPhotoStage,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.domain.exceptions import IncidentNotFoundError
from app.tenants.domain.enums import StorageType

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
PROPERTY = uuid.uuid4()
TECHNICIAN = uuid.uuid4()
OTHER_TECHNICIAN = uuid.uuid4()
MANAGER = uuid.uuid4()
OWNER = uuid.uuid4()


# --- fakes ---------------------------------------------------------------------------


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
    """Hands back exactly what it was given, in the given order.

    Deliberately does **not** sort: the `ORDER BY` is the adapter's job and is asserted against
    a real database in `tests/maintenance/test_repositories.py`. Sorting here would hide a use
    case that reordered what it received.
    """

    def __init__(self, photos: list[IncidentPhoto]) -> None:
        self._photos = photos
        self.asked: list[tuple] = []

    async def list_for_incident(self, tenant_id, incident_id):
        self.asked.append((tenant_id, incident_id))
        return list(self._photos)


class FakeConfigRepository:
    def __init__(self, storage_type: StorageType = StorageType.LOCAL) -> None:
        self._storage_type = storage_type
        self.asked: list[uuid.UUID] = []

    async def get_or_create(self, tenant_id, now):
        self.asked.append(tenant_id)

        class _Config:
            storage_type = self._storage_type

        return _Config()


class FakeStorage:
    """Stamps a monotonically increasing counter into every URL it mints.

    That is what makes "acuñada para esa respuesta" checkable: two identical URLs for two
    different photos, or a URL repeated across two calls, both become visible.
    """

    def __init__(self) -> None:
        self.minted = 0
        self.keys: list[str] = []

    def signed_url(self, key, *, expires_in=3600) -> str:
        self.minted += 1
        self.keys.append(key)
        return f"/api/v1/incident-photos/{key}?sig=mint{self.minted}"


class FakeStorageFactory:
    def __init__(self, storage: FakeStorage) -> None:
        self._storage = storage
        self.resolved: list[StorageType] = []

    def storage_for(self, storage_type):
        self.resolved.append(storage_type)
        return self._storage


# --- builders ------------------------------------------------------------------------


def _incident(assigned_to: uuid.UUID | None = TECHNICIAN) -> Incident:
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
    incident.status = IncidentStatus.IN_PROGRESS
    incident.assigned_technician_id = assigned_to
    return incident


def _photo(incident: Incident, *, stage: IncidentPhotoStage, minutes: int) -> IncidentPhoto:
    photo_id = uuid.uuid4()
    return IncidentPhoto(
        id=photo_id,
        tenant_id=TENANT,
        incident_id=incident.id,
        uploaded_by=TECHNICIAN,
        stage=stage,
        storage_key=f"tenants/{TENANT}/incidents/{incident.id}/{photo_id}.jpg",
        created_at=NOW + timedelta(minutes=minutes),
    )


def _actor(role: UserRole = UserRole.TECHNICIAN, user_id: uuid.UUID = TECHNICIAN):
    return IncidentActor(user_id=user_id, role=role, ip="203.0.113.7")


def _build(
    *,
    incident: Incident | None = None,
    photos: list[IncidentPhoto] | None = None,
    storage_type: StorageType = StorageType.LOCAL,
):
    storage = FakeStorage()
    factory = FakeStorageFactory(storage)
    repo = FakePhotoRepository(photos or [])
    use_case = ListIncidentPhotosUseCase(
        incidents=FakeIncidentRepository(incident),
        photos=repo,
        configs=FakeConfigRepository(storage_type),
        storage=factory,
    )
    return use_case, storage, repo, factory


async def _list(use_case, incident, *, actor=None):
    return await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=actor or _actor(),
        now=NOW,
    )


# --- the listing ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_incident_with_no_photos_lists_empty() -> None:
    incident = _incident()
    use_case, storage, _, _ = _build(incident=incident)

    assert await _list(use_case, incident) == ()
    # No URL was minted, because there was nothing to mint one for.
    assert storage.minted == 0


@pytest.mark.asyncio
async def test_the_order_the_repository_gave_is_preserved() -> None:
    """R3.1 — the use case does not re-sort, reverse or group.

    The adapter's `ORDER BY created_at, id` is what produces the order (pinned against a real
    database in `test_repositories.py`); this asserts the use case is transparent to it.
    """
    incident = _incident()
    before = _photo(incident, stage=IncidentPhotoStage.BEFORE, minutes=0)
    after = _photo(incident, stage=IncidentPhotoStage.AFTER, minutes=30)
    use_case, _, _, _ = _build(incident=incident, photos=[before, after])

    listed = await _list(use_case, incident)

    assert [item.photo.id for item in listed] == [before.id, after.id]
    assert [item.photo.stage for item in listed] == [
        IncidentPhotoStage.BEFORE,
        IncidentPhotoStage.AFTER,
    ]


@pytest.mark.asyncio
async def test_several_photos_of_the_same_stage_all_come_back() -> None:
    """R1.4 through the listing: two angles of one fault are two entries, not one."""
    incident = _incident()
    photos = [
        _photo(incident, stage=IncidentPhotoStage.AFTER, minutes=n) for n in (0, 5, 10)
    ]
    use_case, _, _, _ = _build(incident=incident, photos=photos)

    listed = await _list(use_case, incident)

    assert [item.photo.id for item in listed] == [p.id for p in photos]


@pytest.mark.asyncio
async def test_every_photo_gets_its_own_freshly_minted_url() -> None:
    """R3.1's "acuñada para esa respuesta" — one mint per photo, all distinct."""
    incident = _incident()
    photos = [
        _photo(incident, stage=IncidentPhotoStage.BEFORE, minutes=0),
        _photo(incident, stage=IncidentPhotoStage.AFTER, minutes=1),
    ]
    use_case, storage, _, _ = _build(incident=incident, photos=photos)

    listed = await _list(use_case, incident)

    assert storage.minted == 2
    assert len({item.url for item in listed}) == 2
    # Each URL was minted over that photo's own key.
    assert storage.keys == [p.storage_key for p in photos]


@pytest.mark.asyncio
async def test_a_second_call_mints_new_urls() -> None:
    """The URL is per response, not cached on the row or memoised on the use case."""
    incident = _incident()
    photos = [_photo(incident, stage=IncidentPhotoStage.BEFORE, minutes=0)]
    use_case, storage, _, _ = _build(incident=incident, photos=photos)

    first = await _list(use_case, incident)
    second = await _list(use_case, incident)

    assert storage.minted == 2
    assert first[0].url != second[0].url


@pytest.mark.asyncio
async def test_the_repository_is_asked_within_the_tenant() -> None:
    """Rule 1's mechanism: the tenant is passed explicitly, not left to the session listener."""
    incident = _incident()
    use_case, _, repo, _ = _build(incident=incident)

    await _list(use_case, incident)

    assert repo.asked == [(TENANT, incident.id)]


# --- the shared 404 (R3.4) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_incident_raises_not_found() -> None:
    use_case, _, repo, _ = _build(incident=None)

    with pytest.raises(IncidentNotFoundError):
        await _list(use_case, _incident())

    # The photo repository was never reached: resolving the incident comes first, which is what
    # makes an empty list and a missing incident different outcomes.
    assert repo.asked == []


@pytest.mark.asyncio
async def test_a_technician_who_is_not_the_assignee_raises_not_found() -> None:
    """R3.2/R3.4 — the same error an unknown incident raises, derived from the token's role."""
    incident = _incident(assigned_to=OTHER_TECHNICIAN)
    use_case, _, repo, _ = _build(incident=incident)

    with pytest.raises(IncidentNotFoundError):
        await _list(use_case, incident)

    assert repo.asked == []


@pytest.mark.asyncio
async def test_both_refusals_carry_the_same_message() -> None:
    """R3.4 asks for *indistinguishable*, which is a property of the message and not only of
    the type — two `404`s with different bodies are still distinguishable to a caller.

    **Two cases, not three, and the honest reason is worth stating**: at this layer "an
    incident of another tenant" and "an incident that never existed" are the *same code path*
    — `IncidentRepository.get` answers `None` for both, and the fake reproduces exactly that.
    The third case only becomes separately observable against a real database, where
    `tests/maintenance/test_repositories.py` covers it. Claiming three here would be counting
    the same branch twice.
    """
    unknown_use_case, _, _, _ = _build(incident=None)
    foreign = _incident(assigned_to=OTHER_TECHNICIAN)
    unassigned_use_case, _, _, _ = _build(incident=foreign)

    messages = set()
    for use_case, incident in (
        (unknown_use_case, _incident()),
        (unassigned_use_case, foreign),
    ):
        with pytest.raises(IncidentNotFoundError) as raised:
            await _list(use_case, incident)
        messages.add(str(raised.value))

    assert len(messages) == 1


# --- who may list (R3.2) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "user_id"),
    [
        (UserRole.PROPERTY_MANAGER, MANAGER),
        (UserRole.TENANT_OWNER, OWNER),
    ],
)
@pytest.mark.asyncio
async def test_a_manager_or_owner_sees_photos_of_any_incident_of_the_tenant(
    role: UserRole, user_id: uuid.UUID
) -> None:
    """R3.2 — only a `TECHNICIAN` is narrowed to their own assignments.

    Driven against an incident assigned to somebody else, which is exactly the case a
    row-level restriction would wrongly hide.
    """
    incident = _incident(assigned_to=OTHER_TECHNICIAN)
    photos = [_photo(incident, stage=IncidentPhotoStage.BEFORE, minutes=0)]
    use_case, _, _, _ = _build(incident=incident, photos=photos)

    listed = await _list(use_case, incident, actor=_actor(role, user_id))

    assert [item.photo.id for item in listed] == [photos[0].id]


@pytest.mark.asyncio
async def test_the_assigned_technician_sees_their_own_incident() -> None:
    incident = _incident(assigned_to=TECHNICIAN)
    photos = [_photo(incident, stage=IncidentPhotoStage.AFTER, minutes=0)]
    use_case, _, _, _ = _build(incident=incident, photos=photos)

    listed = await _list(use_case, incident)

    assert len(listed) == 1


# --- the backend stays unknown --------------------------------------------------------


@pytest.mark.parametrize("storage_type", [StorageType.LOCAL, StorageType.S3])
@pytest.mark.asyncio
async def test_the_use_case_does_not_branch_on_the_backend(
    storage_type: StorageType,
) -> None:
    incident = _incident()
    photos = [_photo(incident, stage=IncidentPhotoStage.BEFORE, minutes=0)]
    use_case, storage, _, factory = _build(
        incident=incident, photos=photos, storage_type=storage_type
    )

    listed = await _list(use_case, incident)

    assert factory.resolved == [storage_type]
    assert storage.minted == 1
    assert listed[0].url
