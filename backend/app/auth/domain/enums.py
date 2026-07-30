import enum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    TENANT_OWNER = "TENANT_OWNER"
    PROPERTY_MANAGER = "PROPERTY_MANAGER"
    CLEANER = "CLEANER"
    TECHNICIAN = "TECHNICIAN"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class SessionRevokedReason(str, enum.Enum):
    """Why a session was REVOKED — not why it stopped being usable.

    There is no `ROTATED`: consuming a session on rotation sets `used_at`, and a
    rotation is not a revocation. Carrying the value would put a reason on rows whose
    `revoked_at` is NULL, which is a trap for any query filtering on the reason.
    """

    LOGOUT = "LOGOUT"
    REUSE_DETECTED = "REUSE_DETECTED"
