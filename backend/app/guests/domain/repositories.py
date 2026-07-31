"""Ports owned by the guests domain (design D8).

Shaped by what the reservation flows need: read a linked guest to show it (R1.8), find
an existing one before creating a duplicate (R3.5), and create one. Nothing about
identity documents — that surface belongs to `access-notifications`/`guest-portal`, and
leaving it out of the port is what keeps `document_number_encrypted` unreachable from
here.
"""

import uuid
from typing import Protocol

from app.guests.domain.entities import Guest


class GuestRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        """The linked guest of a reservation detail (R1.8), scoped to its tenant."""
        ...

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> Guest | None:
        """The guest to reuse instead of creating a duplicate (R3.5).

        `guests.email` is a plain index, so several rows can match; the adapter picks
        deterministically (design D8) rather than letting the query plan decide.
        """
        ...

    async def add(self, guest: Guest) -> None:
        """Persist a new guest; refuses an entity belonging to another tenant."""
        ...
