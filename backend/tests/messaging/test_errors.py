"""The error table is exhaustive over the domain's exceptions (design D17).

An exception added to `app/messaging/domain/exceptions.py` without a row in
`app/messaging/api/errors.py` falls to 500 — right for a bug of ours, never for an outcome we
foresaw. This walks the module so the omission is caught here rather than by whoever hits it.
Precedent: `tests/maintenance/test_errors.py`.
"""

import inspect

import pytest

from app.core.error_codes import ErrorCode
from app.messaging.api.errors import _MAPPING, http_error_for
from app.messaging.domain import exceptions as domain_exceptions
from app.messaging.domain.exceptions import (
    ConversationClosedError,
    ConversationNotFoundError,
    InvalidConversationTransitionError,
    MessagingDomainError,
    MessagingValidationError,
    PMSChannelUnavailableError,
)


def domain_errors() -> list[type[MessagingDomainError]]:
    """Every concrete error the module declares, base excluded — sorted for stable ids."""
    found = [
        obj
        for _, obj in inspect.getmembers(domain_exceptions, inspect.isclass)
        if issubclass(obj, MessagingDomainError)
        and obj is not MessagingDomainError
        and obj.__module__ == domain_exceptions.__name__
    ]
    return sorted(found, key=lambda cls: cls.__name__)


def test_the_walk_finds_the_errors_that_exist() -> None:
    """Without this, deleting the hierarchy would turn every parametrised case below into a
    vacuous pass and the exhaustiveness check would go unenforced."""
    assert {cls.__name__ for cls in domain_errors()} == {
        "ConversationNotFoundError",
        "InvalidConversationTransitionError",
        "ConversationClosedError",
        "PMSChannelUnavailableError",
        "MessagingValidationError",
    }


@pytest.mark.parametrize(
    "error_class", domain_errors(), ids=lambda cls: cls.__name__
)
def test_every_domain_error_has_a_row(error_class: type[MessagingDomainError]) -> None:
    assert any(row[0] is error_class for row in _MAPPING), (
        f"{error_class.__name__} has no row in app/messaging/api/errors.py, so it would "
        "reach a client as a 500"
    )


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ConversationNotFoundError(), 404, ErrorCode.NOT_FOUND),
        (InvalidConversationTransitionError("nope"), 409, ErrorCode.CONFLICT),
        (ConversationClosedError("nope"), 409, ErrorCode.CONFLICT),
        (PMSChannelUnavailableError("nope"), 422, ErrorCode.VALIDATION_ERROR),
        (MessagingValidationError("nope"), 422, ErrorCode.VALIDATION_ERROR),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, Exception) else str(value),
)
def test_the_status_of_each_error_is_the_one_the_design_declares(
    error: MessagingDomainError, status: int, code: ErrorCode
) -> None:
    assert http_error_for(error) == (status, code)


def test_an_unmapped_messaging_error_is_a_500() -> None:
    """A messaging error nobody mapped is a bug of ours, and it must not be dressed up as a
    client problem — nor must its message reach the client, which `register_messaging_error_
    handlers` replaces with a constant for exactly this branch."""

    class Unmapped(MessagingDomainError):
        pass

    assert http_error_for(Unmapped("internals")) == (500, ErrorCode.INTERNAL_ERROR)


def test_the_hierarchy_is_flat_so_the_table_order_cannot_matter() -> None:
    """The property the module docstring of `domain/exceptions.py` claims, checked rather than
    asserted: `api/errors.py` resolves by `isinstance` with first-match-wins, so a subclass
    would only be answered correctly while its row happened to sit above its base's."""
    for error_class in domain_errors():
        assert error_class.__bases__ == (MessagingDomainError,)
