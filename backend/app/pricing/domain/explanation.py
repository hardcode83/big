"""Renders a `PriceCalculation` as the text a human approves the price from (R6, D13).

In English, like every other system message (`sdd/project.md`, Conventions), and produced
by a closed template — **no AI adapter takes part** (R6.2; `steering/product.md` principle
5: pricing is deterministic by rules, the AI explains but never calculates).

A second pure function over the calculator's trace rather than a second walk of the rule:
if this recomputed the chain, the price and its explanation could drift apart and no test
would notice (D2).

Note on the numbers: the two-decimal formatting here is **presentation**. The one rounding
that R2.4 governs already happened inside `calculate_price`, on `recommended_price` alone;
the intermediate values keep their full precision in the trace.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.pricing.domain.calculator import (
    KIND_EVENT,
    KIND_LEAD_TIME,
    KIND_OCCUPANCY,
    KIND_SEASON,
    KIND_WEEKDAY,
    AppliedGuardrail,
    AppliedModifier,
    PriceCalculation,
)

#: PRD §7.17 prices in euros and `pricing_rules` carries no currency column.
CURRENCY = "EUR"

_CENTS = Decimal("0.01")

_MODIFIER_LABELS = {
    KIND_WEEKDAY: "Weekday",
    KIND_LEAD_TIME: "Lead time",
    KIND_OCCUPANCY: "Occupancy",
    KIND_SEASON: "Season",
    KIND_EVENT: "Event",
}


def _amount(value: Decimal) -> str:
    return f"{value.quantize(_CENTS, rounding=ROUND_HALF_UP):f}"


def _percentage(value: Decimal) -> str:
    """Signed, two decimals.

    The sign comes from `is_signed()` and not from `>= 0`: a small negative percentage
    quantizes to `Decimal('-0.00')`, and `Decimal('-0.00') >= 0` is `True`, which would
    print a discount as `+0.00%`.
    """
    quantized = value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return f"{'-' if quantized.is_signed() else '+'}{abs(quantized):f}%"


def _modifier_sentence(modifier: AppliedModifier) -> str:
    label = _MODIFIER_LABELS.get(modifier.kind, modifier.kind)
    return (
        f"{label} ({modifier.name}) {_percentage(modifier.modifier_pct)} "
        f"-> {_amount(modifier.price_after)}."
    )


def _guardrail_sentence(guardrail: AppliedGuardrail) -> str:
    """The qualifier appears only when the guardrail carries one.

    Written as a condition on the two values rather than as an `assert` on the kind: an
    `assert` is stripped under `python -O`, which would turn a contract into a `TypeError`
    inside the renderer of a job that has already computed the price.

    The trade that buys: a future guardrail setting only one of the pair would silently
    render without its qualifier instead of failing loudly. Accepted for a renderer — a
    half-built guardrail is a defect of the calculator, and the price is already correct.
    """
    if guardrail.limit_pct is not None and guardrail.reference is not None:
        detail = f" ({_percentage(guardrail.limit_pct)} of {_amount(guardrail.reference)})"
    else:
        detail = ""
    return f"Guardrail {guardrail.kind}{detail} -> {_amount(guardrail.price_after)}."


def render_explanation(calculation: PriceCalculation) -> str:
    """The base price, every modifier in order, every guardrail that cut, the final price."""
    sentences = [f"Base price {_amount(calculation.base_price)} {CURRENCY}."]
    sentences += [_modifier_sentence(modifier) for modifier in calculation.modifiers]
    sentences += [_guardrail_sentence(guardrail) for guardrail in calculation.guardrails]
    sentences.append(f"Recommended {_amount(calculation.recommended_price)} {CURRENCY}.")
    return " ".join(sentences)
