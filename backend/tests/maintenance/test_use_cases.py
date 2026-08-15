"""The incident flow, end to end over the database (R1-R6; design D5-D13).

What these tests are for, beyond the happy paths: D7 names one functional risk above the
others — a context missing any of its three collections gives the property a **plausible and
wrong** operational state, and nothing fails. `test_resolution_lands_where_the_context_says`
is the mitigation, and it is driven from `ResolveIncidentUseCase` rather than from the
resolver, because the bug being guarded against is in the assembling, not in the deciding.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.audit.domain import actions as audit_actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.application.use_cases import IncidentActor
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentNotFoundError,
    InvalidIncidentTransitionError,
    InvalidTechnicianError,
    MaintenanceValidationError,
    OwnerApprovalNotFoundError,
)
from app.maintenance.domain.repositories import IncidentFilters
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.notifications.domain.enums import NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.infrastructure.models import PropertyModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.maintenance.conftest import (
    NOW,
    make_approval,
    make_cleaning_task,
    make_incident,
    make_reservation,
)

pytestmark = pytest.mark.asyncio

LATER = NOW + timedelta(hours=1)

# A description the deterministic classifier reads as a WATER fault, i.e. `HIGH` — the
# severity that fires `INCIDENT_HIGH` and moves the property.
WATER_FAULT = "Hay una fuga de agua y sale agua por el suelo."
# One it does not recognise, so the verdict lands below the threshold (R1.3).
UNRECOGNISED = "Quería preguntar una cosa sobre la estancia."


def manager(world) -> IncidentActor:
    return IncidentActor(user_id=world.manager.id, role=UserRole.PROPERTY_MANAGER, ip="10.0.0.1")


def owner(world) -> IncidentActor:
    return IncidentActor(user_id=world.owner.id, role=UserRole.TENANT_OWNER)


def technician(world) -> IncidentActor:
    return IncidentActor(user_id=world.technician.id, role=UserRole.TECHNICIAN)


def other_technician(world) -> IncidentActor:
    return IncidentActor(user_id=world.other_technician.id, role=UserRole.TECHNICIAN)


async def state_of(session, property_id: uuid.UUID) -> PropertyOperationalState:
    session.expunge_all()
    prop = await session.get(PropertyModel, property_id)
    return prop.current_operational_state


async def audit_actions_for(session, entity_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(AuditLogModel.action).where(AuditLogModel.entity_id == entity_id)
    )
    return sorted(rows.scalars())


async def timeline_types_for(session, tenant_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(TimelineEventModel.event_type).where(
            TimelineEventModel.tenant_id == tenant_id
        )
    )
    return sorted(event.value for event in rows.scalars())


# --- IncidentActor (task 6.1) -----------------------------------------------------------


async def test_only_a_technician_is_restricted_to_their_own_incidents() -> None:
    """R5.3, D13 — derived from the role, never accepted from the request."""
    user_id = uuid.uuid4()

    assert (
        IncidentActor(user_id=user_id, role=UserRole.TECHNICIAN).restrict_to_technician_id
        == user_id
    )
    for role in (UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER, UserRole.CLEANER):
        assert IncidentActor(user_id=user_id, role=role).restrict_to_technician_id is None


async def test_no_action_but_the_job_may_be_audited_without_an_actor(flow) -> None:
    """R6.4, and the condition the security panel of section 4 attached to task 9.1b.

    `AuditLogFactory` accepts `actor_user_id=None` for every action, so a manual operation
    whose use case lost its actor would write a row indistinguishable from the job's, in an
    append-only table. This writer refuses it.
    """
    from app.audit.domain.value_objects import ChangeSet

    writer = flow.triage._audit

    with pytest.raises(MaintenanceValidationError):
        await writer.record(
            tenant_id=uuid.uuid4(),
            action=audit_actions.INCIDENT_ASSIGNED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=uuid.uuid4(),
            actor=None,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT),
            now=NOW,
        )


# --- Classification (task 6.4; R1.2, R1.3, R1.6) ----------------------------------------


async def test_classification_applies_the_verdict_and_moves_the_property(
    flow, world, db_session
) -> None:
    incident = await make_incident(db_session, world, description=WATER_FAULT)

    result = await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    assert result.status is IncidentStatus.CLASSIFIED
    assert result.severity is IncidentSeverity.HIGH
    assert result.category is IncidentCategory.WATER
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.MAINTENANCE_REQUIRED
    )


async def test_low_confidence_leaves_the_incident_open_and_the_property_alone(
    flow, world, db_session
) -> None:
    """R1.3 + D3: still `OPEN`, but no longer *unseen* — which is what stops the job of D2
    from asking the same question every tick."""
    incident = await make_incident(
        db_session, world, title="Consulta", description=UNRECOGNISED
    )

    result = await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    assert result.status is IncidentStatus.OPEN
    assert result.ai_classification is not None
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.VACANT_READY
    )


async def test_a_failing_adapter_leaves_the_incident_open_and_unclassified(
    flow, world, db_session
) -> None:
    """R1.6 — and `ai_classification` stays `NULL`, so the job retries it (D3)."""

    class BrokenClassifier:
        async def classify(self, *, title: str, description: str):
            raise RuntimeError("the provider is down")

    flow.classify._classifier = BrokenClassifier()
    incident = await make_incident(db_session, world, description=WATER_FAULT)

    result = await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    assert result.status is IncidentStatus.OPEN
    assert result.ai_classification is None
    db_session.expunge_all()
    stored = await db_session.get(IncidentModel, incident.id)
    assert stored.status is IncidentStatus.OPEN
    assert stored.ai_classification is None


async def test_the_job_audits_without_an_actor_and_the_timeline_says_ai(
    flow, world, db_session
) -> None:
    """D6 and D10: `actor_user_id`/`actor_ip` at `NULL`, timeline actor `AI`."""
    incident = await make_incident(db_session, world, description=WATER_FAULT)

    await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    rows = await db_session.execute(
        select(AuditLogModel).where(
            AuditLogModel.action == audit_actions.INCIDENT_CLASSIFIED
        )
    )
    entry = rows.scalars().one()
    assert entry.actor_user_id is None
    assert entry.actor_ip is None

    events = await db_session.execute(
        select(TimelineEventModel).where(
            TimelineEventModel.event_type == TimelineEventType.INCIDENT_CLASSIFIED
        )
    )
    event = events.scalars().one()
    assert event.actor_type is TimelineActorType.AI
    assert event.actor_user_id is None


async def test_a_manual_classification_names_its_actor(flow, world, db_session) -> None:
    incident = await make_incident(db_session, world, description=WATER_FAULT)

    await flow.classify.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
    )

    rows = await db_session.execute(
        select(AuditLogModel).where(
            AuditLogModel.action == audit_actions.INCIDENT_CLASSIFIED
        )
    )
    assert rows.scalars().one().actor_user_id == world.manager.id


# --- D8's tolerance (task 6.3) ----------------------------------------------------------


async def test_a_refused_trigger_is_logged_and_tolerated(flow, world, db_session) -> None:
    """D8: a `HIGH` incident on a property in `BLOCKED_BY_OWNER` classifies anyway.

    The matrix has real gaps and three of them are correct — a human decided the property is
    blocked. Failing the classification would refuse to record a fault because of a state
    nobody asked about; the incident is the record and the operational state is a projection.
    """
    world.property.current_operational_state = PropertyOperationalState.BLOCKED_BY_OWNER
    await db_session.flush()
    incident = await make_incident(db_session, world, description=WATER_FAULT)

    result = await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    assert result.status is IncidentStatus.CLASSIFIED
    assert result.severity is IncidentSeverity.HIGH
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.BLOCKED_BY_OWNER
    )


# --- Triage and the budget gate (task 6.5; R1.4, R2.1) ----------------------------------


async def test_triage_below_the_threshold_creates_nothing(flow, world, db_session) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    result = await flow.triage.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
        severity=IncidentSeverity.MEDIUM,
        estimated_cost=Decimal("40.00"),
    )

    assert result.status is IncidentStatus.CLASSIFIED
    assert result.owner_approval_required is False
    approvals = await db_session.scalar(select(func.count()).select_from(OwnerApprovalModel))
    assert approvals == 0


async def test_triage_above_the_threshold_opens_the_budget_gate(
    flow, world, db_session
) -> None:
    """R2.1, R2.3 and D11's first gate, with its notification."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    result = await flow.triage.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
        estimated_cost=Decimal("450.00"),
    )

    assert result.status is IncidentStatus.AWAITING_OWNER_APPROVAL
    assert result.owner_approval_required is True

    approvals = await db_session.execute(select(OwnerApprovalModel))
    approval = approvals.scalars().one()
    assert approval.related_type is OwnerApprovalRelatedType.INCIDENT
    assert approval.related_id == incident.id
    assert approval.amount == Decimal("450.00")
    assert approval.status is OwnerApprovalStatus.PENDING

    logs = await db_session.execute(select(NotificationLogModel))
    log = logs.scalars().one()
    assert log.notification_type == NotificationType.OWNER_APPROVAL_REQUIRED.value
    assert log.recipient_user_id == world.owner.id
    assert log.sla_deadline_at is None


