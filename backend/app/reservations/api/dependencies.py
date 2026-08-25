"""Wiring for the reservation endpoints: one builder per use case.

Same shape as `app/auth/api/dependencies.py`. The repositories take the session from
`get_db_session` — the same session `get_authenticated_request` has already marked with the
tenant, so the listener of `app/core/db.py` scopes ORM reads as well (design D5's net).
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.application.use_cases import (
    CancelReservationUseCase,
    CreateReservationUseCase,
    GetReservationUseCase,
    ListReservationsUseCase,
    UpdateReservationUseCase,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_create_reservation_use_case(session: SessionDep) -> CreateReservationUseCase:
    return CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_update_reservation_use_case(session: SessionDep) -> UpdateReservationUseCase:
    return UpdateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_cancel_reservation_use_case(session: SessionDep) -> CancelReservationUseCase:
    return CancelReservationUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_reservation_use_case(session: SessionDep) -> GetReservationUseCase:
    return GetReservationUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
    )


def get_list_reservations_use_case(session: SessionDep) -> ListReservationsUseCase:
    return ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
    )
