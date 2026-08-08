"""Stable domain errors of the access module."""

import uuid


class AccessDomainError(Exception):
    """Base class, so a caller can catch the module's errors without catching everything."""


class AccessRecordNotFoundError(AccessDomainError):
    """No access record with that id **within the acting tenant**.

    One error for both causes — absent and belonging to a neighbour — on purpose, and it is
    the same choice `NotificationLogNotFoundError` documents: distinguishing them would turn
    the endpoint into an existence oracle across tenants (R3.3).
    """

    def __init__(self, record_id: uuid.UUID | None = None) -> None:
        super().__init__("Access record does not exist")
        self.record_id = record_id


class InvalidAccessTransitionError(AccessDomainError):
    """A transition the state machine of design D14 does not allow (R2.5).

    Carries both states so the API layer can say which move was refused without the router
    having to reconstruct it.
    """

    def __init__(self, *, current: str, requested: str) -> None:
        super().__init__(f"Cannot move an access record from {current} to {requested}")
        self.current = current
        self.requested = requested


class AccessCodeRequiredError(AccessDomainError):
    """An empty or whitespace-only access code.

    Its own error rather than a generic validation one because of what the alternative
    would do: `mask_access_code("")` returns `"****"`, so a blank code would be stored as a
    perfectly ordinary-looking mask and the record would claim a code exists when none does.
    """

    def __init__(self) -> None:
        super().__init__("An access code is required")
