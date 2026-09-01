"""The values that cross the ports of `reviews` (R2.1, R3.3; design D1, D7).

Every one is frozen and every one checks its own contract in `__post_init__`, which is the
lesson `IncidentClassification` paid for in `maintenance`: an obligation written as prose on
a port is satisfied by accident of who wrote the only adapter so far, and a second
implementation inherits nothing. A check here reaches **every** adapter that returns the
declared type, wherever it lives — including `app/integrations/`, which is where a real
model provider would go.

**`SUPPORTED_LANGUAGES` comes from `app/tenants/domain/value_objects.py`** rather than being
restated: it is the list of locales that exist in `frontend/locales/`, and two copies of it
would let this module answer in a language the UI cannot render. Importing another domain's
`domain/` is the direction the dependency rule allows, and what `messaging` already does
for `TenantConfig`.

**No refusal message ever quotes the value it refused.** The values here come from an
adapter that tomorrow is an external model provider, so a rejected `language` or
`content` can be model output derived from the review body. `ReviewValidationError` is
answered 422 and `api/errors.py` renders `str(exc)` into the body, so echoing the bad value
would push into the response — and into every log line — precisely the text the rule-11
contract kept out of the column.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.reviews.domain.enums import RecurringIssueTag, ReviewSentiment
from app.reviews.domain.exceptions import DraftLanguageUnsupportedError, ReviewValidationError
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES


#: The shape a template catalogue version may take, e.g. `2026-09-01.1` — a date and a
#: revision. Checked for the same reason `templates.py` checks `template_version` for
#: messaging: it travels through logs and structured events, and "a version string" is not
#: a closed form until something says so.
_TEMPLATE_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


@dataclass(frozen=True)
class ReviewAnalysis:
    """What an `AIReviewAnalyzer` returns about one review (R2.1, R2.2; design D1, D7).

    **`vocabulary` is the admission condition of rule 11 for `reviews.ai_summary`, not the
    whole guarantee**, and the difference is the one `steering/security.md` records for the
    identical construction in `maintenance`: "un adaptador que construya su `vocabulary` a
    partir de su propia salida satisface la comprobación trivialmente… es segunda red y no
    la garantía." So what this class enforces is that an adapter *declares* the closed
    catalogue its `summary` came from and cannot then return something outside it — which
    reaches every adapter that returns the declared type, wherever it lives.

    What closes the remaining gap for `reviews.ai_summary` is a **runtime** check the
    pipeline owes: before persisting, the use case asserts `summary` is a member of
    `REVIEW_DRAFT_VOCABULARY` if the adapter also surfaced `summary_vocabulary` — the
    catalogue itself, not the set the adapter declared. The closed vocabulary of
    `summary` is `templates.REVIEW_DRAFT_VOCABULARY` (mirroring `RESPONSE_VOCABULARY` for
    messaging), so a paraphrase of the reviewer's body fails closed.

    **`recurring_issues` are a separate closed vocabulary**, the members of
    `RecurringIssueTag`. An unknown value the adapter invented degrades to
    `[RecurringIssueTag.OTHER]` (D7): the entity never persists what it does not recognise,
    and the test `test_recurring_issues_vocabulary.py` bars the door to a writer that
    forgets the rule.

    `confidence` is a `0..1` fraction compared against `TenantConfig.ai_confidence_threshold`
    (R2.3); a value outside that range is a broken adapter rather than a low score and is
    refused here instead of silently never classifying anything.
    """

    sentiment: ReviewSentiment
    summary: str | None
    recurring_issues: tuple[RecurringIssueTag, ...]
    confidence: Decimal
    summary_vocabulary: frozenset[str]
    issues_vocabulary: frozenset[RecurringIssueTag] = frozenset(RecurringIssueTag)

    def __post_init__(self) -> None:
        if not isinstance(self.sentiment, ReviewSentiment):
            raise ReviewValidationError(
                "sentiment must be a ReviewSentiment member, got "
                f"{type(self.sentiment).__name__}; reviews.sentiment is a closed form"
            )
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ReviewValidationError(
                "Analysis confidence must be a fraction within 0..1"
            )
        if not self.summary_vocabulary:
            raise ReviewValidationError(
                "An analysis adapter must declare the closed vocabulary its summary comes "
                "from (rule 11 of steering/security.md, design D7)"
            )
        if self.summary is not None and self.summary not in self.summary_vocabulary:
            raise ReviewValidationError(
                "Analysis summary is not in the adapter's declared vocabulary, so it may "
                "carry reviewer text into reviews.ai_summary, a rule-11 free-text sink"
            )
        if not self.issues_vocabulary:
            raise ReviewValidationError(
                "An analysis adapter must declare the closed tag vocabulary its "
                "recurring_issues come from"
            )
        unknown = [
            tag
            for tag in self.recurring_issues
            if tag not in self.issues_vocabulary
        ]
        if unknown:
            # `Degrade to OTHER with a warning` lives in the entity, not here, because the
            # entity is what owns the invariant of `recurring_issues`. The VO just refuses
            # what it cannot classify; the entity decides whether to drop to `OTHER`.
            raise ReviewValidationError(
                "recurring_issues carries tags outside the adapter's declared vocabulary; "
                "let the entity degrade to OTHER rather than passing unknown tags through"
            )


@dataclass(frozen=True)
class GeneratedDraft:
    """What an `AIReviewDraftGenerator` returns for one review (R3.1, R3.3; design D1, D6).

    **`vocabulary` is the admission condition of rule 11 for `review_response_drafts
    .draft_content`, not the whole guarantee** — same reasoning `ReviewAnalysis` records
    above, and the same closer: `templates.assert_in_catalogue(content)` is the second
    net the pipeline calls before persisting.

    `language` is checked against `SUPPORTED_LANGUAGES` (R3.3). The check is in the type
    rather than on the port, so a draft whose language the adapter invented never reaches
    the column.

    `template_version` carries the `templates.REVIEW_DRAFT_TEMPLATES_VERSION` constant
    shape (D13): it travels through structured logs, not the row, because
    `review_response_drafts.metadata` does not exist (PRD §7.21 — D13 records the
    deviation).
    """

    content: str
    language: str
    confidence: Decimal
    template_version: str
    vocabulary: frozenset[str]

    def __post_init__(self) -> None:
        if self.language not in SUPPORTED_LANGUAGES:
            raise DraftLanguageUnsupportedError(
                "Generated draft is not in a supported language; expected one of "
                f"{', '.join(SUPPORTED_LANGUAGES)}"
            )
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ReviewValidationError(
                "Draft confidence must be a fraction within 0..1"
            )
        if not self.vocabulary:
            raise ReviewValidationError(
                "A draft adapter must declare the closed vocabulary its content comes from "
                "(rule 11 of steering/security.md, design D7)"
            )
        if self.content not in self.vocabulary:
            raise ReviewValidationError(
                "Generated content is not in the adapter's declared vocabulary, so it may "
                "carry reviewer text into review_response_drafts.draft_content, a "
                "rule-11 free-text sink"
            )
        if not (
            isinstance(self.template_version, str)
            and _TEMPLATE_VERSION.fullmatch(self.template_version)
        ):
            raise ReviewValidationError(
                "template_version must look like '2026-09-01.1' — a date and a revision"
            )
