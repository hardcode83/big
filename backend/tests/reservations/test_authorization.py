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
from app.core.db import TENANT_ID_SESSION_KEY
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


async def _seed_reservation(api, users_by_role_a, create_payload, db_session) -> str:
    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 201
    # `super-admin-identity` R1.1: seeding marks `db_session` (shared across this test's
    # simulated requests) to tenant A. A real request never sees that — `get_db_session`
    # hands out a fresh session per request — so unmark here to match, or a `SUPER_ADMIN`
    # check right after (`tenant_id IS NULL`) gets silently hidden by the stale tenant A
    # filter instead of correctly resolving to its own tenantless row.
    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
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
    api, db_session, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload, db_session)

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
    api, db_session, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload, db_session)

    response = await api.patch(
        f"/api/v1/reservations/{reservation_id}",
        json={"adults": 3},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_cancelling_is_allowed_for_managers_only(
    api, db_session, users_by_role_a, create_payload, role: UserRole
) -> None:
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload, db_session)

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
    api, db_session, users_by_role_a, create_payload
) -> None:
    """A `CLEANER` gets the same `403` for a real reservation and for a made-up id.

    If the authorisation check ran after the lookup, the two answers would differ and the
    endpoint would enumerate reservation ids for a role that cannot read them.
    """
    real_id = await _seed_reservation(api, users_by_role_a, create_payload, db_session)
    cleaner = auth_header(api, users_by_role_a[UserRole.CLEANER])

    real = await api.get(f"/api/v1/reservations/{real_id}", headers=cleaner)
    invented = await api.get(f"/api/v1/reservations/{uuid.uuid4()}", headers=cleaner)

    assert real.status_code == invented.status_code == 403
    assert real.json() == invented.json()


@pytest.mark.asyncio
async def test_the_new_derived_fields_do_not_relax_the_role_gate(
    api, db_session, users_by_role_a, create_payload
) -> None:
    """R6.3 / tasks 3.3: a `CLEANER` and a missing token get the same `403` / `401`
    on the listing and detail endpoints even though the response schema now carries
    `property_name`, `property_internal_code`, and `guest_full_name`.

    A future regression that hid the new fields behind a stricter permission would
    either pass this test (gate still works) or fail it (gate leaked); the test that
    *promised* to assert the body shape with the new fields is this one.
    """
    reservation_id = await _seed_reservation(api, users_by_role_a, create_payload, db_session)

    # 1. CLEANER (no READ_RESERVATIONS) — still 403 on listing and detail.
    cleaner = auth_header(api, users_by_role_a[UserRole.CLEANER])
    listing = await api.get("/api/v1/reservations", headers=cleaner)
    detail = await api.get(f"/api/v1/reservations/{reservation_id}", headers=cleaner)
    assert listing.status_code == 403
    assert detail.status_code == 403
    # The 403 envelope is the standard error envelope, not the derived-fields response.
    listing_body = listing.json()
    detail_body = detail.json()
    assert set(listing_body) == {"error"}
    assert listing_body["error"]["code"] == "FORBIDDEN"
    assert set(detail_body) == {"error"}
    assert detail_body["error"]["code"] == "FORBIDDEN"

    # 2. Missing token — still 401 on both endpoints.
    listing_no_auth = await api.get("/api/v1/reservations")
    detail_no_auth = await api.get(f"/api/v1/reservations/{reservation_id}")
    assert listing_no_auth.status_code == 401
    assert detail_no_auth.status_code == 401

    # 3. A reader's response actually carries the new fields — guards against a
    # future `from_domain` regression that would silently strip them.
    reader = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    body = (await api.get("/api/v1/reservations", headers=reader)).json()
    assert body["data"], "the seeded reservation should appear in the listing"
    [row] = body["data"]
    assert row["id"] == reservation_id
    assert row["property_name"] == "Redes 11"
    assert row["property_internal_code"] == "REDES11"
    assert "guest_full_name" in row  # key present even when the seed has no guest
    assert row["guest_full_name"] is None  # null-with-key, not absent
