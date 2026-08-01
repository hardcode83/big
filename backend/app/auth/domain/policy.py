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


_SELF_SERVICE = frozenset({Permission.READ_OWN_PROFILE, Permission.MANAGE_OWN_SESSION})
_RESERVATION_READ = frozenset({Permission.READ_RESERVATIONS})
_RESERVATION_MANAGE = frozenset({Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS})
_USER_READ = frozenset({Permission.READ_USERS})
_USER_MANAGE = frozenset({Permission.READ_USERS, Permission.MANAGE_USERS})
_TENANT_SETTINGS_READ = frozenset({Permission.READ_TENANT_SETTINGS})
_TENANT_SETTINGS_MANAGE = frozenset(
    {Permission.READ_TENANT_SETTINGS, Permission.MANAGE_TENANT_SETTINGS}
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
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: _SELF_SERVICE,
    UserRole.TENANT_OWNER: (
        _SELF_SERVICE | _RESERVATION_READ | _USER_MANAGE | _TENANT_SETTINGS_MANAGE
    ),
    UserRole.PROPERTY_MANAGER: (
        _SELF_SERVICE | _RESERVATION_MANAGE | _USER_READ | _TENANT_SETTINGS_READ
    ),
    UserRole.CLEANER: _SELF_SERVICE,
    UserRole.TECHNICIAN: _SELF_SERVICE,
}


def is_allowed(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
