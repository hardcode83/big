"""`Beds24Adapter` — the real PMS port for the MVP's provider (R2, design D3, D10, D11).

Substitutable for `MockPMSAdapter` and `ChannexAdapter` by contract, not by coincidence: the
same DTO shape, the same `None` for an unknown id, the same tolerance of rows the ingestor will
reject. `steering/backend-architecture.md` states that obligation as Liskov and this is where a
second real provider either honours it or exposes that the port was wrong.

**What it does that Channex cannot** (R2.1): it asks for reservations by **modification** date,
so a booking created a month ago and cancelled a minute ago comes back. `ChannexAdapter`'s own
docstring records that `/bookings` there filters on `inserted_at` and has no modification
filter, which is fine for validating a backend and useless as a production sync — and hands the
problem here by name.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from app.integrations.domain.dtos import PmsFetchResult, PmsRowFailure, ReservationDTO
from app.integrations.infrastructure.beds24.client import Beds24Client
from app.integrations.infrastructure.beds24.mapping import (
    UnmappableField,
    is_blocked_dates,
    to_reservation_dto,
)

BOOKINGS_PATH = "/bookings"

MODIFIED_FROM_PARAM = "modifiedFrom"
"""The filter that makes the full window possible.

ASSUMPTION, and the only one this module makes about the provider's API: the parameter exists
and accepts a UTC instant. It is **documented** in the provider's wiki alongside `modifiedTo`
and **not measured** — `pms-beds24-spike` measured the arrival-window filters and never this
one, and this project has been wrong twice by trusting provider documentation (`x-requestcost`
guessed from docs matched nothing; four rules of the Channex mapping contradict what its docs
implied).

Task 1.2 measures it, and `BLOCKED.md` records that it needs a credential nobody had when this
was written. If the measurement says the parameter takes a plain `YYYY-MM-DD` instead, the fix
is one line here — but note the consequence before applying it: a date-only filter re-reads
everything modified today on every cycle, so a sync running every few minutes would page
through the same rows all day and spend credits doing it.
"""

logger = logging.getLogger(__name__)


class Beds24Adapter:
    """Implements `PMSAdapter` over the Beds24 API V2."""

    def __init__(self, client: Beds24Client) -> None:
        self._client = client

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> PmsFetchResult:
        """Reservations created, modified **or cancelled** since `since` (R2.1).

        The three verbs are the point. A cancellation is a modification of an existing booking,
        so a provider that can only filter by creation date cannot report one — which is the
        limitation this adapter exists not to inherit.
        """
        params: dict[str, Any] = {MODIFIED_FROM_PARAM: _beds24_instant(since)}
        if property_external_id is not None:
            params["propertyId"] = property_external_id

        elements = await self._client.get_collection(BOOKINGS_PATH, params=params)

        rows: list[ReservationDTO] = []
        failures: list[PmsRowFailure] = []
        blocked = 0
        for element in elements:
            # A calendar block is not a reservation and not a failure (design D10). Importing
            # one would invent a guest and drive the `PropertyStateMachine` on a property nobody
            # booked; reporting it as a failed row would fill the operator's report with noise
            # about rows that are working exactly as intended.
            #
            # Counted rather than dropped in silence: "no silent truncation" is the rule the
            # rest of this module is built on, so the count goes to the log.
            if is_blocked_dates(element):
                blocked += 1
                continue
            try:
                rows.append(to_reservation_dto(element))
            except Exception as error:  # noqa: BLE001 - any malformed shape, not a known set
                reference = _element_reference(element)
                failures.append(
                    PmsRowFailure(external_id=reference, reason=_skip_reason(error))
                )
                # The provider's id and the error class only. NOT the payload: it carries guest
                # name, email, phone and — rule 13 — cardholder data, and a log line is a
                # plain-text sink.
                logger.warning(
                    "beds24: could not map booking %s (%s)", reference, type(error).__name__
                )

        if blocked:
            logger.info(
                "beds24: skipped %s calendar block(s) — not reservations", blocked
            )
        return PmsFetchResult(reservations=rows, failures=failures)

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """One reservation by the provider's id; `None` when Beds24 has no such id.

        Beds24 has no per-id route for bookings — you filter the collection — so an unknown id
        comes back as an empty `data`, which `Beds24Client.get_resource` turns into `None`.

        A calendar block is `None` too, for the same reason it is skipped above: asking for a
        reservation by an id that names a block should not return a fabricated stay.
        """
        element = await self._client.get_resource(
            BOOKINGS_PATH, params={"id": external_id}
        )
        if element is None or is_blocked_dates(element):
            return None
        return to_reservation_dto(element)


def _skip_reason(error: Exception) -> str:
    """A skip reason from a closed vocabulary this module owns. **Never `str(error)`.**

    Two review panels measured why on the Channex twin: an exception's own message routinely
    embeds the value it choked on, so a booking with a nested object where a date belongs put
    `card_number` and `cvv` into the operator's report. Rule 13(a) of `steering/security.md`
    requires cardholder data to die inside the adapter, "antes de que nada pueda persistirlos,
    loguearlos o reenviarlos".

    So: the class name always, plus the FIELD name when the mapping raised its own
    `UnmappableField`, which carries a field and no content.
    """
    if isinstance(error, UnmappableField):
        return f"{type(error).__name__}: {error.field}"
    return type(error).__name__


MAX_REFERENCE_LENGTH = 64
NO_REFERENCE = "<no id>"


def _element_reference(element: Any) -> str:
    """Enough to find the booking in the Beds24 panel, and nothing more.

    The same validation `ChannexAdapter` arrived at after its security panel demonstrated two
    separate leaks through the "identifier" — an element carrying an object where the id
    belongs put card data into the log, and a 2000-character value with a newline forged an
    extra log line shaped like ours.

    An identifier survives only if it is genuinely scalar, short and printable. Losing the
    reference is a diagnostic inconvenience; printing a PAN is not.
    """
    if not isinstance(element, dict):
        return NO_REFERENCE

    for candidate in (element.get("id"), element.get("apiReference")):
        # `bool` excluded deliberately: it is a subclass of `int`, and "True" is not an id.
        if isinstance(candidate, bool) or not isinstance(candidate, (str, int)):
            continue
        # Control characters first, then the bound: stripping after truncating could leave a
        # partial escape sequence at the cut.
        text = "".join(character for character in str(candidate) if character.isprintable())
        text = text.strip()[:MAX_REFERENCE_LENGTH]
        if text:
            return text
    return NO_REFERENCE


def _beds24_instant(moment: datetime) -> str:
    """UTC, ISO-8601, with `Z`.

    A naive `datetime` is assumed to be UTC rather than rejected: every caller in this codebase
    (`cli/pms_sync.py`, later Celery beat) builds it with `datetime.now(UTC)`, and refusing one
    would fail a sync over a detail the operator cannot see. That is the call
    `channex/adapter.py` made for the same reason.

    Unlike Channex, the offset is **kept** rather than dropped. Channex was measured to ignore
    the offset and compare the wall-clock part literally, so sending a Madrid timestamp there
    silently dropped two hours of reservations. Nothing has measured Beds24 doing that, and
    inventing the same workaround for a second provider on the strength of the first would be
    designing against a bug this one may not have. Task 1.2 is where it gets checked.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
