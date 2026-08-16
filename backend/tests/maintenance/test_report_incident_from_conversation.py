"""`ReportIncidentFromConversationUseCase` — `messaging`'s incident port, implemented here.

`messaging-ai` R4.6 and design D12. A sibling of `test_report_guest_incident.py`, and the
tests that differ from it are the ones that matter: the actor is a **human**, which is why
that change needs no new exception to rule 9 of `steering/security.md`, and the incident is
**not classified**, which is what leaves it for the `classify_incidents` job of D2.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions as audit_actions
from app.maintenance.application.use_cases import ReportIncidentFromConversationUseCase
from app.maintenance.domain.entities import CONVERSATION_INCIDENT_TITLES
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.messaging.domain.enums import MessageIntent
from app.messaging.domain.templates import INCIDENT_TITLES
from app.timeline.domain.enums import TimelineActorType, TimelineEventType

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
PROPERTY = uuid.uuid4()
RESERVATION = uuid.uuid4()
ACTOR = uuid.uuid4()
IP = "203.0.113.10"

#: What the guest typed, carrying the rule-3 values the census worries about — so the
#: propagation tests below assert the absence of a real value rather than of an empty string.
GUEST_TEXT = "No puedo entrar. Mi DNI es 12345678Z y el codigo 4471 no funciona."


class FakeIncidentRepository:
    def __init__(self) -> None:
        self.rows: list = []

    async def add(self, tenant_id: uuid.UUID, incident) -> None:
        self.rows.append(incident)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.rows: list = []

    async def add(self, tenant_id: uuid.UUID, entry) -> None:
        self.rows.append(entry)


class FakeTimelineRepository:
    def __init__(self) -> None:
        self.rows: list = []

    async def add(self, tenant_id: uuid.UUID, event) -> None:
        self.rows.append(event)


class CountingUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class Harness:
    def __init__(self) -> None:
        self.incidents = FakeIncidentRepository()
        self.audit = FakeAuditRepository()
        self.timeline = FakeTimelineRepository()
        self.uow = CountingUnitOfWork()
        self.use_case = ReportIncidentFromConversationUseCase(
            incidents=self.incidents,
            audit=self.audit,
            timeline=self.timeline,
            uow=self.uow,
        )

    async def run(self, *, intent: MessageIntent = MessageIntent.ACCESS_PROBLEM, reservation_id=RESERVATION):
        return await self.use_case.report(
            tenant_id=TENANT,
            property_id=PROPERTY,
            reservation_id=reservation_id,
            title=INCIDENT_TITLES[intent],
            description=GUEST_TEXT,
            actor_user_id=ACTOR,
            ip=IP,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_the_incident_is_born_open_and_unclassified() -> None:
    """R4.6: "NEVER SHALL clasificarlo en la misma petición".

    `ai_classification` unset is precisely what `list_pending_classification` selects on
    (`maintenance` D3), so the job picks this incident up on its next tick — and would not if
    a low-confidence verdict had been written here.
    """
    harness = Harness()

    incident_id = await harness.run()

    incident = harness.incidents.rows[0]
    assert incident.id == incident_id
    assert incident.status is IncidentStatus.OPEN
    assert incident.ai_classification is None
    assert incident.ai_summary is None
    assert incident.source is IncidentSource.GUEST


@pytest.mark.asyncio
async def test_the_title_is_a_closed_constant_and_the_description_is_verbatim() -> None:
    """D13. The census is done by who writes the column: we compose the title, so it is a
    closed form; the description is the guest's own text, copied without composing anything."""
    harness = Harness()

    await harness.run(intent=MessageIntent.MAINTENANCE_ISSUE)

    incident = harness.incidents.rows[0]
    assert incident.title == INCIDENT_TITLES[MessageIntent.MAINTENANCE_ISSUE]
    assert incident.title in CONVERSATION_INCIDENT_TITLES
    assert incident.description == GUEST_TEXT


