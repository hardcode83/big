"""Wiring for the dashboard endpoints: one builder per use case.

Same shape as `app/properties/api/dependencies.py` — no container, no registry, one function
naming exactly the adapters its use case needs. There are more of them here than anywhere
else in the project, and that is the point of design D1: the dashboard **composes** other
domains' ports and owns no `infrastructure/` of its own.

Every repository takes the session from `get_db_session`, which is the same session
`get_authenticated_request` has already marked with the tenant, so the listener of
`app/core/db.py` scopes ORM reads too — as a net under the explicit `tenant_id` argument,
never instead of it.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from app.core.db import get_db_session
from app.dashboard.application.use_cases import (
    GetDashboardCardsUseCase,
    GetOccupancySeriesUseCase,
    GetOperationalKpisUseCase,
    GetPropertyDashboardUseCase,
)
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyOwnerApprovalReader,
)
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.statements.infrastructure.repositories import SqlAlchemyExpenseReader
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_dashboard_cards_use_case(session: SessionDep) -> GetDashboardCardsUseCase:
    return GetDashboardCardsUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        cleaning=SqlAlchemyCleaningTaskRepository(session),
        incidents=SqlAlchemyIncidentReader(session),
        timeline=SqlAlchemyTimelineEventReader(session),
    )


def get_property_dashboard_use_case(session: SessionDep) -> GetPropertyDashboardUseCase:
    return GetPropertyDashboardUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        cleaning=SqlAlchemyCleaningTaskRepository(session),
        incidents=SqlAlchemyIncidentReader(session),
        approvals=SqlAlchemyOwnerApprovalReader(session),
        expenses=SqlAlchemyExpenseReader(session),
    )


def get_operational_kpis_use_case(session: SessionDep) -> GetOperationalKpisUseCase:
    return GetOperationalKpisUseCase(
        cleaning=SqlAlchemyCleaningTaskRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        incidents=SqlAlchemyIncidentReader(session),
    )


def get_occupancy_series_use_case(session: SessionDep) -> GetOccupancySeriesUseCase:
    return GetOccupancySeriesUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
    )
