"""Domain errors of the cleaning module (R1, R3, R4, R5, design D11).

Pure Python, exactly like `app/reservations/domain/exceptions.py`: no import of
`app.core.errors`, because that module imports FastAPI and pulling it in here would put
the web framework inside `domain/` transitively — where `tests/test_layering.py` would
not catch it. The translation to a status code lives in `app/cleaning/api/errors.py`.

Each error names a business outcome the callers have to tell apart (404 / 409 / 422), so
the mapping is a property of the outcome instead of a decision retaken per router.
"""


class CleaningDomainError(Exception):
    """Base error for the cleaning domain."""


class CleaningValidationError(CleaningDomainError):
    """An invariant of an aggregate was violated — answered 422."""


# The **one** message every not-found path uses. Two 404s with distinguishable bodies are
# the same probe R7.3 closes at the status-code layer, one level down: a body saying "not
# assigned to you" confirms the task exists and belongs to someone else, while an unknown id
# would have said something else. `reservations` reached the same conclusion the plain way —
# `ReservationNotFoundError("Reservation does not exist")` is a constant at all three of its
# call sites. Named by the security reviewer of section 1, on the second round.
#
# It carries no id for the same reason: `app/cleaning/api/errors.py` puts `str(exc)` into the
# response verbatim, exactly as `reservations/api/errors.py:46-47` does.
TASK_NOT_FOUND_MESSAGE = "Cleaning task does not exist"


class CleaningTaskNotFoundError(CleaningDomainError):
    """The task does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown or belongs to another tenant
    (R7.3). A separate "exists but is not yours" error would leak a neighbour's task
    through nothing more than an exception type — the reasoning `reservations` fixed for
    its own aggregates in its design D6.

    It also covers the row-level restriction of R7.2: a task of this tenant assigned to a
    different cleaner is, for that cleaner, indistinguishable from one that does not
    exist. Answering 403 there would turn the endpoint into a probe for which tasks
    exist.

    **The message defaults to a constant and callers do not override it.** Same status
    code with two different bodies is the same probe one layer down.
    """

    def __init__(self, message: str = TASK_NOT_FOUND_MESSAGE) -> None:
        super().__init__(message)


class PropertyNotFoundError(CleaningDomainError):
    """The referenced property does not exist within the acting tenant (R7.3) — 404.

    Its own class inside this hierarchy, and not the one `reservations` declares: D11 wires
    a single `@app.exception_handler(CleaningDomainError)`, so an exception from another
    module's tree would never reach it. Needed by the manual creation path
    (`POST /cleaning-tasks`), which takes a `property_id` from the client.
    """

    def __init__(self, message: str = "Property does not exist") -> None:
        super().__init__(message)


class ReservationNotFoundError(CleaningDomainError):
    """The referenced reservation does not exist within the acting tenant (R7.3) — 404.

    Its own class in this hierarchy for the same reason as `PropertyNotFoundError`: D11 wires
    one handler on `CleaningDomainError`, so `reservations`' own error would never reach it.
    """

    def __init__(self, message: str = "Reservation does not exist") -> None:
        super().__init__(message)


class ChecklistTemplateNotFoundError(CleaningDomainError):
    """No active checklist template resolves for the property (R1.3) — 404.

    Not the same as ambiguity below: here there is nothing to choose from.
    """


class AmbiguousChecklistTemplateError(CleaningDomainError):
    """Two or more active templates compete at the same resolution level (R1.4) — 409.

    Picking one by `id` or `created_at` would anchor the checklist's content to an
    arbitrary tie-break; the same reasoning by which `AdvancePropertyStatesUseCase`
    counts `ambiguous` instead of choosing a reservation
    (`app/properties/application/use_cases.py:201-215`).
    """


class ChecklistItemNotFoundError(CleaningDomainError):
    """The `item_id` does not belong to the task's template (R4.3) — 404."""


class InvalidCleaningTransitionError(CleaningDomainError):
    """The task's current status does not admit the requested operation (R3.7) — 409.

    Raised by the entity, never by the use case: the legal moves of a `CleaningTask` are
    a business rule, and `steering/backend-architecture.md` puts those in `domain/`.
    """


class ChecklistIncompleteError(CleaningDomainError):
    """Required checklist items are still open at completion time (R5.1) — 409.

    Carries the missing `item_id`s so the response can enumerate them: "you cannot
    finish" without saying what is left is an answer the cleaner cannot act on.
    """

    def __init__(self, missing_item_ids: tuple[str, ...]) -> None:
        self.missing_item_ids = missing_item_ids
        super().__init__(
            "Required checklist items are not completed: " + ", ".join(missing_item_ids)
        )


class BlockingIncidentError(CleaningDomainError):
    """An unresolved CRITICAL incident blocks completion (R5.2) — 409."""


class PropertyStateBlocksCleaningError(CleaningDomainError):
    """The property's state does not admit this move right now — answered 409.

    The translation of `IncompatibleTransitionContextError` / `InvalidStateTransitionError`,
    which come from the **properties** domain. That matters: `properties` has no `api/` layer
    and no error handler, so one of those escaping a cleaning endpoint is an unhandled 500.
    The design's own risk note already promised a 409 here ("cerrar una limpieza mientras el
    siguiente huésped ya está dentro devuelve 409 en vez de 500") and the mapping of D11 could
    not deliver it, because those errors are not `CleaningDomainError`s.

    The realistic case is R5.4's contextual resolution: `after_cleaning_completion` refuses to
    resolve while a booking is active (`state_resolution.py:128-131`), i.e. the next guest has
    already checked in.
    """


class DuplicateLiveCleaningTaskError(CleaningDomainError):
    """The reservation already has a live cleaning task (R2.5) — 409.

    Raised from the `IntegrityError` of `uq_cleaning_tasks_live_reservation` (design D2),
    so the partial index stays the authority and a concurrent run of `process_checkouts`
    cannot slip past a read-then-write check.
    """
