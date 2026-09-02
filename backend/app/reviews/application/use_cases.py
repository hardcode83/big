"""The reviews use cases (R5, R6; design D9, D11, D12).

Eleven use cases, each one verb of the flow. The split mirrors `messaging` and
`maintenance`: orchestration only, every rule lives in `domain/`. The state machine on
`Review` is the entity's, the templates are the catalogue's, the tenant isolation is
the repository adapter's.

Two of the eleven are **purely a job**: `ClassifyPendingReviewsUseCase` is the loop
the scheduler calls per tenant, and the use cases it composes do the actual work
on each row.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.enums import UserRole
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.core.unit_of_work import UnitOfWork
from app.notifications.domain.repositories import NotificationLogRepository
from app.reviews.domain.entities import Review, ReviewResponseDraft
from app.reviews.domain.enums import (
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)
from app.reviews.domain.exceptions import (
    InvalidReviewTransitionError,
    ReviewLanguageInferenceError,
    ReviewNotFoundError,
)
from app.reviews.domain.language import detect_or_raise
from app.reviews.domain.notifications import (
    build_review_response_approved_log,
)
from app.reviews.domain.ports import (
    AIReviewAnalyzer,
    AIReviewDraftGenerator,
    ReviewFilters,
    ReviewPage,
    ReviewRepository,
    ReviewResponseDraftRepository,
)
from app.reviews.domain.templates import (
    REVIEW_DRAFT_TEMPLATES_VERSION,
    assert_in_catalogue,
)
from app.tenants.domain.repositories import TenantConfigRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)


#: Per-event titles for the timeline. Constants, and `metadata` carries identifiers only
#: — never the reviewer's body (R6.1, rule 11 of `steering/security.md`).
_TIMELINE_TITLES: dict[TimelineEventType, str] = {
    TimelineEventType.REVIEW_CREATED: "Review created",
    TimelineEventType.REVIEW_RESPONSE_DRAFTED: "Review response drafted",
    TimelineEventType.REVIEW_DRAFT_EDITED: "Review response draft edited",
    TimelineEventType.REVIEW_CLASSIFIED_LOW_CONFIDENCE: "Review classified with low confidence",
    TimelineEventType.REVIEW_RESPONSE_APPROVED: "Review response approved",
    TimelineEventType.REVIEW_IGNORED: "Review ignored",
    TimelineEventType.REVIEW_POSTED_MANUALLY: "Review posted manually",
}

#: Maximum number of reviews one tick of `classify_reviews` will touch. A tenant whose
#: analyser was down all night must not turn one tick into an unbounded run (D2/D16).
_DEFAULT_CLASSIFY_BATCH_SIZE = 100


@dataclass
class ReviewClassificationReport:
    """What one tenant's tick of the classification job produced.

    Mutable on purpose: the loop increments counters as it walks the pending rows, and
    `frozen=True` would have meant `dataclasses.replace` for each increment — cheaper to
    leave the dataclass mutable than to copy it five times per tenant.
    """

    tenant_id: str
    scanned: int = 0
    classified: int = 0
    low_confidence: int = 0
    failed: int = 0
    manual_triage: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timeline_event(
    *,
    review: Review,
    event_type: TimelineEventType,
    actor_type: TimelineActorType,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, str],
    now: datetime,
) -> TimelineEventData:
    """One builder for the seven review events, so no call site can invent a title.

    `property_id` is not optional for `TimelineEventFactory`, and `Review` refuses to
    exist without one (D4, R1.5) — which is the whole reason that refusal is there.
    """
    return TimelineEventData(
        id=uuid.uuid4(),
        tenant_id=review.tenant_id,
        property_id=review.property_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        event_type=event_type,
        title=_TIMELINE_TITLES[event_type],
        created_at=now,
        reservation_id=review.reservation_id,
        metadata=metadata,
    )


def _resolve_language(content: str | None, explicit: str | None) -> str:
    """Pick the language the rest of the flow will use.

    An explicit value the caller supplied wins (R5.1); otherwise we run the
    heuristic on the body. `detect_or_raise` raises `ReviewLanguageInferenceError`
    when the verdict is `None`, and the use cases catch that and answer `422`.
    """
    if explicit is not None:
        return explicit
    return detect_or_raise(content)


# ---------------------------------------------------------------------------
# Create, list, get
# ---------------------------------------------------------------------------


class CreateReviewUseCase:
    """R5.1, R5.2, R6.1 — create the row, persist it with neutral defaults, and emit
    `REVIEW_CREATED`.

    The classification pipeline runs asynchronously (R2.1); the row is born `NEW` with
    `sentiment = NEUTRAL`, `ai_summary = NULL`, `recurring_issues = []`. The first thing
    `classify_reviews` does on its next tick is pick the row up.

    The transaction commits the row, the audit and the timeline event together, so
    there is no state in which a review exists that nobody can attribute or that the
    property's timeline does not show.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._audit = audit
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        property_id: uuid.UUID,
        channel: ReviewChannel,
        actor_ip: str | None,
        reviewer_name: str | None,
        rating: object,
        content: str | None,
        language: str | None,
        reservation_id: uuid.UUID | None,
        now: datetime,
    ) -> Review:
        from decimal import Decimal

        from app.reviews.domain.entities import _assert_rating

        # R5.1: validate the rating here too so the use case answers `422` rather than
        # waiting for the entity. The entity's own guard is the second net.
        rating_value: Decimal | None
        if rating is None:
            rating_value = None
        elif isinstance(rating, Decimal):
            rating_value = rating
        else:
            rating_value = Decimal(str(rating))
            _assert_rating(rating_value)

        resolved_language = _resolve_language(content, language)

        review = Review(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property_id,
            channel=channel,
            created_at=now,
            updated_at=now,
            reservation_id=reservation_id,
            reviewer_name=reviewer_name,
            rating=rating_value,
            content=content,
            language=resolved_language,
            sentiment=ReviewSentiment.NEUTRAL,
            ai_summary=None,
            recurring_issues=(),
            status=ReviewStatus.NEW,
        )

        await self._reviews.add(tenant_id, review)

        # R6.1: `REVIEW_CREATED` carries `review_id`, `property_id`, `channel` — identifiers
        # and closed enums only, never the reviewer's body.
        timeline_event = _timeline_event(
            review=review,
            event_type=TimelineEventType.REVIEW_CREATED,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            metadata={
                "review_id": str(review.id),
                "property_id": str(review.property_id),
                "channel": channel.value,
            },
            now=now,
        )
        await self._timeline.add(
            tenant_id, TimelineEventFactory.create(timeline_event)
        )

        # R1.7: audit the create in the same transaction as the row. `changes` is empty
        # because the row is a fresh insert — the entity's columns carry the diff, and a
        # `null → <value>` replay would just duplicate them. The rule-11 audit row
        # identifies the review by `entity_id`, and the `changes` shape (empty here) is
        # what rule 9 prescribes for inserts.
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.REVIEW_CREATED,
                entity_type=audit_actions.ENTITY_REVIEW,
                entity_id=review.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=ChangeSet(audit_actions.ENTITY_REVIEW),
                now=now,
            ),
        )

        await self._uow.commit()
        return review


