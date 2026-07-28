class TimelineDomainError(Exception):
    """Base error for timeline-domain construction."""


class TimelineEventValidationError(TimelineDomainError):
    pass
