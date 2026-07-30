"""The global tenant filter: defence in depth, not the primary mechanism (R4.2, D16).

Explicit `tenant_id` parameters in every repository method are the authoritative
scoping (design D6). These tests prove the net underneath them: a query that
FORGOT its filter still cannot see another tenant's rows.
"""

import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.models import UserModel
from app.core.db import (
    TENANT_ID_SESSION_KEY,
    bind_session_to_tenant,
    tenant_scoped_classes,
)
from tests.auth.conftest import insert_tenant, insert_user


@pytest.mark.asyncio
async def test_the_registry_scan_finds_the_tenant_scoped_entities() -> None:
    names = {entity.__tablename__ for entity in tenant_scoped_classes()}

    # Guards against the scan silently matching nothing, which would make every
    # test below pass for the wrong reason.
    assert {"users", "user_sessions", "properties", "reservations"} <= names
    # `tenants` itself is not tenant-scoped: it has no tenant_id column.
    assert "tenants" not in names


@pytest.mark.asyncio
async def test_an_unfiltered_select_cannot_see_another_tenant(db_session: AsyncSession) -> None:
    tenant_a = await insert_tenant(db_session, name="filter-a")
    tenant_b = await insert_tenant(db_session, name="filter-b")
    user_a = await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)

    # Deliberately no WHERE tenant_id — this is the mistake being caught.
    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert [user.id for user in found] == [user_a.id]


@pytest.mark.asyncio
async def test_an_unmarked_session_is_not_filtered(db_session: AsyncSession) -> None:
    """Login depends on this: find_by_email_across_tenants has no tenant yet (D16)."""
    tenant_a = await insert_tenant(db_session, name="unmarked-a")
    tenant_b = await insert_tenant(db_session, name="unmarked-b")
    await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    assert TENANT_ID_SESSION_KEY not in db_session.info

    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert len(found) == 2


@pytest.mark.asyncio
async def test_get_by_primary_key_is_filtered(db_session: AsyncSession) -> None:
    # `session.get()` is a path the net must cover too, not just select(). Note the
    # expunge_all() below is load-bearing: get() can answer from the identity map
    # without emitting SQL, and then no listener runs at all — the fourth documented
    # limit of the filter.
    tenant_a = await insert_tenant(db_session, name="get-a")
    tenant_b = await insert_tenant(db_session, name="get-b")
    user_b = await insert_user(db_session, tenant=tenant_b)
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_a.id)

    assert await db_session.get(UserModel, user_b.id) is None


@pytest.mark.asyncio
async def test_an_unfiltered_orm_update_cannot_touch_another_tenant(
    db_session: AsyncSession,
) -> None:
    tenant_a = await insert_tenant(db_session, name="update-a")
    tenant_b = await insert_tenant(db_session, name="update-b")
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)
    result = await db_session.execute(update(UserModel).values(name="rewritten"))

    assert result.rowcount == 1
    db_session.expunge_all()
    db_session.info.pop(TENANT_ID_SESSION_KEY)
    rows = {
        row.id: row.name for row in (await db_session.execute(select(UserModel))).scalars().all()
    }
    assert rows[user_a.id] == "rewritten"
    assert rows[user_b.id] != "rewritten"


@pytest.mark.asyncio
async def test_the_filter_follows_the_marked_tenant(db_session: AsyncSession) -> None:
    tenant_a = await insert_tenant(db_session, name="switch-a")
    tenant_b = await insert_tenant(db_session, name="switch-b")
    await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_b.id)
    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert [user.id for user in found] == [user_b.id]


@pytest.mark.asyncio
async def test_a_query_for_an_unrelated_entity_still_works(db_session: AsyncSession) -> None:
    # `tenants` has no tenant_id, so the filter must not accidentally constrain it.
    tenant_a = await insert_tenant(db_session, name="unrelated-a")
    await insert_tenant(db_session, name="unrelated-b")
    from app.tenants.infrastructure.models import TenantModel

    bind_session_to_tenant(db_session, tenant_a.id)

    found = (await db_session.execute(select(TenantModel))).scalars().all()

    assert len(found) == 2


@pytest.mark.asyncio
async def test_raw_sql_is_documented_as_not_covered(db_session: AsyncSession) -> None:
    """Pins the first documented limit of D16 so nobody assumes more than there is."""
    from sqlalchemy import text

    tenant_a = await insert_tenant(db_session, name="raw-a")
    tenant_b = await insert_tenant(db_session, name="raw-b")
    await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)
    count = await db_session.scalar(text("SELECT count(*) FROM users"))

    # Not a bug: a textual statement never goes through the ORM criteria. This is
    # exactly why explicit scoping (D6) stays the authoritative mechanism.
    assert count == 2


@pytest.mark.asyncio
async def test_binding_rejects_nothing_and_is_idempotent(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()

    bind_session_to_tenant(db_session, tenant_id)
    bind_session_to_tenant(db_session, tenant_id)

    assert db_session.info[TENANT_ID_SESSION_KEY] == tenant_id
