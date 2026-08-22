import dataclasses
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.maintenance.domain.entities import Incident, OwnerApproval
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentBlockedByPendingApprovalError,
    InvalidIncidentTransitionError,
    MaintenanceValidationError,
    OwnerApprovalAlreadyAnsweredError,
)
from app.maintenance.domain.value_objects import IncidentClassification

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)


def make_incident(status: IncidentStatus = IncidentStatus.OPEN) -> Incident:
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        source=IncidentSource.GUEST,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
        created_at=NOW,
        updated_at=NOW,
    )
    incident.status = status
    return incident


def make_approval(
    status: OwnerApprovalStatus = OwnerApprovalStatus.PENDING,
) -> OwnerApproval:
    return OwnerApproval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=Decimal("250.00"),
        reason="Boiler replacement quoted by the technician.",
        requested_at=NOW,
        status=status,
    )


def classification(
    confidence: str = "0.90",
    category: IncidentCategory = IncidentCategory.HVAC,
    severity: IncidentSeverity = IncidentSeverity.HIGH,
) -> IncidentClassification:
    return IncidentClassification(
        category=category,
        severity=severity,
        summary="Air conditioning fault reported",
        confidence=Decimal(confidence),
        vocabulary=frozenset({"Air conditioning fault reported"}),
    )


def test_incident_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        source=IncidentSource.GUEST,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
        created_at=now,
        updated_at=now,
    )

    assert incident.category == IncidentCategory.OTHER
    assert incident.severity == IncidentSeverity.MEDIUM
    assert incident.status == IncidentStatus.OPEN
    assert incident.owner_approval_required is False
    assert incident.reservation_id is None
    # R3.1 — an incident nobody has assigned carries no note, and `None` is the honest
    # answer rather than an empty string a client would have to tell apart from one.
    assert incident.assignment_note is None


def test_owner_approval_instantiates_with_defaults() -> None:
    approval = make_approval()

    assert approval.status is OwnerApprovalStatus.PENDING
    assert approval.responded_at is None
    assert approval.responded_by is None
    assert approval.response_notes is None


def test_owner_approval_has_no_created_or_updated_at() -> None:
    """Strict fidelity to §7.19 (design OQ1): only requested_at/responded_at."""
    fields = OwnerApproval.__dataclass_fields__

    assert "created_at" not in fields
    assert "updated_at" not in fields
    assert "requested_at" in fields


# --- The lifecycle table (R4.1, R4.4, design D5) ---------------------------------------
#
# One row per operation the entity exposes: the statuses it accepts as origin, the status it
# leaves the incident in, and how to drive it. Every legal move of the diagram in the
# design's *Data & interfaces* is here, and `test_operation_table_matches_entity_table`
# checks this list against `Incident._TRANSITIONS` so neither can grow without the other.

Operation = Callable[[Incident], None]

