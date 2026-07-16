import enum


class TenantStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class StorageType(str, enum.Enum):
    LOCAL = "LOCAL"
    S3 = "S3"
