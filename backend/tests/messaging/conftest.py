"""Seeding shared by the messaging integration tests.

`db_session` from the root `conftest.py` is a **plain `AsyncSession` with no tenant marking**,
and that matters more here than anywhere else in the suite: on a marked session the global
`with_loader_criteria` of `app/core/db.py` filters ORM reads by tenant, so an isolation test
for `conversations` could not fail even against a repository that had forgotten its `WHERE`.
The tests in `test_tenant_isolation.py` say so again where they use it.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)
from app.messaging.infrastructure.models import ConversationModel, MessageModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


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


async def seed_reservation(
    db_session,
    tenant,
    prop,
    *,
    check_in: date | None = None,
    status: str = "CONFIRMED",
):
    """A stay for the portal thread to hang off (`guest-portal-messaging` section 3).

    `conversations.reservation_id` is a real foreign key, so the portal repository methods —
    which key on `(tenant_id, reservation_id)` — cannot be tested without one.
    """
    start = check_in or NOW.date()
    model = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status=status,
        check_in_date=start,
        check_out_date=start + timedelta(days=2),
        nights=2,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def seed_conversation(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    channel: ConversationChannel = ConversationChannel.WHATSAPP,
    status: ConversationStatus = ConversationStatus.OPEN,
    escalation_status: ConversationEscalationStatus = ConversationEscalationStatus.NONE,
    last_message_at: datetime | None = None,
    language: str = "es",
    ai_enabled: bool = True,
) -> ConversationModel:
    model = ConversationModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=channel,
        status=status,
        escalation_status=escalation_status,
        language=language,
        last_message_at=last_message_at,
        ai_enabled=ai_enabled,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(model)
    await db_session.flush()
    return model


SECRET = "m" * 64


class World:
    """One tenant, one property and one user per role that matters to the inbox."""

    def __init__(self, tenant, prop, owner, manager, cleaner, technician) -> None:
        self.tenant = tenant
        self.property = prop
        self.owner = owner
        self.manager = manager
        self.cleaner = cleaner
        self.technician = technician


@pytest_asyncio.fixture
async def world(db_session) -> World:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    return World(
        tenant,
        prop,
        await seed_user(db_session, tenant, "owner@example.com", role=UserRole.TENANT_OWNER),
        await seed_user(db_session, tenant, "manager@example.com", role=UserRole.PROPERTY_MANAGER),
        await seed_user(db_session, tenant, "cleaner@example.com", role=UserRole.CLEANER),
        await seed_user(db_session, tenant, "tech@example.com", role=UserRole.TECHNICIAN),
    )


@pytest_asyncio.fixture
async def api(db_session):
    """The real app over the test session, so the endpoint tests exercise `require(...)`, the
    error handlers and the response schemas rather than a use case behind them."""
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
    """A real access token for `user`, issued by the codec the app verifies with.

    Issued at the **wall clock** and not at `NOW`: the fixtures' instant is a fixed point in
    this change's own timeline, and a token stamped there would be expired or issued in the
    future depending on when the suite runs. The routes call `now_utc()` themselves.
    """
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_message(
    db_session,
    conversation: ConversationModel,
    *,
    content: str = "El wifi no funciona",
    sender_type: MessageSenderType = MessageSenderType.GUEST,
    intent: str | None = None,
    created_at: datetime = NOW,
) -> MessageModel:
    model = MessageModel(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        sender_type=sender_type,
        content=content,
        intent=intent,
        created_at=created_at,
    )
    db_session.add(model)
    await db_session.flush()
    return model