_OPERATIONS: list[tuple[str, Operation, frozenset[IncidentStatus], IncidentStatus]] = [
    (
        "classify",
        lambda i: i.classify(
            classification(), confidence_threshold=Decimal("0.70"), adapter="test", now=LATER
        ),
        frozenset({IncidentStatus.OPEN}),
        IncidentStatus.CLASSIFIED,
    ),
    (
        "require_owner_approval",
        lambda i: i.require_owner_approval(now=LATER),
        frozenset({IncidentStatus.CLASSIFIED, IncidentStatus.IN_PROGRESS}),
        IncidentStatus.AWAITING_OWNER_APPROVAL,
    ),
    (
        "resume_after_approval:INCIDENT",
        lambda i: i.resume_after_approval(
            related_type=OwnerApprovalRelatedType.INCIDENT,
            approved_cost=Decimal("250.00"),
            now=LATER,
        ),
        frozenset({IncidentStatus.AWAITING_OWNER_APPROVAL}),
        IncidentStatus.CLASSIFIED,
    ),
    (
        "resume_after_approval:MAINTENANCE_COST",
        lambda i: i.resume_after_approval(
            related_type=OwnerApprovalRelatedType.MAINTENANCE_COST,
            approved_cost=Decimal("250.00"),
            now=LATER,
        ),
        frozenset({IncidentStatus.AWAITING_OWNER_APPROVAL}),
        IncidentStatus.IN_PROGRESS,
    ),
    (
        "assign",
        lambda i: i.assign(technician_id=uuid.uuid4(), now=LATER),
        frozenset(
            {
                IncidentStatus.CLASSIFIED,
                IncidentStatus.ASSIGNED,
                IncidentStatus.ACCEPTED,
                IncidentStatus.IN_PROGRESS,
                IncidentStatus.WAITING_EXTERNAL_PARTS,
            }
        ),
        IncidentStatus.ASSIGNED,
    ),
    (
        "accept",
        lambda i: i.accept(now=LATER),
        frozenset({IncidentStatus.ASSIGNED}),
        IncidentStatus.ACCEPTED,
    ),
    (
        "start",
        lambda i: i.start(now=LATER),
        frozenset({IncidentStatus.ACCEPTED}),
        IncidentStatus.IN_PROGRESS,
    ),
    (
        "wait_for_parts",
        lambda i: i.wait_for_parts(now=LATER),
        frozenset({IncidentStatus.IN_PROGRESS}),
        IncidentStatus.WAITING_EXTERNAL_PARTS,
    ),
    (
        "resume_work",
        lambda i: i.resume_work(now=LATER),
        frozenset({IncidentStatus.WAITING_EXTERNAL_PARTS}),
        IncidentStatus.IN_PROGRESS,
    ),
    (
        "resolve",
        lambda i: i.resolve(final_cost=Decimal("120.00"), now=LATER),
        frozenset({IncidentStatus.IN_PROGRESS}),
        IncidentStatus.RESOLVED,
    ),
    (
        "cancel",
        lambda i: i.cancel(now=LATER),
        frozenset(set(IncidentStatus) - {IncidentStatus.RESOLVED, IncidentStatus.CANCELLED}),
        IncidentStatus.CANCELLED,
    ),
]

_ACCEPTED_CASES = [
    pytest.param(operation, source, target, id=f"{name}-from-{source.value}")
    for name, operation, sources, target in _OPERATIONS
    for source in sorted(sources, key=lambda s: s.value)
]

_REJECTED_CASES = [
    pytest.param(operation, source, id=f"{name}-from-{source.value}")
    for name, operation, sources, _ in _OPERATIONS
    for source in sorted(set(IncidentStatus) - sources, key=lambda s: s.value)
]


@pytest.mark.parametrize(("operation", "source", "target"), _ACCEPTED_CASES)
def test_legal_transition_is_accepted(
    operation: Operation, source: IncidentStatus, target: IncidentStatus
) -> None:
    incident = make_incident(source)

    operation(incident)

    assert incident.status is target
    assert incident.updated_at == LATER


@pytest.mark.parametrize(("operation", "source"), _REJECTED_CASES)
def test_illegal_transition_is_rejected_without_mutating(
    operation: Operation, source: IncidentStatus
) -> None:
    """R4.4: rejected "sin modificar nada" — the whole dataclass, not only `status`."""
    incident = make_incident(source)
    before = dataclasses.asdict(incident)

    if source in {IncidentStatus.RESOLVED, IncidentStatus.CANCELLED}:
        expected: type[Exception] = IncidentAlreadyClosedError
    elif source is IncidentStatus.AWAITING_OWNER_APPROVAL:
        expected = IncidentBlockedByPendingApprovalError
    else:
        expected = InvalidIncidentTransitionError

    with pytest.raises(expected):
        operation(incident)

    assert dataclasses.asdict(incident) == before


def test_operation_table_matches_entity_table() -> None:
    """The test's own table and `_TRANSITIONS` are the same fact, stated twice on purpose.

    Without this, an operation added to the entity with a source the tests never drive
    would be covered by neither the acceptance nor the rejection parametrisation.
    """
    assert {name: (sources, target) for name, _, sources, target in _OPERATIONS} == dict(
        Incident._TRANSITIONS
    )


