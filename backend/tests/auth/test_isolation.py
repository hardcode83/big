"""Tenant isolation, per role (R4.1, R4.2, R4.4, R4.5, design D15).

SCOPE, stated plainly so nobody reads a false green here (design D15): R4.4 asks for
proof that a user of tenant A cannot reach tenant B's data, for each of the five
roles. This change has no business endpoints — only the auth ones — so there is no
business resource to cross. What is proven below is:

  (a) the repository layer, parametrized over all five roles, with two tenants;
  (b) `GET /api/v1/auth/me` with a validly signed token naming another tenant;
  (c) a token naming a tenant that does not exist or is not ACTIVE (R4.5);
  (d) a `tenant_id` supplied in the body, query string or a header being ignored.

That is the whole of R4.4 that this change's surface can express. The per-endpoint,
per-role matrix and R4.3's 404-vs-403 are NOT here, and not because they were
forgotten: they need endpoints that take a resource identifier, and login, refresh,
logout and me are all self-referential (`NotFoundError` has no production call site
yet, for the same reason). Both moved to `user-management` in the PR #25 review, where
they are blocking acceptance criteria — it is the first change with
`/api/v1/users/{id}` and `tenants/{id}`, and it comes before `reservations`.

`steering/security.md` rule 1 — "tests automáticos ... obligatorios en cada módulo
nuevo" — is satisfied for the surface this change actually introduces, not for one it
does not.
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.auth.api.dependencies import get_login_throttle, get_password_hasher, get_token_codec
from app.auth.domain.entities import UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole
from app.auth.infrastructure.models import UserSessionModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import TENANT_ID_SESSION_KEY, get_db_session
from app.core.i18n import Locale
from app.main import create_app
from app.tenants.domain.enums import TenantStatus
from tests.auth.conftest import TEST_BCRYPT_ROUNDS, insert_tenant, insert_user, utc_now
from tests.auth.doubles import UnlimitedLoginThrottle

SECRET = "s" * 64


@pytest.fixture
def codec() -> JwtTokenCodec:
    return JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)


@pytest_asyncio.fixture
async def api(db_session, codec):
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_login_throttle] = lambda: UnlimitedLoginThrottle()
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- (a) repository level, every role -----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
async def test_a_user_of_another_tenant_is_unreachable_for_every_role(
    db_session, tenant_a, tenant_b, role: UserRole
) -> None:
    mine = await insert_user(db_session, tenant=tenant_a, role=role)
    theirs = await insert_user(db_session, tenant=tenant_b, role=role)
    repo = SqlAlchemyUserRepository(db_session)

    assert (await repo.get_active_by_id(tenant_a.id, mine.id)) is not None
    assert (await repo.get_active_by_id(tenant_a.id, theirs.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
async def test_no_role_can_write_over_another_tenants_user(
    db_session, tenant_a, tenant_b, role: UserRole
) -> None:
    theirs = await insert_user(db_session, tenant=tenant_b, role=role)
    repo = SqlAlchemyUserRepository(db_session)
    entity = await repo.get_active_by_id(tenant_b.id, theirs.id)
    assert entity is not None

    with pytest.raises(ValueError):
        await repo.touch_last_login(tenant_a.id, theirs.id, utc_now())

    untouched = await repo.get_active_by_id(tenant_b.id, theirs.id)
    assert untouched is not None and untouched.last_login_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
async def test_no_role_can_touch_another_tenants_session(
    db_session, tenant_a, tenant_b, role: UserRole
) -> None:
    theirs = await insert_user(db_session, tenant=tenant_b, role=role)
    session = UserSession(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        user_id=theirs.id,
        family_id=uuid.uuid4(),
        expires_at=utc_now() + timedelta(days=7),
    )
    repo = SqlAlchemySessionRepository(db_session)
    await repo.add(tenant_b.id, session)
    await db_session.flush()

    assert await repo.get(tenant_a.id, session.id) is None
    assert await repo.consume(tenant_a.id, session.id, utc_now()) is False
    assert (
        await repo.revoke_family(
            tenant_a.id, session.family_id, SessionRevokedReason.LOGOUT, utc_now()
        )
        == 0
    )


@pytest.mark.asyncio
async def test_the_two_tenants_really_are_populated(
    db_session, users_by_role_a, users_by_role_b
) -> None:
    """Guards the matrix above from passing because a fixture created nothing."""
    assert len(users_by_role_a) == len(UserRole) == 5
    assert set(users_by_role_a) == set(users_by_role_b) == set(UserRole)
    assert not {u.id for u in users_by_role_a.values()} & {
        u.id for u in users_by_role_b.values()
    }


# --- (b) and (c) over HTTP -----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
async def test_a_token_naming_another_tenant_is_refused_for_every_role(
    api, db_session, tenant_a, tenant_b, codec, role: UserRole
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, role=role)
    forged = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_b.id,
        role=role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_a_token_naming_a_tenant_that_does_not_exist_is_refused(
    api, db_session, tenant_a, codec
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    forged = codec.issue_access(
        user_id=user.id,
        tenant_id=uuid.uuid4(),
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TenantStatus.SUSPENDED, TenantStatus.CANCELLED])
async def test_a_token_of_a_non_active_tenant_is_refused(api, db_session, codec, status) -> None:
    # R4.5, checked through the joined query of design D7.
    tenant = await insert_tenant(db_session, status=status)
    user = await insert_user(db_session, tenant=tenant)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_tenant_suspended_mid_session_loses_access_at_once(
    api, db_session, tenant_a, codec
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 200

    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
    tenant_a.status = TenantStatus.SUSPENDED
    await db_session.flush()

    assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 401


# --- (d) input can never choose the tenant ------------------------------------


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_query_string_is_ignored(
    api, db_session, tenant_a, tenant_b, codec
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get(
        f"/api/v1/auth/me?tenant_id={tenant_b.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(tenant_a.id)


@pytest.mark.asyncio
async def test_a_tenant_id_header_is_ignored(api, db_session, tenant_a, tenant_b, codec) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(tenant_b.id),
            "X-Tenant-ID": str(tenant_b.id),
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(tenant_a.id)


@pytest.mark.asyncio
async def test_the_request_context_carries_the_tokens_tenant_not_the_bodys(
    api, db_session, tenant_a, tenant_b
) -> None:
    """Login refuses an injected tenant outright: the schema forbids extra fields."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    response = await api.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
            "tenant_id": str(tenant_b.id),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_an_authenticated_request_marks_its_session_before_querying(
    api, db_session, tenant_a, codec
) -> None:
    """The point the tenancy panel left open: the net must actually be armed.

    `bind_session_to_tenant` is what activates the global filter (design D16), and
    `get_authenticated_request` is the only place meant to call it. If an authenticated path
    ever skipped it, the filter would be silently off for that request.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    db_session.info.pop(TENANT_ID_SESSION_KEY, None)

    assert (
        await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200

    assert db_session.info.get(TENANT_ID_SESSION_KEY) == tenant_a.id


@pytest.mark.asyncio
async def test_the_request_context_takes_the_role_from_the_database(
    db_session, tenant_a, codec
) -> None:
    """Design D7 at the level that actually holds the guarantee.

    An earlier test asserted this through `GET /api/v1/auth/me`, which was vacuous:
    `GetCurrentUserUseCase` re-fetches the row itself, so the response reflects the
    database no matter what `RequestContext` carries. The only production consumer of
    `RequestContext.role` is `require()`'s permission check, and today every role holds
    the same permissions, so no HTTP path can expose the difference. Asserting on the
    context directly is the only way to pin it.
    """
    from app.auth.api.dependencies import get_authenticated_request
    from fastapi import Request
    from fastapi.security import HTTPAuthorizationCredentials

    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.CLEANER)
    # The token claims TENANT_OWNER; the database says CLEANER.
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=UserRole.TENANT_OWNER,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    # `request` arrived with `auth-account-recovery` R5.4: the dependency now also gates
    # accounts owing a password change, and needs the route to consult the exempt list.
    # A `GET /api/v1/auth/me` scope is the natural stand-in — the user under test does not
    # owe a change, so the gate is not what this test exercises.
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "headers": [],
        }
    )

    authenticated = await get_authenticated_request(
        request=request,
        session=db_session,
        codec=codec,
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
    )

    assert authenticated.context.role is UserRole.CLEANER, (
        "the effective role must come from the database, not from the token claim"
    )
    assert codec.decode_access(token).role is UserRole.TENANT_OWNER, (
        "the token really did claim a different role, so this test is not vacuous"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [("es", Locale.ES), ("en", Locale.EN), ("fr", Locale.ES), ("", Locale.ES)],
)
async def test_the_request_context_carries_the_users_language(
    db_session, tenant_a, codec, stored: str, expected: Locale
) -> None:
    """`dashboard-api` design D3: the language rides the context, at zero extra queries.

    `users.preferred_language` is `String(5)` with no check constraint, so a value we do
    not ship must degrade to `es` here rather than reach a renderer.
    """
    from app.auth.api.dependencies import get_authenticated_request
    from fastapi.security import HTTPAuthorizationCredentials

    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored)
    token = codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_a.id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    authenticated = await get_authenticated_request(
        session=db_session,
        codec=codec,
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
    )

    assert authenticated.context.preferred_language is expected


@pytest.mark.asyncio
async def test_the_anonymous_login_path_leaves_the_session_unmarked(
    api, db_session, tenant_a
) -> None:
    """The escape hatch of design D16 is needed and must stay scoped to login."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    db_session.info.pop(TENANT_ID_SESSION_KEY, None)

    response = await api.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    assert TENANT_ID_SESSION_KEY not in db_session.info


