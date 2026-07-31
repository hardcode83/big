"""Ports owned by the guests domain (design D8, D17).

Shaped by what the reservation flows need: read the linked guest to show it (R1.8), find
an existing one before creating a duplicate (R3.5), and create one.

**Reads return `GuestSummary`, not `Guest`** (design D17). The entity carries
`document_number_encrypted`, `document_expiry_date` and `date_of_birth`, and a port that
handed the whole entity to its callers would put the identity document one
`model_validate(guest)` away from an HTTP response — R1.8 ("sin exponer ningún dato de
documento") and rule 4 of `steering/security.md` ("número de documento jamás en
listados") would then depend on every future serialiser remembering. The projection makes
it structural instead.

`tenant_id` is a parameter of every method, including `add`, following
`app/auth/domain/ports.py`: one source of truth for the acting tenant per call, so a
repository instance cannot disagree with its caller about which tenant it serves.
"""

import uuid
from typing import Protocol

from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import GuestSummary


class GuestRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        """The linked guest of a reservation detail (R1.8), without any document data."""
        ...

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> GuestSummary | None:
        """The guest to reuse instead of creating a duplicate (R3.5).

        `guests.email` is a plain index, so several rows can match; the adapter picks
        deterministically (design D8) rather than letting the query plan decide.
        """
        ...

    async def add(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        """Persist a new guest; refuses an entity belonging to another tenant.

        Takes the full entity because the ingest paths create guests from scratch and
        never populate document fields — the asymmetry with the reads is deliberate.
        """
        ...
