import uuid
from dataclasses import dataclass
from datetime import datetime

from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus


@dataclass
class AccessRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    provider: AccessProvider = AccessProvider.MANUAL
    external_id: str | None = None
    status: AccessRecordStatus = AccessRecordStatus.PENDING
    code_masked: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_mode: AccessCreatedMode = AccessCreatedMode.MANUAL
    notes: str | None = None
