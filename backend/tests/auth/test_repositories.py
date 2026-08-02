"""Repository adapters, including their tenant scoping (R4.2, R6.5)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth.domain.entities import User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import EmailAlreadyExistsError
from app.auth.domain.repositories import MAX_PAGE, MAX_PER_PAGE, UserFilters
from app.auth.domain.value_objects import normalize_email
from app.core.tenancy import CrossTenantWriteError
from app.auth.infrastructure.models import UserModel, UserSessionModel
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


@pytest.mark.asyncio
async def test_revoke_all_for_user_reaches_every_family(db_session, tenant_a) -> None:
    """user-management R3.7/R4.2: an administrator kills sessions they cannot enumerate.

    `revoke_family` cannot express this — the caller has a `user_id`, not the
    `family_id`s of somebody else's logins across devices.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    other_user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    families = [_session_entity(tenant_a.id, user.id) for _ in range(3)]
    someone_else = _session_entity(tenant_a.id, other_user.id)
    for entity in [*families, someone_else]:
        await repo.add(tenant_a.id, entity)
    await db_session.flush()
    now = utc_now()

    revoked = await repo.revoke_all_for_user(
        tenant_a.id, user.id, SessionRevokedReason.USER_DEACTIVATED, now
    )

    assert revoked == 3
    for entity in families:
        stored = await repo.get(tenant_a.id, entity.id)
        assert stored is not None
        assert stored.revoked_reason is SessionRevokedReason.USER_DEACTIVATED
        assert stored.is_usable(now) is False
    untouched = await repo.get(tenant_a.id, someone_else.id)
    assert untouched is not None and untouched.revoked_at is None


@pytest.mark.asyncio
async def test_revoke_all_for_user_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    """`user_id` is globally unique, so only the tenant clause stops this crossing over."""
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, entity)
    await db_session.flush()

    revoked = await repo.revoke_all_for_user(
        tenant_a.id, user_b.id, SessionRevokedReason.USER_DEACTIVATED, utc_now()
    )

    assert revoked == 0
    stored = await repo.get(tenant_b.id, entity.id)
    assert stored is not None and stored.revoked_at is None


@pytest.mark.asyncio
async def test_revoke_all_for_user_is_idempotent(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_a.id, user.id)
    await repo.add(tenant_a.id, entity)
    await db_session.flush()

    first = await repo.revoke_all_for_user(
        tenant_a.id, user.id, SessionRevokedReason.PASSWORD_RESET, utc_now()
    )
    second = await repo.revoke_all_for_user(
        tenant_a.id, user.id, SessionRevokedReason.USER_DEACTIVATED, utc_now()
    )

    assert (first, second) == (1, 0)
    stored = await repo.get(tenant_a.id, entity.id)
    assert stored is not None
    # The first reason survives: a later administrative action did not cause this
    # revocation and must not relabel it.
    assert stored.revoked_reason is SessionRevokedReason.PASSWORD_RESET


@pytest.mark.asyncio
async def test_revoke_all_for_user_leaves_an_earlier_logout_labelled_as_such(
    db_session, tenant_a
) -> None:
    """A session the user closed themselves keeps `LOGOUT`, not `USER_DEACTIVATED`."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    logged_out = _session_entity(tenant_a.id, user.id)
    still_open = _session_entity(tenant_a.id, user.id)
    for entity in (logged_out, still_open):
        await repo.add(tenant_a.id, entity)
    await db_session.flush()
    await repo.revoke_family(
        tenant_a.id, logged_out.family_id, SessionRevokedReason.LOGOUT, utc_now()
    )

    revoked = await repo.revoke_all_for_user(
        tenant_a.id, user.id, SessionRevokedReason.USER_DEACTIVATED, utc_now()
    )

    assert revoked == 1
    first = await repo.get(tenant_a.id, logged_out.id)
    second = await repo.get(tenant_a.id, still_open.id)
    assert first is not None and first.revoked_reason is SessionRevokedReason.LOGOUT
    assert second is not None
    assert second.revoked_reason is SessionRevokedReason.USER_DEACTIVATED


@pytest.mark.asyncio
async def test_revoke_all_for_user_does_not_commit(db_session, tenant_a) -> None:
    """Deactivation and its audit row must roll back together (R6.4)."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemySessionRepository(db_session)
    entity = _session_entity(tenant_a.id, user.id)
    await repo.add(tenant_a.id, entity)
    await db_session.flush()

    await repo.revoke_all_for_user(
        tenant_a.id, user.id, SessionRevokedReason.USER_DEACTIVATED, utc_now()
    )
    await db_session.rollback()

    stored = (
        await db_session.execute(
            select(UserSessionModel).where(UserSessionModel.id == entity.id)
        )
    ).scalar_one_or_none()
    assert stored is None


