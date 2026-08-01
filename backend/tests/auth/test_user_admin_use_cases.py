"""The six user-administration use cases, against in-memory fakes (R1-R4, R6).

`steering/testing.md` for this layer: fakes of the ports, never the database and never mocks
of SQLAlchemy. What is asserted here is orchestration — what gets written, in what order, with
which audit row, and what happens when a step fails. The SQL itself is covered by
`test_repositories.py`, and the locking it buys by `test_last_owner_concurrency.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions
from app.auth.application.user_admin import (
    CreateUserCommand,
    CreateUserUseCase,
    DeactivateUserUseCase,
    GetUserUseCase,
    ListUsersUseCase,
    ResetUserPasswordUseCase,
    UpdateUserUseCase,
)
from app.auth.domain.entities import User
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    LastOwnerError,
    SelfRoleChangeError,
    UnassignableRoleError,
    UserNotFoundError,
)
from app.auth.domain.repositories import UserFilters
from tests.auth.doubles import (
    FakeAuditLogRepository,
    FakeSessionRepository,
    FakeUnitOfWork,
    FakeUserRepository,
    StubPasswordHasher,
)

TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()
IP = "203.0.113.4"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _user(**overrides) -> User:
    now = utc_now()
    values = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "name": "Ana",
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "hashed::old",
        "role": UserRole.CLEANER,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return User(**values)


@pytest.fixture
def ports():
    return {
        "users": FakeUserRepository(),
        "audit": FakeAuditLogRepository(),
        "sessions": FakeSessionRepository(),
        "uow": FakeUnitOfWork(),
        "hasher": StubPasswordHasher(),
    }


# --- create (R1) -------------------------------------------------------------------


def _create_use_case(ports) -> CreateUserUseCase:
    return CreateUserUseCase(
        users=ports["users"], audit=ports["audit"], hasher=ports["hasher"], uow=ports["uow"]
    )


@pytest.mark.asyncio
async def test_creating_a_user_returns_a_usable_temporary_password(ports) -> None:
    created = await _create_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        command=CreateUserCommand(name="Ana", email="Ana@Example.com", role=UserRole.CLEANER),
        now=utc_now(),
    )

    assert created.temporary_password
    assert await ports["hasher"].verify(
        created.temporary_password, created.user.password_hash
    )
    # Normalised on the way in (ADR 0005, design D19).
    assert created.user.email == "ana@example.com"
    assert created.user.status is UserStatus.ACTIVE
    assert ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_creating_a_user_audits_it_without_the_password(ports) -> None:
    created = await _create_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        command=CreateUserCommand(name="Ana", email="ana@example.com", role=UserRole.CLEANER),
        now=utc_now(),
    )

    (tenant_id, entry) = ports["audit"].entries[0]
    assert tenant_id == TENANT
    assert entry.action == actions.USER_CREATED
    assert entry.actor_user_id == ACTOR
    assert entry.actor_ip == IP
    assert entry.changes["password"] == {"changed": True}
    serialised = str(entry.changes)
    assert created.temporary_password not in serialised
    assert created.user.password_hash not in serialised


@pytest.mark.asyncio
async def test_a_duplicate_address_leaves_no_audit_row(ports) -> None:
    """The order of R1.4 and R6.4 together: a `409` must not look like a creation."""
    ports["users"].duplicate_emails.add("taken@example.com")

    with pytest.raises(EmailAlreadyExistsError):
        await _create_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            command=CreateUserCommand(
                name="Ana", email="taken@example.com", role=UserRole.CLEANER
            ),
            now=utc_now(),
        )

    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_creating_a_super_admin_is_refused(ports) -> None:
    with pytest.raises(UnassignableRoleError):
        await _create_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            command=CreateUserCommand(
                name="Root", email="root@example.com", role=UserRole.SUPER_ADMIN
            ),
            now=utc_now(),
        )

    assert ports["users"].users == {}
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_two_creations_get_different_passwords(ports) -> None:
    use_case = _create_use_case(ports)
    first = await use_case.execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        command=CreateUserCommand(name="A", email="a@example.com", role=UserRole.CLEANER),
        now=utc_now(),
    )
    second = await use_case.execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        command=CreateUserCommand(name="B", email="b@example.com", role=UserRole.TECHNICIAN),
        now=utc_now(),
    )

    assert first.temporary_password != second.temporary_password


# --- read (R2, R7.1) ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_getting_a_user_that_does_not_exist_is_a_not_found(ports) -> None:
    with pytest.raises(UserNotFoundError):
        await GetUserUseCase(users=ports["users"]).execute(
            tenant_id=TENANT, user_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_getting_a_user_of_another_tenant_is_the_same_not_found(ports) -> None:
    """R7.1: the two cases are indistinguishable, which is what the `404` promises."""
    other_tenant = uuid.uuid4()
    stranger = ports["users"].seed(_user(tenant_id=other_tenant))

    with pytest.raises(UserNotFoundError):
        await GetUserUseCase(users=ports["users"]).execute(
            tenant_id=TENANT, user_id=stranger.id
        )


@pytest.mark.asyncio
async def test_listing_only_returns_the_acting_tenant(ports) -> None:
    ports["users"].seed(_user(name="Mine"))
    ports["users"].seed(_user(name="Theirs", tenant_id=uuid.uuid4()))

    page = await ListUsersUseCase(users=ports["users"]).execute(
        tenant_id=TENANT, filters=UserFilters(), page=1, per_page=20
    )

    assert [user.name for user in page.items] == ["Mine"]
    assert page.total == 1


# --- update (R3) -------------------------------------------------------------------


def _update_use_case(ports) -> UpdateUserUseCase:
    return UpdateUserUseCase(
        users=ports["users"],
        sessions=ports["sessions"],
        audit=ports["audit"],
        uow=ports["uow"],
    )


@pytest.mark.asyncio
async def test_updating_the_profile_writes_only_what_changed(ports) -> None:
    user = ports["users"].seed(_user(name="Ana", phone=None))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"name": "Ana Ruiz", "preferred_language": "es"},
        now=utc_now(),
    )

    (_, _, written) = ports["users"].applied[0]
    # `preferred_language` was already "es", so it is not written (design D15/D21).
    assert written == {"name": "Ana Ruiz"}
    assert ports["audit"].entries[0][1].action == actions.USER_UPDATED


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_nothing(ports) -> None:
    user = ports["users"].seed(_user(name="Ana"))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"name": "Ana"},
        now=utc_now(),
    )

    assert ports["users"].applied == []
    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_an_empty_patch_writes_nothing(ports) -> None:
    user = ports["users"].seed(_user())

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={},
        now=utc_now(),
    )

    assert ports["users"].applied == []
    assert ports["audit"].entries == []


@pytest.mark.asyncio
async def test_a_role_change_uses_its_own_audit_action(ports) -> None:
    """Rule 9 of steering/security.md becomes an indexed `action` filter (design D4)."""
    user = ports["users"].seed(_user(role=UserRole.CLEANER))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"role": UserRole.TECHNICIAN},
        now=utc_now(),
    )

    entry = ports["audit"].entries[0][1]
    assert entry.action == actions.USER_ROLE_CHANGED
    assert entry.changes["role"] == {"old": "CLEANER", "new": "TECHNICIAN"}


@pytest.mark.asyncio
async def test_a_patch_changing_role_and_profile_is_one_row_with_both(ports) -> None:
    user = ports["users"].seed(_user(role=UserRole.CLEANER, name="Ana"))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"role": UserRole.TECHNICIAN, "name": "Ana Ruiz"},
        now=utc_now(),
    )

    assert len(ports["audit"].entries) == 1
    entry = ports["audit"].entries[0][1]
    assert entry.action == actions.USER_ROLE_CHANGED
    assert set(entry.changes) == {"role", "name"}


@pytest.mark.asyncio
async def test_changing_your_own_role_is_refused(ports) -> None:
    user = ports["users"].seed(_user(role=UserRole.TENANT_OWNER))
    ports["users"].seed(_user(role=UserRole.TENANT_OWNER))  # so it is not the last owner

    with pytest.raises(SelfRoleChangeError):
        await _update_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=user.id,
            actor_ip=IP,
            user_id=user.id,
            changes={"role": UserRole.CLEANER},
            now=utc_now(),
        )

    assert ports["users"].applied == []


@pytest.mark.asyncio
async def test_demoting_the_last_active_owner_is_refused(ports) -> None:
    owner = ports["users"].seed(_user(role=UserRole.TENANT_OWNER))

    with pytest.raises(LastOwnerError):
        await _update_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=owner.id,
            changes={"role": UserRole.CLEANER},
            now=utc_now(),
        )

    assert ports["users"].applied == []
    assert ports["audit"].entries == []


@pytest.mark.asyncio
async def test_demoting_an_owner_is_allowed_when_another_remains(ports) -> None:
    owner = ports["users"].seed(_user(role=UserRole.TENANT_OWNER))
    ports["users"].seed(_user(role=UserRole.TENANT_OWNER))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=owner.id,
        changes={"role": UserRole.CLEANER},
        now=utc_now(),
    )

    assert ports["users"].applied[0][2] == {"role": UserRole.CLEANER}


@pytest.mark.asyncio
async def test_the_tenant_lock_is_taken_before_a_role_or_status_change(ports) -> None:
    """Design D6: without the lock the owner count is a read-then-write race."""
    user = ports["users"].seed(_user(role=UserRole.CLEANER))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"status": UserStatus.SUSPENDED},
        now=utc_now(),
    )

    assert ports["users"].locks_taken == [TENANT]


@pytest.mark.asyncio
async def test_the_tenant_lock_is_not_taken_for_a_profile_only_patch(ports) -> None:
    """A name change cannot affect the owner population, so it pays no lock."""
    user = ports["users"].seed(_user(name="Ana"))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"name": "Ana Ruiz"},
        now=utc_now(),
    )

    assert ports["users"].locks_taken == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [UserStatus.INACTIVE, UserStatus.SUSPENDED])
async def test_disabling_a_user_revokes_every_session(ports, status) -> None:
    """R3.7: `POST /auth/refresh` never revalidates status, so the tokens must die here."""
    user = ports["users"].seed(_user())

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"status": status},
        now=utc_now(),
    )

    assert ports["sessions"].revocations == [
        (TENANT, user.id, SessionRevokedReason.USER_DEACTIVATED)
    ]


@pytest.mark.asyncio
async def test_reactivating_a_user_does_not_revoke_anything(ports) -> None:
    user = ports["users"].seed(_user(status=UserStatus.SUSPENDED))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"status": UserStatus.ACTIVE},
        now=utc_now(),
    )

    assert ports["sessions"].revocations == []


@pytest.mark.asyncio
async def test_changing_the_email_normalises_it_and_audits_the_change(ports) -> None:
    user = ports["users"].seed(_user(email="old@example.com"))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"email": "  NEW@Example.COM "},
        now=utc_now(),
    )

    assert ports["users"].applied[0][2] == {"email": "new@example.com"}
    assert ports["audit"].entries[0][1].changes["email"] == {
        "old": "old@example.com",
        "new": "new@example.com",
    }


@pytest.mark.asyncio
async def test_a_duplicate_address_on_update_surfaces_as_its_own_error(ports) -> None:
    user = ports["users"].seed(_user(email="mine@example.com"))
    ports["users"].duplicate_emails.add("taken@example.com")

    with pytest.raises(EmailAlreadyExistsError):
        await _update_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=user.id,
            changes={"email": "taken@example.com"},
            now=utc_now(),
        )

    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_updating_a_user_of_another_tenant_is_a_not_found(ports) -> None:
    stranger = ports["users"].seed(_user(tenant_id=uuid.uuid4()))

    with pytest.raises(UserNotFoundError):
        await _update_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=stranger.id,
            changes={"name": "Hacked"},
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_a_failing_audit_write_leaves_the_change_uncommitted(ports) -> None:
    """R6.4: the mutation and its trail live or die together."""
    ports["audit"].fail = True
    user = ports["users"].seed(_user(name="Ana"))

    with pytest.raises(RuntimeError):
        await _update_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=user.id,
            changes={"name": "Ana Ruiz"},
            now=utc_now(),
        )

    assert ports["uow"].commits == 0


# --- deactivate (R3.8, R3.9) -------------------------------------------------------


def _deactivate_use_case(ports) -> DeactivateUserUseCase:
    return DeactivateUserUseCase(
        users=ports["users"],
        sessions=ports["sessions"],
        audit=ports["audit"],
        uow=ports["uow"],
    )


@pytest.mark.asyncio
async def test_deactivating_keeps_the_row_and_revokes_the_sessions(ports) -> None:
    user = ports["users"].seed(_user())

    await _deactivate_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )

    assert ports["users"].applied[0][2] == {"status": UserStatus.INACTIVE}
    assert ports["users"].users[(TENANT, user.id)] is user  # the row stays (R3.8)
    assert ports["sessions"].revocations == [
        (TENANT, user.id, SessionRevokedReason.USER_DEACTIVATED)
    ]
    assert ports["audit"].entries[0][1].action == actions.USER_DEACTIVATED


@pytest.mark.asyncio
async def test_deactivating_an_already_inactive_user_is_a_silent_no_op(ports) -> None:
    """R3.9: `204` again, and NO second audit row."""
    user = ports["users"].seed(_user(status=UserStatus.INACTIVE))

    await _deactivate_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )

    assert ports["users"].applied == []
    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_deactivating_yourself_is_refused(ports) -> None:
    """Design D19: a DELETE is a status change, so R3.5 covers it."""
    user = ports["users"].seed(_user(role=UserRole.TENANT_OWNER))
    ports["users"].seed(_user(role=UserRole.TENANT_OWNER))

    with pytest.raises(SelfRoleChangeError):
        await _deactivate_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=user.id,
            actor_ip=IP,
            user_id=user.id,
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_deactivating_the_last_active_owner_is_refused(ports) -> None:
    owner = ports["users"].seed(_user(role=UserRole.TENANT_OWNER))

    with pytest.raises(LastOwnerError):
        await _deactivate_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=owner.id,
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_deactivating_a_user_of_another_tenant_is_a_not_found(ports) -> None:
    stranger = ports["users"].seed(_user(tenant_id=uuid.uuid4()))

    with pytest.raises(UserNotFoundError):
        await _deactivate_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=stranger.id,
            now=utc_now(),
        )


# --- reset password (R4) -----------------------------------------------------------


def _reset_use_case(ports) -> ResetUserPasswordUseCase:
    return ResetUserPasswordUseCase(
        users=ports["users"],
        sessions=ports["sessions"],
        audit=ports["audit"],
        hasher=ports["hasher"],
        uow=ports["uow"],
    )


@pytest.mark.asyncio
async def test_resetting_issues_a_new_password_and_kills_the_sessions(ports) -> None:
    user = ports["users"].seed(_user(password_hash="hashed::old"))

    result = await _reset_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )

    assert await ports["hasher"].verify(result.temporary_password, user.password_hash)
    assert ports["users"].applied[0][2] == {"password_hash": user.password_hash}
    assert ports["sessions"].revocations == [
        (TENANT, user.id, SessionRevokedReason.PASSWORD_RESET)
    ]


@pytest.mark.asyncio
async def test_resetting_audits_without_the_password_or_its_hash(ports) -> None:
    user = ports["users"].seed(_user())

    result = await _reset_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )

    entry = ports["audit"].entries[0][1]
    assert entry.action == actions.USER_PASSWORD_RESET
    assert entry.changes == {"password": {"changed": True}}
    assert result.temporary_password not in str(entry.changes)
    assert user.password_hash not in str(entry.changes)


@pytest.mark.asyncio
async def test_resetting_a_user_of_another_tenant_is_a_not_found(ports) -> None:
    stranger = ports["users"].seed(_user(tenant_id=uuid.uuid4()))

    with pytest.raises(UserNotFoundError):
        await _reset_use_case(ports).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            user_id=stranger.id,
            now=utc_now(),
        )

    assert ports["sessions"].revocations == []


@pytest.mark.asyncio
async def test_every_mutating_use_case_commits_exactly_once(ports) -> None:
    """One business operation, one transaction."""
    user = ports["users"].seed(_user(name="Ana"))

    await _update_use_case(ports).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        user_id=user.id,
        changes={"name": "Ana Ruiz"},
        now=utc_now(),
    )
    await _reset_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )
    await _deactivate_use_case(ports).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=IP, user_id=user.id, now=utc_now()
    )

    assert ports["uow"].commits == 3
