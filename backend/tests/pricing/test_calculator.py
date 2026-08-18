"""The deterministic price formula (R2.1, R2.2, R2.4, R2.5; design D2, D3, D4).

Written before `app/pricing/domain/calculator.py` exists: `steering/testing.md` mandates
TDD in `domain/` with a real invariant and names "guardrails de pricing" literally.
"""

import uuid
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import pytest

from app.pricing.domain.calculator import (
    AppliedGuardrail,
    AppliedModifier,
    PriceCalculation,
    calculate_price,
)
from app.pricing.domain.entities import PricingRule

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def make_rule(**overrides: Any) -> PricingRule:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "test rule",
        "base_price": Decimal("100.00"),
        "min_price": Decimal("10.00"),
        "max_price": Decimal("1000.00"),
        "max_daily_change_pct": Decimal("100.00"),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return PricingRule(**fields)


def compute(rule: PricingRule, **overrides: Any) -> PriceCalculation:
    kwargs: dict[str, Any] = {
        "target_date": date(2026, 9, 1),  # a Tuesday
        "days_before": 16,
        "occupancy_pct": Decimal("0"),
        "previous_price": None,
    }
    kwargs.update(overrides)
    return calculate_price(rule, **kwargs)


def kinds(calculation: PriceCalculation) -> list[str]:
    return [modifier.kind for modifier in calculation.modifiers]


# --- weekday (R2.1, D3 hole 3) -------------------------------------------------------


def test_weekday_modifier_applies_over_the_base_price() -> None:
    rule = make_rule(weekday_modifiers={"saturday": 20})

    calculation = compute(rule, target_date=date(2026, 9, 5))  # Saturday

    assert calculation.base_price == Decimal("100.00")
    assert [(m.kind, m.name, m.modifier_pct) for m in calculation.modifiers] == [
        ("weekday", "saturday", Decimal("20"))
    ]
    assert calculation.modifiers[0].price_after == Decimal("120.00")
    assert calculation.recommended_price == Decimal("120.00")


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 8, 31), "monday"),
        (date(2026, 9, 1), "tuesday"),
        (date(2026, 9, 2), "wednesday"),
        (date(2026, 9, 3), "thursday"),
        (date(2026, 9, 4), "friday"),
        (date(2026, 9, 5), "saturday"),
        (date(2026, 9, 6), "sunday"),
    ],
)
def test_the_weekday_key_is_the_lowercase_english_name(day: date, expected: str) -> None:
    """Indexed without `strftime`, whose output follows the process locale (D3)."""
    rule = make_rule(weekday_modifiers={expected: 10})

    calculation = compute(rule, target_date=day)

    assert [m.name for m in calculation.modifiers] == [expected]


def test_a_missing_weekday_key_is_worth_zero_and_leaves_no_trace() -> None:
    rule = make_rule(weekday_modifiers={"friday": 15})

    calculation = compute(rule, target_date=date(2026, 9, 1))  # Tuesday

    assert calculation.modifiers == ()
    assert calculation.recommended_price == Decimal("100.00")


# --- lead time (R2.2) ----------------------------------------------------------------


def test_the_applicable_lead_time_rule_with_the_smallest_days_before_wins() -> None:
    rule = make_rule(
        lead_time_rules=[
            {"days_before": 1, "modifier_pct": -20},
            {"days_before": 3, "modifier_pct": -10},
            {"days_before": 30, "modifier_pct": 5},
        ]
    )

    calculation = compute(rule, days_before=2)

    assert [(m.kind, m.modifier_pct) for m in calculation.modifiers] == [
        ("lead_time", Decimal("-10"))
    ]
    assert calculation.recommended_price == Decimal("90.00")


def test_a_lead_time_rule_applies_when_days_before_is_at_or_below_its_threshold() -> None:
    rule = make_rule(lead_time_rules=[{"days_before": 3, "modifier_pct": -10}])

    assert compute(rule, days_before=3).modifiers != ()
    assert compute(rule, days_before=4).modifiers == ()


def test_no_applicable_lead_time_rule_leaves_the_price_untouched() -> None:
    rule = make_rule(lead_time_rules=[{"days_before": 1, "modifier_pct": -20}])

    calculation = compute(rule, days_before=45)

    assert calculation.modifiers == ()
    assert calculation.recommended_price == Decimal("100.00")


# --- occupancy (R2.2) ----------------------------------------------------------------


