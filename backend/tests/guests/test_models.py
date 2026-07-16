import pytest
from sqlalchemy import select

from app.guests.infrastructure.models import GuestModel
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.tenants.infrastructure.models import TenantModel


@pytest.mark.asyncio
async def test_guest_roundtrip_with_defaults(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    guest = GuestModel(tenant_id=tenant.id, full_name="Jane Doe")
    db_session.add(guest)
    await db_session.commit()

    result = await db_session.execute(select(GuestModel).where(GuestModel.id == guest.id))
    fetched = result.scalar_one()
    assert fetched.document_status == GuestDocumentStatus.NOT_PROVIDED
    assert fetched.legal_registration_status == LegalRegistrationStatus.NOT_REQUIRED
    assert fetched.preferred_language == "es"
