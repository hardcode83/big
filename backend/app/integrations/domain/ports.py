"""The PMS port (PRD §16, R3.1, design D1).

EXTERNAL_DEPENDENCY: the real providers (Octorate/Smoobu/Beds24) need credentials this
project does not have, so the MVP implementation is `MockPMSAdapter`. The interface is the
definitive one — `steering/architecture.md`: "MVP = implementaciones mock/manual con la
interfaz definitiva".

**Two methods of the eight in PRD §16**, deliberately. `update_price`, `block_dates`,
`get_availability`, `list_properties`, `get_messages` and `send_message` arrive with the
changes that consume them (`revenue`, `messaging-ai`); a port sized for everything it could
eventually do is the "StorageAdapter gigante con 15 métodos" that
`steering/backend-architecture.md` names as the Interface Segregation failure. The two here
keep PRD §16's signatures verbatim so the rest can be added without rewriting these.

Substitutability is a requirement, not a nicety (SOLID's L, spelled out in the steering):
the mock must raise what a real adapter raises and return the same shapes, so a use case
tested against it behaves the same in production.
"""

from datetime import datetime
from typing import Protocol

from app.integrations.domain.dtos import ParseResult, ReservationDTO


class PMSAdapter(Protocol):
    unmappable_rows: list[str]
    """Rows the adapter received but could not turn into a `ReservationDTO`, last call only.

    **Declared on the port, not left as an implementation detail**, and the reason is a finding
    from the feature-scale architecture panel. `list_reservations` returns bare DTOs, so it has
    nowhere to report a row whose shape the adapter could not use — unlike
    `ReservationCsvParser`, whose `ParseResult` carries `failures` for exactly this. The first
    version put the list on `ChannexAdapter` alone and had the caller reach for it with
    `getattr(adapter, "unmappable_rows", [])`, which meant a future adapter that simply did not
    define the attribute would silently report **zero** unmappable rows while dropping some.

    Declaring it here makes it part of the contract every implementation must satisfy: a skip is
    never silent, which is the same principle that makes pagination raise instead of truncating
    (design D6).

    **Still a stopgap.** The structurally right fix is to widen the return type the way
    `ParseResult` does — `pms-beds24-adapter` owns the port restructuring (ADR 0006 decision 3
    already splits `PMSMessagingPort` off) and should do it there rather than inherit this.

    Contains only strings safe to log: the provider's id and the error class, never the payload,
    which carries guest name, email, phone and card data.
    """

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> list[ReservationDTO]:
        """Reservations created or changed since `since`, optionally for one property.

        `since` is explicit rather than read from a clock inside the adapter: the caller
        owns time, which is what lets the sync be replayed over a known window.
        """
        ...

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """One reservation by the provider's id; `None` when the provider has no such id."""
        ...


class ReservationCsvParser(Protocol):
    """Turns an uploaded CSV into rows, reporting per-row failures instead of raising (R4.2).

    A port because the use case must not import `infrastructure/` (the feature-scale
    architecture review caught the router doing exactly that): parsing a file format is an
    adapter concern, and going through a port is what keeps `application/` free of it.

    Raises only for failures of the FILE as a whole — not UTF-8, missing required columns, more
    rows than allowed — because in those cases there is nothing to report per row.
    """

    def parse(self, raw: bytes, *, max_rows: int) -> ParseResult:
        ...
