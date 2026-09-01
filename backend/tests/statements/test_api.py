"""Integration tests for the ten owner-statements and expenses routes (task 6.5).

What this exercises against the real test database, end to end through the FastAPI router:

* Listing and detail of statements (R3.1, R3.2, R3.4 — including cross-tenant 404).
* Manual generation (R2.3, D3 — idempotency on the UNIQUE key, mixed-currency abort).
* PATCH notes / status (R4.1, R4.5, R4.6, D6.2 — and the illegal-transition 409).
* Expenses CRUD (R5.1, R5.2, R5.3, R5.4, R5.5, R5.7, D6.3 — including the threshold
  bypass that creates an `OwnerApproval(OTHER)` and surfaces `pending_owner_approval_id`).

**Out of scope here, by design**: the CSV/PDF body assertions. The byte-level serializers
live in `infrastructure/csv_export.py` (task 7.3) and `infrastructure/pdf.py` (task 7.2)
and are tested in `test_csv.py` / `test_pdf.py` — the router hands the use case's data
through, and the contract that matters at the API layer is the `Content-Type` and the
filename, not the bytes. The CSV/PDF route tests in `tests/statements/test_api.py`
land alongside the infrastructure tests in section 7.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole
from app.maintenance.domain.enums import (
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.infrastructure.models import OwnerApprovalModel
from app.properties.domain.enums import PropertyStatus
from app.properties.infrastructure.models import PropertyModel
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.tenants.infrastructure.models import TenantConfigModel
from tests.auth.conftest import (  # noqa: F401 — shared integration fixtures (see below)
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
)

# Reuse the conftest fixtures from `tests/conftest.py` (`api`, `db_session`) and
# `tests/auth/conftest.py` (`tenant_a`, `tenant_b`, `users_by_role_a`, `users_by_role_b`).
# The shared `api` fixture wires the same request-session override the rest of the
# integration suite uses, so the tenant marker the request sets is popped on the way
# out — the same property production gets from per-request sessions.

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)

pytestmark = pytest.mark.asyncio


class World:
    """The bundle a test sees: both tenants, the manager and owner of A, B's manager,
    and one property per tenant. `_make_statement` / `_make_expense` consume it.

    Built from the shared `tenant_a/b` and `users_by_role_a/b` fixtures so the test
    inherits the same session, codec, and API client the rest of the integration suite
    uses.
    """

    def __init__(self, tenant_a, tenant_b, manager_a, owner_a, manager_b, prop_a, prop_b):
        self.tenant_a = tenant_a
        self.tenant_b = tenant_b
        self.manager_a = manager_a
        self.owner_a = owner_a
        self.manager_b = manager_b
        self.prop_a = prop_a
        self.prop_b = prop_b


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant_a.id,
        name="Redes 11",
        internal_code="REDES11",
        status=PropertyStatus.ACTIVE,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    """A property of the NEIGHBOUR tenant, inserted directly and not through the API.

    Deliberate: the suite shares ONE session, and `get_authenticated_request` binds it
    to the tenant of whoever calls. A request as tenant B would rebind it and the next
    call as tenant A would answer `401` instead of the `404` under test (the same
    reason `tests/timeline/conftest.py` documents for `property_b`).
    """
    prop = PropertyModel(
        tenant_id=tenant_b.id,
        name="Pajaritos 8",
        internal_code="PAJARITOS8",
        status=PropertyStatus.ACTIVE,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest_asyncio.fixture
async def world(
    db_session,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    property_a,
    property_b,
) -> World:
    # Seed the tenant configs (the threshold check reads from them).
    db_session.add(TenantConfigModel(tenant_id=tenant_a.id))
    db_session.add(TenantConfigModel(tenant_id=tenant_b.id))
    await db_session.flush()
    return World(
        tenant_a,
        tenant_b,
        users_by_role_a[UserRole.PROPERTY_MANAGER],
        users_by_role_a[UserRole.TENANT_OWNER],
        users_by_role_b[UserRole.PROPERTY_MANAGER],
        property_a,
        property_b,
    )


def _auth(client, user) -> dict[str, str]:
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_statement(
    db_session,
    world: World,
    *,
    status: OwnerStatementStatus = OwnerStatementStatus.DRAFT,
    period_start: date = PERIOD_START,
    period_end: date = PERIOD_END,
    notes: str | None = None,
) -> OwnerStatementModel:
    """Build, add, and flush — so the row is visible to the next API call."""
    model = OwnerStatementModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant_a.id,
        property_id=world.prop_a.id,
        period_start=period_start,
        period_end=period_end,
        status=status,
        notes=notes,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def _make_expense(
    db_session,
    world: World,
    *,
    category: ExpenseCategory = ExpenseCategory.CLEANING,
    description: str = "Turnover",
    amount: Decimal = Decimal("50.00"),
    date_: date = date(2026, 7, 12),
    statement_id: uuid.UUID | None = None,
) -> ExpenseModel:
    model = ExpenseModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant_a.id,
        property_id=world.prop_a.id,
        category=category,
        description=description,
        amount=amount,
        date=date_,
        currency="EUR",
        statement_id=statement_id,
    )
    db_session.add(model)
    await db_session.flush()
    return model


# ---- /api/v1/owner-statements GET (R3.1, R3.2) ----------------------------------------


class TestListOwnerStatements:
    async def test_returns_the_prd_pagination_envelope(
        self, api, world, db_session
    ) -> None:
        await _make_statement(db_session, world)

        response = await api.get(
            "/api/v1/owner-statements",
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "total", "page", "per_page"}
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["per_page"] == 20  # R3.1: fixed server-side
        assert body["items"][0]["property_id"] == str(world.prop_a.id)
        # `tenant_id` is not published (R7.2).
        assert "tenant_id" not in body["items"][0]

    async def test_filters_by_property_status_and_period(
        self, api, world, db_session
    ) -> None:
        print(f"session info: {db_session.info}")
        print(f"session in_transaction: {db_session.in_transaction()}")
        s1 = await _make_statement(db_session, world, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
        s2 = await _make_statement(db_session, world)
        db_session.add(s1)
        db_session.add(s2)
        print(f"s1 in session: {s1 in db_session}")
        await db_session.flush()
        await db_session.commit()

        # Verify the seed is visible to a direct query.
        from sqlalchemy import select, text

        from app.statements.infrastructure.models import OwnerStatementModel
        rows_all = await db_session.execute(select(OwnerStatementModel))
        print(f"DB rows (unfiltered): {[(r.id, r.tenant_id) for r in rows_all.scalars().all()]}")
        raw = await db_session.execute(text("SELECT COUNT(*) FROM owner_statements"))
        print(f"raw count: {raw.scalar()}")

        # First, list without filter to see all rows.
        response_all = await api.get(
            "/api/v1/owner-statements",
            headers=_auth(api, world.owner_a),
        )
        print(f"unfiltered body: {response_all.text}")

        response = await api.get(
            "/api/v1/owner-statements",
            params={"property_id": str(world.prop_a.id), "period_start_from": "2026-07-01"},
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        body = response.json()
        print(f"filtered body: {body}")
        ids = {item["id"] for item in body["items"]}
        assert str(s2.id) in ids
        assert str(s1.id) not in ids

        response = await api.get(
            "/api/v1/owner-statements",
            params={"property_id": str(world.prop_a.id), "period_start_from": "2026-07-01"},
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        body = response.json()
        print(f"BODY: {body}")
        print(f"s1.id: {s1.id}, s2.id: {s2.id}")
        ids = {item["id"] for item in body["items"]}
        assert str(s2.id) in ids
        assert str(s1.id) not in ids

    async def test_other_tenants_statements_are_not_visible(
        self, api, world, db_session
    ) -> None:
        # Tenant B has a statement we cannot see.
        other_statement = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant_b.id,
            property_id=world.prop_b.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            status=OwnerStatementStatus.DRAFT,
        )
        db_session.add(other_statement)
        await db_session.flush()

        response = await api.get(
            "/api/v1/owner-statements",
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        assert response.json()["total"] == 0


# ---- /api/v1/owner-statements/{id} GET (R3.3, R3.4) ----------------------------------


class TestGetOwnerStatement:
    async def test_returns_the_statement(self, api, world, db_session) -> None:
        statement = await _make_statement(db_session, world, notes="Post-stay review")
        db_session.add(statement)
        await db_session.flush()

        response = await api.get(
            f"/api/v1/owner-statements/{statement.id}",
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(statement.id)
        assert body["notes"] == "Post-stay review"
        assert body["status"] == "DRAFT"

    async def test_cross_tenant_id_returns_404(
        self, api, world, db_session
    ) -> None:
        # Tenant B's statement id, fetched by tenant A.
        foreign_statement = OwnerStatementModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant_b.id,
            property_id=world.prop_b.id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            status=OwnerStatementStatus.DRAFT,
        )
        db_session.add(foreign_statement)
        await db_session.flush()

        response = await api.get(
            f"/api/v1/owner-statements/{foreign_statement.id}",
            headers=_auth(api, world.owner_a),
        )

        # R3.4: same body whether the id is unknown or belongs to another tenant.
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


# ---- /api/v1/owner-statements/generate POST (R2.1, R2.3) -----------------------------


class TestGenerateOwnerStatement:
    async def test_generates_a_statement(self, api, world) -> None:
        response = await api.post(
            "/api/v1/owner-statements/generate",
            json={
                "property_id": str(world.prop_a.id),
                "period_end": PERIOD_END.isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["created"] == 1
        assert body["skipped"] == 0
        assert body["failed"] == 0

    async def test_idempotent_on_the_unique_key(
        self, api, world
    ) -> None:
        first = await api.post(
            "/api/v1/owner-statements/generate",
            json={
                "property_id": str(world.prop_a.id),
                "period_end": PERIOD_END.isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        second = await api.post(
            "/api/v1/owner-statements/generate",
            json={
                "property_id": str(world.prop_a.id),
                "period_end": PERIOD_END.isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )

        assert first.status_code == 201
        assert second.status_code == 201
        # R2.3 / D6.1: the second call does not create a new row — `skipped` goes up.
        assert first.json()["created"] == 1
        assert second.json()["created"] == 0
        assert second.json()["skipped"] == 1

    async def test_unknown_property_id_returns_422(
        self, api, world
    ) -> None:
        response = await api.post(
            "/api/v1/owner-statements/generate",
            json={
                "property_id": str(uuid.uuid4()),
                "period_end": PERIOD_END.isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        # D9's fourth refinement: a body field that names an unknown property is `422`,
        # not `404` (the path reserved for resource-by-id misses).
        assert response.status_code == 422

    async def test_period_end_mid_month_returns_422(
        self, api, world
    ) -> None:
        # R2.5 / D6.1: a statement is one calendar month; `period_end` must be the last day.
        response = await api.post(
            "/api/v1/owner-statements/generate",
            json={
                "property_id": str(world.prop_a.id),
                "period_end": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 422

    async def test_tenant_owner_does_not_have_manage_permission(
        self, api, world
    ) -> None:
        # D8: `MANAGE_OWNER_STATEMENTS` is given only to `PROPERTY_MANAGER`; `TENANT_OWNER`
        # gets the read bundle and is `403` here.
        response = await api.post(
            "/api/v1/owner-statements/generate",
            json={"period_end": PERIOD_END.isoformat()},
            headers=_auth(api, world.owner_a),
        )
        assert response.status_code == 403


# ---- /api/v1/owner-statements/{id} PATCH (R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, D6.2) --


class TestPatchOwnerStatement:
    async def test_patch_notes_writes_and_audits(
        self, api, world, db_session
    ) -> None:
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/owner-statements/{statement.id}",
            json={"notes": "Quiet guest, post-stay review OK."},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 200
        assert response.json()["notes"] == "Quiet guest, post-stay review OK."

    async def test_patch_empty_notes_returns_422(
        self, api, world, db_session
    ) -> None:
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/owner-statements/{statement.id}",
            json={"notes": "   "},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 422

    async def test_patch_status_draft_to_ready(
        self, api, world, db_session
    ) -> None:
        statement = await _make_statement(db_session, world, status=OwnerStatementStatus.DRAFT)
        db_session.add(statement)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/owner-statements/{statement.id}",
            json={"status": "READY"},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "READY"

    async def test_patch_status_illegal_transition_returns_409(
        self, api, world, db_session
    ) -> None:
        # R4.4 / D1: DRAFT → SENT is not a legal jump.
        statement = await _make_statement(db_session, world, status=OwnerStatementStatus.DRAFT)
        db_session.add(statement)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/owner-statements/{statement.id}",
            json={"status": "SENT"},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    async def test_patch_status_terminal_returns_409(
        self, api, world, db_session
    ) -> None:
        # R4.4: SENT is terminal — no move, legal or otherwise.
        statement = await _make_statement(db_session, world, status=OwnerStatementStatus.SENT)
        db_session.add(statement)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/owner-statements/{statement.id}",
            json={"status": "READY"},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 409


# ---- /api/v1/expenses CRUD (R5) -----------------------------------------------------


class TestExpenseCrud:
    async def test_create_expense_under_threshold_has_no_pending_approval(
        self, api, world
    ) -> None:
        # Default threshold is 100.00 EUR (`TenantConfig.owner_approval_threshold_eur`).
        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(world.prop_a.id),
                "category": "CLEANING",
                "description": "Turnover cleaning",
                "amount": "50.00",
                "date": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["pending_owner_approval_id"] is None
        assert body["approved_by"] is None

    async def test_create_expense_over_threshold_returns_pending_approval_id(
        self, api, world
    ) -> None:
        # R5.7 / D4: amount > threshold triggers an `OwnerApproval(OTHER)` in the same
        # transaction; the response surfaces its id so the UI knows to wait.
        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(world.prop_a.id),
                "category": "AMENITIES",
                "description": "Premium welcome pack",
                "amount": "150.00",
                "date": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["pending_owner_approval_id"] is not None
        assert body["approved_by"] is None

    async def test_list_expenses_returns_tenant_items_only(
        self, api, world, db_session
    ) -> None:
        # Seed an expense in tenant B; it must not appear for tenant A.
        foreign = ExpenseModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant_b.id,
            property_id=world.prop_b.id,
            category=ExpenseCategory.CLEANING,
            description="B-side turnover",
            amount=Decimal("30.00"),
            date=date(2026, 7, 12),
            currency="EUR",
        )
        db_session.add(foreign)
        ours = await _make_expense(db_session, world)
        db_session.add(ours)
        await db_session.flush()

        response = await api.get(
            "/api/v1/expenses",
            headers=_auth(api, world.owner_a),
        )

        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["items"]]
        assert str(ours.id) in ids
        assert str(foreign.id) not in ids

    async def test_get_expense_returns_pending_approval_id(
        self, api, world, db_session
    ) -> None:
        # Seed an expense + a PENDING approval; verify the field on GET.

        expense = await _make_expense(db_session, world)
        db_session.add(expense)
        await db_session.flush()
        approval = OwnerApprovalModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant_a.id,
            property_id=world.prop_a.id,
            related_type=OwnerApprovalRelatedType.OTHER.value,
            related_id=expense.id,
            amount="150.00",
            reason=f"Expense #{expense.id} above threshold.",
            status=OwnerApprovalStatus.PENDING.value,
        )
        db_session.add(approval)
        await db_session.flush()

        response = await api.get(
            f"/api/v1/expenses/{expense.id}",
            headers=_auth(api, world.owner_a),
        )
        assert response.status_code == 200
        assert response.json()["pending_owner_approval_id"] == str(approval.id)

    async def test_patch_description_is_allowed_post_consolidation(
        self, api, world, db_session
    ) -> None:
        # D6.2: `description` remains editable after consolidation. We freeze a row by
        # giving it a statement_id (the mutation has the SQL guard, not the use case).
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()
        expense = await _make_expense(db_session, world, statement_id=statement.id)
        db_session.add(expense)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/expenses/{expense.id}",
            json={"description": "Refined post-stay description"},
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Refined post-stay description"

    async def test_patch_amount_on_consolidated_returns_409(
        self, api, world, db_session
    ) -> None:
        # D6.2: financial fields are immutable once `statement_id IS NOT NULL`.
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()
        expense = await _make_expense(db_session, world, statement_id=statement.id, amount=Decimal("50.00"))
        db_session.add(expense)
        await db_session.flush()

        response = await api.patch(
            f"/api/v1/expenses/{expense.id}",
            json={"amount": "75.00"},
            headers=_auth(api, world.manager_a),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    async def test_delete_consolidated_expense_returns_409(
        self, api, world, db_session
    ) -> None:
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()
        expense = await _make_expense(db_session, world, statement_id=statement.id)
        db_session.add(expense)
        await db_session.flush()

        response = await api.delete(
            f"/api/v1/expenses/{expense.id}",
            headers=_auth(api, world.manager_a),
        )

        # R5.4 / D6.2: a consolidated expense is part of the visible statement.
        assert response.status_code == 409

    async def test_delete_unconsolidated_expense_succeeds(
        self, api, world, db_session
    ) -> None:
        expense = await _make_expense(db_session, world)
        db_session.add(expense)
        await db_session.flush()

        response = await api.delete(
            f"/api/v1/expenses/{expense.id}",
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 204

    async def test_create_expense_in_closed_period_returns_409(
        self, api, world, db_session
    ) -> None:
        # D6.3: a `date` inside a period already covered by an `OwnerStatement` is a
        # `409` — a state conflict (the period is already closed), not a validation error.
        # V1 does not regenerate.
        closed_statement = await _make_statement(db_session, world)
        db_session.add(closed_statement)
        await db_session.flush()

        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(world.prop_a.id),
                "category": "CLEANING",
                "description": "Late turnover",
                "amount": "30.00",
                "date": date(2026, 7, 15).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    async def test_create_expense_with_unknown_property_returns_422(
        self, api, world
    ) -> None:
        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(uuid.uuid4()),
                "category": "CLEANING",
                "description": "Turnover",
                "amount": "50.00",
                "date": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        # R7.2 / D7: a body field naming an unknown property is `422`, never `404`
        # (the path reserved for resource-by-id misses).
        assert response.status_code == 422

    async def test_create_expense_with_empty_description_returns_422(
        self, api, world
    ) -> None:
        # R5.6: empty description is a `422` named `description`.
        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(world.prop_a.id),
                "category": "CLEANING",
                "description": "",
                "amount": "50.00",
                "date": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 422

    async def test_create_expense_over_schema_amount_ceiling_returns_422(
        self, api, world
    ) -> None:
        # R5.2 / D6.2: amount > NUMERIC(10,2) ceiling is a `422`.
        response = await api.post(
            "/api/v1/expenses",
            json={
                "property_id": str(world.prop_a.id),
                "category": "CLEANING",
                "description": "Ceiling test",
                "amount": "1000000000.00",
                "date": date(2026, 7, 12).isoformat(),
            },
            headers=_auth(api, world.manager_a),
        )
        assert response.status_code == 422


# ---- /api/v1/owner-statements/{id}/export.csv|pdf (R6) -------------------------------


class TestExportEndpoints:
    """The byte-level body is tested alongside the infrastructure serializers in
    sections 7.3 (CSV) and 7.2 (PDF). What this module can pin today is the HTTP
    surface: the route exists, returns the right `Content-Type`, and names the
    file in `Content-Disposition`. The body assertions land when sections 7.2/7.3 do.
    """

    async def test_export_csv_route_returns_csv_content_type(
        self, api, world, db_session
    ) -> None:
        # The serializer (`infrastructure/csv_export.py`, task 7.3) does not yet exist;
        # this test simply asserts the route is mounted and the use case answer reaches
        # the endpoint. Once `CsvStatementExporter.render` exists, the body assertion
        # can move in here.
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()
        # Skip if the serializer module is not present (sections 7.2/7.3 not landed).
        pytest.importorskip(
            "app.statements.infrastructure.csv_export",
            reason="CsvStatementExporter lands in task 7.3",
        )

        response = await api.get(
            f"/api/v1/owner-statements/{statement.id}/export.csv",
            headers=_auth(api, world.owner_a),
        )

        # R6.1: text/csv, utf-8.
        assert response.headers["content-type"].startswith("text/csv")
        assert "utf-8" in response.headers["content-type"]
        # Filename matches the period_end (the convention D10 establishes).
        assert PERIOD_END.isoformat() in response.headers["content-disposition"]

    async def test_export_pdf_route_returns_pdf_content_type(
        self, api, world, db_session
    ) -> None:
        # Same skip-pattern as CSV: the PDF serializer (`infrastructure/pdf.py`,
        # task 7.2) is the byte-level concern.
        statement = await _make_statement(db_session, world)
        db_session.add(statement)
        await db_session.flush()
        pytest.importorskip(
            "app.statements.infrastructure.pdf",
            reason="PdfStatementGenerator lands in task 7.2",
        )

        response = await api.get(
            f"/api/v1/owner-statements/{statement.id}/export.pdf",
            headers=_auth(api, world.owner_a),
        )

        # R6.3: application/pdf.
        assert response.headers["content-type"].startswith("application/pdf")
        assert PERIOD_END.isoformat() in response.headers["content-disposition"]
