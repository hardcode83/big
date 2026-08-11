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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.guests.domain.enums import LegalRegistrationStatus
from app.guests.domain.ports import LegalRegistrationStay
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


class SqlAlchemyLegalRegistrationStayStore:
    """`LegalRegistrationStayStore` — one column of `reservations`, and no more.

    Every statement filters `tenant_id`, so a stay of another tenant simply is not there:
    `get` answers `None` and `set_status` matches nothing. That is what makes the `404` of
    R6 identical for "absent" and "someone else's".
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> LegalRegistrationStay | None:
        row = await self._session.execute(
            select(
                ReservationModel.id,
                ReservationModel.property_id,
                ReservationModel.guest_id,
                ReservationModel.check_in_date,
                ReservationModel.check_out_date,
                ReservationModel.legal_registration_status,
            ).where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == reservation_id,
            )
        )
        found = row.one_or_none()
        if found is None:
            return None
        return LegalRegistrationStay(
            reservation_id=found.id,
            property_id=found.property_id,
            guest_id=found.guest_id,
            check_in_date=found.check_in_date,
            check_out_date=found.check_out_date,
            status=found.legal_registration_status,
        )

    async def set_status(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        status: LegalRegistrationStatus,
    ) -> None:
        await self._session.execute(
            update(ReservationModel)
            .where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == reservation_id,
            )
            .values(legal_registration_status=status)
        )

    async def set_guest(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID, guest_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Claim a stay that has **no** guest yet, and report who holds it afterwards.

        One column, like its two siblings (`guest-portal-api` R4.2, OQ3): `guest_id` and
        nothing else — the portal's check-in has a name and a stay, and no business rewriting
        the booking's dates, status or legal state. The `tenant_id` filter is what makes a
        stay of another tenant simply not there, so this matches nothing rather than writing
        across the boundary.

        **`WHERE guest_id IS NULL` is the whole of the concurrency story**, and it is why
        this returns a value instead of `None`. R4.5 names the case that breaks the plain
        `UPDATE`: a guest whose network drops resends the form, and two requests read
        `guest_id IS NULL` at the same time. With an unconditional write both insert a
        `Guest`, the second overwrites the link, and the first row is left orphaned **with
        the encrypted document already written into it** — an identity document no route can
        reach and no ordinary flow can delete. Found by the QA panel of that change's
        section 6, as code analysis rather than a measured failure: the test fixture holds a
        single connection, so the interleaving cannot be produced there.

        Making the write conditional turns the race into a claim with one winner. The
        returned id is whoever holds the stay now — the caller's own on a win, the winner's
        on a loss — so the loser writes its document to the row that is actually linked. What
        it can still leave behind is a `Guest` carrying **only a name**, which is inert.

        Returns `None` when nobody holds the stay after all this — almost always because it
        does not exist in this tenant, and in principle because the winner's transaction
        rolled back between the two statements. The caller answers both the same way, with
        the constant refusal, and the second case cures itself on a retry. Saying only "the
        stay does not exist" would be more definite than the code (security panel, section 6,
        round 2).
        """
        claimed = await self._session.execute(
            update(ReservationModel)
            .where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == reservation_id,
                ReservationModel.guest_id.is_(None),
            )
            .values(guest_id=guest_id)
            .returning(ReservationModel.guest_id)
        )
        won = claimed.scalar_one_or_none()
        if won is not None:
            return won

        # Either somebody else claimed it first, or the stay is not ours. One more read tells
        # the two apart, and it is only ever reached on the losing side of a race.
        holder = await self._session.execute(
            select(ReservationModel.guest_id).where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == reservation_id,
            )
        )
        return holder.scalar_one_or_none()
