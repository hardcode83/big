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
from app.auth.api.schemas import SESSION_REFRESH_COOKIE
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
    """`auth-session-persistence` R1: the refresh token travels only via the cookie."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    response = await _login(api)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900

    cookie_header = response.headers.get("set-cookie")
    assert cookie_header is not None
    assert cookie_header.startswith("autohostai.session.refresh=")
    assert "HttpOnly" in cookie_header
    assert "samesite=lax" in cookie_header.lower()
    assert "Path=/api/v1/auth" in cookie_header
    assert "Max-Age=604800" in cookie_header


@pytest.mark.asyncio
async def test_login_logs_the_resolved_cookie_secure_decision(
    api, db_session, tenant_a, caplog
) -> None:
    """`auth-session-persistence` R7.2: the `Secure` decision is recorded for audit."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")

    with caplog.at_level("INFO", logger="app.auth.api.router"):
        response = await _login(api)

    assert response.status_code == 200
    records = [
        r for r in caplog.records if r.getMessage() == "auth.refresh_cookie_issued"
    ]
    assert len(records) == 1
    assert records[0].secure is False
    assert records[0].endpoint == "login"


@pytest.mark.asyncio
async def test_refresh_logs_the_resolved_cookie_secure_decision(
    api, db_session, tenant_a, caplog
) -> None:
    """`auth-session-persistence` R7.2: same audit log, on the rotation path."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    await _login(api)

    with caplog.at_level("INFO", logger="app.auth.api.router"):
        response = await api.post("/api/v1/auth/refresh", json={})

    assert response.status_code == 200
    records = [
        r for r in caplog.records if r.getMessage() == "auth.refresh_cookie_issued"
    ]
    assert len(records) == 1
    assert records[0].secure is False
    assert records[0].endpoint == "refresh"


@pytest.mark.asyncio
async def test_the_whole_flow_login_me_refresh_logout(api, db_session, tenant_a) -> None:
    """`auth-session-persistence` R2, R3: refresh reads the cookie, logout purges it."""
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    login_response = await _login(api)
    tokens = login_response.json()
    initial_cookie = login_response.cookies.get(SESSION_REFRESH_COOKIE)
    assert initial_cookie is not None

    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)

    # No body needed: the same `api` client instance carries the cookie login set.
    rotated = await api.post("/api/v1/auth/refresh", json={})
    assert rotated.status_code == 200
    rotated_cookie = rotated.cookies.get(SESSION_REFRESH_COOKIE)
    assert rotated_cookie is not None
    assert rotated_cookie != initial_cookie
    # The rotated body carries no `refresh_token` field at all (R1.2/R2.3).
    assert "refresh_token" not in rotated.json()
    # Same raw-header shape as the login cookie (R1/R2): the refresh endpoint's own
    # `Set-Cookie` is not just "present", it carries the same attributes.
    rotated_set_cookie = rotated.headers.get("set-cookie")
    assert rotated_set_cookie is not None
    assert "Max-Age=604800" in rotated_set_cookie
    assert "HttpOnly" in rotated_set_cookie
    assert "Path=/api/v1/auth" in rotated_set_cookie

    logout = await api.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert logout.status_code == 204
    assert logout.content == b""
    logout_set_cookie = logout.headers.get("set-cookie")
    assert logout_set_cookie is not None
    assert logout_set_cookie.startswith("autohostai.session.refresh=")
    assert "Max-Age=0" in logout_set_cookie

    # Presenting the rotated (never-used) token again after logout still fails: the
    # cookie jar deleted it, so this exercises the "no cookie" 401 path.
    reused = await api.post("/api/v1/auth/refresh", json={})
    assert reused.status_code == 401
    assert "set-cookie" not in reused.headers

    # Explicitly presenting the rotated value (simulating a stale client that still
    # holds it) is rejected too: the family was revoked by logout (R3.1).
    api.cookies.set(SESSION_REFRESH_COOKIE, rotated_cookie)
    reused_explicit = await api.post("/api/v1/auth/refresh", json={})
    assert reused_explicit.status_code == 401
    # R2.2: a revoked-cookie 401 emits no `Set-Cookie` either — same as the absent-cookie
    # case above, just reached through a different route (a stale but well-formed value
    # instead of nothing at all).
    assert "set-cookie" not in reused_explicit.headers

    # Idempotent logout (R3.2): calling it again on a client with no cookie left in the
    # jar (the first logout already purged it) still answers 204 and still emits the
    # purge header — the endpoint never branches on "was there anything to revoke".
    second_logout = await api.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert second_logout.status_code == 204
    second_logout_set_cookie = second_logout.headers.get("set-cookie")
    assert second_logout_set_cookie is not None
    assert second_logout_set_cookie.startswith("autohostai.session.refresh=")
    assert "Max-Age=0" in second_logout_set_cookie


@pytest.mark.asyncio
async def test_logout_with_no_bearer_revokes_via_the_refresh_cookie(
    api, db_session, tenant_a
) -> None:
    """`auth-session-persistence` R6.2 (review: sdd-security): the cookie is a credential.

    No `Authorization` header is ever sent — the client's in-memory access token is
    "empty", the case `use-logout-mutation.ts` hits after a reload with no mount-refresh
    yet, or a session-expired reset. The refresh cookie alone must still end the session,
    with no prior `POST /auth/refresh` needed to obtain a Bearer.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    login_response = await _login(api)
    cookie = login_response.cookies.get(SESSION_REFRESH_COOKIE)
    assert cookie is not None

    logout = await api.post("/api/v1/auth/logout")

    assert logout.status_code == 204
    assert logout.content == b""
    logout_set_cookie = logout.headers.get("set-cookie")
    assert logout_set_cookie is not None
    assert logout_set_cookie.startswith("autohostai.session.refresh=")
    assert "Max-Age=0" in logout_set_cookie

    # Proof the family was actually revoked, not just that the local cookie was purged:
    # explicitly presenting the same (captured) cookie value to /auth/refresh is rejected.
    api.cookies.set(SESSION_REFRESH_COOKIE, cookie)
    reused = await api.post("/api/v1/auth/refresh", json={})
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_no_bearer_and_no_cookie_is_a_no_op(api) -> None:
    """R3.2's idempotency extends to the cookie-only path: nothing to revoke is not
    an error — same 204 as the authenticated "already logged out" case."""
    response = await api.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_logout_with_no_bearer_and_a_garbage_cookie_is_a_no_op(api) -> None:
    """A cookie that fails to decode (tampered, wrong signature, expired) does not turn
    into a distinguishable error — it is treated the same as no cookie at all (R3.2)."""
    api.cookies.set(SESSION_REFRESH_COOKIE, "not.a.jwt")

    response = await api.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_the_whole_flow_login_me_refresh_logout_for_a_super_admin(api, db_session) -> None:
    """`super-admin-identity` R2: none of the four answers `500` for a tenantless account."""
    await insert_user(db_session, tenant=None, role=UserRole.SUPER_ADMIN, email="root@example.com")
    login_response = await _login(api, email="root@example.com")
    tokens = login_response.json()
    assert "access_token" in tokens
    initial_cookie = login_response.cookies.get(SESSION_REFRESH_COOKIE)
    assert initial_cookie is not None

    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["tenant_id"] is None
    assert me.json()["role"] == UserRole.SUPER_ADMIN.value

    rotated = await api.post("/api/v1/auth/refresh", json={})
    assert rotated.status_code == 200
    rotated_cookie = rotated.cookies.get(SESSION_REFRESH_COOKIE)
    assert rotated_cookie is not None
    assert rotated_cookie != initial_cookie
    rotated_set_cookie = rotated.headers.get("set-cookie")
    assert rotated_set_cookie is not None
    assert "Max-Age=604800" in rotated_set_cookie
    assert "HttpOnly" in rotated_set_cookie
    assert "Path=/api/v1/auth" in rotated_set_cookie

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
    # `auth-session-persistence` R1.3: a failed login never sets the refresh cookie —
    # the exception raised inside `execute` propagates before `emit_refresh_cookie` runs.
    assert "set-cookie" not in response.headers


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
    login_response = await _login(api)
    refresh_token = login_response.cookies.get(SESSION_REFRESH_COOKIE)
    assert refresh_token is not None

    response = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
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
    # But the session is gone, so it cannot be renewed — the cookie itself was purged
    # by logout, so this hits the "no cookie" 401 path.
    assert (await api.post("/api/v1/auth/refresh", json={})).status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_no_cookie_at_all_is_rejected(api) -> None:
    """`auth-session-persistence` R2.2: an absent cookie is a 401, and no `Set-Cookie`."""
    response = await api.post("/api/v1/auth/refresh", json={})

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_refresh_ignores_a_refresh_token_in_the_body(api, db_session, tenant_a) -> None:
    """`auth-session-persistence` R2.3: a body `refresh_token` is not read as a fallback.

    A valid refresh cookie exists (from login), but this client never sends it — instead
    it sends a JSON body naming a refresh token. That value must be ignored, not read as
    a fallback, so the request is treated exactly as if the cookie were absent: 401.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    login_response = await _login(api)
    real_cookie = login_response.cookies.get(SESSION_REFRESH_COOKIE)
    assert real_cookie is not None
    # The client's jar would otherwise carry the real cookie from login too — delete it
    # so this request truly has no cookie, only the body.
    api.cookies.delete(SESSION_REFRESH_COOKIE)

    response = await api.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": real_cookie},
    )

    assert response.status_code == 401
    _assert_envelope(response.json(), "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_refresh_uses_the_cookie_even_when_the_body_also_carries_a_valid_token(
    api, db_session, tenant_a
) -> None:
    """`auth-session-persistence` R2.3: with BOTH present, the cookie wins outright.

    Two distinct sessions exist, each with its own valid refresh token. The request's
    cookie names one; the body's `refresh_token` names the other, unrelated one. If the
    body were ever consulted — as a fallback, a cross-check, anything — the wrong
    session would be touched. Proof: after the call, the body's token is still fully
    valid and rotates cleanly on its own, so it was never read, let alone spent.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    await insert_user(db_session, tenant=tenant_a, email="second@example.com")

    cookie_login = await _login(api, email="owner@example.com")
    cookie_token = cookie_login.cookies.get(SESSION_REFRESH_COOKIE)
    assert cookie_token is not None

    # A separate login for a second, unrelated session — captured from the response
    # directly (not the jar, which the next login would overwrite anyway).
    api.cookies.delete(SESSION_REFRESH_COOKIE)
    body_login = await _login(api, email="second@example.com")
    body_token = body_login.cookies.get(SESSION_REFRESH_COOKIE)
    assert body_token is not None
    assert body_token != cookie_token

    # The jar carries the first session's cookie; the body names the second, different
    # session's token.
    api.cookies.set(SESSION_REFRESH_COOKIE, cookie_token)
    response = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": body_token}
    )

    assert response.status_code == 200
    rotated_cookie = response.cookies.get(SESSION_REFRESH_COOKIE)
    assert rotated_cookie is not None
    assert rotated_cookie != cookie_token
    # Not the body's token either: it was rotated FROM the cookie, not from the body.
    assert rotated_cookie != body_token

    # The body's token was never touched: it is still live and rotates cleanly on its
    # own, proving the endpoint never read it.
    api.cookies.set(SESSION_REFRESH_COOKIE, body_token)
    still_valid = await api.post("/api/v1/auth/refresh", json={})
    assert still_valid.status_code == 200


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