@pytest.mark.asyncio
async def test_the_session_rows_of_two_tenants_never_mix(
    db_session, tenant_a, tenant_b, api, codec
) -> None:
    for tenant in (tenant_a, tenant_b):
        await insert_user(
            db_session, tenant=tenant, email=f"owner-{tenant.name}@example.com"
        )
        await api.post(
            "/api/v1/auth/login",
            json={
                "email": f"owner-{tenant.name}@example.com",
                "password": "correct horse battery staple",
            },
        )

    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
    per_tenant = (
        await db_session.execute(
            select(UserSessionModel.tenant_id, func.count()).group_by(UserSessionModel.tenant_id)
        )
    ).all()

    assert {tenant_id for tenant_id, _ in per_tenant} == {tenant_a.id, tenant_b.id}
    assert all(count == 1 for _, count in per_tenant)


# --- password recovery (`auth-account-recovery` R2.3, R4.1, R6.3, task 8.3) ----------
#
# This module is the project's designated home for per-module isolation coverage (regla 1 of
# `steering/security.md`), which is why these live here and not only in
# `test_repositories.py`: two tenancy panels pointed out that an auditor reading THIS file
# module-by-module would otherwise conclude `password_reset_tokens` has none.
#
# The two halves are checked differently, and that is the second panel's refinement:
# **running the use case does not exercise the guard**, because its `tenant_id` always comes
# from the row it just resolved, so it never attempts a cross-tenant write. "Reachable" is
# tested by running it; "writable" only by calling `add()` directly with a cross-tagged
# entity.


