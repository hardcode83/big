"""Pure key and boundary tests for transactional guest email exclusion (R3)."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.guests.application.resolution import ManualGuestIdentityInput, ResolveOrCreateGuest
from app.guests.infrastructure.postgres_guest_email_exclusion import guest_email_lock_key
from app.guests.infrastructure.postgres_guest_email_exclusion import PostgresGuestEmailExclusion
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.tenants.infrastructure.models import TenantModel
from tests.guests.test_guest_resolution import FakeGuestEmailExclusion, FakeGuestRepository, NOW, TENANT


def test_lock_key_known_vector() -> None:
    assert guest_email_lock_key(
        uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), " Person@Example.COM "
    ) == -4957761588713872798


def test_lock_key_is_stable_and_tenant_scoped() -> None:
    email = "person@example.com"
    assert guest_email_lock_key(TENANT, email) == guest_email_lock_key(TENANT, email)
    assert guest_email_lock_key(TENANT, email) != guest_email_lock_key(
        uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), email
    )


@pytest.mark.asyncio
async def test_lock_observability_contains_no_guest_pii(caplog, db_session) -> None:
    tenant_id = uuid.uuid4()
    email = "private.person@example.com"

    with caplog.at_level(logging.DEBUG, logger="app.guests.infrastructure.postgres_guest_email_exclusion"):
        await PostgresGuestEmailExclusion(db_session).acquire(tenant_id, email)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "guest email exclusion acquired" in messages
    assert email not in messages
    assert str(tenant_id) not in messages


@pytest.mark.asyncio
async def test_resolver_locks_then_rechecks_before_add() -> None:
    repository = FakeGuestRepository()
    exclusion = FakeGuestEmailExclusion()

    await ResolveOrCreateGuest(repository, exclusion).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Person", email=" PERSON@EXAMPLE.COM "),
        now=NOW,
    )

    assert exclusion.acquired == [(TENANT, "person@example.com")]
    assert repository.email_lookups == [
        (TENANT, "person@example.com"),
        (TENANT, "person@example.com"),
    ]


@pytest.mark.asyncio
async def test_resolver_does_not_lock_absent_email() -> None:
    repository = FakeGuestRepository()
    exclusion = FakeGuestEmailExclusion()

    await ResolveOrCreateGuest(
        repository, exclusion
    ).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Person"),
        now=NOW,
    )

    assert exclusion.acquired == []
    assert repository.email_lookups == []


@pytest.mark.asyncio
async def test_two_sessions_block_then_reuse_and_isolate_tenants(test_engine) -> None:
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
    other_tenant = AsyncSession(test_engine, expire_on_commit=False)
    try:
        identity = ManualGuestIdentityInput(full_name="Same Person", email="same@example.com")

        first_task = asyncio.create_task(
            ResolveOrCreateGuest(
                SqlAlchemyGuestRepository(first), PostgresGuestEmailExclusion(first)
            ).execute(tenant_id=tenant_a, identity=identity, now=datetime.now(UTC))
        )
        first_guest_id = await first_task

        second_task = asyncio.create_task(
            ResolveOrCreateGuest(
                SqlAlchemyGuestRepository(second), PostgresGuestEmailExclusion(second)
            ).execute(tenant_id=tenant_a, identity=identity, now=datetime.now(UTC))
        )
        await asyncio.sleep(0.1)
        assert not second_task.done()

        different_tenant_guest_id = await asyncio.wait_for(
            ResolveOrCreateGuest(
                SqlAlchemyGuestRepository(other_tenant),
                PostgresGuestEmailExclusion(other_tenant),
            ).execute(tenant_id=tenant_b, identity=identity, now=datetime.now(UTC)),
            timeout=1,
        )
        await other_tenant.commit()
        await first.commit()
        assert await asyncio.wait_for(second_task, timeout=1) == first_guest_id
        assert different_tenant_guest_id != first_guest_id
    finally:
        await first.close()
        await second.close()
        await other_tenant.close()
