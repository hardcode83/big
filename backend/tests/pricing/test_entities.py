import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.pricing.domain.entities import (
    MAX_ENTRIES_PER_ARRAY,
    MAX_MODIFIER_NAME_LENGTH,
    MAX_PRICE_VALUE,
    UPDATABLE_RULE_FIELDS,
    PriceRecommendation,
    PricingRule,
)
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import (
    InvalidRecommendationTransitionError,
    PricingValidationError,
)


def test_pricing_rule_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    rule = PricingRule(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Madrid base",
        base_price=Decimal("90.00"),
        min_price=Decimal("60.00"),
        max_price=Decimal("180.00"),
        created_at=now,
        updated_at=now,
    )

    assert rule.property_id is None
    assert rule.active is True
    assert rule.max_daily_change_pct == Decimal("20.00")
    assert rule.weekday_modifiers == {}
    assert rule.lead_time_rules == []
    assert rule.occupancy_rules == []
    assert rule.seasonality_rules == []
    assert rule.event_rules == []


def test_pricing_rule_json_defaults_are_not_shared_between_instances() -> None:
    """A bare `= {}` default would make every rule share one dict."""
    now = datetime.now(timezone.utc)
    common = {
        "tenant_id": uuid.uuid4(),
        "name": "shared-default probe",
        "base_price": Decimal("90.00"),
        "min_price": Decimal("60.00"),
        "max_price": Decimal("180.00"),
        "created_at": now,
        "updated_at": now,
    }
    first = PricingRule(id=uuid.uuid4(), **common)
    second = PricingRule(id=uuid.uuid4(), **common)

    first.weekday_modifiers["friday"] = 15
    first.event_rules.append({"name": "Local Festival", "modifier_pct": 25})

    assert second.weekday_modifiers == {}
    assert second.event_rules == []


def test_price_recommendation_instantiates_with_defaults() -> None:
    recommendation = PriceRecommendation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        pricing_rule_id=uuid.uuid4(),
        date=date(2026, 8, 15),
        recommended_price=Decimal("135.00"),
        explanation="Weekend in high season, +50% over base price.",
        created_at=datetime.now(timezone.utc),
    )

    assert recommendation.current_price is None
    assert recommendation.confidence == Decimal("1.00")
    assert recommendation.status is PriceRecommendationStatus.RECOMMENDED


# --- PricingRule.create / validate (R1.3, R1.4; design D16) ---------------------------

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
TENANT_ID = uuid.uuid4()


def create_rule(**overrides: Any) -> PricingRule:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT_ID,
        "name": "Madrid base",
        "base_price": Decimal("100.00"),
        "min_price": Decimal("50.00"),
        "max_price": Decimal("200.00"),
        "now": NOW,
    }
    fields.update(overrides)
    return PricingRule.create(**fields)


def failing_field(**overrides: Any) -> str:
    with pytest.raises(PricingValidationError) as caught:
        create_rule(**overrides)
    return caught.value.field


def test_a_valid_rule_is_created_and_timestamped() -> None:
    rule = create_rule()

    assert rule.created_at == NOW
    assert rule.updated_at == NOW
    assert rule.active is True
    assert rule.max_daily_change_pct == Decimal("20.00")


def test_min_price_may_not_exceed_max_price() -> None:
    assert failing_field(min_price=Decimal("300.00")) == "min_price"


def test_min_price_may_equal_max_price() -> None:
    rule = create_rule(
        min_price=Decimal("100.00"),
        max_price=Decimal("100.00"),
        base_price=Decimal("100.00"),
    )

    assert rule.min_price == rule.max_price


@pytest.mark.parametrize("base", [Decimal("10.00"), Decimal("500.00")])
def test_base_price_must_sit_inside_the_bounds(base: Decimal) -> None:
    assert failing_field(base_price=base) == "base_price"


@pytest.mark.parametrize("base", [Decimal("50.00"), Decimal("200.00")])
def test_base_price_may_sit_on_either_bound(base: Decimal) -> None:
    assert create_rule(base_price=base).base_price == base


@pytest.mark.parametrize("pct", [Decimal("-1"), Decimal("100.01")])
def test_the_daily_cap_must_be_a_percentage(pct: Decimal) -> None:
    assert failing_field(max_daily_change_pct=pct) == "max_daily_change_pct"


