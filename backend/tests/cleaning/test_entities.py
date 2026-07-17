import uuid
from datetime import datetime, timezone

from app.cleaning.domain.entities import (
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningPhoto,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus


def test_cleaning_task_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    task = CleaningTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )

    assert task.status == CleaningTaskStatus.CREATED
    assert task.validation_status == CleaningValidationStatus.PENDING
    assert task.reservation_id is None
    assert task.assigned_cleaner_id is None


def test_cleaning_checklist_template_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    template = CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Standard checklist",
        items=[{"id": "ventilate", "label_es": "Ventilar", "label_en": "Ventilate", "required": True, "order": 1}],
        required_photos=[{"id": "living_room", "label_es": "Salón", "label_en": "Living room", "required": True}],
        created_at=now,
        updated_at=now,
    )

    assert template.active is True
    assert template.property_id is None


def test_cleaning_checklist_completion_instantiates_with_defaults() -> None:
    completion = CleaningChecklistCompletion(
        id=uuid.uuid4(),
        cleaning_task_id=uuid.uuid4(),
        item_id="ventilate",
    )

    assert completion.completed is False
    assert completion.completed_at is None
    assert completion.completed_by is None


def test_cleaning_photo_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    photo = CleaningPhoto(
        id=uuid.uuid4(),
        cleaning_task_id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        photo_type="living_room",
        storage_key="cleaning/2026-07-17/living_room.jpg",
        created_at=now,
    )

    assert photo.ai_validation_result is None
