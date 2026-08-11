"""The read port of the timeline (`dashboard-api` R4.2, R4.4, task 2.2).

`TimelineFilters` holding its own contradictions, and the port split that keeps the write
side incapable of anything but `add`.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.exceptions import TimelineFilterValidationError
from app.timeline.domain.repositories import (
    TimelineEventReader,
    TimelineEventRepository,
    TimelineFilters,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_no_filter_is_the_default() -> None:
    filters = TimelineFilters()

    assert (
        filters.event_type,
        filters.severity,
        filters.actor_type,
        filters.occurred_from,
        filters.occurred_to,
    ) == (None, None, None, None, None)


def test_the_five_prd_filters_are_accepted_together() -> None:
    filters = TimelineFilters(
        event_type=TimelineEventType.CLEANING_COMPLETED,
        severity=TimelineSeverity.WARNING,
        actor_type=TimelineActorType.SYSTEM,
        occurred_from=NOW - timedelta(days=1),
        occurred_to=NOW,
    )

    assert filters.event_type is TimelineEventType.CLEANING_COMPLETED


def test_an_inverted_range_is_a_contradiction_not_an_empty_result() -> None:
    with pytest.raises(TimelineFilterValidationError):
        TimelineFilters(occurred_from=NOW, occurred_to=NOW - timedelta(seconds=1))


def test_an_equal_range_is_legitimate() -> None:
    assert TimelineFilters(occurred_from=NOW, occurred_to=NOW).occurred_to == NOW


@pytest.mark.parametrize("field_name", ["occurred_from", "occurred_to"])
def test_a_naive_bound_is_rejected(field_name: str) -> None:
    """`timeline_events.created_at` is TIMESTAMPTZ; a naive bound compares wrongly."""
    with pytest.raises(TimelineFilterValidationError):
        TimelineFilters(**{field_name: datetime(2026, 8, 9, 12, 0)})


# --- the port split (R4.4) --------------------------------------------------------------
#
# The QA panel of section 2 asked for parity with R5.4's enum-coverage guard: the
# immutability claim was true and inspectable, but nothing would have failed if a future
# edit merged the two Protocols or added a mutator. These two tests are that guard.


def _protocol_methods(protocol: type) -> set[str]:
    return {
        name
        for name in vars(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }


def test_the_write_port_still_admits_nothing_but_append() -> None:
    """R4.4: "dejando intacta la inmutabilidad que `app/timeline/domain/repositories.py:8-11`
    expresa en la firma: no aparece `save`, `update` ni `delete`".

    The signature IS the rule — `steering/architecture.md` calls the timeline immutable —
    so the rule needs a test, not just a docstring saying so.
    """
    assert _protocol_methods(TimelineEventRepository) == {"add"}


def test_the_reader_is_a_separate_port_and_writes_nothing() -> None:
    """Design D2: a `Protocol` **separado**, Interface Segregation. Merging the two would
    hand every holder of the writer a reader and vice versa."""
    assert _protocol_methods(TimelineEventReader) == {
        "list_for_property",
        "last_for_properties",
    }
    assert not _protocol_methods(TimelineEventReader) & _protocol_methods(
        TimelineEventRepository
    )