def _recovery_use_case(db_session):
    from app.auth.application.recovery import RequestPasswordResetUseCase
    from app.auth.infrastructure.repositories import SqlAlchemyPasswordResetTokenRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.notifications.domain.enums import NotificationChannel
    from app.notifications.infrastructure.repositories import (
        SqlAlchemyNotificationLogRepository,
    )
    from tests.auth.doubles import CapturingEmailAdapter

    adapter = CapturingEmailAdapter()
    return RequestPasswordResetUseCase(
        users=SqlAlchemyUserRepository(db_session),
        tokens=SqlAlchemyPasswordResetTokenRepository(db_session),
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        adapters={NotificationChannel.EMAIL: adapter},
        throttle=UnlimitedLoginThrottle(),
        uow=SqlAlchemyUnitOfWork(db_session),
        token_minutes=30,
        max_live_tokens=3,
        grace_minutes=0,
        frontend_base_url="https://app.example.test",
    )


@pytest.mark.asyncio
async def test_a_recovery_request_writes_only_into_its_own_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    """R2.3 / R6.3 — the "reachable" half, with the global filter OFF.

    `forgot-password` is anonymous, so `bind_session_to_tenant` never runs for it: the only
    protection is the `tenant_id` derived from the row `find_by_email_globally` resolved.
    """
    from app.auth.infrastructure.models import PasswordResetTokenModel
    from app.notifications.infrastructure.models import NotificationLogModel

    user_a = await insert_user(db_session, tenant=tenant_a, email="a1@example.com")
    user_b = await insert_user(db_session, tenant=tenant_b, email="b1@example.com")
    use_case = _recovery_use_case(db_session)

    await use_case.execute(email="a1@example.com", client_ip="203.0.113.1", now=utc_now())
    await use_case.execute(email="b1@example.com", client_ip="203.0.113.2", now=utc_now())

    tokens = (await db_session.execute(select(PasswordResetTokenModel))).scalars().all()
    by_tenant = {t.tenant_id: t for t in tokens}
    assert set(by_tenant) == {tenant_a.id, tenant_b.id}
    assert by_tenant[tenant_a.id].user_id == user_a.id
    assert by_tenant[tenant_b.id].user_id == user_b.id

    rows = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "PASSWORD_RESET_REQUESTED"
            )
        )
    ).scalars().all()
    assert {r.tenant_id for r in rows} == {tenant_a.id, tenant_b.id}
    for row in rows:
        expected = user_a if row.tenant_id == tenant_a.id else user_b
        assert row.recipient_user_id == expected.id
        assert row.recipient_contact == expected.email