def test_terminal_statuses_are_the_origin_of_no_operation() -> None:
    """What makes `RESOLVED`/`CANCELLED` terminal: no row of the table admits them."""
    for sources, _ in Incident._TRANSITIONS.values():
        assert not sources & {IncidentStatus.RESOLVED, IncidentStatus.CANCELLED}


# --- The note that rides with an assignment (R3.1, design D7) ---------------------------


def test_assign_writes_the_note_it_was_given() -> None:
    incident = make_incident(IncidentStatus.CLASSIFIED)

    incident.assign(
        technician_id=uuid.uuid4(),
        now=LATER,
        assignment_note="Portal code 4821, key in the entrance box.",
    )

    assert incident.assignment_note == "Portal code 4821, key in the entrance box."
    assert incident.status is IncidentStatus.ASSIGNED


def test_reassigning_without_a_note_clears_the_previous_one() -> None:
    """D7 — the note belongs to the assignment in force, not to the incident.

    This is the half a truthy-only write would get wrong, and getting it wrong shows
    technician B what the manager wrote for technician A.
    """
    incident = make_incident(IncidentStatus.CLASSIFIED)
    incident.assign(technician_id=uuid.uuid4(), now=LATER, assignment_note="Ask the porter.")

    incident.assign(technician_id=uuid.uuid4(), now=LATER)

    assert incident.assignment_note is None


def test_reassigning_with_a_note_replaces_the_previous_one() -> None:
    incident = make_incident(IncidentStatus.CLASSIFIED)
    incident.assign(technician_id=uuid.uuid4(), now=LATER, assignment_note="Ask the porter.")

    incident.assign(technician_id=uuid.uuid4(), now=LATER, assignment_note="Code 4821.")

    assert incident.assignment_note == "Code 4821."


def test_the_note_does_not_reach_the_transition_table() -> None:
    """R3.2 — the legal moves of `assign` are exactly what they were.

    `test_operation_table_matches_entity_table` pins the table against the test's own copy;
    this pins that the note did not become a sixth origin or a condition on one.
    """
    origins, target = Incident._TRANSITIONS["assign"]

    assert origins == frozenset(
        {
            IncidentStatus.CLASSIFIED,
            IncidentStatus.ASSIGNED,
            IncidentStatus.ACCEPTED,
            IncidentStatus.IN_PROGRESS,
            IncidentStatus.WAITING_EXTERNAL_PARTS,
        }
    )
    assert target is IncidentStatus.ASSIGNED


def test_an_illegal_assign_leaves_no_note_behind() -> None:
    """A refusal must not be a write. `_check_transition` runs first, so the note never
    lands on an incident the move was rejected for."""
    incident = make_incident(IncidentStatus.RESOLVED)

    with pytest.raises(IncidentAlreadyClosedError):
        incident.assign(
            technician_id=uuid.uuid4(), now=LATER, assignment_note="Code 4821."
        )

    assert incident.assignment_note is None


# --- Classification against the confidence threshold (R1.2, R1.3, R1.5; design D3) ------


def test_classify_above_the_threshold_applies_the_verdict() -> None:
    incident = make_incident()

    incident.classify(
        classification("0.90"),
        confidence_threshold=Decimal("0.70"),
        adapter="RuleBasedIncidentClassifier",
        now=LATER,
    )

    assert incident.status is IncidentStatus.CLASSIFIED
    assert incident.category is IncidentCategory.HVAC
    assert incident.severity is IncidentSeverity.HIGH
    assert incident.ai_summary == "Air conditioning fault reported"
    assert incident.ai_classification == {
        "category": "HVAC",
        "severity": "HIGH",
        "confidence": "0.90",
        "adapter": "RuleBasedIncidentClassifier",
        "classified_at": LATER.isoformat(),
    }


def test_classify_below_the_threshold_stays_open_with_defaults() -> None:
    """R1.3 + D3: still `OPEN`, still default category/severity, but no longer *unseen*."""
    incident = make_incident()

    incident.classify(
        classification("0.40"),
        confidence_threshold=Decimal("0.70"),
        adapter="RuleBasedIncidentClassifier",
        now=LATER,
    )

    assert incident.status is IncidentStatus.OPEN
    assert incident.category is IncidentCategory.OTHER
    assert incident.severity is IncidentSeverity.MEDIUM
    assert incident.ai_summary is None
    assert incident.ai_classification is not None
    assert incident.ai_classification["confidence"] == "0.40"


