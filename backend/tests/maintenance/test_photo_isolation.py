"""R6.3 — no tenant reaches another's `incident_photos` row, by any of the three routes.

**This file exists because nothing else in the change satisfies R6.3.** The section 7-9 tenancy
panel checked and found the requirement at zero of three routes: every "isolation-adjacent" test
written so far builds exactly one tenant, so what they demonstrate is row-level scoping (the
assignee restriction) or leakage shape (`storage_key` absent), not tenant isolation. Those tests
now say so in their own docstrings. This is the one that carries the requirement.

**Two kinds of assertion live here and the difference matters**, because it is the difference
between a test that can fail and a test that merely passes:

* *End-to-end* — an authenticated caller of tenant A asks for a row of tenant B through the real
  app and gets the module's `404`. Honest about what it proves: by the time it asserts, the
  request's session is bound to the caller's tenant, so the **global listener** of
  `app/core/db.py` would produce that `404` even if the repository had forgotten its `WHERE`.
  It is worth pinning end to end anyway — the net is a real guarantee and this is the only place
  it is exercised through these three routes — but it cannot fail on the module's own scoping.
* *Mechanism* — a spy on the repository asserting the `tenant_id` it received is the **caller's**
  and never one derived from the request. That one can fail, and it is what `maintenance`'s own
  `test_the_api_scopes_the_lookup_to_the_callers_own_tenant` established as the honest shape.

Both are written for each of the three routes, and the docstrings say which is which.

**The fixture is not `conftest.py`'s `api`.** That one hands every request the same session and
never clears `session.info`, so a second `auth_header` for another tenant would trip
`bind_session_to_tenant`'s rebind guard and 500 instead of exercising the route. This file uses
`request_session_override`, which resets the marker when a request ends — the one property of
session-per-request that makes a two-tenant HTTP scenario expressible at all, and the same
override the anonymous serving route's own tests need for a different reason.
"""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.integrations.api.dependencies import get_url_signing_key
from app.integrations.domain.storage import derive_signing_key, sign_storage_key
from app.integrations.infrastructure.storage import (
    INCIDENT_PHOTO_URL_PREFIX,
    ConfiguredFileStorageFactory,
)
from app.maintenance.api.dependencies import get_incident_photo_storage_factory
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel, IncidentPhotoModel
from app.properties.infrastructure.models import PropertyModel
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from tests.conftest import request_session_override
from tests.maintenance.conftest import (  # noqa: F401
    SECRET,
    World,
    _user,
    auth_header,
    make_incident,
    world,
)

INCIDENTS = "/api/v1/incidents"
PHOTOS = "/api/v1/incident-photos"
JPEG = b"\xff\xd8\xff" + b"\x11" * 64

pytestmark = pytest.mark.asyncio


def _signing_key() -> bytes:
    return derive_signing_key(SECRET)


@pytest_asyncio.fixture
async def iso_api(db_session, tmp_path):
    """The real app, with a session whose tenant marker is cleared when a request ends.

    That is what lets one test authenticate as tenant A and then as tenant B: without it the
    second `auth_header` would ask `bind_session_to_tenant` to rebind an already-marked session
    and raise, so the test would 500 rather than exercise anything.

    **One limit, recorded rather than discovered later** (section 10 tenancy panel): both
    tenants' requests share one physical `Session`, so they share its identity map — limit 4 of
    `app/core/db.py`. A leak arriving through `session.get()` or `.refresh()` rather than a
    `select()` would therefore not be caught here. Nothing in these three routes uses either
    today — every repository method goes through `select` — so the tests below are sound; a
    future route that did would need its own coverage rather than relying on this fixture.
    """
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import get_token_codec
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app

    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    app.dependency_overrides[get_db_session] = request_session_override(db_session)
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_incident_photo_storage_factory] = (
        lambda: ConfiguredFileStorageFactory(
            signing_key=_signing_key(),
            local_root=tmp_path / "media",
            url_prefix=INCIDENT_PHOTO_URL_PREFIX,
        )
    )
    app.dependency_overrides[get_url_signing_key] = _signing_key

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        client.asgi_app = app  # type: ignore[attr-defined]
        yield client


