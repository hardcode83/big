"""Fixtures for the pricing integration tests.

Two tenants from the start, not one: DoD §28.18 asks every module for a test proving one
tenant cannot reach another's rows, and a world with a single tenant makes that test
impossible to write without inventing the second one inline in every case.

Since section 6 the `World` also carries **one user per role**, which the API tests need for a
different reason than the isolation ones: D11's role × permission matrix is fixed in
`tests/auth/test_policy.py`, and what that cannot show is that each of the seven routes hangs
off the permission it should. Walking the surface per role is the only thing that does.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest_asyncio

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.pricing.domain.entities import PriceRecommendation, PricingRule
from app.pricing.infrastructure.repositories import (
    SqlAlchemyPriceRecommendationRepository,
    SqlAlchemyPricingRuleRepository,
)
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 17, 6, tzinfo=timezone.utc)
TODAY = date(2026, 8, 17)

#: The JWT secret the `api` fixture's codec signs with, so a test can mint a real token for a
#: seeded user. Not the app's configured one on purpose: the app under test gets this codec by
#: dependency override, which keeps the suite independent of the environment's `JWT_SECRET_KEY`.
SECRET = "p" * 64


class World:
    """Two tenants, each with a property — the shape a tenant-isolation test needs."""

    def __init__(
        self,
        tenant,
        prop,
        second_property,
        other_tenant,
        other_property,
        manager=None,
        other_manager=None,
        owner=None,
        cleaner=None,
        technician=None,
    ) -> None:
        self.tenant = tenant
        self.property = prop
        self.second_property = second_property
        self.other_tenant = other_tenant
        self.other_property = other_property
        #: The authenticated person every audited pricing action names (design D12).
        self.manager = manager
        self.other_manager = other_manager
        #: D11 gives the owner the same four permissions as the manager — the divergence from
        #: "the owner sees, the manager operates" that its own paragraph argues for, because
        #: `min_price`/`max_price` are the limits of her own money.
        self.owner = owner
        #: The two roles that hold none of the four, so every route must refuse them.
        self.cleaner = cleaner
        self.technician = technician


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(
    db_session, tenant: TenantModel, code: str, status: PropertyStatus = PropertyStatus.ACTIVE
) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=f"Property {code}",
        internal_code=code,
        status=status,
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


async def _user(db_session, tenant: TenantModel, role: UserRole) -> UserModel:
    user = UserModel(
        tenant_id=tenant.id,
        name=f"{role.value} {uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        password_hash="hash",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _manager(db_session, tenant: TenantModel) -> UserModel:
    return await _user(db_session, tenant, UserRole.PROPERTY_MANAGER)


@pytest_asyncio.fixture
async def world(db_session) -> World:
    tenant = await _tenant(db_session, "TenantA")
    other_tenant = await _tenant(db_session, "TenantB")
    return World(
        tenant,
        await _property(db_session, tenant, "REDES11"),
        await _property(db_session, tenant, "REDES12"),
        other_tenant,
        await _property(db_session, other_tenant, "OTHER1"),
        await _manager(db_session, tenant),
        await _manager(db_session, other_tenant),
        await _user(db_session, tenant, UserRole.TENANT_OWNER),
        await _user(db_session, tenant, UserRole.CLEANER),
        await _user(db_session, tenant, UserRole.TECHNICIAN),
    )


@pytest_asyncio.fixture
async def api(db_session):
    """The real app over the test session (design D1's routers, end to end).

    The endpoint tests go through `create_app()` rather than calling a use case, because what
    they exist to prove lives above it: `require(...)`, the error handlers of `api/errors.py`
    and the response schemas that decide what a client actually sees.
    """
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import get_token_codec
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app

    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


def auth_header(client, user: UserModel) -> dict[str, str]:
    """A real access token for `user`, issued by the codec the app verifies with.

    Issued at the **wall clock** and not at `NOW`: the fixtures' instant is a fixed point in
    this change's own timeline, and a token stamped there is either expired or issued in the
    future depending on when the suite runs. The routes call `now_utc()` themselves, so the
    two clocks never have to agree — which is also why a generated horizon in an API test
    starts tomorrow relative to *today*, not to `TODAY`.
    """
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}


class Flow:
    """Every use case of section 5, wired to one session.

    Integration and not unit-with-fakes, which departs from
    `steering/backend-architecture.md`'s "application/: unit tests con fakes en memoria de
    los puertos" for the reason `tests/maintenance/conftest.py` records for its own: the
    invariants these use cases carry are not their arithmetic. They are idempotency against
    a real `UNIQUE (property_id, date)`, a decision surviving a regeneration, and a
    transaction boundary per property — all three of which a fake repository would agree
    with whatever the use case did.

    A class rather than a bag of fixtures so a test reads as `flow.generate.execute(...)`
    and the wiring — which `api/dependencies.py` repeats in section 6 — lives in one place.
    """

    def __init__(self, session) -> None:
        from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
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
        from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
        from app.reservations.infrastructure.repositories import (
            SqlAlchemyReservationRepository,
        )
        from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

        self.session = session
        self.rules = SqlAlchemyPricingRuleRepository(session)
        self.recommendations = SqlAlchemyPriceRecommendationRepository(session)
        self.properties = SqlAlchemyPropertyRepository(session)
        self.audit = SqlAlchemyAuditLogRepository(session)
        self.timeline = SqlAlchemyTimelineEventRepository(session)
        uow = SqlAlchemyUnitOfWork(session)

        self.create_rule = CreatePricingRuleUseCase(
            rules=self.rules, properties=self.properties, audit=self.audit, uow=uow
        )
        self.update_rule = UpdatePricingRuleUseCase(
            rules=self.rules, properties=self.properties, audit=self.audit, uow=uow
        )
        self.get_rule = GetPricingRuleUseCase(self.rules)
        self.list_rules = ListPricingRulesUseCase(self.rules)
        self.generate = GeneratePriceRecommendationsUseCase(
            rules=self.rules,
            recommendations=self.recommendations,
            properties=self.properties,
            reservations=SqlAlchemyReservationRepository(session),
            timeline=self.timeline,
            audit=self.audit,
            uow=uow,
        )
        self.list_recommendations = ListPriceRecommendationsUseCase(self.recommendations)
        self.decide = DecidePriceRecommendationUseCase(
            recommendations=self.recommendations,
            audit=self.audit,
            timeline=self.timeline,
            uow=uow,
        )


@pytest_asyncio.fixture
async def flow(db_session) -> Flow:
    return Flow(db_session)


async def make_reservation(
    db_session,
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    *,
    check_in: date,
    check_out: date,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> ReservationModel:
    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        channel=ReservationChannel.DIRECT,
        status=status,
        check_in_date=check_in,
        check_out_date=check_out,
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
        nights=(check_out - check_in).days,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


@pytest_asyncio.fixture
async def rules(db_session) -> SqlAlchemyPricingRuleRepository:
    return SqlAlchemyPricingRuleRepository(db_session)


@pytest_asyncio.fixture
async def recommendations(db_session) -> SqlAlchemyPriceRecommendationRepository:
    return SqlAlchemyPriceRecommendationRepository(db_session)


def make_rule(tenant_id: uuid.UUID, **overrides: Any) -> PricingRule:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "name": "Madrid base",
        "base_price": Decimal("100.00"),
        "min_price": Decimal("50.00"),
        "max_price": Decimal("200.00"),
        "now": NOW,
    }
    fields.update(overrides)
    return PricingRule.create(**fields)


def make_recommendation(
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    pricing_rule_id: uuid.UUID,
    *,
    day: date = TODAY,
    price: Decimal = Decimal("120.00"),
    explanation: str = "Base price 100.00 EUR. Recommended 120.00 EUR.",
) -> PriceRecommendation:
    return PriceRecommendation.create(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        pricing_rule_id=pricing_rule_id,
        date=day,
        recommended_price=price,
        explanation=explanation,
        now=NOW,
    )


def horizon(
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    pricing_rule_id: uuid.UUID,
    *,
    days: int,
    start: date = TODAY,
    price: Decimal = Decimal("120.00"),
) -> list[PriceRecommendation]:
    return [
        make_recommendation(
            tenant_id,
            property_id,
            pricing_rule_id,
            day=start + timedelta(days=offset),
            price=price,
        )
        for offset in range(days)
    ]
