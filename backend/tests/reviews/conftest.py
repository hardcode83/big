"""Seeding shared by the reviews integration tests.

`db_session` from the root `conftest.py` is a **plain `AsyncSession` with no tenant
marking**, and that matters more here than anywhere else in the suite: on a marked
session the global `with_loader_criteria` of `app/core/db.py` filters ORM reads by
tenant, so an isolation test for `reviews`/`review_response_drafts` could not fail
even against a repository that had forgotten its `WHERE`. The tests in
`test_tenant_isolation.py` say so again where they use it.
"""

import uuid
from datetime import UTC, datetime

import pytest_asyncio

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.properties.infrastructure.models import PropertyModel
from app.reviews.domain.enums import ReviewChannel, ReviewStatus
from app.reviews.infrastructure.models import ReviewModel, ReviewResponseDraftModel
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


async def seed_tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def seed_property(db_session, tenant: TenantModel, code: str) -> PropertyModel:
    model = PropertyModel(tenant_id=tenant.id, name=code, internal_code=code)
    db_session.add(model)
    await db_session.flush()
    return model


async def seed_user(
    db_session,
    tenant: TenantModel,
    email: str,
    *,
    role: UserRole = UserRole.PROPERTY_MANAGER,
    status: UserStatus = UserStatus.ACTIVE,
) -> UserModel:
    model = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        password_hash="x" * 60,
        name=email.split("@")[0],
        role=role,
        status=status,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def seed_review(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    channel: ReviewChannel = ReviewChannel.MANUAL,
    status: ReviewStatus = ReviewStatus.NEW,
    rating: float | None = None,
    content: str | None = None,
    language: str | None = None,
    published_at: datetime | None = None,
) -> ReviewModel:
    model = ReviewModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=channel,
        status=status,
        reviewer_name="Anonymous",
        rating=None if rating is None else _decimal(rating),
        content=content,
        language=language,
        published_at=published_at,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def seed_draft(
    db_session,
    review: ReviewModel,
    *,
    language: str = "es",
    draft_content: str | None = None,
) -> ReviewResponseDraftModel:
    """A draft of a catalogue member, so the `templates.assert_in_catalogue` guard accepts it."""
    from app.reviews.domain.templates import REVIEW_DRAFT_VOCABULARY

    model = ReviewResponseDraftModel(
        id=uuid.uuid4(),
        review_id=review.id,
        draft_content=draft_content or next(iter(REVIEW_DRAFT_VOCABULARY)),
        language=language,
        ai_generated=True,
        edits_count=0,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(model)
    await db_session.flush()
    return model


def _decimal(value: float):
    from decimal import Decimal

    return Decimal(str(value))


class World:
    """One tenant, one property, two users per role that matters."""

    def __init__(self, tenant, prop, owner, manager) -> None:
        self.tenant = tenant
        self.property = prop
        self.owner = owner
        self.manager = manager


@pytest_asyncio.fixture
async def world(db_session) -> World:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    return World(
        tenant,
        prop,
        await seed_user(db_session, tenant, "owner@example.com", role=UserRole.TENANT_OWNER),
        await seed_user(db_session, tenant, "manager@example.com", role=UserRole.PROPERTY_MANAGER),
    )


SECRET = "r" * 64


@pytest_asyncio.fixture
async def api(db_session):
    """The real app over the test session."""
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import get_token_codec
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app

    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


def auth_header(client, user) -> dict[str, str]:
    """A real access token for `user`, issued by the codec the app verifies with."""
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}
