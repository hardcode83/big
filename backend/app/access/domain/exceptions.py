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


class AccessCodeInNotesError(AccessDomainError):
    """The operator pasted the access code into the free-text `notes` of the same request.

    Found by the security panel at feature scale, and the gap it names is exact: `code` is
    masked and discarded, but `notes` was persisted verbatim in `access_records.notes` and
    served in every listing to every holder of `READ_ACCESS_RECORDS` — so the one request
    that exists to *not* store a code stored it, one field over. R2.6 says "en ningún punto".

    This is the only place in the system where both strings are in hand at once, which is why
    the check lives here and not in a validator: it is decidable exactly here and nowhere
    else. It does not — and cannot — stop somebody writing a *different* code into `notes`;
    whether `access_records.notes` should join rule 11's table of cleartext sinks is a
    steering decision, recorded in this change's `BLOCKED.md`.
    """

    def __init__(self) -> None:
        super().__init__(
            "The notes must not contain the access code. Only its masked form is stored, "
            "and free text is not."
        )


class AccessCodeRequiredError(AccessDomainError):
    """An empty or whitespace-only access code.

    Its own error rather than a generic validation one because of what the alternative
    would do: `mask_access_code("")` returns `"****"`, so a blank code would be stored as a
    perfectly ordinary-looking mask and the record would claim a code exists when none does.
    """

    def __init__(self) -> None:
        super().__init__("An access code is required")
