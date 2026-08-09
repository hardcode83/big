"""`ManualAccessAdapter` and `MockAccessAdapter` (R2.1, design D12).

The assertion that matters is not "it works": it is that **neither adapter can hand the
plaintext code back**, in any field, on any path. Design D9 says the code dies in the
request handler, and an adapter is the one place with both the plaintext and a return value.
"""

from datetime import UTC, datetime

import pytest

from app.access.domain.enums import AccessProvider, AccessRecordStatus
from app.access.infrastructure.adapters import ManualAccessAdapter, MockAccessAdapter
from tests.access.test_entities import _record

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
CODE = "481523"
ADAPTERS = [ManualAccessAdapter(), MockAccessAdapter()]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_registering_a_code_moves_the_record_and_keeps_only_the_mask(adapter) -> None:
    record = _record()

    moved = await adapter.create_manual_access(
        record=record, code=CODE, notes="left with the neighbour", now=NOW
    )

    assert moved.status is AccessRecordStatus.MANUAL_ADDED
    assert moved.code_masked == "****23"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_no_adapter_returns_the_plaintext_code_anywhere(adapter) -> None:
    """Design D9, asserted over the whole returned object rather than a named field.

    A future adapter that stashes the code in `notes`, `external_id` or a new attribute
    fails here, which is the point: the guarantee is "nowhere", not "not in `code_masked`".
    """
    record = _record()

    moved = await adapter.create_manual_access(
        record=record, code=CODE, notes=None, now=NOW
    )

    assert CODE not in repr(moved)
    assert not any(
        isinstance(value, str) and CODE in value for value in vars(moved).values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_marking_external_records_the_provider_owns_it(adapter) -> None:
    record = _record()

    moved = await adapter.mark_external_managed(record=record, notes=None, now=NOW)

    assert moved.status is AccessRecordStatus.CREATED_EXTERNAL
    assert moved.provider is AccessProvider.EXTERNAL_MANAGED


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_both_adapters_refuse_the_same_invalid_transition(adapter) -> None:
    """Liskov (`steering/backend-architecture.md`): "mismas excepciones, misma forma de
    retorno, mismas precondiciones". The precondition is the entity's, so both inherit it."""
    from app.access.domain.exceptions import InvalidAccessTransitionError

    record = _record(AccessRecordStatus.DELIVERED)

    with pytest.raises(InvalidAccessTransitionError):
        await adapter.create_manual_access(record=record, code=CODE, notes=None, now=NOW)


@pytest.mark.asyncio
async def test_the_manual_adapter_has_no_provider_to_ask() -> None:
    """`None` is an ordinary answer, not an error: there is no external system here."""
    assert await ManualAccessAdapter().get_access_status("PMS-123") is None


@pytest.mark.asyncio
async def test_the_mock_adapter_reports_the_demo_code_already_masked() -> None:
    """PRD §15: "genera código demo `****23`" — masked at the source.

    A mock that produced a plaintext demo code would be the first place a real one learned it
    could live in this module.
    """
    result = await MockAccessAdapter().get_access_status("PMS-123")

    assert result is not None
    assert result.status is AccessRecordStatus.CREATED_EXTERNAL
    assert result.code_masked == "****23"
    assert result.external_id == "mock-PMS-123"
    assert not hasattr(result, "code")
