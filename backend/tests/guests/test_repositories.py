"""`SqlAlchemyGuestRepository` — dedup, tenant scoping and write refusal (R1.8, R3.5, R5.1)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.guests.domain.entities import Guest
from app.guests.domain.enums import GuestDocumentStatus, GuestDocumentType
from app.guests.infrastructure.models import GuestModel
from app.core.tenancy import CrossTenantWriteError
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _guest(
    db_session, tenant: TenantModel, *, full_name: str, email: str | None, created_at=None
) -> GuestModel:
    model = GuestModel(tenant_id=tenant.id, full_name=full_name, email=email)
    if created_at is not None:
        model.created_at = created_at
        model.updated_at = created_at
    db_session.add(model)
    await db_session.flush()
    return model


def _repository(db_session, tenant: TenantModel) -> SqlAlchemyGuestRepository:
    """The tenant is a per-call parameter, not instance state (see the adapter)."""
    return SqlAlchemyGuestRepository(db_session)


@pytest.mark.asyncio
async def test_get_returns_the_guest_of_its_tenant(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _guest(db_session, tenant, full_name="John Smith", email="john@example.com")

    found = await _repository(db_session, tenant).get(tenant.id, model.id)

    assert found is not None
    assert found.full_name == "John Smith"


@pytest.mark.asyncio
async def test_get_does_not_reach_another_tenants_guest(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _guest(db_session, tenant_b, full_name="Their Guest", email="t@example.com")

    found = await _repository(db_session, tenant_a).get(tenant_a.id, theirs.id)

    assert found is None


@pytest.mark.asyncio
async def test_find_by_email_matches_case_insensitively(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _guest(db_session, tenant, full_name="John", email="john@example.com")

    found = await _repository(db_session, tenant).find_by_email(tenant.id, "  John@Example.COM ")

    assert found is not None
    assert found.id == model.id


@pytest.mark.asyncio
async def test_find_by_email_does_not_cross_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _guest(db_session, tenant_b, full_name="Their John", email="john@example.com")

    found = await _repository(db_session, tenant_a).find_by_email(tenant_a.id, "john@example.com")

    assert found is None


@pytest.mark.asyncio
async def test_find_by_email_picks_the_oldest_deterministically(db_session) -> None:
    """`guests.email` is a plain index, so duplicates are legal — the answer must not
    depend on the query plan (design D8)."""
    tenant = await _tenant(db_session, "TenantA")
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = older + timedelta(days=30)
    second = await _guest(
        db_session, tenant, full_name="John Later", email="john@example.com", created_at=newer
    )
    first = await _guest(
        db_session, tenant, full_name="John First", email="john@example.com", created_at=older
    )

    found = await _repository(db_session, tenant).find_by_email(tenant.id, "john@example.com")

    assert found is not None
    assert found.id == first.id
    assert found.id != second.id


@pytest.mark.asyncio
async def test_reads_cannot_carry_identity_document_data(db_session) -> None:
    """The structural half of R1.8 and rule 4 of `steering/security.md` (design D17).

    A guest WITH document data is stored, and what the port returns must not contain it —
    not masked, not encrypted: absent. That is what stops a future serialiser built on the
    repository's return value from leaking the ciphertext or the date of birth.
    """
    tenant = await _tenant(db_session, "TenantA")
    model = GuestModel(
        tenant_id=tenant.id,
        full_name="John Smith",
        email="john@example.com",
        nationality="GB",
        date_of_birth=date(1980, 5, 17),
        document_type=GuestDocumentType.PASSPORT,
        document_number_encrypted="gAAAAAB-not-a-real-token",
        document_expiry_date=date(2030, 1, 1),
        document_status=GuestDocumentStatus.PROVIDED,
    )
    db_session.add(model)
    await db_session.flush()

    summary = await _repository(db_session, tenant).get(tenant.id, model.id)

    assert summary is not None
    assert summary.document_status is GuestDocumentStatus.PROVIDED
    exposed = set(vars(summary))
    assert not exposed & {
        "document_number_encrypted",
        "document_expiry_date",
        "date_of_birth",
        "nationality",
    }


@pytest.mark.asyncio
async def test_add_stores_the_email_normalised(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = _repository(db_session, tenant)
    now = datetime.now(UTC)
    guest = Guest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        full_name="María García",
        created_at=now,
        updated_at=now,
        email="  Maria.Garcia@Example.COM ",
    )

    await repository.add(tenant.id, guest)

    found = await repository.find_by_email(tenant.id, "maria.garcia@example.com")
    assert found is not None
    assert found.email == "maria.garcia@example.com"


@pytest.mark.asyncio
async def test_add_refuses_a_guest_of_another_tenant(db_session) -> None:
    """The session listener does not guard INSERTs (limit 3 of its docstring), so this
    check is the only thing preventing a cross-tenant row (R5.1)."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    now = datetime.now(UTC)
    foreign = Guest(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        full_name="Their Guest",
        created_at=now,
        updated_at=now,
        email="their@example.com",
    )

    with pytest.raises(CrossTenantWriteError):
        await _repository(db_session, tenant_a).add(tenant_a.id, foreign)
