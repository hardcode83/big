"""The ports `reviews` owns beyond persistence (R1.2, R2.1, R3.1; design D1, D10).

**Two ports for AI, two ports for persistence**, and the split between them is what the
proposal argues for. `AIReviewAnalyzer` and `AIReviewDraftGenerator` are their own
`Protocol`s rather than methods on `messaging.AIAdapter`: `messaging-ai` R2 forbids
`AIAdapter` from growing methods that do not belong to the conversation aggregate, and a
real provider implementing both modules' AI surface would otherwise inherit one
`Protocol` it can only partly satisfy (the Liskov violation `messaging-ai` D6 names for
`PMSMessagingPort`).

`ReviewRepository` and `ReviewResponseDraftRepository` are separate by aggregate root,
following `steering/backend-architecture.md` ("un repositorio por agregado raíz"). The
latter joins `reviews` explicitly to activate the tenant filter, because the global
loader criteria of `app/core/db.py` do not cover a table without its own `tenant_id`
(D10 — the same construction `messages` uses for `conversations`).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.reviews.domain.entities import Review, ReviewResponseDraft
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)
from app.reviews.domain.value_objects import GeneratedDraft, ReviewAnalysis


class AIReviewAnalyzer(Protocol):
    """What the AI says about one review's body (R2.1, design D1).

    The contract of `RuleBasedIncidentClassifier` written for `maintenance` (D4), adapted
    to two outputs the review flow needs: a sentiment and a list of recurring issues, in
    addition to the closed-vocabulary summary.

    **`confidence` is `0..1` and refused outside that range by `ReviewAnalysis.__post_init__`**:
    the same guarantee the incident classifier carries, so a percentage (`85`) cannot
    become "always low-confidence".

    **Raising is a supported outcome**: a malformed body raises, the use case logs the
    error and increments `classification_attempts`, and the row returns to the queue on
    the next tick. The mock does not raise today; the contract does, because a real
    provider will.
    """

    async def analyze_review(
        self, *, content: str, language: str | None
    ) -> ReviewAnalysis:
        """Read the body and decide sentiment, summary and recurring issues (R2.1)."""
        ...


class AIReviewDraftGenerator(Protocol):
    """What the AI drafts as the response to one review (R3.1, design D1).

    **The draft is drawn from the closed catalogue of `templates.py`** — never invented.
    The adapter must declare, in the value it returns, the vocabulary its `content` came
    from (`GeneratedDraft.vocabulary`), which `GeneratedDraft.__post_init__` enforces.
    That is the *admission condition* rule 11 of `steering/security.md` states for this
    class of column; what closes the remaining gap is the use case's runtime
    `assert_in_catalogue` call before persisting, against `templates.REVIEW_DRAFT_VOCABULARY`.

    **`language` is what the caller resolved** — the detector in `domain/language.py`
    or the explicit body field — so this port never has to know about the fallback.
    """

    async def generate_draft(
        self, *, review: Review, language: str
    ) -> GeneratedDraft:
        """The reply to the reviewer, drawn from `REVIEW_DRAFT_TEMPLATES` (R3.2, D6)."""
        ...


@dataclass(frozen=True)
class ReviewFilters:
    """The filters of `GET /reviews`, combined with AND (R5.3, design D11)."""

    property_id: uuid.UUID | None = None
    channel: ReviewChannel | None = None
    sentiment: ReviewSentiment | None = None
    status: ReviewStatus | None = None
    rating_min: Decimal | None = None
    rating_max: Decimal | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True)
class ReviewPage:
    """One page plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[Review, ...]
    total: int


class ReviewRepository(Protocol):
    """The persistence port for `Review` (R1.1, R1.2; design D3, D10).

    Every method takes `tenant_id` explicitly. The parameter is the mechanism; the global
    loader criteria of `app/core/db.py` are the net — `reviews` carries `tenant_id`
    directly (R1.1, an explicit divergence from `messages`/`review_response_drafts`),
    so the net covers this table.

    **`property_id` and `reservation_id` must already have been resolved *within*
    `tenant_id`** (the same precondition `ConversationRepository.add` documents): the
    foreign keys of `reviews` are global rather than composite with `tenant_id`, and the
    database would accept a review of tenant A anchored to a property of tenant B.
    """

    async def add(self, tenant_id: uuid.UUID, review: Review) -> None:
        """Append a review for the acting tenant. Never commits."""
        ...

    async def get(
        self, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> Review | None:
        """The review, or `None` when it does not exist *within this tenant*.

        Returning `None` keeps the 404 decision in the use case. R1.3 requires "does not
        exist" and "belongs to someone else" to be indistinguishable, and here that is
        not a discipline but a consequence of the query: both are the same
        `WHERE tenant_id = :tenant_id AND id = :id` returning zero rows.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, review: Review) -> None:
        """Persist the mutations the entity's own methods made. Never commits.

        Approving, ignoring, marking as posted manually and writing the analyser verdict
        all come through here, so this is the write path that has to stay atomic with
        the audit row, the timeline event and the notification of R6.
        """
        ...

    async def list_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        filters: ReviewFilters,
        *,
        page: int,
        per_page: int,
    ) -> ReviewPage:
        """The reviews of one property, newest `published_at` first with `NULLS LAST` (R5.3)."""
        ...

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        filters: ReviewFilters,
        *,
        page: int,
        per_page: int,
    ) -> ReviewPage:
        """The tenant's reviews, newest `published_at` first with `NULLS LAST` (R5.3).

        Used by the inbox listing `GET /reviews` when the caller does not pin a property.
        """
        ...

    async def count_by_sentiment_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, *, window_days: int
    ) -> dict[ReviewSentiment, int]:
        """The sentiment histogram for the summary endpoint (R5.5)."""
        ...

    async def aggregate_recurring_issues_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        window_days: int,
        top_n: int,
    ) -> dict[RecurringIssueTag, int]:
        """The top-N recurring-issue counts for the summary endpoint (R5.5).

        The tenant's `review_recurring_issues_top_n` bounds the result; the cap is a
        parameter here so the use case does not duplicate the column's bounds check.
        """
        ...

    async def list_pending_classification(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> list[Review]:
        """The candidates of the classification job (design D2, D16).

        `ai_summary IS NULL AND classification_attempts < 3` — the pair R2.4 needs at
        once: an unsuccessful classifier comes back on the next tick (nothing was
        written), while a low-confidence one does not (the row is `DRAFTED` but the
        three AI fields are cleared). Without the second half a deterministic adapter
        would be asked the same question for ever.

        Oldest first, `limit`ed: a tenant whose classifier was down all night must not
        turn one tick into an unbounded run.
        """
        ...


class ReviewResponseDraftRepository(Protocol):
    """The persistence port for `ReviewResponseDraft` (R1.1, R1.2; design D10).

    **`tenant_id` is taken for every read**, because `review_response_drafts` has no
    `tenant_id` column (PRD §7.21) and the global loader criteria of `app/core/db.py` do
    not cover it. The implementation joins `reviews` to filter; the signature hides the
    join so a future column-level tenant key (PRD §7.21 records the choice, not a
    rejection) is a single adapter change.

    `ReviewResponseDraft` already lives at `domain/entities.py` with the rationale, and
    `infrastructure/repositories.py` mirrors this port by joining.
    """

    async def add(
        self, tenant_id: uuid.UUID, draft: ReviewResponseDraft
    ) -> None:
        """Append a draft for a review of this tenant. Never commits.

        Raises `ReviewNotFoundError` when the parent does not resolve within the tenant
        — the one place a repository raises rather than returning `None`, because there
        is no half-written draft to hand back. Same construction `MessageRepository.add`
        uses.
        """
        ...

    async def get(
        self, tenant_id: uuid.UUID, draft_id: uuid.UUID
    ) -> ReviewResponseDraft | None:
        """The draft, or `None` outside this tenant (R1.5)."""
        ...

    async def save(
        self, tenant_id: uuid.UUID, draft: ReviewResponseDraft
    ) -> None:
        """Persist the edits and the approval. Never commits."""
        ...

    async def get_for_review(
        self, tenant_id: uuid.UUID, review_id: uuid.UUID
    ) -> ReviewResponseDraft | None:
        """The single draft of one review (`UNIQUE (review_id)`), or `None`.

        The unique constraint means a second call can only return the same draft or
        `None`; the use case does the `INSERT ... ON CONFLICT (review_id) DO UPDATE`
        on regenerate (R3.5, D5).
        """
        ...
