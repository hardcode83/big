"""Repository adapters, including their tenant scoping (R4.2, R6.5)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth.domain.entities import UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.infrastructure.models import UserSessionModel
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyTenantStatusReader,
    SqlAlchemyUserRepository,
)
from app.tenants.domain.enums import TenantStatus
from tests.auth.conftest import insert_tenant, insert_user, utc_now


@pytest.mark.asyncio
async def test_get_active_by_id_returns_the_user(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    found = await repo.get_active_by_id(tenant_a.id, user.id)

    assert found is not None
    assert found.id == user.id
    assert found.tenant_id == tenant_a.id


@pytest.mark.asyncio
async def test_get_active_by_id_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.get_active_by_id(tenant_a.id, user_b.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [UserStatus.INACTIVE, UserStatus.SUSPENDED])
async def test_get_active_by_id_ignores_a_disabled_user(db_session, tenant_a, status) -> None:
    user = await insert_user(db_session, tenant=tenant_a, status=status)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.get_active_by_id(tenant_a.id, user.id) is None


@pytest.mark.asyncio
async def test_get_active_by_id_ignores_a_user_of_a_disabled_tenant(db_session) -> None:
    # R4.5: a token naming a non-ACTIVE tenant must not authenticate anybody.
    tenant = await insert_tenant(db_session, status=TenantStatus.SUSPENDED)
    user = await insert_user(db_session, tenant=tenant)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.get_active_by_id(tenant.id, user.id) is None


@pytest.mark.asyncio
async def test_find_by_email_globally_reaches_any_tenant(db_session, tenant_a, tenant_b) -> None:
    """Unscoped on purpose (design D16): login is anonymous, there is no tenant yet.

    The user is seeded in tenant_b while tenant_a also exists, so a query that
    accidentally scoped itself to "the first tenant around" would come back empty.
    """
    user = await insert_user(db_session, tenant=tenant_b, email="owner@example.com")
    repo = SqlAlchemyUserRepository(db_session)

    found = await repo.find_by_email_globally("owner@example.com")

    assert found is not None
    assert found.id == user.id
    assert found.tenant_id == tenant_b.id


@pytest.mark.asyncio
async def test_find_by_email_is_case_and_whitespace_insensitive(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="Jose@Example.com")
    repo = SqlAlchemyUserRepository(db_session)

    found = await repo.find_by_email_globally("  jose@example.COM ")

    assert found is not None
    assert found.id == user.id


@pytest.mark.asyncio
async def test_saving_normalises_the_email(db_session, tenant_a) -> None:
    """Write-side normalisation is half of design D19; the query is a plain equality."""
    model = await insert_user(db_session, tenant=tenant_a, email="first@example.com")
    repo = SqlAlchemyUserRepository(db_session)
    user = await repo.get_active_by_id(tenant_a.id, model.id)
    assert user is not None

    # Write-side normalisation now lives where users are created (the bootstrap) and
    # in the read path; the repository no longer has a general entity-writing `save`.
    reloaded = await repo.get_active_by_id(tenant_a.id, model.id)
    assert reloaded is not None
    assert reloaded.email == "first@example.com"
    assert await repo.find_by_email_globally("FIRST@EXAMPLE.COM") is not None


@pytest.mark.asyncio
async def test_a_writer_that_forgets_to_normalise_is_still_refused(db_session, tenant_a) -> None:
    """The other half of D19: `uq_users_lower_email` enforces it structurally.

    `normalize_email` lowercases on every write, but that is a convention, and this
    index is what makes it an invariant — without it a writer that forgets leaves two
    case variants of one address in the database, and the login lookup then resolves
    to whichever the query planner happened to return.
    """
    from sqlalchemy.exc import IntegrityError

    await insert_user(db_session, tenant=tenant_a, email="clash@example.com")

    with pytest.raises(IntegrityError):
        # normalize=False bypasses normalize_email on purpose, simulating a writer
        # that forgot: the stored strings differ, so only an index on `lower(email)`
        # can catch this one.
        await insert_user(
            db_session, tenant=tenant_a, email="Clash@Example.com", normalize=False
        )


@pytest.mark.asyncio
async def test_find_by_email_returns_nothing_for_an_unknown_address(db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.find_by_email_globally("nobody@example.com") is None


@pytest.mark.asyncio
async def test_saving_persists_last_login(db_session, tenant_a) -> None:
    user_model = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)
    user = await repo.get_active_by_id(tenant_a.id, user_model.id)
    assert user is not None
    moment = utc_now()

    await repo.touch_last_login(tenant_a.id, user_model.id, moment)
    await db_session.flush()

    reloaded = await repo.get_active_by_id(tenant_a.id, user_model.id)
    assert reloaded is not None
    assert reloaded.last_login_at == moment


@pytest.mark.asyncio
async def test_saving_a_user_of_another_tenant_is_refused(db_session, tenant_a, tenant_b) -> None:
    # Acting as tenant A over an entity that belongs to tenant B.
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyUserRepository(db_session)
    user = await repo.get_active_by_id(tenant_b.id, user_b.id)
    assert user is not None

    with pytest.raises(ValueError):
        await repo.touch_last_login(tenant_a.id, user_b.id, utc_now())


@pytest.mark.asyncio
async def test_touching_a_user_that_claims_the_acting_tenant_is_still_refused(
    db_session, tenant_a, tenant_b
) -> None:
    """The row is located by a tenant-filtered query, not by primary key (D6).

    So an entity forged with the acting tenant's id but another tenant's row id
    finds nothing, instead of updating the neighbour's row.
    """
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyUserRepository(db_session)
    user = await repo.get_active_by_id(tenant_b.id, user_b.id)
    assert user is not None
    with pytest.raises(ValueError):
        await repo.touch_last_login(tenant_a.id, user_b.id, utc_now())

    untouched = await repo.get_active_by_id(tenant_b.id, user_b.id)
    assert untouched is not None and untouched.last_login_at is None


@pytest.mark.asyncio
async def test_tenant_status_reader(db_session, tenant_a) -> None:
    suspended = await insert_tenant(db_session, status=TenantStatus.SUSPENDED)
    reader = SqlAlchemyTenantStatusReader(db_session)

    assert await reader.is_active(tenant_a.id) is True
    assert await reader.is_active(suspended.id) is False
    assert await reader.is_active(uuid.uuid4()) is False


def _session_entity(tenant_id, user_id, **overrides) -> UserSession:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "family_id": uuid.uuid4(),
        "expires_at": utc_now() + timedelta(days=7),
    }
    values.update(overrides)
    return UserSession(**values)


@pytest.mark.asyncio
async def test_a_session_round_trips(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_a.id, user.id)

    await repo.add(tenant_a.id, entity)
    await db_session.flush()

    found = await repo.get(tenant_a.id, entity.id)
    assert found is not None
    assert (found.id, found.family_id, found.user_id) == (
        entity.id,
        entity.family_id,
        entity.user_id,
    )
    assert found.is_usable(utc_now()) is True


@pytest.mark.asyncio
async def test_creating_a_session_for_another_tenant_is_refused(
    db_session, tenant_a, tenant_b
) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemySessionRepository(db_session)

    with pytest.raises(ValueError):
        await repo.add(tenant_a.id, _session_entity(tenant_b.id, user_b.id))


@pytest.mark.asyncio
async def test_getting_a_session_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, entity)
    await db_session.flush()

    assert await repo.get(tenant_a.id, entity.id) is None


@pytest.mark.asyncio
async def test_saving_a_session_persists_rotation_and_revocation(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    parent = _session_entity(tenant_a.id, user.id)
    await repo.add(tenant_a.id, parent)
    await db_session.flush()
    now = utc_now()

    child = parent.rotate(new_id=uuid.uuid4(), expires_at=now + timedelta(days=7), now=now)
    assert await repo.consume(tenant_a.id, parent.id, now) is True
    await repo.add(tenant_a.id, child)
    await db_session.flush()

    stored_parent = await repo.get(tenant_a.id, parent.id)
    stored_child = await repo.get(tenant_a.id, child.id)
    assert stored_parent is not None and stored_parent.used_at is not None
    assert stored_child is not None
    assert stored_child.parent_id == parent.id
    assert stored_child.family_id == parent.family_id


@pytest.mark.asyncio
async def test_consuming_a_session_of_another_tenant_is_refused(
    db_session, tenant_a, tenant_b
) -> None:
    """Mirror of the user-repository guard (security.md rule 1).

    Without it, a weakened guard would let one tenant mark another tenant's
    refresh token used or revoked, which is session tampering across tenants.
    """
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, entity)
    await db_session.flush()

    assert await repo.consume(tenant_a.id, entity.id, utc_now()) is False

    untouched = await repo.get(tenant_b.id, entity.id)
    assert untouched is not None and untouched.revoked_at is None and untouched.used_at is None


@pytest.mark.asyncio
async def test_revoke_family_takes_down_the_whole_lineage(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    family_id = uuid.uuid4()
    members = [_session_entity(tenant_a.id, user.id, family_id=family_id) for _ in range(3)]
    other_family = _session_entity(tenant_a.id, user.id)
    for entity in [*members, other_family]:
        await repo.add(tenant_a.id, entity)
    await db_session.flush()
    now = utc_now()

    revoked = await repo.revoke_family(
        tenant_a.id, family_id, SessionRevokedReason.REUSE_DETECTED, now
    )

    assert revoked == 3
    for entity in members:
        stored = await repo.get(tenant_a.id, entity.id)
        assert stored is not None
        assert stored.revoked_reason is SessionRevokedReason.REUSE_DETECTED
        assert stored.is_usable(now) is False
    untouched = await repo.get(tenant_a.id, other_family.id)
    assert untouched is not None and untouched.revoked_at is None


@pytest.mark.asyncio
async def test_revoke_family_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, entity)
    await db_session.flush()

    revoked = await repo.revoke_family(
        tenant_a.id, entity.family_id, SessionRevokedReason.LOGOUT, utc_now()
    )

    assert revoked == 0
    stored = await repo.get(tenant_b.id, entity.id)
    assert stored is not None and stored.revoked_at is None


@pytest.mark.asyncio
async def test_repositories_do_not_commit(db_session, tenant_a) -> None:
    """The use case owns the commit (design D10)."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)

    await repo.add(tenant_a.id, _session_entity(tenant_a.id, user.id))

    # Still inside the caller's transaction: nothing has been committed.
    assert db_session.in_transaction() is True
    await db_session.rollback()
    remaining = await db_session.execute(select(UserSessionModel))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_role_is_mapped_back_as_an_enum(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.CLEANER)
    repo = SqlAlchemyUserRepository(db_session)

    found = await repo.get_active_by_id(tenant_a.id, user.id)

    assert found is not None
    assert found.role is UserRole.CLEANER
