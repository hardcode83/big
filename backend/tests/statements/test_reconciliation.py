"""Integration tests for `ReconcileOwnerApprovalsForExpensesUseCase` (D4).

The reconciliation's invariants are not its own arithmetic but its idempotency and the
boundary between **doing nothing silently** (the second-pass case) and **doing something
silently** (the `REJECTED`-on-consolidated case, which must report and never touch).
A fake repository cannot show either, so these run against the real DB.

Cross-tenant tests at the bottom cover regla 1 of `steering/security.md` — the
pending JOIN and the materialise UPDATE/DELETE refuse to touch another tenant's
rows.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio

from app.maintenance.domain.enums import OwnerApprovalRelatedType, OwnerApprovalStatus
from app.maintenance.infrastructure.models import OwnerApprovalModel
from app.properties.domain.enums import PropertyStatus
from app.properties.infrastructure.models import PropertyModel
from app.statements.application.reconciliation import (
    ReconcileOwnerApprovalsForExpensesUseCase,
)
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.statements.infrastructure.reconciliation import (
    SqlAlchemyReconciliationStore,
)
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)

pytestmark = pytest.mark.asyncio


class World:
    def __init__(self, tenant, prop, owner) -> None:
        self.tenant = tenant
        self.property = prop
        self.owner = owner


@pytest_asyncio.fixture
async def world(db_session) -> World:
    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(TenantConfigModel(tenant_id=tenant.id))
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Redes 11",
        internal_code="REDES11",
        status=PropertyStatus.ACTIVE,
    )
    db_session.add(prop)
    await db_session.flush()
    from app.auth.infrastructure.models import UserModel
    from app.auth.domain.enums import UserRole

    owner = UserModel(
        tenant_id=tenant.id,
        name="Owner",
        email="owner@example.com",
        password_hash="hash",
        role=UserRole.TENANT_OWNER,
    )
    db_session.add(owner)
    await db_session.flush()
    return World(tenant, prop, owner)


def _make_expense(world: World, *, statement_id=None) -> ExpenseModel:
    return ExpenseModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        category=ExpenseCategory.MAINTENANCE,
        description="Boiler part",
        amount="150.00",
        date=date(2026, 7, 12),
        currency="EUR",
        statement_id=statement_id,
    )


def _make_approval(
    world: World,
    *,
    expense_id: uuid.UUID,
    status: OwnerApprovalStatus,
    responded_by: uuid.UUID | None = None,
    responded_at: datetime | None = None,
) -> OwnerApprovalModel:
    return OwnerApprovalModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        related_type=OwnerApprovalRelatedType.OTHER.value,
        related_id=expense_id,
        amount="150.00",
        reason=f"Expense #{expense_id} above the tenant threshold.",
        status=status.value,
        responded_by=responded_by,
        responded_at=responded_at,
    )


def _run(session) -> ReconcileOwnerApprovalsForExpensesUseCase:
    """Wire the use case against the in-test session.

    The store commits through the session the test owns; no separate `commit()` is
    taken by the use case itself, because the use case delegates the transactional
    boundary to whatever it is handed. The wiring here passes a no-op commit so the
    test controls flushes explicitly.
    """

    async def _commit() -> None:
        await session.commit()

    return ReconcileOwnerApprovalsForExpensesUseCase(
        store=SqlAlchemyReconciliationStore(session),
        commit=_commit,
    )


# ---- APPROVED ------------------------------------------------------------------


class TestReconcileApproved:
    async def test_approved_materialises_approved_by(self, world: World, db_session) -> None:
        expense = _make_expense(world)
        db_session.add(expense)
        await db_session.flush()
        approval = _make_approval(
            world,
            expense_id=expense.id,
            status=OwnerApprovalStatus.APPROVED,
            responded_by=world.owner.id,
            responded_at=NOW,
        )
        db_session.add(approval)
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        assert report.materialised_approved == 1
        await db_session.refresh(expense)
        assert expense.approved_by == world.owner.id
        assert expense.statement_id is None

    async def test_approved_does_not_touch_consolidated(
        self, world: World, db_session
    ) -> None:
        # Already consolidated (statement_id set, approved_by NULL) — the guard
        # `statement_id IS NULL` keeps the UPDATE a no-op.
        consolidated_statement_id = uuid.uuid4()
        db_session.add(
            OwnerStatementModel(
                id=consolidated_statement_id,
                tenant_id=world.tenant.id,
                property_id=world.property.id,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                status=OwnerStatementStatus.DRAFT,
            )
        )
        await db_session.flush()
        expense = _make_expense(world, statement_id=consolidated_statement_id)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=OwnerApprovalStatus.APPROVED,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        assert report.materialised_approved == 0
        await db_session.refresh(expense)
        assert expense.approved_by is None  # untouched
        assert expense.statement_id == consolidated_statement_id


# ---- REJECTED -------------------------------------------------------------------


class TestReconcileRejected:
    async def test_rejected_deletes_unconsolidated(self, world: World, db_session) -> None:
        expense = _make_expense(world)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=OwnerApprovalStatus.REJECTED,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        assert report.materialised_rejected == 1
        # The expense row is gone.
        from sqlalchemy import select

        rows = await db_session.execute(
            select(ExpenseModel).where(ExpenseModel.id == expense.id)
        )
        assert rows.scalar_one_or_none() is None

    async def test_rejected_against_consolidated_is_reported_not_deleted(
        self, world: World, db_session
    ) -> None:
        # REJECTED + consolidated → anomaly. The design forbids touching the row and
        # forbids interpreting it as approved; it must surface in `failed_reconciliation`.
        consolidated_statement_id = uuid.uuid4()
        statement = OwnerStatementModel(
            id=consolidated_statement_id,
            tenant_id=world.tenant.id,
            property_id=world.property.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            status=OwnerStatementStatus.SENT,
        )
        db_session.add(statement)
        await db_session.commit()
        expense = _make_expense(world, statement_id=consolidated_statement_id)
        db_session.add(expense)
        await db_session.commit()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=OwnerApprovalStatus.REJECTED,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        assert report.materialised_rejected == 0
        assert len(report.failed_reconciliation) == 1
        inconsistency = report.failed_reconciliation[0]
        assert inconsistency.approval_id is not None
        assert inconsistency.expense_id == expense.id
        assert inconsistency.property_id == world.property.id
        assert inconsistency.period_start == PERIOD_START.isoformat()
        assert inconsistency.period_end == PERIOD_END.isoformat()

        # The expense row is intact.
        from sqlalchemy import select

        rows = await db_session.execute(
            select(ExpenseModel).where(ExpenseModel.id == expense.id)
        )
        assert rows.scalar_one_or_none() is not None


# ---- Idempotency -----------------------------------------------------------------


class TestReconcileIdempotency:
    async def test_two_passes_apply_only_once(
        self, world: World, db_session
    ) -> None:
        expense = _make_expense(world)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=OwnerApprovalStatus.APPROVED,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        uc = _run(db_session)
        first = await uc.execute(now=NOW)
        second = await uc.execute(now=NOW)

        assert first.materialised_approved == 1
        assert second.materialised_approved == 0  # second pass: guard fails, no-op
        await db_session.refresh(expense)
        assert expense.approved_by == world.owner.id


# ---- PENDING is untouched -------------------------------------------------------


class TestReconcilePending:
    async def test_pending_approval_is_left_alone(
        self, world: World, db_session
    ) -> None:
        # An approval that nobody has answered yet — the reconciliation must not
        # touch it; the pending query filters `responded_at IS NOT NULL`.
        expense = _make_expense(world)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            OwnerApprovalModel(
                id=uuid.uuid4(),
                tenant_id=world.tenant.id,
                property_id=world.property.id,
                related_type=OwnerApprovalRelatedType.OTHER.value,
                related_id=expense.id,
                amount="150.00",
                reason=f"Expense #{expense.id} above the tenant threshold.",
                status=OwnerApprovalStatus.PENDING.value,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        assert report.total == 0
        await db_session.refresh(expense)
        assert expense.approved_by is None


# ---- Cross-tenant isolation (regla 1) ------------------------------------------


class TestReconcileCrossTenant:
    """Regla 1: the pending JOIN's `e.tenant_id = oa.tenant_id` clause must block the
    same-id cross-tenant race. The reconciliation is a **global** worker (it processes
    every tenant's approvals in one tick), so the cross-tenant safety we verify is the
    structural one: an approval from tenant A pointing at an expense id that exists
    in tenant B must not apply the answer to B's row.
    """

    async def test_approval_from_tenant_a_does_not_apply_to_tenant_b_expense(
        self, world: World, db_session
    ) -> None:
        # TenantA's approval intentionally points at the SAME id as a TenantB expense.
        # The JOIN's `e.tenant_id = oa.tenant_id` must block it from matching.
        other_tenant = TenantModel(name="TenantB", billing_email="b@example.com")
        db_session.add(other_tenant)
        await db_session.flush()
        db_session.add(TenantConfigModel(tenant_id=other_tenant.id))
        await db_session.flush()
        other_prop = PropertyModel(
            tenant_id=other_tenant.id,
            name="Other",
            internal_code="OTHER-1",
            status=PropertyStatus.ACTIVE,
        )
        db_session.add(other_prop)
        await db_session.flush()
        # Hand-pick the id so TenantA's approval can target it.
        shared_id = uuid.uuid4()
        expense_b = ExpenseModel(
            id=shared_id,
            tenant_id=other_tenant.id,
            property_id=other_prop.id,
            category=ExpenseCategory.MAINTENANCE,
            description="Other tenant's expense",
            amount="200.00",
            date=date(2026, 7, 12),
            currency="EUR",
        )
        db_session.add(expense_b)
        await db_session.flush()
        # TenantA approval, pointing at TenantB's id.
        db_session.add(
            OwnerApprovalModel(
                id=uuid.uuid4(),
                tenant_id=world.tenant.id,
                property_id=world.property.id,
                related_type=OwnerApprovalRelatedType.OTHER.value,
                related_id=shared_id,  # <- cross-tenant!
                amount="200.00",
                reason=f"Cross-tenant attempt #{shared_id}.",
                status=OwnerApprovalStatus.APPROVED.value,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        # The JOIN refused to match: the report has no approvals materialised
        # (the work query returned no rows), and the cross-tenant expense is intact.
        assert report.materialised_approved == 0
        assert report.materialised_rejected == 0
        await db_session.refresh(expense_b)
        assert expense_b.approved_by is None


# ---- D4 matrix, parametrized (task 5.4) --------------------------------------------


#: The five scenarios the design D4 enumerates, expressed as a single tuple
#: `(approval_status, expense_consolidated, expected_materialise, expected_failed)`.
#: `expected_materialise` is the count the report must surface; `expected_failed` is
#: whether the row appears in `failed_reconciliation`. The matrix covers the four
#: approval-state x expense-state combinations plus the idempotency pass (a second
#: execution on the same world has to apply zero changes).
@dataclass(frozen=True)
class _Scenario:
    label: str
    approval_status: OwnerApprovalStatus
    expense_consolidated: bool
    expected_materialised: int
    expected_failed: bool


_D4_MATRIX: list[_Scenario] = [
    _Scenario(
        "APPROVED + pending",
        OwnerApprovalStatus.APPROVED,
        expense_consolidated=False,
        expected_materialised=1,
        expected_failed=False,
    ),
    _Scenario(
        "APPROVED + consolidated",
        OwnerApprovalStatus.APPROVED,
        expense_consolidated=True,
        expected_materialised=0,
        expected_failed=False,
    ),
    _Scenario(
        "REJECTED + pending",
        OwnerApprovalStatus.REJECTED,
        expense_consolidated=False,
        expected_materialised=1,
        expected_failed=False,
    ),
    _Scenario(
        "REJECTED + consolidated",
        OwnerApprovalStatus.REJECTED,
        expense_consolidated=True,
        expected_materialised=0,
        expected_failed=True,
    ),
]


class TestReconcileD4Matrix:
    """The D4 matrix, walked end-to-end (`tasks.md` §5.4).

    Each row of `_D4_MATRIX` builds the matching world, runs the use case once, and asserts
    on `report.materialised_*` and the presence of the row in `failed_reconciliation`.
    The assertions are deliberately minimal so the table reads as a contract, not as a
    copy of the individual tests above; those tests are the canonical fixtures, this is
    the canonical matrix.
    """

    @pytest.mark.parametrize(
        "scenario",
        _D4_MATRIX,
        ids=[s.label for s in _D4_MATRIX],
    )
    async def test_matrix(
        self, scenario: _Scenario, world: World, db_session
    ) -> None:
        statement_id: uuid.UUID | None = (
            uuid.uuid4() if scenario.expense_consolidated else None
        )
        if statement_id is not None:
            db_session.add(
                OwnerStatementModel(
                    id=statement_id,
                    tenant_id=world.tenant.id,
                    property_id=world.property.id,
                    period_start=PERIOD_START,
                    period_end=PERIOD_END,
                    status=OwnerStatementStatus.DRAFT,
                )
            )
            await db_session.flush()
        expense = _make_expense(world, statement_id=statement_id)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=scenario.approval_status,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        report = await _run(db_session).execute(now=NOW)

        if scenario.approval_status is OwnerApprovalStatus.APPROVED:
            assert report.materialised_approved == scenario.expected_materialised
            assert report.materialised_rejected == 0
        else:
            assert report.materialised_rejected == scenario.expected_materialised
            assert report.materialised_approved == 0
        failed_for_this_expense = [
            row for row in report.failed_reconciliation if row.expense_id == expense.id
        ]
        assert bool(failed_for_this_expense) is scenario.expected_failed

    async def test_idempotency_two_passes(self, world: World, db_session) -> None:
        """`tasks.md` §5.4 — two consecutive sweeps apply changes only once.

        One APPROVED + pending world, two consecutive executions: the first applies, the
        second is a no-op by virtue of the SQL guard. The expense row's `approved_by` is
        set once, not twice, and the second report carries zero materialisations.
        """
        expense = _make_expense(world)
        db_session.add(expense)
        await db_session.flush()
        db_session.add(
            _make_approval(
                world,
                expense_id=expense.id,
                status=OwnerApprovalStatus.APPROVED,
                responded_by=world.owner.id,
                responded_at=NOW,
            )
        )
        await db_session.flush()

        uc = _run(db_session)
        first = await uc.execute(now=NOW)
        second = await uc.execute(now=NOW)

        assert first.materialised_approved == 1
        assert second.materialised_approved == 0
        assert second.materialised_rejected == 0
        assert second.failed_reconciliation == []
        await db_session.refresh(expense)
        assert expense.approved_by == world.owner.id
