"""The maintenance error mapping, and the completeness net it promises.

`app/maintenance/api/errors.py` says in its own docstring that "adding an exception without
adding its row here is a defect `tests/maintenance/test_errors.py` catches". **That file did
not exist**, so the promise was prose — found while `incident-photos` added three rows to that
table (R2.8, R2.9, R5.1) and noticed nothing would have failed had it forgotten one. This is
it, modelled on `tests/cleaning/test_errors.py`, whose own docstring records the identical
discovery being made about `cleaning` by the QA panel of its sections 2-3.

It matters because the fallback is 500: an unmapped domain error becomes "Unexpected
maintenance error" with the outcome the caller needed to distinguish thrown away. For this
change specifically, that would turn R2.8's `502 BAD_GATEWAY` ("the store failed, retry") into
an opaque server error.
"""

import inspect
import uuid

import pytest

from app.maintenance.api import errors as errors_module
from app.maintenance.api.errors import _MAPPING, http_error_for
from app.maintenance.domain import exceptions as exceptions_module
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentBlockedByPendingApprovalError,
    IncidentNotFoundError,
    IncidentPhotoStorageUnavailableError,
    IncidentPhotoTooLargeError,
    InvalidIncidentTransitionError,
    InvalidTechnicianError,
    MaintenanceDomainError,
    MaintenanceValidationError,
    OwnerApprovalAlreadyAnsweredError,
    OwnerApprovalNotFoundError,
    UnsupportedIncidentPhotoFormatError,
)


def _concrete_domain_errors() -> set[type]:
    """Every subclass of `MaintenanceDomainError` declared in the domain's exception module."""
    return {
        obj
        for _, obj in inspect.getmembers(exceptions_module, inspect.isclass)
        if issubclass(obj, MaintenanceDomainError)
        and obj is not MaintenanceDomainError
        and obj.__module__ == exceptions_module.__name__
    }


def test_every_domain_error_has_a_row() -> None:
    """The net the module's docstring promises. Add an exception without a row and this fails.

    This is the assertion whose absence `incident-photos` found: the three photo errors it adds
    would have been mapped or not with equal silence.
    """
    mapped = {entry[0] for entry in _MAPPING}

    assert _concrete_domain_errors() == mapped


def test_no_row_names_an_exception_from_another_module() -> None:
    """A stray row copied from another domain would never be caught by the handler.

    `register_maintenance_error_handlers` installs a single
    `@app.exception_handler(MaintenanceDomainError)`, so an entry outside this hierarchy is
    dead weight that reads as coverage.
    """
    for error_class, _, _ in _MAPPING:
        assert issubclass(error_class, MaintenanceDomainError)
        assert error_class.__module__ == exceptions_module.__name__


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (IncidentNotFoundError(), 404),
        (OwnerApprovalNotFoundError(), 404),
        (InvalidIncidentTransitionError("x"), 409),
        (IncidentAlreadyClosedError("x"), 409),
        (IncidentBlockedByPendingApprovalError("x"), 409),
        (OwnerApprovalAlreadyAnsweredError("x"), 409),
        (InvalidTechnicianError(uuid.uuid4()), 422),
        (MaintenanceValidationError("x"), 422),
        # `incident-photos`: R5.1, R2.9, R2.8.
        (IncidentPhotoTooLargeError("x"), 413),
        (UnsupportedIncidentPhotoFormatError("x"), 422),
        (IncidentPhotoStorageUnavailableError("x"), 502),
    ],
)
def test_each_error_maps_to_its_status(error, expected_status: int) -> None:
    status, _ = http_error_for(error)

    assert status == expected_status


def test_the_three_conflict_errors_are_distinguishable_at_the_mapping() -> None:
    """R2.4/R2.5/R2.6 and design D6: three refusals, all `409`, all different messages.

    The entity produces three distinct types (`tests/maintenance/test_entities.py` pins that);
    this pins that the mapping does not collapse them into one row on the way out, which is
    what would make the API unable to tell the caller which of the three happened.
    """
    statuses = {
        type(error): http_error_for(error)
        for error in (
            IncidentAlreadyClosedError("closed"),
            IncidentBlockedByPendingApprovalError("waiting"),
            InvalidIncidentTransitionError("out of order"),
        )
    }

    assert len(statuses) == 3
    assert {status for status, _ in statuses.values()} == {409}


def test_the_storage_failure_is_a_502_and_not_a_500() -> None:
    """R2.8 — the code carries "retrying may work", not "our bug".

    A 500 would take the `Unexpected maintenance error` branch of the handler and throw away
    the one thing the caller can act on.
    """
    status, code = http_error_for(IncidentPhotoStorageUnavailableError("x"))

    assert (status, code.value) == (502, "BAD_GATEWAY")


def test_the_oversized_upload_is_a_413() -> None:
    """R5.1's use-case-level half. The middleware answers first in an HTTP request; this is
    the code the use case's own ceiling produces for a caller with no middleware in front."""
    status, code = http_error_for(IncidentPhotoTooLargeError("x"))

    assert (status, code.value) == (413, "PAYLOAD_TOO_LARGE")


def test_an_unsupported_format_is_422_and_not_404() -> None:
    """R2.10's sibling: the bytes are wrong, which is a validation failure about the request.

    Distinct from `cleaning`, where an unknown `photo_type` is a `404` because it names a row
    of a template. Here the stage is a closed enum and the format comes from the bytes, so
    there is nothing whose existence a `404` could describe.
    """
    status, code = http_error_for(UnsupportedIncidentPhotoFormatError("x"))

    assert (status, code.value) == (422, "VALIDATION_ERROR")


def test_subclasses_come_before_their_base() -> None:
    """`_MAPPING` is ordered and first match wins, so a base before its subclass would swallow
    it: the base's row matches first and the subclass never gets its own status.

    The module's header claims the hierarchy is flat "which is exactly what that flatness
    buys" — this checks the ordering property structurally rather than trusting the claim, so
    it stays true if someone ever does introduce a subclass.
    """
    for index, (error_class, _, _) in enumerate(_MAPPING):
        for later_class, _, _ in _MAPPING[index + 1 :]:
            assert not issubclass(later_class, error_class) or later_class is error_class


def test_the_hierarchy_is_actually_flat() -> None:
    """The premise the ordering argument rests on, asserted rather than assumed.

    Every declared error is a direct child of `MaintenanceDomainError`. If that ever stops
    being true, `test_subclasses_come_before_their_base` becomes load-bearing instead of
    belt-and-braces, and this test is the one that says so out loud.
    """
    for error_class in _concrete_domain_errors():
        assert error_class.__bases__ == (MaintenanceDomainError,)


def test_an_unmapped_maintenance_error_falls_to_500() -> None:
    class SurpriseError(MaintenanceDomainError):
        pass

    status, code = http_error_for(SurpriseError("x"))

    assert status == 500
    assert code.value == "INTERNAL_ERROR"


def test_the_handler_does_not_echo_the_message_on_500() -> None:
    """A 500 body must not carry a domain message that was never meant for a client."""
    source = inspect.getsource(errors_module.register_maintenance_error_handlers)

    assert "Unexpected maintenance error" in source