@pytest.mark.parametrize("pct", [Decimal("0"), Decimal("100")])
def test_the_daily_cap_may_sit_on_either_bound(pct: Decimal) -> None:
    assert create_rule(max_daily_change_pct=pct).max_daily_change_pct == pct


@pytest.mark.parametrize("name", ["", "   "])
def test_a_rule_needs_a_name(name: str) -> None:
    assert failing_field(name=name) == "name"


def test_a_rule_name_is_bounded_by_its_column() -> None:
    assert failing_field(name="x" * 201) == "name"


# --- the five JSONB columns (R1.4) ----------------------------------------------------


def test_weekday_modifiers_reject_an_unknown_day() -> None:
    assert failing_field(weekday_modifiers={"lunes": 10}) == "weekday_modifiers"


def test_weekday_modifiers_accept_the_seven_english_days() -> None:
    days = {
        "monday": 0, "tuesday": 0, "wednesday": 0, "thursday": 5,
        "friday": 15, "saturday": 20, "sunday": 10,
    }

    assert create_rule(weekday_modifiers=days).weekday_modifiers == days


def test_weekday_modifiers_reject_a_non_numeric_value() -> None:
    assert failing_field(weekday_modifiers={"monday": "10"}) == "weekday_modifiers"


def test_lead_time_rules_require_their_two_keys() -> None:
    assert failing_field(lead_time_rules=[{"days_before": 3}]) == "lead_time_rules"
    assert failing_field(lead_time_rules=[{"modifier_pct": 3}]) == "lead_time_rules"


def test_lead_time_rules_reject_an_unknown_key() -> None:
    assert failing_field(
        lead_time_rules=[{"days_before": 3, "modifier_pct": -10, "extra": 1}]
    ) == "lead_time_rules"


def test_lead_time_days_before_must_be_a_whole_non_negative_number() -> None:
    assert failing_field(lead_time_rules=[{"days_before": -1, "modifier_pct": 0}])
    assert failing_field(lead_time_rules=[{"days_before": 1.5, "modifier_pct": 0}])


def test_occupancy_rules_bound_their_threshold_to_a_percentage() -> None:
    assert failing_field(
        occupancy_rules=[{"occupancy_pct_above": 101, "modifier_pct": 5}]
    ) == "occupancy_rules"
    assert failing_field(
        occupancy_rules=[{"occupancy_pct_above": -1, "modifier_pct": 5}]
    ) == "occupancy_rules"


def test_seasonality_rules_validate_their_calendar() -> None:
    base = {"name": "s", "start_month": 7, "start_day": 1, "end_month": 8, "end_day": 31,
            "modifier_pct": 30}

    assert create_rule(seasonality_rules=[base]).seasonality_rules == [base]
    assert failing_field(seasonality_rules=[{**base, "start_month": 13}])
    assert failing_field(seasonality_rules=[{**base, "start_day": 0}])
    assert failing_field(seasonality_rules=[{**base, "start_month": 2, "start_day": 30}])


def test_a_season_may_wrap_the_year_end() -> None:
    """D3 hole 1 — the most obvious season of all must stay declarable."""
    wrapping = {"name": "christmas", "start_month": 12, "start_day": 20, "end_month": 1,
                "end_day": 6, "modifier_pct": 40}

    assert create_rule(seasonality_rules=[wrapping]).seasonality_rules == [wrapping]


def test_an_event_may_be_an_exact_date() -> None:
    event = {"name": "Local Festival", "date": "2026-08-15", "modifier_pct": 25}

    assert create_rule(event_rules=[event]).event_rules == [event]


def test_an_event_may_reference_the_holiday_catalogue() -> None:
    event = {"holidays": "ES_NATIONAL", "modifier_pct": 15}

    assert create_rule(event_rules=[event]).event_rules == [event]


def test_an_event_carrying_both_forms_is_rejected() -> None:
    """D7: `event_rules` admits two forms, and an entry with both is neither."""
    assert failing_field(
        event_rules=[{"name": "x", "date": "2026-08-15", "holidays": "ES_NATIONAL",
                      "modifier_pct": 15}]
    ) == "event_rules"


