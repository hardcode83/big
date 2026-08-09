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
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.properties.application.property_admin import (
    CreatePropertyUseCase,
    GetPropertyStateUseCase,
    GetPropertyUseCase,
    ListPropertiesUseCase,
    UpdatePropertyUseCase,
)
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)

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


def get_update_property_use_case(session: SessionDep) -> UpdatePropertyUseCase:
    return UpdatePropertyUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