def test_the_applicable_occupancy_rule_with_the_highest_threshold_wins() -> None:
    rule = make_rule(
        occupancy_rules=[
            {"occupancy_pct_above": 80, "modifier_pct": 15},
            {"occupancy_pct_above": 50, "modifier_pct": 5},
            {"occupancy_pct_above": 20, "modifier_pct": -5},
        ]
    )

    calculation = compute(rule, occupancy_pct=Decimal("60"))

    assert [(m.kind, m.modifier_pct) for m in calculation.modifiers] == [
        ("occupancy", Decimal("5"))
    ]
    assert calculation.recommended_price == Decimal("105.00")


def test_an_occupancy_rule_applies_at_its_threshold() -> None:
    rule = make_rule(occupancy_rules=[{"occupancy_pct_above": 50, "modifier_pct": 5}])

    assert compute(rule, occupancy_pct=Decimal("50")).modifiers != ()
    assert compute(rule, occupancy_pct=Decimal("49.99")).modifiers == ()


# --- seasonality and events: all of them apply (R2.2) --------------------------------


def test_every_matching_season_and_event_applies_in_declaration_order() -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30},
            {"name": "august_peak", "start_month": 8, "start_day": 1, "end_month": 8,
             "end_day": 20, "modifier_pct": 10},
        ],
        event_rules=[{"name": "Local Festival", "date": "2026-08-15", "modifier_pct": 25}],
    )

    calculation = compute(rule, target_date=date(2026, 8, 15))

    assert [(m.kind, m.name) for m in calculation.modifiers] == [
        ("season", "high_summer"),
        ("season", "august_peak"),
        ("event", "Local Festival"),
    ]
    # 100 * 1.30 * 1.10 * 1.25
    assert calculation.recommended_price == Decimal("178.75")


def test_seasons_are_evaluated_before_events() -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "s", "start_month": 8, "start_day": 1, "end_month": 8, "end_day": 31,
             "modifier_pct": 10}
        ],
        event_rules=[{"name": "e", "date": "2026-08-15", "modifier_pct": 10}],
    )

    assert kinds(compute(rule, target_date=date(2026, 8, 15))) == ["season", "event"]


def test_the_full_chain_runs_in_the_prd_order() -> None:
    """Weekday -> lead time -> occupancy -> season -> event (R2.1)."""
    rule = make_rule(
        weekday_modifiers={"saturday": 20},
        lead_time_rules=[{"days_before": 3, "modifier_pct": -10}],
        occupancy_rules=[{"occupancy_pct_above": 50, "modifier_pct": 5}],
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30}
        ],
        event_rules=[{"name": "Local Festival", "date": "2026-08-15", "modifier_pct": 25}],
    )

    calculation = compute(
        rule,
        target_date=date(2026, 8, 15),  # a Saturday
        days_before=2,
        occupancy_pct=Decimal("60"),
    )

    assert kinds(calculation) == ["weekday", "lead_time", "occupancy", "season", "event"]
    assert [m.price_after for m in calculation.modifiers] == [
        Decimal("120"),
        Decimal("108"),
        Decimal("113.4"),
        Decimal("147.42"),
        Decimal("184.275"),
    ]
    assert calculation.recommended_price == Decimal("184.28")  # ROUND_HALF_UP, once


# --- D3 hole 1: an annual range that crosses the year end -----------------------------


@pytest.mark.parametrize(
    "day",
    [date(2026, 12, 20), date(2026, 12, 31), date(2026, 1, 1), date(2026, 1, 6)],
)
def test_a_season_whose_end_precedes_its_start_wraps_around_the_year_end(day: date) -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "christmas", "start_month": 12, "start_day": 20, "end_month": 1,
             "end_day": 6, "modifier_pct": 40}
        ]
    )

    assert [m.name for m in compute(rule, target_date=day).modifiers] == ["christmas"]


@pytest.mark.parametrize("day", [date(2026, 12, 19), date(2026, 1, 7), date(2026, 6, 1)])
def test_a_wrapping_season_does_not_match_outside_its_two_halves(day: date) -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "christmas", "start_month": 12, "start_day": 20, "end_month": 1,
             "end_day": 6, "modifier_pct": 40}
        ]
    )

    assert compute(rule, target_date=day).modifiers == ()


def test_a_season_is_recurring_and_ignores_the_year() -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30}
        ]
    )

    for year in (2025, 2026, 2027, 2031):
        assert compute(rule, target_date=date(year, 7, 15)).modifiers != ()


@pytest.mark.parametrize("day", [date(2026, 7, 1), date(2026, 8, 31)])
def test_a_season_range_is_inclusive_at_both_ends(day: date) -> None:
    rule = make_rule(
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30}
        ]
    )

    assert compute(rule, target_date=day).modifiers != ()


# --- D3 hole 2: an event is an exact date, with its year ------------------------------


