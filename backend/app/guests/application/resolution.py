"""Application service for resolving the guest identity of a reservation.

Email is the only automatic identity key.  The service deliberately does not inspect names
or phone numbers, and reusing a guest is never an implicit edit operation.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.guests.domain.entities import Guest
from app.guests.domain.repositories import GuestRepository
from app.guests.domain.ports import GuestEmailExclusion
from app.guests.domain.value_objects import normalize_email, normalize_phone_e164

MAX_GUEST_FULL_NAME_LENGTH = 300


@dataclass(frozen=True)
class ManualGuestIdentityInput:
    """Validated, canonical contact identity supplied by a manual reservation flow."""

    full_name: str
    email: str | None = None
    phone: str | None = None
    preferred_language: Literal["es", "en"] = "es"

    def __post_init__(self) -> None:
        full_name = self.full_name.strip()
        if not 1 <= len(full_name) <= MAX_GUEST_FULL_NAME_LENGTH:
            raise ValueError("full_name must contain between 1 and 300 characters")

        email = normalize_email(self.email) if self.email is not None else ""
        raw_phone = self.phone.strip() if self.phone is not None else ""
        phone = normalize_phone_e164(raw_phone) if raw_phone else None
        if raw_phone and phone is None:
            raise ValueError("phone must use a supported E.164 or Spanish national format")
        if self.preferred_language not in ("es", "en"):
            raise ValueError("preferred_language must be 'es' or 'en'")

        object.__setattr__(self, "full_name", full_name)
        object.__setattr__(self, "email", email or None)
        object.__setattr__(self, "phone", phone)


class ResolveOrCreateGuest:
    """Resolve by tenant-scoped normalised email, or append one new guest.

    ``GuestRepository.find_by_email`` owns the deterministic historical-duplicate policy:
    earliest ``created_at``, then lowest ``id``.  Returning its result unchanged preserves
    that policy without introducing a second resolution port or any merge/update behaviour.
    The caller supplies the transaction-scoped exclusion so every email resolution is protected
    by the same-session advisory-lock protocol.
    """

    def __init__(
        self, guests: GuestRepository, exclusion: GuestEmailExclusion
    ) -> None:
        self._guests = guests
        self._exclusion = exclusion

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        identity: ManualGuestIdentityInput,
        now: datetime,
    ) -> uuid.UUID:
        if identity.email is not None:
            existing = await self._guests.find_by_email(tenant_id, identity.email)
            if existing is not None:
                return existing.id
            await self._exclusion.acquire(tenant_id, identity.email)
            existing = await self._guests.find_by_email(tenant_id, identity.email)
            if existing is not None:
                return existing.id

        guest = Guest(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            full_name=identity.full_name,
            created_at=now,
            updated_at=now,
            email=identity.email,
            phone=identity.phone,
            preferred_language=identity.preferred_language,
        )
        await self._guests.add(tenant_id, guest)
        return guest.id
