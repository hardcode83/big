"""RBAC policy — PRD §6 in one auditable place (R3.1, design D8).

The catalogue holds only the permissions this change actually enforces. Each new
module adds the permissions its endpoints declare; there is no speculative
catalogue of capabilities nobody checks yet.
"""

import enum
from collections.abc import Mapping

from app.auth.domain.enums import UserRole


class Permission(str, enum.Enum):
    READ_OWN_PROFILE = "READ_OWN_PROFILE"
    MANAGE_OWN_SESSION = "MANAGE_OWN_SESSION"
    # Added by `reservations` (design D7). Two, not one: PRD §6 gives
    # `PROPERTY_MANAGER` "gestionar reservas (crear, editar, cancelar)" and
    # `TENANT_OWNER` only "ver sus propiedades y reservas", so read and write are
    # different capabilities. Importing a CSV and syncing the PMS are the same business
    # capability by another route, so they reuse MANAGE_RESERVATIONS instead of adding a
    # permission nobody reasons about separately.
    READ_RESERVATIONS = "READ_RESERVATIONS"
    MANAGE_RESERVATIONS = "MANAGE_RESERVATIONS"
    # Added by `user-management` (design D8). Four and not two: PRD §6 gives
    # `TENANT_OWNER` "configurar preferencias del tenant" and says nothing about who
    # administers staff, while `PROPERTY_MANAGER` needs to READ both — the roster to assign
    # cleanings, the thresholds and SLAs to operate — without being able to mutate either.
    # Whoever can assign roles can escalate privileges, so that stays with the owner.
    READ_USERS = "READ_USERS"
    MANAGE_USERS = "MANAGE_USERS"
    READ_TENANT_SETTINGS = "READ_TENANT_SETTINGS"
    MANAGE_TENANT_SETTINGS = "MANAGE_TENANT_SETTINGS"
    # Added by `properties-crud` (design D12). Unlike every entry above, this split could NOT be
    # cited from PRD §6: that section names no create-or-edit-property capability for any role at
    # all, so the reasoning is recorded rather than referenced. §6 gives `TENANT_OWNER` "ver sus
    # propiedades y reservas" — a read — and `PROPERTY_MANAGER` "acceder a todos los datos
    # operativos", so the split mirrors `reservations` exactly: the owner sees the portfolio, the
    # manager operates it.
    READ_PROPERTIES = "READ_PROPERTIES"
    MANAGE_PROPERTIES = "MANAGE_PROPERTIES"

    # Added by `cleaning` (design D7). Five and not two, because three different
    # capabilities meet on these tables and PRD §6 gives them to different people:
    # reading the work, administering it (assigning, creating, validating), and *doing* it.
    #
    # `EXECUTE_CLEANING_TASKS` is the cleaner's alone — not the manager's. R3.4/R3.5/R3.6 say
    # "la limpiadora asignada" without exception, and the entity answers 404 to anyone who is
    # not the assignee (R7.2), so a manager holding it would see a task in the listing and get
    # a 404 acting on it. What the manager needs — reassign, create, validate — is
    # `MANAGE_CLEANING_TASKS`.
    READ_CLEANING_TASKS = "READ_CLEANING_TASKS"
    MANAGE_CLEANING_TASKS = "MANAGE_CLEANING_TASKS"
    EXECUTE_CLEANING_TASKS = "EXECUTE_CLEANING_TASKS"
    READ_CLEANING_TEMPLATES = "READ_CLEANING_TEMPLATES"
    MANAGE_CLEANING_TEMPLATES = "MANAGE_CLEANING_TEMPLATES"


_SELF_SERVICE = frozenset({Permission.READ_OWN_PROFILE, Permission.MANAGE_OWN_SESSION})
_RESERVATION_READ = frozenset({Permission.READ_RESERVATIONS})
_RESERVATION_MANAGE = frozenset({Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS})
_USER_READ = frozenset({Permission.READ_USERS})
_USER_MANAGE = frozenset({Permission.READ_USERS, Permission.MANAGE_USERS})
_TENANT_SETTINGS_READ = frozenset({Permission.READ_TENANT_SETTINGS})
_TENANT_SETTINGS_MANAGE = frozenset(
    {Permission.READ_TENANT_SETTINGS, Permission.MANAGE_TENANT_SETTINGS}
)
_PROPERTY_READ = frozenset({Permission.READ_PROPERTIES})
_PROPERTY_MANAGE = frozenset({Permission.READ_PROPERTIES, Permission.MANAGE_PROPERTIES})

_CLEANING_TEMPLATE_MANAGE = frozenset(
    {Permission.READ_CLEANING_TEMPLATES, Permission.MANAGE_CLEANING_TEMPLATES}
)
_CLEANING_READ = frozenset({Permission.READ_CLEANING_TASKS})
_CLEANING_MANAGE = frozenset(
    {Permission.READ_CLEANING_TASKS, Permission.MANAGE_CLEANING_TASKS}
)
_CLEANING_EXECUTE = frozenset(
    {Permission.READ_CLEANING_TASKS, Permission.EXECUTE_CLEANING_TASKS}
)

# Every role that can authenticate may read its own profile and end its own
# session (PRD §6). Role-differentiated permissions belong to the modules that
# introduce the endpoints needing them.
#
# `SUPER_ADMIN` gets NO reservation permission on purpose (design D7): its powers in
# PRD §6 are global — tenants, global configuration, integrations — not the operation of
# one tenant, and cross-tenant visibility is explicitly deferred to the `saas-cross-tenant`
# roadmap entry. Granting it here would pre-empt that decision. `CLEANER` and `TECHNICIAN`
# see only their own tasks and tickets, never the booking ledger.
#
# **Consequence of `_PROPERTY_READ` for the owner, assumed and not accidental** (design D12):
# the owner cannot register her own flat — the manager does. `app/cli/bootstrap.py` creates both
# accounts, so a fresh environment can still reach the API; and this is the one place where
# product intuition ("she owns the homes") and PRD §6 ("ver sus propiedades") diverge, resolved
# in favour of the PRD and of symmetry with reservations.
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: _SELF_SERVICE,
    UserRole.TENANT_OWNER: (
        _SELF_SERVICE
        | _RESERVATION_READ
        | _PROPERTY_READ
        | _USER_MANAGE
        | _TENANT_SETTINGS_MANAGE
        # Reads the work and owns the standard the tenant cleans to; does not operate it.
        | _CLEANING_READ
        | _CLEANING_TEMPLATE_MANAGE
    ),
    UserRole.PROPERTY_MANAGER: (
        _SELF_SERVICE
        | _RESERVATION_MANAGE
        | _PROPERTY_MANAGE
        | _USER_READ
        | _TENANT_SETTINGS_READ
        | _CLEANING_MANAGE
        # R1.1 names `PROPERTY_MANAGER` **and** `TENANT_OWNER` as creators of a template, and
        # PRD §6 puts the manager in charge of cleaning ("gestionar limpiezas: asignar,
        # reasignar, validar"). A first draft gave the manager read-only here and the security
        # panel of sections 2-3 caught the divergence from R1.1 and from design D7: in a tenant
        # whose owner never logs in, `process_checkouts` would have nothing to resolve, because
        # `checklist_template_id` is NOT NULL.
        | _CLEANING_TEMPLATE_MANAGE
    ),
    UserRole.CLEANER: _SELF_SERVICE | _CLEANING_EXECUTE,
    UserRole.TECHNICIAN: _SELF_SERVICE,
}


def is_allowed(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
