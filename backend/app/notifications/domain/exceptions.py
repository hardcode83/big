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


class SMTPConfigurationError(NotificationDomainError):
    """`SMTP_HOST` is set but the relay config is partial (`smtp-delivery-adapter` R2.2, D2).

    Raised by `adapter_registry()`, not at import: `Settings` accepts every `SMTP_*` field
    empty (R2.1, a deployment with no relay must still start), so this is the one place that
    can tell "not configured" from "half configured" apart — and the second one must be loud,
    never a silent fall-through to `ConsoleEmailAdapter`. Same shape as
    `ConfiguredFileStorageFactory.storage_for()` raising `StorageWriteError`: refuse at the
    point something is actually asked to use the broken config.
    """

    def __init__(self, missing_field: str) -> None:
        super().__init__(
            f"SMTP_HOST is configured but {missing_field} is missing; "
            "set it or clear SMTP_HOST to fall back to ConsoleEmailAdapter"
        )
        self.missing_field = missing_field


class NotificationNotFoundError(NotificationDomainError):
    """A reader addressed a notification that is not theirs to address (R1.4).

    Sibling of `NotificationLogNotFoundError` and NOT the same case: that one covers a
    write of the dispatcher or the SLA job that found no row, which is a broken invariant
    and names the id it could not reach. This one covers a request from the outside, where
    naming anything is the failure.

    **The message is a constant, and that is the requirement, not tidiness.** R1.4 says the
    body must not distinguish "does not exist" from "another user's" from "another tenant's"
    — a `403`, or a message carrying the id, would confirm that a row exists and turn the
    endpoint into an existence oracle. The three cases already collapse upstream, in the
    single `UPDATE` of design D3 whose `rowcount == 0` cannot tell them apart; this class is
    what keeps them collapsed on the way out.
    """

    def __init__(self) -> None:
        super().__init__("No such notification")
