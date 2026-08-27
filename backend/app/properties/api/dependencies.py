"""Wiring for the property endpoints: one builder per use case.

Same shape as `app/reservations/api/dependencies.py` and `app/auth/api/user_dependencies.py` —
no container, no registry, one function that names exactly the adapters its use case needs.

The repositories take the session from `get_db_session`, which is the same session
`get_authenticated_request` has already marked with the tenant, so the listener of
`app/core/db.py` scopes ORM reads too — as a net under the explicit `tenant_id` argument, never
instead of it.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentReader
from app.properties.application.action_id_resolver import ActionIdResolver
from app.properties.application.property_admin import (
    CreatePropertyUseCase,
    GetPropertyStateUseCase,
    GetPropertyUseCase,
    ListPropertiesUseCase,
    UpdatePropertyUseCase,
)
from app.properties.application.use_cases import ListBlockedTransitionsUseCase
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_create_property_use_case(session: SessionDep) -> CreatePropertyUseCase:
    return CreatePropertyUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_properties_use_case(session: SessionDep) -> ListPropertiesUseCase:
    return ListPropertiesUseCase(properties=SqlAlchemyPropertyRepository(session))


def get_property_use_case(session: SessionDep) -> GetPropertyUseCase:
    return GetPropertyUseCase(properties=SqlAlchemyPropertyRepository(session))


def get_property_state_use_case(session: SessionDep) -> GetPropertyStateUseCase:
    return GetPropertyStateUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
    )


def get_list_blocked_transitions_use_case(session: SessionDep) -> ListBlockedTransitionsUseCase:
    """No unit of work: the collection is derived on read and writes nothing (design D5).

    The two extra dependencies (`action_ids` and its two ports) come from
    `blocked-transition-response-ids` (R3): they turn the bare stall into a row whose
    `cleaning_task_id` / `incident_id` point at the resource the dashboard's action button
    would call. Tenant scope is the verified token's `tenant_id`, propagated by FastAPI
    `Depends(get_authenticated_request)` to the listener of `app/core/db.py`, and the two
    ports receive it as an explicit argument here.
    """
    return ListBlockedTransitionsUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        action_ids=ActionIdResolver(
            cleaning_tasks=SqlAlchemyCleaningTaskRepository(session),
            incidents=SqlAlchemyIncidentReader(session),
        ),
    )


def get_update_property_use_case(session: SessionDep) -> UpdatePropertyUseCase:
    return UpdatePropertyUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
