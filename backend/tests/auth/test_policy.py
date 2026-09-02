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


def test_super_admin_holds_exactly_self_service_and_nothing_else() -> None:
    """`super-admin-identity` R4.1: giving the role identity must not widen what it can do.

    Direct pin against `_SELF_SERVICE`, not derived from `is_allowed` checks elsewhere —
    those prove individual permissions are absent, not that the set is exactly this one.
    """
    assert ROLE_PERMISSIONS[UserRole.SUPER_ADMIN] == policy._SELF_SERVICE
    assert ROLE_PERMISSIONS[UserRole.SUPER_ADMIN] == frozenset(
        {
            Permission.READ_OWN_PROFILE,
            Permission.MANAGE_OWN_SESSION,
            Permission.READ_OWN_NOTIFICATIONS,
        }
    )


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


def test_only_owner_and_property_manager_read_build_provenance() -> None:
    allowed = {
        role for role in UserRole if is_allowed(role, Permission.READ_BUILD_PROVENANCE)
    }

    assert allowed == {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}
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


# --- Incidents and owner approvals (`maintenance` R5.2, design D13) --------------------

INCIDENT_PERMISSIONS = (
    Permission.READ_INCIDENTS,
    Permission.MANAGE_INCIDENTS,
    Permission.EXECUTE_INCIDENTS,
    Permission.RESPOND_OWNER_APPROVALS,
)

#: The whole table of D13, written out rather than derived: the interesting content is the
#: **exclusions**, and a derived expectation would restate the implementation.
EXPECTED_INCIDENT_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: frozenset(),
    UserRole.TENANT_OWNER: frozenset(
        {Permission.READ_INCIDENTS, Permission.RESPOND_OWNER_APPROVALS}
    ),
    UserRole.PROPERTY_MANAGER: frozenset(
        {
            Permission.READ_INCIDENTS,
            Permission.MANAGE_INCIDENTS,
            Permission.EXECUTE_INCIDENTS,
        }
    ),
    UserRole.TECHNICIAN: frozenset(
        {Permission.READ_INCIDENTS, Permission.EXECUTE_INCIDENTS}
    ),
    UserRole.CLEANER: frozenset(),
}


@pytest.mark.parametrize("role", list(UserRole))
def test_the_incident_matrix_is_the_one_design_d13_decided(role: UserRole) -> None:
    granted = ROLE_PERMISSIONS[role] & frozenset(INCIDENT_PERMISSIONS)

    assert granted == EXPECTED_INCIDENT_PERMISSIONS[role]


def test_the_cleaner_gets_nothing_from_the_incident_flow() -> None:
    """R5.4: the routes are never exposed to `CLEANER`, and this is where that is decided.

    A broken boiler is not part of doing a cleaning, and the twelve routes of D14 all sit
    behind one of these four permissions — so holding none of them is what makes the 403
    structural rather than a check each router has to remember.
    """
    for permission in INCIDENT_PERMISSIONS:
        assert not is_allowed(UserRole.CLEANER, permission)


def test_the_super_admin_gets_nothing_from_the_incident_flow() -> None:
    """Same reason it holds no other operational permission inside a tenant: its powers in
    PRD §6 are global, and `saas-cross-tenant` decides what cross-tenant access looks like."""
    for permission in INCIDENT_PERMISSIONS:
        assert not is_allowed(UserRole.SUPER_ADMIN, permission)


def test_the_technician_may_execute_but_never_manage() -> None:
    """R5.2: "NEVER SHALL concederle nada más". Assigning and triaging are the manager's."""
    assert is_allowed(UserRole.TECHNICIAN, Permission.EXECUTE_INCIDENTS)
    assert not is_allowed(UserRole.TECHNICIAN, Permission.MANAGE_INCIDENTS)
    assert not is_allowed(UserRole.TECHNICIAN, Permission.RESPOND_OWNER_APPROVALS)


# --- Pricing (`revenue-pricing` R1.1, R1.2, R5.2, design D11) --------------------------

PRICING_PERMISSIONS = (
    Permission.READ_PRICING_RULES,
    Permission.MANAGE_PRICING_RULES,
    Permission.READ_PRICE_RECOMMENDATIONS,
    Permission.MANAGE_PRICE_RECOMMENDATIONS,
)

#: D11's table, written out rather than derived — as above, the content is the exclusions.
#: Note the owner and the manager hold **the same four**, which is the deliberate divergence
#: from "la owner ve, el manager opera" that every other pair in this file follows.
EXPECTED_PRICING_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: frozenset(),
    UserRole.TENANT_OWNER: frozenset(PRICING_PERMISSIONS),
    UserRole.PROPERTY_MANAGER: frozenset(PRICING_PERMISSIONS),
    UserRole.TECHNICIAN: frozenset(),
    UserRole.CLEANER: frozenset(),
}