def test_classify_at_the_threshold_classifies() -> None:
    """R1.3 says "menor que", so equality is enough — the boundary is stated once, here."""
    incident = make_incident()

    incident.classify(
        classification("0.70"),
        confidence_threshold=Decimal("0.70"),
        adapter="test",
        now=LATER,
    )

    assert incident.status is IncidentStatus.CLASSIFIED


def test_low_confidence_is_distinguishable_from_a_fresh_incident() -> None:
    """The candidate rule of D2's job: `OPEN` **and** `ai_classification IS NULL`."""
    fresh = make_incident()
    low_confidence = make_incident()
    low_confidence.classify(
        classification("0.10"),
        confidence_threshold=Decimal("0.70"),
        adapter="test",
        now=LATER,
    )

    assert fresh.status is low_confidence.status is IncidentStatus.OPEN
    assert fresh.ai_classification is None
    assert low_confidence.ai_classification is not None


@pytest.mark.parametrize("confidence", ["0.90", "0.10"])
def test_classify_never_rewrites_the_reported_text(confidence: str) -> None:
    """R1.5: the classifier writes neither `title` nor `description`, on any path."""
    incident = make_incident()
    title, description = incident.title, incident.description

    incident.classify(
        classification(confidence),
        confidence_threshold=Decimal("0.70"),
        adapter="test",
        now=LATER,
    )

    assert incident.title == title
    assert incident.description == description


@pytest.mark.parametrize(
    ("given", "recorded"),
    [
        ("RuleBasedIncidentClassifier", "RuleBasedIncidentClassifier"),
        ("adapter v2", "UNKNOWN_CLASSIFIER"),
        ("2fast", "UNKNOWN_CLASSIFIER"),
        ("the guest wrote 12345678Z", "UNKNOWN_CLASSIFIER"),
        ("", "UNKNOWN_CLASSIFIER"),
    ],
)
def test_adapter_name_is_a_closed_token(given: str, recorded: str) -> None:
    """D4: `ai_classification` holds "sólo valores cerrados y números".

    `adapter` is the only one of its five keys that is not an enum, a number or a
    timestamp, so it degrades like `webhook_events.event_type` does — the column named
    late in the rule 11 census precisely because its name promised an enum and its writer
    put free text in it.
    """
    incident = make_incident()

    incident.classify(
        classification(),
        confidence_threshold=Decimal("0.70"),
        adapter=given,
        now=LATER,
    )

    assert incident.ai_classification is not None
    assert incident.ai_classification["adapter"] == recorded


# --- Manual triage (R1.4) ---------------------------------------------------------------


def test_triage_sets_the_fields_a_human_corrects() -> None:
    incident = make_incident(IncidentStatus.CLASSIFIED)

    incident.set_triage(
        category=IncidentCategory.PLUMBING,
        severity=IncidentSeverity.CRITICAL,
        estimated_cost=Decimal("450.00"),
        now=LATER,
    )

    assert incident.category is IncidentCategory.PLUMBING
    assert incident.severity is IncidentSeverity.CRITICAL
    assert incident.estimated_cost == Decimal("450.00")
    assert incident.status is IncidentStatus.CLASSIFIED
    assert incident.updated_at == LATER


def test_triage_leaves_untouched_what_it_was_not_given() -> None:
    incident = make_incident(IncidentStatus.CLASSIFIED)
    incident.severity = IncidentSeverity.HIGH
    incident.estimated_cost = Decimal("30.00")

    incident.set_triage(category=IncidentCategory.WIFI, now=LATER)

    assert incident.category is IncidentCategory.WIFI
    assert incident.severity is IncidentSeverity.HIGH
    assert incident.estimated_cost == Decimal("30.00")


