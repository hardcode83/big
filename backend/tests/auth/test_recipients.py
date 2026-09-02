"""`RoleRecipients` — the one answer to "who on this tenant hears about it" (R5.1, design D1).

Unit tests against the in-memory `FakeUserRepository`, per `steering/testing.md`: this is a
domain service over a port, so it is testable without a session and that is the whole reason
it exists.

What these pin is the part that used to be written twice — `guests::_managers` and
`EscalateBreachedSlasUseCase._active_holders` — so that the six writers this change adds
cannot derive a third spelling of the same rule.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.recipients import Recipients, RoleRecipients

from tests.auth.doubles import FakeUserRepository

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _user(
    tenant_id: uuid.UUID,
    *,
    role: UserRole,
    name: str,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        email=f"{name.lower()}@example.test",
        password_hash="x",
        role=role,
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def users() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def recipients(users: FakeUserRepository) -> RoleRecipients:
    return RoleRecipients(users=users)


# -- managers_or_owners: the fallback that R5.1 fixes ---------------------------------


@pytest.mark.asyncio
async def test_it_returns_the_active_managers_when_there_are_any(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    manager = _user(tenant_id, role=UserRole.PROPERTY_MANAGER, name="Ana")
    other = _user(tenant_id, role=UserRole.PROPERTY_MANAGER, name="Bea")
    users.seed(manager)
    users.seed(other)
    users.seed(_user(tenant_id, role=UserRole.TENANT_OWNER, name="Owner"))

    result = await recipients.managers_or_owners(tenant_id)

    assert {u.id for u in result.users} == {manager.id, other.id}
    assert result.dropped == 0


@pytest.mark.asyncio
async def test_it_falls_back_to_the_active_owners_when_there_is_no_manager(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    owner = _user(tenant_id, role=UserRole.TENANT_OWNER, name="Owner")
    users.seed(owner)

    result = await recipients.managers_or_owners(tenant_id)

    assert [u.id for u in result.users] == [owner.id]


@pytest.mark.asyncio
async def test_an_inactive_manager_does_not_suppress_the_owner_fallback(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    """The filter is on ACTIVE, not on the role existing.

    A tenant whose only manager is deactivated has nobody in that role, so the warning has
    to reach the owner — the same reason `guests::_managers` gives for having a fallback at
    all: a failed police filing cannot be lost because an account was suspended.
    """
    users.seed(
        _user(
            tenant_id,
            role=UserRole.PROPERTY_MANAGER,
            name="Gone",
            status=UserStatus.INACTIVE,
        )
    )
    owner = _user(tenant_id, role=UserRole.TENANT_OWNER, name="Owner")
    users.seed(owner)

    result = await recipients.managers_or_owners(tenant_id)

    assert [u.id for u in result.users] == [owner.id]


@pytest.mark.asyncio
async def test_it_returns_nobody_when_there_is_neither_an_active_manager_nor_owner(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    """R5.2's case. The service reports emptiness; it does not decide what that means.

    Every caller treats it differently — the escalation job leaves the breach unmarked, the
    six writers of this change skip the row and log — so turning it into an exception here
    would take that decision away from all of them.
    """
    users.seed(
        _user(
            tenant_id, role=UserRole.TENANT_OWNER, name="Gone", status=UserStatus.SUSPENDED
        )
    )
    users.seed(_user(tenant_id, role=UserRole.CLEANER, name="Cleaner"))

    result = await recipients.managers_or_owners(tenant_id)

    assert result.users == ()
    assert result.dropped == 0


@pytest.mark.asyncio
async def test_it_never_reaches_another_tenants_roster(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    """Rule 1 of `steering/security.md`, at the one layer that resolves recipients.

    A leak here would not read a neighbour's data — it would *address* them, putting this
    tenant's notification bodies in their inbox.
    """
    neighbour = uuid.uuid4()
    users.seed(_user(neighbour, role=UserRole.PROPERTY_MANAGER, name="Theirs"))
    mine = _user(tenant_id, role=UserRole.PROPERTY_MANAGER, name="Mine")
    users.seed(mine)

    result = await recipients.managers_or_owners(tenant_id)

    assert [u.id for u in result.users] == [mine.id]


# -- active_holders: the parameterised half, and the truncation count ------------------


@pytest.mark.asyncio
async def test_active_holders_returns_one_page_of_the_role(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    owner = _user(tenant_id, role=UserRole.TENANT_OWNER, name="Owner")
    users.seed(owner)
    users.seed(_user(tenant_id, role=UserRole.PROPERTY_MANAGER, name="Manager"))

    result = await recipients.active_holders(tenant_id, UserRole.TENANT_OWNER)

    assert [u.id for u in result.users] == [owner.id]
    assert result.dropped == 0


@pytest.mark.asyncio
async def test_dropped_is_zero_when_pagination_covers_the_full_roster(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    """A tenant whose roster spans more than one page is no longer truncated.

    The previous implementation asked for `per_page=MAX_RECIPIENTS` and called it done,
    so a tenant with more administrative users than that got a silent partial — the exact
    failure mode `EscalateBreachedSlasUseCase` keeps `recipients_truncated` to surface.
    R6.2 closes it: the helper pages end-to-end, and `dropped` stays at zero until the
    safety ceiling (`MAX_PAGE` * `PAGE_SIZE`) is actually exceeded.
    """
    for index in range(RoleRecipients.PAGE_SIZE + 3):
        users.seed(
            _user(tenant_id, role=UserRole.PROPERTY_MANAGER, name=f"Manager{index:03d}")
        )

    result = await recipients.managers_or_owners(tenant_id)

    assert len(result.users) == RoleRecipients.PAGE_SIZE + 3
    assert result.dropped == 0


@pytest.mark.asyncio
async def test_the_owner_fallback_pages_end_to_end_too(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    """With no manager and more than a page of owners, the helper still returns every owner.

    The bug the escalation job had before it routed both reads through one helper was
    that the fallback stopped at one page and counted its truncation — a silent partial
    notification whose counter happened to be zero. The new loop walks both pages the
    same way; this test pins the fallback path at a roster larger than one page.
    """
    for index in range(RoleRecipients.PAGE_SIZE + 2):
        users.seed(_user(tenant_id, role=UserRole.TENANT_OWNER, name=f"Owner{index:03d}"))

    result = await recipients.managers_or_owners(tenant_id)

    assert len(result.users) == RoleRecipients.PAGE_SIZE + 2
    assert result.dropped == 0


# -- the shape of the answer ----------------------------------------------------------


@pytest.mark.asyncio
async def test_recipients_is_frozen(
    recipients: RoleRecipients, users: FakeUserRepository, tenant_id: uuid.UUID
) -> None:
    users.seed(_user(tenant_id, role=UserRole.PROPERTY_MANAGER, name="Ana"))

    result = await recipients.managers_or_owners(tenant_id)

    assert isinstance(result, Recipients)
    with pytest.raises(Exception):
        result.dropped = 7  # type: ignore[misc]


@pytest.mark.asyncio
async def test_it_emits_no_log_of_its_own(
    recipients: RoleRecipients,
    users: FakeUserRepository,
    tenant_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design D1: the truncation log belongs to the caller, because the key names the site.

    `scheduler.escalation_recipients_truncated` means something to whoever reads the
    scheduler's logs; the same event from a cleaning completion is a different key. A helper
    that logged would either invent a third name or force every caller to share one.
    """
    for index in range(RoleRecipients.PAGE_SIZE + 1):
        users.seed(
            _user(tenant_id, role=UserRole.PROPERTY_MANAGER, name=f"Manager{index:03d}")
        )

    with caplog.at_level("DEBUG"):
        result = await recipients.managers_or_owners(tenant_id)

    assert result.dropped == 0
    assert [r for r in caplog.records if r.name.startswith("app.auth")] == []