def test_no_unconditional_write_primitive_came_back() -> None:
    """Regression guard for the two methods 11.9 removed (design D5, R2.1).

    `SessionRepository.save` and `UserRepository.save` were deleted for two different
    reasons: the session one wrote `used_at`/`revoked_at` without checking them, which is
    the read-then-write race of R2.1 sitting next to the safe `consume()`; and the user
    one copied the whole row back, so it could revert a suspension committed mid-request.

    The PR #25 review asked to confirm no consumer of them remains. Absence of callers
    cannot be proven by a test — that is what the grep and the review are for — but their
    ABSENCE FROM THE SURFACE can, and that is the part that decays: the next person
    needing to mark a session used would find a `save` and use it. If either name comes
    back, this fails and the reason is one paragraph up.
    """
    forbidden = "save"
    assert not hasattr(SqlAlchemySessionRepository, forbidden), (
        "SqlAlchemySessionRepository.save is back — every mutation must stay conditional "
        "(consume) or set-based (revoke_family)"
    )
    assert not hasattr(SqlAlchemyUserRepository, forbidden), (
        "SqlAlchemyUserRepository.save is back — writing the whole row can revert a "
        "concurrent status, role or password change; use touch_last_login"
    )


# --- user administration adapter (user-management R1, R2, R3, R7) -------------------


def _domain_user(tenant_id, *, name="Ana", role=UserRole.CLEANER, email=None) -> User:
    return User.create(
        tenant_id=tenant_id,
        name=name,
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        role=role,
        now=utc_now(),
    )


@pytest.mark.asyncio
async def test_get_returns_a_user_whatever_its_status(db_session, tenant_a) -> None:
    """Administration must see a suspended account to be able to reactivate it (R2.6)."""
    suspended = await insert_user(db_session, tenant=tenant_a, status=UserStatus.SUSPENDED)
    repo = SqlAlchemyUserRepository(db_session)

    found = await repo.get(tenant_a.id, suspended.id)

    assert found is not None and found.status is UserStatus.SUSPENDED
    # The authentication lookup still refuses it, which is the difference between the two.
    assert await repo.get_active_by_id(tenant_a.id, suspended.id) is None


@pytest.mark.asyncio
async def test_get_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    """R7.1: indistinguishable from "does not exist", which is what makes the 404 honest."""
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.get(tenant_a.id, user_b.id) is None
    assert await repo.get(tenant_a.id, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_add_persists_a_user(db_session, tenant_a) -> None:
    repo = SqlAlchemyUserRepository(db_session)
    user = _domain_user(tenant_a.id)

    await repo.add(tenant_a.id, user)

    stored = await repo.get(tenant_a.id, user.id)
    assert stored is not None and stored.email == user.email


@pytest.mark.asyncio
async def test_add_refuses_a_user_of_another_tenant(db_session, tenant_a, tenant_b) -> None:
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repo.add(tenant_a.id, _domain_user(tenant_b.id))


@pytest.mark.asyncio
async def test_add_translates_a_duplicate_address_to_its_own_error(db_session, tenant_a) -> None:
    repo = SqlAlchemyUserRepository(db_session)
    existing = await insert_user(db_session, tenant=tenant_a, email="ana@example.com")

    with pytest.raises(EmailAlreadyExistsError) as caught:
        await repo.add(tenant_a.id, _domain_user(tenant_a.id, email="ana@example.com"))

    assert existing.email == "ana@example.com"
    # The message must not name the tenant the address belongs to (R1.4).
    assert "tenant" not in str(caught.value).lower()


@pytest.mark.asyncio
async def test_add_refuses_an_address_taken_in_another_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    """Uniqueness is global since ADR 0005, so this is a `409` and not a silent success."""
    await insert_user(db_session, tenant=tenant_b, email="shared@example.com")
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(EmailAlreadyExistsError):
        await repo.add(tenant_a.id, _domain_user(tenant_a.id, email="shared@example.com"))


@pytest.mark.asyncio
async def test_add_refuses_an_address_that_differs_only_in_case(db_session, tenant_a) -> None:
    """The index is on `lower(email)` (design D19), so this must not create a twin."""
    await insert_user(db_session, tenant=tenant_a, email="ana@example.com")
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(EmailAlreadyExistsError):
        await repo.add(
            tenant_a.id, _domain_user(tenant_a.id, email=normalize_email("ANA@Example.COM"))
        )


@pytest.mark.asyncio
async def test_apply_changes_writes_only_the_named_columns(db_session, tenant_a) -> None:
    """The whole point of design D21: an unnamed column is not touched."""
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.CLEANER)
    repo = SqlAlchemyUserRepository(db_session)

    await repo.apply_changes(tenant_a.id, user.id, {"name": "Ana Ruiz"})

    stored = await repo.get(tenant_a.id, user.id)
    assert stored is not None
    assert stored.name == "Ana Ruiz"
    assert stored.role is UserRole.CLEANER


