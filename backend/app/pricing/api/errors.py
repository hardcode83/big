"""Maps pricing domain errors onto the PRD §23 envelope (design D15).

Same shape as `app/maintenance/api/errors.py`, and for the same reason: the domain stays
free of FastAPI and of `app.core.errors` (which imports it), so the translation happens in
exactly one declared place instead of being repeated — or forgotten — per router.

The table is exhaustive over `app/pricing/domain/exceptions.py`. An unmapped error falls to
500, which is right for a bug of ours and never for an outcome we foresaw, so adding an
exception without adding its row here is a defect `tests/pricing/test_errors.py` catches.

**No new `ErrorCode`.** The three this module needs are already in
`app/core/error_codes.py`, so the single registry and the published contract do not change
shape (D15).

Three rules about the response body, all three asked for by the section-2 security panel and
all three verifiable in `tests/pricing/test_errors.py`:

1. **The handler renders `str(exc)` and does not log it.** This is `maintenance`'s exact
   form, and the omission is deliberate: a copy in the log puts the manager's free text into
   the application log, which rules 3 and 4 of `steering/security.md` do govern. The 500
   branch is the one exception — there the message is a constant of ours, and the exception
   itself is a bug worth a traceback.
2. **No message echoes an unbounded value of the caller's.** The five JSONB columns are
   free-form interiors that no request schema constrains (D16 puts their schema in the
   domain), so an echoed value makes a 422 body as large as whatever was sent. The
   validators in `domain/entities.py` name the *supported set* instead of the offending
   value; this module adds no echoing of its own.
3. **The two 404s are indistinguishable.** `PricingRuleNotFoundError` and
   `PriceRecommendationNotFoundError` each default to a constant message and no caller
   passes a `message=` of its own — the parameter exists for nothing else. R1.7 needs
   "unknown" and "somebody else's" to answer identically, and a 404 whose body differed
   between the two would be a tenant-enumeration oracle.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.pricing.domain.exceptions import (
    InvalidRecommendationTransitionError,
    PriceRecommendationNotFoundError,
    PricingDomainError,
    PricingRuleNotFoundError,
    PricingValidationError,
)

# Order matters: the first matching entry wins. The hierarchy is flat by design (see the
# module docstring of `domain/exceptions.py`), so no row depends on sitting above another —
# which is exactly what that flatness buys. `PricingValidationError` is last anyway, because
# it is the one row D15 declares as covering subclasses.
_MAPPING: tuple[tuple[type[PricingDomainError], int, ErrorCode], ...] = (
    (PricingRuleNotFoundError, 404, ErrorCode.NOT_FOUND),
    (PriceRecommendationNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidRecommendationTransitionError, 409, ErrorCode.CONFLICT),
    (PricingValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: PricingDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A pricing error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_pricing_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PricingDomainError)
    async def _pricing_error(_: Request, exc: PricingDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected pricing error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
