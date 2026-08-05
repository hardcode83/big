import enum


class NotificationType(str, enum.Enum):
    """The sixteen types of PRD §14, with its exact names.

    A Python enum over a `String(100)` column, deliberately: `notification_logs
    .notification_type` was created as free text by `domain-foundation-financial` and
    stays that way, so this needs **no migration** and cannot reject a row written before
    it existed. What it buys is an exhaustive escalation policy — `escalation_for` can be
    tested against every member, which a string could not be.

    Added by `celery-jobs`, whose SLA job (PRD §14) is the first code that has to decide
    what a `notification_type` *means*. `access-notifications` owns the sending side and
    inherits these names.
    """

    CLEANING_TASK_ASSIGNED = "CLEANING_TASK_ASSIGNED"
    CLEANING_NO_RESPONSE = "CLEANING_NO_RESPONSE"
    CLEANING_COMPLETED = "CLEANING_COMPLETED"
    CLEANING_FAILED = "CLEANING_FAILED"
    INCIDENT_CREATED_CRITICAL = "INCIDENT_CREATED_CRITICAL"
    INCIDENT_CREATED_HIGH = "INCIDENT_CREATED_HIGH"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    TECHNICIAN_ASSIGNED = "TECHNICIAN_ASSIGNED"
    TECHNICIAN_NO_RESPONSE = "TECHNICIAN_NO_RESPONSE"
    GUEST_ESCALATION = "GUEST_ESCALATION"
    LOCK_ALERT = "LOCK_ALERT"
    CHECKIN_REMINDER_24H = "CHECKIN_REMINDER_24H"
    CHECKIN_REMINDER_2H = "CHECKIN_REMINDER_2H"
    CHECKOUT_REMINDER = "CHECKOUT_REMINDER"
    PRICE_RECOMMENDATION = "PRICE_RECOMMENDATION"
    SLA_BREACH = "SLA_BREACH"


class NotificationChannel(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (NotificationLog.channel) without a named block (§7.24). Not the same enum as
    ConversationChannel (§7.14): PUSH, IN_APP and CONSOLE do not exist there."""

    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    PUSH = "PUSH"
    IN_APP = "IN_APP"
    CONSOLE = "CONSOLE"


class NotificationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (NotificationLog.status) without a named block (§7.24)."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
