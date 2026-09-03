from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.domain.enums import UserRole
from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningChecklistTemplateModel,
    CleaningPhotoModel,
    CleaningTaskMessageModel,
    CleaningTaskModel,
)
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.auth.infrastructure.models import UserModel


async def _tenant_property_user(
    db_session,
    *,
    name="Owner A",
    billing_email="owner@example.com",
    user_email="ana@example.com",
):
    tenant = TenantModel(name=name, billing_email=billing_email)
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    user = UserModel(
        tenant_id=tenant.id,
        name="Ana Cleaner",
        email=user_email,
        password_hash="hash",
        role="CLEANER",
    )
    db_session.add_all([prop, user])
    await db_session.flush()
    return tenant, prop, user


@pytest.mark.asyncio
async def test_cleaning_task_roundtrip(db_session) -> None:
    tenant, prop, user = await _tenant_property_user(db_session)

    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id,
        name="Standard",
        items=[{"id": "ventilate", "label_es": "Ventilar", "label_en": "Ventilate", "required": True, "order": 1}],
        required_photos=[{"id": "living_room", "label_es": "Salón", "label_en": "Living room", "required": True}],
    )
    db_session.add(template)
    await db_session.flush()

    task = CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        assigned_cleaner_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()

    result = await db_session.execute(select(CleaningTaskModel).where(CleaningTaskModel.id == task.id))
    fetched = result.scalar_one()
    assert fetched.status.value == "CREATED"
    assert fetched.validation_status.value == "PENDING"
    assert fetched.assigned_cleaner_id == user.id


@pytest.mark.asyncio
async def test_cleaning_checklist_completion_unique_per_task_and_item(db_session) -> None:
    tenant, prop, user = await _tenant_property_user(db_session)

    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id, name="Standard", items=[], required_photos=[]
    )
    db_session.add(template)
    await db_session.flush()

    task = CleaningTaskModel(tenant_id=tenant.id, property_id=prop.id, checklist_template_id=template.id)
    db_session.add(task)
    await db_session.flush()

    db_session.add(CleaningChecklistCompletionModel(cleaning_task_id=task.id, item_id="ventilate"))
    await db_session.commit()

    db_session.add(CleaningChecklistCompletionModel(cleaning_task_id=task.id, item_id="ventilate"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_cleaning_photo_roundtrip(db_session) -> None:
    tenant, prop, user = await _tenant_property_user(db_session)

    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id, name="Standard", items=[], required_photos=[]
    )
    db_session.add(template)
    await db_session.flush()

    task = CleaningTaskModel(tenant_id=tenant.id, property_id=prop.id, checklist_template_id=template.id)
    db_session.add(task)
    await db_session.flush()

    photo = CleaningPhotoModel(
        cleaning_task_id=task.id,
        uploaded_by=user.id,
        photo_type="living_room",
        storage_key="cleaning/2026-07-17/living_room.jpg",
    )
    db_session.add(photo)
    await db_session.commit()

    result = await db_session.execute(select(CleaningPhotoModel).where(CleaningPhotoModel.id == photo.id))
    fetched = result.scalar_one()
    assert fetched.ai_validation_result is None


@pytest.mark.asyncio
async def test_cleaning_task_message_roundtrip(db_session) -> None:
    tenant, prop, user = await _tenant_property_user(db_session)

    template = CleaningChecklistTemplateModel(
        tenant_id=tenant.id, name="Standard", items=[], required_photos=[]
    )
    db_session.add(template)
    await db_session.flush()

    task = CleaningTaskModel(tenant_id=tenant.id, property_id=prop.id, checklist_template_id=template.id)
    db_session.add(task)
    await db_session.flush()

    message = CleaningTaskMessageModel(
        tenant_id=tenant.id,
        task_id=task.id,
        author_id=user.id,
        author_role=UserRole.CLEANER,
        content="La habitación necesita más toallas.",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(message)
    await db_session.commit()

    result = await db_session.execute(
        select(CleaningTaskMessageModel).where(CleaningTaskMessageModel.id == message.id)
    )
    fetched = result.scalar_one()
    assert fetched.author_role == UserRole.CLEANER
    assert fetched.content == "La habitación necesita más toallas."


@pytest.mark.asyncio
async def test_a_message_cannot_be_attached_to_a_task_of_another_tenant(db_session) -> None:
    """`staff-messaging` R1/R3.2 — **the database refuses the cross-tenant row**, not the
    repository.

    The composite foreign key on `(tenant_id, task_id)` is the whole mechanism: with two
    independent single-column foreign keys this row would be perfectly legal, since both
    targets exist and just belong to different tenants. Same shape as
    `test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant` for `incident_photos`.
    """
    tenant_a, prop_a, user_a = await _tenant_property_user(db_session)
    tenant_b, prop_b, _ = await _tenant_property_user(
        db_session,
        name="Owner B",
        billing_email="ownerb@example.com",
        user_email="anab@example.com",
    )

    template_b = CleaningChecklistTemplateModel(
        tenant_id=tenant_b.id, name="Standard", items=[], required_photos=[]
    )
    db_session.add(template_b)
    await db_session.flush()

    task_b = CleaningTaskModel(
        tenant_id=tenant_b.id, property_id=prop_b.id, checklist_template_id=template_b.id
    )
    db_session.add(task_b)
    await db_session.flush()

    # Tenant A's message pointing at tenant B's task.
    db_session.add(
        CleaningTaskMessageModel(
            tenant_id=tenant_a.id,
            task_id=task_b.id,
            author_id=user_a.id,
            author_role=UserRole.CLEANER,
            content="Cross-tenant message attempt.",
            created_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
