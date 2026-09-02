"""SQLAlchemy adapters for the two review ports (R1.1, R1.2; design D3, D10).

**`reviews` and `review_response_drafts` are not the same problem.** `reviews` carries
`TenantScopedMixin`, so `tenant_scoped_classes()` selects it and the global
`with_loader_criteria` of `app/core/db.py` covers its ORM reads — the explicit
`tenant_id` in every statement here is the mechanism and that listener is the net.

**`review_response_drafts` has no `tenant_id` column**, the same asymmetry `messages`
documents in `messaging` (PRD §7.21, the schema declares no own `tenant_id` and the
model docstring spells out why). The adapter joins `reviews` explicitly to activate the
tenant filter, and that `JOIN` is the **only** isolation mechanism the table has — not
defence in depth, the one thing between a wiring mistake and a draft of another tenant.

Neither adapter commits. The use case owns the transaction (R4.7, D11), which is what
keeps the review, its timeline event and its draft atomic.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401  (kept for future JSONB column ops)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.reviews.domain.entities import (
    Review,
    ReviewResponseDraft,
    _coerce_recurring_issues,
)
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewSentiment,
)
from app.reviews.domain.exceptions import ReviewNotFoundError, ReviewValidationError
from app.reviews.domain.ports import ReviewFilters, ReviewPage
from app.reviews.infrastructure.models import ReviewModel, ReviewResponseDraftModel

#: Columns `save()` is allowed to update on `Review`. Identity columns (`id`, `tenant_id`)
#: and the creation timestamp (`created_at`) are absent on purpose; everything else is
#: fair game for the entity's transition methods.
_MUTABLE_REVIEW_COLUMNS = (
    "reservation_id",
    "external_id",
    "channel",
    "reviewer_name",
    "rating",
    "content",
    "language",
    "sentiment",
    "ai_summary",
    "recurring_issues",
    "status",
    "published_at",
    "updated_at",
    "classification_attempts",
)

#: Columns `save()` is allowed to update on `ReviewResponseDraft`. Identity and creation
#: timestamp are absent, as are `review_id` (immutable — the unique constraint) and
#: `ai_generated` (provenance, not state — R3.5).
_MUTABLE_DRAFT_COLUMNS = (
    "draft_content",
    "language",
    "edits_count",
    "approved_by",
    "approved_at",
    "updated_at",
)


def _to_review(model: ReviewModel) -> Review:
    """Rebuild the entity from the ORM row, validating the invariants the schema does not.

    The schema accepts any `recurring_issues` JSONB value; the entity's `_coerce_...`
    is what gates the closed tag list. Re-running the coercer at the boundary is the
    read-side half of the rule-11 guarantee (D7): a row that landed before the entity
    guard existed, or one written by a writer that bypassed the type, would otherwise
    raise `ValueError` here and blow the whole read instead of degrading to `OTHER`
    with the warning D7 names. Reusing `_coerce_recurring_issues` keeps the read path
    and the write path on the same degradation rule (R2.2, D7).
    """
    return Review(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        reservation_id=model.reservation_id,
        external_id=model.external_id,
        channel=model.channel,
        reviewer_name=model.reviewer_name,
        rating=model.rating,
        content=model.content,
        language=model.language,
        sentiment=model.sentiment,
        ai_summary=model.ai_summary,
        # The entity accepts a tuple; the coercer handles any list value the schema
        # would have stored, degrading unknown tags to `OTHER` with a warning.
        recurring_issues=_coerce_recurring_issues(model.recurring_issues),
        status=model.status,
        published_at=model.published_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        classification_attempts=model.classification_attempts,
    )


def _to_draft(model: ReviewResponseDraftModel) -> ReviewResponseDraft:
    return ReviewResponseDraft(
        id=model.id,
        review_id=model.review_id,
        draft_content=model.draft_content,
        language=model.language,
        ai_generated=model.ai_generated,
        edits_count=model.edits_count,
        approved_by=model.approved_by,
        approved_at=model.approved_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _review_conditions(tenant_id: uuid.UUID, filters: ReviewFilters) -> list:
    """The `WHERE` for every read of `reviews`, so no method can be written without the
    tenant filter."""
    conditions: list = [ReviewModel.tenant_id == tenant_id]
    if filters.property_id is not None:
        conditions.append(ReviewModel.property_id == filters.property_id)
    if filters.channel is not None:
        conditions.append(ReviewModel.channel == filters.channel)
    if filters.sentiment is not None:
        conditions.append(ReviewModel.sentiment == filters.sentiment)
    if filters.status is not None:
        conditions.append(ReviewModel.status == filters.status)
    if filters.rating_min is not None:
        conditions.append(ReviewModel.rating >= filters.rating_min)
    if filters.rating_max is not None:
        conditions.append(ReviewModel.rating <= filters.rating_max)
    if filters.date_from is not None:
        conditions.append(ReviewModel.published_at >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(ReviewModel.published_at <= filters.date_to)
    return conditions


def _require_positive_page(page: int, per_page: int) -> None:
    """`offset((page - 1) * per_page)` is negative for `page = 0`; the routes declare
    `ge=1` on both, but a caller with no HTTP in front of it (a test, a CLI) gets a
    422 here rather than a Postgres `OFFSET must not be negative`."""
    if page < 1 or per_page < 1:
        raise ReviewValidationError(
            f"page and per_page must be positive, got page={page}, per_page={per_page}"
        )


class SqlAlchemyReviewRepository:
    """`ReviewRepository` — the first writer `reviews` has ever had."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, review: Review) -> None:
        if review.tenant_id != tenant_id:
            # The session's global filter does not cover INSERTs — see `app/core/db.py`'s
            # third limit — so this check is the only thing between a wiring mistake and a
            # row of another tenant. Same pattern `SqlAlchemyConversationRepository.add`
            # and `SqlAlchemyIncidentRepository.add` state.
            raise CrossTenantWriteError(
                entity="review",
                entity_tenant_id=review.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            ReviewModel(
                id=review.id,
                tenant_id=review.tenant_id,
                property_id=review.property_id,
                reservation_id=review.reservation_id,
                external_id=review.external_id,
                channel=review.channel,
                reviewer_name=review.reviewer_name,
                rating=review.rating,
                content=review.content,
                language=review.language,
                sentiment=review.sentiment,
                ai_summary=review.ai_summary,
                recurring_issues=list(review.recurring_issues)
                if review.recurring_issues
                else None,
                status=review.status,
                published_at=review.published_at,
                created_at=review.created_at,
                updated_at=review.updated_at,
                classification_attempts=review.classification_attempts,
            )
        )
        await self._session.flush()

    async def get(
        self, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> Review | None:
        """One query: both R1.3 outcomes (unknown id / another tenant) are the same zero
        rows, which is what makes the indistinguishability a property of the query."""
        result = await self._session.execute(
            select(ReviewModel).where(
                ReviewModel.tenant_id == tenant_id,
                ReviewModel.id == review_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_review(model) if model is not None else None

    async def save(self, tenant_id: uuid.UUID, review: Review) -> None:
        if review.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="review",
                entity_tenant_id=review.tenant_id,
                acting_tenant_id=tenant_id,
            )
        await self._session.execute(
            update(ReviewModel)
            .where(
                ReviewModel.tenant_id == review.tenant_id,
                ReviewModel.id == review.id,
            )
            .values(
                **{
                    column: getattr(review, column)
                    for column in _MUTABLE_REVIEW_COLUMNS
                }
            )
        )
        await self._session.flush()

    async def list_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        filters: ReviewFilters,
        *,
        page: int,
        per_page: int,
    ) -> ReviewPage:
        """The reviews of one property, ordered `published_at DESC NULLS LAST, id` (R5.3).

        `NULLS LAST` matters because Postgres puts nulls first under `DESC`: a brand-new
        review with no `published_at` would otherwise sit above what the manager is
        actually triaging. The tie-break on `id` is what makes the page boundaries stable.
        """
        _require_positive_page(page, per_page)

        conditions = _review_conditions(tenant_id, filters)
        conditions.append(ReviewModel.property_id == property_id)

        total = await self._session.scalar(
            select(func.count()).select_from(ReviewModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(ReviewModel)
            .where(*conditions)
            .order_by(
                ReviewModel.published_at.desc().nullslast(),
                ReviewModel.id,
            )
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return ReviewPage(
            items=tuple(_to_review(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        filters: ReviewFilters,
        *,
        page: int,
        per_page: int,
    ) -> ReviewPage:
        """The tenant's reviews, ordered `published_at DESC NULLS LAST, id` (R5.3).

        Used by `GET /reviews` when the caller does not pin a property. Same shape as
        `list_for_property` minus the property filter.
        """
        _require_positive_page(page, per_page)
        conditions = _review_conditions(tenant_id, filters)

        total = await self._session.scalar(
            select(func.count()).select_from(ReviewModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(ReviewModel)
            .where(*conditions)
            .order_by(
                ReviewModel.published_at.desc().nullslast(),
                ReviewModel.id,
            )
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return ReviewPage(
            items=tuple(_to_review(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def count_by_sentiment_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        window_days: int,
    ) -> dict[ReviewSentiment, int]:
        """The sentiment histogram for `GET /properties/{id}/reviews/summary` (R5.5).

        One query, one row per sentiment: a sparse mapping in which an absent sentiment
        is omitted, not mapped to `0`. The caller decides how to render that — a UI that
        wants all three bars always has the keys to default.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        rows = await self._session.execute(
            select(ReviewModel.sentiment, func.count())
            .where(
                ReviewModel.tenant_id == tenant_id,
                ReviewModel.property_id == property_id,
                ReviewModel.sentiment.is_not(None),
                ReviewModel.published_at >= cutoff,
            )
            .group_by(ReviewModel.sentiment)
        )
        return {sentiment: int(count) for sentiment, count in rows.all()}

    async def aggregate_recurring_issues_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        window_days: int,
        top_n: int,
    ) -> dict[RecurringIssueTag, int]:
        """The top-N recurring-issue counts for the summary endpoint (R5.5).

        `recurring_issues` is a JSONB array of tag strings; we unnest inside the query
        rather than in Python, so the count is computed where the data lives. The
        `top_n` ceiling is a parameter here so the use case does not duplicate the
        tenant config's bounds check.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        # `recurring_issues` is a JSONB array of tag strings; unnest with
        # `jsonb_array_elements_text` so the count is computed in SQL, where the data
        # lives, instead of fetching the whole table to Python. `.op("UNNEST")(JSONB)`
        # would emit `$1::JSONB AS anon_1` and bind the type object as a parameter,
        # which is the wrong shape — the function call has no bound arg.
        rows = await self._session.execute(
            select(
                func.jsonb_array_elements_text(ReviewModel.recurring_issues).label(
                    "tag"
                ),
                func.count(),
            )
            .where(
                ReviewModel.tenant_id == tenant_id,
                ReviewModel.property_id == property_id,
                ReviewModel.published_at >= cutoff,
                ReviewModel.recurring_issues.is_not(None),
            )
            .group_by("tag")
            .order_by(func.count().desc())
            .limit(top_n)
        )
        # The JSONB values are strings — coerce through the enum's `value` validator so
        # an unknown tag (an adapter that bypassed the entity) degrades to `OTHER`
        # rather than raising. The aggregate stays bounded by `top_n`, so the cost of
        # the exception path is the cost of one tuple.
        result: dict[RecurringIssueTag, int] = {}
        for raw_value, count in rows.all():
            try:
                tag = RecurringIssueTag(raw_value)
            except (ValueError, TypeError):
                tag = RecurringIssueTag.OTHER
            result[tag] = int(count)
        return result

    async def list_pending_classification(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> list[Review]:
        """The candidates of the classification job (D2, D16).

        `ai_summary IS NULL AND classification_attempts < 3` — the pair R2.4 needs at
        once: an unsuccessful classifier comes back on the next tick (nothing was
        written), while a low-confidence one does **not** (the three AI fields are
        cleared, but `status` is `DRAFTED`, so the row is `DRAFTED` AND `ai_summary IS NULL`).
        Without the second half a deterministic adapter would be asked the same question
        for ever.

        **`FOR UPDATE SKIP LOCKED`** — the read claims each row for the duration of the
        transaction, and a second tick on the same tenant (or a backfill admin tool that
        races the scheduler) sees those rows as locked and walks past them instead of
        double-classifying. The tenant-level lock `run_for_every_tenant` already holds is
        the outer fence; this is the inner one. Postgres 9.5+ supports the clause and the
        project ships on 16, so the call has been safe since the module existed.

        Oldest first, `limit`ed: a tenant whose classifier was down all night must not
        turn one tick into an unbounded run.
        """
        rows = await self._session.execute(
            select(ReviewModel)
            .where(
                ReviewModel.tenant_id == tenant_id,
                ReviewModel.ai_summary.is_(None),
                ReviewModel.classification_attempts < 3,
            )
            .order_by(ReviewModel.created_at, ReviewModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_to_review(model) for model in rows.scalars()]


class SqlAlchemyReviewResponseDraftRepository:
    """`ReviewResponseDraftRepository` — **no statement here touches
    `review_response_drafts` alone** (R1.1, D10).

    `review_response_drafts` has no `tenant_id`, so `tenant_scoped_classes()` does not
    select it and the global `with_loader_criteria` does not cover it. Every read
    starts from a `JOIN` with `reviews` filtered by `tenant_id`; the write resolves the
    parent within the tenant first and inserts against **the id that resolved**.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scoped(self, tenant_id: uuid.UUID, draft_id: uuid.UUID) -> list:
        """The `WHERE` every draft read shares, so no method can be written without it."""
        return [
            ReviewModel.tenant_id == tenant_id,
            ReviewResponseDraftModel.id == draft_id,
        ]

    @staticmethod
    def _joined(statement: Select) -> Select:
        return statement.join(
            ReviewModel, ReviewModel.id == ReviewResponseDraftModel.review_id
        )

    async def add(self, tenant_id: uuid.UUID, draft: ReviewResponseDraft) -> None:
        """Resolve the parent inside the tenant, then insert against the id that resolved.

        Raises `ReviewNotFoundError` — the same error, with the same constant message,
        that an unknown review raises. R1.3 requires the two to be indistinguishable,
        and here that is one query returning zero rows.
        """
        owner = await self._session.scalar(
            select(ReviewModel.id).where(
                ReviewModel.tenant_id == tenant_id,
                ReviewModel.id == draft.review_id,
            )
        )
        if owner is None:
            raise ReviewNotFoundError()

        self._session.add(
            ReviewResponseDraftModel(
                id=draft.id,
                review_id=owner,
                draft_content=draft.draft_content,
                language=draft.language,
                ai_generated=draft.ai_generated,
                edits_count=draft.edits_count,
                approved_by=draft.approved_by,
                approved_at=draft.approved_at,
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
        )
        await self._session.flush()

    async def get(
        self, tenant_id: uuid.UUID, draft_id: uuid.UUID
    ) -> ReviewResponseDraft:
        """The draft, joined to `reviews` for the tenant filter; raises on miss.

        `R1.3 / D10`: an unknown parent and a parent of another tenant are
        indistinguishable from the caller's seat — the same `ReviewNotFoundError`,
        never a `None` the use case would have to remember to translate.
        """
        rows = await self._session.execute(
            self._joined(select(ReviewResponseDraftModel)).where(
                *self._scoped(tenant_id, draft_id)
            )
        )
        model = rows.scalar_one_or_none()
        if model is None:
            # Same error, fixed message, for unknown id and another-tenant id (R1.3).
            raise ReviewNotFoundError()
        return _to_draft(model)

    async def save(self, tenant_id: uuid.UUID, draft: ReviewResponseDraft) -> None:
        """Persist the edits and the approval. The unique constraint on `review_id`
        makes the `UPDATE` itself a single-row statement."""
        # `ai_generated` is provenance, not state (R3.5, D5): never written here.
        await self._session.execute(
            update(ReviewResponseDraftModel)
            .where(
                ReviewResponseDraftModel.id == draft.id,
                # The same `JOIN` as the read, scoped to the tenant — defence against a
                # draft id that belongs to another tenant.
                ReviewModel.id == ReviewResponseDraftModel.review_id,
                ReviewModel.tenant_id == tenant_id,
            )
            .values(
                **{
                    column: getattr(draft, column)
                    for column in _MUTABLE_DRAFT_COLUMNS
                }
            )
        )
        await self._session.flush()

    async def get_for_review(
        self, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> ReviewResponseDraft | None:
        """The single draft of one review (`UNIQUE (review_id)`), or `None`.

        The unique constraint means a second call can only return the same draft or
        `None`; the use case does the `INSERT ... ON CONFLICT (review_id) DO UPDATE`
        on regenerate (R3.5, D5).
        """
        rows = await self._session.execute(
            self._joined(select(ReviewResponseDraftModel)).where(
                ReviewModel.tenant_id == tenant_id,
                ReviewResponseDraftModel.review_id == review_id,
            )
        )
        model = rows.scalar_one_or_none()
        return _to_draft(model) if model is not None else None