class ListReviewsUseCase:
    """R5.3 — the inbox listing, by property or by tenant."""

    def __init__(self, *, reviews: ReviewRepository) -> None:
        self._reviews = reviews

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: ReviewFilters,
        page: int,
        per_page: int,
        property_id: uuid.UUID | None = None,
    ) -> ReviewPage:
        if property_id is not None:
            return await self._reviews.list_for_property(
                tenant_id, property_id, filters, page=page, per_page=per_page
            )
        return await self._reviews.list_for_tenant(
            tenant_id, filters, page=page, per_page=per_page
        )


class GetReviewUseCase:
    """R5.4 — one review, with the `404` indistinguishability of R1.3."""

    def __init__(self, *, reviews: ReviewRepository) -> None:
        self._reviews = reviews

    async def execute(
        self, *, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> Review:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        return review


class GetReviewDraftUseCase:
    """R5.4 — the draft of one review, or `404` indistinguishably."""

    def __init__(self, *, drafts: ReviewResponseDraftRepository) -> None:
        self._drafts = drafts

    async def execute(
        self, *, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> ReviewResponseDraft:
        draft = await self._drafts.get_for_review(tenant_id, review_id)
        if draft is None:
            raise ReviewNotFoundError()
        return draft


# ---------------------------------------------------------------------------
# Approve, ignore, mark posted, regenerate, edit
# ---------------------------------------------------------------------------


class ApproveReviewUseCase:
    """R3.6, R4.1 — manager/owner approves the draft and the review transitions to
    `APPROVED`. The notification fires in the same transaction.

    **`actor_id` is required**: a person with `APPROVE_REVIEW` is at the keyboard. R6.2
    fires a notification to the manager/owner recipients and writes a timeline event
    in this same transaction.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        drafts: ReviewResponseDraftRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        notifications: NotificationLogRepository,
        users: UserRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._drafts = drafts
        self._audit = audit
        self._timeline = timeline
        self._notifications = notifications
        self._users = users
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        review_id: uuid.UUID,
        now: datetime,
    ) -> Review:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        draft = await self._drafts.get_for_review(tenant_id, review_id)
        if draft is None:
            raise ReviewNotFoundError()
        # Approve both rows in the same transaction.
        draft.approve(actor_id=actor_user_id, now=now)
        await self._drafts.save(tenant_id, draft)

        review.approve(now=now)
        await self._reviews.save(tenant_id, review)

        # R6.2 — `NotificationType.REVIEW_RESPONSE_APPROVED` to managers and owners.
        # `RoleRecipients.managers_or_owners` is the project's helper for "the people
        # who care about this row" — same pattern the conversation escalation uses.
        # The repository query is a `UserRepository.list` per role because the helper
        # returns ids, and the notification row needs each recipient's contact.
        recipients: list = []
        for role in (UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER):
            page = await self._users.list(
                tenant_id=tenant_id,
                filters=UserFilters(role=role),
                page=1,
                per_page=100,
            )
            recipients.extend(page.items)
        for user in recipients:
            notification = build_review_response_approved_log(
                tenant_id=tenant_id,
                review_id=review.id,
                property_id=review.property_id,
                recipient_user_id=user.id,
                recipient_contact=user.email,
                now=now,
            )
            await self._notifications.add(tenant_id, notification)

        # R6.1 — `REVIEW_RESPONSE_APPROVED`.
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_RESPONSE_APPROVED,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                    },
                    now=now,
                )
            ),
        )

        # R1.7: audit the approve in the same transaction as the row and the notification.
        # The draft row carries `approved_by`/`approved_at` (R3.6), but the **vocabulary**
        # rule 9 demands is the `REVIEW_APPROVED` action and `ENTITY_REVIEW` — the audit
        # log is about the review, not about the draft (which has its own
        # `ENTITY_REVIEW_RESPONSE_DRAFT` for edits).
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.REVIEW_APPROVED,
                entity_type=audit_actions.ENTITY_REVIEW,
                entity_id=review.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=ChangeSet(audit_actions.ENTITY_REVIEW)
                .diff("status", ReviewStatus.DRAFTED.value, ReviewStatus.APPROVED.value),
                now=now,
            ),
        )

        await self._uow.commit()
        return review


class IgnoreReviewUseCase:
    """R4.1 — the manager/owner shelves the review. No draft is produced.

    The transition is a `Review.ignore()`; the audit and the timeline event follow.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._audit = audit
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        review_id: uuid.UUID,
        now: datetime,
    ) -> Review:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        review.ignore(now=now)
        await self._reviews.save(tenant_id, review)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_IGNORED,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                    },
                    now=now,
                )
            ),
        )

        # R1.7: audit the ignore. The status diff carries the from-state in
        #  — a  or  is the only thing that
        # makes the row attributable to a particular actor in the trail, and 
        # is what the index  answers
        # before the action does.
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.REVIEW_IGNORED,
                entity_type=audit_actions.ENTITY_REVIEW,
                entity_id=review.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=ChangeSet(audit_actions.ENTITY_REVIEW)
                .diff("status", review.status.value, ReviewStatus.IGNORED.value),
                now=now,
            ),
        )

        await self._uow.commit()
        return review


