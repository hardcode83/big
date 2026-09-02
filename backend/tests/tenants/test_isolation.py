"""R7.9: the tenant endpoints cannot reach another tenant, and why that needs its own test.

`tenant_scoped_classes()` in `app/core/db.py` resolves the tables the global session filter
covers by looking for a `tenant_id` **column**. `tenants` does not have one — it IS the tenant —
so that table is not covered at all, and the filter offers exactly nothing here.

`tenant_configs` does have one and is covered, but as a net, not as the mechanism.

So the comparison of the path id against the token's tenant (design D12) is the only protection
these two endpoints have. That is a different situation from every other endpoint of the change,
and it is why R7.9 exists as a separate criterion.
"""

import uuid

import pytest
from sqlalchemy import text

from app.auth.domain.enums import UserRole
from app.core.db import tenant_scoped_classes
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from tests.auth.conftest import auth_header

OWNER = UserRole.TENANT_OWNER


def test_the_tenants_table_is_not_covered_by_the_global_filter() -> None:
    """The premise of this whole file, asserted rather than assumed.

    If `tenants` ever gains a `tenant_id` column, the filter would start covering it and this
    reasoning would need revisiting — this test is what would say so.
    """
    covered = set(tenant_scoped_classes())

    assert TenantModel not in covered
    assert TenantConfigModel in covered


@pytest.mark.asyncio
async def test_reading_another_tenant_answers_404(
    api, tenant_a, tenant_b, users_by_role_a
) -> None:
    real = await api.get(
        f"/api/v1/tenants/{tenant_b.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )
    invented = await api.get(
        f"/api/v1/tenants/{uuid.uuid4()}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert real.status_code == invented.status_code == 404
    # Indistinguishable: a caller must not learn that another tenant exists by asking.
    assert real.json() == invented.json()


@pytest.mark.asyncio
async def test_patching_another_tenant_answers_404_and_changes_nothing(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_b.id}",
        json={"name": "Hijacked"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 404
    # Raw SQL on purpose: the session is marked with tenant A by now, and this is verifying the
    # row itself rather than what the marked session is willing to show.
    name = (
        await db_session.execute(
            text("SELECT name FROM tenants WHERE id = :id"), {"id": str(tenant_b.id)}
        )
    ).scalar_one()
    assert name == tenant_b.name


@pytest.mark.asyncio
async def test_patching_another_tenants_config_answers_404(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """The row this test proves stays uncreated is the one `insert_tenant` now pre-seeds
    by default (`notification-channel-routing`) — delete it before the check exercises the
    "not even created" invariant, or the count below would be off by one for reasons that
    have nothing to do with the 404 order this test actually pins."""
    from sqlalchemy import delete

    await db_session.execute(
        delete(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_b.id)
    )
    await db_session.flush()

    response = await api.patch(
        f"/api/v1/tenants/{tenant_b.id}",
        json={"config": {"sla_high_minutes": 999}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 404
    rows = (
        await db_session.execute(
            text("SELECT count(*) FROM tenant_configs WHERE tenant_id = :id"),
            {"id": str(tenant_b.id)},
        )
    ).scalar_one()
    # Not even created: the check runs before `get_or_create`.
    assert rows == 0


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.asyncio
async def test_no_role_reaches_the_neighbour_tenant(
    api, tenant_a, tenant_b, users_by_role_a, role
) -> None:
    header = auth_header(api, users_by_role_a[role])

    read = await api.get(f"/api/v1/tenants/{tenant_b.id}", headers=header)
    patched = await api.patch(
        f"/api/v1/tenants/{tenant_b.id}", json={"name": "x"}, headers=header
    )

    assert read.status_code in (403, 404)
    assert patched.status_code in (403, 404)


@pytest.mark.asyncio
async def test_the_token_tenant_wins_over_the_path(api, tenant_a, users_by_role_a) -> None:
    """The positive side of the same rule: your own id works, and only your own."""
    response = await api.get(
        f"/api/v1/tenants/{tenant_a.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(tenant_a.id)


@pytest.mark.asyncio
async def test_a_cross_tenant_patch_is_indistinguishable_from_an_invented_id(
    api, tenant_a, tenant_b, users_by_role_a
) -> None:
    """The body, not just the status code (QA panel of sections 7-8).

    The GET test already compared bodies; PATCH only checked the code and the DB side effects,
    so a future error message that leaked "this tenant exists, but is not yours" would have
    passed.
    """
    header = auth_header(api, users_by_role_a[OWNER])
    body = {"name": "Hijacked"}

    real = await api.patch(f"/api/v1/tenants/{tenant_b.id}", json=body, headers=header)
    invented = await api.patch(f"/api/v1/tenants/{uuid.uuid4()}", json=body, headers=header)

    assert real.status_code == invented.status_code == 404
    assert real.json() == invented.json()
