"""SQLAlchemy adapter for `GuestRepository` (design D8, D17).

`tenant_id` arrives as a parameter on every method — reads and write alike — following
`app/auth/infrastructure/repositories.py`. An instance therefore holds no opinion about
which tenant it serves, so it cannot disagree with its caller: there is one source of
truth per call, and the guard in `add` compares the entity against that same value.

Reads return `GuestSummary`, which has no document fields at all (design D17). The
session-level listener of `app/core/db.py` does not guard INSERTs (limit 3 of its
docstring), so the check in `add` is the only thing between a bug and a cross-tenant row.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.entities import Guest
from app.guests.domain.exceptions import GuestNotFoundError
from app.guests.domain.value_objects import GuestSummary, normalize_email
from app.guests.infrastructure.models import GuestModel


class SqlAlchemyGuestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        result = await self._session.execute(
            select(GuestModel).where(
                GuestModel.tenant_id == tenant_id, GuestModel.id == guest_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_summary(model) if model is not None else None

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> GuestSummary | None:
        """Deterministic pick when a tenant holds several guests with one address.

        A blank address never matches anything. Without that guard, `"   "` normalises to
        `""` and matches every guest stored with a blank email, so two CSV rows with an
        empty `guest_email` — ordinary in real exports — would be merged into one person,
        the opposite of what design D8 says ("sin email… se crea siempre uno nuevo").

        Ordered by `created_at` then `id`: the oldest row wins, and `id` breaks the tie
        when two guests were inserted inside the same clock tick — without it the answer
        would depend on the query plan, so the same import could attach a reservation to a
        different guest on a different day (design D8).

        The comparison is a plain equality against the Python-normalised address, never
        `lower()` in SQL (see `normalize_email`).
        """
        normalised = normalize_email(email) if email else ""
        if not normalised:
            return None
        result = await self._session.execute(
            select(GuestModel)
            .where(
                GuestModel.tenant_id == tenant_id,
                GuestModel.email == normalised,
            )
            .order_by(GuestModel.created_at, GuestModel.id)
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _to_summary(model) if model is not None else None

    async def add(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        if guest.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="guest",
                entity_tenant_id=guest.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            GuestModel(
                id=guest.id,
                tenant_id=guest.tenant_id,
                full_name=guest.full_name,
                # The truth of the NORMALISED value decides, not of the raw one: `"   "`
                # is truthy before `strip()` and would be stored as `""`, which then
                # behaves like a shared address for every guest without one.
                email=(normalize_email(guest.email) if guest.email else "") or None,
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


    async def get_full(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        result = await self._session.execute(
            select(GuestModel).where(
                GuestModel.tenant_id == tenant_id, GuestModel.id == guest_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def save_document(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        if guest.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="guest",
                entity_tenant_id=guest.tenant_id,
                acting_tenant_id=tenant_id,
            )
        result = await self._session.execute(
            update(GuestModel)
            .where(GuestModel.tenant_id == tenant_id, GuestModel.id == guest.id)
            # Six columns and no others. The port says why it is narrow; this is what makes
            # it true — a caller cannot reach `full_name` or `email` through this method
            # however it mutates the entity it passes in.
            .values(
                nationality=guest.nationality,
                date_of_birth=guest.date_of_birth,
                document_type=guest.document_type,
                document_number_encrypted=guest.document_number_encrypted,
                document_expiry_date=guest.document_expiry_date,
                document_status=guest.document_status,
            )
        )
        if result.rowcount == 0:
            raise GuestNotFoundError(guest.id)


def _to_entity(model: GuestModel) -> Guest:
    """The whole row, `document_number_encrypted` still encrypted.

    Decryption is `app/core/crypto.py`'s and happens inside the use case that has already
    written its `AuditLog` row (rule 9), never here.
    """
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


def _to_summary(model: GuestModel) -> GuestSummary:
    return GuestSummary(
        id=model.id,
        full_name=model.full_name,
        email=model.email,
        phone=model.phone,
        preferred_language=model.preferred_language,
        document_status=model.document_status,
        legal_registration_status=model.legal_registration_status,
    )
