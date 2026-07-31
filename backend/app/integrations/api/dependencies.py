"""Wiring for the integration endpoints (design D1)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import ImportReservationsFromCsvUseCase
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_import_csv_use_case(session: SessionDep) -> ImportReservationsFromCsvUseCase:
    return ImportReservationsFromCsvUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
