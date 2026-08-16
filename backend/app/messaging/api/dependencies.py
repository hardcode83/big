"""Wiring for the conversation endpoints: one builder per use case (design D12, D17).

Same shape as `app/maintenance/api/dependencies.py`. The repositories take the session from
`get_db_session` — the one `get_authenticated_request` has already marked with the tenant, so
the listener of `app/core/db.py` scopes ORM reads as well. That is the net; the explicit
`tenant_id` every repository method takes is the mechanism. For `messages` there is no net at
all (R1.2), which is why its adapter joins.

**This is the layer entitled to know two domains** (D12), and it is where the incident port of
`messaging` meets its implementer in `maintenance` — with a `CallerOwnedUnitOfWork`, so the
single commit of R4.7 stays the pipeline's.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.db import get_db_session
from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.maintenance.application.use_cases import ReportIncidentFromConversationUseCase
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.messaging.application.use_cases import (
    CreateConversationUseCase,
    EscalateConversationUseCase,
    GetConversationUseCase,
    ListConversationsUseCase,
    ListMessagesUseCase,
    ProcessInboundGuestMessageUseCase,
    RecordHumanReplyUseCase,
    ResolveConversationUseCase,
)
from app.messaging.infrastructure.ai import MockAIAdapter
from app.messaging.infrastructure.channels import outbound_registry
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def incident_reporting_port(session: AsyncSession) -> ReportIncidentFromConversationUseCase:
    """`maintenance`'s implementer of `IncidentReportingPort`, with a **caller-owned** boundary.

    This is the whole of D12's transactional half, and it is one argument: handing it
    `SqlAlchemyUnitOfWork` would let the incident, its audit row and its timeline event land
    before the pipeline finished — so a failure afterwards would leave an incident nobody can
    trace back to a message, which is exactly the split `guest-portal-api` created before
    `CallerOwnedUnitOfWork` existed.
    """
    return ReportIncidentFromConversationUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=CallerOwnedUnitOfWork(),
    )


def get_process_inbound_message_use_case(
    session: SessionDep,
) -> ProcessInboundGuestMessageUseCase:
    return ProcessInboundGuestMessageUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
        # `MockAIAdapter` is the only implementer this change ships (R2.8,
        # `EXTERNAL_DEPENDENCY`). A real provider implements the same port and is swapped in
        # here — the one line that changes.
        ai=MockAIAdapter(),
        channels=outbound_registry(),
        incidents=incident_reporting_port(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_record_human_reply_use_case(session: SessionDep) -> RecordHumanReplyUseCase:
    return RecordHumanReplyUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_create_conversation_use_case(session: SessionDep) -> CreateConversationUseCase:
    """The property, reservation and guest repositories are not decoration here.

    This is the only route that takes `property_id`/`reservation_id`/`guest_id` **from a
    client**, and the foreign keys of `conversations` are global rather than composite with
    `tenant_id` — so without resolving them within the tenant first, a conversation of tenant A
    can be anchored to a property, a reservation or a guest of tenant B for ever.

    All three go in together because the omission of any one of them is the whole bug: the
    first implementation wired the first two and left `guest_id` unchecked, which the review
    of 2026-08-16 found.
    """
    return CreateConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_conversations_use_case(session: SessionDep) -> ListConversationsUseCase:
    return ListConversationsUseCase(
        conversations=SqlAlchemyConversationRepository(session)
    )


def get_conversation_use_case(session: SessionDep) -> GetConversationUseCase:
    return GetConversationUseCase(conversations=SqlAlchemyConversationRepository(session))


def get_list_messages_use_case(session: SessionDep) -> ListMessagesUseCase:
    return ListMessagesUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
    )


def get_escalate_conversation_use_case(
    session: SessionDep,
) -> EscalateConversationUseCase:
    return EscalateConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_resolve_conversation_use_case(
    session: SessionDep,
) -> ResolveConversationUseCase:
    return ResolveConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