class MarkPostedManuallyUseCase:
    """R4.4 — the manager records that the answer was posted outside the system.

    The transition is `Review.mark_posted_manually()`; **no PMS adapter is invoked**
    (D12). The row is the audit trail of a person, not a call our system made.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._audit = audit
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        review_id: uuid.UUID,
        now: datetime,
    ) -> Review:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        review.mark_posted_manually(now=now)
        await self._reviews.save(tenant_id, review)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_POSTED_MANUALLY,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                    },
                    now=now,
                )
            ),
        )

        # R1.7: audit the manual posting. The `status` field goes from APPROVED to
        # POSTED_MANUALLY (the only legal move); the row's `published_at` is the actor's
        # witness, not the audit's. Posting is a person action, not a system call —
        # `R4.4` documents that no PMS adapter is invoked here.
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.REVIEW_POSTED_MANUALLY,
                entity_type=audit_actions.ENTITY_REVIEW,
                entity_id=review.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=ChangeSet(audit_actions.ENTITY_REVIEW)
                .diff(
                    "status", ReviewStatus.APPROVED.value, ReviewStatus.POSTED_MANUALLY.value
                ),
                now=now,
            ),
        )

        await self._uow.commit()
        return review


class RegenerateReviewDraftUseCase:
    """R3.5 / D5 — replace the existing draft with a new one in a single transaction.

    `UPDATE` by `review_id`, not `DELETE + INSERT`, so the row stays reachable and the
    audit trail sees one operation. `ai_generated` stays `TRUE` (provenance, not state).
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        drafts: ReviewResponseDraftRepository,
        draft_generator: AIReviewDraftGenerator,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._drafts = drafts
        self._draft_generator = draft_generator
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        review_id: uuid.UUID,
        now: datetime,
    ) -> ReviewResponseDraft:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        # The catalogue has no entry for `IGNORED` / `POSTED_MANUALLY` (D12); the use case
        # never asks for one.
        if review.status in (ReviewStatus.IGNORED, ReviewStatus.POSTED_MANUALLY):
            raise InvalidReviewTransitionError(
                f"Cannot regenerate a draft on a {review.status.value} review"
            )
        # `language` is whatever the review resolved; if it's still NULL (a body the
        # detector could not decide on), this use case cannot proceed.
        if review.language is None:
            raise ReviewLanguageInferenceError(
                "Cannot regenerate a draft on a review without a resolved language"
            )
        draft_vo = await self._draft_generator.generate_draft(
            review=review, language=review.language
        )
        # D7 — the runtime check the pipeline owes: `content` must be a member of the
        # module's catalogue, not just the adapter's declared vocabulary.
        assert_in_catalogue(draft_vo.content)

        existing = await self._drafts.get_for_review(tenant_id, review_id)
        if existing is None:
            new_draft = ReviewResponseDraft(
                id=uuid.uuid4(),
                review_id=review.id,
                draft_content=draft_vo.content,
                language=draft_vo.language,
                created_at=now,
                updated_at=now,
                ai_generated=True,
                edits_count=0,
            )
            await self._drafts.add(tenant_id, new_draft)
        else:
            existing.draft_content = draft_vo.content
            existing.language = draft_vo.language
            existing.edits_count = 0
            existing.updated_at = now
            await self._drafts.save(tenant_id, existing)
            new_draft = existing

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_RESPONSE_DRAFTED,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                        "template_version": draft_vo.template_version,
                    },
                    now=now,
                )
            ),
        )
        await self._uow.commit()
        return new_draft