async def test_the_approval_reason_carries_no_reported_text(flow, world, db_session) -> None:
    """D4: `owner_approvals.reason` is written by our code — constant plus identifiers."""
    leaked = "mi DNI es 12345678Z"
    incident = await make_incident(
        db_session, world, status=IncidentStatus.CLASSIFIED, description=leaked
    )

    await flow.triage.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
        estimated_cost=Decimal("450.00"),
    )

    approvals = await db_session.execute(select(OwnerApprovalModel))
    assert leaked not in approvals.scalars().one().reason


async def test_triage_is_refused_on_a_closed_incident(flow, world, db_session) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.RESOLVED)

    with pytest.raises(IncidentAlreadyClosedError):
        await flow.triage.execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            actor=manager(world),
            now=LATER,
            severity=IncidentSeverity.LOW,
        )


# --- Answering the approval (task 6.6; R2.4, R2.5, R2.6) --------------------------------


async def test_approving_the_budget_returns_the_incident_to_the_assignment_flow(
    flow, world, db_session
) -> None:
    """D11: `related_type = INCIDENT` resumes at `CLASSIFIED`."""
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    result = await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.APPROVED,
        response_notes="Adelante.",
        actor=owner(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.CLASSIFIED
    assert result.approved_cost == Decimal("450.00")
    assert TimelineEventType.OWNER_APPROVED_EXPENSE.value in await timeline_types_for(
        db_session, world.tenant.id
    )


async def test_approving_the_real_cost_returns_the_incident_to_in_progress(
    flow, world, db_session
) -> None:
    """D11: `related_type = MAINTENANCE_COST` resumes at `IN_PROGRESS`, and the technician
    retries the close — the system does not close a job the technician did not close."""
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(
        db_session,
        world,
        incident.id,
        related_type=OwnerApprovalRelatedType.MAINTENANCE_COST,
    )

    result = await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.APPROVED,
        response_notes=None,
        actor=owner(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.IN_PROGRESS
    assert result.resolved_at is None


@pytest.mark.parametrize(
    "related_type",
    [OwnerApprovalRelatedType.INCIDENT, OwnerApprovalRelatedType.MAINTENANCE_COST],
)
async def test_rejecting_cancels_the_incident_and_frees_the_property(
    flow, world, db_session, related_type: OwnerApprovalRelatedType
) -> None:
    """R2.5 and D9 together: without D9's widened precondition the property would stay in
    `CRITICAL_INCIDENT` with no trigger able to reach it."""
    world.property.current_operational_state = PropertyOperationalState.CRITICAL_INCIDENT
    await db_session.flush()
    incident = await make_incident(
        db_session,
        world,
        status=IncidentStatus.AWAITING_OWNER_APPROVAL,
        severity=IncidentSeverity.CRITICAL,
    )
    approval = await make_approval(
        db_session, world, incident.id, related_type=related_type
    )

    result = await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.REJECTED,
        response_notes="Demasiado caro.",
        actor=owner(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.CANCELLED
    assert result.approved_cost is None
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.VACANT_READY
    )


async def test_only_the_owner_may_answer(flow, world, db_session) -> None:
    """R2.6, first of its three refusals."""
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    with pytest.raises(MaintenanceValidationError):
        await flow.respond.execute(
            tenant_id=world.tenant.id,
            approval_id=approval.id,
            status=OwnerApprovalStatus.APPROVED,
            response_notes=None,
            actor=manager(world),
            now=LATER,
        )


async def test_an_approval_cannot_be_answered_twice(flow, world, db_session) -> None:
    """R2.6, second refusal — and it holds across two separate calls, not only in memory."""
    from app.maintenance.domain.exceptions import OwnerApprovalAlreadyAnsweredError

    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.APPROVED,
        response_notes=None,
        actor=owner(world),
        now=LATER,
    )
    db_session.expunge_all()

    with pytest.raises(OwnerApprovalAlreadyAnsweredError):
        await flow.respond.execute(
            tenant_id=world.tenant.id,
            approval_id=approval.id,
            status=OwnerApprovalStatus.REJECTED,
            response_notes=None,
            actor=owner(world),
            now=LATER + timedelta(hours=1),
        )


async def test_an_unknown_approval_is_not_found(flow, world) -> None:
    """R2.6, third refusal: an approval of another tenant reads as one that does not exist."""
    with pytest.raises(OwnerApprovalNotFoundError):
        await flow.respond.execute(
            tenant_id=world.tenant.id,
            approval_id=uuid.uuid4(),
            status=OwnerApprovalStatus.APPROVED,
            response_notes=None,
            actor=owner(world),
            now=LATER,
        )


# --- Assignment and SLA (task 6.7; R3.1, R3.4, R3.5) ------------------------------------


async def test_assignment_opens_the_sla_deadline_for_the_severity(
    flow, world, db_session
) -> None:
    incident = await make_incident(
        db_session,
        world,
        status=IncidentStatus.CLASSIFIED,
        severity=IncidentSeverity.CRITICAL,
    )

    result = await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.technician.id,
        actor=manager(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.ASSIGNED
    assert result.assigned_technician_id == world.technician.id

    logs = await db_session.execute(select(NotificationLogModel))
    log = logs.scalars().one()
    assert log.notification_type == NotificationType.TECHNICIAN_ASSIGNED.value
    assert log.recipient_user_id == world.technician.id
    # `sla_critical_minutes` default is 5 (PRD §11).
    assert log.sla_deadline_at == LATER + timedelta(minutes=5)


async def test_reassignment_cancels_the_previous_deadline(flow, world, db_session) -> None:
    """R3.5 — otherwise the first technician's silence escalates work that is no longer
    theirs."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.technician.id,
        actor=manager(world),
        now=LATER,
    )

    await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.other_technician.id,
        actor=manager(world),
        now=LATER + timedelta(minutes=10),
    )

    logs = await db_session.execute(
        select(NotificationLogModel).order_by(NotificationLogModel.created_at)
    )
    first, second = logs.scalars().all()
    assert first.sla_deadline_at is None
    assert second.sla_deadline_at is not None
    assert second.recipient_user_id == world.other_technician.id


@pytest.mark.parametrize("role", ["CLEANER", "PROPERTY_MANAGER"])
async def test_only_a_technician_may_be_assigned(flow, world, db_session, role: str) -> None:
    """R3.4, first refusal."""
    from tests.maintenance.conftest import _user

    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    wrong = await _user(db_session, world.tenant, role)

    with pytest.raises(InvalidTechnicianError):
        await flow.assign.execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            technician_id=wrong.id,
            actor=manager(world),
            now=LATER,
        )


async def test_a_technician_of_another_tenant_cannot_be_assigned(
    flow, world, db_session
) -> None:
    """R3.4, second refusal: `incidents.assigned_technician_id` is a plain FK, so the
    database would accept the row — the tenant-scoped lookup is what refuses it."""
    from app.tenants.infrastructure.models import TenantModel
    from tests.maintenance.conftest import _user

    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()
    theirs = await _user(db_session, neighbour, "TECHNICIAN")
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    with pytest.raises(InvalidTechnicianError):
        await flow.assign.execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            technician_id=theirs.id,
            actor=manager(world),
            now=LATER,
        )


# --- The technician's cycle (task 6.8; R4.1, R4.5) --------------------------------------


async def _assigned(flow, world, db_session, **kwargs) -> IncidentModel:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED, **kwargs)
    await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.technician.id,
        actor=manager(world),
        now=LATER,
    )
    return incident


async def test_the_technician_walks_the_whole_cycle(flow, world, db_session) -> None:
    incident = await _assigned(flow, world, db_session)
    actor = technician(world)
    common = {"tenant_id": world.tenant.id, "incident_id": incident.id, "actor": actor}

    assert (await flow.accept.execute(**common, now=LATER)).status is IncidentStatus.ACCEPTED
    assert (await flow.start.execute(**common, now=LATER)).status is IncidentStatus.IN_PROGRESS
    assert (
        await flow.wait_for_parts.execute(**common, now=LATER)
    ).status is IncidentStatus.WAITING_EXTERNAL_PARTS
    assert (
        await flow.resume_work.execute(**common, now=LATER)
    ).status is IncidentStatus.IN_PROGRESS
    resolved = await flow.resolve.execute(
        **common, final_cost=Decimal("50.00"), now=LATER
    )
    assert resolved.status is IncidentStatus.RESOLVED


async def test_accepting_cancels_the_pending_deadline(flow, world, db_session) -> None:
    """R3.3 — otherwise `check_sla_breaches` escalates work accepted in seconds."""
    incident = await _assigned(flow, world, db_session)

    await flow.accept.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=technician(world),
        now=LATER,
    )

    logs = await db_session.execute(select(NotificationLogModel))
    assert logs.scalars().one().sla_deadline_at is None


async def test_waiting_for_parts_leaves_no_timeline_event(flow, world, db_session) -> None:
    """D10, decided rather than missing: no `TimelineEventType` describes waiting for a
    part, and the milestone is already in the incident's own `status`."""
    incident = await _assigned(flow, world, db_session)
    common = {
        "tenant_id": world.tenant.id,
        "incident_id": incident.id,
        "actor": technician(world),
        "now": LATER,
    }
    await flow.accept.execute(**common)
    await flow.start.execute(**common)
    before = await timeline_types_for(db_session, world.tenant.id)

    await flow.wait_for_parts.execute(**common)

    assert await timeline_types_for(db_session, world.tenant.id) == before
    assert audit_actions.INCIDENT_WAITING_PARTS in await audit_actions_for(
        db_session, incident.id
    )


async def test_a_technician_who_is_not_the_assignee_gets_a_not_found(
    flow, world, db_session
) -> None:
    """R4.5 and R5.3: the same error, with the same message, as an incident that does not
    exist — a 403 would turn the endpoint into a probe."""
    incident = await _assigned(flow, world, db_session)

    with pytest.raises(IncidentNotFoundError):
        await flow.accept.execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            actor=other_technician(world),
            now=LATER,
        )


async def test_a_manager_may_drive_the_cycle_to_unblock_it(flow, world, db_session) -> None:
    """R4.5: "un `PROPERTY_MANAGER` sí puede, para desatascar"."""
    incident = await _assigned(flow, world, db_session)

    result = await flow.accept.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.ACCEPTED


async def test_a_step_out_of_order_is_refused(flow, world, db_session) -> None:
    """R4.4, at the use-case level: the entity's table is the authority and nothing here
    second-guesses it."""
    incident = await _assigned(flow, world, db_session)

    with pytest.raises(InvalidIncidentTransitionError):
        await flow.start.execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            actor=technician(world),
            now=LATER,
        )


