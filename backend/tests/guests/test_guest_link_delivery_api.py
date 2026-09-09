"""The read-status and send routes over HTTP (`guest-link-delivery` R1-R3, D1, D4, D5).

Sibling of `test_portal_token_api.py`, same fixtures, same reasoning about `404` for a
foreign-tenant stay. What is new here: a route that never mints anything
(`GET .../guest-access-token`) and one that mints **and** emails in one request
(`POST .../guest-access-token/send`), whose response never carries the cleartext token.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.guests.api.dependencies import get_send_guest_access_token_use_case
from app.guests.application.portal import SendGuestAccessTokenUseCase
from app.guests.domain.portal_token import hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.main import create_app
from app.notifications.domain.results import NotificationErrorCode, NotificationResult
from app.notifications.infrastructure.models import NotificationLogModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "f" * 64


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
        client.fastapi_app = app  # type: ignore[attr-defined]
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


async def _stay(db_session, tenant, *, guest: GuestModel | None = None) -> ReservationModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="REDES11",
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.DIRECT,
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
        nights=3,
        guest_id=guest.id if guest is not None else None,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


async def _guest(db_session, tenant, *, email: str | None = "guest@example.com") -> GuestModel:
    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace", email=email)
    db_session.add(guest)
    await db_session.flush()
    return guest


def _status_path(reservation) -> str:
    return f"/api/v1/reservations/{reservation.id}/guest-access-token"


def _send_path(reservation) -> str:
    return f"/api/v1/reservations/{reservation.id}/guest-access-token/send"


# --- GET status (R1.1, R2) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_answers_no_live_token_when_none_was_ever_minted(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    reservation = await _stay(db_session, tenant_a)

    response = await api.get(
        _status_path(reservation),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    assert response.json() == {"is_live": False, "issued_at": None}


@pytest.mark.asyncio
async def test_status_answers_live_and_since_when_after_a_mint(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    await api.post(_status_path(reservation), headers=header)

    response = await api.get(_status_path(reservation), headers=header)

    assert response.status_code == 200
    body = response.json()
    assert body["is_live"] is True
    assert body["issued_at"] is not None
    # Never the credential — the whole point of this surface (R2.2).
    assert "token" not in body


@pytest.mark.asyncio
async def test_status_never_carries_the_token_or_its_hash(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    token = (await api.post(_status_path(reservation), headers=header)).json()["token"]

    response = await api.get(_status_path(reservation), headers=header)

    assert token not in response.text
    assert hash_guest_token(token) not in response.text


@pytest.mark.asyncio
async def test_status_is_the_same_404_for_a_foreign_tenants_reservation(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    foreign = await _stay(db_session, tenant_b)

    response = await api.get(
        _status_path(foreign),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN])
async def test_status_is_refused_without_the_permission(
    api, db_session, tenant_a, users_by_role_a, role: UserRole
) -> None:
    reservation = await _stay(db_session, tenant_a)

    response = await api.get(
        _status_path(reservation), headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_status_requires_authentication_at_all(api, db_session, tenant_a) -> None:
    reservation = await _stay(db_session, tenant_a)

    assert (await api.get(_status_path(reservation))).status_code == 401


# --- POST send (R3) ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mints_and_delivers_and_never_echoes_the_token(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest=guest)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    response = await api.post(_send_path(reservation), headers=header)

    assert response.status_code == 200
    body = response.json()
    assert body == {"delivered": True}
    assert "token" not in body

    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id,
                GuestAccessTokenModel.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    assert stored is not None

    rows = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "GUEST_PORTAL_LINK_DELIVERED"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "SENT"
    assert rows[0].related_type == "reservation"
    assert rows[0].related_id == reservation.id
    # R3.4: constants only, never the link/token in the stored row.
    assert stored.token_hash not in (rows[0].subject or "")
    assert stored.token_hash not in (rows[0].body or "")

    audited = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "GUEST_ACCESS_TOKEN_SENT")
        )
    ).scalar_one()
    assert audited.entity_id == stored.id


@pytest.mark.asyncio
async def test_send_reports_not_delivered_when_the_adapter_fails_but_still_mints(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R3.5: an adapter failure does not roll the mint back, and is visible in the response."""
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest=guest)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    class _FailingEmailAdapter:
        async def send(self, **kwargs):
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)

    async def _use_case_with_failing_adapter(session=None):
        from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
        from app.core.config import settings
        from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
        from app.guests.application.portal import IssueGuestAccessTokenUseCase
        from app.guests.infrastructure.portal_repositories import (
            SqlAlchemyGuestAccessTokenRepository,
            SqlAlchemyPortalStayLocator,
        )
        from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
        from app.notifications.domain.enums import NotificationChannel
        from app.notifications.infrastructure.repositories import (
            SqlAlchemyNotificationLogRepository,
        )

        tokens = SqlAlchemyGuestAccessTokenRepository(db_session)
        stays = SqlAlchemyPortalStayLocator(db_session)
        audit = SqlAlchemyAuditLogRepository(db_session)
        return SendGuestAccessTokenUseCase(
            issue=IssueGuestAccessTokenUseCase(
                tokens=tokens, stays=stays, audit=audit, uow=CallerOwnedUnitOfWork()
            ),
            tokens=tokens,
            stays=stays,
            guests=SqlAlchemyGuestRepository(db_session),
            notifications=SqlAlchemyNotificationLogRepository(db_session),
            adapters={NotificationChannel.EMAIL: _FailingEmailAdapter()},
            audit=audit,
            uow=SqlAlchemyUnitOfWork(db_session),
            frontend_base_url=settings.frontend_base_url,
        )

    api.fastapi_app.dependency_overrides[  # type: ignore[attr-defined]
        get_send_guest_access_token_use_case
    ] = _use_case_with_failing_adapter

    response = await api.post(_send_path(reservation), headers=header)

    assert response.status_code == 200
    assert response.json() == {"delivered": False}

    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id,
                GuestAccessTokenModel.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    assert stored is not None

    row = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "GUEST_PORTAL_LINK_DELIVERED"
            )
        )
    ).scalar_one()
    assert row.status == "FAILED"
    assert row.last_error == NotificationErrorCode.ADAPTER_ERROR.value


@pytest.mark.asyncio
async def test_send_is_refused_with_422_and_mints_nothing_without_a_linked_guest(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    reservation = await _stay(db_session, tenant_a, guest=None)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    response = await api.post(_send_path(reservation), headers=header)

    assert response.status_code == 422
    assert (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).first() is None


@pytest.mark.asyncio
async def test_send_is_refused_with_422_and_mints_nothing_for_a_blank_email(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    guest = await _guest(db_session, tenant_a, email="   ")
    reservation = await _stay(db_session, tenant_a, guest=guest)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    response = await api.post(_send_path(reservation), headers=header)

    assert response.status_code == 422
    assert (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).first() is None


@pytest.mark.asyncio
async def test_send_is_the_same_404_for_a_foreign_tenants_reservation(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    foreign_guest = await _guest(db_session, tenant_b)
    foreign = await _stay(db_session, tenant_b, guest=foreign_guest)

    response = await api.post(
        _send_path(foreign),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN])
async def test_send_is_refused_without_the_permission(
    api, db_session, tenant_a, users_by_role_a, role: UserRole
) -> None:
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest=guest)

    response = await api.post(
        _send_path(reservation), headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_send_requires_authentication_at_all(api, db_session, tenant_a) -> None:
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest=guest)

    assert (await api.post(_send_path(reservation))).status_code == 401