class EditReviewDraftUseCase:
    """R3.5 — a manager rewrites the AI's draft.

    The entity mutates `draft_content` and increments `edits_count`; the audit and
    the timeline event are the use case's.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        drafts: ReviewResponseDraftRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._drafts = drafts
        self._audit = audit
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        review_id: uuid.UUID,
        new_content: str,
        now: datetime,
    ) -> ReviewResponseDraft:
        review = await self._reviews.get(tenant_id, review_id)
        if review is None:
            raise ReviewNotFoundError()
        draft = await self._drafts.get_for_review(tenant_id, review_id)
        if draft is None:
            raise ReviewNotFoundError()
        # The entity enforces "approved locks the content" — keep this in front so the
        # use case fails before it touches the audit row.
        draft.edit(new_content=new_content, now=now)
        await self._drafts.save(tenant_id, draft)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_DRAFT_EDITED,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                        "edits_count": str(draft.edits_count),
                    },
                    now=now,
                )
            ),
        )

        # R3.5: audit the draft edit. The audit row points at the **draft**, not the
        # review — R3.5's vocabulary is `REVIEW_DRAFT_EDITED` and the entity that the
        # actor edited is the draft. `entity_id` is `draft.id`; rule 9's `entity_type`
        # is `ENTITY_REVIEW_RESPONSE_DRAFT`. `edits_count` travels in `changes` because
        # it is the value the actor changed by acting, and the audit row's diff is
        # what the rule-9 query answers.
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.REVIEW_DRAFT_EDITED,
                entity_type=audit_actions.ENTITY_REVIEW_RESPONSE_DRAFT,
                entity_id=draft.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=ChangeSet(audit_actions.ENTITY_REVIEW_RESPONSE_DRAFT)
                .diff("edits_count", str(draft.edits_count - 1), str(draft.edits_count)),
                now=now,
            ),
        )

        await self._uow.commit()
        return draft


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class ListReviewsSummaryForPropertyUseCase:
    """R5.5 — the per-property card the dashboard renders.

    Sentiment histogram and top-N recurring-issue counts, both within a 90-day window.
    The `top_n` bound is the tenant's own setting (`TenantConfig.review_recurring_issues_top_n`).
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        configs: TenantConfigRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reviews = reviews
        self._configs = configs
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        window_days: int = 90,
        now: datetime | None = None,
    ) -> dict:
        config = await self._configs.get_or_create(
            tenant_id, now or datetime.now(UTC)
        )
        counts = await self._reviews.count_by_sentiment_for_property(
            tenant_id, property_id, window_days=window_days
        )
        tags = await self._reviews.aggregate_recurring_issues_for_property(
            tenant_id,
            property_id,
            window_days=window_days,
            top_n=config.review_recurring_issues_top_n,
        )
        await self._uow.commit()
        return {
            "window_days": window_days,
            "top_n": config.review_recurring_issues_top_n,
            "by_sentiment": counts,
            "by_recurring_issue": tags,
        }


