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


class IncidentPhotoStage(str, enum.Enum):
    """When in the job a photo of an incident was taken (`incident-photos` D3, R1.2).

    `ASSUMPTION`: **the name is invented and the entity is not in the PRD.** PRD §6 grants the
    `TECHNICIAN` only "subir fotos (antes y después)", and PRD §7 declares `CleaningPhoto`
    (§7.12) but no incident-photo entity at all — §7.13 `Incident` has no photo column. So both
    this enum's name and its two members are this project's, derived from that one phrase.

    **Two members, closed, and that is a decision rather than a starting point** (R1.2). A
    cleaning photo's kind is `cleaning_photos.photo_type`, a `String(100)`, because the task's
    checklist template declares which values are admissible — the template bounds it. An
    incident has no template, so a free-text stage coming from the caller would be a **new
    free-text sink** under rule 11 of `steering/security.md`, with no screen that ever displays
    it and nothing to close the set. The enum is what makes R6.5 true by construction instead of
    by review: there is no third value to send and no text field to fill.

    A third stage is a schema migration and a decision, deliberately. That is the cost of
    closing the set, and it is the cost worth paying here.
    """

    BEFORE = "BEFORE"
    AFTER = "AFTER"
