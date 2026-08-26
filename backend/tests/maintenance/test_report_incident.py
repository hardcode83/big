"""`ReportIncidentUseCase` — the generic way in that `maintenance` did not have (D5).

Same shape as `test_report_guest_incident.py`: in-memory fakes of the three ports for the
orchestration — which rows are written, in which order, and what they carry — plus one
database-backed test for tenant isolation, which fakes cannot prove.

What separates this use case from its neighbour is what most of these tests assert: the
source is the caller's, and no reservation is required. PRD §27's third incident is
`source: CLEANER` and none of the three hangs off a stay, so `ReportGuestIncidentUseCase`
could not have created them.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.audit.domain.entities import AuditLog
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.domain.enums import UserRole
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.application.use_cases import IncidentActor, ReportIncidentUseCase
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineFilters
from app.timeline.infrastructure.repositories import (
    SqlAlchemyTimelineEventReader,
    SqlAlchemyTimelineEventRepository,
)
from tests.auth.conftest import insert_tenant

NOW = datetime(2026, 9, 2, 10, 30, tzinfo=UTC)
TITLE = "Lavadora hace ruido extraño"
DESCRIPTION = "La limpiadora reporta que la lavadora hace un ruido metálico al centrifugar"
TENANT_ID = uuid.uuid4()
PROPERTY_ID = uuid.uuid4()
ACTOR = IncidentActor(user_id=uuid.uuid4(), role=UserRole.TENANT_OWNER)


class _Journal:
    """One list for every write, so the *order* of the operation is observable."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, object]] = []

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.entries]

    def only(self, kind: str) -> object:
        matching = [payload for entry_kind, payload in self.entries if entry_kind == kind]
        assert len(matching) == 1, f"expected exactly one {kind}, got {len(matching)}"
        return matching[0]


class _FakeIncidents:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        assert incident.tenant_id == tenant_id
        self._journal.entries.append(("incident", incident))


class _FakeAudit:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        assert entry.tenant_id == tenant_id
        self._journal.entries.append(("audit", entry))


class _FakeTimeline:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def add(self, tenant_id: uuid.UUID, event: TimelineEvent) -> None:
        assert event.tenant_id == tenant_id
        self._journal.entries.append(("timeline", event))


class _RecordingUnitOfWork:
    def __init__(self, journal: _Journal) -> None:
        self._journal = journal

    async def commit(self) -> None:
        self._journal.entries.append(("commit", None))


class _FakeProperties:
    """Answers only for the property of `TENANT_ID`, which is the whole point of the lookup."""

    def __init__(self, known: set[tuple[uuid.UUID, uuid.UUID]]) -> None:
        self._known = known

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> object | None:
        return object() if (tenant_id, property_id) in self._known else None


async def _report(
    journal: _Journal,
    *,
    source: IncidentSource = IncidentSource.CLEANER,
    actor: IncidentActor | None = ACTOR,
    property_id: uuid.UUID = PROPERTY_ID,
    reported_by_user_id: uuid.UUID | None = None,
    cleaning_task_id: uuid.UUID | None = None,
) -> Incident:
    use_case = ReportIncidentUseCase(
        incidents=_FakeIncidents(journal),
        properties=_FakeProperties({(TENANT_ID, PROPERTY_ID)}),
        audit=_FakeAudit(journal),
        timeline=_FakeTimeline(journal),
        uow=_RecordingUnitOfWork(journal),
    )
    return await use_case.execute(
        tenant_id=TENANT_ID,
        property_id=property_id,
        source=source,
        title=TITLE,
        description=DESCRIPTION,
        actor=actor,
        now=NOW,
        reported_by_user_id=reported_by_user_id,
        cleaning_task_id=cleaning_task_id,
    )


@pytest.mark.asyncio
async def test_the_source_is_the_callers_and_never_forced_to_guest() -> None:
    """The first of `ReportGuestIncidentUseCase`'s two assumptions, and why D5 exists:
    that one writes `source=IncidentSource.GUEST` into the entity constructor."""
    journal = _Journal()

    incident = await _report(journal, source=IncidentSource.CLEANER)

    assert incident.source is IncidentSource.CLEANER
    assert incident.tenant_id == TENANT_ID
    assert incident.property_id == PROPERTY_ID
    assert incident.title == TITLE
    assert incident.description == DESCRIPTION


