import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.maintenance.domain.entities import MAX_MATERIALS
from app.maintenance.domain.enums import IncidentSource, OwnerApprovalRelatedType
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant_property(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


@pytest.mark.asyncio
async def test_incident_roundtrip(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
    )
    db_session.add(incident)
    await db_session.commit()

    result = await db_session.execute(select(IncidentModel).where(IncidentModel.id == incident.id))
    fetched = result.scalar_one()
    assert fetched.category.value == "OTHER"
    assert fetched.severity.value == "MEDIUM"
    assert fetched.status.value == "OPEN"
    assert fetched.owner_approval_required is False


@pytest.mark.asyncio
async def test_incident_property_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    db_session.add(
        IncidentModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.SYSTEM,
            title="Water leak",
            description="Leak detected under the kitchen sink.",
        )
    )
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_assigned_technician_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    technician = UserModel(
        tenant_id=tenant.id,
        name="Tech Tom",
        email="tom@example.com",
        password_hash="hash",
        role="TECHNICIAN",
    )
    db_session.add(technician)
    await db_session.flush()

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.OWNER,
        title="Fridge not cooling",
        description="Kitchen fridge stopped cooling overnight.",
        assigned_technician_id=technician.id,
    )
    db_session.add(incident)
    await db_session.commit()

    await db_session.delete(technician)
    await db_session.commit()

    await db_session.refresh(incident)
    assert incident.assigned_technician_id is None


@pytest.mark.asyncio
async def test_incident_reservation_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    check_in = date(2026, 8, 1)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=3),
        nights=3,
    )
    db_session.add(reservation)
    await db_session.flush()

    db_session.add(
        IncidentModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.PMS,
            title="Guest reported noise",
            description="Guest complained about noise from a neighboring unit.",
            reservation_id=reservation.id,
        )
    )
    await db_session.commit()

    await db_session.delete(reservation)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_reported_by_user_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    reporter = UserModel(
        tenant_id=tenant.id,
        name="Manager Mia",
        email="mia@example.com",
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(reporter)
    await db_session.flush()

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.CLEANER,
        title="Damaged sofa",
        description="Sofa cushion torn, reported by manager.",
        reported_by_user_id=reporter.id,
    )
    db_session.add(incident)
    await db_session.commit()

    await db_session.delete(reporter)
    await db_session.commit()

    await db_session.refresh(incident)
    assert incident.reported_by_user_id is None


@pytest.mark.asyncio
async def test_incident_cleaning_task_restrict_on_delete(db_session) -> None:
    """`RESTRICT` and not `SET NULL` (`cleaner-incident-report` D10): the link matters most
    exactly when someone deletes the task it points at."""
    tenant, prop = await _tenant_property(db_session)
    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id,
        name="Standard",
        items=[{"id": "kitchen", "label": "Kitchen", "required": True}],
        required_photos=[],
    )
    db_session.add(template)
    await db_session.flush()
    task = CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        status=CleaningTaskStatus.IN_PROGRESS,
    )
    db_session.add(task)
    await db_session.flush()

    db_session.add(
        IncidentModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.CLEANER,
            title="Broken boiler",
            description="No hot water in the bathroom.",
            cleaning_task_id=task.id,
        )
    )
    await db_session.commit()

    await db_session.delete(task)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_assignment_note_is_a_nullable_bounded_column() -> None:
    """R3.1, design D6 — the bound lives in the DDL, not only in pydantic.

    `MAX_ASSIGNMENT_NOTE` in `app/maintenance/api/schemas.py` mirrors this number; asserting
    it here is what keeps the two from drifting into the situation `properties-crud` R2.4 had
    to repair on four columns that shipped with a pydantic-only bound.
    """
    column = IncidentModel.__table__.c.assignment_note

    assert column.nullable is True
    assert column.type.length == 2000


@pytest.mark.asyncio
async def test_incident_eta_at_is_a_nullable_timestamptz() -> None:
    """R3.1 — `TIMESTAMPTZ` and nullable.

    `timezone=True` is not decoration: `_apply_eta` refuses a naïve value at the domain edge,
    and a column storing `timestamp without time zone` would silently drop the offset of
    everything that got past it.
    """
    column = IncidentModel.__table__.c.eta_at

    assert column.nullable is True
    assert column.type.timezone is True


