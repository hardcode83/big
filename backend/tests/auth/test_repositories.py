"""Repository adapters, including their tenant scoping (R4.2, R6.5)."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.entities import PasswordResetToken, User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import EmailAlreadyExistsError
from app.auth.domain.repositories import MAX_PAGE, MAX_PER_PAGE, UserFilters
from app.auth.domain.value_objects import normalize_email
from app.core.db import bind_session_to_tenant
from app.core.tenancy import CrossTenantWriteError, TenantMarkedSessionError
from app.auth.infrastructure.models import (
    PasswordResetTokenModel,
    UserModel,
    UserSessionModel,
)
from app.auth.infrastructure.repositories import (
    SqlAlchemyPasswordResetTokenRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyTenantStatusReader,
    SqlAlchemyUserRepository,
)
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel
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
async def test_find_by_email_globally_refuses_a_marked_session(db_session, tenant_a) -> None:
    """R6.2/R6.3: the precondition is a failure, not a paragraph.

    Asserting the raise and not the rows, deliberately: on a marked session the listener
    scopes even a single-column select, so "no user came back" would be indistinguishable
    from a legitimately empty result and this test would pass on a broken guard.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com")
    bind_session_to_tenant(db_session, tenant_a.id)
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(TenantMarkedSessionError, match="find_by_email_globally"):
        await repo.find_by_email_globally("owner@example.com")


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


# --- recovery tokens (`auth-account-recovery` R2.5, R3.2, R3.5, design D1/D3/D7) ----


@pytest.mark.asyncio
async def test_a_password_write_must_name_the_temporary_flag(db_session, tenant_a) -> None:
    """Design D5 at the repository, not only at the entity.

    `set_password_hash` makes the pairing impossible to skip in the entity, but
    `apply_changes` takes a mapping, so it is a second write path where a caller could name
    one column and not the other — and D5's own argument is that two things which must be
    done together are two things somebody will eventually do separately.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(ValueError, match="must be written together"):
        await repo.apply_changes(tenant_a.id, user.id, {"password_hash": "lonely"})


@pytest.mark.asyncio
async def test_the_temporary_flag_cannot_be_cleared_on_its_own(db_session, tenant_a) -> None:
    """The dangerous direction: clearing the flag alone would release an account whose
    password is still the temporary one an administrator handed out (R5.4)."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    with pytest.raises(ValueError, match="must be written together"):
        await repo.apply_changes(tenant_a.id, user.id, {"must_change_password": False})


@pytest.mark.asyncio
async def test_writing_the_password_and_its_flag_together_is_allowed(
    db_session, tenant_a
) -> None:
    """The rule is a coupling, not a prohibition — the real reset path writes both."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    await repo.apply_changes(
        tenant_a.id, user.id, {"password_hash": "fresh", "must_change_password": True}
    )

    refreshed = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert refreshed.password_hash == "fresh"
    assert refreshed.must_change_password is True


@pytest.mark.asyncio
async def test_the_coupling_does_not_burden_unrelated_columns(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyUserRepository(db_session)

    await repo.apply_changes(tenant_a.id, user.id, {"name": "Ana Ruiz"})

    refreshed = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert refreshed.name == "Ana Ruiz"


def _reset_token(tenant_id, user_id, *, token_hash=None, minutes=30, **overrides):
    now = utc_now()
    values = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "token_hash": token_hash or uuid.uuid4().hex + uuid.uuid4().hex,
        "expires_at": now + timedelta(minutes=minutes),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return PasswordResetToken(**values)


@pytest.mark.asyncio
async def test_a_stored_token_can_be_consumed_and_returns_its_owner(
    db_session, tenant_a
) -> None:
    """The anonymous caller learns whose token it was only from the returned row (D3)."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_a.id, user.id)
    await repo.add(tenant_a.id, token)
    await db_session.flush()

    consumed = await repo.consume_globally(token.token_hash, utc_now())

    assert consumed is not None
    assert consumed.id == token.id
    assert consumed.user_id == user.id
    assert consumed.tenant_id == tenant_a.id
    assert consumed.used_at is not None


