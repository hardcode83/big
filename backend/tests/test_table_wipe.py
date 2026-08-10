"""The wipe that replaced `create_all`/`drop_all` must not be short (R3.1, R3.2, design D2).

Dropping the schema between tests could not leave anything behind. Emptying rows can — a
table missing from the statement would leak into the next test, and the leak would look
like an unrelated failure somewhere else. Two properties close that: the statement really
empties a child row whose parent it also deletes, and its table list is exactly the
metadata's.
"""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.core.db import Base
from app.tenants.infrastructure.models import TenantModel
from tests.conftest import _WIPE_EVERY_TABLE


@pytest.mark.asyncio
async def test_the_wipe_empties_a_child_table_as_well_as_its_parent(test_engine) -> None:
    tenant_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        session.add(TenantModel(id=tenant_id, name="wipe-me", billing_email="ops@example.com"))
        await session.flush()
        session.add(
            UserModel(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name="Wipe Me",
                email=f"{uuid.uuid4().hex}@example.com",
                password_hash="x",
                role=UserRole.TENANT_OWNER,
            )
        )
        await session.commit()

    async with test_engine.begin() as conn:
        await conn.execute(text(_WIPE_EVERY_TABLE))

    async with AsyncSession(test_engine) as verify:
        assert await verify.scalar(select(func.count()).select_from(TenantModel)) == 0
        assert await verify.scalar(select(func.count()).select_from(UserModel)) == 0


def test_the_wipe_covers_every_table_the_metadata_declares() -> None:
    """The guarantee that a new table joins the wipe on its own, without anyone remembering."""
    declared = {table.name for table in Base.metadata.sorted_tables}

    assert [name for name in declared if f'DELETE FROM "{name}"' not in _WIPE_EVERY_TABLE] == []
    assert _WIPE_EVERY_TABLE.count("DELETE FROM") == len(declared)