def test_an_event_carrying_neither_form_is_rejected() -> None:
    assert failing_field(event_rules=[{"modifier_pct": 15}]) == "event_rules"


def test_an_unknown_holiday_catalogue_is_rejected() -> None:
    """D7: an open namespace would invite keys nobody resolves."""
    assert failing_field(
        event_rules=[{"holidays": "ES_MADRID", "modifier_pct": 15}]
    ) == "event_rules"


def test_an_event_date_must_be_a_real_iso_date() -> None:
    assert failing_field(
        event_rules=[{"name": "x", "date": "2026-13-40", "modifier_pct": 15}]
    ) == "event_rules"
    assert failing_field(event_rules=[{"name": "x", "date": 20260815, "modifier_pct": 15}])


# --- the free-text names that reach the rule-11 sink (D13) ----------------------------


@pytest.mark.parametrize("column", ["seasonality_rules", "event_rules"])
def test_a_modifier_name_is_bounded_to_a_hundred_characters(column: str) -> None:
    """D13's mitigation: this `name` is the one thing in `explanation` we do not compose."""
    entry: dict[str, Any] = (
        {"name": "x" * 101, "start_month": 7, "start_day": 1, "end_month": 8,
         "end_day": 31, "modifier_pct": 30}
        if column == "seasonality_rules"
        else {"name": "x" * 101, "date": "2026-08-15", "modifier_pct": 25}
    )

    assert failing_field(**{column: [entry]}) == column


@pytest.mark.parametrize("column", ["seasonality_rules", "event_rules"])
def test_a_modifier_name_of_exactly_the_limit_is_accepted(column: str) -> None:
    entry: dict[str, Any] = (
        {"name": "x" * MAX_MODIFIER_NAME_LENGTH, "start_month": 7, "start_day": 1,
         "end_month": 8, "end_day": 31, "modifier_pct": 30}
        if column == "seasonality_rules"
        else {"name": "x" * MAX_MODIFIER_NAME_LENGTH, "date": "2026-08-15",
              "modifier_pct": 25}
    )

    assert create_rule(**{column: [entry]})


# --- what the section-1 security panel asked for (its F3) -----------------------------


@pytest.mark.parametrize(
    ("column", "entry"),
    [
        ("lead_time_rules", {"days_before": "3", "modifier_pct": -10}),
        ("occupancy_rules", {"occupancy_pct_above": " 50 ", "modifier_pct": 5}),
    ],
)
def test_a_threshold_written_as_a_string_is_rejected(column: str, entry: dict) -> None:
    """A JSON string survived the calculator's comparison or its parse — never both."""
    assert failing_field(**{column: [entry]}) == column


@pytest.mark.parametrize(
    ("column", "entry"),
    [
        ("lead_time_rules", {"days_before": True, "modifier_pct": -10}),
        ("occupancy_rules", {"occupancy_pct_above": True, "modifier_pct": 5}),
    ],
)
def test_a_boolean_threshold_is_rejected(column: str, entry: dict) -> None:
    """`1 <= True` is `True`, so booleans reach the calculator where strings do not."""
    assert failing_field(**{column: [entry]}) == column


@pytest.mark.parametrize(
    ("column", "entry"),
    [
        ("weekday_modifiers", None),
        ("lead_time_rules", {"days_before": 3, "modifier_pct": -100.01}),
        ("occupancy_rules", {"occupancy_pct_above": 50, "modifier_pct": -101}),
    ],
)
def test_a_modifier_may_not_discount_more_than_the_whole_price(
    column: str, entry: Any
) -> None:
    """Below -100% the price goes negative, and only `min_price` would catch it."""
    value = {"monday": -101} if column == "weekday_modifiers" else [entry]

    assert failing_field(**{column: value}) == column


@pytest.mark.parametrize("column", ["seasonality_rules", "event_rules"])
@pytest.mark.parametrize("name", [None, 42, "", "   "])
def test_a_modifier_name_must_be_a_non_empty_string(column: str, name: Any) -> None:
    entry: dict[str, Any] = (
        {"name": name, "start_month": 7, "start_day": 1, "end_month": 8, "end_day": 31,
         "modifier_pct": 30}
        if column == "seasonality_rules"
        else {"name": name, "date": "2026-08-15", "modifier_pct": 25}
    )

    assert failing_field(**{column: [entry]}) == column