# --- Resolution and the real-cost gate (task 6.9; R4.2, R4.3) ---------------------------


async def _in_progress(flow, world, db_session, **kwargs) -> IncidentModel:
    incident = await _assigned(flow, world, db_session, **kwargs)
    common = {
        "tenant_id": world.tenant.id,
        "incident_id": incident.id,
        "actor": technician(world),
        "now": LATER,
    }
    await flow.accept.execute(**common)
    await flow.start.execute(**common)
    return incident


async def test_a_clean_resolution_closes_the_incident(flow, world, db_session) -> None:
    incident = await _in_progress(flow, world, db_session)

    result = await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.RESOLVED
    assert result.final_cost == Decimal("60.00")
    assert result.resolved_at == LATER


async def test_a_cost_over_the_threshold_opens_the_second_gate(
    flow, world, db_session
) -> None:
    """R4.3 and D11: without this, estimating 90 EUR and spending 500 walks past the
    approval rule entirely."""
    incident = await _in_progress(flow, world, db_session)

    result = await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("500.00"),
        actor=technician(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.AWAITING_OWNER_APPROVAL
    assert result.final_cost == Decimal("500.00")
    assert result.resolved_at is None

    approvals = await db_session.execute(select(OwnerApprovalModel))
    approval = approvals.scalars().one()
    assert approval.related_type is OwnerApprovalRelatedType.MAINTENANCE_COST
    assert approval.amount == Decimal("500.00")


async def test_a_cost_covered_by_an_approval_resolves_without_a_second_gate(
    flow, world, db_session
) -> None:
    """D11: "cubierto por una aprobación aprobada" — the incident already carries the number
    the owner said yes to."""
    incident = await _in_progress(flow, world, db_session)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.approved_cost = Decimal("600.00")
    await db_session.flush()

    result = await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("500.00"),
        actor=technician(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.RESOLVED
    assert await db_session.scalar(select(func.count()).select_from(OwnerApprovalModel)) == 0


async def test_an_approval_that_does_not_stretch_opens_the_gate(
    flow, world, db_session
) -> None:
    incident = await _in_progress(flow, world, db_session)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.approved_cost = Decimal("400.00")
    await db_session.flush()

    result = await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("500.00"),
        actor=technician(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.AWAITING_OWNER_APPROVAL


# --- The five branches of the contextual resolver (task 6.10; D7) -----------------------


async def test_resolution_lands_where_the_context_says(flow, world, db_session) -> None:
    """D7's main risk, driven from the use case and not from the resolver.

    If `_fire_trigger` forgot any of the three collections the destination would still be a
    valid operational state — just the wrong one — and nothing would raise. Each branch below
    is therefore a different *context*, not a different call.
    """
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)
    await make_cleaning_task(db_session, world, CleaningTaskStatus.IN_PROGRESS)

    result = await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.RESOLVED
    # The branch the design singles out: without `cleaning_tasks` in the context this would
    # be `VACANT_READY`, which reads as "ready to let" for a flat that has not been cleaned.
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.CLEANING_IN_PROGRESS
    )


async def test_another_active_incident_keeps_the_property_where_it_is(
    flow, world, db_session
) -> None:
    """The first collection of D7: **all** the non-terminal incidents, not just this one."""
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)
    await make_incident(
        db_session,
        world,
        status=IncidentStatus.CLASSIFIED,
        severity=IncidentSeverity.CRITICAL,
    )

    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.CRITICAL_INCIDENT
    )