@pytest.mark.asyncio
async def test_an_incident_that_belongs_to_no_stay_can_be_opened() -> None:
    """The second assumption: `reservation_id` and `reporter_token_hash` are required over
    there. None of PRD §27's three incidents hangs off a reservation, and this use case has
    no way to name one — amended D5 removed the parameter rather than leave its tenant
    precondition undischarged."""
    journal = _Journal()

    incident = await _report(journal)

    assert incident.reservation_id is None
    assert incident.reported_by_guest_token is None
    assert incident.reported_by_user_id is None
    event = journal.only("timeline")
    assert isinstance(event, TimelineEvent)
    assert event.reservation_id is None


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_is_refused_before_anything_is_written() -> None:
    """`IncidentRepository.add` states the precondition — "`property_id` … must already have
    been resolved *within* `tenant_id`" — because the FKs of `incidents` are global and the
    database would accept the row. The guest path satisfies it structurally; this one, open
    to any caller, discharges it itself."""
    journal = _Journal()

    with pytest.raises(MaintenanceValidationError):
        await _report(journal, property_id=uuid.uuid4())

    assert journal.kinds() == []


@pytest.mark.asyncio
async def test_it_leaves_the_classification_flows_fields_alone() -> None:
    """The incident is born `OPEN` and unclassified: `category`, `severity` and
    `ai_classification` are the classifier's to write, not the caller's."""
    journal = _Journal()

    incident = await _report(journal)

    assert incident.status is IncidentStatus.OPEN
    assert incident.category is IncidentCategory.OTHER
    assert incident.severity is IncidentSeverity.MEDIUM
    assert incident.ai_summary is None
    assert incident.ai_classification is None
    assert incident.assigned_technician_id is None


@pytest.mark.asyncio
async def test_the_three_writes_happen_in_order_inside_one_transaction() -> None:
    journal = _Journal()

    await _report(journal)

    assert journal.kinds() == ["incident", "audit", "timeline", "commit"]


@pytest.mark.asyncio
async def test_the_audit_row_names_its_actor_and_the_structural_fields_only() -> None:
    journal = _Journal()

    incident = await _report(journal, source=IncidentSource.GUEST)

    entry = journal.only("audit")
    assert isinstance(entry, AuditLog)
    assert entry.action == "INCIDENT_CREATED"
    assert entry.entity_type == "INCIDENT"
    assert entry.entity_id == incident.id
    assert entry.actor_user_id == ACTOR.user_id
    assert entry.actor_guest_token_hash is None
    assert entry.changes == {
        "source": {"old": None, "new": "GUEST"},
        "status": {"old": None, "new": "OPEN"},
    }


@pytest.mark.asyncio
async def test_the_timeline_entry_carries_a_constant_title_and_identifiers_only() -> None:
    """Rule 11's excepción 2 concedes the reporter's prose in `incidents.title`/`description`
    and says of it that «no se propaga»: neither column may reach the timeline."""
    journal = _Journal()

    incident = await _report(journal)

    event = journal.only("timeline")
    assert isinstance(event, TimelineEvent)
    assert event.event_type is TimelineEventType.INCIDENT_CREATED
    assert event.actor_type is TimelineActorType.USER
    assert event.actor_user_id == ACTOR.user_id
    assert event.property_id == PROPERTY_ID
    assert event.created_at == NOW
    assert event.metadata == {
        "incident_id": str(incident.id),
        "source": IncidentSource.CLEANER.value,
    }
    assert TITLE not in event.title
    assert DESCRIPTION not in str(event.metadata)


@pytest.mark.asyncio
async def test_an_alta_without_an_actor_is_refused_and_writes_nothing() -> None:
    """Rule 9's fourth exception covers `INCIDENT_CLASSIFIED` and nothing else, and
    `_AuditWriter` is what makes that true by construction rather than by discipline."""
    journal = _Journal()

    with pytest.raises(MaintenanceValidationError):
        await _report(journal, actor=None)

    assert "commit" not in journal.kinds()


@pytest.mark.asyncio
async def test_nothing_it_writes_is_reachable_from_another_tenant(db_session, world) -> None:
    """DoD §28.18 and rule 1 of `steering/security.md`, over the three tables it writes.

    Against the real repositories and a real neighbour row: an unknown id proves nothing
    about scoping. The session is deliberately left **unmarked** — under
    `bind_session_to_tenant` the listener of `app/core/db.py` would filter every read, so the
    test could not fail and would prove nothing.
    """
    neighbour = await insert_tenant(db_session, name="Another Agency")
    use_case = ReportIncidentUseCase(
        incidents=SqlAlchemyIncidentRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )

    incident = await use_case.execute(
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        source=IncidentSource.CLEANER,
        title=TITLE,
        description=DESCRIPTION,
        actor=IncidentActor(user_id=world.owner.id, role=UserRole.TENANT_OWNER),
        now=NOW,
    )

    # Every row carries the acting tenant: one with a foreign `tenant_id` would be invisible
    # to its owner rather than visible to a stranger.
    assert incident.tenant_id == world.tenant.id
    audit_tenants = (
        (await db_session.execute(select(AuditLogModel.tenant_id))).scalars().all()
    )
    assert set(audit_tenants) == {world.tenant.id}

    # And the neighbour reaches none of it through the ports.
    incidents = SqlAlchemyIncidentRepository(db_session)
    assert await incidents.get(neighbour.id, incident.id) is None
    reader = SqlAlchemyTimelineEventReader(db_session)
    assert not (
        await reader.list_for_property(
            neighbour.id,
            world.property.id,
            filters=TimelineFilters(),
            page=1,
            per_page=50,
        )
    ).items