@pytest.mark.parametrize("role", list(UserRole))
def test_the_pricing_matrix_is_the_one_design_d11_decided(role: UserRole) -> None:
    granted = ROLE_PERMISSIONS[role] & frozenset(PRICING_PERMISSIONS)

    assert granted == EXPECTED_PRICING_PERMISSIONS[role]


def test_the_owner_manages_pricing_and_not_only_reads_it() -> None:
    """The divergence D11 argues for, pinned so nobody "fixes" it into the usual shape.

    `min_price`/`max_price`/`max_daily_change_pct` bound the owner's own money (R3's user
    story), and PRD §19 Mode 1 says "Manager/owner aprueba manualmente y actualiza en OTA".
    An owner without a manager — PRD §1's scale — would otherwise be unable to set her own
    floor or approve a price for her own flat.
    """
    assert is_allowed(UserRole.TENANT_OWNER, Permission.MANAGE_PRICING_RULES)
    assert is_allowed(UserRole.TENANT_OWNER, Permission.MANAGE_PRICE_RECOMMENDATIONS)


# --- `revenue-statements` (design D8) ----------------------------------------------

STATEMENTS_PERMISSIONS = (
    Permission.READ_OWNER_STATEMENTS,
    Permission.MANAGE_OWNER_STATEMENTS,
)


def test_reading_and_managing_statements_are_distinct_permissions() -> None:
    """The two are siblings, not stacked — `MANAGE` does not imply `READ` here as it does
    elsewhere. D8 cites `_ACCESS_*` as the precedent; `_ACCESS_MANAGE` does include
    `READ_ACCESS_RECORDS` (`_ACCESS_MANAGE = {READ_ACCESS_RECORDS, MANAGE_ACCESS_RECORDS}`),
    but for statements the design says the owner reads the document and the manager
    operates it, so the owner does not get `MANAGE`. Pinned here so the bundles don't
    drift into the universal `_MANAGE ⊇ _READ` pattern."""
    assert Permission.READ_OWNER_STATEMENTS != Permission.MANAGE_OWNER_STATEMENTS
    granted = ROLE_PERMISSIONS[UserRole.TENANT_OWNER]
    assert Permission.READ_OWNER_STATEMENTS in granted
    assert Permission.MANAGE_OWNER_STATEMENTS not in granted
    granted = ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]
    assert Permission.READ_OWNER_STATEMENTS in granted
    assert Permission.MANAGE_OWNER_STATEMENTS in granted


EXPECTED_STATEMENTS_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: frozenset(),
    UserRole.TENANT_OWNER: frozenset({Permission.READ_OWNER_STATEMENTS}),
    UserRole.PROPERTY_MANAGER: frozenset(STATEMENTS_PERMISSIONS),
    UserRole.TECHNICIAN: frozenset(),
    UserRole.CLEANER: frozenset(),
}


@pytest.mark.parametrize("role", list(UserRole))
def test_the_statements_matrix_is_the_one_design_d8_decided(role: UserRole) -> None:
    granted = ROLE_PERMISSIONS[role] & frozenset(STATEMENTS_PERMISSIONS)

    assert granted == EXPECTED_STATEMENTS_PERMISSIONS[role]


@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN, UserRole.SUPER_ADMIN])
def test_field_and_admin_roles_get_nothing_from_statements(role: UserRole) -> None:
    """R7.1: the eleven routes sit behind one of these two, so holding none is what makes
    the 403 structural instead of a check each router must remember. `SUPER_ADMIN` gets
    nothing for the same reason it holds no operational permission today
    (`steering/security.md` regla 1, cross-tenant stance)."""
    for permission in STATEMENTS_PERMISSIONS:
        assert not is_allowed(role, permission), (
            f"{role.value} unexpectedly holds {permission.value}"
        )


@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN])
def test_the_operational_roles_get_nothing_from_pricing(role: UserRole) -> None:
    """R1.1/R5.2: the seven routes all sit behind one of these four, so holding none is
    what makes the 403 structural instead of a check each router must remember."""
    for permission in PRICING_PERMISSIONS:
        assert not is_allowed(role, permission)


def test_the_super_admin_gets_nothing_from_pricing() -> None:
    """Same reason it holds no other operational permission inside a tenant."""
    for permission in PRICING_PERMISSIONS:
        assert not is_allowed(UserRole.SUPER_ADMIN, permission)


