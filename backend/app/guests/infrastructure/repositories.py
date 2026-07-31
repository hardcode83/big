"""SQLAlchemy adapter for `GuestRepository` (design D8).

`tenant_id` is filtered explicitly in every read and checked explicitly on write —
the session listener of `app/core/db.py` does not guard INSERTs (limit 3 of its
docstring), so `add` is the only thing standing between a bug and a cross-tenant row.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import normalize_email
from app.guests.infrastructure.models import GuestModel


class CrossTenantWriteError(RuntimeError):
    """A write was attempted for a tenant other than the acting one.

    Not an `AppError`: reaching this means a use case mixed up two tenants, which is a
    programming error, not something a client can provoke into a 4xx.
    """


class SqlAlchemyGuestRepository:
    def __init__(self, session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        result = await self._session.execute(
            select(GuestModel).where(
                GuestModel.tenant_id == tenant_id, GuestModel.id == guest_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_guest(model) if model is not None else None

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> Guest | None:
        """Deterministic pick when a tenant holds several guests with one address.

        Ordered by `created_at` then `id`: the oldest row wins, and `id` breaks the tie
        when two guests were inserted inside the same clock tick — without it the answer
        would depend on the query plan, so the same import could attach a reservation to
        a different guest on a different day (design D8).

        The comparison is a plain equality against the Python-normalised address, never
        `lower()` in SQL (see `normalize_email`).
        """
        result = await self._session.execute(
            select(GuestModel)
            .where(
                GuestModel.tenant_id == tenant_id,
                GuestModel.email == normalize_email(email),
            )
            .order_by(GuestModel.created_at, GuestModel.id)
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _to_guest(model) if model is not None else None

    async def add(self, guest: Guest) -> None:
        if guest.tenant_id != self._tenant_id:
            raise CrossTenantWriteError(
                f"Refusing to create a guest for tenant {guest.tenant_id} "
                f"while acting for {self._tenant_id}"
            )
        self._session.add(
            GuestModel(
                id=guest.id,
                tenant_id=guest.tenant_id,
                full_name=guest.full_name,
                email=normalize_email(guest.email) if guest.email else None,
                phone=guest.phone,
                preferred_language=guest.preferred_language,
                nationality=guest.nationality,
                date_of_birth=guest.date_of_birth,
                document_type=guest.document_type,
                document_number_encrypted=guest.document_number_encrypted,
                document_expiry_date=guest.document_expiry_date,
                document_status=guest.document_status,
                legal_registration_status=guest.legal_registration_status,
            )
        )
        await self._session.flush()


def _to_guest(model: GuestModel) -> Guest:
    return Guest(
        id=model.id,
        tenant_id=model.tenant_id,
        full_name=model.full_name,
        created_at=model.created_at,
        updated_at=model.updated_at,
        email=model.email,
        phone=model.phone,
        preferred_language=model.preferred_language,
        nationality=model.nationality,
        date_of_birth=model.date_of_birth,
        document_type=model.document_type,
        document_number_encrypted=model.document_number_encrypted,
        document_expiry_date=model.document_expiry_date,
        document_status=model.document_status,
        legal_registration_status=model.legal_registration_status,
    )
