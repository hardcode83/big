"""Exceptions for the statements domain.

Flat hierarchy by design (`pricing/domain/exceptions.py` is the precedent): every concrete
exception inherits from `StatementsDomainError`, and the API layer maps each subclass to its
HTTP status and `ErrorCode`. An unmapped subclass falls to a 500, which is the right shape
for a bug, not for a foreseen outcome — so adding an exception without mapping it is a defect
`tests/statements/test_errors.py` should catch.
"""


class StatementsDomainError(Exception):
    """Base for every domain error in `statements`."""


# Constant messages for the two 404 rows (R3.4, R5.5, D9): the body a 404 returns must
# be IDENTICAL whether the id is unknown or belongs to another tenant — a body that
# differed between the two would be a tenant-enumeration oracle. Both messages default
# to the same string so the mapper renders the same body for both cases.
_NOT_FOUND_MESSAGE = "Resource not found."


class OwnerStatementNotFoundError(StatementsDomainError):
    """The `OwnerStatement` does not exist or belongs to another tenant.

    The constant message is what the API renders — see `_NOT_FOUND_MESSAGE` above.
    """

    def __init__(self) -> None:
        super().__init__(_NOT_FOUND_MESSAGE)


class OwnerStatementInvalidTransitionError(StatementsDomainError):
    """An attempted state-machine move is illegal from the current status."""


class OwnerStatementValidationError(StatementsDomainError):
    """A field-level validation failed for an `OwnerStatement` (notes, period, etc.)."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ExpenseNotFoundError(StatementsDomainError):
    """The `Expense` does not exist or belongs to another tenant.

    The constant message is what the API renders — see `_NOT_FOUND_MESSAGE` above.
    Both 404 exceptions share the same string so a caller cannot enumerate.
    """

    def __init__(self) -> None:
        super().__init__(_NOT_FOUND_MESSAGE)


class ExpenseAlreadyConsolidatedError(StatementsDomainError):
    """The operation would mutate a field of an `Expense` whose `statement_id` is set.

    Raised by `SqlAlchemyExpenseRepository.update` for fields listed in D6.2
    (`amount`, `currency`, `category`, `date`, `property_id`, `statement_id`,
    `approved_by`). DELETE raises the same error when `statement_id IS NOT NULL`.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class NamedExpenseInClosedPeriodError(StatementsDomainError):
    """An `Expense` whose `date` falls inside a period that already has an `OwnerStatement`.

    Per design D6.3, V1 does not regenerate or retroactively associate, so a `date` inside a
    closed period cannot be created via API.
    """


class MixedCurrencyPeriodError(StatementsDomainError):
    """The period contains rows whose `currency` is not EUR (design D3).

    The generation aborts the entire `(tenant, property, period)` instead of producing a
    partial statement. Carries the list of offending rows so the caller can fix them.
    """

    def __init__(self, message: str, *, mismatches: list[tuple[str, str, str]]) -> None:
        super().__init__(message)
        self.mismatches = mismatches  # (row_id, currency, table)