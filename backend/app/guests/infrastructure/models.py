from datetime import date

from sqlalchemy import Date, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.guests.domain.enums import GuestDocumentStatus, GuestDocumentType, LegalRegistrationStatus

legal_registration_status_enum = Enum(
    LegalRegistrationStatus, name="legal_registration_status", native_enum=True
)


class GuestModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "guests"
    __table_args__ = (Index("ix_guests_tenant_id_email", "tenant_id", "email"),)

    full_name: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(255), default=None)
    phone: Mapped[str | None] = mapped_column(String(30), default=None)
    preferred_language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    nationality: Mapped[str | None] = mapped_column(String(2), default=None)
    date_of_birth: Mapped[date | None] = mapped_column(Date, default=None)
    document_type: Mapped[GuestDocumentType | None] = mapped_column(
        Enum(GuestDocumentType, name="guest_document_type", native_enum=True), default=None
    )
    document_number_encrypted: Mapped[str | None] = mapped_column(default=None)
    document_expiry_date: Mapped[date | None] = mapped_column(Date, default=None)
    document_status: Mapped[GuestDocumentStatus] = mapped_column(
        Enum(GuestDocumentStatus, name="guest_document_status", native_enum=True),
        default=GuestDocumentStatus.NOT_PROVIDED,
        server_default=GuestDocumentStatus.NOT_PROVIDED.value,
    )
    legal_registration_status: Mapped[LegalRegistrationStatus] = mapped_column(
        legal_registration_status_enum,
        default=LegalRegistrationStatus.NOT_REQUIRED,
        server_default=LegalRegistrationStatus.NOT_REQUIRED.value,
    )
