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
    # `revenue-reviews` (design D9). One new member, named for the verb R6.2 declares.
    # Same precedent `PASSWORD_RESET_REQUESTED` set for `auth-account-recovery`: PRD §14
    # has no slot for it, so it sits outside the catalogue's sixteen. The row carries
    # no SLA deadline (R6.2 says "notificación", not "con plazo") and no escalation —
    # the manager's notification arrives, the manager acts on it, and that is the end
    # of the row's lifecycle.
    REVIEW_RESPONSE_APPROVED = "REVIEW_RESPONSE_APPROVED"
    # The SEVENTEENTH, declared as a divergence from the sixteen of PRD §14
    # (`auth-account-recovery` R6.1). Same kind of divergence `access-notifications` declared
    # for its two jobs against PRD §8.3's four: the PRD's list is the operational catalogue —
    # cleanings, incidents, technicians, guests, prices, SLA — and password recovery is not an
    # operational event, so §14 has no slot for it. It is here rather than reusing a slot
    # because rule 9 of `steering/security.md` only makes an operation findable by filtering
    # on its own name.
    #
    # EXTERNAL_DEPENDENCY: rows of this type reach nobody until a real SMTP adapter arrives
    # with `hardening-release`. `EMAIL` resolves to `ConsoleEmailAdapter`, which
    # `specs/access-notifications.md` forbids from logging content or recipient — so not even
    # a developer can read the link from the log. See `docs/auth-account-recovery.md`.
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    # `staff-messaging` design D8. Two more, the same kind of divergence
    # `REVIEW_RESPONSE_APPROVED` and `PASSWORD_RESET_REQUESTED` already declared: PRD §14 has
    # no slot for a staff-to-manager thread scoped to a cleaning task or an incident, and the
    # body of each carries only ids and a constant text — never the message's `content` (R4).
    CLEANING_TASK_MESSAGE = "CLEANING_TASK_MESSAGE"
    INCIDENT_MESSAGE = "INCIDENT_MESSAGE"


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
