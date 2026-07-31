class TimelineDomainError(Exception):
    """Base error for timeline-domain construction."""


class TimelineEventValidationError(TimelineDomainError):
    pass


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