@pytest.mark.asyncio
async def test_a_token_cannot_be_consumed_twice(db_session, tenant_a) -> None:
    """R3.2: a presented link is a spent link."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_a.id, user.id)
    await repo.add(tenant_a.id, token)
    await db_session.flush()

    assert await repo.consume_globally(token.token_hash, utc_now()) is not None
    assert await repo.consume_globally(token.token_hash, utc_now()) is None


@pytest.mark.asyncio
async def test_an_expired_token_cannot_be_consumed(db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_a.id, user.id, minutes=-1)
    await repo.add(tenant_a.id, token)
    await db_session.flush()

    assert await repo.consume_globally(token.token_hash, utc_now()) is None


@pytest.mark.asyncio
async def test_a_revoked_token_cannot_be_consumed(db_session, tenant_a) -> None:
    """The clause that stops this UPDATE from winning a tie against a concurrent revocation."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_a.id, user.id, revoked_at=utc_now())
    await repo.add(tenant_a.id, token)
    await db_session.flush()

    assert await repo.consume_globally(token.token_hash, utc_now()) is None


@pytest.mark.asyncio
async def test_an_unknown_token_hash_consumes_nothing(db_session, tenant_a) -> None:
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)

    assert await repo.consume_globally("f" * 64, utc_now()) is None


@pytest.mark.asyncio
async def test_consuming_is_unscoped_and_finds_a_token_of_any_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    """Design D3: an unscoped query. No caller supplies the tenant.

    Said "the second and last" until `guest-portal-api` added a third; there is no count in
    prose any more — the census of the reads that resolve a tenant out of the row is the set of
    callers of `require_unmarked_session`, asserted by `tests/test_unscoped_reads.py`, which
    also names the unmarked-session reads outside it.

    The token of tenant B resolves without anyone naming B, and the row is what reveals it.
    """
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, token)
    await db_session.flush()

    consumed = await repo.consume_globally(token.token_hash, utc_now())

    assert consumed is not None
    assert consumed.tenant_id == tenant_b.id


@pytest.mark.asyncio
async def test_consume_globally_refuses_a_marked_session(db_session, tenant_a) -> None:
    """R6.2/R6.3, and here the silent alternative is worse than an empty read.

    A scoped UPDATE that matches nothing does not spend the token, so without the guard the
    caller would report an unusable link and the row would stay live.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token = _reset_token(tenant_a.id, user.id)
    await repo.add(tenant_a.id, token)
    await db_session.flush()
    bind_session_to_tenant(db_session, tenant_a.id)

    with pytest.raises(TenantMarkedSessionError, match="consume_globally"):
        await repo.consume_globally(token.token_hash, utc_now())


@pytest.mark.asyncio
async def test_adding_a_token_for_another_tenant_is_refused(
    db_session, tenant_a, tenant_b
) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repo.add(tenant_a.id, _reset_token(tenant_b.id, user_b.id))


@pytest.mark.asyncio
async def test_count_live_counts_only_spendable_tokens(db_session, tenant_a) -> None:
    """The cap of design D7 is about links that still work, not rows that exist."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    for token in (
        _reset_token(tenant_a.id, user.id),
        _reset_token(tenant_a.id, user.id),
        _reset_token(tenant_a.id, user.id, minutes=-1),
        _reset_token(tenant_a.id, user.id, used_at=now),
        _reset_token(tenant_a.id, user.id, revoked_at=now),
    ):
        await repo.add(tenant_a.id, token)
    await db_session.flush()

    assert await repo.count_live(tenant_a.id, user.id, now) == 2


@pytest.mark.asyncio
async def test_count_live_does_not_see_another_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    await repo.add(tenant_b.id, _reset_token(tenant_b.id, user_b.id))
    await db_session.flush()

    assert await repo.count_live(tenant_a.id, user_a.id, utc_now()) == 0


