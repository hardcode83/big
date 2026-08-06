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

from app.integrations.domain.dtos import PmsFetchResult, PmsRowFailure, ReservationDTO
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.channex.mapping import UnmappableField, to_reservation_dto

BOOKINGS_PATH = "/bookings"

logger = logging.getLogger(__name__)


class ChannexAdapter:
    """Implements `PMSAdapter` over the Channex REST API.

    Substitutable for `MockPMSAdapter` by contract, not by coincidence: the same DTO shape, the
    same `None` for an unknown id, the same tolerance of rows the ingestor will reject.
    """

    def __init__(self, client: ChannexClient) -> None:
        self._client = client

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> PmsFetchResult:
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
        # The failures travel back in the RETURN VALUE (`PmsFetchResult`, design D10). They used
        # to be reported through an `unmappable_rows` attribute on this adapter, reset here on
        # every call — a limitation the port itself documented and handed to a later change.
        # Skipped rows must not be silent, which is the same reason pagination raises instead of
        # truncating (design D6); what changed is that the report is now part of the answer
        # rather than a slot the caller had to remember to read.
        rows: list[ReservationDTO] = []
        failures: list[PmsRowFailure] = []
        for element in elements:
            try:
                rows.append(to_reservation_dto(element))
            except Exception as error:  # noqa: BLE001 - any malformed shape, not a known set
                reference = _element_reference(element)
                failures.append(
                    PmsRowFailure(external_id=reference, reason=_skip_reason(error))
                )
                # The provider's id and the error class only. NOT the payload: it carries guest
                # name, email, phone and address, and a log line is a plain-text sink.
                logger.warning(
                    "channex: could not map booking %s (%s)", reference, type(error).__name__
                )
        return PmsFetchResult(reservations=rows, failures=failures)

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """`None` when Channex has no such booking — never an error.

        The port says so and `MockPMSAdapter` behaves that way; an absent id is an answer, not
        a failure. `ChannexClient.get_resource` turns the provider's 404 into `None`.
        """
        element = await self._client.get_resource(f"{BOOKINGS_PATH}/{external_id}")
        if element is None:
            return None
        return to_reservation_dto(element)


def _skip_reason(error: Exception) -> str:
    """A skip reason built from a closed vocabulary this module owns. **Never `str(error)`.**

    The previous shape was `f"{type(error).__name__}: {error}"`, and the security and QA panels of
    this change both reproduced the same leak through it: an exception's own message routinely
    embeds the value it choked on, so a booking with `arrival_date` set to a string put that
    string in the operator's report, and one with a nested object there put `card_number` and
    `cvv` in it. Rule 13(a) of `steering/security.md` requires cardholder data to die inside the
    adapter — "antes de que nada pueda persistirlos, loguearlos o reenviarlos" — and R6.4 limits
    this report to "el identificador y la clase de error".

    So: the class name always, plus the FIELD name when the mapping raised its own
    `UnmappableField`, which carries a field and no content. Nothing else. Any exception type
    this module does not recognise contributes its class name and nothing more, which is what
    keeps the guarantee true for a provider shape nobody has seen yet — the `except Exception`
    upstream exists precisely because that set is open.
    """
    if isinstance(error, UnmappableField):
        return f"{type(error).__name__}: {error.field}"
    return type(error).__name__


MAX_REFERENCE_LENGTH = 64
NO_REFERENCE = "<no id>"


def _element_reference(element: Any) -> str:
    """Enough to find the booking in the Channex panel, and nothing more.

    `unique_id` if it is there, else the element `id`. Deliberately never the payload — and that
    claim used to be false, which is why this function now validates instead of trusting.

    **Measured by the security panel of this change, after the first fix.** Bounding the skip
    *reason* to a closed vocabulary left the identical exposure one field over: this returned
    `str(identifier)` on whatever the provider had put under `unique_id`, so an element carrying a
    `guarantee` object there produced a "reference" containing `card_number` and `cvv`, and that
    string reached the same `logger.warning` and the same CLI output. Rule 13(a) of
    `steering/security.md` does not care which field the card data travels in.

    A second, separate problem the same probe demonstrated: a 2000-character value containing a
    newline forged an extra log line shaped like ours (`channex: … cvv=737`). An identifier is
    attacker-influenced text going into a line-oriented sink, so it is bounded and stripped of
    control characters, not merely typed.

    So an identifier survives only if it is genuinely scalar, short, and printable. Anything else
    is `<no id>` — losing the reference is a diagnostic inconvenience; printing a PAN is not.
    """
    if not isinstance(element, dict):
        return NO_REFERENCE

    attributes = element.get("attributes")
    candidates = []
    if isinstance(attributes, dict):
        candidates.append(attributes.get("unique_id"))
    candidates.append(element.get("id"))

    for candidate in candidates:
        # `bool` is excluded deliberately: it is a subclass of `int`, and "True" is not an id.
        if isinstance(candidate, bool) or not isinstance(candidate, (str, int)):
            continue
        text = str(candidate)
        # Control characters first, then the bound: stripping after truncating could leave a
        # partial escape sequence at the cut.
        text = "".join(character for character in text if character.isprintable())
        text = text.strip()[:MAX_REFERENCE_LENGTH]
        if text:
            return text
    return NO_REFERENCE


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
