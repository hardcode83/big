import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.guests.domain.enums import GuestDocumentStatus, GuestDocumentType, LegalRegistrationStatus


@dataclass
class Guest:
    id: uuid.UUID
    tenant_id: uuid.UUID
    full_name: str
    created_at: datetime
    updated_at: datetime
    email: str | None = None
    phone: str | None = None
    preferred_language: str = "es"
    nationality: str | None = None
    date_of_birth: date | None = None
    document_type: GuestDocumentType | None = None
    document_number_encrypted: str | None = None
    document_expiry_date: date | None = None
    document_status: GuestDocumentStatus = GuestDocumentStatus.NOT_PROVIDED
    legal_registration_status: LegalRegistrationStatus = LegalRegistrationStatus.NOT_REQUIRED
