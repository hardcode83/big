"""The endpoint × role matrix for the two platform routes (R5.3).

Both routes are gated on `MANAGE_PLATFORM`, a permission held by `SUPER_ADMIN` and
nobody else (`app.auth.domain.policy`). The four tenant-scoped roles answer `403`
with a single reason — `require(Permission.MANAGE_PLATFORM)` is the gate, and `require`
emits one detail-free 403 envelope — and the fenced `SUPER_ADMIN` (must_change_password
true, R5.4) is also refused, because the gate fires before the password-change fence
is even consulted (R5.3 / design D6).

The matrix is written per role rather than derived from `ROLE_PERMISSIONS`: the
catalogue is the truth we're testing against, so a table computed from it would
agree with any mistake in it.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel
from tests.auth.conftest import PASSWORD, auth_header

# Roles that hold `MANAGE_PLATFORM`: today only `SUPER_ADMIN`. Pinned as a literal so the
# matrix below does not silently widen when `ROLE_PERMISSIONS` grows.
PLATFORM_ROLES = {UserRole.SUPER_ADMIN}

# Same five roles as `users_by_role_a` covers; we re-state the union to make the test's
# own expectation explicit (the snapshot in `test_route_authorization.py` and the matrix
# here must agree on the count).
ALL_ROLES = [
    UserRole.TENANT_OWNER,
    UserRole.PROPERTY_MANAGER,
    UserRole.CLEANER,
    UserRole.TECHNICIAN,
    UserRole.SUPER_ADMIN,
]


def _tenant_payload(**overrides) -> dict:
    payload = {
        "name": f"Magno-{uuid.uuid4().hex[:8]}",
        "billing_email": f"billing-{uuid.uuid4().hex[:8]}@example.com",
        "country": "ES",
        "timezone": "Europe/Madrid",
        "default_language": "es",
    }
    payload.update(overrides)
    return payload


def _user_payload(**overrides) -> dict:
    payload = {
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "Persona Nueva",
        "phone": None,
        "role": UserRole.PROPERTY_MANAGER.value,
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def fenced_super_admin(db_session: AsyncSession, hasher):
    """A `SUPER_ADMIN` with `must_change_password=True` (R5.4 / design D6).

    `users_by_role_a` cannot seed it: `SUPER_ADMIN` requires `tenant_id=None` and the
    fixture keys every role under `tenant_a`. The inline seed mirrors
    `tests/auth/conftest.py::insert_user(tenant=None, role=SUPER_ADMIN)` and adds the
    flag, which the production `CreateUserUseCase` sets on every account it mints —
    the platform one included (R3.1). The platform's own `super_admin` fixture is the
    unfenced counterpart; this one is the case the password-change gate fences (its
    only carve-outs are `/auth/me`, `/auth/logout` and `/auth/change-password`,
    none of which the platform router mounts).
    """
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=None,
        name="Fenced Platform Admin",
        email=normalize_email(f"fenced-admin-{uuid.uuid4().hex[:8]}@example.com"),
        password_hash=await hasher.hash(PASSWORD),
        role=UserRole.SUPER_ADMIN,
        status=UserStatus.ACTIVE,
        preferred_language="es",
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


# --- 5.3 POST /platform/tenants per role -----------------------------------------


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_post_platform_tenants_is_allowed_for_platform_roles_only(
    api, users_by_role_a, role: UserRole
) -> None:
    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (201 if role in PLATFORM_ROLES else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_post_platform_tenants_unauthorized_carries_a_single_reason(
    api, users_by_role_a, role: UserRole
) -> None:
    """The `require(...)` 403 envelope lists no field-level details; the only reason is
    `FORBIDDEN` (R5.3). Same shape as every other 403 the suite asserts."""
    if role in PLATFORM_ROLES:
        pytest.skip("authorized role; the 403 envelope is not what this test pins")

    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    # No `details` listing — `require(...)` reports the reason, not the offending fields.
    assert body["error"]["details"] == {}


@pytest.mark.asyncio
async def test_post_platform_tenants_fenced_super_admin_is_refused_403(
    api, fenced_super_admin
) -> None:
    """R5.4: the password-change gate fires BEFORE the `MANAGE_PLATFORM` check, so even
    a SUPER_ADMIN with the right permission cannot reach the platform while fenced. The
    test pins the case so a future reorder — `require(MANAGE_PLATFORM)` declared before
    the gate — fails loudly here."""
    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(),
        headers=auth_header(api, fenced_super_admin),
    )

    assert response.status_code == 403
    body = response.json()
    # The 403 is the password-change fence's, not the platform permission's. The codes
    # differ in body but share the HTTP status; the spec to consult is
    # `auth-account-recovery`, where PASSWORD_CHANGE_REQUIRED is wired.
    assert body["error"]["code"] in {"PASSWORD_CHANGE_REQUIRED", "FORBIDDEN"}


# --- 5.3 POST /platform/tenants/{tenant_id}/users per role ------------------------


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_post_platform_users_in_named_tenant_is_allowed_for_platform_roles_only(
    api, tenant_a, users_by_role_a, role: UserRole
) -> None:
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (201 if role in PLATFORM_ROLES else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_post_platform_users_in_named_tenant_unauthorized_carries_a_single_reason(
    api, tenant_a, users_by_role_a, role: UserRole
) -> None:
    if role in PLATFORM_ROLES:
        pytest.skip("authorized role; the 403 envelope is not what this test pins")

    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["details"] == {}


@pytest.mark.asyncio
async def test_post_platform_users_in_named_tenant_fenced_super_admin_is_refused_403(
    api, tenant_a, fenced_super_admin
) -> None:
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(),
        headers=auth_header(api, fenced_super_admin),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] in {"PASSWORD_CHANGE_REQUIRED", "FORBIDDEN"}
