"""The two pricing aggregates and the invariants they protect (R1.3, R1.4, R5.2-R5.4).

`steering/backend-architecture.md` names "guardrails de pricing" as its example of a
**dominio con invariante real**, so the tactical ceremony here is paid for by the rule it
protects: `PricingRule` is the shape the calculator trusts, and the calculator is a pure
function with no validation of its own (design D16).

Why the invariants live here and not only in Pydantic: `api/schemas.py` guards the request
boundary, but the daily job and `POST /generate` read rules written *earlier*, so a
validator that only ran at the router would leave every later reader unprotected. That is
also `steering/backend.md`'s "la lógica nunca vive en el router".
"""

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Mapping, Sequence

from app.pricing.domain.calculator import WEEKDAY_NAMES
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import (
    InvalidRecommendationTransitionError,
    PricingValidationError,
)
from app.pricing.domain.holidays import SUPPORTED_HOLIDAY_CATALOGS

#: `pricing_rules.name` is `VARCHAR(200)` (PRD §7.17); rejecting here beats a driver error.
MAX_RULE_NAME_LENGTH = 200

#: The `name` of a season or an event is the ONE piece of `explanation` our template does
#: not compose (design D13), and `price_recommendations.explanation` is sink 14 of rule 11
#: in `steering/security.md`. Bounding it is that row's stated mitigation.
MAX_MODIFIER_NAME_LENGTH = 100

#: A ceiling on each JSONB array, asked for by the section-1 security panel. Seasons and
#: events apply **every** entry that matches (R2.2), so N of them are N sentences per day,
#: times a 60-day horizon, times the portfolio — all of it into that same sink. 50 is well
#: above any real calendar: the recurring bulk of a year is one `ES_NATIONAL` entry (D7),
#: not fifty literal ones.
MAX_ENTRIES_PER_ARRAY = 50

#: The twelve writable columns (design D12, which mirrors them into `AUDITABLE_FIELDS`).
UPDATABLE_RULE_FIELDS = frozenset(
    {
        "name",
        "active",
        "property_id",
        "base_price",
        "min_price",
        "max_price",
        "max_daily_change_pct",
        "weekday_modifiers",
        "lead_time_rules",
        "occupancy_rules",
        "seasonality_rules",
        "event_rules",
    }
)

#: `base_price`, `min_price` and `max_price` are `Numeric(10, 2)` — eight integer digits and
#: two decimals. Bounded here for exactly the reason `MAX_RULE_NAME_LENGTH` is: D16 makes
#: this aggregate the shape the calculator trusts ("una función pura … sin validación
#: propia"), so a price the column cannot hold is one `validate()` accepted and something
#: downstream dies on — a `DataError` at the driver, or `InvalidOperation` inside
#: `calculate_price`'s final `quantize`. Both are 500s on a path R1.3 promises as a 422.
#: Raised by the section-2 security panel.
MAX_PRICE_VALUE = Decimal("99999999.99")

_CENTS = Decimal("0.01")
_PERCENT_FLOOR = Decimal("-100")


