"""The port that makes the timeline persistent (design D2).

Until this change the timeline was pure domain: `TimelineEventFactory` built validated
events and nobody stored them (`sdd/specs/timeline-state-machine.md`: "no persiste ni muta
la propiedad"). That stays true of the domain — this is a port, and the adapter lives in
`infrastructure/`.

One method, deliberately. `steering/architecture.md` calls the timeline immutable: "nunca
se editan eventos pasados". A port with only `add` is that rule expressed in a signature —
there is no `save`, no `update`, no `delete` for anyone to reach for. Reading events back
belongs to the change that introduces the timeline endpoints.
"""

import uuid
from typing import Protocol

from app.timeline.domain.entities import TimelineEvent


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
