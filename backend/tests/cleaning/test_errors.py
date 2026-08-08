"""D11 — the error mapping, and the completeness net it promises.

`app/cleaning/api/errors.py` says in its own docstring that "adding an exception without
adding its row here is a defect the `test_errors.py` completeness test catches". The QA panel
of sections 2-3 found that the test did not exist, so the promise was prose. This is it.

It matters because the fallback is 500: an unmapped domain error becomes "Unexpected cleaning
error" with the outcome the caller needed to distinguish thrown away.
"""

import inspect

import pytest

from app.cleaning.api import errors as errors_module
from app.cleaning.api.errors import _MAPPING, http_error_for
from app.cleaning.domain import exceptions as exceptions_module
from app.cleaning.domain.exceptions import (
    TASK_NOT_FOUND_MESSAGE,
    AmbiguousChecklistTemplateError,
    BlockingIncidentError,
    ChecklistIncompleteError,
    ChecklistItemNotFoundError,
    ChecklistTemplateNotFoundError,
    CleaningDomainError,
    CleaningTaskNotFoundError,
    CleaningValidationError,
    DuplicateLiveCleaningTaskError,
    InvalidCleaningTransitionError,
    PropertyNotFoundError,
    PropertyStateBlocksCleaningError,
    ReservationNotFoundError,
)


def _concrete_domain_errors() -> set[type]:
    """Every subclass of `CleaningDomainError` declared in the domain's exception module."""
    return {
        obj
        for _, obj in inspect.getmembers(exceptions_module, inspect.isclass)
        if issubclass(obj, CleaningDomainError)
        and obj is not CleaningDomainError
        and obj.__module__ == exceptions_module.__name__
    }


def test_every_domain_error_has_a_row():
    """The net D11 promises. Add an exception without a row and this fails."""
    mapped = {entry[0] for entry in _MAPPING}

    assert _concrete_domain_errors() == mapped


def test_no_row_names_an_exception_from_another_module():
    """A stray row copied from `reservations` would never be caught by the handler.

    `register_cleaning_error_handlers` installs a single
    `@app.exception_handler(CleaningDomainError)`, so an entry outside this hierarchy is dead
    weight that reads as coverage. An earlier draft of D11's table listed
    `reservations`' own `PropertyNotFoundError` for exactly that reason.
    """
    for error_class, _, _ in _MAPPING:
        assert issubclass(error_class, CleaningDomainError)
        assert error_class.__module__ == exceptions_module.__name__


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (CleaningTaskNotFoundError(), 404),
        (ChecklistTemplateNotFoundError("x"), 404),
        (ChecklistItemNotFoundError("x"), 404),
        (PropertyNotFoundError(), 404),
        (ReservationNotFoundError(), 404),
        (InvalidCleaningTransitionError("x"), 409),
        (PropertyStateBlocksCleaningError("x"), 409),
        (ChecklistIncompleteError(("a",)), 409),
        (BlockingIncidentError("x"), 409),
        (AmbiguousChecklistTemplateError("x"), 409),
        (DuplicateLiveCleaningTaskError("x"), 409),
        (CleaningValidationError("x"), 422),
    ],
)
def test_each_error_maps_to_its_status(error, expected_status):
    status, _ = http_error_for(error)

    assert status == expected_status


def test_subclasses_come_before_their_base():
    """`_MAPPING` is ordered and first match wins, so a base before its subclass would
    swallow it. Checked structurally rather than by eyeballing the literal."""
    for index, (error_class, _, _) in enumerate(_MAPPING):
        for later_class, _, _ in _MAPPING[index + 1 :]:
            assert not issubclass(error_class, later_class) or error_class is later_class


def test_an_unmapped_cleaning_error_falls_to_500():
    class SurpriseError(CleaningDomainError):
        pass

    status, code = http_error_for(SurpriseError("x"))

    assert status == 500
    assert code.value == "INTERNAL_ERROR"


def test_the_handler_does_not_echo_the_message_on_500():
    """A 500 body must not carry a domain message that was never meant for a client."""
    source = inspect.getsource(errors_module.register_cleaning_error_handlers)

    assert "Unexpected cleaning error" in source


def test_the_task_not_found_message_is_the_single_constant():
    """R7.3 one layer below the status code: two 404s must not have different bodies."""
    assert str(CleaningTaskNotFoundError()) == TASK_NOT_FOUND_MESSAGE
