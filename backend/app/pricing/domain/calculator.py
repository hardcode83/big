"""The deterministic price formula of PRD §7.17 (R2.1-R2.5, R3.1-R3.4; design D2, D3, D4).

`calculate_price` takes no clock, no session and no network, so R2.5 — same arguments, same
result — holds **by signature** rather than by discipline.

It returns a `PriceCalculation` and not a `Decimal` on purpose (D2): R6.1 wants the
explanation to list every modifier with its name and percentage plus the guardrails that
cut, and rebuilding that chain in a second place is how two renderings of the same price
drift apart without a test noticing.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterator, Mapping, Sequence

from app.pricing.domain.holidays import holiday_name

#: Indexed by `date.weekday()` (0 = Monday). Not `strftime('%A')`, which the PRD's snippet
#: uses and which follows the locale of whatever process happens to run the job (D3).
WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

KIND_WEEKDAY = "weekday"
KIND_LEAD_TIME = "lead_time"
KIND_OCCUPANCY = "occupancy"
KIND_SEASON = "season"
KIND_EVENT = "event"

GUARDRAIL_DAILY_CHANGE = "max_daily_change_pct"
GUARDRAIL_MIN_PRICE = "min_price"
GUARDRAIL_MAX_PRICE = "max_price"

_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class AppliedModifier:
    kind: str
    name: str
    modifier_pct: Decimal
    price_after: Decimal


@dataclass(frozen=True)
class AppliedGuardrail:
    """A guardrail that actually cut, with what it measured against.

    `reference` and `limit_pct` are populated only for `max_daily_change_pct`: they are the
    previous day's persisted price and the cap percentage, which D13's rendering shows
    ("Guardrail max_daily_change_pct (+20.00% of 110.00) -> 132.00") and which cannot be
    recovered from `price_before`/`price_after` alone. `min_price`/`max_price` leave them
    `None` — their bound is `price_after` itself.
    """

    kind: str
    price_before: Decimal
    price_after: Decimal
    reference: Decimal | None = None
    limit_pct: Decimal | None = None


@dataclass(frozen=True)
class PriceCalculation:
    base_price: Decimal
    modifiers: tuple[AppliedModifier, ...]
    guardrails: tuple[AppliedGuardrail, ...]
    recommended_price: Decimal


def _decimal(value: Any) -> Decimal:
    """The single door every JSONB number walks through (R2.4).

    `Decimal(str(v))` and never `Decimal(v)`: the latter takes a `float` literally, so a
    `modifier_pct` of `15.3` stored as JSON would enter as 15.300000000000000710542735…
    and carry that noise through every later multiplication.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _apply(price: Decimal, modifier_pct: Decimal) -> Decimal:
    return price * (Decimal(1) + modifier_pct / _HUNDRED)


def _weekday_modifier(
    modifiers: Mapping[str, Any], target_date: date
) -> tuple[str, Decimal] | None:
    name = WEEKDAY_NAMES[target_date.weekday()]
    if name not in modifiers:
        return None
    return name, _decimal(modifiers[name])


def _lead_time_modifier(
    rules: Sequence[Mapping[str, Any]], days_before: int
) -> tuple[str, Decimal] | None:
    applicable = [rule for rule in rules if days_before <= rule["days_before"]]
    if not applicable:
        return None
    chosen = min(applicable, key=lambda rule: rule["days_before"])
    # The name is rendered from the PARSED threshold, never from the raw JSONB value: it ends
    # up interpolated into `explanation`, which is a rule-11 sink, and a name built out of
    # whatever the column happened to hold would make that census row inaccurate.
    return f"<={_decimal(chosen['days_before'])} days", _decimal(chosen["modifier_pct"])


def _occupancy_modifier(
    rules: Sequence[Mapping[str, Any]], occupancy_pct: Decimal
) -> tuple[str, Decimal] | None:
    applicable = [
        rule for rule in rules if occupancy_pct >= _decimal(rule["occupancy_pct_above"])
    ]
    if not applicable:
        return None
    chosen = max(applicable, key=lambda rule: _decimal(rule["occupancy_pct_above"]))
    # Parsed, not raw — same reason as `_lead_time_modifier` above.
    return f">{_decimal(chosen['occupancy_pct_above'])}%", _decimal(chosen["modifier_pct"])


def season_matches(rule: Mapping[str, Any], target_date: date) -> bool:
    """A seasonality rule is an **annual, recurring** month/day range (D3, hole 1).

    The PRD leaves `date_in_range` undefined. When `(end_month, end_day)` precedes
    `(start_month, start_day)` the range crosses the year end — 20 Dec to 6 Jan — and
    matches both halves. Reading it as an empty range instead would make the most obvious
    season of all undeclarable.
    """
    start = (rule["start_month"], rule["start_day"])
    end = (rule["end_month"], rule["end_day"])
    day = (target_date.month, target_date.day)
    if end < start:
        return day >= start or day <= end
    return start <= day <= end


def _season_modifiers(
    rules: Sequence[Mapping[str, Any]], target_date: date
) -> Iterator[tuple[str, Decimal]]:
    for rule in rules:
        if season_matches(rule, target_date):
            yield str(rule["name"]), _decimal(rule["modifier_pct"])