# ---------------------------------------------------------------------------
# Classification job
# ---------------------------------------------------------------------------


class ClassifyPendingReviewsUseCase:
    """The job of D2/D16 — every `NEW` review that the pipeline hasn't touched yet.

    **One transaction per review, not one per tick.** `ClassifyOneReviewUseCase` commits
    its own work, so a tenant with fifty pending reviews and an analyser that dies on
    the thirty-first keeps thirty — and the other twenty come back on the next tick
    because their `ai_summary IS NULL`. A single transaction around the loop would trade
    that for an all-or-nothing run of unbounded length.

    Bounded by `batch_size` for the same reason the notification jobs are: a tick has
    to end.
    """

    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        drafts: ReviewResponseDraftRepository,
        analyzer: AIReviewAnalyzer,
        draft_generator: AIReviewDraftGenerator,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
        batch_size: int = _DEFAULT_CLASSIFY_BATCH_SIZE,
    ) -> None:
        self._reviews = reviews
        self._drafts = drafts
        self._analyzer = analyzer
        self._draft_generator = draft_generator
        self._configs = configs
        self._audit = audit
        self._timeline = timeline
        self._uow = uow
        self._batch_size = batch_size

    async def execute(
        self, *, tenant_id: uuid.UUID, now: datetime
    ) -> ReviewClassificationReport:
        report = ReviewClassificationReport(tenant_id=str(tenant_id))
        config = await self._configs.get_or_create(tenant_id, now)
        pending = await self._reviews.list_pending_classification(
            tenant_id, limit=self._batch_size
        )

        for review in pending:
            report.scanned += 1
            outcome = await self._classify_one(
                tenant_id=tenant_id,
                review=review,
                config=config,
                now=now,
            )
            if outcome == "classified":
                report.classified += 1
            elif outcome == "low_confidence":
                report.low_confidence += 1
            elif outcome == "failed":
                report.failed += 1
            elif outcome == "manual_triage":
                report.manual_triage += 1

        return report

    async def _classify_one(
        self,
        *,
        tenant_id: uuid.UUID,
        review: Review,
        config,
        now: datetime,
    ) -> str:
        """The single-review pipeline: analyse, then maybe draft. Returns an outcome label.

        Outcomes:
        - `"classified"`: success — the row carries sentiment/summary/recurring_issues
          and a draft exists.
        - `"low_confidence"`: below `TenantConfig.ai_confidence_threshold` — the three
          AI fields are cleared and a `REVIEW_CLASSIFIED_LOW_CONFIDENCE` is emitted (R2.3).
        - `"failed"`: the analyser raised — the attempt counter is incremented; the next
          tick will try again unless the cap is reached.
        - `"manual_triage"`: the third consecutive failure — the row is parked for a
          human, and no further retry is automatic.
        """
        if review.language is None:
            # R5.1: a body the detector could not decide on stays `NEW`; the language
            # has to come from the manager. Skip until the manual triage screen fills it.
            review.increment_attempts(now=now)
            await self._reviews.save(tenant_id, review)
            await self._uow.commit()
            return "manual_triage"

        try:
            analysis = await self._analyzer.analyze_review(
                content=review.content or "", language=review.language
            )
        except Exception as error:  # noqa: BLE001 - the analyser is the adapter's owner
            logger.warning(
                "reviews.classification_failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "review_id": str(review.id),
                    "error_type": type(error).__name__,
                },
            )
            review.increment_attempts(now=now)
            await self._reviews.save(tenant_id, review)
            await self._uow.commit()
            if review.classification_attempts >= 3:
                # R2.4: the third consecutive failure parks the row for manual triage.
                return "manual_triage"
            return "failed"

        # R2.3: below the tenant's threshold, the three AI fields are cleared and the
        # row transitions to `DRAFTED` so the manager sees something has happened — the
        # `REVIEW_CLASSIFIED_LOW_CONFIDENCE` event names the difference between a
        # confident answer and a hesitant one.
        if analysis.confidence < config.ai_confidence_threshold:
            review.mark_classified_low_confidence(
                sentiment=analysis.sentiment, now=now
            )
            await self._reviews.save(tenant_id, review)
            await self._timeline.add(
                tenant_id,
                TimelineEventFactory.create(
                    _timeline_event(
                        review=review,
                        event_type=TimelineEventType.REVIEW_CLASSIFIED_LOW_CONFIDENCE,
                        actor_type=TimelineActorType.SCHEDULER,
                        actor_user_id=None,
                        metadata={
                            "review_id": str(review.id),
                            "property_id": str(review.property_id),
                            "sentiment": analysis.sentiment.value,
                            "confidence": str(analysis.confidence),
                        },
                        now=now,
                    )
                ),
            )
            await self._uow.commit()
            return "low_confidence"

        # Success path: commit the analyser verdict and generate the draft.
        review.assign_analysis(
            sentiment=analysis.sentiment,
            summary=analysis.summary,
            recurring_issues=analysis.recurring_issues,
            now=now,
        )
        review.mark_drafted(now=now)
        await self._reviews.save(tenant_id, review)

        if review.language is not None:
            draft_vo = await self._draft_generator.generate_draft(
                review=review, language=review.language
            )
            assert_in_catalogue(draft_vo.content)
            existing = await self._drafts.get_for_review(tenant_id, review.id)
            if existing is None:
                await self._drafts.add(
                    tenant_id,
                    ReviewResponseDraft(
                        id=uuid.uuid4(),
                        review_id=review.id,
                        draft_content=draft_vo.content,
                        language=draft_vo.language,
                        created_at=now,
                        updated_at=now,
                        ai_generated=True,
                        edits_count=0,
                    ),
                )
            else:
                existing.draft_content = draft_vo.content
                existing.language = draft_vo.language
                existing.edits_count = 0
                existing.updated_at = now
                await self._drafts.save(tenant_id, existing)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    review=review,
                    event_type=TimelineEventType.REVIEW_RESPONSE_DRAFTED,
                    actor_type=TimelineActorType.SCHEDULER,
                    actor_user_id=None,
                    metadata={
                        "review_id": str(review.id),
                        "property_id": str(review.property_id),
                        "sentiment": analysis.sentiment.value,
                        "template_version": REVIEW_DRAFT_TEMPLATES_VERSION,
                    },
                    now=now,
                )
            ),
        )
        await self._uow.commit()
        return "classified"
