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

from app.integrations.domain.dtos import ReservationDTO


class PMSAdapter(Protocol):
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
