"""Wiring for the review endpoints: one builder per use case (design D12).

Same shape as `app/messaging/api/dependencies.py` and `app/maintenance/api/dependencies.py`.
The repositories take the session from `get_db_session` — the one `get_authenticated_request`
has already marked with the tenant, so the listener of `app/core/db.py` scopes ORM reads as
well. For `review_response_drafts` there is no net at all (R1.2), which is why its
adapter joins.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.reviews.application.use_cases import (
    ApproveReviewUseCase,
    ClassifyPendingReviewsUseCase,
    CreateReviewUseCase,
    EditReviewDraftUseCase,
    GetReviewDraftUseCase,
    GetReviewUseCase,
    IgnoreReviewUseCase,
    ListReviewsSummaryForPropertyUseCase,
    ListReviewsUseCase,
    MarkPostedManuallyUseCase,
    RegenerateReviewDraftUseCase,
)
from app.reviews.infrastructure.ai import MockReviewAnalyzer, MockReviewDraftGenerator
from app.reviews.infrastructure.repositories import (
    SqlAlchemyReviewRepository,
    SqlAlchemyReviewResponseDraftRepository,
)
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


#: One of each AI mock per process is fine — they are stateless. The construction lives
#: here so a future real provider swaps a single line.
_review_analyzer = MockReviewAnalyzer()
_review_draft_generator = MockReviewDraftGenerator()


def _audit(session: AsyncSession) -> SqlAlchemyAuditLogRepository:
    """One audit repository per request (R1.7, rule 9 of `sdd/steering/security.md`).

    All five review use cases that transition a row — Create, Approve, Ignore,
    MarkPostedManually, EditReviewDraft — share this single construction. The class is
    constructed per-call rather than per-process because the session is bound to the
    request that owns it, and the listener that scopes ORM reads by tenant is what makes
    the `WHERE tenant_id = :tenant_id` clauses the repositories write effective for
    this module too.
    """
    return SqlAlchemyAuditLogRepository(session)


def get_create_review_use_case(session: SessionDep) -> CreateReviewUseCase:
    return CreateReviewUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_reviews_use_case(session: SessionDep) -> ListReviewsUseCase:
    return ListReviewsUseCase(reviews=SqlAlchemyReviewRepository(session))


def get_get_review_use_case(session: SessionDep) -> GetReviewUseCase:
    return GetReviewUseCase(reviews=SqlAlchemyReviewRepository(session))


def get_get_review_draft_use_case(session: SessionDep) -> GetReviewDraftUseCase:
    return GetReviewDraftUseCase(drafts=SqlAlchemyReviewResponseDraftRepository(session))


def get_approve_review_use_case(session: SessionDep) -> ApproveReviewUseCase:
    return ApproveReviewUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        drafts=SqlAlchemyReviewResponseDraftRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_ignore_review_use_case(session: SessionDep) -> IgnoreReviewUseCase:
    return IgnoreReviewUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_mark_posted_manually_use_case(
    session: SessionDep,
) -> MarkPostedManuallyUseCase:
    return MarkPostedManuallyUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_regenerate_review_draft_use_case(
    session: SessionDep,
) -> RegenerateReviewDraftUseCase:
    return RegenerateReviewDraftUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        drafts=SqlAlchemyReviewResponseDraftRepository(session),
        draft_generator=_review_draft_generator,
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_edit_review_draft_use_case(session: SessionDep) -> EditReviewDraftUseCase:
    return EditReviewDraftUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        drafts=SqlAlchemyReviewResponseDraftRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_reviews_summary_use_case(
    session: SessionDep,
) -> ListReviewsSummaryForPropertyUseCase:
    return ListReviewsSummaryForPropertyUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_classify_pending_reviews_use_case(
    session: SessionDep,
) -> ClassifyPendingReviewsUseCase:
    return ClassifyPendingReviewsUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        drafts=SqlAlchemyReviewResponseDraftRepository(session),
        analyzer=_review_analyzer,
        draft_generator=_review_draft_generator,
        configs=SqlAlchemyTenantConfigRepository(session),
        audit=_audit(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )