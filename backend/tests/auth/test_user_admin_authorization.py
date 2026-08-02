"""The full endpoint × role matrix of R7.2, for all five roles.

Not a spot check: every method of every user-administration endpoint is exercised with a token
of each role, and the expectation is written out per role rather than derived from the policy
catalogue — a table computed from `ROLE_PERMISSIONS` would agree with any mistake in it.

The matrix comes from design D8, because PRD §6 names nobody as the administrator of staff:
`TENANT_OWNER` manages, `PROPERTY_MANAGER` reads, and `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` get
nothing here. This is the R4.4 criterion `auth-tenancy` declared out of its own scope, since
all four of its endpoints were self-referential.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from tests.auth.conftest import auth_header

READERS = {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}
MANAGERS = {UserRole.TENANT_OWNER}
ALL_ROLES = list(UserRole)


def _payload(**overrides) -> dict:
    payload = {
        "name": "Nueva",
        "email": f"nueva-{uuid.uuid4().hex[:8]}@example.com",
        "role": UserRole.CLEANER.value,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_listing_is_allowed_for_readers_only(api, users_by_role_a, role) -> None:
    response = await api.get("/api/v1/users", headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_reading_the_detail_is_allowed_for_readers_only(api, users_by_role_a, role) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.get(
        f"/api/v1/users/{target.id}", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_creating_is_allowed_for_managers_only(api, users_by_role_a, role) -> None:
    response = await api.post(
        "/api/v1/users", json=_payload(), headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (201 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_patching_is_allowed_for_managers_only(api, users_by_role_a, role) -> None:
    target = users_by_role_a[UserRole.TECHNICIAN]

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={"name": "Renamed"},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_deleting_is_allowed_for_managers_only(api, users_by_role_a, role) -> None:
    target = users_by_role_a[UserRole.TECHNICIAN]

    response = await api.delete(
        f"/api/v1/users/{target.id}", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (204 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_resetting_a_password_is_allowed_for_managers_only(
    api, users_by_role_a, role
) -> None:
    target = users_by_role_a[UserRole.TECHNICIAN]

    response = await api.post(
        f"/api/v1/users/{target.id}/reset-password",
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/users", None),
        ("POST", "/api/v1/users", {}),
        ("GET", f"/api/v1/users/{uuid.uuid4()}", None),
        ("PATCH", f"/api/v1/users/{uuid.uuid4()}", {"name": "x"}),
        ("DELETE", f"/api/v1/users/{uuid.uuid4()}", None),
        ("POST", f"/api/v1/users/{uuid.uuid4()}/reset-password", None),
    ],
)
@pytest.mark.asyncio
async def test_no_endpoint_is_reachable_without_a_token(api, method, path, body) -> None:
    """Deny by default at the transport level, before any role question."""
    response = await api.request(method, path, json=body)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_forbidden_answer_never_reveals_whether_the_user_exists(
    api, users_by_role_a
) -> None:
    """R7.3: a `CLEANER` gets the same `403` for a real user and for a made-up id.

    If the authorisation check ran after the lookup, the two answers would differ and the
    endpoint would enumerate user ids for a role that cannot read them.
    """
    real_id = users_by_role_a[UserRole.TECHNICIAN].id
    cleaner = auth_header(api, users_by_role_a[UserRole.CLEANER])

    real = await api.get(f"/api/v1/users/{real_id}", headers=cleaner)
    invented = await api.get(f"/api/v1/users/{uuid.uuid4()}", headers=cleaner)

    assert real.status_code == invented.status_code == 403
    assert real.json() == invented.json()


@pytest.mark.asyncio
async def test_a_manager_cannot_escalate_itself(api, users_by_role_a) -> None:
    """The reason the write side stays with the owner (design D8).

    A `PROPERTY_MANAGER` with `MANAGE_USERS` could grant itself `TENANT_OWNER`; the point of
    giving it read-only access is that this answer is `403`.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await api.patch(
        f"/api/v1/users/{manager.id}",
        json={"role": UserRole.TENANT_OWNER.value},
        headers=auth_header(api, manager),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_cleaner_can_still_read_its_own_profile(api, users_by_role_a) -> None:
    """The roles denied here keep the self-service PRD §6 grants every role."""
    cleaner = users_by_role_a[UserRole.CLEANER]

    response = await api.get("/api/v1/auth/me", headers=auth_header(api, cleaner))

    assert response.status_code == 200
    assert response.json()["id"] == str(cleaner.id)


@pytest.mark.asyncio
async def test_every_administration_route_declares_a_permission(api) -> None:
    """`tests/test_route_authorization.py` walks this globally; here it is pinned locally.

    Cheap insurance that a future endpoint added to this router cannot ship without a
    `require(...)`, in the file where somebody would add it.
    """
    from app.auth.api.dependencies import REQUIRED_PERMISSION_ATTR
    from app.auth.api.users_router import router

    for route in router.routes:
        declared = [
            dependency.call
            for dependency in route.dependant.dependencies  # type: ignore[attr-defined]
            if hasattr(dependency.call, REQUIRED_PERMISSION_ATTR)
        ]
        assert declared, f"{route.path} does not declare a permission"  # type: ignore[attr-defined]
