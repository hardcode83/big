"""Domain errors of the maintenance module (R1-R5, design D5, D11, D14).

Pure Python, exactly like `app/cleaning/domain/exceptions.py`: no import of
`app.core.errors`, because that module imports FastAPI and pulling it in here would put the
web framework inside `domain/` transitively. The translation to a status code lives in
`app/maintenance/api/errors.py`.

The hierarchy is **flat on purpose**. `api/errors.py` resolves its table by `isinstance`
with first-match-wins, so a subclass is only answered correctly while its row happens to sit
above its base's — a property of the literal's line order, not of the type. `cleaning`
reached the same conclusion and states it in `UnsupportedPhotoFormatError`.
"""

import uuid


class MaintenanceDomainError(Exception):
    """Base error for the maintenance domain."""


class MaintenanceValidationError(MaintenanceDomainError):
    """An invariant of an aggregate was violated — answered 422."""


# The **one** message every incident not-found path uses. Two 404s with distinguishable
# bodies are a probe: a body saying "not assigned to you" confirms the incident exists and
# belongs to someone else, which is exactly what R5.3 closes at the status-code layer.
INCIDENT_NOT_FOUND_MESSAGE = "Incident does not exist"


class IncidentNotFoundError(MaintenanceDomainError):
    """The incident does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown, belongs to another tenant
    (R5.4), or belongs to a technician who is not the caller (R5.3). The message defaults
    to a constant and callers do not override it.
    """

    def __init__(self, message: str = INCIDENT_NOT_FOUND_MESSAGE) -> None:
        super().__init__(message)


class OwnerApprovalNotFoundError(MaintenanceDomainError):
    """The approval does not exist within the acting tenant (R2.6) — answered 404."""

    def __init__(self, message: str = "Owner approval does not exist") -> None:
        super().__init__(message)


class InvalidIncidentTransitionError(MaintenanceDomainError):
    """The incident's current status does not admit the requested move (R4.4) — 409.

    Raised by the entity against its own transition table, never by a use case: the legal
    moves of an `Incident` are a business rule, and `steering/backend-architecture.md` puts
    those in `domain/`.
    """


class IncidentAlreadyClosedError(MaintenanceDomainError):
    """The incident is in a terminal status (`RESOLVED`/`CANCELLED`) — answered 409.

    Its own class rather than an `InvalidIncidentTransitionError`, because a closed
    incident is not "the wrong step in the flow": no later step will ever admit it, so the
    caller has nothing to retry.
    """


class IncidentBlockedByPendingApprovalError(MaintenanceDomainError):
    """The incident is waiting for the owner to answer an approval (R2.1) — 409."""


class OwnerApprovalAlreadyAnsweredError(MaintenanceDomainError):
    """The approval was already answered and cannot be answered twice (R2.6) — 409."""


class InvalidTechnicianError(MaintenanceDomainError):
    """The proposed assignee is not a `TECHNICIAN` of this tenant (R3.4) — 422.

    A **sibling** of `MaintenanceValidationError` and not a subclass, although the outcome
    is the same 422: the flat hierarchy this module's header describes is what keeps
    `api/errors.py` independent of the order of its own table.
    """

    def __init__(self, technician_id: uuid.UUID) -> None:
        self.technician_id = technician_id
        super().__init__("Assignee is not a technician of this tenant")