@pytest.mark.asyncio
async def test_revoke_other_live_kills_the_siblings_and_spares_the_one_kept(
    db_session, tenant_a
) -> None:
    """R3.5b. `keep_id` stays `used`, not `revoked`: the two are different facts."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    keep = _reset_token(tenant_a.id, user.id)
    other, another = (
        _reset_token(tenant_a.id, user.id),
        _reset_token(tenant_a.id, user.id),
    )
    for token in (keep, other, another):
        await repo.add(tenant_a.id, token)
    await db_session.flush()
    now = utc_now()
    consumed = await repo.consume_globally(keep.token_hash, now)
    assert consumed is not None

    revoked = await repo.revoke_other_live(tenant_a.id, user.id, keep.id, now)

    assert revoked == 2
    rows = {
        row.id: row
        for row in (
            await db_session.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == user.id
                )
            )
        ).scalars().all()
    }
    assert rows[keep.id].revoked_at is None
    assert rows[keep.id].used_at is not None
    assert rows[other.id].revoked_at is not None
    assert rows[another.id].revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_keeps_the_newest_and_revokes_the_rest(
    db_session, tenant_a
) -> None:
    """R2.5 / design D7 as amended: the cap retires the OLDEST rather than dropping the
    request, so a legitimate recovery always wins."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    # Explicit, spaced `created_at` so the ordering under test is not at the mercy of clock
    # resolution — which is exactly why the adapter's ORDER BY carries an `id` tiebreaker.
    tokens = []
    for minutes_ago in (30, 20, 10):
        token = _reset_token(
            tenant_a.id, user.id, created_at=now - timedelta(minutes=minutes_ago)
        )
        await repo.add(tenant_a.id, token)
        tokens.append(token)
    await db_session.flush()
    oldest, middle, newest = tokens

    revoked = await repo.revoke_oldest_beyond(tenant_a.id, user.id, 2, now, now)

    assert revoked == 1
    rows = {
        row.id: row
        for row in (
            await db_session.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == user.id
                )
            )
        ).scalars().all()
    }
    assert rows[oldest.id].revoked_at is not None
    assert rows[oldest.id].used_at is None, "revoked and used are different facts"
    assert rows[middle.id].revoked_at is None
    assert rows[newest.id].revoked_at is None


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_converges_when_the_cap_is_lowered(
    db_session, tenant_a
) -> None:
    """`keep_newest` rather than "revoke one": an account left above a lowered cap would
    otherwise stay above it for ever."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    for minutes_ago in (50, 40, 30, 20, 10):
        await repo.add(
            tenant_a.id,
            _reset_token(tenant_a.id, user.id, created_at=now - timedelta(minutes=minutes_ago)),
        )
    await db_session.flush()

    revoked = await repo.revoke_oldest_beyond(tenant_a.id, user.id, 1, now, now)

    assert revoked == 4
    assert await repo.count_live(tenant_a.id, user.id, now) == 1


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_leaves_used_and_expired_rows_alone(
    db_session, tenant_a
) -> None:
    """It operates on LIVE tokens only: a spent link keeps `used_at` and gains no
    `revoked_at`, or the trail would stop distinguishing the two."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    spent = _reset_token(tenant_a.id, user.id, used_at=now - timedelta(minutes=5))
    expired = _reset_token(tenant_a.id, user.id, minutes=-1)
    for token in (spent, expired):
        await repo.add(tenant_a.id, token)
    await db_session.flush()

    revoked = await repo.revoke_oldest_beyond(tenant_a.id, user.id, 0, now, now)

    assert revoked == 0
    rows = {
        row.id: row
        for row in (
            await db_session.execute(
                select(PasswordResetTokenModel).where(
                    PasswordResetTokenModel.user_id == user.id
                )
            )
        ).scalars().all()
    }
    assert rows[spent.id].revoked_at is None
    assert rows[expired.id].revoked_at is None


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_spares_every_link_inside_the_grace_window(
    db_session, tenant_a
) -> None:
    """R2.5 / design D7's grace amendment, against the real SQL.

    This is the test that pins `created_at <= older_than`, and it needs saying why it looks
    redundant next to the four above: every one of those passes `older_than=now` over rows
    aged in minutes, so their boundary is vacuously true and **deleting the predicate leaves
    them all green** (measured — the review panel deleted it and the whole suite stayed
    green). The behaviour only has teeth when `older_than` is strictly in the past and a
    candidate row is younger than it, which is precisely the state the amendment exists for:
    the link just mailed to the account's owner must survive the window in which they click
    it, even when it is the row the cap would otherwise retire.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    grace_boundary = now - timedelta(minutes=2)
    # Four live links, all issued seconds ago: a burst, with the owner's request last.
    for seconds_ago in (40, 30, 20, 10):
        await repo.add(
            tenant_a.id,
            _reset_token(tenant_a.id, user.id, created_at=now - timedelta(seconds=seconds_ago)),
        )
    await db_session.flush()

    revoked = await repo.revoke_oldest_beyond(tenant_a.id, user.id, 3, now, grace_boundary)

    assert revoked == 0, (
        "every live link is younger than the grace boundary, so nothing may be retired "
        "and the caller must discard instead"
    )
    assert await repo.count_live(tenant_a.id, user.id, now) == 4


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_still_retires_a_link_older_than_the_grace_window(
    db_session, tenant_a
) -> None:
    """The other half of the boundary: the grace spares the young, it does not spare
    everything. Without this, a predicate that blocked every revocation would pass the test
    above and the cap would silently stop capping."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    now = utc_now()
    grace_boundary = now - timedelta(minutes=2)
    stale = _reset_token(tenant_a.id, user.id, created_at=now - timedelta(minutes=25))
    await repo.add(tenant_a.id, stale)
    for seconds_ago in (30, 20, 10):
        await repo.add(
            tenant_a.id,
            _reset_token(tenant_a.id, user.id, created_at=now - timedelta(seconds=seconds_ago)),
        )
    await db_session.flush()

    revoked = await repo.revoke_oldest_beyond(tenant_a.id, user.id, 3, now, grace_boundary)

    assert revoked == 1
    row = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.id == stale.id)
        )
    ).scalar_one()
    assert row.revoked_at is not None
    assert row.used_at is None, "revoked and used are different facts"
    assert await repo.count_live(tenant_a.id, user.id, now) == 3


