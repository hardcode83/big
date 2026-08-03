"""`ChannexAdapter` — a real implementation of the PMS port (R2, design D1, D7 bis).

Reads `GET /bookings`, not the Booking Revisions Feed. The feed is what Channex prescribes for
PMS integrations, and it was rejected on purpose (design D1): it is an acknowledged queue, so
consuming it turns a read into a destructive write against the provider and makes the sync
unrepeatable. `PMSAdapter.list_reservations` promises neither of those things.

**The price of that choice, and it is a finding rather than a bug** (R6): `/bookings` filters
on `arrival_date`, `departure_date` and `inserted_at` — there is **no filter on modification
date**. So `list_reservations(since)` sees reservations *created* after `since` and will not
see a modification or a cancellation of an older one. That is fine for validating the backend
against a real PMS, which is what this adapter is for, and it is NOT fine as the basis of a
production sync. `pms-beds24-adapter` inherits the problem and has to solve it differently.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from app.integrations.domain.dtos import ReservationDTO
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.channex.mapping import to_reservation_dto

BOOKINGS_PATH = "/bookings"

logger = logging.getLogger(__name__)


class ChannexAdapter:
    """Implements `PMSAdapter` over the Channex REST API.

    Substitutable for `MockPMSAdapter` by contract, not by coincidence: the same DTO shape, the
    same `None` for an unknown id, the same tolerance of rows the ingestor will reject.
    """

    def __init__(self, client: ChannexClient) -> None:
        self._client = client
        self.unmappable_rows: list[str] = []

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> list[ReservationDTO]:
        params: dict[str, str] = {"filter[inserted_at][gte]": _channex_timestamp(since)}
        if property_external_id is not None:
            params["filter[property_id]"] = property_external_id
        elements = await self._client.get_collection(BOOKINGS_PATH, params=params)

        # **Per element, not a bare comprehension.** A single booking with a missing
        # `arrival_date` or an `occupancy` shaped as a list used to raise out of here and take
        # the WHOLE sync with it — every good row in the page lost, surfacing as a raw traceback
        # because `pms_sync.main` only catches `UnknownTenantError` and `PmsUnavailableError`.
        # Worse, `mapping._date`'s own docstring claimed the ingestor would catch it: it cannot,
        # because mapping happens HERE, before any row reaches
        # `ReservationIngestor.ingest`'s per-row `try/except`. The CSV route
        # (`infrastructure/csv_parser.py`) has always wrapped per row; this did not.
        #
        # **Known limitation of the port, and it is design input for `pms-beds24-adapter`**:
        # `PMSAdapter.list_reservations` returns `list[ReservationDTO]` and has nowhere to report
        # a row it could not map — unlike `ReservationCsvParser`, whose `ParseResult` carries
        # `failures` precisely for this. So the count is exposed on the adapter and printed by
        # the CLI: skipped rows must not be silent, which is the same reason pagination raises
        # instead of truncating (design D6).
        self.unmappable_rows = []
        rows: list[ReservationDTO] = []
        for element in elements:
            try:
                rows.append(to_reservation_dto(element))
            except Exception as error:  # noqa: BLE001 - any malformed shape, not a known set
                reference = _element_reference(element)
                self.unmappable_rows.append(f"{reference} — {type(error).__name__}: {error}")
                # The provider's id and the error class only. NOT the payload: it carries guest
                # name, email, phone and address, and a log line is a plain-text sink.
                logger.warning(
                    "channex: could not map booking %s (%s)", reference, type(error).__name__
                )
        return rows

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """`None` when Channex has no such booking — never an error.

        The port says so and `MockPMSAdapter` behaves that way; an absent id is an answer, not
        a failure. `ChannexClient.get_resource` turns the provider's 404 into `None`.
        """
        element = await self._client.get_resource(f"{BOOKINGS_PATH}/{external_id}")
        if element is None:
            return None
        return to_reservation_dto(element)


def _element_reference(element: Any) -> str:
    """Enough to find the booking in the Channex panel, and nothing more.

    `unique_id` if it is there, else the element `id`. Deliberately never the payload.
    """
    if isinstance(element, dict):
        attributes = element.get("attributes")
        if isinstance(attributes, dict):
            identifier = attributes.get("unique_id") or element.get("id")
            if identifier:
                return str(identifier)
        if element.get("id"):
            return str(element["id"])
    return "<no id>"


def _channex_timestamp(moment: datetime) -> str:
    """UTC, serialised **without** an offset (R2.8) — and this one is measured, not stylistic.

    Channex ignores the offset you send and compares the wall-clock part literally. Three
    strings naming the same instant, against two bookings inserted at 09:53 UTC:

        filter[inserted_at][gte]=2026-08-03T09:00:00        -> 2 rows
        filter[inserted_at][gte]=2026-08-03T09:00:00Z       -> 2 rows
        filter[inserted_at][gte]=2026-08-03T11:00:00+02:00  -> 0 rows

    So handing it a timezone-aware ISO string from Madrid in summer silently drops every
    reservation created in the last two hours. No error, no warning, nothing in the
    documentation. Converting to UTC and dropping the offset is the whole fix.

    A naive `datetime` is assumed to be UTC rather than rejected: the callers in this codebase
    (`cli/pms_sync.py`, later Celery beat) all build it with `datetime.now(UTC)`, and refusing
    it would fail a sync over a detail the operator cannot see.
    """
    if moment.tzinfo is None:
        return moment.isoformat()
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat()
