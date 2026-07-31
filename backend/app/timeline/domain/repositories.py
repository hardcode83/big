"""The port that makes the timeline persistent (design D2).

Until this change the timeline was pure domain: `TimelineEventFactory` built validated
events and nobody stored them (`sdd/specs/timeline-state-machine.md`: "no persiste ni
muta la propiedad"). That stays true of the domain — this is a port, and the adapter
lives in `infrastructure/`.

One method, deliberately. `steering/architecture.md` calls the timeline immutable:
"nunca se editan eventos pasados". A port with only `add` is that rule expressed in a
signature — there is no `save`, no `update`, no `delete` for anyone to reach for.
Reading events back belongs to the change that introduces the timeline endpoints.
"""

from typing import Protocol

from app.timeline.domain.entities import TimelineEvent


class TimelineEventRepository(Protocol):
    async def add(self, event: TimelineEvent) -> None:
        """Append an event. Never commits — the use case owns the transaction (D4)."""
        ...
