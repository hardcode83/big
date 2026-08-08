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
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.core.db import get_db_session
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
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


@pytest_asyncio.fixture
async def api(db_session):
    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


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
    session, tenant, *, property_id=None, active=True, name="Estándar", items=None
) -> CleaningChecklistTemplateModel:
    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id,
        property_id=property_id,
        name=name,
        items=items if items is not None else STANDARD_ITEMS,
        required_photos=STANDARD_PHOTOS,
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
    session, tenant, prop, template, *, reservation=None, status=None, cleaner=None
) -> CleaningTaskModel:
    from app.cleaning.domain.enums import CleaningTaskStatus

    task = CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        reservation_id=reservation.id if reservation is not None else None,
        status=status or CleaningTaskStatus.CREATED,
        assigned_cleaner_id=cleaner.id if cleaner is not None else None,
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
