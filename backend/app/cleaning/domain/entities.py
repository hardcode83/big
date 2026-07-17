import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus


@dataclass
class CleaningTask:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    checklist_template_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    assigned_cleaner_id: uuid.UUID | None = None
    status: CleaningTaskStatus = CleaningTaskStatus.CREATED
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    validation_status: CleaningValidationStatus = CleaningValidationStatus.PENDING
    validated_by_user_id: uuid.UUID | None = None
    validated_at: datetime | None = None


@dataclass
class CleaningChecklistTemplate:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    items: list[dict[str, Any]]
    required_photos: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    active: bool = True


@dataclass
class CleaningChecklistCompletion:
    id: uuid.UUID
    cleaning_task_id: uuid.UUID
    item_id: str
    completed: bool = False
    completed_at: datetime | None = None
    completed_by: uuid.UUID | None = None
    notes: str | None = None


@dataclass
class CleaningPhoto:
    id: uuid.UUID
    cleaning_task_id: uuid.UUID
    uploaded_by: uuid.UUID
    photo_type: str
    storage_key: str
    created_at: datetime
    ai_validation_result: dict[str, Any] | None = None