async def _neighbour(db_session) -> World:
    """A second tenant, with its own property and its own four people.

    Built directly on the session rather than through the API because there is no route that
    creates a tenant — the same reason `test_an_incident_of_another_tenant_is_a_404` does it
    this way.
    """
    tenant = TenantModel(name="TenantB", billing_email=f"b-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id, name="Theirs", internal_code=f"THEIRS{uuid.uuid4().hex[:6]}"
    )
    db_session.add(prop)
    await db_session.flush()
    db_session.add(TenantConfigModel(tenant_id=tenant.id, storage_type=StorageType.LOCAL))
    await db_session.flush()
    return World(
        tenant,
        prop,
        await _user(db_session, tenant, "TENANT_OWNER"),
        await _user(db_session, tenant, "PROPERTY_MANAGER"),
        await _user(db_session, tenant, "TECHNICIAN"),
        await _user(db_session, tenant, "TECHNICIAN"),
    )


async def _local(db_session, tenant_id) -> None:
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if config is None:
        db_session.add(TenantConfigModel(tenant_id=tenant_id, storage_type=StorageType.LOCAL))
    else:
        config.storage_type = StorageType.LOCAL
    await db_session.flush()


async def _their_incident(db_session, neighbour) -> IncidentModel:
    incident = await make_incident(
        db_session, neighbour, status=IncidentStatus.IN_PROGRESS
    )
    incident.assigned_technician_id = neighbour.technician.id
    await db_session.flush()
    return incident


async def _upload_as(iso_api, actor, incident):
    return await iso_api.post(
        f"{INCIDENTS}/{incident.id}/photos",
        data={"stage": "BEFORE"},
        files={"file": ("x.jpg", JPEG, "image/jpeg")},
        headers=auth_header(iso_api, actor),
    )


def _parts(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.path.rsplit("/", 1)[-1], query["exp"][0], query["sig"][0]


# --- route 1 of 3: the upload ---------------------------------------------------------


async def test_a_tenant_cannot_upload_to_another_tenants_incident(
    iso_api, world, db_session
):
    """R6.3, route 1 — end-to-end. A manager of A posting to B's incident gets the `404`.

    Net-only, as this file's docstring explains: the session is bound to A when it asserts, so
    the listener alone would produce this. Paired with the spy test below, which can fail.
    """
    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)

    response = await _upload_as(iso_api, world.manager, theirs)

    assert response.status_code == 404
    # And nothing was written for either tenant.
    assert (
        await db_session.scalar(
            select(IncidentPhotoModel.id).where(
                IncidentPhotoModel.incident_id == theirs.id
            )
        )
        is None
    )


async def test_the_upload_resolves_the_incident_with_the_callers_own_tenant(
    iso_api, world, db_session, monkeypatch
):
    """R6.3, route 1 — **mechanism**, and this one can fail.

    Spies on the repository to assert the `tenant_id` it was handed is the caller's, taken from
    the verified token, and never a value derived from the path. A route that passed the
    incident's own tenant — or accepted one from the request — would still answer `404` here
    thanks to the listener, so the status code cannot tell the two apart. The argument this spy
    records is what can.

    **What this spy does and does not prove, because the section 10 tenancy panel got this
    wrong and the correction is worth keeping.** It proves the *argument*: the `tenant_id` that
    reaches the repository is the caller's. It does **not** prove the repository enforces it — a
    `get` that dropped its `WHERE` would still receive the right argument and this test would
    stay green. That layer is closed one file over, on an **unmarked** session, by
    `tests/maintenance/test_repositories.py::test_no_new_read_port_crosses_a_tenant_boundary`,
    which asserts `IncidentRepository.get(tenant_a, incident_of_b) is None`. Verified by
    mutation: dropping that filter leaves all eight tests here green and turns that one red.
    """
    from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository

    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)
    seen: list[uuid.UUID] = []

    original = SqlAlchemyIncidentRepository.get

    async def _spy(self, tenant_id, incident_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, incident_id)

    monkeypatch.setattr(SqlAlchemyIncidentRepository, "get", _spy)

    await _upload_as(iso_api, world.manager, theirs)

    assert seen, "the repository was never asked, so this test proves nothing"
    assert set(seen) == {world.tenant.id}
    assert neighbour.tenant.id not in seen


