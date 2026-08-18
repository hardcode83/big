"""Domain errors of the pricing module (R1.3, R1.4, R1.7, R5.4; design D15).

Pure Python, like `app/maintenance/domain/exceptions.py`: no import of `app.core.errors`,
because that module imports FastAPI and pulling it in here would put the web framework
inside `domain/` transitively. The translation to a status code lives in
`app/pricing/api/errors.py`.

The hierarchy is **flat on purpose**. `api/errors.py` resolves its table by `isinstance`
with first-match-wins, so a subclass is only answered correctly while its row happens to
sit above its base's — a property of the literal's line order, not of the type. `cleaning`
and `maintenance` reached the same conclusion and say so in theirs.
"""


class PricingDomainError(Exception):
    """Base error for the pricing domain."""


class PricingValidationError(PricingDomainError):
    """An invariant of a `PricingRule` was violated — answered 422.

    Always raised **naming the field that failed** (R1.4: "rechazar con `422` nombrando el
    campo que falla"), which is why `field` is a required attribute and not an optional
    nicety: a 422 that says only "invalid rule" leaves the manager to guess which of the
    five JSONB columns she got wrong.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


class PricingRuleNotFoundError(PricingDomainError):
    """The rule does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown or belongs to another tenant
    (R1.7: "responder `404` y no `403`, sin revelar su existencia"). The message defaults
    to a constant and callers do not override it — two 404s with distinguishable bodies are
    a probe.
    """

    def __init__(self, message: str = "Pricing rule does not exist") -> None:
        super().__init__(message)


class PriceRecommendationNotFoundError(PricingDomainError):
    """The recommendation does not exist within the acting tenant — answered 404."""

    def __init__(self, message: str = "Price recommendation does not exist") -> None:
        super().__init__(message)


class InvalidRecommendationTransitionError(PricingDomainError):
    """The recommendation's status does not admit the requested move (R5.4) — 409.

    Raised by the entity against its own transition table, never by a use case: the legal
    moves of a `PriceRecommendation` are a business rule, and
    `steering/backend-architecture.md` puts those in `domain/`.
    """
