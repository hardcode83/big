"""Wiring for the anonymous guest portal (design D4, D6, D9).

Separate from `api/dependencies.py`, which wires the authenticated side. The split mirrors
the routers' own and buys the same thing: nothing here can accidentally be reached from a
route that expects a `User`, and nothing there can accidentally be handed a `GuestSession`.

**Every use case takes the same `AsyncSession`**, and that is not incidental. The authoriser
calls `bind_session_to_tenant` on it (D4 step 4), so the global tenant filter only covers the
rest of the request if the repositories share that exact instance. FastAPI caches
`Depends(get_db_session)` per request, which is what makes it one — a second session built
here would silently be unbound, which is the tenancy panel's standing warning for §6.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.config import settings
from app.core.db import get_db_session
from app.core.redis import get_redis
from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.application.portal import (
    GetCheckinStatusUseCase,
    GetStayInfoUseCase,
    GuestPortalAuthenticator,
    SubmitGuestCheckinUseCase,
)
from app.guests.application.use_cases import SetGuestDocumentUseCase
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationStayStore
from app.guests.infrastructure.portal_repositories import (
    SessionTenantBinder,
    SqlAlchemyGuestAccessTokenRepository,
    SqlAlchemyGuestPortalStayReader,
    SqlAlchemyPortalStayLocator,
)
from app.guests.infrastructure.portal_throttle import RedisGuestPortalThrottle
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.maintenance.application.use_cases import ReportGuestIncidentUseCase
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

def get_guest_portal_throttle() -> RedisGuestPortalThrottle:
    """Built from configuration on every request, following `get_webhook_throttle`.

    `settings` is read here rather than closed over at import time, so an operator changing a
    limit does not have to rebuild the application and a test can move it without reimporting.
    """
    return RedisGuestPortalThrottle(
        get_redis(),
        requests_per_minute=settings.guest_portal_rate_limit_per_minute,
        probes_per_minute=settings.guest_portal_probe_limit_per_minute,
    )


def get_guest_portal_authenticator(session: SessionDep) -> GuestPortalAuthenticator:
    return GuestPortalAuthenticator(
        tokens=SqlAlchemyGuestAccessTokenRepository(session),
        stays=SqlAlchemyPortalStayLocator(session),
        binder=SessionTenantBinder(session),
        grace_days=settings.guest_portal_token_grace_days,
    )


def get_stay_info_use_case(session: SessionDep) -> GetStayInfoUseCase:
    return GetStayInfoUseCase(
        stays=SqlAlchemyGuestPortalStayReader(
            session,
            # A configuration constant, not a row (D9): reading a support contact from the
            # database would be one join away from exposing whoever staffs it. Read here
            # rather than closed over at import time, like the throttle above, so an operator
            # changing it does not have to rebuild the application.
            support_channel=settings.guest_portal_support_channel,
        )
    )


def get_checkin_status_use_case(session: SessionDep) -> GetCheckinStatusUseCase:
    return GetCheckinStatusUseCase(
        guests=SqlAlchemyGuestRepository(session),
        stays=SqlAlchemyPortalStayLocator(session),
    )


def get_submit_guest_checkin_use_case(session: SessionDep) -> SubmitGuestCheckinUseCase:
    guests = SqlAlchemyGuestRepository(session)
    legal = SqlAlchemyLegalRegistrationStayStore(session)
    return SubmitGuestCheckinUseCase(
        guests=guests,
        stays=SqlAlchemyPortalStayLocator(session),
        legal=legal,
        # The one writer of `guests.document_number_encrypted`, reused rather than
        # reimplemented (D10). `CallerOwnedUnitOfWork` is what makes D10's "un solo
        # `UnitOfWork`, un solo `commit()` al final" true: `SetGuestDocumentUseCase.execute`
        # ends with `await self._uow.commit()` unconditionally, so with a real one here the
        # document, its audit row and the `Guest` OQ3 creates would land **before** the
        # milestone the outer use case still has to write.
        documents=SetGuestDocumentUseCase(
            guests=guests,
            stays=legal,
            audit=SqlAlchemyAuditLogRepository(session),
            uow=CallerOwnedUnitOfWork(),
        ),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_report_guest_incident_use_case(session: SessionDep) -> ReportGuestIncidentUseCase:
    """`maintenance`'s use case, wired from the portal (R5.5, D15).

    Wired here rather than in a `maintenance/api/dependencies.py`, because D15 gives that
    module no `api/` at all: the route belongs to the portal, so this is where its ports get
    their adapters. The same `AsyncSession` as every other portal use case — the authoriser has
    already bound it to the tenant it resolved, and a second session built here would silently
    be unbound.
    """
    return ReportGuestIncidentUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
