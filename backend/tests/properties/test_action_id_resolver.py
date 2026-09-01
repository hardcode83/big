"""Unit tests for `ActionIdResolver`.

Pure application-layer logic: the resolver partitions rows by `blocking_state` family,
calls one batch port per family, returns a `{property_id: (cleaning_id, incident_id)}`
mapping. The fakes are the ones the rest of the suite already uses
(`tests/dashboard/doubles.py`).

These tests are the `Cada tarea de implementación incluye su test` of section 2 — without
them, the integration suite (section 3, `test_blocked_transitions_api.py`) was green
silently because it never exercised the incident branch with a populated summary.
"""

import uuid
from dataclasses import dataclass, field

import pytest

from app.cleaning.domain.value_objects import CleaningTaskSummary
from app.maintenance.domain.value_objects import IncidentSummary
from app.properties.application.action_id_resolver import (
    CLEANING_BLOCKING_STATES,
    ActionIdResolver,
)
from app.properties.domain.enums import PropertyOperationalState
from tests.dashboard.doubles import FakeCleaningRepository, FakeIncidentReader

CLEANING_STATE = PropertyOperationalState.CLEANING_IN_PROGRESS
INCIDENT_STATE = PropertyOperationalState.MAINTENANCE_REQUIRED


@dataclass
class _CountingCleaningRepository:
    """Counts calls and returns the configured batch result. Standalone — not the shared
    `FakeCleaningRepository` — because that one returns summaries keyed by tenant only,
    while this test wants to count calls and pin what was passed.
    """

    result: list[CleaningTaskSummary] = field(default_factory=list)
    calls: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = field(default_factory=list)

    async def list_live_for_properties(self, tenant_id, property_ids):
        self.calls.append((tenant_id, tuple(property_ids)))
        return list(self.result)


@dataclass
class _CountingIncidentReader:
    """Same as `_CountingCleaningRepository` for the incident port. Tracks `tenant_id`
    plus the property_ids argument so R3.1/R3.2 (`tenant_id` verbatim) and R3.4 (one call
    per page) can be asserted from the test.
    """

    result: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    calls: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = field(default_factory=list)

    async def list_open_for_properties(self, tenant_id, property_ids):
        self.calls.append((tenant_id, tuple(property_ids)))
        wanted = set(property_ids)
        return {pid: inc_id for pid, inc_id in self.result.items() if pid in wanted}


def _summary(id_: uuid.UUID, property_id: uuid.UUID) -> IncidentSummary:
    return IncidentSummary(
        id=id_, category="maintenance", severity="LOW", opened_at=None  # type: ignore[arg-type]
    )


def _task(id_: uuid.UUID, property_id: uuid.UUID) -> CleaningTaskSummary:
    return CleaningTaskSummary(
        id=id_,
        property_id=property_id,
        status="LIVE",  # type: ignore[arg-type]
    )


# --- R2.5: partition by family, never both for the same row ---


def test_cleaning_family_routes_to_cleaning_bucket_only() -> None:
    """R2.1: `blocking_state ∈ CLEANING_BLOCKING_STATES` → cleaning bucket, NO incident query."""
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    rows = [(pid, PropertyOperationalState.AWAITING_CLEANING)]

    # Pure-Python coroutine; sync test framework needs asyncio.run, but since this test
    # is meant to read top-to-bottom as a unit test we run the resolver synchronously.
    import asyncio

    result = asyncio.run(resolver.resolve(rows, tenant_id=uuid.uuid4()))

    assert result == {pid: (None, None)}  # no live task → cleaning_task_id is None
    assert len(cleaning_port.calls) == 1
    assert incident_port.calls == []  # R2.5: incident port never called for cleaning rows


@pytest.mark.parametrize("state", sorted(CLEANING_BLOCKING_STATES, key=lambda s: s.value))
def test_each_cleaning_family_state_routes_to_cleaning_bucket(state: PropertyOperationalState) -> None:
    """All three states in `CLEANING_BLOCKING_STATES` route to cleaning; the partition is exhaustive."""
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()
    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]

    pid = uuid.uuid4()
    import asyncio

    asyncio.run(resolver.resolve([(pid, state)], tenant_id=uuid.uuid4()))

    assert len(cleaning_port.calls) == 1
    assert incident_port.calls == []


def test_non_cleaning_state_routes_to_incident_bucket_only() -> None:
    """R2.2: `blocking_state` not in the cleaning family → incident bucket, NO cleaning query."""
    cleaning_port = FakeCleaningRepository()
    incident_port = _CountingIncidentReader()

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    import asyncio

    result = asyncio.run(resolver.resolve([(pid, INCIDENT_STATE)], tenant_id=uuid.uuid4()))

    assert result == {pid: (None, None)}
    assert cleaning_port.calls == []
    assert len(incident_port.calls) == 1


# --- R2.1, R2.2, R2.3, R2.4: population rules ---


