"""Fixtures for the cleaning tests: two tenants, five roles, properties and templates.

Reuses `tests/auth/conftest.py` rather than re-seeding — it already creates a user per role
in each of two tenants, which is exactly what the authorisation matrix (R7.4) and the
isolation tests (R7.3, R7.5) need. The neighbour tenant is never optional here: an isolation
test with nothing to fail to reach proves nothing.

Same arrangement `tests/reservations/conftest.py` uses, and for the same reason.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.cleaning.api.dependencies import get_file_storage_factory, get_url_signing_key
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.core.db import get_db_session
from app.integrations.domain.storage import derive_signing_key
from app.integrations.infrastructure.storage import ConfiguredFileStorageFactory
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
from tests.conftest import request_session_override
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "c" * 64

STANDARD_ITEMS = [
    {"item_id": "kitchen", "label": "Cocina", "required": True},
    {"item_id": "bathroom", "label": "Baño", "required": True},
    {"item_id": "balcony", "label": "Terraza", "required": False},
]
STANDARD_PHOTOS = [{"photo_type": "kitchen", "label": "Cocina", "required": True}]


def signing_key() -> bytes:
    """The URL signing key the `api` fixture signs AND verifies with.

    One function, called from both overrides below, so a test can forge or inspect a signature
    (`test_serve_photo_api.py`) with the certainty that it is the key the app is using.
    """
    return derive_signing_key(SECRET)


@pytest_asyncio.fixture
async def api(db_session, tmp_path):
    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    # One shared session whose tenant marker is cleared when each request ends — not a session
    # per request. The anonymous photo route runs `locate_without_tenant_scoping`, which refuses
    # a session an earlier authenticated request has left bound.
    app.dependency_overrides[get_db_session] = request_session_override(db_session)
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )
    # `LOCAL` storage rooted in the test's own directory rather than the real `/app/media`
    # volume: a suite that wrote there would leave a growing pile of orphaned objects in a
    # developer's environment, and two tests could see each other's files. `media_root` below
    # is the same path, so a test can assert what actually landed on disk.
    app.dependency_overrides[get_file_storage_factory] = lambda: ConfiguredFileStorageFactory(
        signing_key=signing_key(), local_root=tmp_path / "media"
    )
    # And the SAME key for the anonymous serving route, which verifies what the factory above
    # signed. Both halves must be overridden together: the factory override pins the signer to
    # `SECRET` while `get_url_signing_key` would still derive from `settings.jwt_secret_key`,
    # so leaving this one out would make every signed URL in the suite verify against a
    # different key and fail as a `403` that looks like a broken signing scheme.
    app.dependency_overrides[get_url_signing_key] = signing_key

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        # The app itself, so a test can add an override of its own — the photo tests replace
        # the byte ceiling and the storage adapter to reach paths the fixture cannot pose.
        # Named `asgi_app` rather than `app`: httpx has carried a constructor parameter of
        # that name across versions, and shadowing it would be a bug that only shows up on an
        # upgrade.
        client.asgi_app = app  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def media_root(tmp_path):
    """Where the `api` fixture's `LOCAL` adapter writes. Same `tmp_path`, same test."""
    return tmp_path / "media"


def auth_header(client, user: UserModel) -> dict[str, str]:
    """A real access token for `user`, issued by the same codec the app verifies with."""
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


async def insert_property(session, tenant, *, code="REDES11") -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=f"Property {code}",
        internal_code=code,
        pms_external_id=f"PMS-{code}-{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    session.add(prop)
    await session.flush()
    return prop


async def insert_template(
    session,
    tenant,
    *,
    property_id=None,
    active=True,
    name="Estándar",
    items=None,
    required_photos=None,
) -> CleaningChecklistTemplateModel:
    """`STANDARD_ITEMS` and `STANDARD_PHOTOS` unless a test needs another shape.

    `required_photos` is an override and **not** an escape hatch for PRD §11's third clause
    (R4): `STANDARD_PHOTOS` demands one `required: true` type, so every test that closes a task
    built on the default template has to upload it. The parameter exists because R4.5 — "the
    rule is *the required ones*, not *some*" — cannot be tested at all without a template that
    declares an optional type and one that declares no photo, and a suite where every template
    is identical could not tell `required_photo_types()` from `photo_types()`.
    """
    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id,
        property_id=property_id,
        name=name,
        items=items if items is not None else STANDARD_ITEMS,
        required_photos=STANDARD_PHOTOS if required_photos is None else required_photos,
        active=active,
    )
    session.add(template)
    await session.flush()
    return template


async def insert_reservation(session, tenant, prop, *, days_ago=1) -> ReservationModel:
    check_out = datetime.now(UTC).date() - timedelta(days=days_ago)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        check_in_date=check_out - timedelta(days=2),
        check_out_date=check_out,
        nights=2,
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def insert_task(
    session,
    tenant,
    prop,
    template,
    *,
    reservation=None,
    status=None,
    cleaner=None,
    scheduled_start=None,
) -> CleaningTaskModel:
    from app.cleaning.domain.enums import CleaningTaskStatus

    task = CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        reservation_id=reservation.id if reservation is not None else None,
        status=status or CleaningTaskStatus.CREATED,
        assigned_cleaner_id=cleaner.id if cleaner is not None else None,
        scheduled_start=scheduled_start,
    )
    session.add(task)
    await session.flush()
    return task


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a) -> PropertyModel:
    return await insert_property(db_session, tenant_a, code="REDES11")


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    return await insert_property(db_session, tenant_b, code="PAJARITOS8")


@pytest_asyncio.fixture
async def template_a(db_session, tenant_a) -> CleaningChecklistTemplateModel:
    return await insert_template(db_session, tenant_a)


@pytest_asyncio.fixture
async def template_b(db_session, tenant_b) -> CleaningChecklistTemplateModel:
    return await insert_template(db_session, tenant_b)


@pytest.fixture
def template_payload(property_a):
    def _payload(**overrides):
        payload = {
            "name": "Estándar",
            "items": STANDARD_ITEMS,
            "required_photos": STANDARD_PHOTOS,
        }
        payload.update(overrides)
        return payload

    return _payload