@pytest.mark.asyncio
async def test_a_scoped_read_cannot_see_the_other_tenants_token(
    db_session, tenant_a, tenant_b
) -> None:
    """The other side of "reachable": `count_live` is scoped, so A cannot see B's links."""
    from app.auth.infrastructure.repositories import SqlAlchemyPasswordResetTokenRepository

    user_a = await insert_user(db_session, tenant=tenant_a, email="a2@example.com")
    user_b = await insert_user(db_session, tenant=tenant_b, email="b2@example.com")
    await _recovery_use_case(db_session).execute(
        email="b2@example.com", client_ip="203.0.113.3", now=utc_now()
    )

    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()

    assert await repo.count_live(tenant_b.id, user_b.id, now) == 1
    assert await repo.count_live(tenant_a.id, user_a.id, now) == 0
    # A cannot reach B's row even by naming B's user: the tenant clause decides.
    assert await repo.count_live(tenant_a.id, user_b.id, now) == 0


@pytest.mark.asyncio
async def test_consuming_a_token_only_touches_its_own_tenants_user(
    db_session, tenant_a, tenant_b
) -> None:
    """R4.1 — `consume_globally` is unscoped by design (D3), so this is where that is
    checked: the tenant comes OUT of the row, and the other tenant's user is untouched."""
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.models import PasswordResetTokenModel, UserModel
    from app.auth.infrastructure.repositories import SqlAlchemyPasswordResetTokenRepository

    user_a = await insert_user(db_session, tenant=tenant_a, email="a3@example.com")
    user_b = await insert_user(db_session, tenant=tenant_b, email="b3@example.com")
    _cleartext, token_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant_b.id,
            user_id=user_b.id,
            token_hash=token_hash,
            expires_at=utc_now() + timedelta(minutes=30),
        )
    )
    await db_session.flush()
    hash_before_a = user_a.password_hash

    consumed = await SqlAlchemyPasswordResetTokenRepository(db_session).consume_globally(
        token_hash, utc_now()
    )

    assert consumed is not None
    assert consumed.tenant_id == tenant_b.id, "the tenant did not come out of the row"
    assert consumed.user_id == user_b.id
    row_a = (
        await db_session.execute(select(UserModel).where(UserModel.id == user_a.id))
    ).scalar_one()
    assert row_a.password_hash == hash_before_a