# --- route 2 of 3: the listing --------------------------------------------------------


async def test_a_tenant_cannot_list_another_tenants_incident_photos(
    iso_api, world, db_session
):
    """R6.3, route 2 — end-to-end, and it checks the photo really exists first.

    Without that first check the `404` would be indistinguishable from "there are no photos",
    and the test would pass against an empty table — which is the vacuous pass this file's
    whole purpose is to avoid.
    """
    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)
    await _local(db_session, neighbour.tenant.id)

    # Their own technician uploads successfully — possible only because the fixture clears the
    # tenant marker between requests.
    created = await _upload_as(iso_api, neighbour.technician, theirs)
    assert created.status_code == 201, created.text

    theirs_listing = await iso_api.get(
        f"{INCIDENTS}/{theirs.id}/photos",
        headers=auth_header(iso_api, neighbour.manager),
    )
    ours_attempt = await iso_api.get(
        f"{INCIDENTS}/{theirs.id}/photos", headers=auth_header(iso_api, world.manager)
    )

    # The row is really there and really visible to its owner …
    assert theirs_listing.status_code == 200
    assert len(theirs_listing.json()["items"]) == 1
    # … and invisible to the neighbour.
    assert ours_attempt.status_code == 404


async def test_the_listing_resolves_the_incident_with_the_callers_own_tenant(
    iso_api, world, db_session, monkeypatch
):
    """R6.3, route 2 — mechanism, and this one can fail. Same spy, same reason as route 1.

    Same limit too: it proves the argument, not the repository's enforcement. That layer is
    `tests/maintenance/test_repositories.py::test_no_new_read_port_crosses_a_tenant_boundary`.
    """
    from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository

    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)
    seen: list[uuid.UUID] = []

    original = SqlAlchemyIncidentRepository.get

    async def _spy(self, tenant_id, incident_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, incident_id)

    monkeypatch.setattr(SqlAlchemyIncidentRepository, "get", _spy)

    await iso_api.get(
        f"{INCIDENTS}/{theirs.id}/photos", headers=auth_header(iso_api, world.manager)
    )

    assert seen, "the repository was never asked, so this test proves nothing"
    assert set(seen) == {world.tenant.id}


async def test_the_photo_repository_is_asked_with_the_callers_tenant(
    iso_api, world, db_session, monkeypatch
):
    """R6.3, route 2 — the **second** scoped read of that request, which the spy above misses.

    `_load_incident_in_scope` is not the only tenant-scoped call the listing makes:
    `IncidentPhotoRepository.list_for_incident` takes its own `tenant_id`. A route that scoped
    the incident correctly and then read the photos with the wrong tenant would pass every test
    above, because the incident lookup is what produces the `404`.
    """
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    await _local(db_session, world.tenant.id)
    mine = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    mine.assigned_technician_id = world.technician.id
    await db_session.flush()
    seen: list[uuid.UUID] = []

    original = SqlAlchemyIncidentPhotoRepository.list_for_incident

    async def _spy(self, tenant_id, incident_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, incident_id)

    monkeypatch.setattr(SqlAlchemyIncidentPhotoRepository, "list_for_incident", _spy)

    response = await iso_api.get(
        f"{INCIDENTS}/{mine.id}/photos", headers=auth_header(iso_api, world.manager)
    )

    assert response.status_code == 200
    assert seen == [world.tenant.id]


# --- route 3 of 3: the anonymous serving route ----------------------------------------
#
# This route has no caller tenant at all — that is the point of it — so "isolation" here is a
# different claim: the signature is the credential, and it covers the whole storage key, which
# begins with `tenants/{tenant_id}/`. So what must hold is that a signature minted for one
# tenant's object cannot serve another's, and that the unscoped lookup does not become a way to
# read a neighbour's bytes.


