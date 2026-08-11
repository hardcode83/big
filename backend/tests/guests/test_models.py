import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import ForeignKeyConstraint, select
from sqlalchemy.exc import IntegrityError

from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
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


# --- `guest_access_tokens` (R1.1, R1.5, design D2) -----------------------------------
#
# Structural assertions about what the mapping *declares*. The behaviour they stand for is
# driven against real Postgres further down this same file; a schema invariant deserves
# both, because a declaration that never reaches the database is silent and a behavioural
# test alone would not say which declaration was meant to produce it.


def test_the_token_table_carries_the_columns_the_authoriser_reads() -> None:
    columns = GuestAccessTokenModel.__table__.columns

    assert {"id", "tenant_id", "reservation_id", "token_hash", "revoked_at"} <= set(columns.keys())
    assert columns["token_hash"].type.length == 64
    assert columns["reservation_id"].nullable is False
    assert columns["revoked_at"].nullable is True


def test_there_is_no_expires_at_column() -> None:
    """D3: the window is derived at authorisation time, never stored.

    Worth pinning as an absence. An `expires_at` computed at issue time goes stale the
    moment the stay moves, and would need a sweep to catch cancellations — which is exactly
    the design D3 rejected. The cheapest way for it to come back is someone adding it
    "for convenience" alongside `revoked_at`.
    """
    assert "expires_at" not in GuestAccessTokenModel.__table__.columns


def test_the_reservation_foreign_key_restricts_deletion() -> None:
    """A live token is a reason not to delete the stay silently — it is the access trail."""
    foreign_key = next(iter(GuestAccessTokenModel.__table__.columns["reservation_id"].foreign_keys))

    assert foreign_key.column.table.name == "reservations"
    assert foreign_key.ondelete == "RESTRICT"


def test_the_token_hash_is_unique_across_tenants() -> None:
    """D2: the authorising query runs with no tenant in hand, so "exactly one row" has to
    be a schema guarantee rather than something the caller narrows afterwards."""
    token_hash = GuestAccessTokenModel.__table__.columns["token_hash"]

    assert token_hash.unique is True
    assert token_hash.index is True


def test_only_one_live_token_per_reservation_is_declared() -> None:
    """R1.5 as a partial unique index. Partial, because the revoked rows are the history."""
    indexes = {index.name: index for index in GuestAccessTokenModel.__table__.indexes}
    live = indexes["uq_guest_access_tokens_live_per_reservation"]

    assert live.unique is True
    assert [column.name for column in live.columns] == ["reservation_id"]
    assert "revoked_at IS NULL" in str(live.dialect_options["postgresql"]["where"])


def test_the_token_table_is_inside_the_global_tenant_filter() -> None:
    """Rule 1 of `steering/security.md`: it carries `tenant_id`, so the net covers it."""
    from app.core.db import tenant_scoped_classes

    assert GuestAccessTokenModel in tenant_scoped_classes()


def test_the_reservation_is_reached_through_a_composite_foreign_key() -> None:
    """R2.5: the token's tenant and its stay's tenant cannot diverge.

    Declared here and *exercised* two tests below. Both halves matter: this one fails if
    somebody simplifies the constraint back to a single-column FK, which is the shape that
    let the mismatched row through in the first place.
    """
    composite = {
        constraint
        for constraint in GuestAccessTokenModel.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint) and len(constraint.columns) == 2
    }
    assert len(composite) == 1
    constraint = composite.pop()

    assert {column.name for column in constraint.columns} == {"tenant_id", "reservation_id"}
    assert {key.target_fullname for key in constraint.elements} == {
        "reservations.tenant_id",
        "reservations.id",
    }
    assert constraint.ondelete == "RESTRICT"


# --- The same invariants, against a real Postgres --------------------------------------
#
# The assertions above read SQLAlchemy metadata, which proves what the mapping *declares*
# and nothing about what reached the database. The security and QA panels of section 1 both
# called that out: a partial index that silently failed to apply would leave the whole
# revocation story resting on nothing, with a green suite. These drive the constraints.


async def _stay(db_session, *, name: str):
    """A tenant with one property and one reservation, flushed and ready to reference."""
    tenant = TenantModel(name=name, billing_email=f"{name}@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(
        tenant_id=tenant.id,
        name=f"Property {name}",
        internal_code=f"CODE-{uuid.uuid4().hex[:8]}",
        pms_external_id=f"PMS-{uuid.uuid4().hex[:8]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()

    check_in = date(2026, 9, 1)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status="CONFIRMED",
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=2),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return tenant, reservation


@pytest.mark.asyncio
async def test_a_second_live_token_for_one_stay_is_refused(db_session) -> None:
    """R1.5, driven rather than declared. This is the invariant revocation rests on."""
    tenant, reservation = await _stay(db_session, name="live-token")

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant.id, reservation_id=reservation.id, token_hash="1" * 64
        )
    )
    await db_session.flush()

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant.id, reservation_id=reservation.id, token_hash="2" * 64
        )
    )
    with pytest.raises(IntegrityError, match="uq_guest_access_tokens_live_per_reservation"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_a_revoked_token_does_not_block_the_next_one(db_session) -> None:
    """The other half of R1.5, and why the index is partial rather than plain.

    Without this, the test above would also pass for an index that forbade re-issuing a
    token for a stay for ever — which would make `IssueGuestAccessTokenUseCase`'s
    revoke-and-create (D14) impossible.
    """
    tenant, reservation = await _stay(db_session, name="reissue")

    first = GuestAccessTokenModel(
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        token_hash="3" * 64,
        revoked_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )
    db_session.add(first)
    await db_session.flush()

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant.id, reservation_id=reservation.id, token_hash="4" * 64
        )
    )
    await db_session.flush()  # must not raise


@pytest.mark.asyncio
async def test_a_token_cannot_point_at_another_tenants_reservation(db_session) -> None:
    """R2.5, and the finding that produced the composite FK.

    Before it, Postgres accepted this row — proven by the tenancy panel of section 1 by
    inserting one. It matters more here than anywhere else in the schema because the
    authoriser resolves the tenant *from this row* on a session that is not yet marked
    (design D4), so the global filter is off at exactly the moment the mismatch would be
    read, and the request would be bound to the wrong tenant. Rule 3(c) of
    `steering/security.md`: a scoping failure here does not disclose data, it grants control.
    """
    tenant_a, _ = await _stay(db_session, name="mismatch-a")
    _, reservation_b = await _stay(db_session, name="mismatch-b")

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant_a.id, reservation_id=reservation_b.id, token_hash="5" * 64
        )
    )

    with pytest.raises(IntegrityError, match="fk_guest_access_tokens_reservation_within_tenant"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_the_token_hash_is_unique_across_two_different_tenants(db_session) -> None:
    """D2's global uniqueness, driven: two tenants cannot hold the same digest.

    Per-tenant uniqueness would be indistinguishable from this in a single-tenant test, and
    the authorising lookup — which has no tenant in hand — depends on the stronger one.
    """
    tenant_a, reservation_a = await _stay(db_session, name="global-a")
    _, reservation_b = await _stay(db_session, name="global-b")

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant_a.id, reservation_id=reservation_a.id, token_hash="6" * 64
        )
    )
    await db_session.flush()

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=reservation_b.tenant_id,
            reservation_id=reservation_b.id,
            token_hash="6" * 64,
        )
    )
    with pytest.raises(IntegrityError, match="ix_guest_access_tokens_token_hash"):
        await db_session.flush()