def event_match_name(rule: Mapping[str, Any], target_date: date) -> str | None:
    """The name an event rule contributes on `target_date`, or `None` if it does not match.

    Two admitted forms (D7), and the validator rejects an entry carrying both or neither:

    - the PRD's, an **exact date with its year** — `{"name", "date", "modifier_pct"}`;
    - the catalogue's — `{"holidays": "ES_NATIONAL", "modifier_pct"}`, where the catalogue
      supplies the dates and the rule supplies the percentage.
    """
    if "holidays" in rule:
        return holiday_name(target_date)
    return str(rule["name"]) if date.fromisoformat(str(rule["date"])) == target_date else None


def _event_modifiers(
    rules: Sequence[Mapping[str, Any]], target_date: date
) -> Iterator[tuple[str, Decimal]]:
    for rule in rules:
        name = event_match_name(rule, target_date)
        if name is not None:
            yield name, _decimal(rule["modifier_pct"])


def calculate_price(
    rule: Any,
    *,
    target_date: date,
    days_before: int,
    occupancy_pct: Decimal,
    previous_price: Decimal | None,
) -> PriceCalculation:
    """Price for one property and one date, with the trace that explains it.

    `rule` is a `PricingRule`; it is typed loosely to keep this module free of an import
    cycle with `entities.py`, which imports nothing from here.
    """
    base_price = _decimal(rule.base_price)
    price = base_price
    modifiers: list[AppliedModifier] = []

    # PRD §7.17: weekday -> lead time -> occupancy -> season and events, each multiplicative
    # over the previous result (R2.1). Seasons and events all apply, in declared order — a
    # product of factors commutes, but the explanation does not, and a fixed order is what
    # makes it reproducible.
    weekday = _weekday_modifier(rule.weekday_modifiers, target_date)
    if weekday is not None:
        price = _apply(price, weekday[1])
        modifiers.append(AppliedModifier(KIND_WEEKDAY, weekday[0], weekday[1], price))

    lead_time = _lead_time_modifier(rule.lead_time_rules, days_before)
    if lead_time is not None:
        price = _apply(price, lead_time[1])
        modifiers.append(AppliedModifier(KIND_LEAD_TIME, lead_time[0], lead_time[1], price))

    occupancy = _occupancy_modifier(rule.occupancy_rules, occupancy_pct)
    if occupancy is not None:
        price = _apply(price, occupancy[1])
        modifiers.append(AppliedModifier(KIND_OCCUPANCY, occupancy[0], occupancy[1], price))

    for name, pct in _season_modifiers(rule.seasonality_rules, target_date):
        price = _apply(price, pct)
        modifiers.append(AppliedModifier(KIND_SEASON, name, pct, price))

    for name, pct in _event_modifiers(rule.event_rules, target_date):
        price = _apply(price, pct)
        modifiers.append(AppliedModifier(KIND_EVENT, name, pct, price))

    price, guardrails = _apply_guardrails(rule, price, previous_price)

    # The only rounding in the whole chain, and it happens after the guardrails (R2.4).
    # Clamping first is what keeps the emitted price inside [min_price, max_price]: both
    # bounds carry two decimals already, so this can only move the value within the range.
    return PriceCalculation(
        base_price=base_price,
        modifiers=tuple(modifiers),
        guardrails=guardrails,
        recommended_price=price.quantize(_CENTS, rounding=ROUND_HALF_UP),
    )


def _apply_guardrails(
    rule: Any, price: Decimal, previous_price: Decimal | None
) -> tuple[Decimal, tuple[AppliedGuardrail, ...]]:
    """The daily cap first, the absolute bounds last (R3.1-R3.4).

    Order matters and is not cosmetic: PRD §19 declares `min_price`/`max_price` absolute,
    so they run last and no emitted price is ever outside them even when the daily cap
    would have allowed it. On the horizon's first day there is no previous price to measure
    against, so the cap does not apply (R3.3).

    Only a guardrail that actually cuts leaves a trace — that is what R3.5 renders.
    """
    applied: list[AppliedGuardrail] = []

    if previous_price is not None:
        # `abs`, because R3.2 says "±`max_daily_change_pct` %" — a magnitude. R1.3 keeps the
        # column inside `[0, 100]`, but that validator guards the API, not this function, and
        # a negative value here would INVERT the band (ceiling below floor) and cut a modest
        # rise into a steep fall. The band cannot invert if the width cannot be negative.
        change_pct = abs(_decimal(rule.max_daily_change_pct))
        ceiling = _apply(previous_price, change_pct)
        floor = _apply(previous_price, -change_pct)
        if price > ceiling:
            applied.append(
                AppliedGuardrail(
                    GUARDRAIL_DAILY_CHANGE, price, ceiling, previous_price, change_pct
                )
            )
            price = ceiling
        elif price < floor:
            applied.append(
                AppliedGuardrail(
                    GUARDRAIL_DAILY_CHANGE, price, floor, previous_price, -change_pct
                )
            )
            price = floor

    min_price = _decimal(rule.min_price)
    max_price = _decimal(rule.max_price)
    if price < min_price:
        applied.append(AppliedGuardrail(GUARDRAIL_MIN_PRICE, price, min_price))
        price = min_price
    elif price > max_price:
        applied.append(AppliedGuardrail(GUARDRAIL_MAX_PRICE, price, max_price))
        price = max_price

    return price, tuple(applied)