def test_the_mapping_and_the_vocabulary_cannot_drift_apart() -> None:
    """The two halves of D13 live in different modules **on purpose**, so something has to
    hold them together.

    `maintenance` owns `incidents.title` and therefore owns the closed set it admits
    (`CONVERSATION_INCIDENT_TITLES`); `messaging` owns the decision of which intent opens an
    incident and therefore the intent-to-title mapping (`INCIDENT_TITLES`). Neither imports
    the other — that cross-domain import is what the review of 2026-08-16 removed. This test
    is what replaces it: add a title to one side without the other and it fails here, at build
    time, instead of at `MaintenanceValidationError` in production.
    """
    assert set(INCIDENT_TITLES.values()) == CONVERSATION_INCIDENT_TITLES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title",
    [
        "Se ha roto la caldera y mi DNI es 12345678Z",
        "Maintenance issue",
        "",
        "maintenance issue reported in a guest conversation",
    ],
)
async def test_a_title_outside_the_closed_catalogue_is_refused(title: str) -> None:
    """`incidents.title` on this path is written by **us**, so rule 11 of
    `steering/security.md` requires a closed form — and "the one caller passes a constant" is
    the argument the security panel refused for `messages.content`. It is checked in code here
    too, so a second caller of the port cannot pass operator-typed or guest-derived text.
    """
    harness = Harness()

    with pytest.raises(MaintenanceValidationError):
        await harness.use_case.report(
            tenant_id=TENANT,
            property_id=PROPERTY,
            reservation_id=RESERVATION,
            title=title,
            description=GUEST_TEXT,
            actor_user_id=ACTOR,
            ip=IP,
            now=NOW,
        )

    assert harness.incidents.rows == []


@pytest.mark.asyncio
async def test_the_audit_row_names_the_human_at_the_keyboard() -> None:
    """**Why `messaging-ai` needs no new exception to rule 9.** The rule's fourth exception
    covers automatic classification with no actor, and invites the assumption that anything
    the AI touches is actorless. A guest's message arrives through the panel or the API with
    an authenticated user behind it, and that user is the actor."""
    harness = Harness()

    await harness.run()

    entry = harness.audit.rows[0]
    assert entry.actor_user_id == ACTOR
    assert entry.actor_ip == IP
    assert entry.action == audit_actions.INCIDENT_CREATED
    assert entry.entity_type == audit_actions.ENTITY_INCIDENT


@pytest.mark.asyncio
async def test_the_audit_row_carries_no_word_the_guest_typed() -> None:
    """`AUDITABLE_FIELDS["INCIDENT"]` names neither `title` nor `description`, and `ChangeSet`
    refuses a field outside it — so this cannot leak even by trying (R3.6)."""
    harness = Harness()

    await harness.run()

    rendered = str(harness.audit.rows[0].changes)
    assert "12345678Z" not in rendered
    assert "4471" not in rendered
    assert GUEST_TEXT not in rendered


@pytest.mark.asyncio
async def test_the_timeline_event_has_a_user_actor_and_a_constant_title() -> None:
    """`GUEST` was right for `ReportGuestIncidentUseCase`, where nobody was authenticated.
    Here somebody is, and `TimelineEventFactory` only accepts `actor_user_id` alongside
    `USER`, so the two cannot disagree about who was there."""
    harness = Harness()

    await harness.run()

    event = harness.timeline.rows[0]
    assert event.event_type is TimelineEventType.INCIDENT_CREATED
    assert event.actor_type is TimelineActorType.USER
    assert event.actor_user_id == ACTOR
    assert event.title == "Incident reported in a guest conversation"


@pytest.mark.asyncio
async def test_the_timeline_event_carries_no_word_the_guest_typed() -> None:
    """R3.6, on the other sink. `timeline_events` is append-only, so a leak here could never
    be redacted."""
    harness = Harness()

    await harness.run()

    event = harness.timeline.rows[0]
    assert "12345678Z" not in str(event.metadata)
    assert GUEST_TEXT not in str(event.metadata)
    assert event.description is None


@pytest.mark.asyncio
async def test_a_conversation_without_a_reservation_still_opens_an_incident() -> None:
    """`Conversation.reservation_id` is nullable and R5.6 says a missing reservation must not
    fail the processing, so the port takes it as optional and this path has to work."""
    harness = Harness()

    await harness.run(reservation_id=None)

    assert harness.incidents.rows[0].reservation_id is None


@pytest.mark.asyncio
async def test_it_never_ends_the_transaction_it_was_given() -> None:
    """D12: the wiring hands it a `CallerOwnedUnitOfWork`, whose `commit()` does nothing, so
    the single commit of R4.7 stays the messaging pipeline's.

    Asserted here with a counting double: this use case **does** call `commit()`, which is
    correct — what makes it harmless is which unit of work it is given, and that is
    `test_dependencies.py`'s assertion, not this file's.
    """
    harness = Harness()

    await harness.run()

    assert harness.uow.commits == 1
