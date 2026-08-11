"""`ReportGuestIncidentUseCase` (R5.1, R5.4, R6.1-R6.4; design D15, D12, D13).

Unit tests with in-memory fakes of the three ports, as `steering/testing.md` prescribes for
`application/`: what is under test is the orchestration — which rows are written, in which
order, and what they carry — and a real database would only make that harder to see. The row's
shape against the actual DDL is `tests/maintenance/test_repositories.py`.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain.entities import AuditLog
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.maintenance.application.use_cases import ReportGuestIncidentUseCase
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity, IncidentSource, IncidentStatus
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType

NOW = datetime(2026, 9, 2, 10, 30, tzinfo=UTC)
IP = "203.0.113.7"
TITLE = "The boiler makes a loud noise"
DESCRIPTION = "It started last night and wakes us up."
TENANT_ID = uuid.uuid4()
PROPERTY_ID = uuid.uuid4()
RESERVATION_ID = uuid.uuid4()


class _Journal:
    """One list for every write, so the *order* of the operation is observable.

    R6.2 is an ordering requirement — the audit row before the answer — and three separate
    fakes each holding their own list could not tell a passing implementation from one that
    audits last.
    """

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


def _use_case(journal: _Journal) -> ReportGuestIncidentUseCase:
    return ReportGuestIncidentUseCase(
        incidents=_FakeIncidents(journal),
        audit=_FakeAudit(journal),
        timeline=_FakeTimeline(journal),
        uow=_RecordingUnitOfWork(journal),
    )


async def _report(
    journal: _Journal,
    *,
    token_hash: str,
    title: str = TITLE,
    description: str = DESCRIPTION,
    ip: str | None = IP,
) -> Incident:
    return await _use_case(journal).execute(
        tenant_id=TENANT_ID,
        property_id=PROPERTY_ID,
        reservation_id=RESERVATION_ID,
        reporter_token_hash=token_hash,
        title=title,
        description=description,
        ip=ip,
        now=NOW,
    )


def _audit_row(journal: _Journal) -> AuditLog:
    entry = journal.only("audit")
    assert isinstance(entry, AuditLog)
    return entry


def _timeline_row(journal: _Journal) -> TimelineEvent:
    event = journal.only("timeline")
    assert isinstance(event, TimelineEvent)
    return event


@pytest.mark.asyncio
async def test_it_creates_the_incident_from_the_stay_the_token_resolved() -> None:
    journal = _Journal()
    digest = hash_guest_token(generate_guest_token())

    incident = await _report(journal, token_hash=digest)

    assert incident.source is IncidentSource.GUEST
    assert incident.status is IncidentStatus.OPEN
    assert incident.tenant_id == TENANT_ID
    assert incident.property_id == PROPERTY_ID
    assert incident.reservation_id == RESERVATION_ID
    assert incident.reported_by_guest_token == digest
    assert incident.reported_by_user_id is None
    assert incident.title == TITLE
    assert incident.description == DESCRIPTION
    assert journal.only("incident") is incident


@pytest.mark.asyncio
async def test_it_leaves_the_classification_flows_fields_alone() -> None:
    """R5.4: the four fields `maintenance` owns are untouched, so the row is ordinary."""
    journal = _Journal()

    incident = await _report(journal, token_hash=hash_guest_token("h"))

    assert incident.category is IncidentCategory.OTHER
    assert incident.severity is IncidentSeverity.MEDIUM
    assert incident.ai_summary is None
    assert incident.ai_classification is None
    assert incident.assigned_technician_id is None
    assert incident.owner_approval_required is False


@pytest.mark.asyncio
async def test_the_audit_row_is_written_before_the_commit_that_makes_it_visible() -> None:
    """R6.2 — "antes de producir la respuesta", which for a write means before the commit.

    The whole sequence is asserted rather than just the pair: the incident needs an id before
    it can be audited, and the timeline entry is part of the same transaction, so a
    reordering that moved any of them past the commit would leave an incident nobody can
    attribute.
    """
    journal = _Journal()

    await _report(journal, token_hash=hash_guest_token("h"))

    assert journal.kinds() == ["incident", "audit", "timeline", "commit"]


@pytest.mark.asyncio
async def test_the_audit_row_names_the_bearer_by_digest_and_the_structural_fields_only() -> None:
    journal = _Journal()
    digest = hash_guest_token(generate_guest_token())

    incident = await _report(journal, token_hash=digest)

    entry = _audit_row(journal)
    assert entry.action == "INCIDENT_CREATED"
    assert entry.entity_type == "INCIDENT"
    assert entry.entity_id == incident.id
    assert entry.actor_guest_token_hash == digest
    assert entry.actor_user_id is None
    assert entry.actor_ip == IP
    assert entry.changes == {
        "source": {"old": None, "new": "GUEST"},
        "status": {"old": None, "new": "OPEN"},
        "reservation_id": {"old": None, "new": str(RESERVATION_ID)},
    }


@pytest.mark.asyncio
async def test_the_timeline_entry_is_the_guests_milestone_with_no_user_to_name() -> None:
    """R6.3, D12: `INCIDENT_CREATED` already exists, with `GUEST` as the actor."""
    journal = _Journal()

    incident = await _report(journal, token_hash=hash_guest_token("h"))

    event = _timeline_row(journal)
    assert event.event_type is TimelineEventType.INCIDENT_CREATED
    assert event.actor_type is TimelineActorType.GUEST
    assert event.actor_user_id is None
    assert event.property_id == PROPERTY_ID
    assert event.reservation_id == RESERVATION_ID
    assert event.created_at == NOW
    assert event.metadata == {
        "incident_id": str(incident.id),
        "reservation_id": str(RESERVATION_ID),
    }


@pytest.mark.asyncio
async def test_neither_the_token_nor_what_the_guest_typed_reaches_audit_or_timeline() -> None:
    """R6.4 and rule 11, checked over the whole serialised row rather than field by field.

    The cleartext token is the obvious half. The other half is the free text: `title` and
    `description` are typed by an anonymous stranger, and both `audit_logs.changes` and
    `timeline_events` are append-only, so anything that lands there can never be redacted.
    A field-by-field assertion would keep passing if a future change added a fourth key; this
    searches everything that gets persisted.

    The title and description used here are made unmistakable, so a substring match cannot
    pass by luck.
    """
    journal = _Journal()
    token = generate_guest_token()
    document_number = "12345678Z"
    title = f"boiler {document_number} noise"
    description = f"my document is {document_number} and the token is {token}"

    await _report(
        journal, token_hash=hash_guest_token(token), title=title, description=description
    )

    entry = _audit_row(journal)
    event = _timeline_row(journal)
    audited = json.dumps(entry.changes)
    recorded = json.dumps(
        {
            "title": event.title,
            "description": event.description,
            "metadata": event.metadata,
        }
    )

    for haystack in (audited, recorded):
        assert token not in haystack
        assert document_number not in haystack
        assert title not in haystack
        assert description not in haystack
    # The digest is the actor of the audit row, and it is the ONLY place the credential is
    # referenced at all — the timeline entry names no actor beyond `GUEST`.
    assert entry.actor_guest_token_hash == hash_guest_token(token)
    assert hash_guest_token(token) not in recorded


@pytest.mark.asyncio
async def test_a_request_with_no_client_ip_still_audits() -> None:
    """`actor_ip` is nullable, and a proxy that hides the address is not a reason to skip the
    row: rule 9 asks for the trail, and the digest is what identifies the actor."""
    journal = _Journal()

    await _report(journal, token_hash=hash_guest_token("h"), ip=None)

    entry = _audit_row(journal)
    assert entry.actor_ip is None
    assert entry.actor_guest_token_hash == hash_guest_token("h")


@pytest.mark.asyncio
async def test_two_reports_are_two_incidents() -> None:
    """D13, stated rather than hidden: the incident path is deliberately not idempotent.

    What bounds a retry is the per-token rate limit of D6, not a uniqueness rule here. Pinned
    so that a future change adding deduplication has to change a test that says why.
    """
    journal = _Journal()
    digest = hash_guest_token("h")

    first = await _report(journal, token_hash=digest)
    second = await _report(journal, token_hash=digest)

    assert first.id != second.id
    assert journal.kinds().count("incident") == 2
