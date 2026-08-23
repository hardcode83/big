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
from app.core.config import settings
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.api.dependencies import SigningKeyDep, storage_factory_for
from app.integrations.domain.storage import FileStorageFactory
from app.integrations.infrastructure.storage import INCIDENT_PHOTO_URL_PREFIX
from app.integrations.application.signed_serving import ServeSignedObjectUseCase
from app.maintenance.application.use_cases import (
    AcceptIncidentUseCase,
    ListIncidentPhotosUseCase,
    UploadIncidentPhotoUseCase,
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
    SqlAlchemyIncidentPhotoRepository,
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyUnscopedIncidentPhotoLocationQuery,
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


#: `maintenance` serves its photos from its own anonymous route, so it mints URLs with its own
#: prefix (R4.1). Sharing `cleaning`'s dependency would mint URLs pointing at
#: `/api/v1/cleaning-photos`, which cannot resolve an `incident_photos` id and would answer the
#: constant `403` — a broken feature that looks like a broken signing scheme.
get_incident_photo_storage_factory = storage_factory_for(INCIDENT_PHOTO_URL_PREFIX)

StorageFactoryDep = Annotated[
    FileStorageFactory, Depends(get_incident_photo_storage_factory)
]


# --- incident photos (`incident-photos` section 7, design D10) -------------------------


def get_upload_incident_photo_use_case(
    session: SessionDep, storage: StorageFactoryDep
) -> UploadIncidentPhotoUseCase:
    """R2 — the upload's wiring.

    `storage` comes from the shared builder in `app/integrations/api/dependencies.py`, which is
    the one place the object-store settings are read; this module never learns that a bucket, a
    region or an endpoint exists.

    `max_bytes` is read from `settings` **here** and handed in, so the use case receives its
    configuration the same way it receives its ports (R5.1: the existing
    `PHOTO_UPLOAD_MAX_BYTES`, no new setting). That is also what lets a test drive the `413`
    path with a two-byte ceiling instead of a 10 MB fixture.

    A unit of work and the audit repository, because this one writes: the object, the row and
    the audit entry are one transaction (design D7).
    """
    return UploadIncidentPhotoUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        photos=SqlAlchemyIncidentPhotoRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        max_bytes=settings.photo_upload_max_bytes,
    )


def get_list_incident_photos_use_case(
    session: SessionDep, storage: StorageFactoryDep
) -> ListIncidentPhotosUseCase:
    """R3.1 — reads only, so no unit of work and no audit repository.

    `configs` is here because the signed URL's shape depends on the tenant's backend, which is
    the one thing the use case must not decide for itself.
    """
    return ListIncidentPhotosUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        photos=SqlAlchemyIncidentPhotoRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
    )


def get_serve_incident_photo_use_case(
    session: SessionDep, storage: StorageFactoryDep, signing_key: SigningKeyDep
) -> ServeSignedObjectUseCase:
    """The anonymous serving route's wiring (design D5, D13) — the third builder of D10.

    **`SqlAlchemyUnscopedIncidentPhotoLocationQuery` is wired HERE and nowhere else**, which is
    what keeps the one tenant-less read in `maintenance` to the one route that cannot have a
    tenant. Every other builder in this module hands out `SqlAlchemyIncidentPhotoRepository`,
    whose every method demands one.

    The use case is `app/integrations/`'s, shared with `cleaning` since design D5; this builder
    is the seam that makes it resolve *incident* photos.

    The session it gets is the request's, and for this route nothing binds a tenant to it, so
    the query runs unfiltered — the precondition the adapter documents. That is not something
    the absence of `require(...)` guarantees: limit 2 of `_scope_statement_to_tenant`
    (`app/core/db.py`) says being anonymous is no guarantee of being unmarked. What holds the
    precondition if a dependency here ever starts binding is `require_unmarked_session`, which
    fails the read instead of letting it answer for one tenant.

    `signing_key` is the same dependency the factory signs with, so signing and verifying
    cannot drift apart.
    """
    return ServeSignedObjectUseCase(
        locations=SqlAlchemyUnscopedIncidentPhotoLocationQuery(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
        signing_key=signing_key,
    )
