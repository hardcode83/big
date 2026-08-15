"""The audit vocabulary `maintenance` mints, and the columns it refuses to carry (D6, R6.2).

Its own file, like `test_guest_portal_vocabulary.py` and `test_webhook_endpoint_vocabulary.py`:
each change that widens the closed vocabulary of `app/audit/domain/` states what it added and
what it deliberately left out, next to its reason.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel

INCIDENT_ACTIONS = {
    "INCIDENT_CLASSIFIED",
    "INCIDENT_TRIAGED",
    "INCIDENT_ASSIGNED",
    "INCIDENT_ACCEPTED",
    "INCIDENT_STARTED",
    "INCIDENT_WAITING_PARTS",
    "INCIDENT_RESOLVED",
    "INCIDENT_CANCELLED",
}
APPROVAL_ACTIONS = {"OWNER_APPROVAL_REQUESTED", "OWNER_APPROVAL_ANSWERED"}


def test_the_ten_actions_of_the_flow_are_declared() -> None:
    """D6, and the door `actions.py` described: each of these has a use case performing it."""
    assert INCIDENT_ACTIONS | APPROVAL_ACTIONS <= actions.ACTIONS


def test_the_owner_approval_entity_type_exists() -> None:
    assert actions.ENTITY_OWNER_APPROVAL == "OWNER_APPROVAL"
    assert actions.ENTITY_OWNER_APPROVAL in actions.ENTITY_TYPES


def test_the_incident_allowlist_is_exactly_what_it_should_be() -> None:
    """R6.2, and **exact** rather than a subset on purpose.

    The allowlist is the whole defence of rule 11 in this module — "by construction, not by
    care" — so a later change adding a free-text incident column to it (a resolution note,
    an operator comment) has to fail here rather than pass silently. The three names it
    starts with are `guest-portal-api`'s; the eight after are this flow's.
    """
    assert AUDITABLE_FIELDS["INCIDENT"] == frozenset(
        {
            "source",
            "status",
            "reservation_id",
            "category",
            "severity",
            "assigned_technician_id",
            "owner_approval_required",
            "estimated_cost",
            "approved_cost",
            "final_cost",
            "resolved_at",
        }
    )


def test_the_owner_approval_allowlist_is_exactly_what_d6_declares() -> None:
    """Without `approved_cost_applied`, which D6 listed and this change does not implement.

    It is not a column of `owner_approvals`, and `_check_auditable` says an audited diff
    "may only name a real, non-sensitive column of the entity" — a slot with no column has
    no type behind it. The fact D6 wanted recorded lives on `INCIDENT.approved_cost`
    instead. Raised by the security panel of section 4 and written into the change's D6.
    """
    assert AUDITABLE_FIELDS["OWNER_APPROVAL"] == frozenset(
        {"status", "amount", "related_type", "responded_by", "responded_at"}
    )


def test_no_allowlisted_name_is_absent_from_its_table() -> None:
    """What the removal above generalises: every auditable name is a real column.

    Read off the SQLAlchemy models rather than restated, so a column renamed in a migration
    takes this with it instead of leaving an allowlist entry pointing at nothing.
    """
    for entity, model in (
        (actions.ENTITY_INCIDENT, IncidentModel),
        (actions.ENTITY_OWNER_APPROVAL, OwnerApprovalModel),
    ):
        columns = set(model.__mapper__.columns.keys())

        assert AUDITABLE_FIELDS[entity] <= columns, (
            f"{entity} allows a name that is not a column: "
            f"{AUDITABLE_FIELDS[entity] - columns}"
        )


@pytest.mark.parametrize(
    ("entity", "field", "old", "new"),
    [
        (actions.ENTITY_INCIDENT, "category", IncidentCategory.OTHER, IncidentCategory.HVAC),
        (actions.ENTITY_INCIDENT, "severity", IncidentSeverity.MEDIUM, IncidentSeverity.HIGH),
        (actions.ENTITY_INCIDENT, "status", IncidentStatus.OPEN, IncidentStatus.CLASSIFIED),
        (actions.ENTITY_INCIDENT, "assigned_technician_id", None, uuid.uuid4()),
        (actions.ENTITY_INCIDENT, "owner_approval_required", False, True),
        (actions.ENTITY_INCIDENT, "resolved_at", None, datetime(2026, 8, 15, tzinfo=timezone.utc)),
        (actions.ENTITY_OWNER_APPROVAL, "status", OwnerApprovalStatus.PENDING, OwnerApprovalStatus.APPROVED),
        (actions.ENTITY_OWNER_APPROVAL, "amount", None, Decimal("450.00")),
        (actions.ENTITY_OWNER_APPROVAL, "related_type", None, OwnerApprovalRelatedType.INCIDENT),
        (actions.ENTITY_OWNER_APPROVAL, "responded_by", None, uuid.uuid4()),
        (actions.ENTITY_OWNER_APPROVAL, "responded_at", None, datetime(2026, 8, 15, tzinfo=timezone.utc)),
    ],
)
def test_every_new_field_survives_a_real_diff(
    entity: str, field: str, old: object, new: object
) -> None:
    """Membership in the allowlist is not the same as being storable.

    Each of these is exercised with the type its column actually carries — a native enum, a
    UUID, a bool, a `Decimal`, a timestamp — because `_storable` is what turns those into
    JSON, and a regression there would only show up on the field types nobody tried.
    """
    changes = ChangeSet(entity).diff(field, old, new)

    assert field in changes.as_dict()


@pytest.mark.parametrize(
    ("entity", "field"),
    [
        (actions.ENTITY_INCIDENT, "title"),
        (actions.ENTITY_INCIDENT, "description"),
        (actions.ENTITY_INCIDENT, "ai_summary"),
        (actions.ENTITY_INCIDENT, "ai_classification"),
        (actions.ENTITY_OWNER_APPROVAL, "reason"),
        (actions.ENTITY_OWNER_APPROVAL, "response_notes"),
    ],
)
def test_no_free_text_column_of_this_flow_can_be_audited(entity: str, field: str) -> None:
    """R6.2 and D4, and the half of rule 11 that says an exception does not propagate.

    Excepción 2 of rule 11 covers `incidents.title`/`description` as prose the reporter
    typed, and says of itself: "**No se propaga.** El valor no sale de estas dos columnas:
    no llega a `audit_logs.changes`". `ai_summary` and `ai_classification` are not under
    that exception at all — our classifier writes them, and the same paragraph adds that
    the exception "**No autoriza a un escritor nuestro**". `owner_approvals.reason` and
    `response_notes` are the same shape one table over.

    Both forms are refused, not only `diff`: `redacted()` would still assert in an
    append-only table that a field nobody declared had changed.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(entity).diff(field, None, "whatever was written there")

    with pytest.raises(AuditContractError):
        ChangeSet(entity).redacted(field)


def test_the_costs_are_a_real_diff_and_not_a_redaction() -> None:
    """The three costs are amounts, not values of rule 3 — the audit trail is what an owner
    reads to reconstruct what was authorised and what was spent."""
    changes = (
        ChangeSet(actions.ENTITY_INCIDENT)
        .diff("estimated_cost", None, "450.00")
        .diff("approved_cost", None, "450.00")
        .diff("final_cost", None, "520.00")
    )

    assert changes.as_dict() == {
        "estimated_cost": {"old": None, "new": "450.00"},
        "approved_cost": {"old": None, "new": "450.00"},
        "final_cost": {"old": None, "new": "520.00"},
    }
