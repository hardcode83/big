import dataclasses
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.maintenance.domain.entities import Incident, IncidentPhoto, OwnerApproval
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentPhotoStage,
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
        "reject",
        lambda i: i.reject(now=LATER),
        frozenset({IncidentStatus.ASSIGNED, IncidentStatus.ACCEPTED}),
        IncidentStatus.CLASSIFIED,
    ),
    (
        "en_route",
        lambda i: i.en_route(now=LATER),
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


# --- The materials the technician declares on closing (R4.1-R4.4; design D7) ------------


def test_the_cost_gate_keeps_the_materials_the_technician_declared() -> None:
    """R4.3 — the close that opens the second approval gate writes `materials` anyway.

    The technician declared the spend; losing its description because the amount crossed the
    threshold would make them type it twice.
    """
    incident = make_incident(IncidentStatus.IN_PROGRESS)

    incident.require_owner_approval(
        now=LATER, final_cost=Decimal("500.00"), materials="Dos codos de 22 mm y teflón"
    )

    assert incident.materials == "Dos codos de 22 mm y teflón"
    assert incident.final_cost == Decimal("500.00")
    assert incident.status is IncidentStatus.AWAITING_OWNER_APPROVAL


def test_a_second_close_without_materials_does_not_erase_them() -> None:
    """D7 — the semantics that **preserve** rather than replace, and the reason for them.

    After the owner approves, the technician repeats the close. With `assign`'s
    complete-operation semantics a body arriving without `materials` would silently wipe what
    R4.3 has just protected.
    """
    incident = make_incident(IncidentStatus.IN_PROGRESS)
    incident.require_owner_approval(
        now=LATER, final_cost=Decimal("500.00"), materials="Dos codos de 22 mm"
    )
    incident.resume_after_approval(
        related_type=OwnerApprovalRelatedType.MAINTENANCE_COST,
        approved_cost=Decimal("500.00"),
        now=LATER,
    )

    incident.resolve(final_cost=Decimal("500.00"), now=LATER)

    assert incident.materials == "Dos codos de 22 mm"


def test_resolve_writes_the_materials_it_was_given() -> None:
    incident = make_incident(IncidentStatus.IN_PROGRESS)

    incident.resolve(
        final_cost=Decimal("120.00"), materials="Una junta y medio metro de tubo", now=LATER
    )

    assert incident.materials == "Una junta y medio metro de tubo"


def test_materials_never_touches_the_final_cost() -> None:
    """R4.4 — no derivation and no cross-validation between the two."""
    incident = make_incident(IncidentStatus.IN_PROGRESS)

    incident.resolve(final_cost=Decimal("0.00"), materials="Nada, solo mano de obra", now=LATER)

    assert incident.final_cost == Decimal("0.00")


# --- The estimated time of arrival (R3.1, R3.3, R3.4, R3.5; design D6) ------------------


@pytest.mark.parametrize("operation", ["accept", "en_route"])
def test_an_eta_in_the_past_is_refused_without_writing_anything(operation: str) -> None:
    """R3.4 — "estrictamente anterior … y NEVER SHALL escribir nada".

    The whole dataclass is compared, not just `eta_at`: the refusal has to land before
    `_transition`, so `status` and `updated_at` must be untouched too.
    """
    source = (
        IncidentStatus.ASSIGNED if operation == "accept" else IncidentStatus.ACCEPTED
    )
    incident = make_incident(source)
    before = dataclasses.asdict(incident)

    with pytest.raises(MaintenanceValidationError):
        getattr(incident, operation)(now=LATER, eta_at=LATER - timedelta(minutes=1))

    assert dataclasses.asdict(incident) == before


def test_an_eta_exactly_now_is_accepted() -> None:
    """"Estrictamente anterior" is the wording, so the boundary itself passes — a technician
    saying "I am here now" is not an error."""
    incident = make_incident(IncidentStatus.ASSIGNED)

    incident.accept(now=LATER, eta_at=LATER)

    assert incident.eta_at == LATER


@pytest.mark.parametrize("operation", ["accept", "en_route"])
def test_a_naive_eta_is_refused(operation: str) -> None:
    """Not in R3.4's letter, and load-bearing anyway (D6): without it the comparison with
    `now` raises `TypeError` and surfaces as an undeclared `500` instead of a `422`. The same
    check `properties`, `timeline`, `auth` and `cleaning` already make at their edges."""
    source = (
        IncidentStatus.ASSIGNED if operation == "accept" else IncidentStatus.ACCEPTED
    )
    incident = make_incident(source)
    before = dataclasses.asdict(incident)

    with pytest.raises(MaintenanceValidationError):
        getattr(incident, operation)(now=LATER, eta_at=datetime(2026, 8, 16, 9, 0))

    assert dataclasses.asdict(incident) == before


@pytest.mark.parametrize("operation", ["accept", "en_route"])
def test_an_eta_in_the_future_is_written(operation: str) -> None:
    source = (
        IncidentStatus.ASSIGNED if operation == "accept" else IncidentStatus.ACCEPTED
    )
    incident = make_incident(source)
    eta = LATER + timedelta(hours=3)

    getattr(incident, operation)(now=LATER, eta_at=eta)

    assert incident.eta_at == eta


def test_an_absent_eta_preserves_whatever_was_there() -> None:
    """R3.3 — "IF el cuerpo no lo trae, THEN … dejar el valor anterior intacto". Falls out of
    `_apply_eta` returning early on `None`, which is what makes "absent" and "cleared" two
    different things without a sentinel."""
    incident = make_incident(IncidentStatus.ACCEPTED)
    eta = LATER + timedelta(hours=3)
    incident.eta_at = eta

    incident.en_route(now=LATER)

    assert incident.eta_at == eta


def test_assigning_clears_the_eta_unconditionally() -> None:
    """R3.5 — the ETA belongs to the assignment in force, exactly like `assignment_note`, so
    a reassignment does not inherit the previous technician's promised hour."""
    incident = make_incident(IncidentStatus.ACCEPTED)
    incident.eta_at = LATER + timedelta(hours=3)
    incident.assignment_note = "Sube por la escalera B"

    incident.assign(technician_id=uuid.uuid4(), now=LATER)

    assert incident.eta_at is None
    assert incident.assignment_note is None


# --- The technician's refusal (R1.1, R1.2, R1.8; design D2) -----------------------------


@pytest.mark.parametrize(
    "source", [IncidentStatus.ASSIGNED, IncidentStatus.ACCEPTED], ids=lambda s: s.value
)
def test_reject_clears_all_three_fields_of_the_current_assignment(
    source: IncidentStatus,
) -> None:
    """D2 — the three, and not only the one R1.2 names.

    `assigned_technician_id`, `eta_at` and `assignment_note` all belong to the assignment in
    force rather than to the incident. A `CLASSIFIED` incident with no owner that kept the
    note written for whoever said no — or the hour that technician promised — is the same
    "fila que miente" the `ASSUMPTION` of R1 rejects for the assignee. Who refused survives
    in the `AuditLog`, which audits `assigned_technician_id` with its previous value.
    """
    incident = make_incident(source)
    incident.assigned_technician_id = uuid.uuid4()
    incident.assignment_note = "El portal abre con el 4821"
    incident.eta_at = LATER + timedelta(hours=2)

    incident.reject(now=LATER)

    assert incident.status is IncidentStatus.CLASSIFIED
    assert incident.assigned_technician_id is None
    assert incident.assignment_note is None
    assert incident.eta_at is None
    assert incident.updated_at == LATER


def test_reject_leaves_the_incident_where_assign_can_pick_it_up() -> None:
    """R1.2 — `CLASSIFIED` is an origin `assign` already admits, which is the whole point of
    choosing it: the manager reassigns without a step in between."""
    incident = make_incident(IncidentStatus.ASSIGNED)
    incident.assigned_technician_id = uuid.uuid4()

    incident.reject(now=LATER)

    assert incident.status in Incident._TRANSITIONS["assign"][0]


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


# --- incident photos (`incident-photos` sections 3.1-3.4) -----------------------------
#
# The enum, the entity, and the state gate that decides whether an incident will take a
# photo at all. The gate is the only real invariant of the three, so it carries most of the
# tests: it has to produce *three distinguishable* refusals, in a fixed order, and R2.4/R2.5/
# R2.6 each name a different one.


def test_the_photo_stage_enum_has_exactly_two_members() -> None:
    """R1.2 — `BEFORE` and `AFTER`, closed.

    Asserted as an exact set, not with two `in` checks, so that adding a third member fails
    here. That is the point of the closed enum: a third stage must be a deliberate schema
    change, not a one-line addition, because the closedness is what keeps this off the
    free-text-sink census of rule 11 (R6.5).
    """
    assert {stage.value for stage in IncidentPhotoStage} == {"BEFORE", "AFTER"}


def test_the_photo_stage_values_are_their_own_names() -> None:
    """The PRD convention: enum values are the exact tokens, so the wire, the database enum
    and the Python member cannot drift apart."""
    for stage in IncidentPhotoStage:
        assert stage.value == stage.name


def test_incident_photo_instantiates_with_the_seven_fields_it_declares() -> None:
    """R1.1 — and no more than those.

    `IncidentPhoto` deliberately has no `content_type` and no client file name (R1.5): the
    served `Content-Type` is derived from the storage key's extension, and the client's file
    name never touches the key. Asserted as an exact field set so neither can be added
    without this failing.
    """
    photo = IncidentPhoto(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        stage=IncidentPhotoStage.BEFORE,
        storage_key="tenants/t/incidents/i/p.jpg",
        created_at=NOW,
    )

    assert {field.name for field in dataclasses.fields(photo)} == {
        "id",
        "tenant_id",
        "incident_id",
        "uploaded_by",
        "stage",
        "storage_key",
        "created_at",
    }


def test_incident_photo_carries_its_own_tenant_id() -> None:
    """R1.3/D2 — the deviation from `cleaning_photos`, which has none.

    The column is what puts `incident_photos` under the global tenant filter and what lets
    the isolation test of R6.3 exist without going through the incident.
    """
    tenant = uuid.uuid4()
    photo = IncidentPhoto(
        id=uuid.uuid4(),
        tenant_id=tenant,
        incident_id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        stage=IncidentPhotoStage.AFTER,
        storage_key="tenants/t/incidents/i/p.png",
        created_at=NOW,
    )

    assert photo.tenant_id == tenant


# --- the state gate: `Incident.ensure_accepts_photo()` (R2.4, R2.5, R2.6, D6) ----------


@pytest.mark.parametrize(
    "status", [IncidentStatus.IN_PROGRESS, IncidentStatus.WAITING_EXTERNAL_PARTS]
)
def test_the_two_working_statuses_accept_a_photo(status: IncidentStatus) -> None:
    """R2.4 — the two states in which the technician's work is under way.

    `WAITING_EXTERNAL_PARTS` is included on purpose: the flat still has a broken thing in it
    and the technician may well photograph what is missing.
    """
    incident = make_incident(status)

    incident.ensure_accepts_photo()


@pytest.mark.parametrize("status", [IncidentStatus.RESOLVED, IncidentStatus.CANCELLED])
def test_a_closed_incident_refuses_a_photo_as_already_closed(
    status: IncidentStatus,
) -> None:
    """R2.6 — and specifically `IncidentAlreadyClosedError`, not the generic refusal.

    First in the order, because a closed incident will never admit anything: answering "out
    of order" would suggest waiting for a state that is never coming.
    """
    incident = make_incident(status)

    with pytest.raises(IncidentAlreadyClosedError):
        incident.ensure_accepts_photo()


def test_an_incident_awaiting_the_owner_refuses_a_photo_with_its_own_error() -> None:
    """R2.5 — `IncidentBlockedByPendingApprovalError`, distinguishable from R2.4's refusal.

    Second in the order. It means something different from "out of order": the work is
    blocked on a specific answer from a specific person, which is actionable.
    """
    incident = make_incident(IncidentStatus.AWAITING_OWNER_APPROVAL)

    with pytest.raises(IncidentBlockedByPendingApprovalError):
        incident.ensure_accepts_photo()


@pytest.mark.parametrize(
    "status",
    [
        IncidentStatus.OPEN,
        IncidentStatus.CLASSIFIED,
        IncidentStatus.ASSIGNED,
        IncidentStatus.ACCEPTED,
    ],
)
def test_any_other_status_refuses_a_photo_as_out_of_order(
    status: IncidentStatus,
) -> None:
    """R2.4 — `InvalidIncidentTransitionError` for everything that is neither closed nor
    awaiting the owner and is not one of the two working states.

    Third and last in the order, so it is the residue rather than a case that shadows the
    two specific ones.
    """
    incident = make_incident(status)

    with pytest.raises(InvalidIncidentTransitionError):
        incident.ensure_accepts_photo()


def test_the_three_refusals_are_distinguishable_from_each_other() -> None:
    """The assertion the proposal actually asks for: not "a 409", but *which* 409.

    Each of the three parametrised tests above catches one error class, but `pytest.raises`
    accepts a subclass, so three separate tests could all be passing on a common ancestor if
    the hierarchy were ever flattened wrongly. This pins that the three are distinct types,
    which is what makes the API's three distinct messages (D6) possible.
    """
    errors = set()
    for status in (
        IncidentStatus.RESOLVED,
        IncidentStatus.AWAITING_OWNER_APPROVAL,
        IncidentStatus.OPEN,
    ):
        try:
            make_incident(status).ensure_accepts_photo()
        except Exception as exc:  # noqa: BLE001 - the type is the assertion
            errors.add(type(exc))

    assert errors == {
        IncidentAlreadyClosedError,
        IncidentBlockedByPendingApprovalError,
        InvalidIncidentTransitionError,
    }


def test_the_shared_helper_answers_the_photo_gate_and_a_real_transition_alike() -> None:
    """D6's "una sola casa" for the refusal order, asserted as cross-caller consistency.

    **This test does not observe the order, and an earlier name of it claimed to.** The two
    extracted branches are mutually exclusive on one row — an incident cannot be both closed
    and awaiting the owner — so no single scenario can watch one check run before the other.
    The order is a fact about the code's structure, and what actually exercises it across all
    eleven operations is the pre-existing `_REJECTED_CASES` matrix above, together with
    `test_operation_table_matches_entity_table`, which fails if a row is ever added to
    `_TRANSITIONS` without being declared here — including the pseudo-transition D6 rejected.

    What this *does* verify is the thing the extraction could actually have broken: that
    `ensure_accepts_photo` and a genuine transition are answered by the **same** helper, so
    they cannot drift into disagreeing about what a closed incident means.
    """
    resolved = make_incident(IncidentStatus.RESOLVED)

    with pytest.raises(IncidentAlreadyClosedError):
        resolved.ensure_accepts_photo()

    # And the same entity refuses a real transition with the same error, which is the
    # evidence that one helper answers for both callers rather than two copies agreeing today.
    with pytest.raises(IncidentAlreadyClosedError):
        resolved.en_route(now=NOW)


@pytest.mark.parametrize("status", list(IncidentStatus))
def test_ensure_accepts_photo_never_mutates(status: IncidentStatus) -> None:
    """D6 — the method does not move the incident. Every status, accepted or refused.

    Uploading a photo is evidence, not a lifecycle step: `_TRANSITIONS` has no row for it and
    the entity must come out of this call byte-identical.
    """
    incident = make_incident(status)
    before = dataclasses.asdict(incident)

    try:
        incident.ensure_accepts_photo()
    except (
        IncidentAlreadyClosedError,
        IncidentBlockedByPendingApprovalError,
        InvalidIncidentTransitionError,
    ):
        pass

    assert dataclasses.asdict(incident) == before

