"""Wiring for the pricing endpoints: one builder per use case (design D1).

Same shape as `app/maintenance/api/dependencies.py`. The repositories take the session from
`get_db_session` — the same session `get_authenticated_request` has already marked with the
tenant, so the listener of `app/core/db.py` scopes ORM reads as well. That is the net; the
explicit `tenant_id` every repository method takes is the mechanism.

`_write_kwargs` exists for the reason `maintenance`'s `_flow_kwargs` does: a use case that
forgot its audit repository would silently stop honouring rule 9 of `steering/security.md`,
and the two rule writers plus the decision writer all need the same four collaborators.

**`SqlAlchemyUnitOfWork` and never `CallerOwnedUnitOfWork`**, and for the generator that is
load-bearing rather than conventional: D9 makes it abandon the failed property's transaction
so the sweep can carry on, and `GeneratePriceRecommendationsUseCase.__init__` refuses a
boundary whose `rollback()` is a no-op. A request owns its own transaction here, so the real
one is also the correct one.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.pricing.application.use_cases import (
    CreatePricingRuleUseCase,
    DecidePriceRecommendationUseCase,
    GeneratePriceRecommendationsUseCase,
    GetPricingRuleUseCase,
    ListPriceRecommendationsUseCase,
    ListPricingRulesUseCase,
    UpdatePricingRuleUseCase,
)
from app.pricing.infrastructure.repositories import (
    SqlAlchemyPriceRecommendationRepository,
    SqlAlchemyPricingRuleRepository,
)
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _rule_write_kwargs(session: AsyncSession) -> dict:
    """The four collaborators both rule writers take.

    `properties` is not optional decoration: D20 makes the two of them resolve a
    `property_id` a human typed *inside* the acting tenant before it can reach a statement,
    and a builder that omitted it would not construct.
    """
    return {
        "rules": SqlAlchemyPricingRuleRepository(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def get_list_pricing_rules_use_case(session: SessionDep) -> ListPricingRulesUseCase:
    return ListPricingRulesUseCase(SqlAlchemyPricingRuleRepository(session))


def get_pricing_rule_use_case(session: SessionDep) -> GetPricingRuleUseCase:
    return GetPricingRuleUseCase(SqlAlchemyPricingRuleRepository(session))


def get_create_pricing_rule_use_case(session: SessionDep) -> CreatePricingRuleUseCase:
    return CreatePricingRuleUseCase(**_rule_write_kwargs(session))


def get_update_pricing_rule_use_case(session: SessionDep) -> UpdatePricingRuleUseCase:
    return UpdatePricingRuleUseCase(**_rule_write_kwargs(session))


def get_list_price_recommendations_use_case(
    session: SessionDep,
) -> ListPriceRecommendationsUseCase:
    return ListPriceRecommendationsUseCase(
        SqlAlchemyPriceRecommendationRepository(session)
    )


def get_generate_price_recommendations_use_case(
    session: SessionDep,
) -> GeneratePriceRecommendationsUseCase:
    return GeneratePriceRecommendationsUseCase(
        rules=SqlAlchemyPricingRuleRepository(session),
        recommendations=SqlAlchemyPriceRecommendationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_decide_price_recommendation_use_case(
    session: SessionDep,
) -> DecidePriceRecommendationUseCase:
    return DecidePriceRecommendationUseCase(
        recommendations=SqlAlchemyPriceRecommendationRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
