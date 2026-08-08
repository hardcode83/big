"""`NotificationResult` makes rule 11 hold by construction (design D8).

The point of these tests is not the dataclass — it is that **no adapter can put a provider's
error text into `notification_logs.last_error`**, because the return type has nowhere to put
it. Rule 11 of `sdd/steering/security.md` records that the same guarantee, left to
convention, leaked three times.
"""

import dataclasses
import typing

import pytest

from app.notifications.domain.results import NotificationErrorCode, NotificationResult


def _accepts_str(hint: object) -> bool:
    return hint is str or str in typing.get_args(hint)


def test_result_has_no_free_text_error_field() -> None:
    """The structural guarantee, asserted rather than assumed.

    If somebody adds a `str`-typed error field to carry "just the provider's message", this
    fails — which is the whole reason the test exists. `provider_message_id` is the one
    string allowed through, and it is an opaque handle, not content.

    `NotificationErrorCode` subclasses `str` for the usual SQLAlchemy reasons, so the check
    reads the **annotations**, not the runtime MRO: `error_code` is typed as the enum, and
    an adapter cannot put arbitrary text there whatever the enum inherits from.
    """
    hints = typing.get_type_hints(NotificationResult)
    string_fields = {
        field.name
        for field in dataclasses.fields(NotificationResult)
        if _accepts_str(hints[field.name])
    }
    assert string_fields == {"provider_message_id"}


def test_error_code_is_a_closed_enum() -> None:
    assert issubclass(NotificationErrorCode, str)
    assert {code.value for code in NotificationErrorCode} == {
        "ADAPTER_ERROR",
        "INVALID_RECIPIENT",
        "TIMEOUT",
        "NO_ADAPTER_FOR_CHANNEL",
        "MAX_ATTEMPTS_EXCEEDED",
    }


def test_ok_is_delivered_without_error() -> None:
    result = NotificationResult.ok(provider_message_id="abc-123")
    assert result.delivered is True
    assert result.error_code is None
    assert result.provider_message_id == "abc-123"


def test_failure_carries_its_code() -> None:
    result = NotificationResult.failure(NotificationErrorCode.TIMEOUT)
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.TIMEOUT


def test_delivered_with_error_code_is_rejected() -> None:
    """`record_attempt` branches on these two fields; a contradictory pair would write
    `SENT` and a `last_error` in the same row."""
    with pytest.raises(ValueError):
        NotificationResult(delivered=True, error_code=NotificationErrorCode.TIMEOUT)


def test_failure_without_error_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        NotificationResult(delivered=False)


def test_result_is_immutable() -> None:
    result = NotificationResult.ok()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.delivered = False  # type: ignore[misc]
