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
from collections.abc import Sequence
from typing import Protocol

from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import GuestSummary


class GuestRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        """The linked guest of a reservation detail (R1.8), without any document data."""
        ...

    async def list_for_ids(
        self, tenant_id: uuid.UUID, guest_ids: Sequence[uuid.UUID]
    ) -> Sequence[GuestSummary]:
        """The guests of a batch of reservations, in ONE query (`dashboard-api` R1.7).

        The dashboard collection puts a guest name on every card, and one `get` per card is
        the N+1 that R1.7 forbids. Same shape as the batch readers that change adds to
        `cleaning`, `maintenance` and `timeline`.

        Returns `GuestSummary` like its siblings here, so the document fields are out of
        reach by construction rather than by the caller's restraint — `get_full` remains the
        one narrow exception, and it is not this.

        An empty `guest_ids` returns an empty sequence without querying. Ids that do not
        resolve within the tenant are simply absent; the caller keys by `id`.
        """
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

    async def get_full(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        """The whole entity, document fields included (`access-notifications` R6, R7).

        **The deliberate exception to this port's own rule**, and it is narrow on purpose.
        The docstring above explains why reads return `GuestSummary`: an entity in a
        response is one `model_validate` away from publishing an identity document. That
        reasoning still holds for every caller that only needs to *show* a guest.

        What it cannot serve is the two paths that need the fields themselves — deciding
        whether a stay is ready to report (PRD §17, and even there only whether a number is
        *stored*) and assembling the submission. Those are the two, they both live in
        `guests/application/`, and rule 9 of `sdd/steering/security.md` puts an `AuditLog`
        row behind the second.

        `document_number_encrypted` comes back **as ciphertext**: decryption is
        `app/core/crypto.py`'s, so the number is cleartext only inside the use case that
        wrote its audit row first.
        """
        ...

    async def save_document(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        """Write the identity-document fields of one guest (R7.1).

        Narrow like `NotificationLogRepository.mark_breached`, and for the same reason: this
        path exists to store a document, and a port that also let it rewrite `full_name`,
        `email` or `preferred_language` would be an open door for the change that comes next.
        Persists `nationality`, `date_of_birth`, `document_type`,
        `document_number_encrypted`, `document_expiry_date` and `document_status`.
        """
        ...