def test_cleaning_row_with_live_task_yields_the_task_id() -> None:
    """R2.1: `cleaning_task_id` populated when a live task exists; R2.3 (the absence is the absence)."""
    pid = uuid.uuid4()
    task_id = uuid.uuid4()
    cleaning_port = _CountingCleaningRepository(result=[_task(task_id, pid)])
    incident_port = FakeIncidentReader()

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    result = asyncio.run(resolver.resolve([(pid, CLEANING_STATE)], tenant_id=uuid.uuid4()))

    assert result[pid] == (task_id, None)


def test_cleaning_row_with_no_live_task_yields_none() -> None:
    """R2.3 (no live task): `cleaning_task_id` is None, the row still maps."""
    pid = uuid.uuid4()
    cleaning_port = _CountingCleaningRepository(result=[])
    incident_port = FakeIncidentReader()

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    result = asyncio.run(resolver.resolve([(pid, CLEANING_STATE)], tenant_id=uuid.uuid4()))

    assert result[pid] == (None, None)


def test_incident_row_with_open_incident_yields_the_incident_id() -> None:
    """R2.2 + the narrowing: the resolver returns the incident **id**, not the summary."""
    pid = uuid.uuid4()
    incident_id = uuid.uuid4()
    cleaning_port = FakeCleaningRepository()
    incident_port = FakeIncidentReader()
    incident_port.open_by_property[pid] = [_summary(incident_id, pid)]

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    result = asyncio.run(resolver.resolve([(pid, INCIDENT_STATE)], tenant_id=uuid.uuid4()))

    assert result[pid] == (None, incident_id)
    assert isinstance(result[pid][1], uuid.UUID)


def test_incident_row_with_no_open_incident_yields_none() -> None:
    """R2.4 (no open incident): `incident_id` is None, the row still maps."""
    pid = uuid.uuid4()
    cleaning_port = FakeCleaningRepository()
    incident_port = FakeIncidentReader()  # no entry for `pid`

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    result = asyncio.run(resolver.resolve([(pid, INCIDENT_STATE)], tenant_id=uuid.uuid4()))

    assert result[pid] == (None, None)


# --- R3.1, R3.2: tenant_id is forwarded verbatim ---


def test_tenant_id_is_forwarded_to_both_ports() -> None:
    """R3.1, R3.2: the resolver passes the verified `tenant_id` straight through."""
    tenant = uuid.uuid4()
    cleaning_pid = uuid.uuid4()
    incident_pid = uuid.uuid4()
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()
    incident_port.result[incident_pid] = uuid.uuid4()

    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(
        resolver.resolve(
            [(cleaning_pid, CLEANING_STATE), (incident_pid, INCIDENT_STATE)],
            tenant_id=tenant,
        )
    )

    assert len(cleaning_port.calls) == 1
    assert cleaning_port.calls[0][0] == tenant
    assert len(incident_port.calls) == 1
    assert incident_port.calls[0][0] == tenant


# --- R3.4: at most one call per family per resolve() invocation ---


def test_mixed_page_issues_exactly_two_calls() -> None:
    """R3.4: one call to cleaning, one call to incident — never N+1."""
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()

    rows = [
        (uuid.uuid4(), CLEANING_STATE),
        (uuid.uuid4(), CLEANING_STATE),
        (uuid.uuid4(), INCIDENT_STATE),
        (uuid.uuid4(), INCIDENT_STATE),
        (uuid.uuid4(), INCIDENT_STATE),
    ]
    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(resolver.resolve(rows, tenant_id=uuid.uuid4()))

    assert len(cleaning_port.calls) == 1, "cleaning batch must be a single call"
    assert len(incident_port.calls) == 1, "incident batch must be a single call"
    # And the property_ids passed to each port are exactly the right partition:
    assert sorted(cleaning_port.calls[0][1]) == sorted(pid for pid, state in rows if state == CLEANING_STATE)
    assert sorted(incident_port.calls[0][1]) == sorted(pid for pid, state in rows if state == INCIDENT_STATE)


def test_single_family_page_issues_exactly_one_call() -> None:
    """R3.4: a cleaning-only page does not query incidents and vice versa."""
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()

    rows = [(uuid.uuid4(), CLEANING_STATE) for _ in range(5)]
    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(resolver.resolve(rows, tenant_id=uuid.uuid4()))

    assert len(cleaning_port.calls) == 1
    assert incident_port.calls == []


def test_empty_rows_short_circuits_to_no_calls() -> None:
    """R3.4 (and R2): empty input → no port calls, empty mapping."""
    cleaning_port = _CountingCleaningRepository()
    incident_port = _CountingIncidentReader()
    resolver = ActionIdResolver(cleaning_tasks=cleaning_port, incidents=incident_port)  # type: ignore[arg-type]
    import asyncio

    result = asyncio.run(resolver.resolve([], tenant_id=uuid.uuid4()))

    assert result == {}
    assert cleaning_port.calls == []
    assert incident_port.calls == []
