import uuid
from datetime import datetime, timezone

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus


def test_access_record_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    record = AccessRecord(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )

    assert record.provider == AccessProvider.MANUAL
    assert record.status == AccessRecordStatus.PENDING
    assert record.created_mode == AccessCreatedMode.MANUAL
    assert record.reservation_id is None