async def test_a_pending_cleaning_sends_the_property_to_awaiting_cleaning(
    flow, world, db_session
) -> None:
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)
    await make_cleaning_task(db_session, world, CleaningTaskStatus.CREATED)

    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.AWAITING_CLEANING
    )


async def test_a_stay_starting_today_sends_the_property_to_awaiting_checkin(
    flow, world, db_session
) -> None:
    """The second collection of D7: the reservations of the window."""
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)
    today = LATER.date()
    await make_reservation(
        db_session, world, check_in=today, check_out=today + timedelta(days=3)
    )

    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.AWAITING_CHECKIN
    )


async def test_a_future_stay_sends_the_property_to_ready_for_next_guest(
    flow, world, db_session
) -> None:
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)
    later_day = LATER.date() + timedelta(days=2)
    await make_reservation(
        db_session, world, check_in=later_day, check_out=later_day + timedelta(days=2)
    )

    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.READY_FOR_NEXT_GUEST
    )


async def test_nothing_pending_sends_the_property_back_to_vacant_ready(
    flow, world, db_session
) -> None:
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await _in_progress(flow, world, db_session)

    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.VACANT_READY
    )


# --- Cancellation and the reads (task 6.11; R4.4, R5.1, R5.3) ---------------------------


async def test_cancelling_closes_the_incident_and_recomposes_the_property(
    flow, world, db_session
) -> None:
    world.property.current_operational_state = PropertyOperationalState.MAINTENANCE_REQUIRED
    await db_session.flush()
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    result = await flow.cancel.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
    )

    assert result.status is IncidentStatus.CANCELLED
    assert await state_of(db_session, world.property.id) is (
        PropertyOperationalState.VACANT_READY
    )
    assert audit_actions.INCIDENT_CANCELLED in await audit_actions_for(
        db_session, incident.id
    )


