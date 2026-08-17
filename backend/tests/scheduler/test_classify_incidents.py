"""The classification job (`maintenance` R1.2, R1.6; design D2, D3, D6).

Fixtures are imported from `tests/maintenance/conftest.py` rather than re-seeded — the same
arrangement `tests/cleaning/conftest.py` uses over `tests/auth` — because the job's subject
is a `maintenance` incident and the wiring it needs is the wiring that module already
declares.

What is worth testing here and not in `tests/maintenance` is the **candidate rule** of D3,
because it is what makes the job terminate: a verdict of "I am not sure" must not be asked
for again, while a failure must.
"""

import uuid

import pytest
from sqlalchemy import select

from app.audit.domain import actions as audit_actions
from app.audit.infrastructure.models import AuditLogModel
from app.maintenance.application.use_cases import ClassifyPendingIncidentsUseCase
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.scheduler.schedule import CADENCES, beat_schedule
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.maintenance.conftest import (  # noqa: F401
    NOW,
    flow,
    make_incident,
    world,
)

pytestmark = pytest.mark.asyncio

LATER = NOW.replace(hour=11)

WATER_FAULT = "Hay una fuga de agua y sale agua por el suelo."
UNRECOGNISED = "Quería preguntar una cosa sobre la estancia."


def job(flow, batch_size: int = 50) -> ClassifyPendingIncidentsUseCase:
    return ClassifyPendingIncidentsUseCase(
        reader=flow.reader, classify=flow.classify, batch_size=batch_size
    )


async def test_the_job_is_on_the_calendar() -> None:
    """R1.2 asks for the port to be invoked "when an incident is `OPEN`", not "when somebody
    asks" — so the job has to be scheduled, not merely callable."""
    assert "classify_incidents" in CADENCES
    assert "classify_incidents" in {
        entry["task"] for entry in beat_schedule().values()
    }


async def test_it_classifies_what_is_pending(flow, world, db_session) -> None:
    first = await make_incident(db_session, world, description=WATER_FAULT)
    second = await make_incident(db_session, world, description=WATER_FAULT)

    report = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert report.considered == 2
    assert report.classified == 2
    db_session.expunge_all()
    for incident_id in (first.id, second.id):
        stored = await db_session.get(IncidentModel, incident_id)
        assert stored.status is IncidentStatus.CLASSIFIED


async def test_it_does_not_retry_a_low_confidence_verdict(flow, world, db_session) -> None:
    """D3: the candidate rule is `OPEN` **and** `ai_classification IS NULL`.

    Without the second half a deterministic adapter would be asked the same question every
    tick and answer the same way for ever — the job would spin, and with a real provider
    behind the port it would spin at a price.
    """
    await make_incident(
        db_session, world, title="Consulta", description=UNRECOGNISED
    )

    first = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)
    second = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert (first.considered, first.low_confidence) == (1, 1)
    assert second.considered == 0


async def test_it_does_retry_one_the_adapter_failed_on(flow, world, db_session) -> None:
    """R1.6, and the other half of D3: a failure writes nothing, so the incident is still a
    candidate on the next tick."""

    class BrokenClassifier:
        async def classify(self, *, title: str, description: str):
            raise RuntimeError("the provider is down")

    incident = await make_incident(db_session, world, description=WATER_FAULT)
    flow.classify._classifier = BrokenClassifier()

    failed = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert (failed.considered, failed.failed) == (1, 1)

    flow.classify._classifier = flow.classifier
    recovered = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert (recovered.considered, recovered.classified) == (1, 1)
    db_session.expunge_all()
    assert (await db_session.get(IncidentModel, incident.id)).status is (
        IncidentStatus.CLASSIFIED
    )


@pytest.mark.parametrize(
    "closed", [IncidentStatus.CANCELLED, IncidentStatus.RESOLVED]
)
async def test_a_closed_incident_that_was_never_classified_is_not_a_candidate(
    flow, world, db_session, closed: IncidentStatus
) -> None:
    """The **other** half of D3's rule, and it had no test until the QA panel of sections
    7-8 showed what that costs.

    The case is reachable: a manager cancels a guest-reported incident before the job ever
    looks at it, so it is terminal with `ai_classification` still `NULL`. Dropping the
    `status = OPEN` half of the query leaves every other test in this file green — and the
    job then picks the incident up and dies with an uncaught `IncidentAlreadyClosedError`
    from `Incident.classify`, which aborts the whole tenant's tick, not just that row.
    """
    await make_incident(db_session, world, description=WATER_FAULT, status=closed)

    report = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert report.considered == 0


async def test_the_batch_is_bounded(flow, world, db_session) -> None:
    """A tenant whose classifier was down all night must not turn one tick into an
    unbounded run."""
    for _ in range(3):
        await make_incident(db_session, world, description=WATER_FAULT)

    report = await job(flow, batch_size=2).execute(tenant_id=world.tenant.id, now=LATER)

    assert report.considered == 2


async def test_the_job_audits_without_an_actor(flow, world, db_session) -> None:
    """D6 and rule 9 of `steering/security.md`: the command has no identity to record.

    The exemption is owed a named entry in that rule — the change's task 9.1b — and
    `_AuditWriter` refuses it for every other action of this module.
    """
    await make_incident(db_session, world, description=WATER_FAULT)

    await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    rows = await db_session.execute(
        select(AuditLogModel).where(
            AuditLogModel.action == audit_actions.INCIDENT_CLASSIFIED
        )
    )
    entry = rows.scalars().one()
    assert entry.actor_user_id is None
    assert entry.actor_ip is None


async def test_the_job_writes_its_timeline_event_as_ai(flow, world, db_session) -> None:
    """D10: `TimelineEventFactory` only admits `actor_user_id` alongside `USER`, so the row
    cannot claim a person who was not there — which is what R6.4 forbids."""
    await make_incident(db_session, world, description=WATER_FAULT)

    await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    rows = await db_session.execute(
        select(TimelineEventModel).where(
            TimelineEventModel.event_type == TimelineEventType.INCIDENT_CLASSIFIED
        )
    )
    event = rows.scalars().one()
    assert event.actor_type is TimelineActorType.AI
    assert event.actor_user_id is None


async def test_an_incident_of_another_tenant_is_not_a_candidate(
    flow, world, db_session
) -> None:
    """The job runs per tenant, and the loop is what would leak if the query forgot."""
    from app.tenants.infrastructure.models import TenantModel

    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()
    await make_incident(db_session, world, description=WATER_FAULT)

    report = await job(flow).execute(tenant_id=neighbour.id, now=LATER)

    assert report.considered == 0


async def test_the_report_adds_up(flow, world, db_session) -> None:
    await make_incident(db_session, world, description=WATER_FAULT)
    await make_incident(db_session, world, title="Consulta", description=UNRECOGNISED)

    report = await job(flow).execute(tenant_id=world.tenant.id, now=LATER)

    assert report.considered == report.classified + report.low_confidence + report.failed
    assert report.tenant_id == str(world.tenant.id)
    assert uuid.UUID(report.tenant_id) == world.tenant.id