async def test_a_signature_for_one_tenants_photo_cannot_serve_anothers(
    iso_api, world, db_session
):
    """R6.3, route 3 — and this one **can** fail, because no listener protects it.

    The route is anonymous: there is no session tenant, so nothing filters. The only thing
    standing between a caller and a neighbour's bytes is that the signature covers the whole
    storage key. Here a perfectly valid signature over tenant A's key is presented against
    tenant B's photo id — the pivot the resolve-then-verify ordering forbids — and across
    tenants, which is what makes this R6.3 evidence rather than the same-tenant pivot test in
    `test_serve_photo_api.py`.
    """
    await _local(db_session, world.tenant.id)
    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)
    mine = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    mine.assigned_technician_id = world.technician.id
    await db_session.flush()

    ours = await _upload_as(iso_api, world.technician, mine)
    assert ours.status_code == 201, ours.text
    theirs_created = await _upload_as(iso_api, neighbour.technician, theirs)
    assert theirs_created.status_code == 201, theirs_created.text

    our_row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(ours.json()["id"])
            )
        )
    ).scalar_one()
    their_photo_id, exp, _ = _parts(theirs_created.json()["url"])

    # A signature that is cryptographically perfect — right secret, right scheme, live expiry —
    # over OUR key, presented against THEIR photo id.
    forged = sign_storage_key(
        signing_key=_signing_key(), key=our_row.storage_key, expiry=int(exp)
    )
    response = await iso_api.get(f"{PHOTOS}/{their_photo_id}?exp={exp}&sig={forged}")

    assert response.status_code == 403
    # And their own URL still works, so the refusal above is not the route simply being broken.
    honest = await iso_api.get(theirs_created.json()["url"])
    assert honest.status_code == 200
    assert honest.content == JPEG


async def test_each_tenants_signed_url_serves_only_its_own_bytes(
    iso_api, world, db_session
):
    """R6.3, route 3 — the positive half, with distinguishable bytes.

    Two tenants, two photos with **different** content, each fetched with its own minted URL.
    A route that resolved the id without honouring the key — or that cached one tenant's object
    — would hand back the wrong bytes, which a status-code assertion would not notice.
    """
    await _local(db_session, world.tenant.id)
    neighbour = await _neighbour(db_session)
    theirs_incident = await _their_incident(db_session, neighbour)
    mine = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    mine.assigned_technician_id = world.technician.id
    await db_session.flush()

    ours_bytes = b"\xff\xd8\xff" + b"A" * 32
    theirs_bytes = b"\xff\xd8\xff" + b"B" * 32

    ours = await iso_api.post(
        f"{INCIDENTS}/{mine.id}/photos",
        data={"stage": "BEFORE"},
        files={"file": ("a.jpg", ours_bytes, "image/jpeg")},
        headers=auth_header(iso_api, world.technician),
    )
    theirs = await iso_api.post(
        f"{INCIDENTS}/{theirs_incident.id}/photos",
        data={"stage": "BEFORE"},
        files={"file": ("b.jpg", theirs_bytes, "image/jpeg")},
        headers=auth_header(iso_api, neighbour.technician),
    )
    assert (ours.status_code, theirs.status_code) == (201, 201)

    served_ours = await iso_api.get(ours.json()["url"])
    served_theirs = await iso_api.get(theirs.json()["url"])

    assert served_ours.content == ours_bytes
    assert served_theirs.content == theirs_bytes
    assert served_ours.content != served_theirs.content


async def test_the_unscoped_lookup_does_not_leak_the_neighbours_key(
    iso_api, world, db_session
):
    """R6.4 at the route: the tenant-less read exists, and it still publishes no path.

    The lookup deliberately has no tenant filter — it cannot have one — so this asserts the
    other half of why that is safe: what comes back is bytes and a derived `Content-Type`, and
    the neighbour's storage key appears in no body and no header, refused or served.
    """
    neighbour = await _neighbour(db_session)
    theirs = await _their_incident(db_session, neighbour)
    created = await _upload_as(iso_api, neighbour.technician, theirs)
    assert created.status_code == 201, created.text

    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(created.json()["id"])
            )
        )
    ).scalar_one()
    photo_id, exp, sig = _parts(created.json()["url"])

    served = await iso_api.get(created.json()["url"])
    refused = await iso_api.get(f"{PHOTOS}/{photo_id}?exp={exp}&sig={'0' * len(sig)}")

    for response in (served, refused):
        assert row.storage_key.encode() not in response.content
        assert b"tenants/" not in response.content
        for value in response.headers.values():
            assert row.storage_key not in value
