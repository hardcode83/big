"""Wiring for the use-case tests of `maintenance` (section 6).

**Integration and not unit-with-fakes**, which is a deliberate departure from
`steering/backend-architecture.md`'s "application/: unit tests con **fakes** en memoria de
los puertos". The invariant these use cases carry is not their own arithmetic: it is what
D7 calls the main functional risk of the change — that
`ContextualStateResolver.after_incident_resolution` is handed **all three** collections, and
that a missing one yields a plausible, wrong destination without failing anything. A fake
repository returns whatever the test told it to, so it would agree with a use case that
assembled the context wrong. Only the real machine over real rows can disagree.

`tests/cleaning` reached the same place for the same reason — its lifecycle tests run
against the database — so this is the house pattern for the state-machine seam rather than
an exception invented here.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest_asyncio

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.infrastructure.classifier import RuleBasedIncidentClassifier
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyLiveCleaningTaskQuery,
    SqlAlchemyOwnerApprovalRepository,
)
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)

#: The key the `api` fixture both signs and verifies with. Its own, so a test can issue a
#: token for any of the `world` users without going through a login round trip.
SECRET = "m" * 64


class Flow:
    """Every port of section 6, wired to one session.

    A class rather than a bag of fixtures so a test reads as `flow.classify.execute(...)`
    and the wiring — which is what `api/dependencies.py` will have to repeat in section 8 —
    lives in one place that a reviewer can check against D14.
    """

    def __init__(self, session) -> None:
        from app.maintenance.application.use_cases import (
            AcceptIncidentUseCase,
            AssignIncidentUseCase,
            CancelIncidentUseCase,
            ClassifyIncidentUseCase,
            GetIncidentUseCase,
            ListIncidentsUseCase,
            ResolveIncidentUseCase,
            RespondOwnerApprovalUseCase,
            ResumeWorkUseCase,
            StartIncidentUseCase,
            TriageIncidentUseCase,
            WaitForPartsUseCase,
        )

        self.session = session
        self.incidents = SqlAlchemyIncidentRepository(session)
        self.reader = SqlAlchemyIncidentReader(session)
        self.approvals = SqlAlchemyOwnerApprovalRepository(session)
        self.notifications = SqlAlchemyNotificationLogRepository(session)
        self.classifier = RuleBasedIncidentClassifier()
        common = {
            "incidents": self.incidents,
            "reader": self.reader,
            "properties": SqlAlchemyPropertyRepository(session),
            "transitions": SqlAlchemyPropertyStateTransitionRepository(session),
            "timeline": SqlAlchemyTimelineEventRepository(session),
            "reservations": SqlAlchemyReservationRepository(session),
            "cleaning_tasks": SqlAlchemyLiveCleaningTaskQuery(session),
            "audit": SqlAlchemyAuditLogRepository(session),
            "uow": SqlAlchemyUnitOfWork(session),
        }
        users = SqlAlchemyUserRepository(session)
        configs = SqlAlchemyTenantConfigRepository(session)

        self.classify = ClassifyIncidentUseCase(
            classifier=self.classifier, configs=configs, **common
        )
        self.triage = TriageIncidentUseCase(
            approvals=self.approvals,
            users=users,
            notifications=self.notifications,
            configs=configs,
            **common,
        )
        self.respond = RespondOwnerApprovalUseCase(approvals=self.approvals, **common)
        self.assign = AssignIncidentUseCase(
            users=users, notifications=self.notifications, configs=configs, **common
        )
        self.accept = AcceptIncidentUseCase(notifications=self.notifications, **common)
        self.start = StartIncidentUseCase(**common)
        self.wait_for_parts = WaitForPartsUseCase(**common)
        self.resume_work = ResumeWorkUseCase(**common)
        self.resolve = ResolveIncidentUseCase(
            approvals=self.approvals,
            users=users,
            notifications=self.notifications,
            configs=configs,
            **common,
        )
        self.cancel = CancelIncidentUseCase(**common)
        self.list = ListIncidentsUseCase(self.reader)
        self.get = GetIncidentUseCase(self.incidents)


@pytest_asyncio.fixture
async def flow(db_session) -> Flow:
    return Flow(db_session)


class World:
    """One tenant, one property and the four people who act on an incident."""

    def __init__(self, tenant, prop, owner, manager, technician, other_technician) -> None:
        self.tenant = tenant
        self.property = prop
        self.owner = owner
        self.manager = manager
        self.technician = technician
        self.other_technician = other_technician


async def _user(db_session, tenant: TenantModel, role: str) -> UserModel:
    """`UserRole(role)` and not the bare string: the attribute is read back from the
    identity map before any refresh, so a `str` would reach `candidate.role is not
    UserRole.TECHNICIAN` as a `str` and fail an identity comparison that is correct."""
    from app.auth.domain.enums import UserRole

    user = UserModel(
        tenant_id=tenant.id,
        name=f"{role.title()} {uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        password_hash="hash",
        role=UserRole(role),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def world(db_session) -> World:
    from app.properties.domain.enums import PropertyOperationalState

    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Redes 11",
        internal_code="REDES11",
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    db_session.add(prop)
    await db_session.flush()
    return World(
        tenant,
        prop,
        await _user(db_session, tenant, "TENANT_OWNER"),
        await _user(db_session, tenant, "PROPERTY_MANAGER"),
        await _user(db_session, tenant, "TECHNICIAN"),
        await _user(db_session, tenant, "TECHNICIAN"),
    )


async def make_incident(
    db_session,
    world: World,
    *,
    title: str = "Se ha roto la caldera",
    description: str = "Sale agua por debajo y no hay agua caliente.",
    status=None,
    severity=None,
) -> IncidentModel:
    from app.maintenance.domain.enums import (
        IncidentCategory,
        IncidentSeverity,
        IncidentSource,
        IncidentStatus,
    )

    incident = IncidentModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        source=IncidentSource.GUEST,
        title=title,
        description=description,
        category=IncidentCategory.OTHER,
        severity=severity or IncidentSeverity.MEDIUM,
        status=status or IncidentStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(incident)
    await db_session.flush()
    return incident


async def make_approval(
    db_session, world: World, incident_id: uuid.UUID, *, related_type=None, amount="450.00"
) -> OwnerApprovalModel:
    from decimal import Decimal

    from app.maintenance.domain.enums import OwnerApprovalRelatedType

    approval = OwnerApprovalModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        related_type=related_type or OwnerApprovalRelatedType.INCIDENT,
        related_id=incident_id,
        amount=Decimal(amount),
        reason="Maintenance expense above the tenant threshold.",
        requested_at=NOW,
    )
    db_session.add(approval)
    await db_session.flush()
    return approval


async def make_reservation(
    db_session, world: World, *, check_in: date, check_out: date, status=None
) -> ReservationModel:
    from app.reservations.domain.enums import ReservationChannel, ReservationStatus

    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        channel=ReservationChannel.DIRECT,
        status=status or ReservationStatus.CONFIRMED,
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
async def api(db_session):
    """The real app over the test session, so the endpoint tests exercise `require(...)`,
    the error handlers and the response schemas rather than a use case behind them."""
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
    """A real access token for `user`, issued by the same codec the app verifies with.

    Issued at the **wall clock** and not at `NOW`: the fixtures' instant is a fixed point in
    the change's own timeline, and a token stamped there is either expired or issued in the
    future depending on when the suite runs. The routes call `now_utc()` themselves, so the
    two clocks never have to agree.
    """
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}


async def make_cleaning_task(db_session, world: World, status) -> CleaningTaskModel:
    template = CleaningChecklistTemplateModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        name=f"Standard {uuid.uuid4().hex[:6]}",
        items=[{"id": "kitchen", "label": "Kitchen", "required": True}],
        required_photos=[],
    )
    db_session.add(template)
    await db_session.flush()
    task = CleaningTaskModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        checklist_template_id=template.id,
        status=status,
        scheduled_start=NOW,
        scheduled_end=NOW + timedelta(hours=2),
    )
    db_session.add(task)
    await db_session.flush()
    return task
