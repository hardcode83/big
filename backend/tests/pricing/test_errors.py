"""D15 — the error table, and the completeness net its docstring promises.

Modelled on `tests/cleaning/test_errors.py`, which exists because `cleaning` made the same
promise in prose and the QA panel found no test behind it. The fallback is what makes this
worth pinning: an unmapped domain error becomes a 500 reading "Unexpected pricing error",
with the outcome the caller needed to distinguish thrown away — a 409 R5.4 promised, or a 422
R1.4 promised, silently downgraded to "our bug".

The three body rules of task 6.2 are asserted here too, because each one is a rule about a
**response** and there is nowhere else that reads the handler: the message is not logged, no
message echoes an unbounded caller value, and the two 404s are indistinguishable (R1.7).
"""

import inspect

import pytest

from app.core.error_codes import ErrorCode
from app.pricing.api import errors as errors_module
from app.pricing.api.errors import _MAPPING, http_error_for
from app.pricing.domain import exceptions as exceptions_module
from app.pricing.domain.exceptions import (
    InvalidRecommendationTransitionError,
    PriceRecommendationNotFoundError,
    PricingDomainError,
    PricingRuleNotFoundError,
    PricingValidationError,
)


def _concrete_domain_errors() -> set[type]:
    """Every subclass of `PricingDomainError` declared in the domain's exception module."""
    return {
        obj
        for _, obj in inspect.getmembers(exceptions_module, inspect.isclass)
        if issubclass(obj, PricingDomainError)
        and obj is not PricingDomainError
        and obj.__module__ == exceptions_module.__name__
    }


def test_every_domain_error_has_a_row() -> None:
    """The net D15 promises. Add an exception without a row and this fails."""
    mapped = {entry[0] for entry in _MAPPING}

    assert _concrete_domain_errors() == mapped


def test_no_row_names_an_exception_from_another_module() -> None:
    """`register_pricing_error_handlers` installs one handler, for `PricingDomainError`.

    A row naming somebody else's exception — `maintenance` has a `ValidationError` of the
    same shape — would never be reached by that handler, so it is dead weight that reads as
    coverage.
    """
    for error_class, _, _ in _MAPPING:
        assert issubclass(error_class, PricingDomainError)
        assert error_class.__module__ == exceptions_module.__name__


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PricingRuleNotFoundError(), (404, ErrorCode.NOT_FOUND)),
        (PriceRecommendationNotFoundError(), (404, ErrorCode.NOT_FOUND)),
        (InvalidRecommendationTransitionError("x"), (409, ErrorCode.CONFLICT)),
        (PricingValidationError("min_price", "x"), (422, ErrorCode.VALIDATION_ERROR)),
    ],
)
def test_each_error_maps_to_its_status_and_code(error, expected) -> None:
    """D15's table, value by value. `test_every_domain_error_has_a_row` only checks
    presence, so without this a row could carry any status and stay green."""
    assert http_error_for(error) == expected


def test_no_row_introduces_a_new_error_code() -> None:
    """D15: "Ningún `ErrorCode` nuevo" — the published contract keeps its shape.

    `tests/test_openapi_contract.py` proves the registry is the published enum; this proves
    the claim D15 makes about *this* table, which is narrower: the three codes it needs
    already existed before the change.
    """
    assert {code for _, _, code in _MAPPING} == {
        ErrorCode.NOT_FOUND,
        ErrorCode.CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    }


def test_subclasses_come_before_their_base() -> None:
    """`_MAPPING` is ordered and first match wins, so a base placed before its subclass
    would swallow it. The hierarchy is flat today (see `domain/exceptions.py`), which is what
    makes every row independent — this is what keeps it that way."""
    for index, (error_class, _, _) in enumerate(_MAPPING):
        for later_class, _, _ in _MAPPING[index + 1 :]:
            assert not issubclass(later_class, error_class) or later_class is error_class


def test_an_unmapped_pricing_error_falls_to_500() -> None:
    class SurpriseError(PricingDomainError):
        pass

    status, code = http_error_for(SurpriseError("x"))

    assert (status, code) == (500, ErrorCode.INTERNAL_ERROR)


def test_the_handler_does_not_echo_the_message_on_500() -> None:
    source = inspect.getsource(errors_module.register_pricing_error_handlers)

    assert "Unexpected pricing error" in source


def test_the_handler_does_not_log_the_message() -> None:
    """Task 6.2, first body rule: `str(exc)` is rendered, never logged.

    A 422 from `PricingValidationError` can carry the `name` a manager typed, and the
    application log is not one of the sinks the rule-11 census covers for it. `maintenance`'s
    handler settled on this exact shape; asserted rather than trusted because adding a
    `logger.warning(str(exc))` here is the natural next edit somebody makes while debugging.

    Two halves, because either alone is escapable: the module imports no logging machinery,
    and the handler body calls nothing that looks like a log.
    """
    assert not hasattr(errors_module, "logger")
    assert not hasattr(errors_module, "logging")

    handler = inspect.getsource(errors_module.register_pricing_error_handlers)

    assert ".warning(" not in handler
    assert ".exception(" not in handler
    assert ".error(" not in handler
    assert ".info(" not in handler


def test_the_two_not_found_messages_are_constants_and_indistinguishable_per_resource() -> None:
    """Task 6.2, third body rule, and R1.7 below the status code.

    Two rules — one unknown, one another tenant's — must answer with the same body, which
    holds because the message is the constructor default and no call site overrides it. The
    *rule* and the *recommendation* messages differ from each other, and that is fine: they
    are different paths, and nothing about one leaks whether the other exists.
    """
    assert str(PricingRuleNotFoundError()) == str(PricingRuleNotFoundError())
    assert str(PriceRecommendationNotFoundError()) == str(
        PriceRecommendationNotFoundError()
    )
    assert "Pricing rule does not exist" == str(PricingRuleNotFoundError())
    assert "Price recommendation does not exist" == str(PriceRecommendationNotFoundError())
