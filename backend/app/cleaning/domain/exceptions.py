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


class PhotosIncompleteError(CleaningDomainError):
    """Required photos are still missing at completion time (R4.1, R4.2) — 409.

    The photo twin of `ChecklistIncompleteError`, deliberately built the same way: it carries
    the missing `photo_type`s so the 409 can enumerate them, because a cleaner told only "you
    cannot finish" has to guess which room to go back to. R4.2 asks for the enumeration "in the
    same format the items are enumerated in today", and the format the items use is this
    message — the cleaning handler serialises `str(exc)` and the envelope's `details` stays
    empty for every other error of this module.

    A **sibling** of `ChecklistIncompleteError` and not a subclass. They map to the same status
    for the same reason and share a shape, but `isinstance` between them would be a lie: an
    `except ChecklistIncompleteError` written to retry a checklist would swallow a photo
    refusal it knows nothing about, and the error table in `api/errors.py` is ordered
    subclass-first precisely because that relationship is load-bearing there.
    """

    def __init__(self, missing_photo_types: tuple[str, ...]) -> None:
        self.missing_photo_types = missing_photo_types
        super().__init__(
            "Required photos are not uploaded: " + ", ".join(missing_photo_types)
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


class PhotoTypeNotFoundError(CleaningDomainError):
    """The `photo_type` is not one the task's template declares (R2.2) — 404.

    The photo counterpart of `ChecklistItemNotFoundError`, and answered the same way for the
    same reason: R2.2 asks for "the same 404 the checklist gives an unknown `item_id`". A 422
    would be defensible in isolation and is wrong here — it would tell a caller that the value
    is well-formed but absent, which over a template it cannot read is one bit more than the
    404 gives.
    """


class UnsupportedPhotoFormatError(CleaningDomainError):
    """The uploaded bytes are not an image format the allowlist accepts (R2.4) — 422.

    A **sibling** of `CleaningValidationError` and not a subclass of it, although the outcome
    is the same 422. Every entry of `_MAPPING` in `api/errors.py` is resolved by
    `isinstance` with first-match-wins, so a subclass is correct only while its row happens to
    sit above its base's — a property of the literal's line order, not of the type. Keeping
    the hierarchy flat, as every other error in this module is, removes the hazard instead of
    documenting it.

    Determined from the **content** (`detect_image_type`) and never from the `Content-Type` the
    client declared, which is rule 6 of `steering/security.md` and R2.4.
    """


class PhotoTooLargeError(CleaningDomainError):
    """The upload exceeded `photo_upload_max_bytes` (R2.5) — 413.

    Raised while the file is being consumed in chunks, which is the second half of design
    D11's pair. The first half is `MaxBodySizeMiddleware`, and it is the half that actually
    satisfies R2.5 — including for a client that lies in `Content-Length` or sends
    `Transfer-Encoding: chunked`. This one bounds the in-process copy and covers callers with
    no middleware in front. Two checks, one number (`settings.photo_upload_max_bytes`).

    Do not restate the reasoning here: it lives in one place, rule 14 of
    `sdd/steering/security.md`. It was previously duplicated across five files and four of
    them drifted into claiming the opposite.
    """


class PhotoStorageUnavailableError(CleaningDomainError):
    """The storage backend refused or failed the write (R1.5) — 502.

    The translation of `StorageWriteError`, which comes from `app/integrations/domain/`: like
    the properties errors above, it is not a `CleaningDomainError`, so without this it would
    escape a cleaning endpoint as an unhandled 500. R1.5 asks for a `502` in the PRD §23
    envelope, and 502 is the honest code — the failure is a dependency's, not the caller's.

    **No row is left behind when this is raised.** The object is written before the row
    (design D4), so a failure here happens before anything was inserted; the opposite
    direction — a commit that fails after the object landed — is compensated by deleting the
    object, not by leaving a row pointing at nothing (R1.5).
    """


class DuplicateLiveCleaningTaskError(CleaningDomainError):
    """The reservation already has a live cleaning task (R2.5) — 409.

    Raised from the `IntegrityError` of `uq_cleaning_tasks_live_reservation` (design D2),
    so the partial index stays the authority and a concurrent run of `process_checkouts`
    cannot slip past a read-then-write check.
    """
