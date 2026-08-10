"""The port that makes the timeline persistent (design D2).

Until this change the timeline was pure domain: `TimelineEventFactory` built validated
events and nobody stored them (`sdd/specs/timeline-state-machine.md`: "no persiste ni muta
la propiedad"). That stays true of the domain — this is a port, and the adapter lives in
`infrastructure/`.

One method, deliberately. `steering/architecture.md` calls the timeline immutable: "nunca
se editan eventos pasados". A port with only `add` is that rule expressed in a signature —
there is no `save`, no `update`, no `delete` for anyone to reach for. Reading events back
belongs to the change that introduces the timeline endpoints.

That change is `dashboard-api`, and it did **not** add the read methods here. They live in
`TimelineEventReader`, a separate `Protocol` below (its design D2): Interface Segregation
as `steering/backend-architecture.md` asks for it — "puertos pequeños y por rol" — and,
more to the point, it keeps the property the paragraph above describes. `add` being the
only method of `TimelineEventRepository` is what makes immutability visible in a signature;
hanging two readers off it would have traded that guarantee for a shorter file.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.exceptions import TimelineFilterValidationError


class TimelineEventRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, event: TimelineEvent) -> None:
        """Append an event for the acting tenant. Never commits — the use case owns the
        transaction (design D4).

        **Precondition the caller must honour**: `property_id`, `reservation_id` and
        `actor_user_id` must already have been resolved *within* `tenant_id`. The foreign
        keys of `timeline_events` are global (not composite with `tenant_id`), so the
        database would accept an event of tenant A anchored to a property of tenant B, and
        this port cannot detect it without a query of its own. Every caller in this change
        satisfies it structurally — the property comes from
        `PropertyRepository.get/find_by_*` and the reservation from
        `ReservationRepository`, all tenant-scoped — and the composite foreign key that
        would make it impossible instead of merely wrong is recorded as debt in
        `sdd/changes/reservations/design.md` D18.
        """
        ...


@dataclass(frozen=True)
class TimelineFilters:
    """The AND-combined filters of `GET /api/v1/timeline/{property_id}` (R4.2).

    The five PRD §10 filters the frontend contract declares
    (`frontend/features/dashboard/data/dto.ts:111-117`). `from`/`to` are spelled
    `occurred_from`/`occurred_to` here because `from` is a Python keyword; the query
    parameters keep the contract's names, and the `api/` layer is where that alias lives.
    """

    event_type: TimelineEventType | None = None
    severity: TimelineSeverity | None = None
    actor_type: TimelineActorType | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None

    def __post_init__(self) -> None:
        if self.occurred_from is not None and self.occurred_to is not None:
            if self.occurred_to < self.occurred_from:
                raise TimelineFilterValidationError(
                    "to cannot be earlier than from"
                )
        for field_name in ("occurred_from", "occurred_to"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                # `created_at` is TIMESTAMPTZ; comparing it against a naive datetime is the
                # kind of silent off-by-two-hours that makes an audit trail lie.
                raise TimelineFilterValidationError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class Page:
    """One page of events plus the total the client needs for `total_pages` (PRD §23).

    Declared here rather than imported: `properties`, `reservations` and `auth` each own
    theirs, and there is no shared pagination helper in this codebase — following that
    keeps the domains uncoupled.
    """

    items: tuple[TimelineEvent, ...]
    total: int


class TimelineEventReader(Protocol):
    """The read side of the timeline (`dashboard-api` R4, design D2).

    Separate from `TimelineEventRepository` on purpose — see this module's docstring. It is
    also the port shape the aggregate needs: one paginated reader for the timeline endpoint
    and one batch reader for the dashboard collection, which must resolve N properties
    without N queries (R1.7).

    Both methods take `tenant_id` explicitly and return nothing outside it, which is what
    lets a foreign `property_id` answer `404` rather than `403` without the router writing
    a tenant check of its own (design D11).
    """

    async def list_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        filters: TimelineFilters,
        page: int,
        per_page: int,
    ) -> Page:
        """One page of a property's events, newest first (R4.1, design D8).

        Ordered by `created_at DESC` with `id DESC` as the tiebreaker. The second key is
        not decoration: several events of one business operation share the instant the use
        case decided on (the adapter writes `created_at` from the event, not from
        `now()`), so without it paging through a burst repeats rows and skips others.

        `total` counts the same filtered set as `items`, never the whole property.
        """
        ...

    async def last_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, TimelineEvent]:
        """The most recent event of each property, in **one** statement (R1.7).

        Keyed by `property_id`, and a property with no events is simply absent from the
        mapping rather than mapped to `None` — the caller already has to handle "no last
        event" for a property it did not ask about.

        An empty `property_ids` returns an empty mapping without querying.
        """
        ...
