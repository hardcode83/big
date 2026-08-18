"""SQLAlchemy adapters for the pricing ports (R1.2, R4.2, R5.1; design D9).

These adapters reach `pricing_rules` and `price_recommendations`, whose tables landed with
`domain-foundation-financial` in 2026-07-31. Both hold rule-11 sinks; who writes them is
declared in that rule's table in `steering/security.md`, which is the only place it lives.

Every statement filters `tenant_id` explicitly. The session listener of `app/core/db.py`
also covers both tables (they carry `TenantScopedMixin`), but it is the net and never the
mechanism — and for an INSERT it is not even the net, because the listener does not cover
INSERTs at all (limit 3 of that module), which is why every writer here checks the tenant
itself and raises `CrossTenantWriteError`.

No method commits. The use case owns the transaction, which is what makes a rule and its
`AuditLog` atomic (R1.6) and what lets design D9 put a boundary around each property's
horizon rather than around the whole run.
"""

import uuid
from datetime import date
from typing import Sequence

from sqlalchemy import and_ as sql_and
from sqlalchemy import func, literal_column, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.pricing.domain.entities import PriceRecommendation, PricingRule
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import PricingValidationError
from app.pricing.domain.repositories import (
    PriceRecommendationFilters,
    PriceRecommendationPage,
    PricingRuleFilters,
    PricingRulePage,
    UpsertOutcome,
)
from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from app.properties.infrastructure.models import PropertyModel

#: The columns `PricingRule.update_details` may change — exactly `UPDATABLE_RULE_FIELDS`
#: plus the timestamp it stamps. Named rather than writing the whole row, for the reason
#: `maintenance` gives its `_MUTABLE_INCIDENT_COLUMNS`: an UPDATE that also set `tenant_id`
#: or `created_at` would let a wiring mistake move a row between tenants through a method
#: whose name says it only saves.
_MUTABLE_RULE_COLUMNS = (
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
    "updated_at",
)

#: A recommendation only ever transitions. `recommended_price`, `explanation` and
#: `pricing_rule_id` are rewritten by the generator through `upsert_many`, never here.
_MUTABLE_RECOMMENDATION_COLUMNS = ("status",)

#: How each upserted row says which branch it took. Postgres leaves the system column
#: `xmax` at zero for a freshly inserted tuple and non-zero for one the conflict path
#: updated, so `created` and `updated` come back from the statement itself instead of from
#: a count taken before it — which would be a race with a concurrent run.
#:
#: A `literal_column` because `xmax` is a system column: it is not in the model's metadata,
#: so there is no mapped attribute to compare against.
_WAS_INSERTED = literal_column("xmax = 0").label("was_inserted")

#: The statuses `upsert_many`'s conflict predicate refuses to rewrite (R4.3). Spelt out here
#: rather than imported from `application/`, where the caller keeps its own copy for the
#: pre-read: `infrastructure/` must not depend on `application/`, and this list is the
#: *statement's* contract — the two are the same set on purpose and a test pins them equal,
#: because the guarantee is only as good as its narrower half.
_STATUSES_A_HUMAN_DECIDED = (
    PriceRecommendationStatus.APPROVED,
    PriceRecommendationStatus.APPLIED_EXTERNAL,
)


def _require_same_tenant(entity_tenant_id: uuid.UUID, acting: uuid.UUID, entity: str) -> None:
    """Refuse an entity that belongs to somebody else.

    Every writer below then builds its statement from the **`tenant_id` parameter**, never
    from `entity.tenant_id`, even though this guard has just proved them equal. The SQL is
    identical either way; what differs is what happens to a later refactor that moves or
    drops the guard. Keying the write to the caller's argument keeps it safe on its own,
    which is what task 3.1 asks for ("el escritor scopea por ese parámetro, nunca leyendo
    `entity.tenant_id` del objeto que persiste"). Raised by the section-3 tenancy panel.
    """
    if entity_tenant_id != acting:
        raise CrossTenantWriteError(
            entity=entity, entity_tenant_id=entity_tenant_id, acting_tenant_id=acting
        )


