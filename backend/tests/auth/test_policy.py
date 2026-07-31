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


SELF_SERVICE = (Permission.READ_OWN_PROFILE, Permission.MANAGE_OWN_SESSION)

# The matrix of PRD §6, written out rather than derived from the catalogue: a table that
# computed itself from `ROLE_PERMISSIONS` would agree with any mistake made there.
# Reservation permissions arrived with the `reservations` change (its design D7).
EXPECTED_RESERVATION_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    # "gestionar reservas (crear, editar, cancelar)" + "acceder a todos los datos operativos"
    UserRole.PROPERTY_MANAGER: frozenset(
        {Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS}
    ),
    # "ver sus propiedades y reservas" — read, not manage
    UserRole.TENANT_OWNER: frozenset({Permission.READ_RESERVATIONS}),
    # Sees only its own cleaning tasks
    UserRole.CLEANER: frozenset(),
    # Sees only its own tickets
    UserRole.TECHNICIAN: frozenset(),
    # Global powers (tenants, configuration, integrations), not the operation of one
    # tenant; cross-tenant visibility is deferred to the `saas-cross-tenant` entry.
    UserRole.SUPER_ADMIN: frozenset(),
}


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("permission", SELF_SERVICE)
def test_every_role_may_manage_its_own_session_and_read_its_own_profile(
    role: UserRole, permission: Permission
) -> None:
    # PRD §6 grants the self-service permissions to every role that can authenticate at
    # all. Role-differentiated ones are asserted below, per module that introduces them.
    assert is_allowed(role, permission) is True


@pytest.mark.parametrize("role", list(UserRole))
def test_the_reservation_matrix_is_exactly_the_one_prd_6_describes(role: UserRole) -> None:
    granted = {
        permission
        for permission in (Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS)
        if is_allowed(role, permission)
    }
    assert granted == EXPECTED_RESERVATION_PERMISSIONS[role]


def test_managing_reservations_implies_reading_them() -> None:
    """A role that can edit a booking it cannot read would be an unusable combination."""
    for role in UserRole:
        if is_allowed(role, Permission.MANAGE_RESERVATIONS):
            assert is_allowed(role, Permission.READ_RESERVATIONS)


def test_no_permission_is_granted_to_every_role_by_accident() -> None:
    """Catches a future `is_allowed` that always answers True, without a stub.

    The self-service pair IS universal, so the guard is that the differentiated ones are
    not: if this ever passes for `MANAGE_RESERVATIONS`, deny-by-default has broken.
    """
    for permission in (Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS):
        assert not all(is_allowed(role, permission) for role in UserRole)


def test_is_allowed_denies_when_the_permission_is_not_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