@pytest.mark.parametrize("catalogue", [{}, [], 42, None])
def test_a_non_string_holiday_catalogue_is_rejected_not_crashed(catalogue: Any) -> None:
    """`SUPPORTED_HOLIDAY_CATALOGS` is a frozenset, so `{} not in it` raises `TypeError`.

    That is not a `PricingDomainError`, so it would answer 500 where R1.4 promises 422.
    Found by the section-2 security panel.
    """
    assert failing_field(
        event_rules=[{"holidays": catalogue, "modifier_pct": 15}]
    ) == "event_rules"


# --- the prices must fit the column that stores them (R1.3) ---------------------------


@pytest.mark.parametrize("column", ["base_price", "min_price", "max_price"])
def test_a_price_beyond_the_column_is_rejected(column: str) -> None:
    """`Numeric(10, 2)`. Unbounded, `validate()` accepted a rule that later killed the
    calculator's final `quantize` with `InvalidOperation` — a 500 on R1.3's 422 path."""
    huge = Decimal("1E+30")
    overrides: dict[str, Any] = {
        "base_price": {"base_price": huge, "min_price": huge, "max_price": huge},
        "min_price": {"min_price": Decimal("-1")},
        "max_price": {"max_price": huge},
    }[column]

    assert failing_field(**overrides) == column


def test_a_price_at_the_column_ceiling_is_accepted() -> None:
    rule = create_rule(
        base_price=MAX_PRICE_VALUE, min_price=MAX_PRICE_VALUE, max_price=MAX_PRICE_VALUE
    )

    assert rule.max_price == MAX_PRICE_VALUE


def test_a_price_with_more_than_two_decimals_is_rejected() -> None:
    """Postgres would round it silently into a price nobody asked for."""
    assert failing_field(base_price=Decimal("100.005")) == "base_price"


def test_trailing_zeros_are_not_extra_decimals() -> None:
    assert create_rule(base_price=Decimal("100.000")).base_price == Decimal("100.00")


def test_the_daily_cap_must_also_fit_its_column() -> None:
    assert failing_field(max_daily_change_pct=Decimal("20.005")) == "max_daily_change_pct"


# --- the entity owns its JSONB, the caller does not (D16) -----------------------------


def test_create_copies_the_json_the_caller_passed() -> None:
    """Otherwise appending to that list mutates a rule `validate()` already blessed."""
    events = [{"name": "e1", "date": "2026-08-15", "modifier_pct": 10}]

    rule = create_rule(event_rules=events)
    events.append({"name": "e2", "date": "2026-08-16", "modifier_pct": 999})

    assert rule.event_rules == [{"name": "e1", "date": "2026-08-15", "modifier_pct": 10}]


def test_create_copies_nested_objects_too() -> None:
    events = [{"name": "e1", "date": "2026-08-15", "modifier_pct": 10}]

    rule = create_rule(event_rules=events)
    events[0]["modifier_pct"] = 999

    assert rule.event_rules[0]["modifier_pct"] == 10


def test_update_details_copies_the_json_the_caller_passed() -> None:
    rule = create_rule()
    seasons = [{"name": "s", "start_month": 7, "start_day": 1, "end_month": 8,
                "end_day": 31, "modifier_pct": 30}]

    rule.update_details({"seasonality_rules": seasons}, now=NOW)
    seasons[0]["modifier_pct"] = 999

    assert rule.seasonality_rules[0]["modifier_pct"] == 30


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_number_is_rejected(value: float) -> None:
    assert failing_field(
        lead_time_rules=[{"days_before": 3, "modifier_pct": value}]
    ) == "lead_time_rules"