def _require_positive_page(page: int, per_page: int) -> None:
    """`offset((page - 1) * per_page)` goes negative for `page = 0`.

    Postgres answers that with `OFFSET must not be negative` — a `DBAPIError` that reaches
    the caller as a 500 instead of the 422 a bad query parameter deserves. The routes
    declare `ge=1`, so this is the second line of defence and the one that holds for a
    caller that is not a route: the job, a command, a test.
    """
    if page < 1 or per_page < 1:
        raise PricingValidationError(
            "page", f"page and per_page must be positive, got page={page}, per_page={per_page}"
        )


def _to_rule(model: PricingRuleModel) -> PricingRule:
    return PricingRule(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        base_price=model.base_price,
        min_price=model.min_price,
        max_price=model.max_price,
        created_at=model.created_at,
        updated_at=model.updated_at,
        property_id=model.property_id,
        active=model.active,
        max_daily_change_pct=model.max_daily_change_pct,
        weekday_modifiers=dict(model.weekday_modifiers or {}),
        lead_time_rules=list(model.lead_time_rules or []),
        occupancy_rules=list(model.occupancy_rules or []),
        seasonality_rules=list(model.seasonality_rules or []),
        event_rules=list(model.event_rules or []),
    )


def _to_recommendation(model: PriceRecommendationModel) -> PriceRecommendation:
    return PriceRecommendation(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        pricing_rule_id=model.pricing_rule_id,
        date=model.date,
        recommended_price=model.recommended_price,
        explanation=model.explanation,
        created_at=model.created_at,
        current_price=model.current_price,
        confidence=model.confidence,
        status=model.status,
    )


def _rule_conditions(tenant_id: uuid.UUID, filters: PricingRuleFilters) -> list:
    conditions = [PricingRuleModel.tenant_id == tenant_id]
    if filters.property_id_is_null:
        conditions.append(PricingRuleModel.property_id.is_(None))
    elif filters.property_id is not None:
        conditions.append(PricingRuleModel.property_id == filters.property_id)
    if filters.active is not None:
        conditions.append(PricingRuleModel.active.is_(filters.active))
    return conditions


