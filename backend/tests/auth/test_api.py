"""The auth endpoints end to end over ASGI (R1, R2, R3, R6.2, R6.6)."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import (
    get_login_throttle,
    get_password_hasher,
    get_token_codec,
)
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import TENANT_ID_SESSION_KEY, get_db_session
from app.main import create_app
from tests.auth.conftest import PASSWORD, TEST_BCRYPT_ROUNDS, insert_user, utc_now
from tests.auth.doubles import InMemoryLoginThrottle

SECRET = "s" * 64


@pytest_asyncio.fixture
async def api(db_session):
    """The real app, with only the outermost adapters swapped for the test ones."""
    app = create_app()
    throttle = InMemoryLoginThrottle()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_login_throttle] = lambda: throttle
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        client.throttle = throttle  # type: ignore[attr-defined]
        yield client


async def _login(api, email="owner@example.com", password=PASSWORD, **extra):
    return await api.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})


def _assert_envelope(payload, code: str) -> None:
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str) and payload["error"]["message"]


@pytest.mark.asyncio
async def test_login_returns_a_token_pair(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    response = await _login(api)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900


@pytest.mark.asyncio
async def test_the_whole_flow_login_me_refresh_logout(api, db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()

    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)

    rotated = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]

    logout = await api.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert logout.status_code == 204
    assert logout.content == b""

    reused = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_the_whole_flow_login_me_refresh_logout_for_a_super_admin(api, db_session) -> None:
    """`super-admin-identity` R2: none of the four answers `500` for a tenantless account."""
    await insert_user(db_session, tenant=None, role=UserRole.SUPER_ADMIN, email="root@example.com")
    tokens = (await _login(api, email="root@example.com")).json()
    assert "access_token" in tokens

    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["tenant_id"] is None
    assert me.json()["role"] == UserRole.SUPER_ADMIN.value

    rotated = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]

    logout = await api.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert logout.status_code == 204


@pytest.mark.asyncio
async def test_me_never_exposes_the_password_hash(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()

    body = (
        await api.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
    ).json()

    assert set(body) == {
        "id",
        "tenant_id",
        "name",
        "email",
        "role",
        "preferred_language",
        # `auth-account-recovery` R5.6: the frontend needs it here to redirect to the
        # change-password screen rather than discovering the state from a `403` elsewhere.
        "must_change_password",
    }
    assert "password_hash" not in body
    assert "status" not in body


@pytest.mark.asyncio
async def test_wrong_credentials_answer_the_envelope(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    response = await _login(api, password="wrong")

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_CREDENTIALS")
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [UserStatus.INACTIVE, UserStatus.SUSPENDED])
async def test_a_disabled_account_is_indistinguishable(api, db_session, tenant_a, status) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", status=status)

    response = await _login(api)

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_CREDENTIALS")


@pytest.mark.asyncio
async def test_a_missing_bearer_header_is_rejected(api) -> None:
    response = await api.get("/api/v1/auth/me")

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_a_non_bearer_scheme_is_rejected(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()

    response = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Basic {tokens['access_token']}"}
    )

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_a_refresh_token_is_not_accepted_as_a_bearer(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()

    response = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_a_garbage_token_is_rejected(api) -> None:
    response = await api.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_a_token_naming_another_tenant_is_rejected(api, db_session, tenant_a, tenant_b) -> None:
    """R4.1/R4.5: the tenant comes from the token, and it is revalidated (design D7)."""
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    forged = api.codec.issue_access(
        user_id=user.id,
        tenant_id=tenant_b.id,
        role=UserRole.TENANT_OWNER,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    response = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_a_suspended_user_loses_access_immediately(api, db_session, tenant_a) -> None:
    """No waiting for the access token to expire (design D7)."""
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 200

    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
    user.status = UserStatus.SUSPENDED
    await db_session.flush()

    assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_an_access_token_still_works_after_logout_through_the_real_boundary(
    api, db_session, tenant_a
) -> None:
    """Pins R2.4 where a revocation check would actually live.

    An earlier version of this pin decoded the JWT with the bare codec, so it could not
    fail: `get_authenticated_request` is the only place a revocation list would be
    consulted, and that path was never exercised. Going through HTTP is what makes the
    negative requirement enforceable.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    tokens = (await _login(api)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (
        await api.post("/api/v1/auth/logout", headers=headers)
    ).status_code == 204

    # Still 200: there is no access-token revocation list, by decision. The window is
    # bounded by the token lifetime.
    assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 200
    # But the session is gone, so it cannot be renewed.
    assert (
        await api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


@pytest.mark.asyncio
async def test_the_effective_role_comes_from_the_database_not_the_token(
    api, db_session, tenant_a
) -> None:
    """Design D7 and task 7.2: demoting a role takes effect immediately.

    Issued with TENANT_OWNER in the claim, then demoted in the database. If the claim
    were trusted, `/me` would still say TENANT_OWNER — and every RBAC decision would be
    made on a stale role for up to the access token's lifetime.
    """
    user = await insert_user(
        db_session, tenant=tenant_a, email="owner@example.com", role=UserRole.TENANT_OWNER
    )
    tokens = (await _login(api)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert api.codec.decode_access(tokens["access_token"]).role is UserRole.TENANT_OWNER

    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
    user.role = UserRole.CLEANER
    await db_session.flush()

    body = (await api.get("/api/v1/auth/me", headers=headers)).json()

    assert body["role"] == UserRole.CLEANER.value


@pytest.mark.asyncio
async def test_the_rate_limit_answers_429_with_the_envelope(api, db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    api.throttle._attempts_per_minute = 1
    await _login(api)

    response = await _login(api)

    assert response.status_code == 429
    _assert_envelope(response.json(), "RATE_LIMITED")


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_body_is_refused_outright(api, db_session, tenant_a, tenant_b) -> None:
    """The schemas forbid extra fields, so an injected tenant cannot even be parsed."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    response = await _login(api, tenant_id=str(tenant_b.id))

    assert response.status_code == 422
    _assert_envelope(response.json(), "VALIDATION_ERROR")


@pytest.mark.asyncio
async def test_a_malformed_body_answers_the_reshaped_422(api) -> None:
    response = await api.post("/api/v1/auth/login", json={"email": "only-an-email"})

    assert response.status_code == 422
    _assert_envelope(response.json(), "VALIDATION_ERROR")
    assert response.json()["error"]["details"]["errors"]


@pytest.mark.asyncio
async def test_openapi_declares_the_bearer_scheme(api) -> None:
    schema = (await api.get("/openapi.json")).json()

    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert any(
        definition.get("scheme") == "bearer" for definition in schemes.values()
    ), f"no bearer security scheme in {list(schemes)}"


@pytest.mark.asyncio
async def test_the_protected_endpoints_reference_the_scheme_in_openapi(api) -> None:
    schema = (await api.get("/openapi.json")).json()

    assert schema["paths"]["/api/v1/auth/me"]["get"].get("security")
    assert schema["paths"]["/api/v1/auth/logout"]["post"].get("security")
    assert not schema["paths"]["/api/v1/auth/login"]["post"].get("security")


@pytest.mark.asyncio
async def test_every_auth_endpoint_is_documented(api) -> None:
    schema = (await api.get("/openapi.json")).json()

    for path, method in [
        ("/api/v1/auth/login", "post"),
        ("/api/v1/auth/refresh", "post"),
        ("/api/v1/auth/logout", "post"),
        ("/api/v1/auth/me", "get"),
    ]:
        operation = schema["paths"][path][method]
        assert operation.get("summary"), f"{method.upper()} {path} has no summary"