# --- the two parameters `cleaner-incident-report` adds (R3.3, R4.3; design D4, D10) ---------
#
# The amended D5 of 2026-08-16 removed `reservation_id` and `reported_by_user_id` because both
# "arrastraban la misma precondición sin descargar y hoy no tienen llamante", and set the rule
# for whoever brought the first: add the parameter **together with** the lookup that makes it
# safe. These tests are that rule being honoured rather than repealed.


@pytest.mark.asyncio
async def test_the_two_new_parameters_default_to_none_so_existing_callers_are_untouched() -> None:
    """R4.2, and the reason `app/cli/seed_demo.py` needed no edit at all.

    Keyword-only with a `None` default: a call written before this change produces exactly the
    entity it produced before.
    """
    journal = _Journal()

    incident = await _report(journal)

    assert incident.reported_by_user_id is None
    assert incident.cleaning_task_id is None


@pytest.mark.asyncio
async def test_both_ids_reach_the_entity_when_the_caller_has_them() -> None:
    """R3.3 and R4.3. Passed separately and not derived from one another: "who reported" and
    "who is acting" are two concepts, and collapsing them would silently change what the demo
    seed writes (D4's rejected alternative)."""
    journal = _Journal()
    reporter = uuid.uuid4()
    task = uuid.uuid4()

    incident = await _report(journal, reported_by_user_id=reporter, cleaning_task_id=task)

    assert incident.reported_by_user_id == reporter
    assert incident.cleaning_task_id == task
    # The actor is a different person from the reporter in this call, which is the case that
    # proves the use case does not derive one from the other.
    assert ACTOR.user_id != reporter


@pytest.mark.asyncio
async def test_the_audit_row_broadcasts_the_task_when_there_is_one() -> None:
    """D10: an incident's audit row records what it was anchored against — which is why
    `reservation_id` is in the allowlist — and "during which cleaning" is the same anchor.

    An identifier and never text, so rule 11's excepción 2 ("no se propaga") is untouched.
    """
    journal = _Journal()
    task = uuid.uuid4()

    await _report(journal, cleaning_task_id=task)

    entry = journal.only("audit")
    assert isinstance(entry, AuditLog)
    assert entry.changes == {
        "source": {"old": None, "new": "CLEANER"},
        "status": {"old": None, "new": "OPEN"},
        "cleaning_task_id": {"old": None, "new": str(task)},
    }


@pytest.mark.asyncio
async def test_the_audit_row_omits_the_key_entirely_when_there_is_no_task() -> None:
    """`ChangeSet.diff` always inserts the key, so calling it unconditionally would stamp
    `{"old": null, "new": null}` on every incident the portal, the pipeline and the seed
    create. `audit_logs` is append-only, so that null would be permanent."""
    journal = _Journal()

    await _report(journal, source=IncidentSource.GUEST)

    entry = journal.only("audit")
    assert isinstance(entry, AuditLog)
    assert "cleaning_task_id" not in entry.changes


@pytest.mark.asyncio
async def test_the_timeline_carries_the_task_id_only_when_there_is_one() -> None:
    """Identifiers only, and the key absent rather than present-and-null for the same reason
    the audit row omits it: `timeline_events` is append-only."""
    journal = _Journal()
    task = uuid.uuid4()

    incident = await _report(journal, cleaning_task_id=task)

    event = journal.only("timeline")
    assert isinstance(event, TimelineEvent)
    assert event.metadata == {
        "incident_id": str(incident.id),
        "source": IncidentSource.CLEANER.value,
        "cleaning_task_id": str(task),
    }
    # And still nothing of what was typed.
    assert TITLE not in str(event.metadata)
    assert DESCRIPTION not in str(event.metadata)


@pytest.mark.asyncio
async def test_the_timeline_omits_the_key_when_the_incident_has_no_cleaning() -> None:
    journal = _Journal()

    incident = await _report(journal, source=IncidentSource.GUEST)

    event = journal.only("timeline")
    assert isinstance(event, TimelineEvent)
    assert event.metadata == {
        "incident_id": str(incident.id),
        "source": IncidentSource.GUEST.value,
    }
