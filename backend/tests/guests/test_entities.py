import uuid
from datetime import datetime, timezone

from app.guests.domain.entities import Guest
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus


def test_guest_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    guest = Guest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        full_name="Jane Doe",
        created_at=now,
        updated_at=now,
    )

    assert guest.preferred_language == "es"
    assert guest.document_status == GuestDocumentStatus.NOT_PROVIDED
    assert guest.legal_registration_status == LegalRegistrationStatus.NOT_REQUIRED
    assert guest.document_type is None
