"""Wiring for the tenant endpoints: one builder per use case."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.tenants.application.use_cases import (
    GetTenantSettingsUseCase,
    UpdateTenantSettingsUseCase,
)
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_tenant_settings_use_case(session: SessionDep) -> GetTenantSettingsUseCase:
    return GetTenantSettingsUseCase(
        tenants=SqlAlchemyTenantRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
    )


def get_update_tenant_settings_use_case(
    session: SessionDep,
) -> UpdateTenantSettingsUseCase:
    return UpdateTenantSettingsUseCase(
        tenants=SqlAlchemyTenantRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
