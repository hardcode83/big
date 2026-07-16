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