@pytest.mark.parametrize(
    "status", [IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]
)
def test_triage_is_refused_on_a_closed_incident(status: IncidentStatus) -> None:
    """R1.4: "mientras la incidencia no esté en un estado terminal"."""
    incident = make_incident(status)
    before = dataclasses.asdict(incident)

    with pytest.raises(IncidentAlreadyClosedError):
        incident.set_triage(category=IncidentCategory.WIFI, now=LATER)

    assert dataclasses.asdict(incident) == before


def test_triage_is_allowed_while_the_owner_has_not_answered() -> None:
    """`AWAITING_OWNER_APPROVAL` is not terminal, so R1.4 still applies to it."""
    incident = make_incident(IncidentStatus.AWAITING_OWNER_APPROVAL)

    incident.set_triage(severity=IncidentSeverity.CRITICAL, now=LATER)

    assert incident.severity is IncidentSeverity.CRITICAL


# --- The cost fields the flow writes (R2.4, R4.2, R4.3; design D11) ---------------------


def test_resolve_writes_the_final_cost_and_the_resolution_instant() -> None:
    """R4.2: "SHALL exigir `final_cost`, fijar `resolved_at` y pasar a `RESOLVED`"."""
    incident = make_incident(IncidentStatus.IN_PROGRESS)

    incident.resolve(final_cost=Decimal("120.00"), now=LATER)

    assert incident.status is IncidentStatus.RESOLVED
    assert incident.final_cost == Decimal("120.00")
    assert incident.resolved_at == LATER


def test_the_real_cost_gate_records_the_cost_without_resolving() -> None:
    """D11: "incidencia a `AWAITING_OWNER_APPROVAL` **sin** `resolved_at`"."""
    incident = make_incident(IncidentStatus.IN_PROGRESS)

    incident.require_owner_approval(final_cost=Decimal("800.00"), now=LATER)

    assert incident.status is IncidentStatus.AWAITING_OWNER_APPROVAL
    assert incident.final_cost == Decimal("800.00")
    assert incident.resolved_at is None
    assert incident.owner_approval_required is True


def test_the_budget_gate_records_no_cost_of_its_own() -> None:
    incident = make_incident(IncidentStatus.CLASSIFIED)
    incident.estimated_cost = Decimal("450.00")

    incident.require_owner_approval(now=LATER)

    assert incident.status is IncidentStatus.AWAITING_OWNER_APPROVAL
    assert incident.final_cost is None
    assert incident.estimated_cost == Decimal("450.00")


def test_an_approval_of_an_unrelated_type_resumes_nothing() -> None:
    """`OwnerApprovalRelatedType` has a third member, `OTHER`, and D11 derives the
    destination from exactly two. An approval of that type answering an incident would have
    to guess where to put it, so it says so instead."""
    incident = make_incident(IncidentStatus.AWAITING_OWNER_APPROVAL)
    before = dataclasses.asdict(incident)

    with pytest.raises(MaintenanceValidationError):
        incident.resume_after_approval(
            related_type=OwnerApprovalRelatedType.OTHER,
            approved_cost=Decimal("450.00"),
            now=LATER,
        )

    assert dataclasses.asdict(incident) == before


def test_resume_after_approval_applies_the_approved_cost() -> None:
    """R2.4: "IF la respuesta es `APPROVED`, THEN SHALL fijar `approved_cost`"."""
    incident = make_incident(IncidentStatus.AWAITING_OWNER_APPROVAL)

    incident.resume_after_approval(
        related_type=OwnerApprovalRelatedType.INCIDENT,
        approved_cost=Decimal("450.00"),
        now=LATER,
    )

    assert incident.status is IncidentStatus.CLASSIFIED
    assert incident.approved_cost == Decimal("450.00")


