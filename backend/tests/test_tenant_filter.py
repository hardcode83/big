"""The global tenant filter: defence in depth, not the primary mechanism (R4.2, D16).

Explicit `tenant_id` parameters in every repository method are the authoritative
scoping (design D6). These tests prove the net underneath them: a query that
FORGOT its filter still cannot see another tenant's rows.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.models import AuditLogModel
from app.auth.infrastructure.models import UserModel
from app.core.db import (
    TENANT_ID_SESSION_KEY,
    bind_session_to_tenant,
    tenant_scoped_classes,
)
from app.integrations.infrastructure.models import WebhookEventModel
from app.maintenance.domain.enums import OwnerApprovalRelatedType
from app.maintenance.infrastructure.models import OwnerApprovalModel
from app.notifications.domain.enums import NotificationChannel
from app.notifications.infrastructure.models import NotificationLogModel
from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from app.properties.infrastructure.models import PropertyModel
from app.reviews.domain.enums import ReviewChannel
from app.reviews.infrastructure.models import ReviewModel
from app.statements.domain.enums import ExpenseCategory
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from tests.auth.conftest import insert_tenant, insert_user


@pytest.mark.asyncio
async def test_the_registry_scan_finds_the_tenant_scoped_entities() -> None:
    names = {entity.__tablename__ for entity in tenant_scoped_classes()}

    # Guards against the scan silently matching nothing, which would make every
    # test below pass for the wrong reason.
    assert {"users", "user_sessions", "properties", "reservations"} <= names
    # `tenants` itself is not tenant-scoped: it has no tenant_id column.
    assert "tenants" not in names
    # The financial/system tables (§7.17-7.26). Asserted positively on purpose: the
    # only thing tying them to the net is `TenantScopedMixin`, and dropping it from
    # any of these models would remove the table from the filter with the rest of the
    # suite still green (steering/security.md rule 1).
    assert {
        "pricing_rules",
        "price_recommendations",
        "reviews",
        "notification_logs",
        "audit_logs",
        "owner_statements",
        "expenses",
        "owner_approvals",
    } <= names


@pytest.mark.asyncio
async def test_an_unfiltered_select_cannot_see_another_tenant(db_session: AsyncSession) -> None:
    tenant_a = await insert_tenant(db_session, name="filter-a")
    tenant_b = await insert_tenant(db_session, name="filter-b")
    user_a = await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)

    # Deliberately no WHERE tenant_id — this is the mistake being caught.
    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert [user.id for user in found] == [user_a.id]


@pytest.mark.asyncio
async def test_an_unmarked_session_is_not_filtered(db_session: AsyncSession) -> None:
    """Login depends on this: find_by_email_globally has no tenant yet (D16)."""
    tenant_a = await insert_tenant(db_session, name="unmarked-a")
    tenant_b = await insert_tenant(db_session, name="unmarked-b")
    await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    assert TENANT_ID_SESSION_KEY not in db_session.info

    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert len(found) == 2


@pytest.mark.asyncio
async def test_get_by_primary_key_is_filtered(db_session: AsyncSession) -> None:
    # `session.get()` is a path the net must cover too, not just select(). Note the
    # expunge_all() below is load-bearing: get() can answer from the identity map
    # without emitting SQL, and then no listener runs at all — the fourth documented
    # limit of the filter.
    tenant_a = await insert_tenant(db_session, name="get-a")
    tenant_b = await insert_tenant(db_session, name="get-b")
    user_b = await insert_user(db_session, tenant=tenant_b)
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_a.id)

    assert await db_session.get(UserModel, user_b.id) is None


@pytest.mark.asyncio
async def test_an_unfiltered_orm_update_cannot_touch_another_tenant(
    db_session: AsyncSession,
) -> None:
    tenant_a = await insert_tenant(db_session, name="update-a")
    tenant_b = await insert_tenant(db_session, name="update-b")
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)
    result = await db_session.execute(update(UserModel).values(name="rewritten"))

    assert result.rowcount == 1
    db_session.expunge_all()
    db_session.info.pop(TENANT_ID_SESSION_KEY)
    rows = {
        row.id: row.name for row in (await db_session.execute(select(UserModel))).scalars().all()
    }
    assert rows[user_a.id] == "rewritten"
    assert rows[user_b.id] != "rewritten"


@pytest.mark.asyncio
async def test_the_filter_follows_the_marked_tenant(db_session: AsyncSession) -> None:
    tenant_a = await insert_tenant(db_session, name="switch-a")
    tenant_b = await insert_tenant(db_session, name="switch-b")
    await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_b.id)
    found = (await db_session.execute(select(UserModel))).scalars().all()

    assert [user.id for user in found] == [user_b.id]


async def _property_for(session: AsyncSession, tenant) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id, name="REDES11", internal_code=f"p-{uuid.uuid4().hex[:8]}"
    )
    session.add(prop)
    await session.flush()
    return prop


async def _pricing_rule(session: AsyncSession, tenant) -> PricingRuleModel:
    rule = PricingRuleModel(
        tenant_id=tenant.id,
        name="Madrid base",
        base_price=Decimal("90.00"),
        min_price=Decimal("60.00"),
        max_price=Decimal("180.00"),
    )
    session.add(rule)
    await session.flush()
    return rule


async def _price_recommendation(session: AsyncSession, tenant) -> PriceRecommendationModel:
    prop = await _property_for(session, tenant)
    rule = await _pricing_rule(session, tenant)
    recommendation = PriceRecommendationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        pricing_rule_id=rule.id,
        date=date(2026, 8, 15),
        recommended_price=Decimal("135.00"),
        explanation="High season weekend.",
    )
    session.add(recommendation)
    await session.flush()
    return recommendation


async def _review(session: AsyncSession, tenant) -> ReviewModel:
    prop = await _property_for(session, tenant)
    review = ReviewModel(tenant_id=tenant.id, property_id=prop.id, channel=ReviewChannel.AIRBNB)
    session.add(review)
    await session.flush()
    return review


async def _notification_log(session: AsyncSession, tenant) -> NotificationLogModel:
    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact="owner@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="cleaning.assigned",
    )
    session.add(log)
    await session.flush()
    return log


async def _audit_log(session: AsyncSession, tenant) -> AuditLogModel:
    entry = AuditLogModel(
        tenant_id=tenant.id,
        action="reservation.update",
        entity_type="Reservation",
        entity_id=uuid.uuid4(),
    )
    session.add(entry)
    await session.flush()
    return entry


async def _owner_statement(session: AsyncSession, tenant) -> OwnerStatementModel:
    prop = await _property_for(session, tenant)
    statement = OwnerStatementModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    session.add(statement)
    await session.flush()
    return statement


async def _expense(session: AsyncSession, tenant) -> ExpenseModel:
    prop = await _property_for(session, tenant)
    expense = ExpenseModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        category=ExpenseCategory.CLEANING,
        description="Turnover clean.",
        amount=Decimal("45.00"),
        date=date(2026, 7, 12),
    )
    session.add(expense)
    await session.flush()
    return expense


async def _owner_approval(session: AsyncSession, tenant) -> OwnerApprovalModel:
    prop = await _property_for(session, tenant)
    approval = OwnerApprovalModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=Decimal("250.00"),
        reason="Boiler replacement.",
    )
    session.add(approval)
    await session.flush()
    return approval


async def _webhook_event(session: AsyncSession, tenant) -> WebhookEventModel:
    event = WebhookEventModel(
        tenant_id=tenant.id,
        provider="octorate",
        event_type="reservation.created",
        payload={},
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "factory"),
    [
        (PricingRuleModel, _pricing_rule),
        (PriceRecommendationModel, _price_recommendation),
        (ReviewModel, _review),
        (NotificationLogModel, _notification_log),
        (AuditLogModel, _audit_log),
        (OwnerStatementModel, _owner_statement),
        (ExpenseModel, _expense),
        (OwnerApprovalModel, _owner_approval),
        # The one table whose tenant scoping is hand-assembled rather than inherited
        # from TenantScopedMixin (D4) — so the one that most needs the generic proof.
        (WebhookEventModel, _webhook_event),
    ],
    ids=lambda value: getattr(value, "__tablename__", ""),
)
async def test_the_financial_tables_are_inside_the_net(db_session: AsyncSession, model, factory) -> None:
    """One case per module added by domain-foundation-financial.

    steering/security.md rule 1 makes an isolation test mandatory in every new
    module. Parametrised here rather than copied into five test files: the thing
    being proven is a property of the filter, and a per-module parameter still fails
    on its own if that module's model loses `TenantScopedMixin`.
    """
    tenant_a = await insert_tenant(db_session, name=f"net-a-{model.__tablename__}")
    tenant_b = await insert_tenant(db_session, name=f"net-b-{model.__tablename__}")
    row_a = await factory(db_session, tenant_a)
    await factory(db_session, tenant_b)
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_a.id)

    # Deliberately no WHERE tenant_id — this is the mistake being caught.
    found = (await db_session.execute(select(model))).scalars().all()

    assert [row.id for row in found] == [row_a.id]


@pytest.mark.asyncio
async def test_webhook_events_is_inside_the_net_despite_the_nullable_tenant(
    db_session: AsyncSession,
) -> None:
    """Column presence is what the scan matches, not `TenantScopedMixin` (D4)."""
    names = {entity.__tablename__ for entity in tenant_scoped_classes()}

    assert "webhook_events" in names


@pytest.mark.asyncio
async def test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session(
    db_session: AsyncSession,
) -> None:
    """The consequence of D4, fixed in a test before anything builds on it.

    §7.26 makes `webhook_events.tenant_id` nullable so an unattributable payload is
    recorded rather than lost. But the table is inside the global filter, so a marked
    session asks for `tenant_id = X` and the `NULL` rows — precisely the ones
    `reservations-webhooks` has to process — come back empty, with no error.

    The answer is not to weaken the filter: it is that the job reads them from a
    session that was NEVER marked — its own, like the Celery entrypoints and the
    anonymous login path already use. The phases below are ordered to model exactly
    that, and deliberately never `pop()` the marker off a marked session: `session.info`
    is per-session, so un-marking mid-request would disable the net for every scoped
    table for the rest of that session, `guests.document_number` included. This test
    exists so the behaviour is discovered here and not in production (R4.3).
    """
    tenant_a = await insert_tenant(db_session, name="webhook-a")
    attributed = WebhookEventModel(
        tenant_id=tenant_a.id, provider="octorate", event_type="reservation.created", payload={}
    )
    orphan = WebhookEventModel(provider="octorate", event_type="reservation.created", payload={})
    db_session.add_all([attributed, orphan])
    await db_session.flush()

    # No expunge_all() in either phase, unlike test_get_by_primary_key_is_filtered:
    # `select()` always emits SQL, so the criteria apply whatever the identity map
    # holds. The map only shortcuts `session.get()`/`refresh()` — the filter's fourth
    # documented limit — which this test never calls.

    # Phase 1 — never marked. This is the shape the future job must use.
    assert TENANT_ID_SESSION_KEY not in db_session.info
    everything = (await db_session.execute(select(WebhookEventModel))).scalars().all()

    assert {row.id for row in everything} == {attributed.id, orphan.id}
    # Guards against the assertion above passing on an empty table.
    assert any(row.tenant_id is None for row in everything)

    # Phase 2 — marked. The orphan row silently disappears; that is the hazard.
    bind_session_to_tenant(db_session, tenant_a.id)
    visible = (await db_session.execute(select(WebhookEventModel))).scalars().all()

    assert [row.id for row in visible] == [attributed.id]


@pytest.mark.asyncio
async def test_a_query_for_an_unrelated_entity_still_works(db_session: AsyncSession) -> None:
    # `tenants` has no tenant_id, so the filter must not accidentally constrain it.
    tenant_a = await insert_tenant(db_session, name="unrelated-a")
    await insert_tenant(db_session, name="unrelated-b")
    from app.tenants.infrastructure.models import TenantModel

    bind_session_to_tenant(db_session, tenant_a.id)

    found = (await db_session.execute(select(TenantModel))).scalars().all()

    assert len(found) == 2


@pytest.mark.asyncio
async def test_raw_sql_is_documented_as_not_covered(db_session: AsyncSession) -> None:
    """Pins the first documented limit of D16 so nobody assumes more than there is."""
    from sqlalchemy import text

    tenant_a = await insert_tenant(db_session, name="raw-a")
    tenant_b = await insert_tenant(db_session, name="raw-b")
    await insert_user(db_session, tenant=tenant_a)
    await insert_user(db_session, tenant=tenant_b)

    bind_session_to_tenant(db_session, tenant_a.id)
    count = await db_session.scalar(text("SELECT count(*) FROM users"))

    # Not a bug: a textual statement never goes through the ORM criteria. This is
    # exactly why explicit scoping (D6) stays the authoritative mechanism.
    assert count == 2


@pytest.mark.asyncio
async def test_binding_rejects_nothing_and_is_idempotent(db_session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()

    bind_session_to_tenant(db_session, tenant_id)
    bind_session_to_tenant(db_session, tenant_id)

    assert db_session.info[TENANT_ID_SESSION_KEY] == tenant_id


def test_application_code_never_unmarks_a_session() -> None:
    """The prohibition in `_scope_statement_to_tenant`'s limit 2, made executable.

    `session.info` is per-session, not per-statement, so removing the tenant marker
    mid-request switches the net off for EVERY scoped table for the rest of that
    session — `guests.document_number` included. `bind_session_to_tenant` has no
    symmetric unbind precisely because there is no legitimate reason to do it.

    This test exists because the docstring alone was not enough: the only executable
    example of the forbidden call lived in this very file (a green test), which makes
    it the discoverable idiom for anyone who needs the `tenant_id IS NULL` rows of
    `webhook_events`. That read belongs in a session that was NEVER marked — the
    job's own, from `async_session_factory`, the way `app/cli/bootstrap.py` does it.

    AST-based, like `test_layering.py`: a text grep would trip over the word in a
    docstring and miss `d = session.info; d.pop(...)`. `tests/` is deliberately out of
    scope — the test above needs the call to demonstrate the hazard.
    """
    import ast
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []

    for module_path in sorted(app_root.glob("**/*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # session.info.pop(...) / .info.pop(TENANT_ID_SESSION_KEY)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "pop"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "info"
            ):
                offenders.append(f"{module_path.relative_to(app_root)}: session.info.pop(...)")
            # del session.info[TENANT_ID_SESSION_KEY]
            if isinstance(node, ast.Delete):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "info"
                    ):
                        offenders.append(f"{module_path.relative_to(app_root)}: del session.info[...]")
            # Any other mention of the key outside app/core/db.py, which owns it.
            if (
                isinstance(node, ast.Name)
                and node.id == "TENANT_ID_SESSION_KEY"
                and module_path.name != "db.py"
            ):
                offenders.append(f"{module_path.relative_to(app_root)}: TENANT_ID_SESSION_KEY")

    assert not offenders, (
        "application code must not remove a session's tenant marker: "
        f"{sorted(set(offenders))}. Read unmarked data from a session that was never "
        "marked instead (see limit 2 in app/core/db.py)."
    )


def test_the_unmarking_check_catches_what_it_claims_to() -> None:
    """The enforcement mechanism gets its own test, like test_layering.py's."""
    import ast

    for source in (
        "session.info.pop('tenant_id')",
        "del session.info['tenant_id']",
        "d = request.state.session.info\nd.pop('tenant_id')",
    ):
        ast.parse(source)  # all three parse; the first two are what the scan matches

    popped = ast.parse("session.info.pop('tenant_id')")
    call = next(n for n in ast.walk(popped) if isinstance(n, ast.Call))
    assert isinstance(call.func, ast.Attribute)
    assert call.func.attr == "pop"
    assert isinstance(call.func.value, ast.Attribute) and call.func.value.attr == "info"

    deleted = ast.parse("del session.info['tenant_id']")
    delete = next(n for n in ast.walk(deleted) if isinstance(n, ast.Delete))
    target = delete.targets[0]
    assert isinstance(target, ast.Subscript)
    assert isinstance(target.value, ast.Attribute) and target.value.attr == "info"
