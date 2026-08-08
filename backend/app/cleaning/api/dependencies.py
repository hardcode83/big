"""Wiring for the cleaning endpoints: one builder per use case.

Same shape as `app/reservations/api/dependencies.py`. The repositories take the session
from `get_db_session` — the same session `get_authenticated_request` has already marked
with the tenant, so the listener of `app/core/db.py` scopes ORM reads as well.

That net does **not** reach `cleaning_checklist_completions`, which has no `tenant_id`
column (design D6); there the explicit `JOIN` inside the adapter is the only mechanism.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.use_cases import (
    AcceptCleaningTaskUseCase,
    AssignCleaningTaskUseCase,
    CompleteChecklistItemUseCase,
    CompleteCleaningTaskUseCase,
    CreateChecklistTemplateUseCase,
    CreateCleaningTaskUseCase,
    GetChecklistUseCase,
    GetCleaningTaskUseCase,
    ListChecklistTemplatesUseCase,
    ListCleaningTasksUseCase,
    RejectCleaningTaskUseCase,
    StartCleaningTaskUseCase,
    ValidateCleaningTaskUseCase,
)
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyBlockingIncidentQuery,
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _lifecycle_kwargs(session: AsyncSession) -> dict:
    """The seven collaborators every task-lifecycle use case takes.

    One helper rather than seven repeated literals: a use case added later that forgets, say,
    the audit repository would silently stop honouring rule 9.
    """
    return {
        "tasks": SqlAlchemyCleaningTaskRepository(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "transitions": SqlAlchemyPropertyStateTransitionRepository(session),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "reservations": SqlAlchemyReservationRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def get_create_checklist_template_use_case(
    session: SessionDep,
) -> CreateChecklistTemplateUseCase:
    return CreateChecklistTemplateUseCase(
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_checklist_templates_use_case(
    session: SessionDep,
) -> ListChecklistTemplatesUseCase:
    return ListChecklistTemplatesUseCase(
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session)
    )


def get_create_cleaning_task_use_case(session: SessionDep) -> CreateCleaningTaskUseCase:
    return CreateCleaningTaskUseCase(
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        **_lifecycle_kwargs(session),
    )


def get_assign_cleaning_task_use_case(session: SessionDep) -> AssignCleaningTaskUseCase:
    return AssignCleaningTaskUseCase(
        users=SqlAlchemyUserRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        **_lifecycle_kwargs(session),
    )


def get_accept_cleaning_task_use_case(session: SessionDep) -> AcceptCleaningTaskUseCase:
    # The notification repository is the eighth collaborator only for the two operations
    # that ANSWER an assignment (`access-notifications` R5): answering closes the SLA
    # deadline the assignment opened. Starting, completing and validating happen after an
    # answer, so their deadline is already closed and they do not get the port.
    return AcceptCleaningTaskUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        **_lifecycle_kwargs(session),
    )


def get_reject_cleaning_task_use_case(session: SessionDep) -> RejectCleaningTaskUseCase:
    return RejectCleaningTaskUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        **_lifecycle_kwargs(session),
    )


def get_start_cleaning_task_use_case(session: SessionDep) -> StartCleaningTaskUseCase:
    return StartCleaningTaskUseCase(**_lifecycle_kwargs(session))


def get_complete_cleaning_task_use_case(session: SessionDep) -> CompleteCleaningTaskUseCase:
    return CompleteCleaningTaskUseCase(
        completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        incidents=SqlAlchemyBlockingIncidentQuery(session),
        **_lifecycle_kwargs(session),
    )


def get_validate_cleaning_task_use_case(session: SessionDep) -> ValidateCleaningTaskUseCase:
    return ValidateCleaningTaskUseCase(**_lifecycle_kwargs(session))


def get_cleaning_task_use_case(session: SessionDep) -> GetCleaningTaskUseCase:
    return GetCleaningTaskUseCase(tasks=SqlAlchemyCleaningTaskRepository(session))


def get_list_cleaning_tasks_use_case(session: SessionDep) -> ListCleaningTasksUseCase:
    return ListCleaningTasksUseCase(tasks=SqlAlchemyCleaningTaskRepository(session))


def get_checklist_use_case(session: SessionDep) -> GetChecklistUseCase:
    return GetChecklistUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
    )


def get_complete_checklist_item_use_case(
    session: SessionDep,
) -> CompleteChecklistItemUseCase:
    return CompleteChecklistItemUseCase(
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
        **_lifecycle_kwargs(session),
    )