@pytest.mark.parametrize(
    ("approved_cost", "final_cost", "covered"),
    [
        (None, Decimal("10.00"), False),
        (Decimal("450.00"), Decimal("450.00"), True),
        (Decimal("450.00"), Decimal("449.99"), True),
        (Decimal("450.00"), Decimal("450.01"), False),
        (Decimal("0.00"), Decimal("0.00"), True),
    ],
)
def test_is_covered_by_approval_is_the_literal_formula_of_d11(
    approved_cost: Decimal | None, final_cost: Decimal, covered: bool
) -> None:
    """D11: "`approved_cost is not None and final_cost <= approved_cost`" — an incident
    with no approved cost is covered by nothing, and an approval does not stretch."""
    incident = make_incident(IncidentStatus.IN_PROGRESS)
    incident.approved_cost = approved_cost

    assert incident.is_covered_by_approval(final_cost) is covered


@pytest.mark.parametrize(
    ("source", "mutate"),
    [
        pytest.param(
            IncidentStatus.CLASSIFIED,
            lambda i: i.set_triage(estimated_cost=Decimal("-1"), now=LATER),
            id="set_triage",
        ),
        pytest.param(
            IncidentStatus.IN_PROGRESS,
            lambda i: i.require_owner_approval(final_cost=Decimal("-1"), now=LATER),
            id="require_owner_approval",
        ),
        pytest.param(
            IncidentStatus.AWAITING_OWNER_APPROVAL,
            lambda i: i.resume_after_approval(
                related_type=OwnerApprovalRelatedType.INCIDENT,
                approved_cost=Decimal("-1"),
                now=LATER,
            ),
            id="resume_after_approval",
        ),
        pytest.param(
            IncidentStatus.IN_PROGRESS,
            lambda i: i.resolve(final_cost=Decimal("-1"), now=LATER),
            id="resolve",
        ),
    ],
)
def test_no_cost_path_accepts_a_negative_amount(
    source: IncidentStatus, mutate: Operation
) -> None:
    incident = make_incident(source)
    before = dataclasses.asdict(incident)

    with pytest.raises(MaintenanceValidationError):
        mutate(incident)

    assert dataclasses.asdict(incident) == before


# --- Answering an owner approval (R2.4, R2.6) ------------------------------------------


def test_approval_answer_approved_records_the_response_and_returns_the_amount() -> None:
    approval = make_approval()
    responder = uuid.uuid4()

    applied = approval.answer(
        status=OwnerApprovalStatus.APPROVED,
        responded_by=responder,
        response_notes="Go ahead.",
        now=LATER,
    )

    assert approval.status is OwnerApprovalStatus.APPROVED
    assert approval.responded_at == LATER
    assert approval.responded_by == responder
    assert approval.response_notes == "Go ahead."
    assert applied == approval.amount


def test_approval_answer_rejected_records_the_response_and_applies_no_cost() -> None:
    approval = make_approval()

    applied = approval.answer(
        status=OwnerApprovalStatus.REJECTED,
        responded_by=uuid.uuid4(),
        response_notes="Too expensive.",
        now=LATER,
    )

    assert approval.status is OwnerApprovalStatus.REJECTED
    assert approval.responded_at == LATER
    assert applied is None


@pytest.mark.parametrize(
    "already", [OwnerApprovalStatus.APPROVED, OwnerApprovalStatus.REJECTED]
)
def test_approval_cannot_be_answered_twice(already: OwnerApprovalStatus) -> None:
    """R2.6: "ni responder dos veces la misma"."""
    approval = make_approval(status=already)
    approval.responded_at = NOW
    before = dataclasses.asdict(approval)

    with pytest.raises(OwnerApprovalAlreadyAnsweredError):
        approval.answer(
            status=OwnerApprovalStatus.APPROVED,
            responded_by=uuid.uuid4(),
            response_notes=None,
            now=LATER,
        )

    assert dataclasses.asdict(approval) == before


@pytest.mark.parametrize(
    "answer", [OwnerApprovalStatus.PENDING, OwnerApprovalStatus.EXPIRED]
)
def test_approval_answer_must_be_approved_or_rejected(
    answer: OwnerApprovalStatus,
) -> None:
    approval = make_approval()
    before = dataclasses.asdict(approval)

    with pytest.raises(MaintenanceValidationError):
        approval.answer(
            status=answer,
            responded_by=uuid.uuid4(),
            response_notes=None,
            now=LATER,
        )

    assert dataclasses.asdict(approval) == before
