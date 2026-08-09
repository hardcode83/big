"""Wiring for the access endpoints: one builder per use case.

Same shape as `app/cleaning/api/dependencies.py`.

**`ManualAccessAdapter` is the provider, hardcoded, and that is the MVP's decision, not an
oversight.** [ADR 0006](../../../../docs/adr/0006-pms-channel-manager-provider.md) decision 5
leaves the access layer open — GrinPass has no public API yet, Beds24 brings TTLock/Nuki —
so nothing above the port may assume a route. When one is chosen, this is the single line
that changes, which is the whole point of the port existing.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.application.use_cases import (
    GetAccessRecordUseCase,
    ListAccessRecordsUseCase,
    MarkAccessDeliveredUseCase,
    MarkAccessExternallyManagedUseCase,
    RegisterManualAccessCodeUseCase,
)
from app.access.infrastructure.adapters import ManualAccessAdapter
from app.access.infrastructure.repositories import SqlAlchemyAccessRecordRepository
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _operation_kwargs(session: AsyncSession) -> dict:
    """The five collaborators every operator action takes.

    One helper rather than five repeated literals: a use case added later that forgot the
    audit repository would silently stop honouring rule 9 of `steering/security.md`.
    """
    return {
        "records": SqlAlchemyAccessRecordRepository(session),
        "provider": ManualAccessAdapter(),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def get_register_manual_access_code_use_case(
    session: SessionDep,
) -> RegisterManualAccessCodeUseCase:
    return RegisterManualAccessCodeUseCase(**_operation_kwargs(session))


def get_mark_access_externally_managed_use_case(
    session: SessionDep,
) -> MarkAccessExternallyManagedUseCase:
    return MarkAccessExternallyManagedUseCase(**_operation_kwargs(session))


def get_mark_access_delivered_use_case(session: SessionDep) -> MarkAccessDeliveredUseCase:
    return MarkAccessDeliveredUseCase(**_operation_kwargs(session))


def get_access_record_use_case(session: SessionDep) -> GetAccessRecordUseCase:
    return GetAccessRecordUseCase(records=SqlAlchemyAccessRecordRepository(session))


def get_list_access_records_use_case(session: SessionDep) -> ListAccessRecordsUseCase:
    return ListAccessRecordsUseCase(records=SqlAlchemyAccessRecordRepository(session))