@pytest.mark.parametrize(
    "column",
    ["lead_time_rules", "occupancy_rules", "seasonality_rules", "event_rules"],
)
def test_each_array_is_capped(column: str) -> None:
    """Seasons and events apply ALL that match, so N rules are N sentences x 60 days."""
    entry: dict[str, Any] = {
        "lead_time_rules": {"days_before": 3, "modifier_pct": -10},
        "occupancy_rules": {"occupancy_pct_above": 50, "modifier_pct": 5},
        "seasonality_rules": {"name": "s", "start_month": 7, "start_day": 1,
                              "end_month": 8, "end_day": 31, "modifier_pct": 30},
        "event_rules": {"name": "e", "date": "2026-08-15", "modifier_pct": 25},
    }[column]

    assert failing_field(**{column: [entry] * (MAX_ENTRIES_PER_ARRAY + 1)}) == column
    assert create_rule(**{column: [entry] * MAX_ENTRIES_PER_ARRAY})


@pytest.mark.parametrize(
    "column",
    ["lead_time_rules", "occupancy_rules", "seasonality_rules", "event_rules"],
)
def test_an_array_column_must_be_an_array(column: str) -> None:
    assert failing_field(**{column: {"days_before": 3}}) == column


def test_weekday_modifiers_must_be_an_object() -> None:
    assert failing_field(weekday_modifiers=[{"monday": 1}]) == "weekday_modifiers"


@pytest.mark.parametrize("falsy", [0, "", False, 0.0])
@pytest.mark.parametrize(
    "column",
    ["weekday_modifiers", "lead_time_rules", "occupancy_rules", "seasonality_rules",
     "event_rules"],
)
def test_a_falsy_json_value_is_rejected_not_swallowed(column: str, falsy: Any) -> None:
    """Omitting a column means empty; **passing** `0` means passing a non-object.

    A truthy gate in `create` swapped the second for the first before `validate()` ran, so
    a malformed rule was silently accepted where R1.4 promises a 422 naming the field.
    Found by the section-2 QA panel on re-review.
    """
    assert failing_field(**{column: falsy}) == column


@pytest.mark.parametrize(
    "column",
    ["weekday_modifiers", "lead_time_rules", "occupancy_rules", "seasonality_rules",
     "event_rules"],
)
def test_an_omitted_json_column_still_defaults_to_empty(column: str) -> None:
    """The other half of the same line: `None` — or absence — is genuinely "empty"."""
    rule = create_rule(**{column: None})

    assert getattr(rule, column) == ({} if column == "weekday_modifiers" else [])


def test_an_array_entry_must_be_an_object() -> None:
    assert failing_field(lead_time_rules=["days_before"]) == "lead_time_rules"


# --- update_details (R1.3, R1.4, R1.6) ------------------------------------------------


def test_update_details_applies_only_the_named_fields_and_reports_them() -> None:
    rule = create_rule()
    later = NOW.replace(hour=12)

    changed = rule.update_details({"name": "Madrid summer", "active": False}, now=later)

    assert changed == frozenset({"name", "active"})
    assert rule.name == "Madrid summer"
    assert rule.active is False
    assert rule.base_price == Decimal("100.00")
    assert rule.updated_at == later


def test_update_details_reports_nothing_when_the_values_are_unchanged() -> None:
    rule = create_rule()

    changed = rule.update_details({"name": "Madrid base"}, now=NOW.replace(hour=12))

    assert changed == frozenset()
    assert rule.updated_at == NOW  # nothing moved, so the timestamp does not either


def test_update_details_rejects_a_field_that_is_not_updatable() -> None:
    rule = create_rule()

    with pytest.raises(PricingValidationError) as caught:
        rule.update_details({"tenant_id": uuid.uuid4()}, now=NOW)

    assert caught.value.field == "tenant_id"


def test_update_details_revalidates_the_whole_rule() -> None:
    """A PATCH of one bound must not be judged against the old value of the other."""
    rule = create_rule()

    with pytest.raises(PricingValidationError) as caught:
        rule.update_details({"min_price": Decimal("500.00")}, now=NOW)

    assert caught.value.field == "min_price"


def test_a_rejected_update_leaves_the_entity_untouched() -> None:
    rule = create_rule()

    with pytest.raises(PricingValidationError):
        rule.update_details({"max_price": Decimal("10.00")}, now=NOW.replace(hour=12))

    assert rule.max_price == Decimal("200.00")
    assert rule.updated_at == NOW


