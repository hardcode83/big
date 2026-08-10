"""Reading a property's timeline (`dashboard-api` R4, R5).

The `application/` layer of `timeline`, which did not exist: until now the module was a
factory plus a write port, and the events were recorded by *other* domains' use cases. The
`api/` layer of R4 needs a use case to go through — `steering/backend-architecture.md` puts
"acceso a `infrastructure/` directo" among the things `api/` must not contain — so this is
where the two steps that make a timeline readable live: prove the property is the caller's,
then render what it holds in the caller's language.
"""

import uuid
from dataclasses import dataclass

from app.core.i18n import Locale
from app.properties.domain.repositories import PropertyRepository
from app.timeline.domain.exceptions import PropertyNotFoundError
from app.timeline.domain.rendering import RenderedEntry, render
from app.timeline.domain.repositories import TimelineEventReader, TimelineFilters


@dataclass(frozen=True)
class RenderedPage:
    entries: tuple[RenderedEntry, ...]
    total: int


class GetPropertyTimelineUseCase:
    def __init__(
        self, *, properties: PropertyRepository, events: TimelineEventReader
    ) -> None:
        self._properties = properties
        self._events = events

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        filters: TimelineFilters,
        page: int,
        per_page: int,
        locale: Locale,
    ) -> RenderedPage:
        """One page of the property's history, readable in `locale`.

        **The property lookup is not redundant with the event query**, which is the obvious
        objection: `list_for_property` already returns nothing outside the tenant, so the
        page would come back empty either way. Empty is `200`, and R4.5 requires `404` —
        for a property that does not exist and for a neighbour's alike. Without this read,
        a caller could tell "your flat has no events yet" from "that flat is not yours" by
        the status code, which is exactly the distinction design D11 refuses to publish.
        """
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise PropertyNotFoundError("Property does not exist")

        found = await self._events.list_for_property(
            tenant_id, property_id, filters=filters, page=page, per_page=per_page
        )
        return RenderedPage(
            entries=tuple(render(event, locale) for event in found.items),
            total=found.total,
        )
