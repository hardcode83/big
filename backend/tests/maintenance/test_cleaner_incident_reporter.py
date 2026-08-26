"""`CleanerIncidentReporter` — the adapter, not a second alta (`cleaner-incident-report` D3).

R3.7 says the generic alta "existe precisamente para esto y SHALL extenderse, no duplicarse",
so most of what matters here is **negative**: what this class cannot be asked to do. The three
writes, their order and their transaction are `ReportIncidentUseCase`'s and are tested in
`test_report_incident.py`; what this file pins is that the adapter seals what it must seal and
adds nothing of its own.

Fakes rather than the database: what is under test is delegation, and a real session would only
re-test the writer next door.
"""

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain.entities import AuditLog
from app.auth.domain.enums import UserRole
from app.cleaning.domain.ports import IncidentReport, IncidentReportedAcknowledgement
from app.maintenance.application.use_cases import (
    CleanerIncidentReporter,
    ReportIncidentUseCase,
)
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.timeline.domain.entities import TimelineEvent

NOW = datetime(2026, 8, 19, 9, 15, tzinfo=UTC)
TENANT_ID = uuid.uuid4()
PROPERTY_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
CLEANER_ID = uuid.uuid4()
REPORT = IncidentReport(
    title="Caldera rota",
    description="No sale agua caliente en el baño del piso.",
)


class _Journal:
    def __init__(self) -> None:
        self.entries: list[tuple[str, object]] = []

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.entries]

    def only(self, kind: str) -> object:
        matching = [payload for k, payload in self.entries if k == kind]
        assert len(matching) == 1, f"expected exactly one {kind}, got {len(matching)}"
        return matching[0]


class _FakeIncidents:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        self._journal.entries.append(("incident", incident))


class _FakeAudit:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        self._journal.entries.append(("audit", entry))


class _FakeTimeline:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, event: TimelineEvent) -> None:
        self._journal.entries.append(("timeline", event))


class _RecordingUnitOfWork:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def commit(self) -> None:
        self._journal.entries.append(("commit", None))


class _FakeProperties:
    def __init__(self, known: set[tuple[uuid.UUID, uuid.UUID]]) -> None:
        self._known = known

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> object | None:
        return object() if (tenant_id, property_id) in self._known else None


def _reporter(
    journal: _Journal, *, known_property: bool = True
) -> CleanerIncidentReporter:
    return CleanerIncidentReporter(
        ReportIncidentUseCase(
            incidents=_FakeIncidents(journal),
            properties=_FakeProperties(
                {(TENANT_ID, PROPERTY_ID)} if known_property else set()
            ),
            audit=_FakeAudit(journal),
            timeline=_FakeTimeline(journal),
            uow=_RecordingUnitOfWork(journal),
        )
    )


async def _report(journal: _Journal, **overrides) -> IncidentReportedAcknowledgement:
    known_property = overrides.pop("known_property", True)
    kwargs = {
        "tenant_id": TENANT_ID,
        "property_id": PROPERTY_ID,
        "cleaning_task_id": TASK_ID,
        "report": REPORT,
        "actor_user_id": CLEANER_ID,
        "ip": "203.0.113.7",
        "now": NOW,
    }
    kwargs.update(overrides)
    return await _reporter(journal, known_property=known_property).report(**kwargs)


def test_the_source_is_not_a_parameter_so_no_other_can_be_asked_for() -> None:
    """R3.1, by construction rather than by care.

    The seal is only worth something if `cleaning` has no way to request a different source.
    A `source` parameter — even one defaulting to `CLEANER` — would move that decision to the
    consuming module, which is D3's rejected alternative.
    """
    parameters = inspect.signature(CleanerIncidentReporter.report).parameters

    assert "source" not in parameters
    # And nothing else that would let the caller choose what kind of incident this is.
    assert not {
        "category",
        "severity",
        "status",
        "ai_summary",
        "ai_classification",
        "reported_by_guest_token",
        "assigned_technician_id",
    } & set(parameters)


@pytest.mark.asyncio
async def test_the_incident_is_sealed_cleaner() -> None:
    journal = _Journal()

    await _report(journal)

    incident = journal.only("incident")
    assert isinstance(incident, Incident)
    assert incident.source is IncidentSource.CLEANER


@pytest.mark.asyncio
async def test_it_is_born_open_and_unclassified() -> None:
    """R3.2: the classification job fills these in on a later tick, and an incident born with
    them already set would be indistinguishable from a classified one."""
    journal = _Journal()

    acknowledgement = await _report(journal)

    incident = journal.only("incident")
    assert isinstance(incident, Incident)
    assert incident.status is IncidentStatus.OPEN
    assert incident.ai_summary is None
    assert incident.ai_classification is None
    assert incident.assigned_technician_id is None
    # `category` and `severity` are NOT NULL with DDL defaults, so "unset" means the default
    # rather than `None` — asserted as the values the classifier will overwrite.
    assert incident.category is IncidentCategory.OTHER
    assert incident.severity is IncidentSeverity.MEDIUM
    # R6.2's declared coupling starts here: born MEDIUM, so it does not block a `complete()`
    # at the moment it is reported.
    assert acknowledgement.status is IncidentStatus.OPEN


