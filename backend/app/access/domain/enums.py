import enum


class AccessProvider(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (AccessRecord.provider) without a named block (§7.16)."""

    GRINPASS = "GRINPASS"
    MANUAL = "MANUAL"
    MOCK = "MOCK"
    EXTERNAL_MANAGED = "EXTERNAL_MANAGED"


class AccessRecordStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (AccessRecord.status) without a named block (§7.16)."""

    PENDING = "PENDING"
    CREATED_EXTERNAL = "CREATED_EXTERNAL"
    MANUAL_ADDED = "MANUAL_ADDED"
    DELIVERED = "DELIVERED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AccessCreatedMode(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (AccessRecord.created_mode) without a named block (§7.16)."""

    EXTERNAL_PMS_AUTOMATIC = "EXTERNAL_PMS_AUTOMATIC"
    MANUAL = "MANUAL"
    MOCK = "MOCK"