def _recommendation_conditions(
    tenant_id: uuid.UUID, filters: PriceRecommendationFilters
) -> list:
    conditions = [PriceRecommendationModel.tenant_id == tenant_id]
    if filters.property_id is not None:
        conditions.append(PriceRecommendationModel.property_id == filters.property_id)
    if filters.date_from is not None:
        conditions.append(PriceRecommendationModel.date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(PriceRecommendationModel.date <= filters.date_to)
    if filters.status is not None:
        conditions.append(PriceRecommendationModel.status == filters.status)
    return conditions


class SqlAlchemyPricingRuleRepository:
    """`PricingRuleRepository`. `pricing_rules.name` is a rule-11 sink; its contract and who
    writes it live in that rule's table in `steering/security.md`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, rule: PricingRule) -> None:
        _require_same_tenant(rule.tenant_id, tenant_id, "pricing rule")
        self._session.add(
            PricingRuleModel(
                id=rule.id,
                tenant_id=tenant_id,
                property_id=rule.property_id,
                name=rule.name,
                active=rule.active,
                base_price=rule.base_price,
                min_price=rule.min_price,
                max_price=rule.max_price,
                max_daily_change_pct=rule.max_daily_change_pct,
                weekday_modifiers=rule.weekday_modifiers,
                lead_time_rules=rule.lead_time_rules,
                occupancy_rules=rule.occupancy_rules,
                seasonality_rules=rule.seasonality_rules,
                event_rules=rule.event_rules,
                created_at=rule.created_at,
                updated_at=rule.updated_at,
            )
        )
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> PricingRule | None:
        model = await self._session.scalar(
            select(PricingRuleModel).where(
                PricingRuleModel.tenant_id == tenant_id,
                PricingRuleModel.id == rule_id,
            )
        )
        return _to_rule(model) if model is not None else None

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: PricingRuleFilters,
        *,
        page: int,
        per_page: int,
    ) -> PricingRulePage:
        _require_positive_page(page, per_page)
        conditions = _rule_conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(PricingRuleModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(PricingRuleModel)
            .where(*conditions)
            # Newest first, `id` breaking a shared instant so the order is total and two
            # pages cannot overlap or drop a row.
            .order_by(PricingRuleModel.created_at.desc(), PricingRuleModel.id.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return PricingRulePage(
            items=tuple(_to_rule(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def list_active(self, tenant_id: uuid.UUID) -> Sequence[PricingRule]:
        rows = await self._session.execute(
            select(PricingRuleModel)
            .where(
                PricingRuleModel.tenant_id == tenant_id,
                PricingRuleModel.active.is_(True),
            )
            # Ordered so `resolve_rule`'s input is stable across runs. The tie-break lives
            # in that pure function (D6) and does not depend on this, but a stable order
            # keeps query logs and any future statement-count test comparable.
            .order_by(PricingRuleModel.updated_at.desc(), PricingRuleModel.id.desc())
        )
        return [_to_rule(model) for model in rows.scalars()]

    async def update(self, tenant_id: uuid.UUID, rule: PricingRule) -> None:
        _require_same_tenant(rule.tenant_id, tenant_id, "pricing rule")
        await self._session.execute(
            update(PricingRuleModel)
            .where(
                PricingRuleModel.tenant_id == tenant_id,
                PricingRuleModel.id == rule.id,
            )
            .values(**{column: getattr(rule, column) for column in _MUTABLE_RULE_COLUMNS})
        )
        await self._session.flush()


class SqlAlchemyPriceRecommendationRepository:
    """`PriceRecommendationRepository`. `price_recommendations.explanation` is a rule-11 sink;
    its contract and who writes it live in that rule's table in `steering/security.md`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_properties_of_tenant(
        self, tenant_id: uuid.UUID, property_ids: set[uuid.UUID]
    ) -> None:
        """Every property written must belong to the acting tenant. **Load-bearing.**

        `price_recommendations` has `UNIQUE (property_id, date)` with no `tenant_id` in it
        (PRD §7.18) and its FK to `properties` is global, not composite. So a row carrying
        tenant A's `tenant_id` and tenant B's `property_id` passes `_require_same_tenant`
        — the entity is self-consistent, it is just anchored to somebody else's flat.

        The damage is not the overwrite the `ON CONFLICT … WHERE` guards. It is the
        **first** insert, which finds no conflict at all: A takes the unique key `(P, date)`,
        and from then on every upsert B makes for its own property-day conflicts with A's
        row, fails that predicate, and is skipped — silently and for ever. B's horizon comes
        back empty with nothing raised anywhere.

        One query per call, which the nightly job makes once per property. Raised by the
        section-3 security panel, whose F1 showed the comment on the `where=` predicate was
        asserting an invariant this schema does not hold.

        **Safe only while nothing re-parents a property.** This `SELECT` and the `INSERT`
        share a transaction, but under READ COMMITTED that buys nothing against a *committed*
        change of `properties.tenant_id`, and the `FOR KEY SHARE` lock the foreign key takes
        does not block one either — `tenant_id` is not a key column. Nothing in
        `app/properties/` writes that column after construction today, so the window has no
        actor; if a "move a property between tenants" feature ever lands, this read needs
        `.with_for_update(read=True)`.
        """
        owned = await self._session.scalars(
            select(PropertyModel.id).where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.id.in_(sorted(property_ids)),
            )
        )
        foreign = property_ids - set(owned)
        if foreign:
            raise CrossTenantWriteError(
                entity=f"price recommendation for propert{'y' if len(foreign) == 1 else 'ies'} "
                f"{sorted(str(one) for one in foreign)}",
                entity_tenant_id="another tenant",
                acting_tenant_id=tenant_id,
            )

    async def get(
        self, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
    ) -> PriceRecommendation | None:
        model = await self._session.scalar(
            select(PriceRecommendationModel).where(
                PriceRecommendationModel.tenant_id == tenant_id,
                PriceRecommendationModel.id == recommendation_id,
            )
        )
        return _to_recommendation(model) if model is not None else None

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: PriceRecommendationFilters,
        *,
        page: int,
        per_page: int,
    ) -> PriceRecommendationPage:
        _require_positive_page(page, per_page)
        conditions = _recommendation_conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(PriceRecommendationModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(PriceRecommendationModel)
            .where(*conditions)
            # By the date being priced, ascending: this is a calendar, and a manager reads
            # it forwards. `id` makes the order total for the paginator.
            .order_by(PriceRecommendationModel.date.asc(), PriceRecommendationModel.id.asc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return PriceRecommendationPage(
            items=tuple(_to_recommendation(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def list_for_property_range(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        date_from: date,
        date_to: date,
    ) -> Sequence[PriceRecommendation]:
        rows = await self._session.execute(
            select(PriceRecommendationModel)
            .where(
                PriceRecommendationModel.tenant_id == tenant_id,
                PriceRecommendationModel.property_id == property_id,
                PriceRecommendationModel.date >= date_from,
                PriceRecommendationModel.date <= date_to,
            )
            .order_by(PriceRecommendationModel.date.asc())
        )
        return [_to_recommendation(model) for model in rows.scalars()]

    async def upsert_many(
        self,
        tenant_id: uuid.UUID,
        recommendations: Sequence[PriceRecommendation],
    ) -> UpsertOutcome:
        """`INSERT … ON CONFLICT (property_id, date) DO UPDATE` (R4.2, design D9).

        The `UNIQUE` decides, not a prior read, so two runs of the job cannot fail against
        each other. `RETURNING xmax = 0` is how each row reports which branch it took:
        Postgres leaves `xmax` at zero for a freshly inserted tuple and non-zero for one
        the conflict path updated, so `created` and `updated` come back from the statement
        itself rather than from a count taken before it — which would be a race.

        `preserved` is always zero here: the rows R4.3 protects never reach this method,
        because the use case filters them out before calling it. The field exists on the
        outcome so the caller can report all three counts from one place.
        """
        if not recommendations:
            return UpsertOutcome()

        for recommendation in recommendations:
            _require_same_tenant(recommendation.tenant_id, tenant_id, "price recommendation")

        # Two rows for one `(property_id, date)` in a single statement make Postgres raise
        # `ON CONFLICT DO UPDATE command cannot affect row a second time` — an
        # `IntegrityError` that nothing translates, so it would reach the caller as an
        # opaque 500. Answered here for the same reason `_require_positive_page` answers a
        # bad page: the generator should never produce one, and a caller that is not the
        # generator deserves to be told which key it duplicated. Raised by the section-3 QA
        # panel.
        keys = [(row.property_id, row.date) for row in recommendations]
        if len(set(keys)) != len(keys):
            duplicated = sorted(
                {f"{property_id}@{day}" for property_id, day in keys if keys.count(
                    (property_id, day)
                ) > 1}
            )
            raise PricingValidationError(
                "recommendations",
                f"one upsert cannot carry the same (property_id, date) twice: {duplicated}",
            )

        await self._require_properties_of_tenant(tenant_id, {row.property_id for row in
                                                             recommendations})

        statement = insert(PriceRecommendationModel).values(
            [
                {
                    "id": recommendation.id,
                    "tenant_id": tenant_id,
                    "property_id": recommendation.property_id,
                    "pricing_rule_id": recommendation.pricing_rule_id,
                    "date": recommendation.date,
                    "current_price": recommendation.current_price,
                    "recommended_price": recommendation.recommended_price,
                    "explanation": recommendation.explanation,
                    "confidence": recommendation.confidence,
                    "status": recommendation.status,
                    "created_at": recommendation.created_at,
                }
                for recommendation in recommendations
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=[PriceRecommendationModel.property_id, PriceRecommendationModel.date],
            set_={
                "recommended_price": statement.excluded.recommended_price,
                "explanation": statement.excluded.explanation,
                "pricing_rule_id": statement.excluded.pricing_rule_id,
            },
            # The conflict target is `(property_id, date)` and carries no tenant, because
            # that is the UNIQUE the schema declares. This predicate stops the statement
            # rewriting another tenant's row through it.
            #
            # It is a **live** guard, not a theoretical one — an earlier version of this
            # comment claimed a property belongs to exactly one tenant so it could never
            # fire, which is true of `properties` and false of this table: nothing ties a
            # recommendation's `tenant_id` to its property's owner. What makes it
            # unreachable today is `_require_properties_of_tenant` above, which refuses the
            # anchor before the statement is built. Both stay: this one guards a row already
            # in the table, that one guards the row in hand.
            #
            # **And the status guard, which is what makes R4.3 true rather than likely.**
            # The caller filters decided days out before calling, but that filter reads the
            # horizon *before* this statement runs, so an approval landing in between was
            # overwritten: the QA panel reproduced a `777.00` approval becoming `100.00`,
            # with no audit row (D12) and no timeline row (D14) to show it. A pre-read is
            # not concurrency control — D9 says so of counting, and it is just as true of
            # preserving. The `UNIQUE` decides what exists; this predicate decides what may
            # be rewritten.
            where=sql_and(
                PriceRecommendationModel.tenant_id == tenant_id,
                PriceRecommendationModel.status.notin_(_STATUSES_A_HUMAN_DECIDED),
            ),
        ).returning(
            _WAS_INSERTED,
            PriceRecommendationModel.property_id,
            PriceRecommendationModel.date,
        )

        rows = (await self._session.execute(statement)).all()
        # The keys the insert branch actually took, so the caller's timeline events describe
        # rows that exist (R4.4). Returned rather than inferred: on the conflict path the
        # stored row keeps its own `id`, so a caller emitting from its pre-read would point
        # an append-only event at an id no row carries.
        inserted = tuple(
            (property_id, day) for was_inserted, property_id, day in rows if was_inserted
        )
        await self._session.flush()
        if len(rows) == len(recommendations):
            return UpsertOutcome(inserted=inserted, updated=len(rows) - len(inserted))

        # A row either predicate skipped comes back as nothing, and the two reasons are not
        # remotely the same event: one is a human decision this statement must respect
        # (R4.3), the other is a cross-tenant write that every other path in this file
        # treats as fatal. Telling them apart needs one query, and only on this rare path.
        touched = {(property_id, day) for _, property_id, day in rows}
        missing = [key for key in keys if key not in touched]
        decided = await self._decided_among(tenant_id, missing)
        if len(decided) != len(missing):
            # Something was skipped that is not a decision of ours: another tenant's row
            # holds the key. Not-miscounting is not detecting — silence here would leave an
            # operator with a horizon full of holes and a job reporting success. Raised by
            # the section-3 security panel.
            raise CrossTenantWriteError(
                entity=f"price recommendation ({len(missing) - len(decided)} row(s) "
                "skipped by the tenant predicate)",
                entity_tenant_id="another tenant",
                acting_tenant_id=tenant_id,
            )
        return UpsertOutcome(
            inserted=inserted,
            updated=len(rows) - len(inserted),
            # Rows a human decided between the caller's read and this statement. The caller
            # counts the ones its own read already saw; these are the ones it could not.
            preserved=len(decided),
        )

    async def _decided_among(
        self, tenant_id: uuid.UUID, keys: Sequence[tuple[uuid.UUID, date]]
    ) -> set[tuple[uuid.UUID, date]]:
        """Which of `keys` this tenant holds in a status a regeneration must not touch.

        The reason `upsert_many` can add a status guard without turning every preserved row
        into a spurious cross-tenant alarm: `ON CONFLICT` reports a skip without saying why,
        so the why is read back for the handful of keys that were skipped.
        """
        if not keys:
            return set()
        rows = await self._session.execute(
            select(PriceRecommendationModel.property_id, PriceRecommendationModel.date).where(
                PriceRecommendationModel.tenant_id == tenant_id,
                PriceRecommendationModel.status.in_(_STATUSES_A_HUMAN_DECIDED),
                tuple_(PriceRecommendationModel.property_id, PriceRecommendationModel.date).in_(
                    keys
                ),
            )
        )
        return {(property_id, day) for property_id, day in rows.all()}

    async def update(
        self, tenant_id: uuid.UUID, recommendation: PriceRecommendation
    ) -> None:
        _require_same_tenant(recommendation.tenant_id, tenant_id, "price recommendation")
        await self._session.execute(
            update(PriceRecommendationModel)
            .where(
                PriceRecommendationModel.tenant_id == tenant_id,
                PriceRecommendationModel.id == recommendation.id,
            )
            .values(
                **{
                    column: getattr(recommendation, column)
                    for column in _MUTABLE_RECOMMENDATION_COLUMNS
                }
            )
        )
        await self._session.flush()
