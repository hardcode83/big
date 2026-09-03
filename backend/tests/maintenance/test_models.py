import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import UniqueConstraint, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.maintenance.domain.entities import MAX_MATERIALS
from app.maintenance.domain.enums import (
    IncidentPhotoStage,
    IncidentSource,
    OwnerApprovalRelatedType,
)
from app.maintenance.infrastructure.models import (
    IncidentMessageModel,
    IncidentModel,
    IncidentPhotoModel,
    OwnerApprovalModel,
)
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


# --- incident_photos (`incident-photos` section 4, R1, R6) -----------------------------
#
# The table's whole reason to look different from `cleaning_photos` is D2: its own `tenant_id`
# plus a COMPOSITE foreign key into `incidents`, so that "the photo's tenant and its incident's
# tenant agree" is enforced by Postgres rather than by whoever writes the row. The test that
# earns its keep here is `test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant` —
# it is the one that fails if someone replaces the composite key with two simple ones.


async def _tenant_property_incident(db_session, *, name="Owner A", email="owner@example.com"):
    """A tenant, a property and an `IN_PROGRESS` incident, flushed and ready to hang photos off."""
    tenant = TenantModel(name=name, billing_email=email)
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(
        tenant_id=tenant.id, name="REDES11", internal_code=f"redes11-{tenant.id.hex[:8]}"
    )
    db_session.add(prop)
    await db_session.flush()

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.CLEANER,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
    )
    db_session.add(incident)
    await db_session.flush()
    return tenant, prop, incident


async def _uploader(db_session, tenant, *, email="tech@example.com"):
    user = UserModel(
        tenant_id=tenant.id,
        name="Tech One",
        email=email,
        password_hash="hash",
        role="TECHNICIAN",
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _photo(tenant, incident, uploader, *, stage=IncidentPhotoStage.BEFORE, key=None):
    return IncidentPhotoModel(
        tenant_id=tenant.id,
        incident_id=incident.id,
        uploaded_by=uploader.id,
        stage=stage,
        storage_key=key or f"tenants/{tenant.id}/incidents/{incident.id}/{uuid.uuid4()}.jpg",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_incident_photo_roundtrip(db_session) -> None:
    """R1.1 — the seven columns persist and read back with their declared types."""
    tenant, _, incident = await _tenant_property_incident(db_session)
    uploader = await _uploader(db_session, tenant)

    photo = _photo(tenant, incident, uploader)
    db_session.add(photo)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(IncidentPhotoModel).where(IncidentPhotoModel.id == photo.id)
        )
    ).scalar_one()

    assert fetched.tenant_id == tenant.id
    assert fetched.incident_id == incident.id
    assert fetched.uploaded_by == uploader.id
    assert fetched.stage is IncidentPhotoStage.BEFORE
    assert fetched.storage_key == photo.storage_key
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_two_photos_of_the_same_stage_are_allowed(db_session) -> None:
    """R1.4 — no uniqueness over `(incident_id, stage)`.

    A technician photographs two angles of one fault. This is the assertion that fails if
    somebody "tidies up" by adding a unique constraint.
    """
    tenant, _, incident = await _tenant_property_incident(db_session)
    uploader = await _uploader(db_session, tenant)

    db_session.add(_photo(tenant, incident, uploader, stage=IncidentPhotoStage.AFTER))
    db_session.add(_photo(tenant, incident, uploader, stage=IncidentPhotoStage.AFTER))
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(IncidentPhotoModel).where(IncidentPhotoModel.incident_id == incident.id)
        )
    ).scalars().all()

    assert len(rows) == 2
    assert {row.stage for row in rows} == {IncidentPhotoStage.AFTER}


@pytest.mark.asyncio
async def test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant(db_session) -> None:
    """R1.3 / D2 — **the database refuses the cross-tenant row**, not the repository.

    This is the test the composite foreign key exists for. With two independent single-column
    foreign keys (`tenant_id → tenants.id` and `incident_id → incidents.id`) this row is
    perfectly legal: both targets exist, they just belong to different tenants. That is the row
    the review panels of `guest-portal-api` reproduced for its own case, and the reason D2 chose
    `fk_incident_photos_incident_within_tenant` over the simpler pair.
    """
    tenant_a, _, _ = await _tenant_property_incident(db_session)
    tenant_b, _, incident_b = await _tenant_property_incident(
        db_session, name="Owner B", email="ownerb@example.com"
    )
    uploader_a = await _uploader(db_session, tenant_a)

    # Tenant A's photo pointing at tenant B's incident.
    db_session.add(
        IncidentPhotoModel(
            tenant_id=tenant_a.id,
            incident_id=incident_b.id,
            uploaded_by=uploader_a.id,
            stage=IncidentPhotoStage.BEFORE,
            storage_key=f"tenants/{tenant_a.id}/incidents/{incident_b.id}/{uuid.uuid4()}.jpg",
            created_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_photo_restrict_on_incident_delete(db_session) -> None:
    """`ON DELETE RESTRICT` — a photo is evidence, so it is a reason not to delete the incident."""
    tenant, _, incident = await _tenant_property_incident(db_session)
    uploader = await _uploader(db_session, tenant)
    db_session.add(_photo(tenant, incident, uploader))
    await db_session.commit()

    # The refusal comes from the DELETE itself, not from the commit: `RESTRICT` is checked
    # immediately (it is not a deferred constraint), so this is where it must be caught.
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("DELETE FROM incidents WHERE id = :id"), {"id": str(incident.id)}
        )


@pytest.mark.asyncio
async def test_incident_photo_restrict_on_uploader_delete(db_session) -> None:
    """`RESTRICT` and not `SET NULL`: the column is NOT NULL and records who did the work."""
    tenant, _, incident = await _tenant_property_incident(db_session)
    uploader = await _uploader(db_session, tenant)
    db_session.add(_photo(tenant, incident, uploader))
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(uploader.id)}
        )