def test_the_manager_executes_too_and_that_is_the_difference_from_cleaning() -> None:
    """R4.5: "un `PROPERTY_MANAGER` sí puede, para desatascar" — where `cleaning` gives
    `EXECUTE_CLEANING_TASKS` to the cleaner alone."""
    assert is_allowed(UserRole.PROPERTY_MANAGER, Permission.EXECUTE_INCIDENTS)
    assert not is_allowed(UserRole.PROPERTY_MANAGER, Permission.EXECUTE_CLEANING_TASKS)


def test_only_the_owner_answers_an_approval() -> None:
    """R2.6: "NEVER SHALL permitir responder una aprobación a un rol distinto de
    `TENANT_OWNER`" — the manager included, because the money is not hers."""
    allowed = {
        role for role in UserRole if is_allowed(role, Permission.RESPOND_OWNER_APPROVALS)
    }

    assert allowed == {UserRole.TENANT_OWNER}


def test_every_incident_permission_implies_reading_incidents() -> None:
    """Anyone who can act on an incident can see it — otherwise the actor gets a 404 on the
    thing they were just told to do, which is the trap `cleaning` documents for its own
    execute permission."""
    for role in UserRole:
        for permission in (Permission.MANAGE_INCIDENTS, Permission.EXECUTE_INCIDENTS):
            if is_allowed(role, permission):
                assert is_allowed(role, Permission.READ_INCIDENTS)


def test_no_incident_permission_is_granted_to_every_role() -> None:
    for permission in INCIDENT_PERMISSIONS:
        assert not all(is_allowed(role, permission) for role in UserRole)


# --- The guest portal token (`guest-portal-api` R1.1, R1.4, design D14) ----------------


def test_only_the_two_administrative_roles_may_mint_a_guest_access_token() -> None:
    """D14: `TENANT_OWNER` and `PROPERTY_MANAGER`, and nobody else.

    The whole matrix in one assertion, because the interesting content is the **exclusions**.
    Minting one of these hands out a link whose bearer can submit the guest's identity
    document, so it belongs with the two roles PRD §17 already trusts with that document.
    """
    allowed = {
        role for role in UserRole if is_allowed(role, Permission.MANAGE_GUEST_ACCESS_TOKENS)
    }

    assert allowed == {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}


def test_neither_the_cleaner_nor_the_technician_may_mint_a_guest_access_token() -> None:
    """Stated separately from the matrix above because it is the exclusion that could
    plausibly be argued the other way: both roles are physically at the property. Doing a
    cleaning or a repair is still not a reason to hand out a credential to a surface that
    writes guest PII."""
    assert not is_allowed(UserRole.CLEANER, Permission.MANAGE_GUEST_ACCESS_TOKENS)
    assert not is_allowed(UserRole.TECHNICIAN, Permission.MANAGE_GUEST_ACCESS_TOKENS)


def test_the_super_admin_may_not_mint_a_guest_access_token() -> None:
    """Consistent with every other operational permission inside a tenant.

    PRD §6 gives `SUPER_ADMIN` global powers — tenants, global configuration, integrations —
    not the operation of one tenant, and cross-tenant access is deferred to the
    `saas-cross-tenant` roadmap entry. Granting it here would pre-empt that decision on a
    credential that reaches identity documents, which is the worst place to do so.
    """
    assert not is_allowed(UserRole.SUPER_ADMIN, Permission.MANAGE_GUEST_ACCESS_TOKENS)


def test_minting_a_token_is_not_implied_by_managing_reservations() -> None:
    """D14 keeps this out of `MANAGE_RESERVATIONS` on purpose.

    Folding it in would grant it to every future holder of "can edit bookings" by accident —
    the same reasoning that keeps `READ_GUEST_DOCUMENTS` separate from `READ_RESERVATIONS`.
    Pinned as a property rather than a role list so it survives the matrix changing.
    """
    assert Permission.MANAGE_GUEST_ACCESS_TOKENS is not Permission.MANAGE_RESERVATIONS

    reservation_managers = {
        role for role in UserRole if is_allowed(role, Permission.MANAGE_RESERVATIONS)
    }
    token_minters = {
        role for role in UserRole if is_allowed(role, Permission.MANAGE_GUEST_ACCESS_TOKENS)
    }

    assert reservation_managers != token_minters


def test_there_is_no_read_permission_for_guest_access_tokens() -> None:
    """D14, asserted as an absence.

    There is nothing to read: the row stores only a hash, and rule 3(a)'s named exception
    returns the cleartext value exactly once at issue time and never afterwards. A read
    permission would grant the ability to see a digest, which is not a capability anyone
    reasons about separately.
    """
    assert not any(
        permission.value.startswith("READ_GUEST_ACCESS_TOKEN") for permission in Permission
    )


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