def test_an_event_matches_its_exact_date_only() -> None:
    rule = make_rule(event_rules=[{"name": "Local Festival", "date": "2026-08-15",
                                   "modifier_pct": 25}])

    assert compute(rule, target_date=date(2026, 8, 15)).modifiers != ()
    assert compute(rule, target_date=date(2027, 8, 15)).modifiers == ()
    assert compute(rule, target_date=date(2026, 8, 16)).modifiers == ()


# --- D7: the holiday catalogue form of an event rule ----------------------------------


def test_a_holiday_catalogue_event_matches_every_national_holiday() -> None:
    rule = make_rule(event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}])

    calculation = compute(rule, target_date=date(2026, 8, 15))  # Assumption of Mary

    assert [(m.kind, m.name, m.modifier_pct) for m in calculation.modifiers] == [
        ("event", "Assumption of Mary", Decimal("15"))
    ]


def test_a_holiday_catalogue_event_does_not_match_an_ordinary_day() -> None:
    rule = make_rule(event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}])

    assert compute(rule, target_date=date(2026, 8, 16)).modifiers == ()


def test_a_holiday_catalogue_event_applies_once_on_a_holiday() -> None:
    rule = make_rule(event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}])

    calculation = compute(rule, target_date=date(2026, 12, 25))

    assert len(calculation.modifiers) == 1
    assert calculation.recommended_price == Decimal("115.00")


# --- determinism (R2.5) ---------------------------------------------------------------


def test_the_same_arguments_always_give_the_same_result() -> None:
    rule = make_rule(
        weekday_modifiers={"saturday": 20},
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30}
        ],
    )
    kwargs = {"target_date": date(2026, 8, 15), "days_before": 3,
              "occupancy_pct": Decimal("60"), "previous_price": None}

    assert calculate_price(rule, **kwargs) == calculate_price(rule, **kwargs)


def test_the_value_objects_are_frozen() -> None:
    calculation = compute(make_rule(weekday_modifiers={"tuesday": 5}))

    with pytest.raises(FrozenInstanceError):
        calculation.recommended_price = Decimal("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        calculation.modifiers[0].name = "other"  # type: ignore[misc]


def test_the_trace_is_a_tuple_not_a_list() -> None:
    calculation = compute(make_rule())

    assert isinstance(calculation.modifiers, tuple)
    assert isinstance(calculation.guardrails, tuple)


def test_the_applied_value_objects_are_importable_and_shaped_as_designed() -> None:
    modifier = AppliedModifier(
        kind="weekday", name="monday", modifier_pct=Decimal("5"),
        price_after=Decimal("105.00"),
    )
    guardrail = AppliedGuardrail(
        kind="max_price", price_before=Decimal("200"), price_after=Decimal("150"),
    )

    assert modifier.kind == "weekday"
    assert guardrail.kind == "max_price"


# --- guardrails (R3.1-R3.5, design D4) ------------------------------------------------


def test_a_price_below_min_price_is_lifted_to_it() -> None:
    rule = make_rule(min_price=Decimal("80.00"), weekday_modifiers={"tuesday": -50})

    calculation = compute(rule)

    assert calculation.recommended_price == Decimal("80.00")
    assert [(g.kind, g.price_before, g.price_after) for g in calculation.guardrails] == [
        ("min_price", Decimal("50"), Decimal("80.00"))
    ]


def test_a_price_above_max_price_is_cut_to_it() -> None:
    rule = make_rule(max_price=Decimal("130.00"), weekday_modifiers={"tuesday": 50})

    calculation = compute(rule)

    assert calculation.recommended_price == Decimal("130.00")
    assert [(g.kind, g.price_before, g.price_after) for g in calculation.guardrails] == [
        ("max_price", Decimal("150"), Decimal("130.00"))
    ]


def test_a_price_inside_the_bounds_leaves_no_guardrail_trace() -> None:
    calculation = compute(make_rule(min_price=Decimal("50.00"), max_price=Decimal("150.00")))

    assert calculation.guardrails == ()
    assert calculation.recommended_price == Decimal("100.00")


def test_an_upward_jump_beyond_the_daily_cap_is_capped() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("20.00"), weekday_modifiers={"tuesday": 50})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    # 150 wanted, previous 100, cap +20% -> 120
    assert calculation.recommended_price == Decimal("120.00")
    assert [(g.kind, g.price_after) for g in calculation.guardrails] == [
        ("max_daily_change_pct", Decimal("120.00"))
    ]