def test_incident_photos_has_no_content_type_or_file_name_column() -> None:
    """R1.5 — asserted as an exact column set, so neither can be added quietly.

    The served `Content-Type` is derived from the extension inside `storage_key`; the client's
    file name never touches the key. A column for either would be a second, weaker source for a
    decision that already has exactly one.
    """
    columns = set(IncidentPhotoModel.__table__.columns.keys())

    assert columns == {
        "id",
        "tenant_id",
        "incident_id",
        "uploaded_by",
        "stage",
        "storage_key",
        "created_at",
    }


def test_incident_photos_has_no_updated_at_column() -> None:
    """The documented deviation from `steering/backend.md`: the row is immutable after insert.

    Stated as its own test rather than left to the column-set assertion above, so the intent is
    findable by name — the same way `test_owner_approvals_has_no_created_at_or_updated_at_column`
    records `owner_approvals`' own omission.
    """
    assert "updated_at" not in IncidentPhotoModel.__table__.columns


def test_incident_photos_created_at_has_no_server_default() -> None:
    """Stricter than `cleaning_photos` on purpose (R3.1).

    Postgres `now()` is the *transaction* timestamp, so a burst of photos inserted together
    would share one instant and the listing's ordering would fall through to a random `uuid4`.
    The use case passes the real upload time, and a `server_default` here would quietly make it
    optional to do so.
    """
    assert IncidentPhotoModel.__table__.columns["created_at"].server_default is None


def test_incident_photos_has_no_unique_constraint_over_stage() -> None:
    """R1.4 as a schema assertion, complementing the behavioural test above."""
    unique_column_sets = [
        {column.name for column in constraint.columns}
        for constraint in IncidentPhotoModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert {"incident_id", "stage"} not in unique_column_sets


def test_incidents_declares_the_unique_pair_the_composite_key_targets() -> None:
    """D2 — `uq_incidents_tenant_id_id` exists *because* `incident_photos` references it.

    Postgres requires a composite foreign key to point at a declared unique key. Pinned here so
    that removing the constraint fails loudly rather than only when the next migration runs.
    """
    named = {
        constraint.name
        for constraint in IncidentModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_incidents_tenant_id_id" in named


def test_incident_photos_is_inside_the_global_tenant_filter() -> None:
    """R1.3's actual payoff, and the thing `cleaning_photos` never gets.

    `tenant_scoped_classes()` resolves from the SQLAlchemy mapper registry, so it is this model
    — not the domain dataclass — that enters the filter of `app/core/db.py`. Asserted here
    because this is the section that delivers it.
    """
    from app.core.db import tenant_scoped_classes

    assert IncidentPhotoModel in tenant_scoped_classes()


@pytest.mark.asyncio
async def test_incident_message_roundtrip(db_session) -> None:
    """`staff-messaging` R2 — the columns persist and read back with their declared types."""
    tenant, _, incident = await _tenant_property_incident(db_session)
    author = await _uploader(db_session, tenant)

    message = IncidentMessageModel(
        tenant_id=tenant.id,
        incident_id=incident.id,
        author_id=author.id,
        author_role=UserRole.TECHNICIAN,
        content="The part arrived, starting the repair now.",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(message)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(IncidentMessageModel).where(IncidentMessageModel.id == message.id)
        )
    ).scalar_one()

    assert fetched.tenant_id == tenant.id
    assert fetched.incident_id == incident.id
    assert fetched.author_id == author.id
    assert fetched.author_role == UserRole.TECHNICIAN
    assert fetched.content == "The part arrived, starting the repair now."
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_a_message_cannot_be_attached_to_an_incident_of_another_tenant(db_session) -> None:
    """`staff-messaging` R2/R3.2 — **the database refuses the cross-tenant row**, not the
    repository.

    The same case `test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant` drives
    for `incident_photos`: with two independent single-column foreign keys this row would be
    perfectly legal, since both targets exist and just belong to different tenants.
    """
    tenant_a, _, _ = await _tenant_property_incident(db_session)
    tenant_b, _, incident_b = await _tenant_property_incident(
        db_session, name="Owner B", email="ownerb2@example.com"
    )
    author_a = await _uploader(db_session, tenant_a)

    # Tenant A's message pointing at tenant B's incident.
    db_session.add(
        IncidentMessageModel(
            tenant_id=tenant_a.id,
            incident_id=incident_b.id,
            author_id=author_a.id,
            author_role=UserRole.TECHNICIAN,
            content="Cross-tenant message attempt.",
            created_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
