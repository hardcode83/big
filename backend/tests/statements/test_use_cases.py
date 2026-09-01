"""Integration tests for the eleven use cases of `statements/application/use_cases.py`.

Integration rather than unit-with-fakes, mirroring `tests/maintenance/test_*`: the
invariants the use cases carry are not their own arithmetic but the **integration** with
the database (consolidation guard, period UNIQUE, threshold approval flow), and a fake
repository would agree with whatever the code did.

The wiring is centralised in `Flow`, a class that mirrors what
`app/statements/api/dependencies.py` will be when section 6 lands — reviewing the
diff against this file is how a panel confirms that the use case's declared collaborators
are exactly what the API would wire.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.domain.enums import OwnerApprovalRelatedType
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyOwnerApprovalRepository,
)
from app.properties.domain.enums import PropertyStatus
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.statements.application.use_cases import (
    CreateExpenseUseCase,
    DeleteExpenseUseCase,
    ExportOwnerStatementCsvUseCase,
    ExportOwnerStatementPdfUseCase,
    GenerateOwnerStatementUseCase,
    GetExpenseUseCase,
    GetOwnerStatementUseCase,
    ListExpensesUseCase,
    ListOwnerStatementsUseCase,
    StatementsActor,
    TransitionOwnerStatementStatusUseCase,
    UpdateExpenseUseCase,
    UpdateOwnerStatementNotesUseCase,
)
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.domain.exceptions import (
    ExpenseAlreadyConsolidatedError,
    NamedExpenseInClosedPeriodError,
    OwnerStatementInvalidTransitionError,
    OwnerStatementNotFoundError,
    OwnerStatementValidationError,
)
from app.statements.domain.repositories import (
    OwnerStatementFilters,
)
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.statements.infrastructure.repositories import (
    SqlAlchemyExpenseRepository,
    SqlAlchemyOwnerStatementRepository,
)
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)

pytestmark = pytest.mark.asyncio


class Flow:
    """Every use case of §4.1-4.10, wired to one session."""

    def __init__(self, session) -> None:
        self.session = session
        self.statements = SqlAlchemyOwnerStatementRepository(session)
        self.expenses = SqlAlchemyExpenseRepository(session)
        self.properties = SqlAlchemyPropertyRepository(session)
        self.reservations = SqlAlchemyReservationRepository(session)
        self.timeline = SqlAlchemyTimelineEventRepository(session)
        self.audit = SqlAlchemyAuditLogRepository(session)
        self.approvals = SqlAlchemyOwnerApprovalRepository(session)
        self.tenant_configs = SqlAlchemyTenantConfigRepository(session)
        self.tenants = SqlAlchemyTenantRepository(session)
        self.uow = SqlAlchemyUnitOfWork(session)
        common = {
            "statements": self.statements,
            "expenses": self.expenses,
            "properties": self.properties,
            "reservations": self.reservations,
            "timeline": self.timeline,
            "audit": self.audit,
            "uow": self.uow,
        }
        self.create_expense = CreateExpenseUseCase(
            expenses=self.expenses,
            properties=self.properties,
            approvals=self.approvals,
            configs=self.tenant_configs,
            audit=self.audit,
            uow=self.uow,
        )
        self.update_expense = UpdateExpenseUseCase(
            expenses=self.expenses,
            approvals=self.approvals,
            configs=self.tenant_configs,
            audit=self.audit,
            uow=self.uow,
        )
        self.delete_expense = DeleteExpenseUseCase(
            expenses=self.expenses, audit=self.audit, uow=self.uow
        )
        self.get_expense = GetExpenseUseCase(self.expenses)
        self.list_expenses = ListExpensesUseCase(self.expenses)
        self.get_statement = GetOwnerStatementUseCase(
            statements=self.statements,
            expenses=self.expenses,
            reservations=self.reservations,
        )
        self.list_statements = ListOwnerStatementsUseCase(self.statements)
        self.update_notes = UpdateOwnerStatementNotesUseCase(
            statements=self.statements, audit=self.audit, uow=self.uow
        )
        self.transition_status = TransitionOwnerStatementStatusUseCase(
            statements=self.statements, audit=self.audit, uow=self.uow
        )
        self.generate = GenerateOwnerStatementUseCase(
            configs=self.tenant_configs, **common
        )
        # Fakes: the CSV exporter and PDF generator live in `infrastructure/` and are
        # the dependency the API builder injects. The use cases take them through
        # their constructor so the export tests can pin the bytes the serializer
        # would produce without going through the real fpdf2/stdlib csv writers.
        class _FakeCsvExporter:
            def render(self, *, header, rows):
                return (",".join(header) + "\n" + "\n".join(str(r) for r in rows)).encode()

        class _FakePdfGenerator:
            def render(
                self,
                *,
                statement,
                property,
                tenant,
                reservations,
                expenses_by_category,
            ):
                return b"%PDF-fake"

        self.export_csv = ExportOwnerStatementCsvUseCase(
            expenses=self.expenses,
            statements=self.statements,
            csv_exporter=_FakeCsvExporter(),
        )
        self.export_pdf = ExportOwnerStatementPdfUseCase(
            statements=self.statements,
            expenses=self.expenses,
            properties=self.properties,
            tenants=self.tenants,
            reservations=self.reservations,
            pdf_generator=_FakePdfGenerator(),
        )


@pytest_asyncio.fixture
async def flow(db_session) -> Flow:
    return Flow(db_session)


class World:
    def __init__(self, tenant, prop, manager) -> None:
        self.tenant = tenant
        self.property = prop
        self.manager = manager


@pytest_asyncio.fixture
async def world(db_session) -> World:
    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    config = TenantConfigModel(tenant_id=tenant.id)
    db_session.add(config)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Redes 11",
        internal_code="REDES11",
        status=PropertyStatus.ACTIVE,
    )
    db_session.add(prop)
    await db_session.flush()
    from app.auth.domain.enums import UserRole
    from app.auth.infrastructure.models import UserModel

    manager = UserModel(
        tenant_id=tenant.id,
        name="Manager One",
        email="manager@example.com",
        password_hash="hash",
        role=UserRole.PROPERTY_MANAGER,
    )
    db_session.add(manager)
    await db_session.flush()
    return World(tenant, prop, manager)


def actor_of(world: World) -> StatementsActor:
    return StatementsActor(user_id=world.manager.id, ip="10.0.0.1")


# ---- CreateExpenseUseCase (R5.1, R5.2, R5.6, R5.7, D4) -----------------------------


class TestCreateExpense:
    async def test_creates_an_expense_and_returns_no_approval_under_threshold(
        self, flow: Flow, world: World
    ) -> None:
        expense, approval_id = await flow.create_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            property_id=world.property.id,
            category=ExpenseCategory.CLEANING,
            description="Turnover clean",
            amount=Decimal("50.00"),
            date_=date(2026, 7, 12),
        )
        assert expense.id is not None
        assert approval_id is None
        assert expense.approved_by is None

    async def test_creates_an_expense_and_a_pending_approval_over_threshold(
        self, flow: Flow, world: World
    ) -> None:
        # TenantConfig.owner_approval_threshold_eur defaults to 100.00.
        expense, approval_id = await flow.create_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            property_id=world.property.id,
            category=ExpenseCategory.MAINTENANCE,
            description="Boiler part",
            amount=Decimal("150.00"),
            date_=date(2026, 7, 15),
        )
        assert approval_id is not None
        # `OTHER` is the canonical related_type (D4 / §3 fix-rounds regression).
        approval = await flow.approvals.get(world.tenant.id, approval_id)
        assert approval is not None
        assert approval.related_type is OwnerApprovalRelatedType.OTHER
        assert approval.related_id == expense.id
        assert approval.amount == Decimal("150.00")

    async def test_rejects_empty_description(self, flow: Flow, world: World) -> None:
        with pytest.raises(OwnerStatementValidationError):
            await flow.create_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                property_id=world.property.id,
                category=ExpenseCategory.CLEANING,
                description="   ",
                amount=Decimal("10.00"),
                date_=date(2026, 7, 12),
            )

    async def test_rejects_description_with_null_byte(self, flow: Flow, world: World) -> None:
        with pytest.raises(OwnerStatementValidationError):
            await flow.create_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                property_id=world.property.id,
                category=ExpenseCategory.CLEANING,
                description="before\x00after",
                amount=Decimal("10.00"),
                date_=date(2026, 7, 12),
            )

    async def test_rejects_amount_over_column_ceiling(self, flow: Flow, world: World) -> None:
        with pytest.raises(OwnerStatementValidationError):
            await flow.create_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                property_id=world.property.id,
                category=ExpenseCategory.CLEANING,
                description="huge",
                amount=Decimal(1000000000),  # way past NUMERIC(10,2)
                date_=date(2026, 7, 12),
            )

    async def test_rejects_unknown_property(self, flow: Flow, world: World) -> None:
        with pytest.raises(OwnerStatementValidationError):
            await flow.create_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                property_id=uuid.uuid4(),
                category=ExpenseCategory.CLEANING,
                description="huh",
                amount=Decimal("10.00"),
                date_=date(2026, 7, 12),
            )


# ---- UpdateExpenseUseCase / DeleteExpenseUseCase (R5.3, R5.4, D6.2, D6.3) ------


class TestUpdateAndDeleteExpense:
    async def test_updates_a_mutable_field(self, flow: Flow, world: World) -> None:
        expense, _ = await flow.create_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            property_id=world.property.id,
            category=ExpenseCategory.CLEANING,
            description="Turnover",
            amount=Decimal("50.00"),
            date_=date(2026, 7, 12),
        )
        updated, _pending = await flow.update_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            expense_id=expense.id,
            description="Turnover (post-stay review)",
        )
        assert updated.description == "Turnover (post-stay review)"

    async def test_rejects_a_date_in_a_closed_period(
        self, flow: Flow, world: World
    ) -> None:
        # Seed an existing OwnerStatement covering 2026-07-01 to 2026-07-31.
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            status=OwnerStatementStatus.DRAFT,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        with pytest.raises(NamedExpenseInClosedPeriodError):
            await flow.create_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                property_id=world.property.id,
                category=ExpenseCategory.CLEANING,
                description="Too late",
                amount=Decimal("10.00"),
                date_=date(2026, 7, 12),  # inside the closed period
            )

    async def test_delete_succeeds_for_unconsolidated(self, flow: Flow, world: World) -> None:
        expense, _ = await flow.create_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            property_id=world.property.id,
            category=ExpenseCategory.CLEANING,
            description="Trash",
            amount=Decimal("5.00"),
            date_=date(2026, 7, 12),
        )
        await flow.delete_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            expense_id=expense.id,
        )
        assert await flow.expenses.get(world.tenant.id, expense.id) is None

    async def test_delete_rejects_when_consolidated(
        self, flow: Flow, world: World
    ) -> None:
        expense, _ = await flow.create_expense.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=NOW,
            property_id=world.property.id,
            category=ExpenseCategory.CLEANING,
            description="Already counted",
            amount=Decimal("50.00"),
            date_=date(2026, 7, 12),
        )
        # Create a real OwnerStatement first (FK target), then associate the expense
        # to it; the delete guard fires on `statement_id IS NOT NULL`.
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        await flow.expenses.bulk_associate_to_statement(
            tenant_id=world.tenant.id,
            expense_ids=[expense.id],
            statement_id=stmt.id,
        )
        with pytest.raises(ExpenseAlreadyConsolidatedError):
            await flow.delete_expense.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                expense_id=expense.id,
            )


# ---- Get/List OwnerStatementUseCase + notes/transition (R3, R4) -------------------


class TestOwnerStatementReads:
    async def test_get_returns_none_for_other_tenant(self, flow: Flow, world: World) -> None:
        # The repository returns `None` for cross-tenant; the use case maps that to
        # `OwnerStatementNotFoundError`.
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        with pytest.raises(OwnerStatementNotFoundError):
            await flow.get_statement.execute(
                tenant_id=uuid.uuid4(),  # not the owner's
                statement_id=stmt.id,
            )

    async def test_list_filters_by_property(self, flow: Flow, world: World) -> None:
        # Add a second property; only one row should match.
        other = PropertyModel(
            tenant_id=world.tenant.id,
            name="Other",
            internal_code="OTHER-1",
        )
        flow.session.add(other)
        await flow.session.flush()
        for prop in (world.property, other):
            flow.session.add(
                OwnerStatementModel(
                    id=uuid.uuid4(),
                    tenant_id=world.tenant.id,
                    property_id=prop.id,
                    period_start=PERIOD_START,
                    period_end=PERIOD_END,
                )
            )
        await flow.session.flush()
        items, total = await flow.list_statements.execute(
            tenant_id=world.tenant.id,
            filters=OwnerStatementFilters(property_id=world.property.id),
            page=1,
        )
        assert total == 1
        assert items[0].property_id == world.property.id


class TestOwnerStatementNotes:
    async def test_updates_notes_on_a_draft(self, flow: Flow, world: World) -> None:
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        later = datetime(2026, 8, 16, tzinfo=UTC)
        updated = await flow.update_notes.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=later,
            statement_id=stmt.id,
            notes="Reviewed with the owner.",
        )
        assert updated.notes == "Reviewed with the owner."
        assert updated.updated_at == later

    async def test_rejects_empty_notes(self, flow: Flow, world: World) -> None:
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        with pytest.raises(OwnerStatementValidationError):
            await flow.update_notes.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                statement_id=stmt.id,
                notes="",
            )

    async def test_revert_updated_at_on_validation_failure(
        self, flow: Flow, world: World
    ) -> None:
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        snapshot = stmt.updated_at
        later = datetime(2026, 8, 16, tzinfo=UTC)
        with pytest.raises(OwnerStatementValidationError):
            await flow.update_notes.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=later,
                statement_id=stmt.id,
                notes="   ",  # rejected
            )
        # Snapshot must be intact (R4.6).
        assert stmt.updated_at == snapshot


class TestOwnerStatementTransition:
    async def test_draft_to_ready(self, flow: Flow, world: World) -> None:
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        later = datetime(2026, 8, 16, tzinfo=UTC)
        updated = await flow.transition_status.execute(
            tenant_id=world.tenant.id,
            actor=actor_of(world),
            now=later,
            statement_id=stmt.id,
            target_status=OwnerStatementStatus.READY,
        )
        assert updated.status is OwnerStatementStatus.READY
        assert updated.updated_at == later

    async def test_rejects_draft_to_sent(self, flow: Flow, world: World) -> None:
        stmt = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        flow.session.add(stmt)
        await flow.session.flush()
        with pytest.raises(OwnerStatementInvalidTransitionError):
            await flow.transition_status.execute(
                tenant_id=world.tenant.id,
                actor=actor_of(world),
                now=NOW,
                statement_id=stmt.id,
                target_status=OwnerStatementStatus.SENT,
            )


# ---- GenerateOwnerStatementUseCase (R1, R2, D3, D6.1) ----------------------------


class TestGenerate:
    async def test_idempotent_on_a_second_call_over_same_key(
        self, flow: Flow, world: World
    ) -> None:
        await _seed_reservation(flow, world)
        first = await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        assert first.created == 1
        second = await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        assert second.created == 0
        assert second.skipped == 1

    async def test_aborts_on_mixed_currency(self, flow: Flow, world: World) -> None:
        # Add a USD reservation that overlaps the period.
        flow.session.add(
            ReservationModel(
                id=uuid.uuid4(),
                tenant_id=world.tenant.id,
                property_id=world.property.id,
                channel="DIRECT",
                status="CONFIRMED",
                check_in_date=date(2026, 7, 5),
                check_out_date=date(2026, 7, 10),
                nights=5,
                gross_amount=Decimal("200.00"),
                ota_commission=Decimal(0),
                net_amount=Decimal("200.00"),
                currency="USD",
            )
        )
        await flow.session.flush()
        outcome = await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        assert outcome.created == 0
        assert outcome.failed == 1
        assert outcome.currency_mismatch  # at least one entry

    async def test_creates_when_called_with_actor(
        self, flow: Flow, world: World
    ) -> None:
        await _seed_reservation(flow, world)
        outcome = await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        assert outcome.created == 1
        assert outcome.skipped == 0
        # Manual path writes an AuditLog (R7.5).
        from sqlalchemy import select

        from app.audit.infrastructure.models import AuditLogModel

        rows = (
            await flow.session.execute(
                select(AuditLogModel).where(
                    AuditLogModel.tenant_id == world.tenant.id,
                    AuditLogModel.action == "OWNER_STATEMENT_GENERATED",
                )
            )
        ).scalars()
        assert any(row.entity_type == "OWNER_STATEMENT" for row in rows)


# ---- Export use cases (R6) -------------------------------------------------------


class TestExports:
    async def test_csv_returns_header_and_in_statement_rows(
        self, flow: Flow, world: World
    ) -> None:
        await _seed_reservation(flow, world)
        # Generate, which associates the period's expenses to the new statement.
        await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        statements, _ = await flow.list_statements.execute(
            tenant_id=world.tenant.id,
            filters=OwnerStatementFilters(property_id=world.property.id),
            page=1,
        )
        statement_id = statements[0].id
        _statement, body = await flow.export_csv.execute(
            tenant_id=world.tenant.id, statement_id=statement_id
        )
        # The fake exporter renders `header` as the first line — assert it carries the
        # canonical six column names, which is the contract the real `csv.writer`
        # implementation also produces (R6.1).
        first_line = body.split(b"\n", 1)[0].decode()
        assert first_line == "date,category,description,amount,currency,receipt_storage_key"

    async def test_pdf_returns_the_payload(self, flow: Flow, world: World) -> None:
        await _seed_reservation(flow, world)
        await flow.generate.execute(
            tenant_id=world.tenant.id,
            now=NOW,
            property_id=world.property.id,
            actor=actor_of(world),
            period_end=PERIOD_END,
        )
        statements, _ = await flow.list_statements.execute(
            tenant_id=world.tenant.id,
            filters=OwnerStatementFilters(property_id=world.property.id),
            page=1,
        )
        _statement, body = await flow.export_pdf.execute(
            tenant_id=world.tenant.id, statement_id=statements[0].id
        )
        # The fake generator emits `%PDF-fake`; the real one starts with the same four
        # bytes (R6.3 — `bytes[:4] == b"%PDF"`). What the test pins here is the seam
        # the use case has to expose: bytes leave the application layer, not the
        # rendered structure the old signature returned.
        assert body == b"%PDF-fake"


# ---- helpers --------------------------------------------------------------------


async def _seed_reservation(flow: Flow, world: World) -> ReservationModel:
    """A single EUR reservation that overlaps the period, plus two EUR expenses."""
    flow.session.add(
        ReservationModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            channel="DIRECT",
            status="CONFIRMED",
            check_in_date=date(2026, 7, 5),
            check_out_date=date(2026, 7, 10),
            nights=5,
            gross_amount=Decimal("300.00"),
            ota_commission=Decimal("30.00"),
            net_amount=Decimal("270.00"),
            currency="EUR",
        )
    )
    flow.session.add(
        ExpenseModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            category=ExpenseCategory.CLEANING,
            description="Turnover",
            amount=Decimal("50.00"),
            date=date(2026, 7, 12),
            currency="EUR",
        )
    )
    await flow.session.flush()
    return None
