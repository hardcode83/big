"""What a delivery attempt returns (`access-notifications` design D8, PRD §14).

**The error is an enum, not a string, and that is the whole point.** `notification_logs
.last_error` is one of the cleartext sinks of rule 11 in `sdd/steering/security.md`, whose
contract for this column is the structured form: no rule-3 value survives in it at all. Who
writes it is declared in that rule's table.

Making the code a closed enum moves that guarantee from discipline to construction: a
provider SDK's exception routinely embeds the very message it failed to send — subject,
body, recipient — and the natural `str(exc)` would carry it straight into the column. It
**does not fit in the return type**, so no adapter can pass it on without changing this
file, which is a diff a reviewer sees.

Same shape as `ChangeSet` in `app/audit/domain/value_objects.py`, and for the same reason:
rule 11 records that three consecutive reviews found a leak when the contract rested on
every caller remembering it.
"""

import enum
from dataclasses import dataclass


class NotificationErrorCode(str, enum.Enum):
    """Why a delivery attempt did not succeed.

    Deliberately coarse. A finer taxonomy would be guesswork today — the only adapters are
    a console logger and two mocks — and every value here has to be one a *future* SMTP or
    WhatsApp adapter can map onto without inventing a category. What the operator needs to
    tell apart is: our fault, their address, the network, and "we gave up".
    """

    #: The adapter raised or reported a failure it could not classify further.
    ADAPTER_ERROR = "ADAPTER_ERROR"
    #: `recipient_contact` is empty or not addressable on this channel.
    INVALID_RECIPIENT = "INVALID_RECIPIENT"
    #: The provider did not answer in time.
    TIMEOUT = "TIMEOUT"
    #: No adapter is registered for the row's channel (R4.5).
    NO_ADAPTER_FOR_CHANNEL = "NO_ADAPTER_FOR_CHANNEL"
    #: `notification_max_attempts` reached; the row moves to `FAILED` (R4.4).
    MAX_ATTEMPTS_EXCEEDED = "MAX_ATTEMPTS_EXCEEDED"
    #: A WhatsApp free-text send was attempted more than 24h after the guest's last inbound
    #: message (or with no known inbound message at all) and no `template_id` was supplied to
    #: fall back to (`whatsapp-cloud-adapter` design D2, R2.1/R2.3).
    OUTSIDE_SESSION_WINDOW = "OUTSIDE_SESSION_WINDOW"


@dataclass(frozen=True)
class NotificationResult:
    """The outcome of one `NotificationAdapter.send`.

    **There is no string field at all**, and that is a decision, not an omission. An earlier
    version carried `provider_message_id: str | None` — an opaque handle for support, said
    the docstring — and the security panel of sections 1-2 named it for what it was: an
    unconstrained `str` in the one return type D8 exists to keep text out of, guarded by
    prose rather than by the type. Nothing consumed it: `record_attempt` does not accept it
    and no caller logged it. So it went, and the guarantee is now total — a future adapter
    that wants to bring the provider's response back has to change this file, which is a
    diff a reviewer sees.
    """

    delivered: bool
    error_code: NotificationErrorCode | None = None

    def __post_init__(self) -> None:
        """A result cannot be both delivered and failed, nor failed without a reason.

        Checked here rather than trusted, because `record_attempt` branches on exactly
        these two fields: a delivered result with an error code would write `SENT` **and**
        a `last_error`, and a failure with no code would write a `last_error` of `null`
        that tells the operator nothing.
        """
        if self.delivered and self.error_code is not None:
            raise ValueError("a delivered result carries no error code")
        if not self.delivered and self.error_code is None:
            raise ValueError("a failed result must name its error code")

    @classmethod
    def ok(cls) -> "NotificationResult":
        return cls(delivered=True)

    @classmethod
    def failure(cls, error_code: NotificationErrorCode) -> "NotificationResult":
        return cls(delivered=False, error_code=error_code)
