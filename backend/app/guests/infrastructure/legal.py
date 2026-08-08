"""`LegalRegistrationInitialiser` — PRD §17 step 1 (`access-notifications` R6.2, design D10).

> 1. Al confirmar reserva: `legal_registration_status = PENDING_GUEST_DATA`

Lives in `guests/infrastructure/` and writes `reservations`, which reads oddly for a moment
and is the right home: **the state belongs to the stay, not to the guest** (design D10 — a
guest with two stays cannot have one value), but the *capability* belongs to the legal
registration domain, which is what `guests/` owns. The access reconciler consumes it through
a one-method port so it never imports this module.

Idempotent, and narrowly so: it moves a reservation **only** from `NOT_REQUIRED`. A stay
already at `READY_TO_SUBMIT`, `SUBMITTED` or `FAILED` is left alone — the sweep runs every
five minutes and dragging a submitted registration back to "waiting for guest data" would be
the worst possible kind of idempotence.
"""

import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.guests.domain.enums import LegalRegistrationStatus
from app.reservations.infrastructure.models import ReservationModel


class SqlAlchemyLegalRegistrationInitialiser:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def initialise(
        self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID, now: datetime
    ) -> bool:
        result = await self._session.execute(
            update(ReservationModel)
            .where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == reservation_id,
                # The whole idempotence, expressed as a predicate rather than a read-then-write:
                # two concurrent sweeps cannot both move the same row.
                ReservationModel.legal_registration_status
                == LegalRegistrationStatus.NOT_REQUIRED,
            )
            .values(legal_registration_status=LegalRegistrationStatus.PENDING_GUEST_DATA)
        )
        return result.rowcount > 0
