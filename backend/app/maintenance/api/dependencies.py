"""Wiring for the maintenance endpoints: one builder per use case (design D14).

Same shape as `app/cleaning/api/dependencies.py`. The repositories take the session from
`get_db_session` — the same session `get_authenticated_request` has already marked with the
tenant, so the listener of `app/core/db.py` scopes ORM reads as well. That is the net; the
explicit `tenant_id` every repository method takes is the mechanism (D15).

`_flow_kwargs` exists for the reason `cleaning`'s `_lifecycle_kwargs` does: a use case added
later that forgot, say, the audit repository would silently stop honouring rule 9, and a
forgotten `cleaning_tasks` would silently give a property the wrong operational state (D7's
main risk).
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.application.use_cases import (
    AcceptIncidentUseCase,
    AssignIncidentUseCase,
    CancelIncidentUseCase,
    ClassifyIncidentUseCase,
    EnRouteIncidentUseCase,
    GetIncidentContextUseCase,
    GetIncidentUseCase,
    ListIncidentsUseCase,
    RejectIncidentUseCase,
    ResolveIncidentUseCase,
    RespondOwnerApprovalUseCase,
    ResumeWorkUseCase,
    TriageIncidentUseCase,
    WaitForPartsUseCase,
)
from app.maintenance.infrastructure.classifier import RuleBasedIncidentClassifier
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyLiveCleaningTaskQuery,
    SqlAlchemyOwnerApprovalRepository,
)
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


def _flow_kwargs(session: AsyncSession) -> dict:
    """The nine collaborators every incident-flow use case takes."""
    return {
        "incidents": SqlAlchemyIncidentRepository(session),
        "reader": SqlAlchemyIncidentReader(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "transitions": SqlAlchemyPropertyStateTransitionRepository(session),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "reservations": SqlAlchemyReservationRepository(session),
        "cleaning_tasks": SqlAlchemyLiveCleaningTaskQuery(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def _gate_kwargs(session: AsyncSession) -> dict:
    """What the two use cases that open an owner-approval gate need on top."""
    return {
        "approvals": SqlAlchemyOwnerApprovalRepository(session),
        "users": SqlAlchemyUserRepository(session),
        "notifications": SqlAlchemyNotificationLogRepository(session),
        "configs": SqlAlchemyTenantConfigRepository(session),
    }


def get_list_incidents_use_case(session: SessionDep) -> ListIncidentsUseCase:
    return ListIncidentsUseCase(SqlAlchemyIncidentReader(session))


def get_incident_use_case(session: SessionDep) -> GetIncidentUseCase:
    return GetIncidentUseCase(SqlAlchemyIncidentRepository(session))


def get_incident_context_use_case(session: SessionDep) -> GetIncidentContextUseCase:
    """R1.1 — a read, so no unit of work and no audit repository (design D2).

    The two repositories `_flow_kwargs` already hands out. Composing them here rather than
    wiring a bespoke reader is what keeps the tenant scope written in one place: each `get`
    takes its `tenant_id` explicitly, and `app/core/db.py`'s listener is defence in depth
    behind it.
    """
    return GetIncidentContextUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
    )


def get_classify_incident_use_case(session: SessionDep) -> ClassifyIncidentUseCase:
    return ClassifyIncidentUseCase(
        classifier=RuleBasedIncidentClassifier(),
        configs=SqlAlchemyTenantConfigRepository(session),
        **_flow_kwargs(session),
    )


def get_triage_incident_use_case(session: SessionDep) -> TriageIncidentUseCase:
    return TriageIncidentUseCase(**_gate_kwargs(session), **_flow_kwargs(session))


def get_assign_incident_use_case(session: SessionDep) -> AssignIncidentUseCase:
    return AssignIncidentUseCase(
        users=SqlAlchemyUserRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        **_flow_kwargs(session),
    )


def get_accept_incident_use_case(session: SessionDep) -> AcceptIncidentUseCase:
    return AcceptIncidentUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session), **_flow_kwargs(session)
    )


def get_en_route_incident_use_case(session: SessionDep) -> EnRouteIncidentUseCase:
    return EnRouteIncidentUseCase(**_flow_kwargs(session))


def get_reject_incident_use_case(session: SessionDep) -> RejectIncidentUseCase:
    """R1.6 — wired like `get_accept_incident_use_case` plus `users`.

    It needs `users` because R1.4 tells the tenant's `PROPERTY_MANAGER`, and `notifications`
    both to cancel the deadline the assignment opened (R1.3) and to leave that row.
    """
    return RejectIncidentUseCase(
        users=SqlAlchemyUserRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        **_flow_kwargs(session),
    )


def get_wait_for_parts_use_case(session: SessionDep) -> WaitForPartsUseCase:
    return WaitForPartsUseCase(**_flow_kwargs(session))


def get_resume_work_use_case(session: SessionDep) -> ResumeWorkUseCase:
    return ResumeWorkUseCase(**_flow_kwargs(session))


def get_resolve_incident_use_case(session: SessionDep) -> ResolveIncidentUseCase:
    return ResolveIncidentUseCase(**_gate_kwargs(session), **_flow_kwargs(session))


def get_cancel_incident_use_case(session: SessionDep) -> CancelIncidentUseCase:
    return CancelIncidentUseCase(**_flow_kwargs(session))


def get_respond_owner_approval_use_case(
    session: SessionDep,
) -> RespondOwnerApprovalUseCase:
    return RespondOwnerApprovalUseCase(
        approvals=SqlAlchemyOwnerApprovalRepository(session), **_flow_kwargs(session)
    )
