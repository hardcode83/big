"""R2.5, design D2 — the partial unique index, and the drift it is exposed to.

The index predicate is SQL text and `LIVE_STATUSES` is a Python frozenset; neither can be
derived from the other, so the correspondence is pinned here. Without this, adding a status
to one and not the other silently re-opens the hole `AWAITING_CLEANING` fell into: a task
the resolver counts as pending that the index does not constrain, or the reverse.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cleaning.domain.entities import LIVE_STATUSES
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _index_predicate_statuses() -> frozenset[str]:
    """The status list written into the index predicate, parsed from the model."""
    index = next(
        ix
        for ix in CleaningTaskModel.__table__.indexes
        if ix.name == "uq_cleaning_tasks_live_reservation"
    )
    predicate = str(index.dialect_options["postgresql"]["where"])
    inside = predicate.split("IN", 1)[1]
    return frozenset(part.strip().strip("()'\" ") for part in inside.split(",") if part.strip())


def test_index_predicate_matches_live_statuses():
    assert _index_predicate_statuses() == {status.value for status in LIVE_STATUSES}


@pytest_asyncio.fixture
async def seeded(db_session):
    tenant = TenantModel(name="Adamar", billing_email="a@example.test")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(
        tenant_id=tenant.id, name="Redes 11", internal_code="REDES11", max_guests=4
    )
    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id,
        name="Estándar",
        items=[{"item_id": "a", "label": "A", "required": True}],
        required_photos=[],
    )
    db_session.add_all([prop, template])
    await db_session.flush()

    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        check_in_date=NOW.date(),
        check_out_date=(NOW + timedelta(days=2)).date(),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return tenant, prop, template, reservation


def _task(tenant, prop, template, reservation, status):
    return CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        reservation_id=reservation.id if reservation else None,
        status=status,
    )


@pytest.mark.asyncio
async def test_two_live_tasks_for_one_reservation_are_refused(db_session, seeded):
    tenant, prop, template, reservation = seeded
    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.CREATED))
    await db_session.flush()

    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.ASSIGNED))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_a_replacement_may_coexist_with_the_rejected_task(db_session, seeded):
    """Design D3: rejection is terminal and the replacement is a second row."""
    tenant, prop, template, reservation = seeded
    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.REJECTED))
    await db_session.flush()

    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.CREATED))
    await db_session.flush()

    rows = await db_session.execute(
        text("SELECT count(*) FROM cleaning_tasks WHERE reservation_id = :r"),
        {"r": reservation.id},
    )
    assert rows.scalar_one() == 2


@pytest.mark.asyncio
async def test_a_later_cleaning_may_follow_a_completed_one(db_session, seeded):
    tenant, prop, template, reservation = seeded
    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.COMPLETED))
    await db_session.flush()

    db_session.add(_task(tenant, prop, template, reservation, CleaningTaskStatus.CREATED))
    await db_session.flush()


@pytest.mark.asyncio
async def test_manual_tasks_without_a_reservation_are_not_constrained(db_session, seeded):
    tenant, prop, template, _ = seeded
    db_session.add(_task(tenant, prop, template, None, CleaningTaskStatus.CREATED))
    db_session.add(_task(tenant, prop, template, None, CleaningTaskStatus.CREATED))

    await db_session.flush()


def test_the_index_is_scoped_by_tenant():
    """`tenant_id` leads the index, so the constraint cannot reach across tenants.

    Not decorative: `reservations.id` is a UUID unique on its own, but the index exists to
    protect a per-tenant invariant and its leading column is what keeps it one.
    """
    index = next(
        ix
        for ix in CleaningTaskModel.__table__.indexes
        if ix.name == "uq_cleaning_tasks_live_reservation"
    )
    assert [column.name for column in index.columns] == ["tenant_id", "reservation_id"]
