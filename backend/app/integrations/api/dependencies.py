"""Wiring for the integration endpoints (design D1)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.config import settings
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import (
    CreateWebhookEndpointUseCase,
    ImportReservationsFromCsvUseCase,
    RotateWebhookEndpointUseCase,
)
from app.integrations.infrastructure.csv_parser import CsvReservationParser
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
)
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_import_csv_use_case(session: SessionDep) -> ImportReservationsFromCsvUseCase:
    return ImportReservationsFromCsvUseCase(
        parser=CsvReservationParser(),
        max_rows=settings.csv_import_max_rows,
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_create_webhook_endpoint_use_case(
    session: SessionDep,
) -> CreateWebhookEndpointUseCase:
    return CreateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_rotate_webhook_endpoint_use_case(
    session: SessionDep,
) -> RotateWebhookEndpointUseCase:
    return RotateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
