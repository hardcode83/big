"""Domain errors of the reviews module (R1.4, R4.1, R5.1; design D4).

Flat on purpose, exactly like `app/messaging/domain/exceptions.py` and
`app/maintenance/domain/exceptions.py`: `api/errors.py` resolves its table by `isinstance`
with first-match-wins, so a subclass is only answered correctly while its row happens to sit
above its base's — a property of the literal's line order, not of the type. `messaging` and
`maintenance` both reached this conclusion before this module existed.

Pure Python, no import of `app.core.errors`: pulling FastAPI in here would put the web
framework inside `domain/` transitively.
"""


class ReviewsDomainError(Exception):
    """Base error for the reviews domain."""


#: The **one** message every review not-found path uses (R1.5). Two 404s with distinguishable
#: bodies are a probe: a body saying "belongs to another tenant" confirms the review exists,
#: which is exactly what R1.3 forbids being able to tell apart.
REVIEW_NOT_FOUND_MESSAGE = "Review does not exist"


class ReviewNotFoundError(ReviewsDomainError):
    """The review does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown or belongs to another tenant
    (R1.3). The message is fixed, the constructor takes none, and a caller that wanted to
    override it would have to write its own class — same trick `ConversationNotFoundError`
    in `messaging` records.
    """

    def __init__(self) -> None:
        super().__init__(REVIEW_NOT_FOUND_MESSAGE)


class InvalidReviewTransitionError(ReviewsDomainError):
    """The review's current status does not admit the requested move (R4.1) — answered 409.

    Raised by the entity against its own transition table, never by a use case: the legal
    moves of a `Review` are a business rule, and `steering/backend-architecture.md` puts
    those in `domain/`.
    """


class ReviewValidationError(ReviewsDomainError):
    """An invariant of an aggregate or value object was violated — answered 422."""


class DraftLanguageUnsupportedError(ReviewsDomainError):
    """The language of the requested draft is not in `SUPPORTED_LANGUAGES` (R3.3) — 422.

    A sibling of `ReviewValidationError` and not a subclass, although the outcome is the
    same 422: this module's flat hierarchy is what keeps `api/errors.py` independent of the
    order of its own table.
    """


class ReviewLanguageInferenceError(ReviewsDomainError):
    """The language detection could not decide ES/EN with enough evidence (R5.1) — 422.

    Caller chose to omit `language` in `POST /reviews` and the heuristic returned `None`;
    the request cannot proceed without a language and the manager must name one explicitly.
    """