async def test_a_technician_only_lists_their_own_incidents(flow, world, db_session) -> None:
    """R5.3, applied in the repository filter and not in a router."""
    mine = await _assigned(flow, world, db_session)
    await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    page = await flow.list.execute(
        tenant_id=world.tenant.id,
        actor=technician(world),
        filters=IncidentFilters(),
        page=1,
        per_page=20,
    )

    assert [incident.id for incident in page.items] == [mine.id]
    assert page.total == 1


async def test_a_technician_cannot_widen_the_filter_to_see_more(
    flow, world, db_session
) -> None:
    """The restriction overwrites whatever filter arrived, so a crafted query parameter
    cannot drop it."""
    mine = await _assigned(flow, world, db_session)
    await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    page = await flow.list.execute(
        tenant_id=world.tenant.id,
        actor=technician(world),
        filters=IncidentFilters(assigned_technician_id=world.other_technician.id),
        page=1,
        per_page=20,
    )

    assert [incident.id for incident in page.items] == [mine.id]


async def test_a_manager_lists_the_whole_tenant(flow, world, db_session) -> None:
    await _assigned(flow, world, db_session)
    await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    page = await flow.list.execute(
        tenant_id=world.tenant.id,
        actor=manager(world),
        filters=IncidentFilters(),
        page=1,
        per_page=20,
    )

    assert page.total == 2


