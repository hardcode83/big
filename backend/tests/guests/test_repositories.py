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
    db_session,
    tenant: TenantModel,
    *,
    full_name: str,
    email: str | None = None,
    phone: str | None = None,
    created_at=None,
) -> GuestModel:
    model = GuestModel(tenant_id=tenant.id, full_name=full_name, email=email, phone=phone)
    if created_at is not None:
        model.created_at = created_at
        model.updated_at = created_at
    db_session.add(model)
    await db_session.flush()
    return model


def _repository(db_session, tenant: TenantModel) -> SqlAlchemyGuestRepository:
    """The tenant is a per-call parameter, not instance state (see the adapter)."""
    return SqlAlchemyGuestRepository(db_session)


# --- `list_for_ids` (`dashboard-api` R1.7, task 6.1) ------------------------------------
#
# The batch reader the dashboard card needs. The tenancy panel of `dashboard-api` sections
# 6-7 asked for these specifically: it is the one method built for the "dictionary lookup
# keyed by an id that resolved in another tenant" hazard the aggregate introduces, and it
# had no cross-tenant test anywhere in the suite — the end-to-end isolation test looked like
# it covered the path but never reached it, because its seeded reservation had no guest.


@pytest.mark.asyncio
async def test_list_for_ids_returns_the_summaries_of_the_batch(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    one = await _guest(db_session, tenant, full_name="Marta García", email="m@example.com")
    two = await _guest(db_session, tenant, full_name="Luis Pérez", email="l@example.com")
    await _guest(db_session, tenant, full_name="Not asked for", email="n@example.com")

    found = await _repository(db_session, tenant).list_for_ids(tenant.id, [one.id, two.id])

    assert {guest.id for guest in found} == {one.id, two.id}
    assert {guest.full_name for guest in found} == {"Marta García", "Luis Pérez"}


@pytest.mark.asyncio
async def test_list_for_ids_never_reads_another_tenants_guest(db_session) -> None:
    """DoD §28.18 and rule 1 of `steering/security.md`.

    The neighbour's id is passed in **explicitly**, so the tenant argument is the only thing
    excluding it — exactly the call a buggy aggregate would make after joining on a global
    UUID. `guests.id` is not composite with `tenant_id`, so nothing but this filter stops it.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _guest(db_session, tenant_a, full_name="Mine", email="mine@example.com")
    theirs = await _guest(db_session, tenant_b, full_name="Theirs", email="t@example.com")

    found = await _repository(db_session, tenant_a).list_for_ids(
        tenant_a.id, [mine.id, theirs.id]
    )

    assert [guest.id for guest in found] == [mine.id]
    assert all(guest.full_name != "Theirs" for guest in found)


@pytest.mark.asyncio
async def test_list_for_ids_omits_an_id_that_does_not_resolve(db_session) -> None:
    """Absent rather than raising: the caller keys the result by id and defaults."""
    tenant = await _tenant(db_session, "TenantA")
    mine = await _guest(db_session, tenant, full_name="Mine", email="mine@example.com")

    found = await _repository(db_session, tenant).list_for_ids(
        tenant.id, [mine.id, uuid.uuid4()]
    )

    assert [guest.id for guest in found] == [mine.id]


@pytest.mark.asyncio
async def test_list_for_ids_returns_summaries_without_document_data(db_session) -> None:
    """Rule 4 of `steering/security.md` — the batch reader returns `GuestSummary` like its
    siblings, so a document number is out of reach by construction."""
    import dataclasses

    tenant = await _tenant(db_session, "TenantA")
    guest = await _guest(db_session, tenant, full_name="Marta", email="m@example.com")

    found = await _repository(db_session, tenant).list_for_ids(tenant.id, [guest.id])

    fields = {field.name for field in dataclasses.fields(found[0])}
    assert "document_number_encrypted" not in fields
    assert "date_of_birth" not in fields


@pytest.mark.asyncio
async def test_list_for_ids_with_an_empty_batch_returns_nothing(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")

    assert await _repository(db_session, tenant).list_for_ids(tenant.id, []) == []


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
async def test_the_id_breaks_the_tie_when_created_at_is_identical(db_session) -> None:
    """The second half of design D8's rule: two rows inserted in the same clock tick."""
    tenant = await _tenant(db_session, "TenantA")
    same_instant = datetime(2026, 1, 1, tzinfo=UTC)
    one = await _guest(
        db_session, tenant, full_name="John A", email="john@example.com", created_at=same_instant
    )
    two = await _guest(
        db_session, tenant, full_name="John B", email="john@example.com", created_at=same_instant
    )

    found = await _repository(db_session, tenant).find_by_email(tenant.id, "john@example.com")

    assert found is not None
    assert found.id == min(one.id, two.id, key=str)


# --- `find_by_phone` (`whatsapp-cloud-adapter` R4.2, R4.4) --------------------------------
#
# Plural, unlike `find_by_email`: R4.4 needs to know *whether* more than one guest shares a
# phone so the caller can escalate rather than guess, so this must never collapse to a
# single deterministic pick.


@pytest.mark.asyncio
async def test_find_by_phone_with_no_match_returns_empty(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _guest(db_session, tenant, full_name="John", phone="+34600000000")

    found = await _repository(db_session, tenant).find_by_phone(tenant.id, "+34611111111")

    assert found == []


@pytest.mark.asyncio
async def test_find_by_phone_with_one_match_returns_it(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _guest(db_session, tenant, full_name="John", phone="+34612345678")

    found = await _repository(db_session, tenant).find_by_phone(tenant.id, "+34612345678")

    assert [g.id for g in found] == [model.id]


@pytest.mark.asyncio
async def test_find_by_phone_with_several_matches_returns_all_of_them(db_session) -> None:
    """The escalation signal of R4.4: several guests sharing one number is not collapsed."""
    tenant = await _tenant(db_session, "TenantA")
    one = await _guest(db_session, tenant, full_name="John", phone="+34612345678")
    two = await _guest(db_session, tenant, full_name="Jane", phone="+34612345678")

    found = await _repository(db_session, tenant).find_by_phone(tenant.id, "+34612345678")

    assert {g.id for g in found} == {one.id, two.id}


@pytest.mark.asyncio
async def test_find_by_phone_does_not_cross_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _guest(db_session, tenant_b, full_name="Their John", phone="+34612345678")

    found = await _repository(db_session, tenant_a).find_by_phone(tenant_a.id, "+34612345678")

    assert found == []


@pytest.mark.asyncio
async def test_find_by_phone_with_a_blank_phone_matches_nothing(db_session) -> None:
    """The same guard `find_by_email` applies to a blank address, and for the same reason."""
    tenant = await _tenant(db_session, "TenantA")
    await _guest(db_session, tenant, full_name="No phone")

    found = await _repository(db_session, tenant).find_by_phone(tenant.id, "")

    assert found == []


@pytest.mark.asyncio
async def test_a_blank_email_is_stored_as_null(db_session) -> None:
    """`"   "` is truthy before `strip()`; storing it as `""` would make it a shared key."""
    tenant = await _tenant(db_session, "TenantA")
    now = datetime.now(UTC)
    guest = Guest(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        full_name="No Email",
        created_at=now,
        updated_at=now,
        email="   ",
    )

    await _repository(db_session, tenant).add(tenant.id, guest)

    stored = await _repository(db_session, tenant).get(tenant.id, guest.id)
    assert stored is not None
    assert stored.email is None


@pytest.mark.asyncio
async def test_a_blank_email_never_matches_another_guest(db_session) -> None:
    """Two rows with no email are two people, not one (design D8)."""
    tenant = await _tenant(db_session, "TenantA")
    now = datetime.now(UTC)
    for name in ("First Anonymous", "Second Anonymous"):
        await _repository(db_session, tenant).add(
            tenant.id,
            Guest(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                full_name=name,
                created_at=now,
                updated_at=now,
                email="  ",
            ),
        )

    assert await _repository(db_session, tenant).find_by_email(tenant.id, "\t") is None
    assert await _repository(db_session, tenant).find_by_email(tenant.id, "") is None


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
