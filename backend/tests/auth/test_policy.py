"""RBAC policy: PRD §6 in one auditable place (R3.1, design D8)."""

import pytest

from app.auth.domain import policy
from app.auth.domain.enums import UserRole
from app.auth.domain.policy import ROLE_PERMISSIONS, Permission, is_allowed


def test_every_role_has_an_explicit_policy_entry() -> None:
    # Adding a value to UserRole without deciding its permissions must fail here
    # rather than silently grant or deny at runtime.
    assert set(ROLE_PERMISSIONS) == set(UserRole)


def test_policy_entries_are_immutable_sets() -> None:
    for permissions in ROLE_PERMISSIONS.values():
        assert isinstance(permissions, frozenset)


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("permission", list(Permission))
def test_every_role_may_manage_its_own_session_and_read_its_own_profile(
    role: UserRole, permission: Permission
) -> None:
    # The only permissions this change introduces are self-service ones: reading
    # your own profile and ending your own session. PRD §6 grants those to every
    # role that can authenticate at all. Role-differentiated permissions arrive
    # with the modules that need them (design D8 — no speculative catalogue).
    assert is_allowed(role, permission) is True


def test_is_allowed_denies_when_the_permission_is_not_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Guards against an is_allowed that always returns True: with the real
    # catalogue every pair is allowed, so the deny path needs a stubbed mapping.
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {**ROLE_PERMISSIONS, UserRole.CLEANER: frozenset()},
    )

    assert policy.is_allowed(UserRole.CLEANER, Permission.READ_OWN_PROFILE) is False
    assert policy.is_allowed(UserRole.TENANT_OWNER, Permission.READ_OWN_PROFILE) is True


def test_is_allowed_denies_a_role_missing_from_the_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy, "ROLE_PERMISSIONS", {})

    assert policy.is_allowed(UserRole.SUPER_ADMIN, Permission.READ_OWN_PROFILE) is False