@pytest.mark.asyncio
async def test_a_cross_tenant_token_write_is_refused(db_session, tenant_a, tenant_b) -> None:
    """The "writable" half, and it needs `add()` called DIRECTLY.

    Running the use case cannot reach this: it always passes the `tenant_id` it just derived,
    so it never attempts the write the guard exists to refuse. Pointed out by the tenancy
    panel of section 6 while reviewing this very task.
    """
    from app.auth.domain.entities import PasswordResetToken
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.repositories import SqlAlchemyPasswordResetTokenRepository
    from app.core.tenancy import CrossTenantWriteError

    user_b = await insert_user(db_session, tenant=tenant_b, email="b4@example.com")
    now = utc_now()
    foreign = PasswordResetToken(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        token_hash=generate_recovery_token()[1],
        expires_at=now + timedelta(minutes=30),
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPasswordResetTokenRepository(db_session).add(tenant_a.id, foreign)


@pytest.mark.asyncio
async def test_a_cross_tenant_notification_write_is_refused(
    db_session, tenant_a, tenant_b
) -> None:
    """The same half for the second table `forgot-password` writes (R6.3)."""
    from app.core.tenancy import CrossTenantWriteError
    from app.notifications.domain.entities import NotificationLog
    from app.notifications.domain.enums import NotificationChannel
    from app.notifications.infrastructure.repositories import (
        SqlAlchemyNotificationLogRepository,
    )

    user_b = await insert_user(db_session, tenant=tenant_b, email="b5@example.com")
    now = utc_now()
    foreign = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        recipient_user_id=user_b.id,
        recipient_contact=user_b.email,
        channel=NotificationChannel.EMAIL,
        notification_type="PASSWORD_RESET_REQUESTED",
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyNotificationLogRepository(db_session).add(tenant_a.id, foreign)


@pytest.mark.asyncio
async def test_revoking_links_does_not_reach_the_other_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    """`count_live`, `revoke_other_live` and `revoke_oldest_beyond` are all tenant-scoped
    (design D3), unlike `consume_globally`."""
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.models import PasswordResetTokenModel
    from app.auth.infrastructure.repositories import SqlAlchemyPasswordResetTokenRepository

    user_a = await insert_user(db_session, tenant=tenant_a, email="a6@example.com")
    user_b = await insert_user(db_session, tenant=tenant_b, email="b6@example.com")
    now = utc_now()
    b_token_id = uuid.uuid4()
    db_session.add(
        PasswordResetTokenModel(
            id=b_token_id,
            tenant_id=tenant_b.id,
            user_id=user_b.id,
            token_hash=generate_recovery_token()[1],
            expires_at=now + timedelta(minutes=30),
        )
    )
    await db_session.flush()
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)

    assert await repo.revoke_other_live(tenant_a.id, user_a.id, uuid.uuid4(), now) == 0
    assert await repo.revoke_oldest_beyond(tenant_a.id, user_a.id, 0, now, now) == 0

    row = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.id == b_token_id)
        )
    ).scalar_one()
    assert row.revoked_at is None, "tenant B's link was revoked from tenant A"
