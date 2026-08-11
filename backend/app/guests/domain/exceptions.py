"""Stable domain errors of the guests module (`access-notifications`)."""

import uuid


class GuestDomainError(Exception):
    """Base class, so a caller can catch the module's errors without catching everything."""


class GuestNotFoundError(GuestDomainError):
    """No guest with that id **within the acting tenant**.

    One error for both causes — absent and belonging to a neighbour — for the same reason
    `AccessRecordNotFoundError` gives: distinguishing them turns the endpoint into an
    existence oracle across tenants. It matters more here than anywhere else in the codebase,
    because what the oracle would be answering about is an identity document.
    """

    def __init__(self, guest_id: uuid.UUID | None = None) -> None:
        super().__init__("Guest does not exist")
        self.guest_id = guest_id


class GuestDocumentMissingError(GuestDomainError):
    """A read or a submission asked for a document the guest does not have."""

    def __init__(self) -> None:
        super().__init__("This guest has no identity document on file")


class LegalRegistrationNotReadyError(GuestDomainError):
    """A submission was requested for a stay that is not `READY_TO_SUBMIT` (R6.6).

    Carries the missing fields when that is the reason, so the operator is told *what* to go
    and get rather than only that they cannot proceed. Never carries a value — only names.
    """

    def __init__(self, *, current: str, missing: tuple[str, ...] = ()) -> None:
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        super().__init__(
            f"The legal registration of this reservation is {current}, not READY_TO_SUBMIT."
            + detail
        )
        self.current = current
        self.missing = missing


class ReservationNotFoundError(GuestDomainError):
    """The stay a legal registration was requested for does not exist in this tenant."""

    def __init__(self) -> None:
        super().__init__("Reservation does not exist")


class GuestPortalUnauthorised(GuestDomainError):
    """The presented portal token does not authorise anything (`guest-portal-api` R2.2, D5).

    **One exception for five causes, and that is the entire design.** R2.2 requires a code
    that "no distinga entre esas condiciones" — non-existent, malformed, revoked, outside the
    window, or belonging to a cancelled stay — so that an anonymous caller cannot learn
    whether a reservation exists. A hierarchy of causes here would put that guarantee in the
    hands of everyone who catches it.

    It carries **no detail and no cause**: no `__cause__` chained, no reservation id, no
    reason. `str(exc)` is a constant, and every portal route answers it through the single
    helper that emits one constant `404` body — the four routes of PRD §23 go through it, none
    of them able to drift from the others.

    The same reasoning as `GuestNotFoundError` one class up, applied where it matters more:
    that one protects an identity document from an authenticated operator of another tenant;
    this one protects the existence of a booking from the whole internet.
    """

    def __init__(self) -> None:
        super().__init__("Not found")
