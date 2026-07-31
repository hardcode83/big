"""SQLAlchemy adapter for `ReservationRepository` (design D5, D9, D12).

Every statement filters `tenant_id` explicitly and `add`/`save` check it, because the
session listener of `app/core/db.py` covers neither INSERTs nor the identity map (limits
3 and 4 of its own docstring). No method commits: the use case owns the transaction
(design D4).
"""

import uuid

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.reservations.domain.entities import Reservation
from app.reservations.domain.exceptions import DuplicateExternalReservationError
from app.reservations.domain.repositories import Page, ReservationFilters
from app.reservations.infrastructure.models import ReservationModel

EXTERNAL_PMS_ID_CONSTRAINT = "uq_reservations_tenant_id_external_pms_id"

# Columns `save` writes back. Identity (`id`, `tenant_id`, `property_id`,
# `external_pms_id`) is excluded on purpose: a repository that could move a row to
# another tenant or re-point it at another property would defeat both the isolation rule
# and the idempotency key.
_MUTABLE_COLUMNS = (
    "guest_id",
    "external_channel_id",
    "channel",
    "status",
    "check_in_date",
    "check_out_date",
    "check_in_time",
    "check_out_time",
    "nights",
    "adults",
    "children",
    "total_guests",
    "gross_amount",
    "ota_commission",
    "net_amount",
    "currency",
    "payment_status",
    "access_status",
    "legal_registration_status",
    "cleaning_required",
    "special_requests",
    "internal_notes",
    "updated_at",
)


class SqlAlchemyReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> Reservation | None:
        result = await self._session.execute(
            select(ReservationModel).where(
                ReservationModel.tenant_id == tenant_id, ReservationModel.id == reservation_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_reservation(model) if model is not None else None

    async def find_by_external_pms_id(
        self, tenant_id: uuid.UUID, external_pms_id: str
    ) -> Reservation | None:
        """`uq_reservations_tenant_id_external_pms_id` guarantees at most one row."""
        result = await self._session.execute(
            select(ReservationModel).where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.external_pms_id == external_pms_id.strip(),
            )
        )
        model = result.scalar_one_or_none()
        return _to_reservation(model) if model is not None else None

    async def list(
        self, tenant_id: uuid.UUID, filters: ReservationFilters, *, page: int, per_page: int
    ) -> Page:
        """One page plus the unpaginated total (PRD §23).

        The count runs over the same filtered statement, so `total_pages` can never
        describe a different result set than `data`.
        """
        conditions = _conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(ReservationModel).where(*conditions)
        )
        rows = await self._session.execute(
            _ordered(select(ReservationModel).where(*conditions))
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return Page(
            items=tuple(_to_reservation(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def add(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        if reservation.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="reservation",
                entity_tenant_id=reservation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            ReservationModel(
                id=reservation.id,
                tenant_id=reservation.tenant_id,
                property_id=reservation.property_id,
                guest_id=reservation.guest_id,
                external_pms_id=reservation.external_pms_id,
                external_channel_id=reservation.external_channel_id,
                channel=reservation.channel,
                status=reservation.status,
                check_in_date=reservation.check_in_date,
                check_out_date=reservation.check_out_date,
                check_in_time=reservation.check_in_time,
                check_out_time=reservation.check_out_time,
                nights=reservation.nights,
                adults=reservation.adults,
                children=reservation.children,
                total_guests=reservation.total_guests,
                gross_amount=reservation.gross_amount,
                ota_commission=reservation.ota_commission,
                net_amount=reservation.net_amount,
                currency=reservation.currency,
                payment_status=reservation.payment_status,
                access_status=reservation.access_status,
                legal_registration_status=reservation.legal_registration_status,
                cleaning_required=reservation.cleaning_required,
                special_requests=reservation.special_requests,
                internal_notes=reservation.internal_notes,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            # The constraint is the authority on duplicates, not a prior read: two
            # concurrent imports of the same PMS reservation both pass the lookup and
            # only one can pass this (design D9).
            if EXTERNAL_PMS_ID_CONSTRAINT in str(error.orig):
                raise DuplicateExternalReservationError(
                    f"A reservation with external_pms_id {reservation.external_pms_id} "
                    "already exists for this tenant"
                ) from error
            raise

    async def save(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        if reservation.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="reservation",
                entity_tenant_id=reservation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        values = {column: getattr(reservation, column) for column in _MUTABLE_COLUMNS}
        await self._session.execute(
            update(ReservationModel)
            .where(
                ReservationModel.tenant_id == reservation.tenant_id,
                ReservationModel.id == reservation.id,
            )
            .values(**values)
        )


def _conditions(tenant_id: uuid.UUID, filters: ReservationFilters) -> list:
    conditions = [ReservationModel.tenant_id == tenant_id]
    if filters.property_id is not None:
        conditions.append(ReservationModel.property_id == filters.property_id)
    if filters.status is not None:
        conditions.append(ReservationModel.status == filters.status)
    # Stay overlap, not check-in inside the window (design D12): a guest already in the
    # flat when the range opens is part of the answer.
    if filters.date_to is not None:
        conditions.append(ReservationModel.check_in_date <= filters.date_to)
    if filters.date_from is not None:
        conditions.append(ReservationModel.check_out_date >= filters.date_from)
    return conditions


def _ordered(statement: Select) -> Select:
    """Newest stay first, `id` as the tie-break.

    Without the second key two reservations sharing a `check_in_date` could swap places
    between pages and a client paging through would see one twice and miss another.
    """
    return statement.order_by(ReservationModel.check_in_date.desc(), ReservationModel.id)


def _to_reservation(model: ReservationModel) -> Reservation:
    return Reservation(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        channel=model.channel,
        check_in_date=model.check_in_date,
        check_out_date=model.check_out_date,
        nights=model.nights,
        created_at=model.created_at,
        updated_at=model.updated_at,
        guest_id=model.guest_id,
        external_pms_id=model.external_pms_id,
        external_channel_id=model.external_channel_id,
        status=model.status,
        check_in_time=model.check_in_time,
        check_out_time=model.check_out_time,
        adults=model.adults,
        children=model.children,
        total_guests=model.total_guests,
        gross_amount=model.gross_amount,
        ota_commission=model.ota_commission,
        net_amount=model.net_amount,
        currency=model.currency,
        payment_status=model.payment_status,
        access_status=model.access_status,
        legal_registration_status=model.legal_registration_status,
        cleaning_required=model.cleaning_required,
        special_requests=model.special_requests,
        internal_notes=model.internal_notes,
    )