def test_the_updatable_fields_are_the_twelve_the_design_names() -> None:
    assert UPDATABLE_RULE_FIELDS == frozenset(
        {
            "name", "active", "property_id", "base_price", "min_price", "max_price",
            "max_daily_change_pct", "weekday_modifiers", "lead_time_rules",
            "occupancy_rules", "seasonality_rules", "event_rules",
        }
    )


# --- PriceRecommendation state machine (R5.2, R5.3, R5.4; DoD §28.19) -----------------

S = PriceRecommendationStatus

LEGAL_DECISIONS = {(S.RECOMMENDED, S.APPROVED), (S.RECOMMENDED, S.REJECTED)}


def make_recommendation(status: PriceRecommendationStatus = S.RECOMMENDED) -> PriceRecommendation:
    recommendation = PriceRecommendation.create(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        property_id=uuid.uuid4(),
        pricing_rule_id=uuid.uuid4(),
        date=date(2026, 9, 1),
        recommended_price=Decimal("120.00"),
        explanation="Base price 100.00 EUR. Recommended 120.00 EUR.",
        now=NOW,
    )
    recommendation.status = status
    return recommendation


def test_a_created_recommendation_starts_recommended_with_full_confidence() -> None:
    """R6.3 — `confidence` is 1.00 while the calculation is deterministic."""
    recommendation = make_recommendation()

    assert recommendation.status is S.RECOMMENDED
    assert recommendation.confidence == Decimal("1.00")
    assert recommendation.current_price is None  # R5.5: no PMS, so no published price
    assert recommendation.created_at == NOW


@pytest.mark.parametrize("origin", list(S))
@pytest.mark.parametrize("target", list(S))
def test_the_full_decision_matrix(origin: PriceRecommendationStatus,
                                  target: PriceRecommendationStatus) -> None:
    """The whole 5x5, invalid moves included — `steering/testing.md`, DoD §28.19."""
    recommendation = make_recommendation(origin)

    if (origin, target) in LEGAL_DECISIONS:
        recommendation.decide(target)
        assert recommendation.status is target
    else:
        with pytest.raises(InvalidRecommendationTransitionError):
            recommendation.decide(target)
        assert recommendation.status is origin  # R5.4: the state is left intact


@pytest.mark.parametrize("origin", list(S))
def test_only_an_approved_recommendation_may_be_marked_applied_external(
    origin: PriceRecommendationStatus,
) -> None:
    recommendation = make_recommendation(origin)

    if origin is S.APPROVED:
        recommendation.mark_applied_external()
        assert recommendation.status is S.APPLIED_EXTERNAL
    else:
        with pytest.raises(InvalidRecommendationTransitionError):
            recommendation.mark_applied_external()
        assert recommendation.status is origin


@pytest.mark.parametrize("status", ["APPROVED", 123, None])
def test_decide_refuses_something_that_is_not_a_status(status: Any) -> None:
    """R5.4 is a 409, and `f"decide:{status.value}"` on a bare string is a 500.

    Found by the section-2 QA panel: the operation key was built before the membership
    check, so a caller that forgot to coerce through the enum crashed instead.
    """
    recommendation = make_recommendation(S.RECOMMENDED)

    with pytest.raises(InvalidRecommendationTransitionError):
        recommendation.decide(status)

    assert recommendation.status is S.RECOMMENDED


def test_decide_refuses_applied_external_which_has_its_own_operation() -> None:
    """Three legal transitions, and `APPLIED_EXTERNAL` is not one `decide` may reach."""
    recommendation = make_recommendation(S.APPROVED)

    with pytest.raises(InvalidRecommendationTransitionError):
        recommendation.decide(S.APPLIED_EXTERNAL)

    assert recommendation.status is S.APPROVED


def test_nothing_produces_or_leaves_draft() -> None:
    """`DRAFT` is declared by PRD §7.18 and written by no path of this change."""
    assert PriceRecommendation.create(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        property_id=uuid.uuid4(),
        pricing_rule_id=uuid.uuid4(),
        date=date(2026, 9, 1),
        recommended_price=Decimal("120.00"),
        explanation="x",
        now=NOW,
    ).status is not S.DRAFT

    for target in S:
        assert (S.DRAFT, target) not in LEGAL_DECISIONS