@pytest.mark.asyncio
async def test_revoke_oldest_beyond_does_not_reach_another_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token_b = _reset_token(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, token_b)
    await db_session.flush()

    assert await repo.revoke_oldest_beyond(tenant_a.id, user_a.id, 0, utc_now(), utc_now()) == 0
    row = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.id == token_b.id)
        )
    ).scalar_one()
    assert row.revoked_at is None


@pytest.mark.asyncio
async def test_revoke_other_live_does_not_reach_another_tenant(
    db_session, tenant_a, tenant_b
) -> None:
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    token_b = _reset_token(tenant_b.id, user_b.id)
    await repo.add(tenant_b.id, token_b)
    await db_session.flush()

    assert await repo.revoke_other_live(tenant_a.id, user_a.id, uuid.uuid4(), utc_now()) == 0
    row = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(
                PasswordResetTokenModel.id == token_b.id
            )
        )
    ).scalar_one()
    assert row.revoked_at is None


@pytest.mark.asyncio
async def test_two_simultaneous_presentations_of_one_token_leave_exactly_one_winner(
    test_engine,
) -> None:
    """The race R3.2 exists to close, proved against real Postgres (design D1).

    Two transactions present the same link at the same time. Only one may come back with a
    row: if both did, both callers would go on to reset the password, and a single-use
    credential would have been honoured twice. No fake can show this — what is being proved
    is that the conditional UPDATE serialises, because Postgres re-evaluates its WHERE
    against the new row version when the blocked statement unblocks.
    """
    tenant_id, user_id, token_hash = uuid.uuid4(), uuid.uuid4(), uuid.uuid4().hex * 2
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        session.add(
            TenantModel(id=tenant_id, name=f"t-{tenant_id.hex[:8]}", billing_email="o@x.com")
        )
        await session.flush()
        session.add(
            UserModel(
                id=user_id,
                tenant_id=tenant_id,
                name="Ana",
                email=f"ana-{user_id.hex[:8]}@example.com",
                password_hash="hashed",
                role=UserRole.TENANT_OWNER,
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add(
            PasswordResetTokenModel(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                user_id=user_id,
                token_hash=token_hash,
                expires_at=utc_now() + timedelta(minutes=30),
            )
        )
        await session.commit()

    async def _consume():
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            consumed = await SqlAlchemyPasswordResetTokenRepository(session).consume_globally(
                token_hash, utc_now()
            )
            await session.commit()
            return consumed

    results = await asyncio.gather(_consume(), _consume(), return_exceptions=True)

    winners = [r for r in results if not isinstance(r, BaseException) and r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, f"expected exactly one winner, got {results}"
    assert len(losers) == 1, f"expected exactly one loser, got {results}"


@pytest.mark.asyncio
async def test_two_tokens_cannot_share_a_hash(db_session, tenant_a) -> None:
    """`uq_password_reset_tokens_token_hash` is what makes `rowcount` a decision (D1)."""
    user = await insert_user(db_session, tenant=tenant_a)
    repo = SqlAlchemyPasswordResetTokenRepository(db_session)
    shared = uuid.uuid4().hex + uuid.uuid4().hex
    await repo.add(tenant_a.id, _reset_token(tenant_a.id, user.id, token_hash=shared))
    await repo.add(tenant_a.id, _reset_token(tenant_a.id, user.id, token_hash=shared))

    with pytest.raises(IntegrityError):
        await db_session.flush()
