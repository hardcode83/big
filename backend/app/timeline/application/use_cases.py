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
from app.timeline.domain.read_models import TenantActivityEntry, from_rendered
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


@dataclass(frozen=True)
class RenderedTenantPage:
    entries: tuple[TenantActivityEntry, ...]
    total: int


class ListTenantActivityUseCase:
    """`GET /api/v1/timeline`: the tenant's activity across every property, readable in
    `locale` (`dashboard-activity-feed` R1, R3, R4; design D5, D6, D9).

    A collection endpoint, not a resource one (design D9): there is no `property_id` in the
    route that could fail to exist, so — unlike `GetPropertyTimelineUseCase` — there is no
    `PropertyRepository.get` pre-check and no 404 path here. A tenant with no properties or
    no events simply gets an empty page.

    Composition mirrors `ListReservationsUseCase`
    (`app/reservations/application/use_cases.py`, design D3 of `reservation-property-identity`):
    the page query runs once, then the DISTINCT `property_id`s of that page are resolved in
    ONE batch call to `properties.list_for_ids`, never per row. `PropertyRepository.list_for_ids`
    already short-circuits on empty input (no SQL trip), so an empty page needs no extra
    guard here to keep the statement count at zero for that call.
    """

    def __init__(
        self, *, properties: PropertyRepository, events: TimelineEventReader
    ) -> None:
        self._properties = properties
        self._events = events

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: TimelineFilters,
        page: int,
        per_page: int,
        locale: Locale,
    ) -> RenderedTenantPage:
        found = await self._events.list_for_tenant(
            tenant_id, filters=filters, page=page, per_page=per_page
        )
        rendered = [render(event, locale) for event in found.items]

        property_ids = {event.property_id for event in found.items}
        properties_by_id = {
            prop.id: prop
            for prop in await self._properties.list_for_ids(tenant_id, property_ids)
        }

        entries = tuple(
            from_rendered(
                entry,
                property_id=event.property_id,
                property_name=(
                    properties_by_id[event.property_id].name
                    if event.property_id in properties_by_id
                    else None
                ),
                property_internal_code=(
                    properties_by_id[event.property_id].internal_code
                    if event.property_id in properties_by_id
                    else None
                ),
            )
            for event, entry in zip(found.items, rendered, strict=True)
        )
        return RenderedTenantPage(entries=entries, total=found.total)
