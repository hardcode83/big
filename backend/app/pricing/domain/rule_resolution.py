"""Which rule prices a property (R1.5, design D6, OQ3).

A pure function and not a `ORDER BY … LIMIT 1` in the repository: choosing the applicable
rule is a business rule, and `steering/backend-architecture.md` puts those in `domain/`.
It also means the job resolves N properties against one already-loaded list instead of
issuing one query per property.
"""

import uuid
from typing import Any, Sequence


def _preference(rule: Any) -> tuple[Any, ...]:
    """Most recently updated wins, `id` breaking the final tie.

    The tie-break is real, not theoretical: nothing in the schema stops a tenant from
    having two active rules for the same property, and this change adds no migration
    (OQ3). Without the `id` the answer would depend on the order the query happened to
    return, and two runs of the same job could price the same day differently.
    """
    return (rule.updated_at, rule.id)


def resolve_rule(rules: Sequence[Any], property_id: uuid.UUID) -> Any | None:
    """The active `PricingRule` that applies to `property_id`, or `None`.

    A rule of the property's own wins over the tenant-wide one (`property_id is None`),
    which is R1.5 read literally: a tenant rule applies to every property that has no rule
    of its own.
    """
    own = [rule for rule in rules if rule.active and rule.property_id == property_id]
    if own:
        return max(own, key=_preference)
    tenant_wide = [rule for rule in rules if rule.active and rule.property_id is None]
    if tenant_wide:
        return max(tenant_wide, key=_preference)
    return None
