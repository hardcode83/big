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


# The `user-management` matrix (its design D8), written out for the same reason as the one
# above. PRD §6 names nobody as the administrator of staff, so this is the decision the
# change took and this table is where it is auditable.
EXPECTED_ADMIN_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    # "configurar preferencias del tenant" (PRD §6) plus staff administration: whoever can
    # assign roles can escalate privileges, so it stays with the owner.
    UserRole.TENANT_OWNER: frozenset(
        {
            Permission.READ_USERS,
            Permission.MANAGE_USERS,
            Permission.READ_TENANT_SETTINGS,
            Permission.MANAGE_TENANT_SETTINGS,
        }
    ),
    # Reads the roster to assign cleanings and tickets, and the thresholds and SLAs to
    # operate; mutates neither.
    UserRole.PROPERTY_MANAGER: frozenset(
        {Permission.READ_USERS, Permission.READ_TENANT_SETTINGS}
    ),
    # The staff listing carries the email and role of every colleague. Their self-service is
    # `GET /api/v1/auth/me`.
    UserRole.CLEANER: frozenset(),
    UserRole.TECHNICIAN: frozenset(),
    # Same reasoning as the reservation matrix: global powers, not the operation of one
    # tenant; deferred to `saas-cross-tenant`.
    UserRole.SUPER_ADMIN: frozenset(),
}

ADMIN_PERMISSIONS = (
    Permission.READ_USERS,
    Permission.MANAGE_USERS,
    Permission.READ_TENANT_SETTINGS,
    Permission.MANAGE_TENANT_SETTINGS,
)


@pytest.mark.parametrize("role", list(UserRole))
def test_the_user_administration_matrix_is_the_one_design_d8_decided(role: UserRole) -> None:
    granted = {
        permission for permission in ADMIN_PERMISSIONS if is_allowed(role, permission)
    }
    assert granted == EXPECTED_ADMIN_PERMISSIONS[role]


def test_managing_users_implies_reading_them() -> None:
    for role in UserRole:
        if is_allowed(role, Permission.MANAGE_USERS):
            assert is_allowed(role, Permission.READ_USERS)


def test_managing_tenant_settings_implies_reading_them() -> None:
    for role in UserRole:
        if is_allowed(role, Permission.MANAGE_TENANT_SETTINGS):
            assert is_allowed(role, Permission.READ_TENANT_SETTINGS)


def test_only_the_owner_administers_users_or_settings() -> None:
    """One assertion for the decision that matters most in this change (design D8)."""
    for permission in (Permission.MANAGE_USERS, Permission.MANAGE_TENANT_SETTINGS):
        allowed = {role for role in UserRole if is_allowed(role, permission)}
        assert allowed == {UserRole.TENANT_OWNER}


# The permissions that gate, in their own module, facts the timeline also reveals by the
# mere existence of an entry (`dashboard-api`, security panel of section 2).
_IMPLIED_BY_READING_A_TIMELINE = (
    Permission.READ_RESERVATIONS,
    Permission.READ_CLEANING_TASKS,
    Permission.READ_ACCESS_RECORDS,
    Permission.READ_GUEST_DOCUMENTS,
)


@pytest.mark.parametrize(
    "implied", _IMPLIED_BY_READING_A_TIMELINE, ids=lambda p: p.value
)
def test_reading_properties_implies_every_permission_a_timeline_entry_can_reveal(
    implied: Permission,
) -> None:
    """`GET /api/v1/timeline/{property_id}` is gated by `READ_PROPERTIES` alone, and that
    is only sound while this holds.

    An entry carries no `metadata` (R4.3), but its `event_type` and title do announce that
    something happened in another domain — "Access instructions delivered", "Legal
    registration submitted", "Cleaning completed". Reading those same facts through the
    `access`, `guests` or `cleaning` modules needs a permission of its own, so a role that
    held `READ_PROPERTIES` *without* one of these would learn through the timeline what it
    was not granted elsewhere. That is design D10's "agregar no puede conceder" applied to
    a read that is an aggregate in everything but name.

    Today the alignment holds by construction — `TENANT_OWNER` and `PROPERTY_MANAGER` have
    all of them, and no other role has `READ_PROPERTIES`. It held **incidentally** until
    this test, which is the whole point: the security panel found that nothing would have
    noticed a future "read-only auditor" role scoped to properties. If this test fails,
    do not delete it — either grant the missing permission or make the timeline omit the
    entries whose source the caller cannot read.
    """
    for role in UserRole:
        if is_allowed(role, Permission.READ_PROPERTIES):
            assert is_allowed(role, implied), (
                f"{role.value} can read a property's timeline but not {implied.value}"
            )


def test_no_permission_is_granted_to_every_role_by_accident() -> None:
    """Catches a future `is_allowed` that always answers True, without a stub.

    The self-service pair IS universal, so the guard is that the differentiated ones are
    not: if this ever passes for `MANAGE_RESERVATIONS`, deny-by-default has broken.
    """
    for permission in (
        Permission.READ_RESERVATIONS,
        Permission.MANAGE_RESERVATIONS,
        *ADMIN_PERMISSIONS,
    ):
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
