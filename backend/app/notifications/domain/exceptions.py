"""Stable domain errors of the notifications module."""


class NotificationDomainError(Exception):
    """Base class, so a caller can catch the module's errors without catching everything."""


class NotificationLogNotFoundError(NotificationDomainError):
    """A write addressed a notification log that is not there.

    Raised by `mark_breached` when the UPDATE matches no row. Separate from
    `CrossTenantWriteError` on purpose: that one names a cause we can prove (the entity
    says it belongs to another tenant), and this one covers the case where we cannot —
    the row vanished, or the session is bound to a tenant the caller did not mean. Both
    break R5.3's invariant, so both must be loud; only one of them may claim a reason.
    """

    def __init__(self, log_id) -> None:
        super().__init__(f"No notification log {log_id} within the acting tenant")
        self.log_id = log_id