@pytest.mark.asyncio
async def test_apply_changes_cannot_revert_a_concurrent_column(db_session, tenant_a) -> None:
    """The regression `auth-tenancy` deleted `save` to prevent (its design D5, D21 here).

    A profile write issued after a suspension must not resurrect the account, which is
    exactly what copying a whole entity read before the suspension would do.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)
    await repo.apply_changes(tenant_a.id, user.id, {"status": UserStatus.SUSPENDED})

    await repo.apply_changes(tenant_a.id, user.id, {"name": "Ana Ruiz"})

    stored = await repo.get(tenant_a.id, user.id)
    assert stored is not None
    assert stored.status is UserStatus.SUSPENDED
    assert stored.name == "Ana Ruiz"


@pytest.mark.asyncio
async def test_apply_changes_will_not_cross_tenants(db_session, tenant_a, tenant_b) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b, role=UserRole.CLEANER)
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(ValueError):
        await repo.apply_changes(tenant_a.id, user_b.id, {"role": UserRole.TENANT_OWNER})

    stored = await repo.get(tenant_b.id, user_b.id)
    assert stored is not None and stored.role is UserRole.CLEANER


@pytest.mark.asyncio
async def test_apply_changes_refuses_identity_columns(db_session, tenant_a, tenant_b) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    for values in (
        {"tenant_id": tenant_b.id},
        {"id": uuid.uuid4()},
        {"last_login_at": utc_now()},
        {"created_at": utc_now()},
    ):
        with pytest.raises(ValueError):
            await repo.apply_changes(tenant_a.id, user.id, values)


@pytest.mark.asyncio
async def test_apply_changes_refuses_an_unknown_column(db_session, tenant_a) -> None:
    """A typo must fail loudly rather than write nothing and report success."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(ValueError):
        await repo.apply_changes(tenant_a.id, user.id, {"nmae": "Ana"})


@pytest.mark.asyncio
async def test_apply_changes_translates_a_duplicate_address(db_session, tenant_a) -> None:
    await insert_user(db_session, tenant=tenant_a, email="taken@example.com")
    user = await insert_user(db_session, tenant=tenant_a, email="mine@example.com")
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(EmailAlreadyExistsError):
        await repo.apply_changes(tenant_a.id, user.id, {"email": "taken@example.com"})