def test_a_downward_jump_beyond_the_daily_cap_is_capped() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("20.00"), weekday_modifiers={"tuesday": -50})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    # 50 wanted, previous 100, cap -20% -> 80
    assert calculation.recommended_price == Decimal("80.00")
    assert [(g.kind, g.price_after) for g in calculation.guardrails] == [
        ("max_daily_change_pct", Decimal("80.00"))
    ]


def test_a_jump_within_the_daily_cap_is_left_alone() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("20.00"), weekday_modifiers={"tuesday": 10})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    assert calculation.guardrails == ()
    assert calculation.recommended_price == Decimal("110.00")


def test_the_first_day_of_the_horizon_has_no_daily_cap() -> None:
    """R3.3: there is no previous recommended price to measure against."""
    rule = make_rule(max_daily_change_pct=Decimal("1.00"), weekday_modifiers={"tuesday": 50})

    calculation = compute(rule, previous_price=None)

    assert calculation.guardrails == ()
    assert calculation.recommended_price == Decimal("150.00")


def test_the_absolute_bounds_win_over_the_daily_cap(
) -> None:
    """R3.4: the cap may allow a move that `max_price` still forbids."""
    rule = make_rule(
        max_price=Decimal("110.00"),
        max_daily_change_pct=Decimal("50.00"),
        weekday_modifiers={"tuesday": 100},
    )

    calculation = compute(rule, previous_price=Decimal("100.00"))

    # 200 wanted -> cap allows 150 -> max_price cuts to 110
    assert calculation.recommended_price == Decimal("110.00")
    assert [(g.kind, g.price_before, g.price_after) for g in calculation.guardrails] == [
        ("max_daily_change_pct", Decimal("200"), Decimal("150.00")),
        ("max_price", Decimal("150.00"), Decimal("110.00")),
    ]


def test_min_price_wins_over_a_daily_cap_that_would_have_gone_lower() -> None:
    rule = make_rule(
        min_price=Decimal("95.00"),
        max_daily_change_pct=Decimal("50.00"),
        weekday_modifiers={"tuesday": -80},
    )

    calculation = compute(rule, previous_price=Decimal("100.00"))

    # 20 wanted -> cap allows 50 -> min_price lifts to 95
    assert calculation.recommended_price == Decimal("95.00")
    assert [g.kind for g in calculation.guardrails] == ["max_daily_change_pct", "min_price"]


def test_an_emitted_price_is_never_outside_the_bounds() -> None:
    rule = make_rule(
        min_price=Decimal("90.00"),
        max_price=Decimal("110.00"),
        max_daily_change_pct=Decimal("90.00"),
    )

    for previous, pct in ((Decimal("500.00"), 200), (Decimal("1.00"), -90)):
        calculation = compute(
            make_rule(
                min_price=rule.min_price,
                max_price=rule.max_price,
                max_daily_change_pct=rule.max_daily_change_pct,
                weekday_modifiers={"tuesday": pct},
            ),
            previous_price=previous,
        )
        assert rule.min_price <= calculation.recommended_price <= rule.max_price


def test_a_negative_daily_cap_cannot_invert_the_band() -> None:
    """R3.2 says "±`max_daily_change_pct` %" — a magnitude, so the width is `abs`.

    R1.3 keeps the column inside `[0, 100]`, but that validator guards the API and this
    function is also reached by the job reading rules written before it. Without `abs` a
    negative width put the ceiling *below* the floor, and a +5% day came out 20% down.
    """
    rule = make_rule(max_daily_change_pct=Decimal("-20.00"), weekday_modifiers={"tuesday": 5})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    assert calculation.recommended_price == Decimal("105.00")
    assert calculation.guardrails == ()


def test_a_negative_daily_cap_still_caps_at_its_magnitude() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("-20.00"), weekday_modifiers={"tuesday": 50})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    assert calculation.recommended_price == Decimal("120.00")


def test_a_zero_daily_cap_freezes_the_price_at_the_previous_day() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("0.00"), weekday_modifiers={"tuesday": 50})

    calculation = compute(rule, previous_price=Decimal("100.00"))

    assert calculation.recommended_price == Decimal("100.00")


# --- the modifier name is ours, never the raw JSONB value -----------------------------


def test_the_occupancy_name_is_rendered_from_the_parsed_threshold() -> None:
    """`explanation` is a rule-11 sink: the name must not echo whatever the column held.

    `occupancy_pct_above` is the reachable one of the two thresholds, because its comparison
    goes through `_decimal` and therefore accepts a JSON *string*. Rendering the raw value
    would have put `> 50 %` — the manager's own spacing — into the sink.
    """
    rule = make_rule(occupancy_rules=[{"occupancy_pct_above": " 50 ", "modifier_pct": 5}])

    calculation = compute(rule, occupancy_pct=Decimal("60"))

    assert calculation.modifiers[0].name == ">50%"


