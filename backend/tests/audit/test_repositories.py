"""Integration tests for the audit log adapter (R6.4, R7.8).

Against real Postgres, because what is being checked is what the JSONB column accepts and
what the tenant guard refuses — neither is observable with a fake.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from tests.auth.conftest import insert_tenant, insert_user


def utc_now() -> datetime:
    return datetime.now(UTC)


# Sentinel, not `changes or <default>`: an EMPTY ChangeSet is falsy on purpose (design
# D15), so `or` would silently replace exactly the value one of these tests needs to pass in.
_UNSET = object()


def _entry(tenant_id, *, actor_user_id=None, changes=_UNSET, entity_id=None):
    return AuditLogFactory.build(
        tenant_id=tenant_id,
        action=actions.USER_ROLE_CHANGED,
        entity_type=actions.ENTITY_USER,
        entity_id=entity_id or uuid.uuid4(),
        actor_user_id=actor_user_id,
        actor_ip="203.0.113.9",
        changes=(
            ChangeSet(actions.ENTITY_USER).diff("role", "CLEANER", "TECHNICIAN") if changes is _UNSET else changes
        ),
        now=utc_now(),
    )


@pytest.mark.asyncio
async def test_it_appends_an_entry_with_its_json_diff(db_session) -> None:
    tenant = await insert_tenant(db_session)
    actor = await insert_user(db_session, tenant=tenant)
    repository = SqlAlchemyAuditLogRepository(db_session)

    await repository.add(tenant.id, _entry(tenant.id, actor_user_id=actor.id))
    await db_session.flush()

    stored = (await db_session.execute(select(AuditLogModel))).scalar_one()
    assert stored.tenant_id == tenant.id
    assert stored.actor_user_id == actor.id
    assert stored.action == actions.USER_ROLE_CHANGED
    assert stored.entity_type == actions.ENTITY_USER
    assert stored.changes == {"role": {"old": "CLEANER", "new": "TECHNICIAN"}}


@pytest.mark.asyncio
async def test_it_stores_a_redacted_diff_without_any_value(db_session) -> None:
    tenant = await insert_tenant(db_session)
    repository = SqlAlchemyAuditLogRepository(db_session)

    await repository.add(
        tenant.id, _entry(tenant.id, changes=ChangeSet(actions.ENTITY_USER).redacted("password"))
    )
    await db_session.flush()

    stored = (await db_session.execute(select(AuditLogModel))).scalar_one()
    assert stored.changes == {"password": {"changed": True}}


@pytest.mark.asyncio
async def test_it_refuses_an_entry_of_another_tenant(db_session) -> None:
    """The session filter does not cover INSERTs, so this guard is the only one."""
    tenant_a = await insert_tenant(db_session, name="a")
    tenant_b = await insert_tenant(db_session, name="b")
    repository = SqlAlchemyAuditLogRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repository.add(tenant_a.id, _entry(tenant_b.id))


@pytest.mark.asyncio
async def test_it_does_not_commit(db_session) -> None:
    """The use case owns the transaction: an audit row must roll back with its mutation."""
    tenant = await insert_tenant(db_session)
    repository = SqlAlchemyAuditLogRepository(db_session)

    await repository.add(tenant.id, _entry(tenant.id))
    await db_session.rollback()

    assert (await db_session.execute(select(AuditLogModel))).first() is None


@pytest.mark.asyncio
async def test_a_null_diff_is_stored_as_null(db_session) -> None:
    tenant = await insert_tenant(db_session)
    repository = SqlAlchemyAuditLogRepository(db_session)

    await repository.add(tenant.id, _entry(tenant.id, changes=ChangeSet(actions.ENTITY_USER)))
    await db_session.flush()

    stored = (await db_session.execute(select(AuditLogModel))).scalar_one()
    assert stored.changes is None


@pytest.mark.asyncio
async def test_it_refuses_a_cleartext_guest_token_as_the_actor(db_session) -> None:
    """`guest-portal-api` R1.2/R6.4, guarded at the write boundary.

    Re-checked here rather than trusted to `AuditLogFactory` for the same reason the
    cross-tenant guard above lives here: `AuditLog` is a plain mutable dataclass, so a
    caller can build one without the factory or mutate the field afterwards — which is what
    this test does. The column also carries a CHECK; this guard exists to name the field
    instead of dying at the driver with an error that identifies nothing.
    """
    tenant = await insert_tenant(db_session)
    repository = SqlAlchemyAuditLogRepository(db_session)
    entry = _entry(tenant.id)
    entry.actor_guest_token_hash = generate_guest_token()

    with pytest.raises(AuditContractError, match="SHA-256"):
        await repository.add(tenant.id, entry)


@pytest.mark.asyncio
async def test_it_stores_a_guest_token_digest_as_the_actor(db_session) -> None:
    """The positive half, so the guard cannot pass by refusing everything (R6.1)."""
    tenant = await insert_tenant(db_session)
    repository = SqlAlchemyAuditLogRepository(db_session)
    digest = hash_guest_token("a-portal-token")
    entry = _entry(tenant.id)
    entry.actor_guest_token_hash = digest

    await repository.add(tenant.id, entry)
    await db_session.flush()

    stored = (await db_session.execute(select(AuditLogModel))).scalar_one()
    assert stored.actor_guest_token_hash == digest
    assert stored.actor_user_id is None


@pytest.mark.asyncio
async def test_entries_of_two_tenants_stay_separate(db_session) -> None:
    tenant_a = await insert_tenant(db_session, name="a")
    tenant_b = await insert_tenant(db_session, name="b")
    repository = SqlAlchemyAuditLogRepository(db_session)

    await repository.add(tenant_a.id, _entry(tenant_a.id))
    await repository.add(tenant_b.id, _entry(tenant_b.id))
    await db_session.flush()

    rows = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert {row.tenant_id for row in rows} == {tenant_a.id, tenant_b.id}
