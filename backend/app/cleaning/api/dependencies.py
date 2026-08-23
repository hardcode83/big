"""Wiring for the cleaning endpoints: one builder per use case.

Same shape as `app/reservations/api/dependencies.py`. The repositories take the session
from `get_db_session` — the same session `get_authenticated_request` has already marked
with the tenant, so the listener of `app/core/db.py` scopes ORM reads as well.

That net does **not** reach `cleaning_checklist_completions`, which has no `tenant_id`
column (design D6); there the explicit `JOIN` inside the adapter is the only mechanism.
"""

from functools import partial
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.evidence import CompletionEvidenceGatherer
from app.cleaning.application.use_cases import (
    AcceptCleaningTaskUseCase,
    AssignCleaningTaskUseCase,
    CancelCleaningTaskUseCase,
    CompleteChecklistItemUseCase,
    CompleteCleaningTaskUseCase,
    CreateChecklistTemplateUseCase,
    CreateCleaningTaskUseCase,
    GetChecklistUseCase,
    GetCleaningTaskContextUseCase,
    GetCleaningTaskUseCase,
    ListChecklistTemplatesUseCase,
    ListCleaningPhotosUseCase,
    ListCleaningTasksUseCase,
    RejectCleaningTaskUseCase,
    ServeLocalCleaningPhotoUseCase,
    StartCleaningTaskUseCase,
    UploadCleaningPhotoUseCase,
    ValidateCleaningTaskUseCase,
)
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyBlockingIncidentQuery,
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningPhotoRepository,
    SqlAlchemyCleaningTaskRepository,
    SqlAlchemyUnscopedCleaningPhotoLocationQuery,
)
from app.core.config import settings
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.domain.storage import FileStorageFactory, derive_signing_key
from app.integrations.infrastructure.storage import (
    ConfiguredFileStorageFactory,
    build_s3_client,
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


def get_cancel_cleaning_task_use_case(session: SessionDep) -> CancelCleaningTaskUseCase:
    """Takes the notification port for the same reason `reject` does: cancelling a task that was
    only `ASSIGNED` has to close its assignment SLA, or the manager is escalated about a task that
    no longer exists (design D8, corrected in section 5)."""
    return CancelCleaningTaskUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        **_lifecycle_kwargs(session),
    )


def get_start_cleaning_task_use_case(session: SessionDep) -> StartCleaningTaskUseCase:
    return StartCleaningTaskUseCase(**_lifecycle_kwargs(session))


