"""Response DTOs of the timeline endpoint (PRD §23, `dashboard-api` R4).

One rule this module exists to enforce: **`metadata` is not here, in any form.** R4.3 calls
it free JSON that is not part of the read contract, and the projection it is built from
(`RenderedEntry`) does not carry it either — so there are two structural refusals rather
than one remembered omission. Fields are enumerated and mapped explicitly, never dumped
with `from_attributes`, for the reason `PropertyResponse` records: an entity gains fields
over time and a dump publishes each new one automatically.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.rendering import RenderedEntry

MAX_PER_PAGE = 100
# Same ceiling and same reason as `properties` and `reservations`: the value becomes a SQL
# OFFSET, and a 20-digit page number overflows int8 and returns a driver error instead of a
# `422` in the PRD §23 envelope.
MAX_PAGE = 100_000


class TimelineEntryResponse(BaseModel):
    """One entry — the fields of `TimelineEntry`
    (`frontend/features/dashboard/data/dto.ts:99-108`), in this API's snake_case.

    `actor_type`, `event_type` and `severity` travel as the exact canonical literals and
    are never translated (R5.5). `title` is the composed, localised text (R5.1).
    `description` is **not**: it carries operator-written text — the reason a property was
    blocked or taken out of service — and is returned verbatim, in whatever language it was
    typed. Declared as an `ASSUMPTION` under R5.1 and reasoned in `domain/rendering.py`.
    """

    id: uuid.UUID
    occurred_at: datetime
    actor_type: TimelineActorType
    event_type: TimelineEventType
    severity: TimelineSeverity
    title: str
    description: str | None

    @classmethod
    def from_rendered(cls, entry: RenderedEntry) -> "TimelineEntryResponse":
        return cls(
            id=entry.id,
            occurred_at=entry.occurred_at,
            actor_type=entry.actor_type,
            event_type=entry.event_type,
            severity=entry.severity,
            title=entry.title,
            description=entry.description,
        )


class TimelinePageResponse(BaseModel):
    """The pagination envelope of PRD §23."""

    data: list[TimelineEntryResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, entries: tuple[RenderedEntry, ...], *, total: int, page: int, per_page: int
    ) -> "TimelinePageResponse":
        return cls(
            data=[TimelineEntryResponse.from_rendered(entry) for entry in entries],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )
