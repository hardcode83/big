import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Mapping

from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)
from app.reviews.domain.exceptions import (
    InvalidReviewTransitionError,
    ReviewValidationError,
)
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

#: The widest body a reviewer can type (R5.1, design D21). 4000 mirrors
#: `messaging.MAX_MESSAGE_CONTENT_LENGTH`: a single guest writes one or the other in a
#: short reply, and the product ceiling is the same number. The column is `Text` with no
#: database limit, so the constant is the whole bound.
MAX_REVIEW_CONTENT_LENGTH = 4000

#: The widest reviewer display name we accept (R5.1).
MAX_REVIEWER_NAME_LENGTH = 200

#: How many classification attempts before the row is parked for manual triage (R2.4).
#: Kept beside the entity because the schema's default is the same number, and a future
#: widening is a single edit.
MAX_CLASSIFICATION_ATTEMPTS = 3


def _assert_rating(rating: Decimal | None) -> None:
    """`rating` is one decimal in `[1.0, 5.0]`, or `None` (R1.4).

    The range lives in the type and **not** as a CHECK on the schema (D15: the comment in
    `infrastructure/models.py` already names this; `revenue-reviews` does not add it). The
    domain guard catches a value the schema would silently store.

    `Decimal("0.05")` is rejected: the column is `Numeric(3, 1)`, so anything below one
    decimal would round on persistence and the reviewer would see `4` or `5` for a `4.05`.
    `Decimal("5.5")` is rejected: outside the range.
    """
    if rating is None:
        return
    if rating.as_tuple().exponent < -1:  # type: ignore[operator]
        raise ReviewValidationError(
            "rating must have at most one decimal; Numeric(3, 1) rounds finer values"
        )
    if not (Decimal("1.0") <= rating <= Decimal("5.0")):
        raise ReviewValidationError(
            "rating must be in 1.0..5.0 with one decimal"
        )


def _coerce_recurring_issues(
    raw: list[Any] | None,
) -> tuple[RecurringIssueTag, ...]:
    """The closed tag list that may reach `reviews.recurring_issues` (R2.2, design D7).

    Every value is checked against `RecurringIssueTag`; an unknown value degrades to
    `OTHER` with a `logger.warning` (D7's "red de degradación", not the guarantee). The
    column is JSONB and could carry anything; the entity is what refuses to persist it.

    `None` is a real value: the row was created and the classification has not run yet
    (R2.1). It returns `()` rather than `None` so the field has one shape downstream.
    """
    if raw is None:
        return ()
    cleaned: list[RecurringIssueTag] = []
    for value in raw:
        if isinstance(value, RecurringIssueTag):
            cleaned.append(value)
            continue
        # Strings arrive from the AI adapter; enum members arrive from code. Anything
        # else is a writer that bypassed the type — refuse it.
        try:
            cleaned.append(RecurringIssueTag(value))
        except (ValueError, TypeError):
            logger.warning(
                "reviews.recurring_issues.dropped_unknown_tag",
                extra={"unknown_value": repr(value)},
            )
            cleaned.append(RecurringIssueTag.OTHER)
    return tuple(cleaned)


@dataclass
class Review:
    """One row of `reviews`, with its state machine (R1.4, R4.1; design D4).

    The legal moves live on the entity — `_STATUS_TRANSITIONS` below names the five
    operations and their origin sets — and **every** status change goes through one of the
    methods. A `setattr(self, "status", APPROVED)` from a use case would write the column
    without the table's check, which is exactly what the architecture panel of
    `messaging`'s section 5-6 warned against in the conversation aggregate.

    `recurring_issues` is rebuilt through `_coerce_recurring_issues` in `__post_init__`,
    so an unknown tag the adapter invented never persists: it degrades to `OTHER` and
    leaves a `logger.warning` for the operator to widen the catalogue deliberately.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    channel: ReviewChannel
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    external_id: str | None = None
    reviewer_name: str | None = None
    rating: Decimal | None = None
    content: str | None = None
    language: str | None = None
    sentiment: ReviewSentiment | None = None
    ai_summary: str | None = None
    recurring_issues: tuple[RecurringIssueTag, ...] = field(default_factory=tuple)
    status: ReviewStatus = ReviewStatus.NEW
    published_at: datetime | None = None
    classification_attempts: int = 0

    #: The legal moves of the **status** axis (R4.1, design D4).
    #:
    #: Five operations and not four, because the pipeline can take a review straight from
    #: `NEW` to `IGNORED` (no draft generated — a review the manager decided was not worth
    #: answering) without ever crossing `DRAFTED`. A combined table would have to enumerate
    #: the cartesian product and would hide *which* operation refused a move.
    #:
    #: `POSTED_MANUALLY` and `IGNORED` appear as origins and never as destinations beyond
    #: `APPROVED → POSTED_MANUALLY`: D12 records that `IGNORED` and `POSTED_MANUALLY` are
    #: terminal — a review in either state admits no further transition. The methods below
    #: refuse the second move by construction.
    _STATUS_TRANSITIONS: ClassVar[
        Mapping[str, tuple[frozenset[ReviewStatus], ReviewStatus]]
    ] = {
        "mark_drafted": (
            frozenset({ReviewStatus.NEW}),
            ReviewStatus.DRAFTED,
        ),
        "approve": (
            frozenset({ReviewStatus.DRAFTED}),
            ReviewStatus.APPROVED,
        ),
        "ignore": (
            frozenset({ReviewStatus.NEW, ReviewStatus.DRAFTED}),
            ReviewStatus.IGNORED,
        ),
        "mark_posted_manually": (
            frozenset({ReviewStatus.APPROVED}),
            ReviewStatus.POSTED_MANUALLY,
        ),
        "mark_classified_low_confidence": (
            frozenset({ReviewStatus.NEW}),
            ReviewStatus.DRAFTED,
        ),
    }

    def __post_init__(self) -> None:
        """The invariants of `reviews` that are the entity's to keep (R1.4, R1.5).

        **`property_id` is non-null and is refused here**, the same way `Conversation`
        refuses it (R1.5, `messaging` D19): a review without a property cannot produce any
        timeline event R6.1 declares mandatory, and the column stays non-nullable so a
        future PMS adapter never has a reason to invent a `NULL` row.

        **`language` is one of `SUPPORTED_LANGUAGES` or `None`** — `None` is a real value
        (R5.1, A2): the body did not say, and the manager triages it. The check is closed
        here rather than on the schema because we *write* this column and the schema is a
        `String(5)` whose name promises a code (the `webhook_events.event_type` shape the
        census preamble of rule 11 exists for).

        **`recurring_issues` is rebuilt through the closed tag list** (R2.2): unknown
        values degrade to `OTHER` with a warning, the catalogue is the entity's to keep.

        **`ai_summary` is the closed-vocabulary sink of rule 11** (R2.1, D7): when the
        pipeline wrote it, it went through `templates.assert_in_catalogue` first. The
        entity refuses a non-`None` value that does not fit `REVIEW_DRAFT_VOCABULARY` (the
        set the *module* declares), so the entity guards the column too — same belt and
        braces the conversation's `Message.intent` carries.
        """
        if self.property_id is None:
            raise ReviewValidationError(
                "A review must belong to a property: without one it can produce none of "
                "the timeline events R6.1 requires (design D4, R1.5)"
            )
        if self.language is not None and self.language not in SUPPORTED_LANGUAGES:
            raise ReviewValidationError(
                f"Review language must be one of {', '.join(SUPPORTED_LANGUAGES)}, or unset"
            )
        # Re-run the coercer in case the constructor was called with raw values (an
        # adapter that forgot to type-narrow). Idempotent for already-coerced tuples.
        object.__setattr__(
            self, "recurring_issues", _coerce_recurring_issues(list(self.recurring_issues))
        )
        # The catalogue check on `ai_summary` is enforced in the use case against the
        # analyser's declared vocabulary, not here. The entity keeps the *type* check
        # (string-or-None) but does not pretend to know which closed vocabulary the
        # analyser chose — that contract lives on `ReviewAnalysis.recurring_issues_vocabulary`
        # and is the admission condition of rule 11 for the column. R2.1 records the split.
        _assert_rating(self.rating)
        if self.content is not None and len(self.content) > MAX_REVIEW_CONTENT_LENGTH:
            raise ReviewValidationError(
                f"Review content exceeds {MAX_REVIEW_CONTENT_LENGTH} characters"
            )
        if self.reviewer_name is not None and len(self.reviewer_name) > MAX_REVIEWER_NAME_LENGTH:
            raise ReviewValidationError(
                f"Reviewer name exceeds {MAX_REVIEWER_NAME_LENGTH} characters"
            )

    def _check_transition(self, operation: str) -> ReviewStatus:
        origins, target = self._STATUS_TRANSITIONS[operation]
        if self.status not in origins:
            raise InvalidReviewTransitionError(
                f"Review cannot move from {self.status.value} to {target.value}"
            )
        return target

    def mark_drafted(self, *, now: datetime) -> None:
        """The pipeline generated a draft (R4.1).

        `NEW → DRAFTED` is the only move that fires this method. A re-classification that
        updates `ai_summary` on a review already in `DRAFTED` goes through
        `assign_analysis` instead, which preserves `status`.
        """
        self.status = self._check_transition("mark_drafted")
        self.updated_at = now

    def approve(self, *, now: datetime) -> None:
        """A manager or owner approved the draft (R3.6, R4.1).

        The actor is recorded on `audit_logs` (R1.7, R6.1) and on the draft row's
        `approved_by` — the review's status is the answer to "what happened to this
        review", not "who approved it".
        """
        self.status = self._check_transition("approve")
        self.updated_at = now

    def ignore(self, *, now: datetime) -> None:
        """The manager chose not to respond (R4.1).

        `NEW → IGNORED` and `DRAFTED → IGNORED` are both legal — a review can be ignored
        before the pipeline ever runs, and a draft can be shelved without being posted.
        `POSTED_MANUALLY` and `IGNORED` are terminal: a second `ignore()` call raises
        `InvalidReviewTransitionError`, which is what R4.1 asks for.
        """
        self.status = self._check_transition("ignore")
        self.updated_at = now

    def mark_posted_manually(self, *, now: datetime) -> None:
        """The review was answered outside the system (R4.4, D12).

        The adapter of PMS does not enter this module: the change of status is a record of
        something a person did, not a call the system made (R4.4). A `POSTED_MANUALLY`
        review is terminal.
        """
        self.status = self._check_transition("mark_posted_manually")
        self.updated_at = now

    def mark_classified_low_confidence(
        self,
        *,
        sentiment: ReviewSentiment,
        now: datetime,
    ) -> None:
        """The adapter returned a verdict below the tenant's threshold (R2.3, design D2).

        `NEW → DRAFTED` is the same destination as `mark_drafted`, but the method is its
        own so the use case can record the low-confidence outcome as its own
        `REVIEW_CLASSIFIED_LOW_CONFIDENCE` timeline event (D8) — the operator sees the
        difference between "the pipeline answered confidently" and "the pipeline answered
        hesitantly".
        """
        self.status = self._check_transition("mark_classified_low_confidence")
        self.sentiment = sentiment
        # Per R2.3 the three AI fields are cleared: confidence was below threshold, the
        # summary is not trustworthy, and `recurring_issues` is reset.
        self.ai_summary = None
        self.recurring_issues = ()
        self.updated_at = now

    def increment_attempts(self, *, now: datetime) -> None:
        """One more failure (R2.4). The pipeline stops at `MAX_CLASSIFICATION_ATTEMPTS`.

        The check is the use case's, not the entity's — the entity does not know the
        constant on purpose, because the job that calls `increment_attempts` is the only
        thing that needs to enforce the cap.
        """
        self.classification_attempts += 1
        self.updated_at = now

    def assign_analysis(
        self,
        *,
        sentiment: ReviewSentiment,
        summary: str | None,
        recurring_issues: tuple[RecurringIssueTag, ...],
        now: datetime,
    ) -> None:
        """The adapter's verdict is committed to the row (R2.1, D7).

        **`status` is left alone**: a re-classification of a `DRAFTED` review that the
        pipeline re-ran updates the three AI fields without moving the axis, and a fresh
        `NEW` review the pipeline just answered uses `mark_drafted` to move the axis in a
        second step. The split is what keeps "classified" and "drafted" as two facts the
        timeline can name separately (D8's `REVIEW_RESPONSE_DRAFTED` vs the implicit
        "classified" the existing timeline already records).
        """
        self.sentiment = sentiment
        self.ai_summary = summary
        self.recurring_issues = recurring_issues
        self.updated_at = now


@dataclass
class ReviewResponseDraft:
    """One row of `review_response_drafts`, no `tenant_id` of its own (§7.21).

    Scoped transitively through the mandatory, unique `review_id`. The global tenant
    filter matches on column presence, so it does NOT cover this table — any repository
    touching it must JOIN `reviews` explicitly (see D10 and the docstring in
    `infrastructure/models.py`).

    **`ai_generated` is the provenance of the original content, not the current state.**
    A manager editing the draft does not flip it to `FALSE`: the column is bitácora de
    origen, not state (R3.5). `edits_count` is what records the iterations; without it the
    audit cannot tell a pristine draft from an iterated one (D5 / OQ4).
    """

    id: uuid.UUID
    review_id: uuid.UUID
    draft_content: str
    language: str
    created_at: datetime
    updated_at: datetime
    ai_generated: bool = True
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    edits_count: int = 0

    def __post_init__(self) -> None:
        if self.language not in SUPPORTED_LANGUAGES:
            raise ReviewValidationError(
                f"Draft language must be one of {', '.join(SUPPORTED_LANGUAGES)}"
            )
        # `ai_generated` is provenance, not state (R3.5, D5): when True, the catalogue of
        # `templates.REVIEW_DRAFT_VOCABULARY` applies; when False, the draft is human prose
        # (excepción 3 in the rule-11 census). The use case calls `assert_in_catalogue`
        # before persisting an AI draft; this entity guard is the second net that catches
        # a writer bypassing the use case (a test, a CLI).
        if self.ai_generated and len(self.draft_content) > MAX_REVIEW_CONTENT_LENGTH:
            raise ReviewValidationError(
                f"Draft content exceeds {MAX_REVIEW_CONTENT_LENGTH} characters"
            )

    def edit(self, *, new_content: str, now: datetime) -> None:
        """A manager rewrote the draft (R3.5).

        `edits_count` is incremented in the entity, the audit row is the use case's job
        (REVIEW_DRAFT_EDITED, R1.7). Splitting the two keeps the entity free of the audit
        repository and matches what `Conversation.take_over` and the rest of the project's
        state-machine methods do: mutate the state, leave the audit to the use case.

        `ai_generated` is left `True`: it is provenance, not state.
        """
        if self.approved_at is not None:
            raise ReviewValidationError(
                "An approved draft cannot be edited: approval locks the content (R3.6)"
            )
        if not new_content.strip():
            raise ReviewValidationError("Draft content cannot be empty")
        if len(new_content) > MAX_REVIEW_CONTENT_LENGTH:
            raise ReviewValidationError(
                f"Draft content exceeds {MAX_REVIEW_CONTENT_LENGTH} characters"
            )
        self.draft_content = new_content
        self.edits_count += 1
        self.updated_at = now

    def approve(self, *, actor_id: uuid.UUID, now: datetime) -> None:
        """A manager or owner signed off on the draft (R3.6).

        Once approved, `edit()` refuses further changes — the `approved_at` lock is what
        R3.6 promises, and `edit()` is the one that enforces it.
        """
        self.approved_by = actor_id
        self.approved_at = now
        self.updated_at = now
