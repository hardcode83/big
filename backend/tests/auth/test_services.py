"""The tenant must keep an administrator (R3.6, design D6).

Pure rule, tested without a database: the use case supplies the count of OTHER active
owners, the domain decides. That split is what makes the rule cheap to test exhaustively
here and leaves only the locking to the integration test.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.exceptions import LastOwnerError
from app.auth.domain.services import assert_tenant_keeps_an_owner


def _user(role: UserRole, status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Ana",
        email="ana@example.com",
        password_hash="hashed",
        role=role,
        created_at=now,
        updated_at=now,
        status=status,
    )


def test_demoting_the_last_active_owner_is_refused() -> None:
    with pytest.raises(LastOwnerError):
        assert_tenant_keeps_an_owner(
            target=_user(UserRole.TENANT_OWNER),
            new_role=UserRole.PROPERTY_MANAGER,
            new_status=None,
            other_active_owners=0,
        )


def test_deactivating_the_last_active_owner_is_refused() -> None:
    with pytest.raises(LastOwnerError):
        assert_tenant_keeps_an_owner(
            target=_user(UserRole.TENANT_OWNER),
            new_role=None,
            new_status=UserStatus.INACTIVE,
            other_active_owners=0,
        )


def test_suspending_the_last_active_owner_is_refused() -> None:
    """SUSPENDED locks the account out exactly as INACTIVE does (`get_active_by_id`)."""
    with pytest.raises(LastOwnerError):
        assert_tenant_keeps_an_owner(
            target=_user(UserRole.TENANT_OWNER),
            new_role=None,
            new_status=UserStatus.SUSPENDED,
            other_active_owners=0,
        )


def test_demoting_an_owner_is_allowed_when_another_active_one_remains() -> None:
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.TENANT_OWNER),
        new_role=UserRole.CLEANER,
        new_status=None,
        other_active_owners=1,
    )


def test_deactivating_a_non_owner_is_always_allowed() -> None:
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.CLEANER),
        new_role=None,
        new_status=UserStatus.INACTIVE,
        other_active_owners=0,
    )


def test_deactivating_an_already_inactive_owner_is_allowed() -> None:
    """It was not holding the tenant up, so removing it takes nothing away."""
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.TENANT_OWNER, UserStatus.INACTIVE),
        new_role=None,
        new_status=UserStatus.INACTIVE,
        other_active_owners=0,
    )


def test_promoting_someone_to_owner_is_always_allowed() -> None:
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.CLEANER),
        new_role=UserRole.TENANT_OWNER,
        new_status=None,
        other_active_owners=0,
    )


def test_reactivating_an_inactive_owner_is_allowed() -> None:
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.TENANT_OWNER, UserStatus.INACTIVE),
        new_role=None,
        new_status=UserStatus.ACTIVE,
        other_active_owners=0,
    )


def test_a_change_that_touches_neither_role_nor_status_is_allowed() -> None:
    """A profile-only PATCH must not be able to trip this rule."""
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.TENANT_OWNER),
        new_role=None,
        new_status=None,
        other_active_owners=0,
    )


def test_demoting_and_deactivating_at_once_is_refused() -> None:
    """Both fields in one PATCH: the rule looks at the RESULT, not at one field."""
    with pytest.raises(LastOwnerError):
        assert_tenant_keeps_an_owner(
            target=_user(UserRole.TENANT_OWNER),
            new_role=UserRole.CLEANER,
            new_status=UserStatus.INACTIVE,
            other_active_owners=0,
        )


def test_an_owner_staying_an_active_owner_is_allowed() -> None:
    """Re-sending the values it already had is not a removal."""
    assert_tenant_keeps_an_owner(
        target=_user(UserRole.TENANT_OWNER),
        new_role=UserRole.TENANT_OWNER,
        new_status=UserStatus.ACTIVE,
        other_active_owners=0,
    )


def test_a_negative_count_is_a_programming_error() -> None:
    """Guards against a repository that returns -1 or a swapped argument."""
    with pytest.raises(ValueError):
        assert_tenant_keeps_an_owner(
            target=_user(UserRole.TENANT_OWNER),
            new_role=UserRole.CLEANER,
            new_status=None,
            other_active_owners=-1,
        )