@pytest.mark.asyncio
async def test_incident_materials_is_a_nullable_bounded_column() -> None:
    """R4.1 — the bound lives in the DDL, not only in pydantic.

    `MAX_MATERIALS` in `app/maintenance/domain/entities.py` is the same number, imported by
    `api/schemas.py`; asserting the width here is what keeps the two from drifting into the
    situation `properties-crud` R2.4 had to repair on four columns that shipped with a
    pydantic-only bound. The real DDL is read back in
    `tests/test_migrations.py::test_the_declared_column_widths_reach_the_real_ddl`, which is
    the half this assertion cannot see — the suite's schema comes from `create_all`, so a
    model and a migration that disagreed would both look right from here.
    """
    column = IncidentModel.__table__.c.materials

    assert column.nullable is True
    assert column.type.length == MAX_MATERIALS


@pytest.mark.asyncio
async def test_incident_severity_is_distinct_postgres_enum_from_timeline_severity(db_session) -> None:
    incident_severity_values = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = "
            "(SELECT oid FROM pg_type WHERE typname = 'incident_severity') ORDER BY enumsortorder"
        )
    )
    timeline_severity_values = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = "
            "(SELECT oid FROM pg_type WHERE typname = 'timeline_severity') ORDER BY enumsortorder"
        )
    )

    assert [r[0] for r in incident_severity_values] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert [r[0] for r in timeline_severity_values] == ["INFO", "WARNING", "ERROR", "CRITICAL"]


async def _owner_approval(db_session, tenant, prop, responded_by=None) -> OwnerApprovalModel:
    approval = OwnerApprovalModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=Decimal("250.00"),
        reason="Boiler replacement quoted by the technician.",
        responded_by=responded_by,
    )
    db_session.add(approval)
    return approval


@pytest.mark.asyncio
async def test_owner_approval_roundtrip_applies_the_prd_defaults(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    approval = await _owner_approval(db_session, tenant, prop)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(OwnerApprovalModel).where(OwnerApprovalModel.id == approval.id)
        )
    ).scalar_one()
    assert fetched.status.value == "PENDING"
    assert fetched.requested_at is not None
    assert fetched.responded_at is None
    assert fetched.amount == Decimal("250.00")


@pytest.mark.asyncio
async def test_owner_approvals_has_no_created_at_or_updated_at_column() -> None:
    """§7.19 declares neither (design OQ1): the mixin must not have crept in."""
    columns = set(OwnerApprovalModel.__table__.columns.keys())

    assert "created_at" not in columns
    assert "updated_at" not in columns
    assert {"requested_at", "responded_at"} <= columns


@pytest.mark.asyncio
async def test_owner_approval_responder_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    owner = UserModel(
        tenant_id=tenant.id,
        name="Owner Olga",
        email="olga@example.com",
        password_hash="hash",
        role="TENANT_OWNER",
    )
    db_session.add(owner)
    await db_session.flush()

    approval = await _owner_approval(db_session, tenant, prop, responded_by=owner.id)
    await db_session.commit()

    await db_session.delete(owner)
    await db_session.commit()
    await db_session.refresh(approval)

    assert approval.responded_by is None
    assert approval.reason.startswith("Boiler replacement")


@pytest.mark.asyncio
async def test_owner_approval_polymorphic_reference_has_no_foreign_key() -> None:
    assert OwnerApprovalModel.__table__.c.related_id.foreign_keys == set()
    assert OwnerApprovalModel.__table__.c.related_id.nullable is False


@pytest.mark.asyncio
async def test_owner_approval_requested_at_default_comes_from_the_ddl(db_session) -> None:
    """`requested_at` is this row's creation timestamp, defaulted like every other.

    Raw `text()`: SQLAlchemy Core would fill a Python-side default and prove nothing
    (QA finding, section 1). §7.19 declares the column NOT NULL with no DEFAULT —
    exactly as it declares `created_at` in the other 22 tables, all of which
    `TimestampMixin` defaults (design D5, panel section 2).
    """
    tenant, prop = await _tenant_property(db_session)

    await db_session.execute(
        text(
            "INSERT INTO owner_approvals "
            "(id, tenant_id, property_id, related_type, related_id, amount, reason) "
            "VALUES (:id, :tenant_id, :property_id, 'INCIDENT', :related_id, 250.00, 'raw insert')"
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant.id,
            "property_id": prop.id,
            "related_id": uuid.uuid4(),
        },
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(OwnerApprovalModel).where(OwnerApprovalModel.reason == "raw insert")
        )
    ).scalar_one()
    assert fetched.requested_at is not None
    assert fetched.status.value == "PENDING"


@pytest.mark.asyncio
async def test_owner_approval_property_restrict_on_delete(db_session) -> None:
    """`owner_approvals.property_id` is this model's OWN mandatory FK (R3.7, D8).

    Without it, flipping this column to CASCADE would leave the file green: every
    other RESTRICT case here drives IncidentModel or ExpenseModel instead.
    """
    tenant, prop = await _tenant_property(db_session)
    await _owner_approval(db_session, tenant, prop)
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()