@pytest.mark.asyncio
async def test_the_acknowledgement_is_the_three_fields_and_nothing_else() -> None:
    """R4.4/R4.5. Read off the dataclass so a fourth field has to be added deliberately."""
    journal = _Journal()

    acknowledgement = await _report(journal)

    incident = journal.only("incident")
    assert isinstance(incident, Incident)
    assert acknowledgement == IncidentReportedAcknowledgement(
        id=incident.id, status=incident.status, created_at=incident.created_at
    )
    assert {f.name for f in IncidentReportedAcknowledgement.__dataclass_fields__.values()} == {
        "id",
        "status",
        "created_at",
    }


@pytest.mark.asyncio
async def test_the_reporter_and_the_task_are_written_and_the_guest_token_is_not() -> None:
    """R3.3, R4.3: the cleaner's own id lands in `reported_by_user_id`, and
    `reported_by_guest_token` stays `NULL` — this is not an anonymous surface."""
    journal = _Journal()

    await _report(journal)

    incident = journal.only("incident")
    assert isinstance(incident, Incident)
    assert incident.reported_by_user_id == CLEANER_ID
    assert incident.cleaning_task_id == TASK_ID
    assert incident.reported_by_guest_token is None
    assert incident.property_id == PROPERTY_ID
    assert incident.reservation_id is None


@pytest.mark.asyncio
async def test_it_delegates_rather_than_repeating_the_three_writes() -> None:
    """R3.7. One incident row, one audit row, one timeline entry, one commit — the same journal
    `ReportIncidentUseCase` produces on its own. A second alta here would show up as doubles."""
    journal = _Journal()

    await _report(journal)

    assert journal.kinds() == ["incident", "audit", "timeline", "commit"]


@pytest.mark.asyncio
async def test_the_audit_actor_is_the_cleaner_with_their_ip() -> None:
    """Rule 9 of `steering/security.md`: the actor and the IP are the two things `audit_logs`
    records that `property_state_transitions` cannot."""
    journal = _Journal()

    await _report(journal)

    entry = journal.only("audit")
    assert isinstance(entry, AuditLog)
    assert entry.actor_user_id == CLEANER_ID
    assert entry.actor_ip == "203.0.113.7"
    assert entry.actor_guest_token_hash is None


def test_an_actor_is_required_by_the_signature() -> None:
    """R3.6, one layer above `_AuditWriter`.

    The port types `actor_user_id` as a plain `uuid.UUID` with no default, so there is no way
    to reach the writer's refusal from this surface — the alta without an actor that rule 9's
    fourth exception does not cover cannot be expressed here at all.
    """
    parameter = inspect.signature(CleanerIncidentReporter.report).parameters["actor_user_id"]

    assert parameter.default is inspect.Parameter.empty
    assert parameter.annotation is uuid.UUID


@pytest.mark.asyncio
async def test_a_property_outside_the_tenant_is_refused_before_anything_is_written() -> None:
    """The precondition `IncidentRepository.add` states and `ReportIncidentUseCase` discharges.

    Unreachable through the route — the use case of `cleaning` derives `property_id` from a task
    it already resolved inside the tenant — which is exactly why it is worth pinning that the
    adapter does not bypass the check on the way past.
    """
    journal = _Journal()

    with pytest.raises(MaintenanceValidationError):
        await _report(journal, known_property=False)

    assert journal.kinds() == []


def test_the_actor_role_is_sealed_and_not_taken_from_the_caller() -> None:
    """The port carries a user id and an IP, not a role: this adapter serves one surface.

    Nothing on the alta path reads the role — `_AuditWriter` records the user and the IP — so
    sealing `CLEANER` states the fact rather than deciding anything. Pinned so that a later
    edit cannot quietly make the role a parameter and thereby a claim about the caller.
    """
    parameters = inspect.signature(CleanerIncidentReporter.report).parameters

    assert "role" not in parameters
    assert "actor" not in parameters
    assert UserRole.CLEANER.value == "CLEANER"


def test_an_actor_without_an_identity_is_refused_at_runtime_not_only_by_the_type() -> None:
    """R3.6 as a **runtime** property, which is what the signature test above is not.

    Raised by the security panel of sections 3-4: `IncidentActor.user_id` was typed
    non-optional and Python builds `IncidentActor(user_id=None, …)` anyway, after which
    `_AuditWriter.record` waves it through — it refuses only `actor is None` — and an
    append-only `INCIDENT_CREATED` row naming nobody gets committed. That is exactly the alta
    rule 9's fourth exception does not cover.

    Pinned on the value object rather than on this adapter so it holds for every incident flow,
    not just the cleaner's.
    """
    from app.maintenance.application.use_cases import IncidentActor

    with pytest.raises(MaintenanceValidationError):
        IncidentActor(user_id=None, role=UserRole.CLEANER, ip="203.0.113.7")


@pytest.mark.asyncio
async def test_an_alta_without_an_identified_actor_writes_absolutely_nothing() -> None:
    """The other half of R3.6 — "y no comitear nada" — measured rather than inferred.

    Before the guard above, the QA panel of sections 3-4 measured this exact call handing an
    incident **and** an actor-less audit row to their repositories, and surviving only because
    `TimelineEventFactory` happened to raise afterwards. "Nothing was committed" was true by
    accident of ordering in an unrelated module, not because R3.6 was enforced. This asserts
    the refusal comes first, so the count is zero rather than rolled back.
    """
    journal = _Journal()

    with pytest.raises(MaintenanceValidationError):
        await _report(journal, actor_user_id=None)

    assert journal.kinds() == []
