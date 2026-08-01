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

    authenticated = await get_authenticated_request(
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