async def test_reading_one_incident_obeys_the_same_restriction(
    flow, world, db_session
) -> None:
    mine = await _assigned(flow, world, db_session)
    theirs = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    assert (
        await flow.get.execute(
            tenant_id=world.tenant.id, incident_id=mine.id, actor=technician(world)
        )
    ).id == mine.id

    with pytest.raises(IncidentNotFoundError):
        await flow.get.execute(
            tenant_id=world.tenant.id, incident_id=theirs.id, actor=technician(world)
        )


async def test_an_unknown_incident_reads_the_same_as_one_that_is_not_yours(
    flow, world
) -> None:
    with pytest.raises(IncidentNotFoundError):
        await flow.get.execute(
            tenant_id=world.tenant.id, incident_id=uuid.uuid4(), actor=technician(world)
        )


# --- Tenant isolation at this layer (R5.4, R2.6, DoD §28.18) ----------------------------
#
# Against a **real** neighbour row, not a random uuid: an unknown id proves nothing about
# scoping, because a use case that dropped its `tenant_id` argument would still answer "not
# found" for an id nobody ever created. `db_session` is unmarked, so these can fail. Raised
# by the tenancy panel of section 6.


@pytest_asyncio.fixture
async def neighbour(db_session):
    from app.properties.infrastructure.models import PropertyModel
    from app.tenants.infrastructure.models import TenantModel
    from tests.maintenance.conftest import World, _user

    tenant = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Theirs",
        internal_code="THEIRS",
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    db_session.add(prop)
    await db_session.flush()
    return World(
        tenant,
        prop,
        await _user(db_session, tenant, "TENANT_OWNER"),
        await _user(db_session, tenant, "PROPERTY_MANAGER"),
        await _user(db_session, tenant, "TECHNICIAN"),
        await _user(db_session, tenant, "TECHNICIAN"),
    )


async def test_reading_a_neighbours_incident_is_a_not_found(
    flow, world, neighbour, db_session
) -> None:
    theirs = await make_incident(db_session, neighbour, status=IncidentStatus.CLASSIFIED)

    with pytest.raises(IncidentNotFoundError):
        await flow.get.execute(
            tenant_id=world.tenant.id, incident_id=theirs.id, actor=manager(world)
        )


