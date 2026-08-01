import enum


class IncidentCategory(str, enum.Enum):
    ACCESS = "ACCESS"
    LOCK = "LOCK"
    WIFI = "WIFI"
    ELECTRICITY = "ELECTRICITY"
    WATER = "WATER"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    APPLIANCE = "APPLIANCE"
    NOISE = "NOISE"
    CLEANING = "CLEANING"
    DAMAGE = "DAMAGE"
    SAFETY = "SAFETY"
    OTHER = "OTHER"


class IncidentStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLASSIFIED = "CLASSIFIED"
    AWAITING_OWNER_APPROVAL = "AWAITING_OWNER_APPROVAL"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_EXTERNAL_PARTS = "WAITING_EXTERNAL_PARTS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class IncidentSource(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Incident.source) without a named block (§7.13)."""

    GUEST = "GUEST"
    CLEANER = "CLEANER"
    OWNER = "OWNER"
    SYSTEM = "SYSTEM"
    PMS = "PMS"
    LOCK_ALERT = "LOCK_ALERT"


class IncidentSeverity(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Incident.severity) without a named block (§7.13). Not the same enum
    as TimelineSeverity (INFO/WARNING/ERROR/CRITICAL) — different values."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class OwnerApprovalRelatedType(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (OwnerApproval.related_type) without a named block (§7.19)."""

    INCIDENT = "INCIDENT"
    MAINTENANCE_COST = "MAINTENANCE_COST"
    OTHER = "OTHER"


class OwnerApprovalStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (OwnerApproval.status) without a named block (§7.19)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
