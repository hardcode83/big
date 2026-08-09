"""Fixtures for the notifications API tests.

Same arrangement as `tests/cleaning/conftest.py`: reuse `tests/auth/conftest.py`, which
already seeds a user per role in two tenants. The neighbour tenant is not optional — an
isolation test with nothing to fail to reach proves nothing.
"""

import uuid
from datetime import datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.main import create_app
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.infrastructure.models import NotificationLogModel
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "d" * 64


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
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


async def insert_notification(
    session,
    tenant,
    *,
    recipient: UserModel | None = None,
    subject: str = "Cleaning assigned",
    body: str = "A cleaning task has been assigned to you.",
    status: NotificationStatus = NotificationStatus.SENT,
    last_error: str | None = None,
    notification_type: str = "CLEANING_TASK_ASSIGNED",
    created_at: datetime | None = None,
) -> NotificationLogModel:
    """`created_at` is explicit whenever a test asserts an order.

    Postgres' `now()` is **transaction** time, so two rows inserted by the same test share it
    to the microsecond and the `id` tie-break decides — a random UUID. In production the rows
    come from different transactions and the timestamps differ; in a test they never do.
    """
    model = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_user_id=recipient.id if recipient is not None else None,
        recipient_contact=recipient.email if recipient is not None else "x@example.com",
        channel=NotificationChannel.IN_APP,
        notification_type=notification_type,
        subject=subject,
        body=body,
        status=status,
        last_error=last_error,
    )
    if created_at is not None:
        model.created_at = created_at
    session.add(model)
    await session.flush()
    return model