def _copied(value: Any) -> Any:
    """A defensive copy of a JSONB value, recursively, all the way down.

    `create` and `update_details` store what the caller handed them, and without this the
    caller keeps a live reference: appending to that list after construction mutates a rule
    that `validate()` already blessed, which is precisely the guarantee D16 sells the
    calculator. Raised by the section-2 QA panel.

    `deepcopy` would do. This is preferred because it says exactly what it covers —
    `Mapping` and `list`, the only containers a JSON document has. Anything else is
    returned as-is, which is safe for the scalars JSON actually produces (`str`, `int`,
    `float`, `bool`, `None`) and for tuples, which are immutable. It would NOT protect a
    `set`, but no JSON decoder emits one and `validate()` refuses any entry that is not a
    `Mapping`, so such a value cannot survive into a stored rule anyway.
    """
    if isinstance(value, Mapping):
        return {key: _copied(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copied(item) for item in value]
    return value


def _number(column: str, value: Any) -> Decimal:
    """A JSON **number**, finite, as a `Decimal`.

    Three refusals, each one a hole the section-1 panels found in the calculator:

    - a `str` — `days_before` is compared as a bare `int`, so `"3"` raises `TypeError`
      halfway through a job instead of being answered `422` at the door;
    - a `bool` — `1 <= True` is `True` in Python, so a boolean survives that comparison
      and only dies later, inside `Decimal("True")`;
    - a non-finite — `json.loads` accepts bare `NaN`/`Infinity`, and neither belongs in a
      price.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise PricingValidationError(column, f"expected a JSON number, got {type(value).__name__}")
    number = Decimal(str(value))
    if not number.is_finite():
        raise PricingValidationError(column, "expected a finite number")
    return number


def _price(column: str, value: Any) -> Decimal:
    """A number the `Numeric(10, 2)` column can hold **exactly**.

    The scale check compares against the quantized value rather than the exponent, so
    `Decimal("100.000")` passes — it is 100 with trailing zeros, which the column stores
    fine — while `Decimal("100.005")` is refused instead of being silently rounded by
    Postgres into a price nobody asked for.
    """
    number = _number(column, value)
    if number < 0:
        raise PricingValidationError(column, "cannot be negative")
    if number > MAX_PRICE_VALUE:
        raise PricingValidationError(
            column, f"exceeds {MAX_PRICE_VALUE}, the largest value the column stores"
        )
    if number != number.quantize(_CENTS):
        raise PricingValidationError(column, "cannot carry more than two decimal places")
    return number


def _modifier_pct(column: str, value: Any) -> Decimal:
    number = _number(column, value)
    if number < _PERCENT_FLOOR:
        raise PricingValidationError(column, "modifier_pct cannot discount more than 100%")
    return number


def _modifier_name(column: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PricingValidationError(column, "name must be a non-empty string")
    if len(value) > MAX_MODIFIER_NAME_LENGTH:
        raise PricingValidationError(
            column, f"name is longer than {MAX_MODIFIER_NAME_LENGTH} characters"
        )


def _entries(column: str, value: Any, allowed_keys: Sequence[frozenset[str]]) -> list[Mapping]:
    if not isinstance(value, list):
        raise PricingValidationError(column, "expected an array")
    if len(value) > MAX_ENTRIES_PER_ARRAY:
        raise PricingValidationError(
            column, f"holds more than {MAX_ENTRIES_PER_ARRAY} entries"
        )
    for entry in value:
        if not isinstance(entry, Mapping):
            raise PricingValidationError(column, "every entry must be an object")
        if not any(set(entry) == keys for keys in allowed_keys):
            raise PricingValidationError(
                column,
                "entry keys must be exactly one of "
                + " or ".join(sorted(str(sorted(keys)) for keys in allowed_keys)),
            )
    return list(value)


def _validate_weekday_modifiers(value: Any) -> None:
    column = "weekday_modifiers"
    if not isinstance(value, Mapping):
        raise PricingValidationError(column, "expected an object")
    for day, modifier in value.items():
        if day not in WEEKDAY_NAMES:
            # The caller's key is deliberately NOT echoed, for the reason the `holidays`
            # branch of `_validate_event_rules` gives: a JSON object key is as long as
            # whoever sent it chose, and echoing it makes the 422 body that size. Naming the
            # seven accepted keys is what makes the message actionable; R1.4 only asks for
            # the field. Required by rule 2 of `app/pricing/api/errors.py`.
            raise PricingValidationError(
                column,
                "keys must be lowercase English weekday names: "
                + ", ".join(WEEKDAY_NAMES),
            )
        _modifier_pct(column, modifier)


def _validate_lead_time_rules(value: Any) -> None:
    column = "lead_time_rules"
    for entry in _entries(column, value, [frozenset({"days_before", "modifier_pct"})]):
        days_before = _number(column, entry["days_before"])
        if days_before < 0 or days_before != days_before.to_integral_value():
            raise PricingValidationError(column, "days_before must be a whole number >= 0")
        _modifier_pct(column, entry["modifier_pct"])


def _validate_occupancy_rules(value: Any) -> None:
    column = "occupancy_rules"
    for entry in _entries(column, value, [frozenset({"occupancy_pct_above", "modifier_pct"})]):
        threshold = _number(column, entry["occupancy_pct_above"])
        if not (Decimal(0) <= threshold <= Decimal(100)):
            raise PricingValidationError(column, "occupancy_pct_above must be between 0 and 100")
        _modifier_pct(column, entry["modifier_pct"])


def _validate_month_day(column: str, month: Any, day: Any) -> None:
    month_number = _number(column, month)
    day_number = _number(column, day)
    if month_number != month_number.to_integral_value() or not (1 <= month_number <= 12):
        raise PricingValidationError(column, "month must be a whole number between 1 and 12")
    # Against a leap year, so 29 February stays declarable in a recurring annual range.
    _, last_day = calendar.monthrange(2024, int(month_number))
    if day_number != day_number.to_integral_value() or not (1 <= day_number <= last_day):
        raise PricingValidationError(
            column, f"day must be a whole number between 1 and {last_day} for that month"
        )


def _validate_seasonality_rules(value: Any) -> None:
    column = "seasonality_rules"
    keys = frozenset({"name", "start_month", "start_day", "end_month", "end_day", "modifier_pct"})
    for entry in _entries(column, value, [keys]):
        _modifier_name(column, entry["name"])
        _validate_month_day(column, entry["start_month"], entry["start_day"])
        _validate_month_day(column, entry["end_month"], entry["end_day"])
        _modifier_pct(column, entry["modifier_pct"])
        # No check that the end follows the start: when it does not, the range wraps the
        # year end on purpose (design D3, hole 1) — 20 Dec to 6 Jan is the most obvious
        # season there is, and rejecting it would make it undeclarable.


def _validate_event_rules(value: Any) -> None:
    column = "event_rules"
    literal = frozenset({"name", "date", "modifier_pct"})
    catalogue = frozenset({"holidays", "modifier_pct"})
    for entry in _entries(column, value, [literal, catalogue]):
        # `_entries` already rejected an entry holding both forms or neither: its key set
        # has to equal one of the two exactly (D7, R1.4).
        if "holidays" in entry:
            # The `isinstance` comes FIRST because `SUPPORTED_HOLIDAY_CATALOGS` is a
            # frozenset: `{} not in frozenset(...)` raises `TypeError: unhashable type`,
            # which is not a `PricingDomainError` and so answers 500 where R1.4 promises
            # 422. Same guard the `date` branch below already had.
            if not isinstance(entry["holidays"], str):
                raise PricingValidationError(column, "holidays must be a catalogue name")
            if entry["holidays"] not in SUPPORTED_HOLIDAY_CATALOGS:
                # The caller's value is deliberately NOT echoed. `event_rules` is free-form
                # JSONB whose interior no request schema constrains, so echoing it makes a
                # 422 body as large as the string somebody sent. Naming the supported set
                # is what makes the message actionable; R1.4 only asks for the field.
                raise PricingValidationError(
                    column,
                    "holidays must be one of "
                    f"{', '.join(sorted(SUPPORTED_HOLIDAY_CATALOGS))}",
                )
        else:
            _modifier_name(column, entry["name"])
            if not isinstance(entry["date"], str):
                raise PricingValidationError(column, "date must be an ISO 8601 string")
            try:
                date.fromisoformat(entry["date"])
            except ValueError as error:
                # `str(error)` is NOT interpolated, and that is the same rule as the
                # `holidays` branch above: `ValueError: Invalid isoformat string: '…'` quotes
                # the offending string **in full**, so a caller sending a megabyte under
                # `date` would get it back as a 422 body. The cause is still chained for a
                # traceback; only the client-visible message is a constant of ours.
                raise PricingValidationError(
                    column, "date must be an ISO 8601 calendar date (YYYY-MM-DD)"
                ) from error
        _modifier_pct(column, entry["modifier_pct"])


@dataclass
class PricingRule:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    base_price: Decimal
    min_price: Decimal
    max_price: Decimal
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    active: bool = True
    max_daily_change_pct: Decimal = Decimal("20.00")
    weekday_modifiers: dict[str, Any] = field(default_factory=dict)
    lead_time_rules: list[dict[str, Any]] = field(default_factory=list)
    occupancy_rules: list[dict[str, Any]] = field(default_factory=list)
    seasonality_rules: list[dict[str, Any]] = field(default_factory=list)
    event_rules: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        id: uuid.UUID,
        tenant_id: uuid.UUID,
        name: str,
        base_price: Decimal,
        min_price: Decimal,
        max_price: Decimal,
        now: datetime,
        property_id: uuid.UUID | None = None,
        active: bool = True,
        max_daily_change_pct: Decimal = Decimal("20.00"),
        weekday_modifiers: dict[str, Any] | None = None,
        lead_time_rules: list[dict[str, Any]] | None = None,
        occupancy_rules: list[dict[str, Any]] | None = None,
        seasonality_rules: list[dict[str, Any]] | None = None,
        event_rules: list[dict[str, Any]] | None = None,
    ) -> "PricingRule":
        """A validated rule, or `PricingValidationError` naming the field that failed."""
        rule = cls(
            id=id,
            tenant_id=tenant_id,
            name=name,
            base_price=base_price,
            min_price=min_price,
            max_price=max_price,
            created_at=now,
            updated_at=now,
            property_id=property_id,
            active=active,
            max_daily_change_pct=max_daily_change_pct,
            # Copied, never aliased: otherwise the caller keeps a live handle on a rule
            # `validate()` has already blessed (see `_copied`).
            #
            # `is None` and NOT a truthy test: omitting a column means "empty", but a
            # caller PASSING `0`, `""` or `False` is passing something that is not an
            # object or an array, and a truthy gate swapped it for the default before
            # `validate()` ever saw it — a silent accept where R1.4 promises a 422 naming
            # the field. D16 makes this entity the only gate, so there is nothing upstream
            # to catch it. Raised by the section-2 QA panel on re-review.
            weekday_modifiers=_copied(weekday_modifiers) if weekday_modifiers is not None else {},
            lead_time_rules=_copied(lead_time_rules) if lead_time_rules is not None else [],
            occupancy_rules=_copied(occupancy_rules) if occupancy_rules is not None else [],
            seasonality_rules=(
                _copied(seasonality_rules) if seasonality_rules is not None else []
            ),
            event_rules=_copied(event_rules) if event_rules is not None else [],
        )
        rule.validate()
        return rule

    def update_details(self, changes: Mapping[str, Any], *, now: datetime) -> frozenset[str]:
        """Apply a partial update and return the fields that actually moved.

        Validation runs over the **whole** rule afterwards, not over the incoming fields:
        a `PATCH` that raises `min_price` has to be judged against the `max_price` already
        stored, and checking only what arrived would let the pair end up crossed.

        The fields are applied in place and **restored from a snapshot** if `validate()`
        rejects them, so a refused update leaves the entity — and its `updated_at` —
        exactly as it was (the same guarantee R5.4 gives the state machine). It is not
        validated on a copy: `validate()` reads the whole aggregate, and a copy would have
        to be a deep one to keep the five JSONB columns independent.

        The returned set is what the audit diff records (R1.6); an empty one means nothing
        changed, so no timestamp moves and no row is owed.
        """
        unknown = set(changes) - UPDATABLE_RULE_FIELDS
        if unknown:
            raise PricingValidationError(sorted(unknown)[0], "is not an updatable field")

        changed = frozenset(
            name for name, value in changes.items() if getattr(self, name) != value
        )
        if not changed:
            return changed

        previous = {name: getattr(self, name) for name in changed}
        for name in changed:
            setattr(self, name, _copied(changes[name]))
        try:
            self.validate()
        except PricingValidationError:
            for name, value in previous.items():
                setattr(self, name, value)
            raise
        self.updated_at = now
        return changed

    def validate(self) -> None:
        """Every invariant of R1.3 and R1.4, each failure naming its field."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise PricingValidationError("name", "is required")
        if len(self.name) > MAX_RULE_NAME_LENGTH:
            raise PricingValidationError(
                "name", f"is longer than {MAX_RULE_NAME_LENGTH} characters"
            )

        base = _price("base_price", self.base_price)
        minimum = _price("min_price", self.min_price)
        maximum = _price("max_price", self.max_price)
        if minimum > maximum:
            raise PricingValidationError("min_price", "cannot exceed max_price")
        if not (minimum <= base <= maximum):
            raise PricingValidationError(
                "base_price", "must fall inside [min_price, max_price]"
            )

        cap = _number("max_daily_change_pct", self.max_daily_change_pct)
        if not (Decimal(0) <= cap <= Decimal(100)):
            raise PricingValidationError("max_daily_change_pct", "must be between 0 and 100")
        # `Numeric(5, 2)`, so the same exactness the prices need.
        if cap != cap.quantize(_CENTS):
            raise PricingValidationError(
                "max_daily_change_pct", "cannot carry more than two decimal places"
            )

        _validate_weekday_modifiers(self.weekday_modifiers)
        _validate_lead_time_rules(self.lead_time_rules)
        _validate_occupancy_rules(self.occupancy_rules)
        _validate_seasonality_rules(self.seasonality_rules)
        _validate_event_rules(self.event_rules)


@dataclass
class PriceRecommendation:
    """One property, one date, one recommended price (PRD §7.18).

    `ASSUMPTION` (R5.5): this row has **`created_at` and no `updated_at`** — PRD §7.18
    declares only the one timestamp and `specs/domain-foundation-financial.md` kept it that
    way on purpose. So `decide()` and `mark_applied_external()` move `status` without
    stamping anything, and **the temporal trail of an approval lives in the `AuditLog` and
    the `TimelineEvent`, never in this row**. Anyone reading a status here and wanting to
    know *when* it changed has to go to those two; the row cannot answer it.

    That is also why this entity has no `update_details` twin of `PricingRule`'s: the only
    mutable column is `status`, and it moves through the state machine below.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    pricing_rule_id: uuid.UUID
    date: date
    recommended_price: Decimal
    explanation: str
    created_at: datetime
    current_price: Decimal | None = None
    confidence: Decimal = Decimal("1.00")
    status: PriceRecommendationStatus = PriceRecommendationStatus.RECOMMENDED

    #: The three legal moves of R5.2/R5.3, keyed by operation rather than by
    #: `origin -> destinations`: `decide` and `mark_applied_external` are different
    #: capabilities, and a pair-keyed table would let one inherit the other's origins.
    #:
    #: `DRAFT` appears as neither an origin nor a destination. PRD §7.18 declares it in the
    #: enum and no path of this change produces it or moves out of it.
    _TRANSITIONS: ClassVar[
        Mapping[str, tuple[frozenset[PriceRecommendationStatus], PriceRecommendationStatus]]
    ] = {
        "decide:APPROVED": (
            frozenset({PriceRecommendationStatus.RECOMMENDED}),
            PriceRecommendationStatus.APPROVED,
        ),
        "decide:REJECTED": (
            frozenset({PriceRecommendationStatus.RECOMMENDED}),
            PriceRecommendationStatus.REJECTED,
        ),
        "mark_applied_external": (
            frozenset({PriceRecommendationStatus.APPROVED}),
            PriceRecommendationStatus.APPLIED_EXTERNAL,
        ),
    }

    @classmethod
    def create(
        cls,
        *,
        id: uuid.UUID,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        pricing_rule_id: uuid.UUID,
        date: date,
        recommended_price: Decimal,
        explanation: str,
        now: datetime,
    ) -> "PriceRecommendation":
        """A new recommendation, always `RECOMMENDED` and always fully confident.

        `confidence` is pinned at `1.00` (R6.3) rather than left to the caller. The column
        exists for a **future** mode whose calculation carries real uncertainty; today the
        price is a deterministic function of the rule (R2.5), so any other value would be
        decoration. `current_price` stays `None` because its source would be
        `PMSAdapter.get_availability`, and Mode 1 never calls the PMS (R5.5, D19).
        """
        return cls(
            id=id,
            tenant_id=tenant_id,
            property_id=property_id,
            pricing_rule_id=pricing_rule_id,
            date=date,
            recommended_price=recommended_price,
            explanation=explanation,
            created_at=now,
            current_price=None,
            confidence=Decimal("1.00"),
            status=PriceRecommendationStatus.RECOMMENDED,
        )

    def _transition(self, operation: str) -> None:
        """Validate before mutating, so a refusal leaves the entity untouched (R5.4)."""
        origins, target = self._TRANSITIONS[operation]
        if self.status not in origins:
            raise InvalidRecommendationTransitionError(
                f"Price recommendation cannot move from {self.status.value} to {target.value}"
            )
        self.status = target

    def decide(self, status: PriceRecommendationStatus) -> None:
        """Approve or reject a recommendation still in `RECOMMENDED` (R5.2).

        `APPLIED_EXTERNAL` is deliberately unreachable from here: it is not a decision but
        a fact of the world — somebody published that price outside the system — and it has
        its own operation and its own audit action (design D12).
        """
        # The type check comes before `status.value`: without it a caller passing the bare
        # string `"APPROVED"` gets an `AttributeError`, which is a 500 where R5.4 promises
        # a 409. Raised by the section-2 QA panel.
        if not isinstance(status, PriceRecommendationStatus):
            raise InvalidRecommendationTransitionError(
                f"{status!r} is not a PriceRecommendationStatus"
            )
        operation = f"decide:{status.value}"
        if operation not in self._TRANSITIONS:
            raise InvalidRecommendationTransitionError(
                f"{status.value} is not a decision; only APPROVED and REJECTED are"
            )
        self._transition(operation)

    def mark_applied_external(self) -> None:
        """Record that a human published this price in the OTA (R5.3)."""
        self._transition("mark_applied_external")
