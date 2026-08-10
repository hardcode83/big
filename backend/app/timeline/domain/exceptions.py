class TimelineDomainError(Exception):
    """Base error for timeline-domain construction."""


class TimelineEventValidationError(TimelineDomainError):
    pass


class PropertyNotFoundError(TimelineDomainError):
    """The property whose timeline was asked for is not this tenant's (R4.5).

    Its own class rather than an import from `app/properties/domain/exceptions.py`, which
    is the convention `cleaning` and `reservations` already follow: each module owns its
    error hierarchy so that `api/errors.py` maps one base class and nothing leaks in from a
    neighbour's.

    **Raised identically for "does not exist" and "belongs to another tenant"**, because
    `PropertyRepository.get` returns `None` for both (design D11) — so the caller cannot
    tell the two apart from the response, which is the point.
    """


class TimelineFilterValidationError(TimelineDomainError):
    """The requested filter combination is a contradiction (`dashboard-api` R4.2).

    A domain error and not a router check, for the reason `ReservationFilters` records:
    `steering/backend.md` says "la lógica nunca vive en el router", so any future caller —
    a dashboard aggregate, a report — gets the same answer instead of silently receiving
    zero rows.
    """


class TimelineMetadataNotSerialisableError(TimelineDomainError):
    """`metadata` holds a value the `JSONB` column cannot store (design D2).

    Added by `reservations`, the first change that persists events. `TimelineEventFactory`
    checks that `metadata` IS a dict but not what is inside it, so a `date`, a `UUID` or a
    `Decimal` — the natural types of a reservation's own fields — reached the INSERT and
    came back as an opaque `StatementError`, i.e. a 500 with no indication of which field
    was at fault. Raising a typed domain error instead names the offending keys.

    Detected in the adapter rather than in the factory on purpose: the factory belongs to
    the archived `timeline-state-machine` capability, whose spec describes it as pure
    construction with no knowledge of storage. Tightening it is a candidate for the change
    that next touches that capability.
    """

