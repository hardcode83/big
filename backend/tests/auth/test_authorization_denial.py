"""The RBAC denial path, executed for real (R3.4, `steering/security.md` rule 2).

Why this file exists: `ROLE_PERMISSIONS` currently grants both permissions to all five
roles, so neither `/auth/me` nor `/auth/logout` can ever produce a 403 — which left
`require()`'s `raise ForbiddenError` unexecuted by the whole suite, even though it is
the single enforcement point every future module's RBAC will go through. An inversion
or a swallowed exception there would ship green.

So these tests mount throwaway routes on a real app with a permission the caller does
not hold, instead of waiting for a business module to have role-differentiated
permissions.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_token_codec, require
from app.auth.domain import policy
from app.auth.domain.enums import UserRole
from app.auth.domain.policy import Permission
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.main import create_app
from tests.auth.conftest import insert_user, utc_now

SECRET = "s" * 64


@pytest.fixture
def codec() -> JwtTokenCodec:
    return JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)


@pytest_asyncio.fixture
async def guarded_app(db_session, codec):
    """A real app with two throwaway guarded routes and a recorder of what ran."""
    app = create_app()
    app.state.executed = []

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec

    @app.get("/needs-profile")
    async def needs_profile(_=Depends(require(Permission.READ_OWN_PROFILE))) -> dict[str, bool]:
        app.state.executed.append("needs-profile")
        return {"ran": True}

    @app.get("/needs-session")
    async def needs_session(_=Depends(require(Permission.MANAGE_OWN_SESSION))) -> dict[str, bool]:
        app.state.executed.append("needs-session")
        return {"ran": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client


def _token(codec: JwtTokenCodec, user) -> str:
    return codec.issue_access(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
async def test_a_role_without_the_permission_gets_403_and_the_body_does_not_run(
    guarded_app, db_session, tenant_a, codec, monkeypatch: pytest.MonkeyPatch, role: UserRole
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, role=role)
    # Strip the permission from this role only, so the denial is reachable while the
    # rest of the catalogue stays as PRD §6 defines it.
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {**policy.ROLE_PERMISSIONS, role: frozenset({Permission.MANAGE_OWN_SESSION})},
    )

    response = await guarded_app.get(
        "/needs-profile", headers={"Authorization": f"Bearer {_token(codec, user)}"}
    )

    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "FORBIDDEN"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert guarded_app.app.state.executed == [], "the endpoint body must not have run"


@pytest.mark.asyncio
async def test_the_same_caller_is_allowed_where_the_permission_is_held(
    guarded_app, db_session, tenant_a, codec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards against a `require` that denies everything, which would also pass above."""
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.CLEANER)
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {**policy.ROLE_PERMISSIONS, UserRole.CLEANER: frozenset({Permission.MANAGE_OWN_SESSION})},
    )
    headers = {"Authorization": f"Bearer {_token(codec, user)}"}

    denied = await guarded_app.get("/needs-profile", headers=headers)
    allowed = await guarded_app.get("/needs-session", headers=headers)

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert guarded_app.app.state.executed == ["needs-session"]


@pytest.mark.asyncio
async def test_authorisation_is_checked_after_authentication_not_instead_of_it(
    guarded_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No token at all: the answer must be 401, not 403 — otherwise the absence of a
    # credential would be reported as a permission problem.
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {**policy.ROLE_PERMISSIONS, UserRole.CLEANER: frozenset()},
    )

    response = await guarded_app.get("/needs-profile")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_a_role_with_no_permissions_at_all_is_denied_everything(
    guarded_app, db_session, tenant_a, codec, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.TECHNICIAN)
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {**policy.ROLE_PERMISSIONS, UserRole.TECHNICIAN: frozenset()},
    )
    headers = {"Authorization": f"Bearer {_token(codec, user)}"}

    assert (await guarded_app.get("/needs-profile", headers=headers)).status_code == 403
    assert (await guarded_app.get("/needs-session", headers=headers)).status_code == 403
    assert guarded_app.app.state.executed == []


@pytest.mark.asyncio
async def test_a_role_missing_from_the_catalogue_is_denied(
    guarded_app, db_session, tenant_a, codec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny by default: an unmapped role must not fall through as allowed."""
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.SUPER_ADMIN)
    monkeypatch.setattr(policy, "ROLE_PERMISSIONS", {})

    response = await guarded_app.get(
        "/needs-profile", headers={"Authorization": f"Bearer {_token(codec, user)}"}
    )

    assert response.status_code == 403
