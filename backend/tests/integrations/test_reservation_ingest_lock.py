"""Pure key and boundary tests for the reservation ingest lock (review finding 1).

Mirrors `tests/guests/test_guest_email_exclusion.py` exactly: that file proves
`PostgresGuestEmailExclusion` serializes concurrent writers racing on the same tenant/email via
a real Postgres advisory lock, and this reuses the same testing approach for the new lock that
serializes concurrent ingest writers racing on the same tenant/`external_pms_id`.
"""

import asyncio
import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.infrastructure.postgres_reservation_ingest_lock import (
    PostgresReservationIngestLock,
    reservation_ingest_lock_key,
)
from app.tenants.infrastructure.models import TenantModel

TENANT = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def test_lock_key_known_vector() -> None:
    assert (
        reservation_ingest_lock_key(
            uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), "PMS-1234"
        )
        == 4994179628455957107
    )


def test_lock_key_is_stable_and_tenant_scoped() -> None:
    external_id = "PMS-9999"
    assert reservation_ingest_lock_key(TENANT, external_id) == reservation_ingest_lock_key(
        TENANT, external_id
    )
    assert reservation_ingest_lock_key(TENANT, external_id) != reservation_ingest_lock_key(
        uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"), external_id
    )


def test_lock_key_is_external_id_scoped() -> None:
    """Two different PMS bookings for the same tenant must not collide on one key."""
    assert reservation_ingest_lock_key(TENANT, "PMS-1") != reservation_ingest_lock_key(
        TENANT, "PMS-2"
    )


@pytest.mark.asyncio
async def test_lock_observability_contains_no_booking_identity(caplog, db_session) -> None:
    tenant_id = uuid.uuid4()
    external_id = "PMS-PRIVATE-0001"

    with caplog.at_level(
        logging.DEBUG,
        logger="app.integrations.infrastructure.postgres_reservation_ingest_lock",
    ):
        await PostgresReservationIngestLock(db_session).acquire(tenant_id, external_id)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "reservation ingest lock acquired" in messages
    assert external_id not in messages
    assert str(tenant_id) not in messages


@pytest.mark.asyncio
async def test_acquire_is_a_no_op_for_a_blank_external_id(db_session) -> None:
    """No PMS id means no create-vs-update race to serialize (mirrors the email exclusion's
    no-op on an absent email)."""
    await PostgresReservationIngestLock(db_session).acquire(uuid.uuid4(), "")


@pytest.mark.asyncio
async def test_two_sessions_block_then_release_and_isolate_by_key(test_engine) -> None:
    """Same tenant/external_pms_id: the second acquire blocks until the first commits.

    Different external_pms_id, or a different tenant, must never block — proving the lock
    key is scoped narrowly enough to serialize only the SAME real-world PMS booking, not every
    concurrent ingest row.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        setup.add_all(
            [
                TenantModel(id=tenant_a, name="lock-tenant-a", billing_email="a@example.com"),
                TenantModel(id=tenant_b, name="lock-tenant-b", billing_email="b@example.com"),
            ]
        )
        await setup.commit()

    first = AsyncSession(test_engine, expire_on_commit=False)
    second = AsyncSession(test_engine, expire_on_commit=False)
    other_key = AsyncSession(test_engine, expire_on_commit=False)
    other_tenant = AsyncSession(test_engine, expire_on_commit=False)
    try:
        external_id = "PMS-RACE-0001"

        await PostgresReservationIngestLock(first).acquire(tenant_a, external_id)

        second_task = asyncio.create_task(
            PostgresReservationIngestLock(second).acquire(tenant_a, external_id)
        )
        await asyncio.sleep(0.1)
        assert not second_task.done()

        # A different external_pms_id for the same tenant is not blocked by the held lock.
        await asyncio.wait_for(
            PostgresReservationIngestLock(other_key).acquire(tenant_a, "PMS-OTHER-0002"),
            timeout=1,
        )
        await other_key.commit()

        # Nor is the same external_pms_id under a different tenant.
        await asyncio.wait_for(
            PostgresReservationIngestLock(other_tenant).acquire(tenant_b, external_id),
            timeout=1,
        )
        await other_tenant.commit()

        await first.commit()
        await asyncio.wait_for(second_task, timeout=1)
        await second.commit()
    finally:
        await first.close()
        await second.close()
        await other_key.close()
        await other_tenant.close()