def test_a_string_lead_time_threshold_never_reaches_the_comparison() -> None:
    """`days_before` is compared as a bare `int`, so a `str` dies before the renderer.

    Only the string half is unreachable this way — see the boolean case below. Task 2.2 is
    what turns this `TypeError` into a `422`.
    """
    rule = make_rule(lead_time_rules=[{"days_before": " 3 ", "modifier_pct": -10}])

    with pytest.raises(TypeError):
        compute(rule, days_before=2)


def test_a_boolean_lead_time_threshold_cannot_reach_the_name_either() -> None:
    """The half that IS reachable, and the reason `days_before` is parsed at all.

    `1 <= True` is `True` in Python, so a boolean survives the comparison that rejects a
    string — and the raw value used to render `<=True days` straight into `explanation`, a
    rule-11 sink. Parsing the threshold is what stops it: `Decimal("True")` is refused.

    Found by the section-1 security panel on re-review, after this file claimed the parse
    was defence-in-depth. It is not: it is load-bearing.
    """
    rule = make_rule(lead_time_rules=[{"days_before": True, "modifier_pct": -10}])

    with pytest.raises(InvalidOperation):
        compute(rule, days_before=1)


@pytest.mark.parametrize("threshold", [float("inf"), 1e21])
def test_a_non_finite_or_huge_lead_time_threshold_renders_no_manager_text(
    threshold: float,
) -> None:
    """These survive the comparison too, so the name must still come out of `Decimal`.

    `json.loads` accepts bare `Infinity`, so this is reachable through JSONB. The rendered
    name is `Decimal.__str__`'s closed alphabet — digits, `.`, sign, `E`, `Infinity` — never
    the repr of whatever the column held (`inf`, `1e+21`).
    """
    rule = make_rule(lead_time_rules=[{"days_before": threshold, "modifier_pct": -10}])

    name = compute(rule, days_before=2).modifiers[0].name

    assert name in {"<=Infinity days", "<=1E+21 days"}


# --- Decimal end to end (R2.4) --------------------------------------------------------


def test_every_price_in_the_trace_is_a_decimal_even_with_json_ints_and_floats() -> None:
    """`modifier_pct` reaches us as `int` or `float` from JSONB; nothing may become a float."""
    rule = make_rule(
        base_price=Decimal("100.00"),
        min_price=Decimal("10.00"),
        max_price=Decimal("120.00"),
        max_daily_change_pct=Decimal("15.00"),
        weekday_modifiers={"saturday": 20},  # int
        lead_time_rules=[{"days_before": 3, "modifier_pct": -10.5}],  # float
        occupancy_rules=[{"occupancy_pct_above": 50.5, "modifier_pct": 5}],
        seasonality_rules=[
            {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
             "end_day": 31, "modifier_pct": 30.25}
        ],
        event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}],
    )

    calculation = compute(
        rule,
        target_date=date(2026, 8, 15),
        days_before=2,
        occupancy_pct=Decimal("60"),
        previous_price=Decimal("100.00"),
    )

    assert len(calculation.modifiers) == 5
    assert calculation.guardrails  # both the cap and max_price bite here
    assert type(calculation.base_price) is Decimal
    assert type(calculation.recommended_price) is Decimal
    for modifier in calculation.modifiers:
        assert type(modifier.modifier_pct) is Decimal
        assert type(modifier.price_after) is Decimal
    for guardrail in calculation.guardrails:
        assert type(guardrail.price_before) is Decimal
        assert type(guardrail.price_after) is Decimal


def test_a_float_modifier_does_not_leak_binary_noise() -> None:
    """`Decimal(0.1)` is 0.1000000000000000055511151231257827…; `Decimal(str(0.1))` is not."""
    rule = make_rule(base_price=Decimal("100.00"), weekday_modifiers={"tuesday": 10.1})

    calculation = compute(rule)

    assert calculation.modifiers[0].modifier_pct == Decimal("10.1")
    assert calculation.modifiers[0].price_after == Decimal("110.10")


def test_the_final_price_is_rounded_half_up_exactly_once() -> None:
    rule = make_rule(base_price=Decimal("100.00"), weekday_modifiers={"tuesday": 0.005})

    calculation = compute(rule)

    # 100 * 1.00005 = 100.005 -> 100.01, and the untouched trace still carries 100.005
    assert calculation.modifiers[0].price_after == Decimal("100.005")
    assert calculation.recommended_price == Decimal("100.01")
    assert calculation.recommended_price.as_tuple().exponent == -2
