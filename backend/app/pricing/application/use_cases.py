"""The seven use cases of `pricing` (R1, R4, R5, R6; design D10, D12, D14, D20).

Four of them are the manager's rule editor, two are the manager's recommendation reader
and decision, and one — `GeneratePriceRecommendationsUseCase` — is the **single**
generator shared by the nightly job and by `POST /price-recommendations/generate` (D10).
One generator and not two because the job and the button do the same thing, and two
copies of a 60-day horizon walk would be two chances to disagree about the guardrails.

**Mode 1 throughout** (PRD §19): nothing here imports, holds or calls a `PMSAdapter`.
The system recommends; a human publishes the price in the OTA and comes back to say so.

**The generation writes no `AuditLog`** (R4.1/R4.5 by way of D12 and OQ1). That is a cut
into an obligation rule 9 of `steering/security.md` states, and it stands on the **fifth
named exception** that rule carries — written by task 8.1, and cited rather than restated
here. Its whole scope is the generation: every human decision below writes its row, and
`_AuditWriter` refuses an anonymous one by construction.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import REDACT_ONLY_FIELDS, ChangeSet
from app.core.tenancy import CrossTenantWriteError
from app.core.unit_of_work import CallerOwnedUnitOfWork, UnitOfWork
from app.pricing.domain.calculator import calculate_price
from app.pricing.domain.constants import HORIZON_DAYS
from app.pricing.domain.entities import (
    UPDATABLE_RULE_FIELDS,
    PriceRecommendation,
    PricingRule,
)
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import (
    PriceRecommendationNotFoundError,
    PricingRuleNotFoundError,
    PricingValidationError,
)
from app.pricing.domain.explanation import render_explanation
from app.pricing.domain.occupancy import occupancy_pct_for, occupancy_window
from app.pricing.domain.repositories import (
    PriceRecommendationFilters,
    PriceRecommendationPage,
    PriceRecommendationRepository,
    PricingRuleFilters,
    PricingRulePage,
    PricingRuleRepository,
)
from app.pricing.domain.rule_resolution import resolve_rule
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyStatus
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.repositories import ReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)

#: What the timeline row says happened. Constants, like every other module's: the title is
#: stored on an append-only table, and `app/timeline/domain/rendering.py:211-218` already
#: carries the ES/EN pair each type is displayed with, so no i18n arrives with this change.
_TIMELINE_TITLES: dict[TimelineEventType, str] = {
    TimelineEventType.PRICE_RECOMMENDATION_CREATED: "Price recommendation created",
    TimelineEventType.PRICE_UPDATED_EXTERNAL: "Price updated in the channel",
}

#: The two statuses a regeneration must leave alone (R4.3, design D9). A human decided
#: them, and a nightly job does not get to undo a decision.
PRESERVED_STATUSES: frozenset[PriceRecommendationStatus] = frozenset(
    {PriceRecommendationStatus.APPROVED, PriceRecommendationStatus.APPLIED_EXTERNAL}
)

#: The five JSONB columns of a rule reach the audit trail only as `{"changed": true}`.
#: Read off `REDACT_ONLY_FIELDS` rather than re-listed here, so the two cannot drift: that
#: mapping is what `ChangeSet.diff()` enforces, and a second copy of the list would be a
#: second thing to keep true.
_REDACT_ONLY_RULE_FIELDS = REDACT_ONLY_FIELDS[audit_actions.ENTITY_PRICING_RULE]


@dataclass(frozen=True)
class PricingActor:
    """Who is acting, and from where — the two things `audit_logs` records (rule 9).

    Every operation of this module that changes something is performed by an authenticated
    person, so unlike `maintenance`'s equivalent this carries no role: pricing draws no
    distinction between its two permitted roles once `require(...)` has let them through
    (D11 gives `TENANT_OWNER` and `PROPERTY_MANAGER` the same four permissions).
    """

    user_id: uuid.UUID
    ip: str | None = None


@dataclass(frozen=True)
class GenerationOutcome:
    """What one run of the generator did, per property of its scope.

    The first four are the counts R4.5 makes the endpoint report. `failed` is the fifth and
    it is **not** decoration: D9 says a property that fails does not discard the horizons
    already written, and a run that swallowed the failure would report a green sweep over a
    portfolio with a hole in it. Every increment is logged with the property that caused it.
    """

    created: int = 0
    updated: int = 0
    preserved: int = 0
    skipped: int = 0
    failed: int = 0


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Same shape as `maintenance`'s and `cleaning`'s, with one difference that is the whole
    point: **no action of this module may be written without an actor** (D12). All five —
    creating a rule, updating a rule, deciding a recommendation, marking one applied, and
    generating a horizon on request — are performed by an authenticated person through a
    route, so there is no caller for whom the absence of an actor would be honest.

    `maintenance` had to carve out its classification job. Pricing does not carve anything
    out: the nightly generation writes no row because it never calls this, which makes the
    exemption a consequence of "no actor, no call" rather than a special case inside the
    writer. That is also what keeps rule 9's exception honest — it now covers the clock
    only, which is the one path for which «ausencia de actor» is true (design D12/OQ1).
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor: PricingActor | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        if actor is None:
            raise PricingValidationError(
                "actor",
                f"{action} must name the user who performed it: every audited pricing "
                "action is performed by an authenticated person (design D12)",
            )
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor.user_id,
                actor_ip=actor.ip,
                changes=changes,
                now=now,
            ),
        )


def _rule_change_set(
    rule: PricingRule, fields: frozenset[str], before: Mapping[str, Any]
) -> ChangeSet:
    """The audited diff of a rule, with **every field name taken from the entity**.

    The names come from `UPDATABLE_RULE_FIELDS` and the values from `getattr(rule, name)`,
    never from the caller's mapping, and that is a security property rather than a style
    choice. `REDACT_ONLY_FIELDS` refuses the five JSONB columns *by field name*, so the
    natural shortcut when one of them raises is to relabel it — `diff("name", old,
    json.dumps(rule.seasonality_rules))` passes, because `name` is diffable and `_storable`
    accepts any `str`, and the manager's free text lands verbatim in `audit_logs.changes`,
    itself a rule-11 sink. Reading the value off the attribute the name denotes makes that
    unwritable here. Left as a note by the section-4 security panel.
    """
    change_set = ChangeSet(audit_actions.ENTITY_PRICING_RULE)
    for name in sorted(fields):
        if name in _REDACT_ONLY_RULE_FIELDS:
            change_set = change_set.redacted(name)
        else:
            change_set = change_set.diff(name, before.get(name), getattr(rule, name))
    return change_set


class _PropertyResolver:
    """Resolves a `property_id` a human typed **inside the acting tenant** (design D20).

    The foreign keys of `pricing_rules.property_id` and `price_recommendations.property_id`
    are global rather than composite with `tenant_id`, so the database would accept a rule
    of tenant A pointing at a property of tenant B. That is not an integrity nicety: the
    section-3 security panel showed the first insert of such a row takes the
    `UNIQUE (property_id, date)` key and makes every later upsert of the rightful tenant
    fail its predicate and be skipped, silently and for ever.

    `upsert_many` closes the generated half by asking the same question of its own. This
    closes the half that arrives by keyboard — and 422, not 404: the tenant is being told
    its request names a property it does not have, which is exactly what R1.4 answers.
    """

    def __init__(self, properties: PropertyRepository) -> None:
        self._properties = properties

    async def require(self, tenant_id: uuid.UUID, property_id: uuid.UUID | None) -> None:
        if property_id is None:
            # A tenant-wide rule (R1.5). There is nothing to resolve.
            return
        if await self._properties.get(tenant_id, property_id) is None:
            raise PricingValidationError(
                "property_id", "does not name a property of this tenant"
            )


class CreatePricingRuleUseCase:
    """`POST /api/v1/pricing-rules` (R1.1, R1.3, R1.4, R1.6).

    The rule, its audit row and its commit are one transaction, so there is no state in
    which a pricing rule exists that nobody can attribute.
    """

    def __init__(
        self,
        *,
        rules: PricingRuleRepository,
        properties: PropertyRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._rules = rules
        self._resolver = _PropertyResolver(properties)
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: PricingActor,
        now: datetime,
        name: str,
        base_price: Decimal,
        min_price: Decimal,
        max_price: Decimal,
        property_id: uuid.UUID | None = None,
        active: bool = True,
        max_daily_change_pct: Decimal = Decimal("20.00"),
        weekday_modifiers: dict[str, Any] | None = None,
        lead_time_rules: list[dict[str, Any]] | None = None,
        occupancy_rules: list[dict[str, Any]] | None = None,
        seasonality_rules: list[dict[str, Any]] | None = None,
        event_rules: list[dict[str, Any]] | None = None,
    ) -> PricingRule:
        # Before the entity is built, not after: D20's whole point is that a foreign
        # `property_id` must never reach a statement.
        await self._resolver.require(tenant_id, property_id)

        rule = PricingRule.create(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            base_price=base_price,
            min_price=min_price,
            max_price=max_price,
            now=now,
            property_id=property_id,
            active=active,
            max_daily_change_pct=max_daily_change_pct,
            weekday_modifiers=weekday_modifiers,
            lead_time_rules=lead_time_rules,
            occupancy_rules=occupancy_rules,
            seasonality_rules=seasonality_rules,
            event_rules=event_rules,
        )
        await self._rules.add(tenant_id, rule)

        # A creation audits the twelve scalars plus whichever JSONB columns arrived with
        # content: recording `{"changed": true}` for five empty defaults would say five
        # things changed when nothing did.
        audited = frozenset(
            name
            for name in UPDATABLE_RULE_FIELDS
            if name not in _REDACT_ONLY_RULE_FIELDS or getattr(rule, name)
        )
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.PRICING_RULE_CREATED,
            entity_type=audit_actions.ENTITY_PRICING_RULE,
            entity_id=rule.id,
            actor=actor,
            changes=_rule_change_set(rule, audited, {}),
            now=now,
        )
        await self._uow.commit()
        return rule


class UpdatePricingRuleUseCase:
    """`PATCH /api/v1/pricing-rules/{id}` (R1.2, R1.3, R1.4, R1.6, R1.7)."""

    def __init__(
        self,
        *,
        rules: PricingRuleRepository,
        properties: PropertyRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._rules = rules
        self._resolver = _PropertyResolver(properties)
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        rule_id: uuid.UUID,
        changes: Mapping[str, Any],
        *,
        actor: PricingActor,
        now: datetime,
    ) -> PricingRule:
        rule = await self._rules.get(tenant_id, rule_id)
        if rule is None:
            # Never a 403 (R1.7): "unknown" and "somebody else's" answer identically, or
            # the difference between the two is a tenant-enumeration probe.
            raise PricingRuleNotFoundError()

        if "property_id" in changes:
            # `property_id` is mutable (it is in `_MUTABLE_RULE_COLUMNS`), so re-pointing a
            # rule at another tenant's flat is exactly as reachable as creating one there.
            await self._resolver.require(tenant_id, changes["property_id"])

        before = {name: getattr(rule, name) for name in UPDATABLE_RULE_FIELDS}
        changed = rule.update_details(changes, now=now)
        if not changed:
            # Nothing moved, so nothing is owed: no write, no audit row, no timestamp. An
            # audit trail with rows that record no change is one nobody reads.
            return rule

        await self._rules.update(tenant_id, rule)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.PRICING_RULE_UPDATED,
            entity_type=audit_actions.ENTITY_PRICING_RULE,
            entity_id=rule.id,
            actor=actor,
            changes=_rule_change_set(rule, changed, before),
            now=now,
        )
        await self._uow.commit()
        return rule


class GetPricingRuleUseCase:
    """`GET /api/v1/pricing-rules/{id}` (R1.2, R1.7)."""

    def __init__(self, rules: PricingRuleRepository) -> None:
        self._rules = rules

    async def execute(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> PricingRule:
        rule = await self._rules.get(tenant_id, rule_id)
        if rule is None:
            raise PricingRuleNotFoundError()
        return rule


class ListPricingRulesUseCase:
    """`GET /api/v1/pricing-rules` (R1.2)."""

    def __init__(self, rules: PricingRuleRepository) -> None:
        self._rules = rules

    async def execute(
        self,
        tenant_id: uuid.UUID,
        filters: PricingRuleFilters,
        *,
        page: int,
        per_page: int,
    ) -> PricingRulePage:
        return await self._rules.list(tenant_id, filters, page=page, per_page=per_page)


class GeneratePriceRecommendationsUseCase:
    """The one generator, shared by the nightly job and by `POST /generate` (design D10).

    Synchronous, because the work is bounded by construction: 60 days times a portfolio
    somebody physically manages (PRD §1), one reservation query and one upsert per
    property. Queueing it would need a job id, a status endpoint and a `202` — and R4.5
    asks for how many rows were created and updated, which is only known at the end.

    **One transaction per property** (D9), not one per tenant: 60 rows is the unit of work
    a manager would recognise, and a property that fails must not discard the horizons
    already written for the ones before it. That makes the `uow` handed to this class
    load-bearing: it must be one that really ends a transaction, because abandoning the
    failed property is what keeps its partial horizon out of the next property's commit.
    `CallerOwnedUnitOfWork` therefore does **not** satisfy this constructor's contract —
    see its `rollback()` docstring.

    **No `AuditLog` anywhere in here** (D12, OQ1): the clock fires the nightly run, so
    there is no person to name and no request to take an IP from, and a two-flat tenant
    would write ~120 identical anonymous rows a day into the table whose index by actor
    exists to answer a different question. The trail is the `TimelineEvent` of each new
    recommendation (R4.4) and this method's own report.
    """

    def __init__(
        self,
        *,
        rules: PricingRuleRepository,
        recommendations: PriceRecommendationRepository,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        timeline: TimelineEventRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        # This generator's correctness depends on abandoning its own failed unit (D9), so a
        # boundary whose `rollback()` is deliberately empty is refused here rather than
        # documented and hoped for. `CallerOwnedUnitOfWork` says as much in its own
        # docstring, but prose was the only barrier and the one machine-checked surface
        # asserted the opposite — `tests/test_unit_of_work.py` pins the two adapters as
        # substitutable for the port, which they are for every other use case. Composed
        # under it, "abandon and carry on" silently becomes "keep and carry on": the QA
        # panel of `/sdd:review` measured `created=0, failed=2` on a two-property sweep,
        # the second failing *because* the first did, with the rows of the failure
        # committed — measured by the QA panel of `/sdd:review`, 2026-08-17.
        if isinstance(uow, CallerOwnedUnitOfWork):
            raise TypeError(
                "GeneratePriceRecommendationsUseCase needs a unit of work it can abandon: "
                "a use case whose correctness depends on abandoning its own failed unit "
                "cannot be composed under a caller-owned boundary."
            )
        self._rules = rules
        self._recommendations = recommendations
        self._properties = properties
        self._reservations = reservations
        self._timeline = timeline
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        *,
        now: datetime,
        property_id: uuid.UUID | None = None,
        actor: PricingActor | None = None,
    ) -> GenerationOutcome:
        execution_date = now.date()
        candidates = await self._candidates(tenant_id, property_id)
        # Once for the whole sweep: `resolve_rule` is a pure function over the candidate
        # set (D6), so N properties resolve against one loaded list instead of N queries.
        active_rules = await self._rules.list_active(tenant_id)

        outcome = GenerationOutcome()
        for index, property in enumerate(candidates):
            rule = resolve_rule(active_rules, property.id)
            if rule is None:
                # R4.6: omitted without an error and without failing the run. A tenant that
                # has written no rules yet finishes green with everything in `skipped`.
                outcome = _plus(outcome, skipped=1)
                continue
            try:
                outcome = _plus(
                    outcome,
                    **await self._price_one_property(
                        tenant_id,
                        property=property,
                        rule=rule,
                        execution_date=execution_date,
                        now=now,
                        actor=actor,
                    ),
                )
            except CrossTenantWriteError:
                # Deliberately **not** swallowed with the rest. Every property here came
                # out of a tenant-scoped query, so this cannot be a data problem the sweep
                # should shrug off — it is the cross-tenant event section 3 made fatal, and
                # counting it as one more failed property would bury it in a log line.
                await self._abandon(tenant_id, property.id)
                raise
            except Exception:
                # As wide as it is because `application/` may not name the driver's
                # exceptions (`steering/backend-architecture.md`: nothing outside
                # `infrastructure/` imports SQLAlchemy), and the domain side is no
                # narrower — a rule row written before the validator of task 2.2 existed
                # reaches `calculate_price` and dies as `TypeError` **or**
                # `decimal.InvalidOperation`, depending on which comparison it survives.
                #
                # The rollback is what makes D9's "the loop carries on" true: a failure
                # inside the upsert leaves the session unusable, so without it the next
                # property's commit would fail too and one bad rule would take the whole
                # portfolio with it.
                if not await self._abandon(tenant_id, property.id):
                    # Abandoning failed too, so no later property can commit either.
                    # Report the tail rather than letting the rollback's own exception
                    # escape: `failed` exists precisely so a holey sweep cannot be mistaken
                    # for a green one, and an `execute` that raises returns no counters at
                    # all. Measured by the QA panel of `/sdd:review`, 2026-08-17.
                    tail = self._unreachable(candidates[index + 1 :], active_rules)
                    return _plus(
                        outcome,
                        failed=1 + tail["failed"],
                        skipped=tail["skipped"],
                    )
                logger.exception(
                    "Pricing horizon failed for property %s of tenant %s; "
                    "the sweep continues with the next property",
                    property.id,
                    tenant_id,
                )
                outcome = _plus(outcome, failed=1)
        return outcome

    @staticmethod
    def _unreachable(
        remaining: Sequence[Property], active_rules: Sequence[PricingRule]
    ) -> dict[str, int]:
        """How to report the properties an unrecoverable session left unvisited.

        Not all of them `failed`. R4.6 gives `skipped` one exact meaning — no active
        applicable rule — and D9's refinement paragraph argues against overloading a counter
        with a second reason, which is why `failed` exists at all. A property that was never
        going to be priced did not break, and an operator paged on `failed` should not be
        sent after it. Classifying costs no query: `resolve_rule` is pure over a list already
        in memory. Raised by the QA panel on re-review.
        """
        skipped = sum(
            1 for property in remaining if resolve_rule(active_rules, property.id) is None
        )
        return {"failed": len(remaining) - skipped, "skipped": skipped}

    async def _abandon(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> bool:
        """Abandon the failed property's transaction. `False` when even that failed.

        A dropped connection is the most likely cause of **both** the original failure and
        of the rollback's, so the two are correlated rather than independent — which is why
        this is guarded instead of trusted.
        """
        try:
            await self._uow.rollback()
        except Exception:
            logger.exception(
                "Could not abandon the failed transaction of property %s of tenant %s; "
                "the sweep stops here and the remaining properties are reported as failed",
                property_id,
                tenant_id,
            )
            return False
        return True

    async def _candidates(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID | None
    ) -> Sequence[Property]:
        """The properties this run prices — the active portfolio, or one named property.

        **Both paths mean the same thing by "candidate": an ACTIVE property.** R4.1 says
        "cada propiedad activa", so the sweep asks `list_by_status(ACTIVE)` and a caller
        naming an inactive one is refused rather than silently counted.

        An earlier version let the named path through and counted it in `skipped`. The
        section-5 architecture panel rejected that, and it was right: R4.6 gives `skipped`
        one exact meaning — no active applicable rule — and D9's own refinement paragraph
        argues against overloading a counter with a second reason (it is why `failed`
        exists rather than being folded in here). Two causes in one number is a report
        nobody can act on.

        The two refusals differ on purpose and leak nothing. "Unknown or somebody else's"
        share one constant message, because R1.7 needs those indistinguishable. "Yours but
        inactive" is a fact about the caller's **own** portfolio, so naming it is not an
        oracle — and it is the actionable answer: activate the property, or stop asking.
        """
        if property_id is None:
            return await self._properties.list_by_status(tenant_id, PropertyStatus.ACTIVE)
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            # 422 rather than 404, for D20's reason: this is a body field naming something
            # the tenant does not have, not a missing resource in the path.
            raise PricingValidationError(
                "property_id", "does not name a property of this tenant"
            )
        if property.status is not PropertyStatus.ACTIVE:
            raise PricingValidationError(
                "property_id",
                "names a property that is not ACTIVE; only the active portfolio is priced",
            )
        return [property]

    async def _price_one_property(
        self,
        tenant_id: uuid.UUID,
        *,
        property: Property,
        rule: PricingRule,
        execution_date: date,
        now: datetime,
        actor: PricingActor | None,
    ) -> dict[str, int]:
        """One property's 60-day horizon, in one transaction (design D9).

        Every property reaching here is ACTIVE and belongs to `tenant_id`: `_candidates`
        is the only producer and it establishes both. There is no re-check, because a
        second one here would be a second place for the two answers to disagree.
        """
        occupancy_pct = await self._occupancy_of(tenant_id, property.id, execution_date)

        first_day = execution_date + timedelta(days=1)
        last_day = execution_date + timedelta(days=HORIZON_DAYS)
        # One query for the whole existing horizon (D9): it tells us what to preserve and
        # what to count, never what to write — the `UNIQUE (property_id, date)` decides
        # that inside `upsert_many`.
        existing = {
            row.date: row
            for row in await self._recommendations.list_for_property_range(
                tenant_id, property.id, first_day, last_day
            )
        }

        to_write: list[PriceRecommendation] = []
        preserved = 0
        previous_price: Decimal | None = None

        # Ascending, and that is R3.2 rather than a habit: each day's cap is measured
        # against the previous day's price, so the order the horizon is walked in is part
        # of the result.
        for offset in range(HORIZON_DAYS):
            target_date = first_day + timedelta(days=offset)
            current = existing.get(target_date)

            if current is not None and current.status in PRESERVED_STATUSES:
                preserved += 1
                # **The previous price is the persisted one, not the one we would have
                # calculated for that day** (design D4, task 5.5). If yesterday is approved
                # at 120 and today's recalculation "would have" put it at 90, the curve the
                # manager reads starts at 120.
                #
                # What that buys, stated at its real width: the day *after* a preserved one
                # is capped against what the manager can see. It does **not** make every
                # adjacent persisted pair obey the cap, and an earlier wording of this
                # comment claimed it did. The cap can only be enforced forward, and R4.3
                # forbids adjusting the preserved neighbour, so the pair
                # *(recalculated, preserved)* is structurally unconstrained — R4.3 outranks
                # R3.2 at exactly that boundary. Measured by the QA panel of `/sdd:review`
                # on 2026-08-17: approved days seeded at 200/300/120 leave persisted steps
                # of +87.5% and −50% with no clamp in play.
                previous_price = current.recommended_price
                continue

            calculation = calculate_price(
                rule,
                target_date=target_date,
                # The horizon starts tomorrow, so this is never 0 (see `domain/constants`).
                days_before=(target_date - execution_date).days,
                occupancy_pct=occupancy_pct,
                previous_price=previous_price,
            )
            row = PriceRecommendation.create(
                # An existing row keeps its identity: the manager may already be looking at
                # it, and `ON CONFLICT DO UPDATE` would keep the stored id anyway — passing
                # a fresh one here would only make the entity describe a row that is not
                # the one about to exist.
                id=current.id if current is not None else uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=property.id,
                pricing_rule_id=rule.id,
                date=target_date,
                recommended_price=calculation.recommended_price,
                explanation=render_explanation(calculation),
                now=now,
            )
            if current is not None:
                # The upsert rewrites price, rendered text and rule and nothing else, so
                # the stored status and creation instant survive it. Copying them onto the
                # entity keeps it a description of the row that will exist — which matters
                # for `REJECTED`, deliberately regenerated (D9) and deliberately still
                # rejected afterwards.
                row.status = current.status
                row.created_at = current.created_at
            to_write.append(row)
            previous_price = calculation.recommended_price

        written = await self._recommendations.upsert_many(tenant_id, to_write)

        # R4.4/D14: only creations put an event on the property's timeline. In the steady
        # state the job creates one date per property per day — the one entering at the far
        # end of the horizon — and updates the other 59, so the timeline gets one row a day
        # instead of sixty. The first run over a property does emit 60, once.
        #
        # **Which ones those are comes from the statement, never from the pre-read.** An
        # earlier version walked a `fresh` list built at `existing.get(...) is None` and
        # priced the disagreement at "one duplicate timeline row" for the unlocked manual
        # path. That undercounted it: on the conflict path the stored row keeps its own
        # `id`, so the event would carry the id the entity was built with and point at no
        # row at all — and `timeline_events` is append-only, so the dangling pointer is
        # permanent. Measured by the QA panel of `/sdd:review`, 2026-08-17.
        by_key = {(row.property_id, row.date): row for row in to_write}
        for key in written.inserted:
            await self._timeline.add(
                tenant_id,
                self._event(
                    tenant_id=tenant_id,
                    recommendation=by_key[key],
                    event_type=TimelineEventType.PRICE_RECOMMENDATION_CREATED,
                    actor=actor,
                    now=now,
                    extra={"pricing_rule_id": str(rule.id)},
                ),
            )

        if actor is not None:
            # **Only the human path.** The clock has no person to name and no request to take
            # an `ip` from, so the nightly run stays exempt on rule 9's genuine
            # ausencia-de-actor ground; an authenticated manager pressing generate does not,
            # and without this row «quién movió este precio y cuándo» is unanswerable for her
            # — a repeat run over a full horizon inserts nothing, so D14 leaves no timeline
            # row either, and the manual path carries no lock. One row per property, on the
            # property, because 60 recommendations have no single `entity_id` and D12 already
            # recorded that there is no execution column to hang one on. No diff: the counts
            # are in the response and the log. Decided by Jose on 2026-08-17 (design D12/OQ1).
            await self._audit.record(
                tenant_id=tenant_id,
                action=audit_actions.PRICE_RECOMMENDATIONS_GENERATED,
                entity_type=audit_actions.ENTITY_PROPERTY,
                entity_id=property.id,
                actor=actor,
                changes=ChangeSet(audit_actions.ENTITY_PROPERTY),
                now=now,
            )

        await self._uow.commit()
        # Every count is the statement's (`RETURNING xmax = 0`) or this walk's, and none is
        # the pre-read's, so `created + updated + preserved == HORIZON_DAYS` holds however
        # the two disagree.
        #
        # `preserved` has two summands and they cannot overlap: `preserved` is what the
        # pre-read saw already decided, so those days never entered `to_write`;
        # `written.preserved` is what the **statement** refused because a human decided it
        # after that read. The second is the one R4.3 was quietly missing.
        return {
            "created": written.created,
            "updated": written.updated,
            "preserved": preserved + written.preserved,
        }

    async def _occupancy_of(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, execution_date: date
    ) -> Decimal:
        """One scalar per property and run, from the local reservations (R2.3, D5).

        PRD §7.17 defines occupancy relative to *today*, not to the date being priced, so
        this is read once and reused for all 60 days instead of being asked 60 times. No
        PMS call: `reservations` is already the projection of that calendar (Mode 1).
        """
        window_start, window_end = occupancy_window(execution_date)
        reservations = await self._reservations.list_for_properties(
            tenant_id,
            [property_id],
            window_start,
            # `occupancy_window` is half-open and the port's range is inclusive, so this
            # asks for one day more than the window. Harmless and deliberate: a stay
            # starting on `window_end` contributes no night inside the window, and
            # `occupancy_pct_for` clips to the window itself regardless.
            window_end,
        )
        return occupancy_pct_for(reservations, execution_date=execution_date)

    def _event(
        self,
        *,
        tenant_id: uuid.UUID,
        recommendation: PriceRecommendation,
        event_type: TimelineEventType,
        actor: PricingActor | None,
        now: datetime,
        extra: dict[str, str] | None = None,
    ):
        """Identifiers and a price, and nothing else (design D14).

        `timeline_events` is append-only, so whatever lands in `metadata` can never be
        redacted — and `TimelineEventFactory` checks only that it is a `dict`, with no
        allowlist of keys. The payload is therefore built key by key here rather than from
        the entity: `metadata=asdict(recommendation)` would carry the rendered text of a
        rule-11 sink into a second one, and would pass every assertion that only compared
        against a fixture. Task 5.6 pins the exact key set on the constructed event.

        `SCHEDULER` when nobody is acting, `USER` when somebody is: `TimelineEventFactory`
        accepts `actor_user_id` only alongside `USER`, so the row cannot claim a person who
        was not there.
        """
        return TimelineEventFactory.create(
            TimelineEventData(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=recommendation.property_id,
                actor_type=(
                    TimelineActorType.USER if actor is not None else TimelineActorType.SCHEDULER
                ),
                actor_user_id=actor.user_id if actor is not None else None,
                event_type=event_type,
                title=_TIMELINE_TITLES[event_type],
                created_at=now,
                metadata={
                    "recommendation_id": str(recommendation.id),
                    "date": recommendation.date.isoformat(),
                    "recommended_price": str(recommendation.recommended_price),
                    **(extra or {}),
                },
            )
        )


class ListPriceRecommendationsUseCase:
    """`GET /api/v1/price-recommendations` (R5.1)."""

    def __init__(self, recommendations: PriceRecommendationRepository) -> None:
        self._recommendations = recommendations

    async def execute(
        self,
        tenant_id: uuid.UUID,
        filters: PriceRecommendationFilters,
        *,
        page: int,
        per_page: int,
    ) -> PriceRecommendationPage:
        return await self._recommendations.list(
            tenant_id, filters, page=page, per_page=per_page
        )


class DecidePriceRecommendationUseCase:
    """`PATCH /api/v1/price-recommendations/{id}` — the three legal moves (R5.2-R5.5).

    **Nothing here touches the `PMSAdapter`**, and that is Mode 1 of PRD §19 rather than
    an omission: the system recommends and a human publishes. `APPLIED_EXTERNAL` is that
    human coming back to say they did it, which is why it carries a timeline event (the
    fact) and its own audit action (D12) instead of sharing the decision's.

    The entity owns the state machine (`decide` / `mark_applied_external`), so an illegal
    move raises before anything is written and leaves the status exactly as it was (R5.4).
    """

    def __init__(
        self,
        *,
        recommendations: PriceRecommendationRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._recommendations = recommendations
        self._audit = _AuditWriter(audit)
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        status: PriceRecommendationStatus,
        *,
        actor: PricingActor,
        now: datetime,
    ) -> PriceRecommendation:
        recommendation = await self._recommendations.get(tenant_id, recommendation_id)
        if recommendation is None:
            raise PriceRecommendationNotFoundError()

        previous_status = recommendation.status
        if status is PriceRecommendationStatus.APPLIED_EXTERNAL:
            recommendation.mark_applied_external()
            action = audit_actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL
        else:
            # Anything that is not one of the two decisions — including a bare string from
            # a caller that skipped the schema — is refused by the entity as a 409.
            recommendation.decide(status)
            action = audit_actions.PRICE_RECOMMENDATION_DECIDED

        await self._recommendations.update(tenant_id, recommendation)
        await self._audit.record(
            tenant_id=tenant_id,
            action=action,
            entity_type=audit_actions.ENTITY_PRICE_RECOMMENDATION,
            entity_id=recommendation.id,
            actor=actor,
            # `status` is the entity's whole auditable surface (D12), which is also why the
            # rendered text of the recommendation cannot follow it into `audit_logs`.
            changes=ChangeSet(audit_actions.ENTITY_PRICE_RECOMMENDATION).diff(
                "status", previous_status, recommendation.status
            ),
            now=now,
        )

        if action == audit_actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL:
            await self._timeline.add(
                tenant_id,
                _applied_external_event(
                    tenant_id=tenant_id, recommendation=recommendation, actor=actor, now=now
                ),
            )

        await self._uow.commit()
        return recommendation


def _applied_external_event(
    *,
    tenant_id: uuid.UUID,
    recommendation: PriceRecommendation,
    actor: PricingActor,
    now: datetime,
):
    """`PRICE_UPDATED_EXTERNAL` — three identifiers, no free text (design D14)."""
    return TimelineEventFactory.create(
        TimelineEventData(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=recommendation.property_id,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor.user_id,
            event_type=TimelineEventType.PRICE_UPDATED_EXTERNAL,
            title=_TIMELINE_TITLES[TimelineEventType.PRICE_UPDATED_EXTERNAL],
            created_at=now,
            metadata={
                "recommendation_id": str(recommendation.id),
                "date": recommendation.date.isoformat(),
                "recommended_price": str(recommendation.recommended_price),
            },
        )
    )


def _plus(
    outcome: GenerationOutcome,
    *,
    created: int = 0,
    updated: int = 0,
    preserved: int = 0,
    skipped: int = 0,
    failed: int = 0,
) -> GenerationOutcome:
    """`GenerationOutcome` is frozen, so accumulating means replacing.

    Named parameters rather than `**counts`: the counters are fed from a dict one caller
    builds, and a `**kwargs` version would swallow a misspelt key as a zero instead of
    raising — a run reporting `created=0` because somebody typed `create`.
    """
    return GenerationOutcome(
        created=outcome.created + created,
        updated=outcome.updated + updated,
        preserved=outcome.preserved + preserved,
        skipped=outcome.skipped + skipped,
        failed=outcome.failed + failed,
    )