@pytest.mark.asyncio
async def test_apply_changes_with_nothing_to_write_is_a_no_op(db_session, tenant_a) -> None:
    """Design D15: a PATCH that changes nothing must not even reach the database."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    await repo.apply_changes(tenant_a.id, user.id, {})

    assert await repo.get(tenant_a.id, user.id) is not None


@pytest.mark.asyncio
async def test_the_listing_is_ordered_by_name_with_a_stable_tiebreaker(
    db_session, tenant_a
) -> None:
    """Two users with the same name must not swap places between pages (design D17)."""
    repo = SqlAlchemyUserRepository(db_session)
    for name in ("Zoe", "Ana", "Ana", "Marta"):
        await repo.add(tenant_a.id, _domain_user(tenant_a.id, name=name))

    page = await repo.list(tenant_a.id, UserFilters(), page=1, per_page=10)

    assert [user.name for user in page.items] == ["Ana", "Ana", "Marta", "Zoe"]
    ana_ids = [user.id for user in page.items if user.name == "Ana"]
    assert ana_ids == sorted(ana_ids)


@pytest.mark.asyncio
async def test_paginating_neither_repeats_nor_skips_a_row(db_session, tenant_a) -> None:
    repo = SqlAlchemyUserRepository(db_session)
    for index in range(7):
        await repo.add(tenant_a.id, _domain_user(tenant_a.id, name=f"user-{index:02d}"))

    first = await repo.list(tenant_a.id, UserFilters(), page=1, per_page=3)
    second = await repo.list(tenant_a.id, UserFilters(), page=2, per_page=3)
    third = await repo.list(tenant_a.id, UserFilters(), page=3, per_page=3)

    seen = [user.id for user in (*first.items, *second.items, *third.items)]
    assert len(seen) == len(set(seen)) == 7
    assert first.total == second.total == third.total == 7


@pytest.mark.asyncio
async def test_the_listing_only_sees_its_own_tenant(db_session, tenant_a, tenant_b) -> None:
    repo = SqlAlchemyUserRepository(db_session)
    await repo.add(tenant_a.id, _domain_user(tenant_a.id, name="Mine"))
    await repo.add(tenant_b.id, _domain_user(tenant_b.id, name="Theirs"))

    page = await repo.list(tenant_a.id, UserFilters(), page=1, per_page=10)

    assert [user.name for user in page.items] == ["Mine"]
    assert page.total == 1


@pytest.mark.asyncio
async def test_the_listing_filters_by_role_and_by_status(db_session, tenant_a) -> None:
    repo = SqlAlchemyUserRepository(db_session)
    await repo.add(tenant_a.id, _domain_user(tenant_a.id, role=UserRole.CLEANER))
    await repo.add(tenant_a.id, _domain_user(tenant_a.id, role=UserRole.TECHNICIAN))
    suspended = _domain_user(tenant_a.id, role=UserRole.CLEANER)
    await repo.add(tenant_a.id, suspended)
    await repo.apply_changes(tenant_a.id, suspended.id, {"status": UserStatus.SUSPENDED})

    by_role = await repo.list(
        tenant_a.id, UserFilters(role=UserRole.CLEANER), page=1, per_page=10
    )
    by_status = await repo.list(
        tenant_a.id, UserFilters(status=UserStatus.SUSPENDED), page=1, per_page=10
    )
    both = await repo.list(
        tenant_a.id,
        UserFilters(role=UserRole.TECHNICIAN, status=UserStatus.SUSPENDED),
        page=1,
        per_page=10,
    )

    assert by_role.total == 2
    assert by_status.total == 1
    assert both.total == 0  # filters combine with AND


@pytest.mark.asyncio
async def test_the_listing_rejects_pagination_outside_its_bounds(db_session, tenant_a) -> None:
    """`page` becomes a SQL OFFSET; unbounded it overflows int8 at the driver (R2.2)."""
    repo = SqlAlchemyUserRepository(db_session)

    for page, per_page in ((0, 20), (MAX_PAGE + 1, 20), (1, 0), (1, MAX_PER_PAGE + 1)):
        with pytest.raises(ValueError):
            await repo.list(tenant_a.id, UserFilters(), page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_counting_active_owners_excludes_the_target(db_session, tenant_a) -> None:
    """Otherwise the target counts as the owner surviving its own demotion (R3.6)."""
    owner = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.count_active_owners_excluding(tenant_a.id, owner.id) == 0

    second = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)
    assert await repo.count_active_owners_excluding(tenant_a.id, owner.id) == 1
    assert await repo.count_active_owners_excluding(tenant_a.id, second.id) == 1


@pytest.mark.asyncio
async def test_counting_active_owners_ignores_inactive_ones_and_other_tenants(
    db_session, tenant_a, tenant_b
) -> None:
    target = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)
    await insert_user(
        db_session,
        tenant=tenant_a,
        role=UserRole.TENANT_OWNER,
        status=UserStatus.SUSPENDED,
    )
    await insert_user(db_session, tenant=tenant_b, role=UserRole.TENANT_OWNER)
    repo = SqlAlchemyUserRepository(db_session)

    assert await repo.count_active_owners_excluding(tenant_a.id, target.id) == 0


@pytest.mark.asyncio
async def test_locking_the_tenant_does_not_fail_on_a_real_tenant(db_session, tenant_a) -> None:
    """The lock itself; the concurrency it buys is proved in test_last_owner_concurrency.py."""
    repo = SqlAlchemyUserRepository(db_session)

    await repo.lock_tenant_for_admin(tenant_a.id)

    assert await repo.count_active_owners_excluding(tenant_a.id, uuid.uuid4()) >= 0


@pytest.mark.asyncio
async def test_no_administration_method_commits(db_session, tenant_a) -> None:
    """A user and its audit row must roll back together (R6.4)."""
    repo = SqlAlchemyUserRepository(db_session)
    user = _domain_user(tenant_a.id)
    await repo.add(tenant_a.id, user)
    await repo.apply_changes(tenant_a.id, user.id, {"name": "Ana Ruiz"})

    await db_session.rollback()

    assert (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one_or_none() is None
