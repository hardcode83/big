"""Wiring for the guest-document and legal-registration endpoints.

`MockSESHospedajesAdapter` is the provider, hardcoded, and PRD §29 keeps it that way for the
MVP. ADR 0006 decision 4 picks Chekin for the real one; what has to happen before that line
changes is in `app/guests/domain/ports.py` and is not a code question.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.application.portal import (
    IssueGuestAccessTokenUseCase,
    RevokeGuestAccessTokenUseCase,
)
from app.guests.application.use_cases import (
    ReadGuestDocumentUseCase,
    SetGuestDocumentUseCase,
    SubmitLegalRegistrationUseCase,
)
from app.guests.infrastructure.adapters import MockSESHospedajesAdapter
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationStayStore
from app.guests.infrastructure.portal_repositories import (
    SqlAlchemyGuestAccessTokenRepository,
    SqlAlchemyPortalStayLocator,
)
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_set_guest_document_use_case(session: SessionDep) -> SetGuestDocumentUseCase:
    return SetGuestDocumentUseCase(
        guests=SqlAlchemyGuestRepository(session),
        stays=SqlAlchemyLegalRegistrationStayStore(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_read_guest_document_use_case(session: SessionDep) -> ReadGuestDocumentUseCase:
    return ReadGuestDocumentUseCase(
        guests=SqlAlchemyGuestRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_issue_guest_access_token_use_case(
    session: SessionDep,
) -> IssueGuestAccessTokenUseCase:
    return IssueGuestAccessTokenUseCase(
        tokens=SqlAlchemyGuestAccessTokenRepository(session),
        stays=SqlAlchemyPortalStayLocator(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_revoke_guest_access_token_use_case(
    session: SessionDep,
) -> RevokeGuestAccessTokenUseCase:
    return RevokeGuestAccessTokenUseCase(
        tokens=SqlAlchemyGuestAccessTokenRepository(session),
        stays=SqlAlchemyPortalStayLocator(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_submit_legal_registration_use_case(
    session: SessionDep,
) -> SubmitLegalRegistrationUseCase:
    return SubmitLegalRegistrationUseCase(
        guests=SqlAlchemyGuestRepository(session),
        stays=SqlAlchemyLegalRegistrationStayStore(session),
        provider=MockSESHospedajesAdapter(),
        users=SqlAlchemyUserRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        tenant_configs=SqlAlchemyTenantConfigRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