def get_complete_cleaning_task_use_case(session: SessionDep) -> CompleteCleaningTaskUseCase:
    """The four reads of the close now arrive as one collaborator (design D5).

    No `Depends` of its own for the gatherer: this module has one builder per use case and the
    gatherer is not one, so a node in FastAPI's dependency graph that nobody else consumes would
    buy nothing. Same four adapters and the same request session as before — the one already
    marked with the tenant, which is what the listener of `app/core/db.py` scopes ORM reads by.
    """
    return CompleteCleaningTaskUseCase(
        evidence=CompletionEvidenceGatherer(
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
            # PRD §11's third clause (R4): the close reads which photo types are already there.
            photos=SqlAlchemyCleaningPhotoRepository(session),
            incidents=SqlAlchemyBlockingIncidentQuery(session),
        ),
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


def get_url_signing_key() -> bytes:
    """The HKDF-derived URL signing key of design D6.

    Its own dependency because **two** things need the same bytes and must not drift: the
    factory below, which signs, and `ServeLocalCleaningPhotoUseCase`, which verifies. Deriving
    it twice from `settings` would work, but it would also let a test override one half and
    silently leave the other on the real secret — every signature would then be refused, and
    the failure would look like a broken signing scheme rather than like a broken fixture.

    The key is derived per call rather than cached. It is two HMACs of a 32-byte input, and a
    module-level cache of a value computed from `JWT_SECRET_KEY` is the kind of thing that
    survives a settings change in a test and then explains nothing when a signature stops
    verifying. `derive_signing_key` is pure, so calling it is the cheap option and the honest
    one.
    """
    return derive_signing_key(settings.jwt_secret_key)


SigningKeyDep = Annotated[bytes, Depends(get_url_signing_key)]


def get_file_storage_factory(signing_key: SigningKeyDep) -> FileStorageFactory:
    """The tenant-agnostic factory of design D1, wired with the derived URL signing key.

    Its own dependency, and overridable as one, so a test can point the `LOCAL` root at a
    temporary directory without reaching into the use case builders below.

    **This is the only place the object-store settings are read** (`object-storage-provisioning`
    design D5, R3.2): the use cases receive the factory and never learn a bucket, a region or an
    endpoint exists. `partial` keeps `s3_client_factory` a zero-argument callable, so the tests
    that inject a spy through this same dependency go on working unchanged.

    `.strip() or None` is what satisfies R3.4: an unset variable arrives as `""`, and boto3 reads
    an empty `endpoint_url` as an endpoint rather than as its absence. Turning it into `None` is
    what makes "point at AWS" mean *configure nothing*.

    The `.strip()` is not decoration, and a bare `or None` was wrong here. A whitespace-only value
    — one stray space surviving a hand-edited `.env` — is truthy, so it would reach
    `boto3.client(...)` and raise `InvalidRegionError` or `ValueError: Invalid endpoint:` straight
    out of `storage_for(S3)`, bypassing the `StorageWriteError` contract that
    `ConfiguredFileStorageFactory` otherwise guarantees for a misconfigured store. The bucket beside
    it has always been read as `s3_bucket.strip()` for exactly this reason; these two now match it.
    """
    return ConfiguredFileStorageFactory(
        signing_key=signing_key,
        s3_bucket=settings.s3_bucket,
        s3_client_factory=partial(
            build_s3_client,
            region_name=settings.s3_region.strip() or None,
            endpoint_url=settings.s3_endpoint_url.strip() or None,
        ),
    )


StorageFactoryDep = Annotated[FileStorageFactory, Depends(get_file_storage_factory)]


def get_upload_cleaning_photo_use_case(
    session: SessionDep, storage: StorageFactoryDep
) -> UploadCleaningPhotoUseCase:
    """R2 — no `_lifecycle_kwargs`: an upload moves no property state.

    It takes the four repositories it actually reads and writes, plus the storage factory and
    the byte ceiling. `settings.photo_upload_max_bytes` is read HERE and handed in, so the use
    case stays free of `app.core.config` and a test can drive the 413 path without a 10 MB
    fixture — the same shape `csv_import_max_bytes` already uses.
    """
    return UploadCleaningPhotoUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        photos=SqlAlchemyCleaningPhotoRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        max_bytes=settings.photo_upload_max_bytes,
    )


def get_cleaning_task_context_use_case(session: SessionDep) -> GetCleaningTaskContextUseCase:
    """R1.1 — a read, so no unit of work and no audit repository (design D2).

    The three repositories the module already hands out elsewhere. Composing them here rather than
    wiring a bespoke reader is what keeps the tenant scope written in one place: each `get` takes
    its `tenant_id` explicitly, and `app/core/db.py`'s listener is defence in depth behind it.
    """
    return GetCleaningTaskContextUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
    )


def get_list_cleaning_photos_use_case(
    session: SessionDep, storage: StorageFactoryDep
) -> ListCleaningPhotosUseCase:
    """R3.1 — reads only, so no unit of work and no audit repository.

    `configs` is here because the signed URL's shape depends on the tenant's backend, which is
    the one thing the use case must not decide for itself (R1.2).
    """
    return ListCleaningPhotosUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        photos=SqlAlchemyCleaningPhotoRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
    )


def get_serve_local_cleaning_photo_use_case(
    session: SessionDep, storage: StorageFactoryDep, signing_key: SigningKeyDep
) -> ServeLocalCleaningPhotoUseCase:
    """The anonymous serving route's wiring (design D7, D7b).

    **`SqlAlchemyUnscopedCleaningPhotoLocationQuery` is wired HERE and nowhere else**, which is
    what keeps the one tenant-less read in `cleaning` to the one route that cannot have a
    tenant. Every other builder in this module hands out `SqlAlchemyCleaningPhotoRepository`,
    whose every method demands one.

    The session it gets is the request's, and for this route nothing binds a tenant to it, so
    the query runs unfiltered — the precondition it documents. That is this chain as it stood
    on 2026-08-17, read off by a person; no test asserts it, and it is **not** something the
    absence of `require(...)` guarantees: limit 2 of `_scope_statement_to_tenant` (`app/core/db.py`) says being anonymous
    is no guarantee of being unmarked, and names the cases — which this docstring deliberately
    does not repeat. What holds the precondition if a dependency here ever starts binding is
    `require_unmarked_session`, which fails the read instead of letting it answer for one
    tenant.

    `signing_key` is the same dependency the factory signs with, so signing and verifying
    cannot drift apart.
    """
    return ServeLocalCleaningPhotoUseCase(
        locations=SqlAlchemyUnscopedCleaningPhotoLocationQuery(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=storage,
        signing_key=signing_key,
    )