async def test_a_neighbours_incident_is_not_in_the_listing(
    flow, world, neighbour, db_session
) -> None:
    mine = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await make_incident(db_session, neighbour, status=IncidentStatus.CLASSIFIED)

    page = await flow.list.execute(
        tenant_id=world.tenant.id,
        actor=manager(world),
        filters=IncidentFilters(),
        page=1,
        per_page=20,
    )

    assert [incident.id for incident in page.items] == [mine.id]
    assert page.total == 1


async def test_a_neighbours_approval_cannot_be_answered(
    flow, world, neighbour, db_session
) -> None:
    """R2.6: "ni responder una de otro tenant"."""
    theirs = await make_incident(
        db_session, neighbour, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    their_approval = await make_approval(db_session, neighbour, theirs.id)

    with pytest.raises(OwnerApprovalNotFoundError):
        await flow.respond.execute(
            tenant_id=world.tenant.id,
            approval_id=their_approval.id,
            status=OwnerApprovalStatus.APPROVED,
            response_notes=None,
            actor=owner(world),
            now=LATER,
        )


async def test_a_neighbours_incident_cannot_be_driven(
    flow, world, neighbour, db_session
) -> None:
    """Every mutating path goes through `_load_incident`, so one test per family is enough
    to show the tenant argument reaches the query — but the families differ, so both the
    manager path and the technician path are exercised."""
    theirs = await make_incident(db_session, neighbour, status=IncidentStatus.CLASSIFIED)

    with pytest.raises(IncidentNotFoundError):
        await flow.cancel.execute(
            tenant_id=world.tenant.id,
            incident_id=theirs.id,
            actor=manager(world),
            now=LATER,
        )

    with pytest.raises(IncidentNotFoundError):
        await flow.triage.execute(
            tenant_id=world.tenant.id,
            incident_id=theirs.id,
            actor=manager(world),
            now=LATER,
            severity=IncidentSeverity.LOW,
        )


# --- What the panel of section 6 changed (R2.1, R4.3, R6.4, D4, D6, D8) -----------------


async def test_the_threshold_rule_lives_in_the_entity(flow, world, db_session) -> None:
    """The architecture panel of section 6: `> threshold` was a bare comparison in two use
    cases, and it is a business rule (R2.1, R4.3), not a step of orchestration."""
    incident = (await make_incident(db_session, world)).id
    entity = await flow.incidents.get(world.tenant.id, incident)
    assert entity is not None

    assert entity.needs_owner_approval(Decimal("101.00"), Decimal("100.00")) is True
    assert entity.needs_owner_approval(Decimal("100.00"), Decimal("100.00")) is False
    assert entity.needs_owner_approval(None, Decimal("100.00")) is False

    entity.approved_cost = Decimal("500.00")
    assert entity.needs_owner_approval(Decimal("400.00"), Decimal("100.00")) is False


async def test_a_summary_that_echoes_the_report_is_dropped(
    flow, world, db_session
) -> None:
    """D4, enforced where the value is written rather than only where it is documented.

    Raised by the security panel of section 6: `IncidentClassification.summary` is an
    unconstrained `str`, so the contract held only because the one adapter honoured it.

    **This adapter declares its vocabulary from its own output, which is the one shape the
    type check cannot catch** — `summary in vocabulary` is trivially true when the set was
    built from the summary. It is not a contrived case: it is what a careless real adapter
    does when told "declare the set you drew from" and it drew from the model's reply. So
    this is the test that keeps `_non_echoing` honest as the second net, and the reason the
    census does not claim the type closes everything.
    """

    class EchoingClassifier:
        async def classify(self, *, title: str, description: str):
            from app.maintenance.domain.value_objects import IncidentClassification

            echoed = f"El huésped dice: {description}"
            return IncidentClassification(
                category=IncidentCategory.WATER,
                severity=IncidentSeverity.HIGH,
                summary=echoed,
                confidence=Decimal("0.95"),
                vocabulary=frozenset({echoed}),
            )

    flow.classify._classifier = EchoingClassifier()
    incident = await make_incident(
        db_session, world, description="Mi DNI es 12345678Z y hay una fuga."
    )

    result = await flow.classify.execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=None, now=LATER
    )

    # The classification survives — R1.6 says an incident is not lost over an adapter
    # misbehaving — but the one field that could carry the value does not.
    assert result.status is IncidentStatus.CLASSIFIED
    assert result.severity is IncidentSeverity.HIGH
    assert result.ai_summary is None


