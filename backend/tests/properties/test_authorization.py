"""The full endpoint × role matrix of R6.8, for all five roles.

Not a spot check: every method of every property endpoint is exercised with a token of each role,
and the expectation is **written out per role rather than derived from the policy catalogue** — a
table computed from `ROLE_PERMISSIONS` would agree with any mistake in it.

The matrix comes from design D12, which had to be argued rather than cited: PRD §6 names no
create-or-edit-property capability for any role. §6 gives `TENANT_OWNER` "ver sus propiedades y
reservas" (a read) and `PROPERTY_MANAGER` "acceder a todos los datos operativos", so the split
mirrors `reservations` — and its assumed consequence is that the owner cannot register her own
flat, only the manager can.

Every assertion checks the CONCRETE status code, never `!= 403`: that weaker form would pass just
as happily if an allowed role got a `500`.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from tests.properties.conftest import auth_header

READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}
MANAGERS = {UserRole.PROPERTY_MANAGER}
ALL_ROLES = list(UserRole)


async def _seed_property(api, users_by_role_a, create_payload, **overrides) -> str:
    response = await api.post(
        "/api/v1/properties",
        json=create_payload(**overrides),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_listing_is_allowed_for_readers_only(api, users_by_role_a, role: UserRole) -> None:
    response = await api.get(
        "/api/v1/properties", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_reading_the_detail_is_allowed_for_readers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    property_id = await _seed_property(api, users_by_role_a, create_payload)

    response = await api.get(
        f"/api/v1/properties/{property_id}", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_creating_is_allowed_for_managers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    """The owner is refused here on purpose — design D12's assumed consequence."""
    response = await api.post(
        "/api/v1/properties",
        json=create_payload(internal_code=f"CODE-{role.value}"),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (201 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_patching_is_allowed_for_managers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    property_id = await _seed_property(api, users_by_role_a, create_payload)

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"city": "Segovia"},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.asyncio
async def test_no_endpoint_is_reachable_without_a_token(api) -> None:
    property_id = uuid.uuid4()
    for method, path, body in (
        ("get", "/api/v1/properties", None),
        ("post", "/api/v1/properties", {"name": "X", "internal_code": "X"}),
        ("get", f"/api/v1/properties/{property_id}", None),
        ("patch", f"/api/v1/properties/{property_id}", {"city": "Madrid"}),
    ):
        response = await getattr(api, method)(path, json=body) if body else await getattr(
            api, method
        )(path)
        assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"


@pytest.mark.asyncio
async def test_a_forbidden_answer_never_reveals_whether_the_resource_exists(
    api, users_by_role_a, create_payload
) -> None:
    """R1.7: authorisation is decided BEFORE the resource is looked up.

    A `CLEANER` must get the same body for a real id and an invented one, or the difference is an
    oracle for enumerating the tenant's portfolio.
    """
    property_id = await _seed_property(api, users_by_role_a, create_payload)
    headers = auth_header(api, users_by_role_a[UserRole.CLEANER])

    real = await api.get(f"/api/v1/properties/{property_id}", headers=headers)
    invented = await api.get(f"/api/v1/properties/{uuid.uuid4()}", headers=headers)

    assert real.status_code == invented.status_code == 403
    assert real.json() == invented.json()
