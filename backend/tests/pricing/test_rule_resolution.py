import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.pricing.domain.entities import PricingRule
from app.pricing.domain.rule_resolution import resolve_rule

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
PROPERTY_ID = uuid.uuid4()
OTHER_PROPERTY_ID = uuid.uuid4()


def rule(**overrides: Any) -> PricingRule:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "rule",
        "base_price": Decimal("100.00"),
        "min_price": Decimal("50.00"),
        "max_price": Decimal("200.00"),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return PricingRule(**fields)


def test_a_rule_of_the_property_wins_over_the_tenant_wide_one() -> None:
    own = rule(property_id=PROPERTY_ID, name="own")
    tenant_wide = rule(property_id=None, name="tenant", updated_at=NOW + timedelta(days=5))

    assert resolve_rule([tenant_wide, own], PROPERTY_ID) is own


def test_a_property_without_its_own_rule_falls_back_to_the_tenant_wide_one() -> None:
    tenant_wide = rule(property_id=None, name="tenant")
    other = rule(property_id=OTHER_PROPERTY_ID, name="other")

    assert resolve_rule([other, tenant_wide], PROPERTY_ID) is tenant_wide


def test_no_applicable_rule_resolves_to_none() -> None:
    assert resolve_rule([rule(property_id=OTHER_PROPERTY_ID)], PROPERTY_ID) is None
    assert resolve_rule([], PROPERTY_ID) is None


def test_an_inactive_rule_never_applies() -> None:
    inactive_own = rule(property_id=PROPERTY_ID, active=False)
    tenant_wide = rule(property_id=None)

    assert resolve_rule([inactive_own, tenant_wide], PROPERTY_ID) is tenant_wide
    assert resolve_rule([inactive_own], PROPERTY_ID) is None


def test_an_inactive_tenant_wide_rule_does_not_shadow_nothing() -> None:
    assert resolve_rule([rule(property_id=None, active=False)], PROPERTY_ID) is None


def test_the_most_recently_updated_of_two_candidates_wins() -> None:
    older = rule(property_id=PROPERTY_ID, updated_at=NOW)
    newer = rule(property_id=PROPERTY_ID, updated_at=NOW + timedelta(hours=1))

    assert resolve_rule([older, newer], PROPERTY_ID) is newer
    assert resolve_rule([newer, older], PROPERTY_ID) is newer


def test_the_id_breaks_a_tie_on_updated_at() -> None:
    first = rule(id=uuid.UUID(int=1), property_id=PROPERTY_ID, updated_at=NOW)
    second = rule(id=uuid.UUID(int=2), property_id=PROPERTY_ID, updated_at=NOW)

    assert resolve_rule([first, second], PROPERTY_ID) is second


def test_the_answer_does_not_depend_on_the_order_of_the_list() -> None:
    """The tie-break exists so two runs of the same job cannot disagree (OQ3)."""
    candidates = [
        rule(id=uuid.UUID(int=n), property_id=PROPERTY_ID, updated_at=NOW)
        for n in range(1, 6)
    ] + [
        rule(id=uuid.UUID(int=n), property_id=None, updated_at=NOW + timedelta(days=1))
        for n in range(6, 9)
    ]
    expected = resolve_rule(candidates, PROPERTY_ID)

    for shift in range(len(candidates)):
        shuffled = candidates[shift:] + candidates[:shift]
        assert resolve_rule(shuffled, PROPERTY_ID) is expected

    assert list(reversed(candidates)) != candidates
    assert resolve_rule(list(reversed(candidates)), PROPERTY_ID) is expected
