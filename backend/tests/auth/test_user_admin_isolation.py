"""Cross-tenant isolation of the user endpoints (R7.1, R7.8).

The blocking R4.3 criterion `auth-tenancy` could not verify: referencing a user that EXISTS
but belongs to another tenant must answer `404` and not `403`, with a body indistinguishable
from an id that never existed. Anything else confirms the existence of a resource to somebody
with no right to know it.

Both tenants are seeded with a user per role, so every assertion here has a real neighbour to
fail to reach — an isolation test with nothing to reach proves nothing.
"""

import uuid

import pytest
from sqlalchemy import select, text

from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from tests.auth.conftest import auth_header

OWNER = UserRole.TENANT_OWNER


async def _row_of(db_session, user_id: uuid.UUID) -> dict:
    """Read a user with raw SQL, bypassing the global tenant filter on purpose.

    Every request in these tests shares ONE session (the `get_db_session` override), so the
    first authenticated call marks it with tenant A and `app/core/db.py` then hides tenant B's
    rows from this session — including from a verification query written here. That is a
    property of the harness, not of production, where each request gets a fresh session.

    Raw SQL is the documented way through: the filter hooks `do_orm_execute`, so it "cubre solo
    SELECT/UPDATE/DELETE del ORM" (limit 1 of its own docstring). Verifying with it is also the
    strictest possible check — it looks at the row itself, with nothing in between.
    """
    result = await db_session.execute(
        text(
            "SELECT role::text AS role, status::text AS status, password_hash "
            "FROM users WHERE id = :id"
        ),
        {"id": str(user_id)},
    )
    return dict(result.mappings().one())


@pytest.mark.asyncio
async def test_reading_a_user_of_another_tenant_answers_404(
    api, users_by_role_a, users_by_role_b
) -> None:
    stranger = users_by_role_b[UserRole.CLEANER]

    real = await api.get(
        f"/api/v1/users/{stranger.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )
    invented = await api.get(
        f"/api/v1/users/{uuid.uuid4()}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert real.status_code == invented.status_code == 404
    assert real.json() == invented.json()


@pytest.mark.asyncio
async def test_patching_a_user_of_another_tenant_answers_404_and_changes_nothing(
    api, db_session, users_by_role_a, users_by_role_b
) -> None:
    stranger = users_by_role_b[UserRole.CLEANER]

    response = await api.patch(
        f"/api/v1/users/{stranger.id}",
        json={"role": UserRole.TENANT_OWNER.value},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 404
    assert (await _row_of(db_session, stranger.id))["role"] == UserRole.CLEANER.value


@pytest.mark.asyncio
async def test_deleting_a_user_of_another_tenant_answers_404_and_changes_nothing(
    api, db_session, users_by_role_a, users_by_role_b
) -> None:
    stranger = users_by_role_b[UserRole.CLEANER]

    response = await api.delete(
        f"/api/v1/users/{stranger.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 404
    assert (await _row_of(db_session, stranger.id))["status"] == UserStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_resetting_the_password_of_another_tenant_answers_404(
    api, db_session, users_by_role_a, users_by_role_b
) -> None:
    stranger = users_by_role_b[UserRole.CLEANER]
    before = (await _row_of(db_session, stranger.id))["password_hash"]

    response = await api.post(
        f"/api/v1/users/{stranger.id}/reset-password",
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 404
    assert (await _row_of(db_session, stranger.id))["password_hash"] == before


@pytest.mark.asyncio
async def test_the_listing_never_shows_another_tenants_users(
    api, users_by_role_a, users_by_role_b
) -> None:
    response = await api.get("/api/v1/users", headers=auth_header(api, users_by_role_a[OWNER]))

    ids = {user["id"] for user in response.json()["data"]}
    assert ids == {str(user.id) for user in users_by_role_a.values()}
    assert not ids & {str(user.id) for user in users_by_role_b.values()}


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.asyncio
async def test_no_role_reaches_the_neighbour_tenant(
    api, users_by_role_a, users_by_role_b, role
) -> None:
    """R7.2 applied to isolation: the five roles, none of them crossing over.

    The two allowed answers are `403` (the role cannot use the endpoint at all) and `404` (it
    can, but the resource is not in its tenant). What must never appear is a `200`.
    """
    stranger = users_by_role_b[UserRole.CLEANER]
    header = auth_header(api, users_by_role_a[role])

    responses = [
        await api.get(f"/api/v1/users/{stranger.id}", headers=header),
        await api.patch(
            f"/api/v1/users/{stranger.id}", json={"name": "x"}, headers=header
        ),
        await api.delete(f"/api/v1/users/{stranger.id}", headers=header),
        await api.post(f"/api/v1/users/{stranger.id}/reset-password", headers=header),
    ]

    assert all(response.status_code in (403, 404) for response in responses), [
        response.status_code for response in responses
    ]


@pytest.mark.asyncio
async def test_a_created_user_belongs_to_the_token_tenant(
    api, db_session, users_by_role_a, tenant_a
) -> None:
    """R1.3: the tenant comes from the token, and there is no way to say otherwise."""
    response = await api.post(
        "/api/v1/users",
        json={
            "name": "Nueva",
            "email": f"nueva-{uuid.uuid4().hex[:8]}@example.com",
            "role": UserRole.CLEANER.value,
        },
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 201
    row = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == uuid.UUID(response.json()["user"]["id"]))
        )
    ).scalar_one()
    assert row.tenant_id == tenant_a.id


@pytest.mark.asyncio
async def test_the_audit_row_is_written_under_the_acting_tenant(
    api, db_session, users_by_role_a, tenant_a
) -> None:
    """R7.8: the audit INSERT is not covered by the session filter, only by its own guard."""
    await api.patch(
        f"/api/v1/users/{users_by_role_a[UserRole.CLEANER].id}",
        json={"name": "Ana Ruiz"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    rows = (await db_session.execute(select(AuditLogModel))).scalars().all()

    assert rows
    assert {row.tenant_id for row in rows} == {tenant_a.id}
