"""The audit vocabulary `revenue-pricing` mints, and what it refuses to carry (D12, D13).

Its own file, like `test_maintenance_vocabulary.py` and `test_guest_portal_vocabulary.py`:
each change that widens the closed vocabulary of `app/audit/domain/` states what it added
and what it deliberately left out, next to its reason.
"""

import json
import uuid
from decimal import Decimal

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import (
    AUDITABLE_FIELDS,
    REDACT_ONLY_FIELDS,
    ChangeSet,
)
from app.pricing.domain.entities import UPDATABLE_RULE_FIELDS
from app.pricing.domain.enums import PriceRecommendationStatus

PRICING_ACTIONS = {
    "PRICING_RULE_CREATED",
    "PRICING_RULE_UPDATED",
    "PRICE_RECOMMENDATION_DECIDED",
    "PRICE_RECOMMENDATION_APPLIED_EXTERNAL",
}


def test_the_four_actions_are_declared() -> None:
    assert PRICING_ACTIONS <= actions.ACTIONS


def test_the_two_entity_types_exist() -> None:
    assert actions.ENTITY_PRICING_RULE == "PRICING_RULE"
    assert actions.ENTITY_PRICE_RECOMMENDATION == "PRICE_RECOMMENDATION"
    assert {actions.ENTITY_PRICING_RULE, actions.ENTITY_PRICE_RECOMMENDATION} <= (
        actions.ENTITY_TYPES
    )


def test_approving_and_rejecting_share_one_action() -> None:
    """D12: the outcome is a field of the entity, so splitting would put "what was decided
    about this price" in two places — the precedent `OWNER_APPROVAL_ANSWERED` set."""
    assert not {"PRICE_RECOMMENDATION_APPROVED", "PRICE_RECOMMENDATION_REJECTED"} & (
        actions.ACTIONS
    )


def test_applying_externally_is_not_a_decision_and_has_its_own_action() -> None:
    """D12: publishing a price in the OTA is a fact of the world, not a decision. A review
    asks the two things separately."""
    assert actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL != (
        actions.PRICE_RECOMMENDATION_DECIDED
    )


def test_the_generation_has_exactly_one_action_and_it_is_on_the_property() -> None:
    """The fifth named exception of rule 9 covers **the clock only** (task 8.1).

    An earlier reading of OQ1 exempted `POST /generate` too and this test pinned the absence
    of any generation verb. The reason OQ1 gave — «ausencia de actor» — is true of the clock
    and false of an endpoint that receives a `user_id` and an `ip`, so the human path now
    writes one row per property it repriced and only the nightly run stays exempt (decided
    by Jose on 2026-08-17, see design D12/OQ1).

    **One** verb, not two: the entity is the property, because a horizon is 60
    recommendations and D12 already recorded that `AuditLog.entity_id` is a mandatory single
    UUID with no execution column to hang one on.
    """
    generation_actions = {
        name for name in actions.ACTIONS if "PRICE_RECOMMENDATION" in name and "GENERAT" in name
    }

    assert generation_actions == {actions.PRICE_RECOMMENDATIONS_GENERATED}
    # It is not a `PRICE_RECOMMENDATION` action, so it stays out of that entity's allowlist:
    # `AUDITABLE_FIELDS["PRICE_RECOMMENDATION"]` is `{"status"}` and nothing here diffs.
    assert actions.PRICE_RECOMMENDATIONS_GENERATED not in {
        actions.PRICE_RECOMMENDATION_DECIDED,
        actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL,
    }


# --- the allowlists (R1.6, R5.2, and rule 11 by construction) --------------------------


def test_the_pricing_rule_allowlist_mirrors_the_entitys_writable_surface() -> None:
    """Exact, not a subset: a later change adding a free-text rule column has to fail here.

    It is also pinned against `UPDATABLE_RULE_FIELDS` so the two cannot drift — D12 derives
    one from the other, and a silent divergence would let a column be editable but
    unauditable, or auditable but not editable.
    """
    assert AUDITABLE_FIELDS["PRICING_RULE"] == frozenset(UPDATABLE_RULE_FIELDS)
    assert len(AUDITABLE_FIELDS["PRICING_RULE"]) == 12


def test_the_recommendation_allowlist_is_only_status() -> None:
    assert AUDITABLE_FIELDS["PRICE_RECOMMENDATION"] == frozenset({"status"})


@pytest.mark.parametrize(
    "field",
    ["explanation", "recommended_price", "pricing_rule_id", "confidence", "current_price",
     "date", "property_id"],
)
def test_no_other_recommendation_field_can_be_audited(field: str) -> None:
    """D13's "no se propaga", enforced by `ChangeSet` rather than by each use case.

    `explanation` is sink 14 of rule 11 and carries the `name` the manager typed into her
    own seasonality/event rules. `audit_logs.changes` is itself a rule-11 sink, so her text
    must not travel from one to the other.
    """
    change_set = ChangeSet(actions.ENTITY_PRICE_RECOMMENDATION)

    with pytest.raises(AuditContractError):
        change_set.diff(field, "before", "after")
    with pytest.raises(AuditContractError):
        change_set.redacted(field)


def test_a_status_transition_is_recordable() -> None:
    recorded = ChangeSet(actions.ENTITY_PRICE_RECOMMENDATION).diff(
        "status",
        PriceRecommendationStatus.RECOMMENDED.value,
        PriceRecommendationStatus.APPROVED.value,
    )

    assert recorded.as_dict() == {
        "status": {"old": "RECOMMENDED", "new": "APPROVED"}
    }


