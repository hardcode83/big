import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningChecklistTemplateModel,
    CleaningPhotoModel,
    CleaningTaskModel,
)
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.auth.infrastructure.models import UserModel


async def _tenant_property_user(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    user = UserModel(
        tenant_id=tenant.id,
        name="Ana Cleaner",
        email="ana@example.com",
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
