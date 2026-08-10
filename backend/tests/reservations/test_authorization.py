"""The full endpoint × role matrix of R5.7, for all five roles.

Not a spot check: every method of every reservation endpoint is exercised with a token of
each role, and the expectation is written out per role rather than derived from the policy
catalogue — a table computed from `ROLE_PERMISSIONS` would agree with any mistake in it.

The matrix comes from PRD §6 via design D7: `PROPERTY_MANAGER` manages, `TENANT_OWNER`
reads, and `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` get nothing here.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from tests.reservations.conftest import auth_header

# A literal, not `uuid.uuid4()`. Inside `@pytest.mark.parametrize` a random value becomes
# part of the test id, and under `pytest -n` each worker collects a different one — the
# suite then aborts with "Different tests were collected between gw0 and gw3" before running
# anything. It reads better too: what these cases need is an id that resolves to nothing,
# and any fixed one does that.
ABSENT_ID = "3f1a6c2e-0000-4000-8000-000000000001"

READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}
MANAGERS = {UserRole.PROPERTY_MANAGER}
ALL_ROLES = list(UserRole)


async def _seed_reservation(api, users_by_role_a, create_payload) -> str:
    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_listing_is_allowed_for_readers_only(
    api, users_by_role_a, role: UserRole
) -> None:
    response = await api.get(
        "/api/v1/reservations", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_reading_the_detail_is_allowed_for_readers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload)

    response = await api.get(
        f"/api/v1/reservations/{reservation_id}", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_creating_is_allowed_for_managers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(),
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (201 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_patching_is_allowed_for_managers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload)

    response = await api.patch(
        f"/api/v1/reservations/{reservation_id}",
        json={"adults": 3},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_cancelling_is_allowed_for_managers_only(
    api, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload)

    response = await api.delete(
        f"/api/v1/reservations/{reservation_id}",
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (204 if role in MANAGERS else 403)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/reservations", None),
        ("POST", "/api/v1/reservations", {}),
        ("GET", f"/api/v1/reservations/{ABSENT_ID}", None),
        ("PATCH", f"/api/v1/reservations/{ABSENT_ID}", {"adults": 2}),
        ("DELETE", f"/api/v1/reservations/{ABSENT_ID}", None),
    ],
)
@pytest.mark.asyncio
async def test_no_endpoint_is_reachable_without_a_token(api, method, path, body) -> None:
    """Deny by default at the transport level, before any role question."""
    response = await api.request(method, path, json=body)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_forbidden_answer_never_reveals_whether_the_resource_exists(
    api, users_by_role_a, create_payload
) -> None:
    """A `CLEANER` gets the same `403` for a real reservation and for a made-up id.

    If the authorisation check ran after the lookup, the two answers would differ and the
    endpoint would enumerate reservation ids for a role that cannot read them.
    """
    real_id = await _seed_reservation(api, users_by_role_a, create_payload)
    cleaner = auth_header(api, users_by_role_a[UserRole.CLEANER])

    real = await api.get(f"/api/v1/reservations/{real_id}", headers=cleaner)
    invented = await api.get(f"/api/v1/reservations/{uuid.uuid4()}", headers=cleaner)

    assert real.status_code == invented.status_code == 403
    assert real.json() == invented.json()
