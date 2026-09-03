"""Maps statements domain errors onto the PRD §23 envelope (design D9, D13).

Same shape as `app/pricing/api/errors.py` and `app/maintenance/api/errors.py`. The domain
stays free of FastAPI and of `app.core.errors` (which imports them all); translation
happens in exactly one declared place instead of being repeated — or forgotten — per
router. The seven exceptions of `app/statements/domain/exceptions.py` are mapped here
exhaustively, so adding an exception without mapping it is a defect
`tests/statements/test_errors.py` should catch.

**No new `ErrorCode`.** The three this module needs are already in
`app/core/error_codes.py` (`NOT_FOUND`, `CONFLICT`, `VALIDATION_ERROR`), so the single
registry and the published OpenAPI contract (`sdd/specs/api-contract.md`) do not change
shape.

Three rules about the response body, the same three the pricing and maintenance mappers
enforce and the same three the section-2 security panel asked for:

1. **The handler renders `str(exc)` and does not log it.** The 500 branch is the
   exception — there the message is a constant of ours, and the exception itself is a bug
   worth a traceback.
2. **No message echoes an unbounded value of the caller's.** The exception messages name
   the *supported set* (the field, the cause) rather than the offending value, so a 422
   body stays bounded.
3. **The two 404s are indistinguishable.** `OwnerStatementNotFoundError` and
   `ExpenseNotFoundError` each default to a constant message; R3.4 and R5.5 require
   "unknown" and "another tenant's" to answer identically, and a 404 whose body differed
   between the two would be a tenant-enumeration oracle.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.statements.domain.exceptions import (
    ExpenseAlreadyConsolidatedError,
    ExpenseNotFoundError,
    MixedCurrencyPeriodError,
    NamedExpenseInClosedPeriodError,
    OwnerStatementInvalidTransitionError,
    OwnerStatementNotFoundError,
    OwnerStatementValidationError,
    StatementsDomainError,
)

# Order matters: the first matching entry wins. The hierarchy is flat by design (see the
# module docstring of `domain/exceptions.py`), so no row depends on sitting above another.
# `OwnerStatementValidationError` covers any field-level validation raised by either the
# entity or the use case; the more specific rows sit above it so a `MixedCurrencyPeriodError`
# — which subclasses nothing but the base — maps to its `409` row rather than being
# collapsed into the catch-all.
_MAPPING: tuple[tuple[type[StatementsDomainError], int, ErrorCode], ...] = (
    # Absence. The two 404 rows are the **only** difference between "unknown" and "wrong
    # tenant"; both routes render the same constant body so a caller cannot enumerate.
    (OwnerStatementNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ExpenseNotFoundError, 404, ErrorCode.NOT_FOUND),
    # State conflicts. Two flavours, both 409, both named by the offending field:
    # the D6.2 immutability of a consolidated expense (R5.4 / R5.3), and the D6.3 closed
    # period that D6.3 forbids creating an expense inside (R5.3).
    (ExpenseAlreadyConsolidatedError, 409, ErrorCode.CONFLICT),
    (NamedExpenseInClosedPeriodError, 409, ErrorCode.CONFLICT),
    (OwnerStatementInvalidTransitionError, 409, ErrorCode.CONFLICT),
    # The D3 mixed-currency abort. Same 409 status because the operation refuses on
    # data, not on input shape; a separate row so the error code stays `CONFLICT`
    # (it is the only catch-all that already exists in the registry).
    (MixedCurrencyPeriodError, 409, ErrorCode.CONFLICT),
    # Catch-all for any field-level validation raised by the entity or the use case
    # (`update_notes` rejection, threshold-bypass refusal, period cross-month shape, etc.).
    (OwnerStatementValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: StatementsDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # An unmapped statements error is a bug, not a client problem — falling through to
    # `INTERNAL_ERROR` keeps the contract honest about what the API foresaw.
    return 500, ErrorCode.INTERNAL_ERROR


def register_statements_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StatementsDomainError)
    async def _statements_error(_: Request, exc: StatementsDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected statements error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))