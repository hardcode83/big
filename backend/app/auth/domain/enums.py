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

    `USER_DEACTIVATED` and `PASSWORD_RESET` were added by `user-management` (design D7,
    D18). They are administrative: unlike `LOGOUT` and `REUSE_DETECTED`, the session's
    owner is NOT the actor. Both are needed because `POST /api/v1/auth/refresh` does not
    go through `get_authenticated_request`, so it never revalidates that the user is
    still ACTIVE — without revoking, a deactivated account keeps minting token pairs
    indefinitely even though its access tokens are rejected.

    Two values rather than one `ADMIN_REVOKED`, because `revoked_reason` exists to
    diagnose: "you were deactivated" and "your password was reset" are different answers
    to the same complaint.
    """

    LOGOUT = "LOGOUT"
    REUSE_DETECTED = "REUSE_DETECTED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    PASSWORD_RESET = "PASSWORD_RESET"