# --- the five JSONB columns are recordable ONLY as `{"changed": true}` -----------------


JSONB_COLUMNS = (
    "weekday_modifiers",
    "lead_time_rules",
    "occupancy_rules",
    "seasonality_rules",
    "event_rules",
)


@pytest.mark.parametrize("column", JSONB_COLUMNS)
def test_a_jsonb_rule_column_cannot_be_diffed(column: str) -> None:
    """The five are redact-only, so `diff()` refuses them by **name**.

    The refusal has to be by name rather than by value shape. An earlier version relied on
    `_storable` rejecting a `Mapping`/`list`, which left the path below wide open.
    """
    change_set = ChangeSet(actions.ENTITY_PRICING_RULE)
    value = {"monday": 10} if column == "weekday_modifiers" else [{"modifier_pct": 10}]

    with pytest.raises(AuditContractError):
        change_set.diff(column, None, value)


@pytest.mark.parametrize("column", JSONB_COLUMNS)
def test_a_jsonb_rule_column_cannot_be_diffed_pre_serialised(column: str) -> None:
    """The reachable path the shape-based guard missed (security panel, section 4).

    `_storable` accepts any `str`, so a caller that serialised the column first — the
    natural thing to reach for when JSONB "will not fit" — wrote the manager's typed text
    verbatim into `audit_logs.changes`, itself a rule-11 sink. `REDACT_ONLY_FIELDS` closes
    it because it refuses the field, not the encoding.
    """
    change_set = ChangeSet(actions.ENTITY_PRICING_RULE)
    typed_by_the_manager = json.dumps(
        [{"name": "wifi is hunter2", "modifier_pct": 10}]
    )

    with pytest.raises(AuditContractError):
        change_set.diff(column, None, typed_by_the_manager)


@pytest.mark.parametrize("column", JSONB_COLUMNS)
def test_no_encoding_of_a_jsonb_column_survives(column: str) -> None:
    """Every shape a caller could reach for, refused the same way."""
    change_set = ChangeSet(actions.ENTITY_PRICING_RULE)

    for encoded in ("[]", "{'name': 'x'}", repr([{"name": "x"}]), "", "0"):
        with pytest.raises(AuditContractError):
            change_set.diff(column, None, encoded)


@pytest.mark.parametrize("column", JSONB_COLUMNS)
def test_a_jsonb_rule_column_is_recordable_as_changed(column: str) -> None:
    recorded = ChangeSet(actions.ENTITY_PRICING_RULE).redacted(column)

    assert recorded.as_dict() == {column: {"changed": True}}


def test_a_seasonality_name_cannot_reach_the_audit_log_through_its_column() -> None:
    """The concrete leak the two tests above close, stated as the scenario it is."""
    typed_by_the_manager = [
        {"name": "DNI 12345678Z of the guest", "start_month": 7, "start_day": 1,
         "end_month": 8, "end_day": 31, "modifier_pct": 30}
    ]

    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_PRICING_RULE).diff(
            "seasonality_rules", None, typed_by_the_manager
        )


# --- the scalar columns of a rule are ordinary diffs -----------------------------------


def test_the_price_columns_are_ordinary_diffs() -> None:
    """None of the twelve is a rule-3 value, so none is on the denylist."""
    recorded = (
        ChangeSet(actions.ENTITY_PRICING_RULE)
        .diff("base_price", Decimal("100.00"), Decimal("120.00"))
        .diff("active", True, False)
        .diff("property_id", None, uuid.UUID(int=7))
    )

    assert recorded.as_dict()["base_price"] == {"old": "100.00", "new": "120.00"}
    assert recorded.as_dict()["active"] == {"old": True, "new": False}


def test_an_invented_rule_field_is_refused() -> None:
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_PRICING_RULE).diff("horizon_days", 60, 90)


# --- the redact-only mechanism cannot be keyed wrong ------------------------------------


def test_every_redact_only_entity_is_a_real_audited_entity() -> None:
    """`_check_recordable` does `REDACT_ONLY_FIELDS.get(entity_type, frozenset())`, which
    **fails open**: a mistyped key like `"PRICING_RULES"` would silently disable the guard
    for the entity it was meant to protect, and every existing test would stay green.

    Unlike the global `REDACTED_FIELDS`, which cannot be keyed wrong because it has no key.
    Raised by the section-4 security panel as the exposure of adding a second mechanism.
    """
    assert set(REDACT_ONLY_FIELDS) <= set(AUDITABLE_FIELDS), (
        f"unknown entity type in REDACT_ONLY_FIELDS: "
        f"{sorted(set(REDACT_ONLY_FIELDS) - set(AUDITABLE_FIELDS))}"
    )


def test_every_redact_only_field_is_auditable_at_all() -> None:
    """A redact-only field must also be on its entity's allowlist.

    Otherwise `redacted()` fails too — `_check_auditable` runs for both methods — and the
    column becomes unrecordable in any form rather than recordable as `{"changed": true}`.
    That is the trap `PMS_CREDENTIAL.secret_encrypted`'s comment describes for the global
    denylist, and it applies to this mechanism identically.
    """
    for entity_type, fields in REDACT_ONLY_FIELDS.items():
        assert fields <= AUDITABLE_FIELDS[entity_type], (
            f"{entity_type}: {sorted(fields - AUDITABLE_FIELDS[entity_type])} are "
            "redact-only but not auditable, so they cannot be recorded at all"
        )
