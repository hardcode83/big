"""Ports owned by the pricing domain (R1.2, R4.2, R5.1; design D6, D9).

`app/pricing/` was one of the modules `steering/backend-architecture.md` calls "dominios que
todavía son solo estructura de datos" — entities and tables, no use case, no port. These are
its first, and they arrive together because this change is also its first writer.

Two ports and not one, per the same rule `maintenance` cites: "No repositorio 'Dios' con
métodos de varios agregados — un repositorio por agregado raíz". A `PricingRule` and a
`PriceRecommendation` have different lifecycles (a rule is edited by a person, a horizon is
rewritten by a job every night) and different permissions.

**Every method takes `tenant_id` explicitly and returns nothing outside it.** The parameter
is the authoritative mechanism; the global loader criteria of `app/core/db.py` are only the
net — and for INSERTs they are not even that (limit 3 of that module), which is why the
writers check the tenant themselves.

**Precondition every writer inherits** (design D9): `property_id` and `pricing_rule_id` must
already have been resolved *within* `tenant_id`. The foreign keys of `pricing_rules` and
`price_recommendations` are global rather than composite with `tenant_id`, so the database
would happily accept a recommendation of tenant A anchored to a property of tenant B, and no
port can detect that without a query of its own. It is the same precondition
`IncidentRepository.add` states, for the same schema reason.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from app.pricing.domain.entities import PriceRecommendation, PricingRule
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import PricingValidationError


@dataclass(frozen=True)
class PricingRuleFilters:
    """The filters of `GET /pricing-rules` (R1.2), combined with AND.

    `property_id` is a three-state filter and that is deliberate: absent means "every rule",
    while a caller wanting only the tenant-wide ones asks for `property_id_is_null=True`.
    Without the second flag there would be no way to express it, because `property_id=None`
    is indistinguishable from "not filtering".

    Setting **both** is rejected rather than silently resolved. An earlier version let
    `property_id_is_null` win and ignored the id, which answers a question the caller did
    not ask — and the two together have no coherent meaning, since no rule can be both
    anchored to a property and tenant-wide. Raised by the section-3 QA panel.
    """

    property_id: uuid.UUID | None = None
    property_id_is_null: bool = False
    active: bool | None = None

    def __post_init__(self) -> None:
        if self.property_id is not None and self.property_id_is_null:
            raise PricingValidationError(
                "property_id",
                "cannot filter by a property and by 'no property' at the same time",
            )


@dataclass(frozen=True)
class PriceRecommendationFilters:
    """The filters of `GET /price-recommendations` (R5.1), combined with AND."""

    property_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: PriceRecommendationStatus | None = None


@dataclass(frozen=True)
class PricingRulePage:
    """One page plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[PricingRule, ...]
    total: int


@dataclass(frozen=True)
class PriceRecommendationPage:
    items: tuple[PriceRecommendation, ...]
    total: int


@dataclass(frozen=True)
class UpsertOutcome:
    """What `upsert_many` did, split the way R4.5 asks the endpoint to report it.

    `preserved` is the count R4.3 protects: rows in `APPROVED` or `APPLIED_EXTERNAL` that a
    regeneration must not touch. It is separate from `updated` because "we left your
    decision alone" and "we recalculated it" are different answers to the manager. Here it
    counts specifically the ones **the statement** refused — a decision taken after the
    caller read the horizon, which is the only kind the caller cannot count itself.

    `inserted` carries the `(property_id, date)` keys the statement took the insert branch
    for, and `created` is derived from it rather than counted alongside it. The keys exist
    because R4.4 puts a `TimelineEvent` on **new** recommendations only, and the caller may
    not decide which those were from its own pre-read: a concurrent insert between the read
    and the write turns an expected insert into an update, and the emitted event would then
    carry an id no row has — permanently, `timeline_events` being append-only. Only the
    statement knows which branch each row took.
    """

    inserted: tuple[tuple[uuid.UUID, date], ...] = ()
    updated: int = 0
    preserved: int = 0

    @property
    def created(self) -> int:
        """Derived, never stored beside `inserted`: two copies of one fact can disagree."""
        return len(self.inserted)


class PricingRuleRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, rule: PricingRule) -> None:
        """Append a rule for the acting tenant. **Never commits** — the use case owns the
        transaction, which is what makes the rule and its `AuditLog` atomic (R1.6)."""
        ...

    async def get(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> PricingRule | None:
        """The rule, or `None` when it does not exist **within this tenant**.

        Returning `None` rather than raising keeps the 404 decision in the use case, and
        R1.7 needs "unknown" and "not yours" to be indistinguishable — so this port must
        not answer differently for the two.
        """
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: PricingRuleFilters,
        *,
        page: int,
        per_page: int,
    ) -> PricingRulePage:
        """The paginated listing of `GET /pricing-rules` (R1.2)."""
        ...

    async def list_active(self, tenant_id: uuid.UUID) -> Sequence[PricingRule]:
        """Every active rule of the tenant, for the generator to resolve against (D6).

        Unpaginated on purpose, and the only unbounded read here: `resolve_rule` is a pure
        function over the whole candidate set, so the job loads it **once** and applies it
        per property instead of issuing a query each time. A tenant's active pricing rules
        are units — one per property plus a tenant-wide fallback — so the ceiling is the
        portfolio, which PRD §1 already bounds to what somebody physically manages.
        """
        ...

    async def update(self, tenant_id: uuid.UUID, rule: PricingRule) -> None:
        """Persist the mutations `update_details` made. Never commits (R1.6)."""
        ...


class PriceRecommendationRepository(Protocol):
    async def get(
        self, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
    ) -> PriceRecommendation | None:
        """The recommendation, or `None` outside this tenant (R1.7's shape, for R5.1)."""
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: PriceRecommendationFilters,
        *,
        page: int,
        per_page: int,
    ) -> PriceRecommendationPage:
        """The paginated listing of `GET /price-recommendations` (R5.1)."""
        ...

    async def list_for_property_range(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        date_from: date,
        date_to: date,
    ) -> Sequence[PriceRecommendation]:
        """The existing horizon of one property, in **one** query (design D9).

        The generator reads this before writing so it knows what to preserve and what to
        count, not as a concurrency control — the `UNIQUE (property_id, date)` decides that.
        Inclusive of both bounds, because a horizon is a closed range of dates.
        """
        ...

    async def upsert_many(
        self,
        tenant_id: uuid.UUID,
        recommendations: Sequence[PriceRecommendation],
    ) -> UpsertOutcome:
        """Write a horizon idempotently: `INSERT … ON CONFLICT (property_id, date)` (R4.2).

        The `UNIQUE` decides, not a prior read, so two runs of the job cannot fail against
        each other. **Never commits** — D9 puts the transaction boundary at one per
        property, and that boundary belongs to the use case.

        The caller passes only the rows it intends to write, filtering out the ones R4.3
        protects (`APPROVED`, `APPLIED_EXTERNAL`) before calling — **and an implementation
        must refuse them again anyway**, reporting them in `preserved`. The caller's filter
        reads the horizon before this statement runs, so an approval landing in between
        escaped it: the QA panel of `/sdd:review` reproduced a `777.00` approval being
        rewritten to `100.00`, with no audit row (D12) and no timeline row (D14) to show it
        had happened. D9 says a pre-read is not concurrency control, and that is as true of
        preserving as of counting. The two filters are the same set on purpose; the narrower
        one is the one that holds.

        The outcome's `inserted` keys are **the statement's answer**, not the caller's
        expectation, and an implementation must report them as such: R4.4 emits a timeline
        row per new recommendation, and an implementation that echoed back what it was
        asked to insert would let a concurrent insert produce an event pointing at an id no
        row carries.
        """
        ...

    async def update(
        self, tenant_id: uuid.UUID, recommendation: PriceRecommendation
    ) -> None:
        """Persist a status transition (R5.2, R5.3). Never commits.

        Only `status` moves: PRD §7.18 gives this table `created_at` and no `updated_at`,
        so there is no timestamp to touch, and the temporal trail lives in the `AuditLog`
        and the `TimelineEvent` (R5.5's `ASSUMPTION`).
        """
        ...
