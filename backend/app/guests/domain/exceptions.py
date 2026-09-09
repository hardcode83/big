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


class GuestContactMissingError(GuestDomainError):
    """There is nobody to email the portal link to (`guest-link-delivery` R3.2).

    Two causes, **told apart on purpose**, which is the opposite of what `GuestNotFoundError`
    one class up does — and the difference is the whole reason this is a separate exception.
    That one collapses "absent" and "belongs to a neighbour" because separating them would
    answer a question about another tenant's data. This one is raised only *after* the stay has
    already resolved inside the acting tenant, so both messages describe rows the caller is
    entitled to read, and R3.2 asks for a refusal the operator can act on: "link this stay to a
    guest" and "put an address on the guest you already linked" are two different chores.

    It is not `GuestNotFoundError` for the same reason it is not `ReservationNotFoundError`:
    both of those mean `404`, and on the send route a `404` means "this reservation is not
    yours". Nothing here is missing in that sense — the reservation is there and is the
    caller's; it is simply not yet in a state that can receive a link. That is a `422`.

    Raised **before anything is minted** (design D4 step 2). A caller that sees it has changed
    no state at all, so fixing the guest and retrying is a clean operation rather than a
    second token on top of an orphaned first one.
    """

    #: The stay has no `guest_id` yet — legal before check-in, since `POST /reservations`
    #: allows a booking without a guest (`guest-portal-api` OQ3).
    NO_GUEST = (
        "This reservation has no guest linked yet, so there is no address to send the "
        "portal link to. Link a guest with an email address and try again."
    )
    #: The guest exists and has no usable address. Also covers a `guest_id` that resolves to
    #: nothing — see `SendGuestAccessTokenUseCase` for why that folds in here.
    NO_EMAIL = (
        "The guest linked to this reservation has no email address on file, so the portal "
        "link cannot be delivered. Add an email address to the guest and try again."
    )

    def __init__(self, message: str) -> None:
        super().__init__(message)


class GuestPortalUnauthorised(GuestDomainError):
    """The presented portal token does not authorise anything (`guest-portal-api` R2.2, D5).

    **One exception for five causes, and that is the entire design.** R2.2 requires a code
    that "no distinga entre esas condiciones" — non-existent, malformed, revoked, outside the
    window, or belonging to a cancelled stay — so that an anonymous caller cannot learn
    whether a reservation exists. A hierarchy of causes here would put that guarantee in the
    hands of everyone who catches it.

    It carries **no detail and no cause**: no `__cause__` chained, no reservation id, no
    reason. `str(exc)` is a constant, and every portal route answers it through the single
    helper that emits one constant `404` body — **every** portal route goes through it, none of
    them able to drift from the others. Stated as "every" and not as a tally: the surface has
    grown twice since this sentence was written, and what has to stay true is that no route
    bypasses the helper, which is a property a number cannot express.

    The same reasoning as `GuestNotFoundError` one class up, applied where it matters more:
    that one protects an identity document from an authenticated operator of another tenant;
    this one protects the existence of a booking from the whole internet.
    """

    def __init__(self) -> None:
        super().__init__("Not found")