async def test_the_second_gate_and_the_resume_have_their_own_actions(
    flow, world, db_session
) -> None:
    """D6's vocabulary, honestly: neither parking an incident on the real-cost gate nor
    resuming it after an approval is a triage, and `INCIDENT_TRIAGED` covered both until the
    architecture panel of section 6 said so."""
    incident = await _in_progress(flow, world, db_session)
    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("500.00"),
        actor=technician(world),
        now=LATER,
    )
    approvals = await db_session.execute(select(OwnerApprovalModel))
    approval = approvals.scalars().one()

    await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.APPROVED,
        response_notes=None,
        actor=owner(world),
        now=LATER,
    )

    actions_written = await audit_actions_for(db_session, incident.id)
    assert audit_actions.INCIDENT_AWAITING_APPROVAL in actions_written
    assert audit_actions.INCIDENT_RESUMED in actions_written
    assert audit_actions.INCIDENT_TRIAGED not in actions_written


async def test_our_own_wiring_mistakes_are_not_tolerated(flow, world, db_session) -> None:
    """The DESIGN-CONFLICT the architecture panel of section 6 raised, closed.

    D8 listed `IncompatibleTransitionContextError` among the exceptions the mixin tolerates,
    and the machine raises that one **only** when our code disagrees with itself — a
    severity that does not match the trigger we derived from it, a source entity absent from
    the context we built. Tolerating it is what hid the missing-source bug this mixin had.
    It now surfaces.
    """
    from app.properties.domain.exceptions import IncompatibleTransitionContextError

    incident = await make_incident(
        db_session, world, status=IncidentStatus.CLASSIFIED, severity=IncidentSeverity.HIGH
    )
    entity = await flow.incidents.get(world.tenant.id, incident.id)
    assert entity is not None

    with pytest.raises(IncompatibleTransitionContextError):
        # A trigger that contradicts the incident's own severity: our bug, not a gap in the
        # matrix, and `VACANT_READY` + `INCIDENT_CRITICAL` is a declared policy pair, so it
        # gets past the `_POLICY` lookup and dies on the precondition.
        await flow.cancel._fire_trigger(
            tenant_id=world.tenant.id,
            incident=entity,
            trigger=PropertyStateTrigger.INCIDENT_CRITICAL,
            actor=manager(world),
            now=LATER,
        )


# --- Audit and timeline discipline (R6) -------------------------------------------------


async def test_every_transition_leaves_its_audit_row(flow, world, db_session) -> None:
    """R6.1: the `AuditLog` and the `TimelineEvent` land in the same transaction as the
    change — which is why no use case here commits before writing them."""
    incident = await _in_progress(flow, world, db_session)
    await flow.resolve.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        final_cost=Decimal("60.00"),
        actor=technician(world),
        now=LATER,
    )

    assert await audit_actions_for(db_session, incident.id) == sorted(
        [
            audit_actions.INCIDENT_ASSIGNED,
            audit_actions.INCIDENT_ACCEPTED,
            audit_actions.INCIDENT_STARTED,
            audit_actions.INCIDENT_RESOLVED,
        ]
    )


async def test_the_owners_notes_stay_in_their_own_column(flow, world, db_session) -> None:
    """Excepción 3 of rule 11, and the half it does **not** concede.

    The owner's prose is allowed to survive in `owner_approvals.response_notes` — it is
    hers, about her own money, and has no decomposition into fields. What it may not do is
    propagate: `ChangeSet` refuses the column by construction (it is outside
    `AUDITABLE_FIELDS["OWNER_APPROVAL"]`) and no timeline event carries it. Asserted here
    through the real flow rather than against the allowlist, because the allowlist is what a
    future change would edit without noticing it is also the boundary of a steering
    exception.
    """
    notes = "Lo rechazo, y de paso el DNI del huésped es 12345678Z"
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    await flow.respond.execute(
        tenant_id=world.tenant.id,
        approval_id=approval.id,
        status=OwnerApprovalStatus.REJECTED,
        response_notes=notes,
        actor=owner(world),
        now=LATER,
    )

    db_session.expunge_all()
    stored = await db_session.get(OwnerApprovalModel, approval.id)
    assert stored.response_notes == notes

    audit_rows = await db_session.execute(select(AuditLogModel))
    for row in audit_rows.scalars():
        assert notes not in str(row.changes)

    events = await db_session.execute(select(TimelineEventModel))
    for event in events.scalars():
        assert notes not in event.title
        assert notes not in str(event.metadata_)
        assert notes not in str(event.description)


async def test_no_timeline_event_carries_the_reported_text(flow, world, db_session) -> None:
    """R6.3 and D10: constant titles, and `metadata` with identifiers only."""
    leaked = "mi DNI es 12345678Z"
    incident = await make_incident(
        db_session, world, status=IncidentStatus.CLASSIFIED, description=leaked
    )
    await flow.cancel.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        actor=manager(world),
        now=LATER,
    )

    events = await db_session.execute(select(TimelineEventModel))
    for event in events.scalars():
        assert leaked not in event.title
        assert leaked not in str(event.metadata_)
        assert leaked not in str(event.description)
