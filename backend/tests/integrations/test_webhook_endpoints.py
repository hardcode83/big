"""The `webhook_endpoints` table and its OWN isolation test (`reservations-webhooks` R2, D2, D3).

Its own, and not the module's generic one, for the reason rule 3(c) of `steering/security.md`
gives about credential tables and that applies here with a twist: a scoping failure in
`pms_credentials` grants write access to another client's PMS, and a scoping failure **here** lets
one client's webhooks be accepted and ingested as another client's reservations. Neither is a
disclosure; both are control.

There is a second reason this table deserves more than the generic test, and it is specific to
this change: `find_by_token_hash` is the one query in the module that runs **with no tenant at
all** (design D1), because the token is what resolves the tenant. A test suite that only exercised
scoped reads would never touch the method whose whole job is to be unscoped.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import SecretDecryptionError, decrypt, encrypt
from app.core.db import bind_session_to_tenant, tenant_scoped_classes
from app.core.tenancy import CrossTenantWriteError, TenantMarkedSessionError
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import WebhookEndpointAlreadyExistsError
from app.integrations.domain.webhook_auth import (
    generate_webhook_token,
    hash_webhook_token,
)
from app.integrations.infrastructure.models import WebhookEndpointModel
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
)

HEADER_NAME = "X-Beds24-Secret"


def _endpoint(
    tenant_id: uuid.UUID,
    *,
    token: str | None = None,
    secret: str = "s3cret",
    provider: PMSProvider = PMSProvider.BEDS24,
) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        token_hash=hash_webhook_token(token or generate_webhook_token()),
        header_name=HEADER_NAME,
        header_secret=encrypt(secret),
    )


# --- Storage and recovery (R2.1, R2.2) ---


@pytest.mark.asyncio
async def test_an_endpoint_is_stored_and_recovered_by_its_token(
    db_session, tenant_a
) -> None:
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    token = generate_webhook_token()
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id, token=token))
    await db_session.flush()

    found = await repository.find_by_token_hash(
        PMSProvider.BEDS24, hash_webhook_token(token)
    )

    assert found is not None
    assert found.tenant_id == tenant_a.id
    assert decrypt(found.header_secret) == "s3cret"


@pytest.mark.asyncio
async def test_find_by_token_hash_refuses_a_marked_session(db_session, tenant_a) -> None:
    """R6.2/R6.3: the precondition is a failure, not a paragraph.

    Asserting the raise and not the rows, deliberately: on a marked session the listener scopes
    even a single-column select, so "no endpoint came back" would be indistinguishable from an
    unknown token — and this route answers both the same way on purpose (R1.6), so a broken guard
    here would look exactly like the intended refusal.

    This read was the one outside the census: it spent two changes there while three prose sites
    claimed the census was the whole class. It is guarded and declared since
    `rule11-ownership-single-source`; this is the test its siblings already had.
    """
    token = generate_webhook_token()
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id, token=token))
    await db_session.flush()

    bind_session_to_tenant(db_session, tenant_a.id)

    with pytest.raises(TenantMarkedSessionError, match="find_by_token_hash"):
        await repository.find_by_token_hash(
            PMSProvider.BEDS24, hash_webhook_token(token)
        )


@pytest.mark.asyncio
async def test_the_stored_bytes_are_ciphertext_not_the_secret(
    db_session, tenant_a
) -> None:
    """R2.2. The column is named `_encrypted`; this is what makes the name true."""
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id, secret="pegame-en-el-panel"))
    await db_session.flush()

    stored = (
        await db_session.execute(
            text("SELECT header_secret_encrypted FROM webhook_endpoints WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()

    assert "pegame-en-el-panel" not in stored


@pytest.mark.asyncio
async def test_the_stored_token_is_a_hash_not_the_token(db_session, tenant_a) -> None:
    """D3: a dump of this table must not hand over the route."""
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    token = generate_webhook_token()
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id, token=token))
    await db_session.flush()

    stored = (
        await db_session.execute(
            text("SELECT token_hash FROM webhook_endpoints WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()

    assert stored != token
    assert token not in stored


@pytest.mark.asyncio
async def test_an_unknown_token_is_none_rather_than_an_error(db_session) -> None:
    """Absence is an answer. The receiving use case is what turns it into design D4's 404."""
    repository = SqlAlchemyWebhookEndpointRepository(db_session)

    found = await repository.find_by_token_hash(
        PMSProvider.BEDS24, hash_webhook_token(generate_webhook_token())
    )

    assert found is None


@pytest.mark.asyncio
async def test_a_token_does_not_authenticate_a_different_provider(
    db_session, tenant_a
) -> None:
    """`provider` is in the WHERE clause, not just in the route.

    Without it, a token minted for BEDS24 would authenticate a request claiming to be from
    CHANNEX, and `webhook_events.provider` would become a column the caller picks.
    """
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    token = generate_webhook_token()
    await repository.upsert(
        tenant_a.id, _endpoint(tenant_a.id, token=token, provider=PMSProvider.BEDS24)
    )
    await db_session.flush()

    assert (
        await repository.find_by_token_hash(PMSProvider.CHANNEX, hash_webhook_token(token))
    ) is None


# --- Rotation (R2.4, D3) ---


@pytest.mark.asyncio
async def test_rotation_replaces_both_secrets_in_place(db_session, tenant_a) -> None:
    """R2.4, and the "both together" half of D3.

    One row per (tenant, provider), so rotation must not leave a second row behind — that would
    be an old token that still authenticates, which is the opposite of invalidation.
    """
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    old_token = generate_webhook_token()
    await repository.upsert(
        tenant_a.id, _endpoint(tenant_a.id, token=old_token, secret="old")
    )
    await db_session.flush()

    new_token = generate_webhook_token()
    await repository.upsert(
        tenant_a.id, _endpoint(tenant_a.id, token=new_token, secret="new")
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            text("SELECT count(*) FROM webhook_endpoints WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()
    assert rows == 1

    assert (
        await repository.find_by_token_hash(
            PMSProvider.BEDS24, hash_webhook_token(new_token)
        )
    ) is not None


@pytest.mark.asyncio
async def test_the_old_token_stops_authenticating_after_rotation(
    db_session, tenant_a
) -> None:
    """R2.4 in the words the requirement uses: rotation SHALL invalidate the previous value.

    No grace window (D3) — the old material is gone the moment the transaction commits.
    """
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    old_token = generate_webhook_token()
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id, token=old_token))
    await db_session.flush()

    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id))
    await db_session.flush()

    assert (
        await repository.find_by_token_hash(
            PMSProvider.BEDS24, hash_webhook_token(old_token)
        )
    ) is None


# --- Tenant isolation, its own test for this table (rule 1, rule 3(c)) ---


def test_the_endpoints_table_is_inside_the_global_filter() -> None:
    """The premise the isolation tests below rest on, in the shape the repo already uses.

    If `webhook_endpoints` ever stopped being tenant-scoped, this says so — instead of the
    isolation tests quietly passing against a table the filter no longer covers.
    """
    assert WebhookEndpointModel in tenant_scoped_classes()


@pytest.mark.asyncio
async def test_a_tenant_cannot_write_an_endpoint_of_another(
    db_session, tenant_a, tenant_b
) -> None:
    repository = SqlAlchemyWebhookEndpointRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repository.upsert(tenant_a.id, _endpoint(tenant_b.id))


@pytest.mark.asyncio
async def test_a_tenant_cannot_read_an_endpoint_of_another_by_id(
    db_session, tenant_a, tenant_b
) -> None:
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    theirs = _endpoint(tenant_b.id)
    await repository.upsert(tenant_b.id, theirs)
    await db_session.flush()

    assert (await repository.get(tenant_a.id, theirs.id)) is None

    # Raw SQL on purpose: this proves the ROW is still there, so a bug that deleted it could not
    # pass by making the filtered read empty.
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM webhook_endpoints WHERE tenant_id = :t"),
            {"t": str(tenant_b.id)},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_two_tenants_can_each_have_an_endpoint_for_the_same_provider(
    db_session, tenant_a, tenant_b
) -> None:
    """The UNIQUE is on (tenant, provider), not on provider.

    Worth pinning: a unique constraint on `provider` alone would work perfectly with one tenant
    and make the product single-tenant on the second one.
    """
    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    await repository.upsert(tenant_a.id, _endpoint(tenant_a.id))
    await repository.upsert(tenant_b.id, _endpoint(tenant_b.id))
    await db_session.flush()

    count = (
        await db_session.execute(text("SELECT count(*) FROM webhook_endpoints"))
    ).scalar_one()
    assert count == 2


# --- The constraint, not the caller's read, is what refuses a duplicate ---


@pytest.mark.asyncio
async def test_an_insert_that_loses_the_unique_race_is_a_domain_refusal(
    test_engine, db_session, tenant_a
) -> None:
    """The check-then-act window `find_for` cannot close (QA panel of section 1).

    Two genuinely concurrent creations, because nothing weaker reproduces it: sequentially, the
    second caller's own `SELECT` sees the first row and takes the update branch, so the insert
    path is never entered. Only overlapping transactions put a caller in the losing state — its
    `SELECT` found nothing, and by the time it flushes the index is taken.

    What must come back is the domain's refusal, not `IntegrityError`: unhandled, the loser
    reaches the client as a `500` where the operation promises a `409`.
    """
    # The tenant has to be visible to the other two connections, and `db_session` only flushed it.
    await db_session.commit()

    # The overlap is forced, not hoped for. Left to `asyncio.gather`'s scheduling this test is a
    # coin toss: if the second caller's SELECT runs after the first one's COMMIT it sees the row,
    # takes the update branch and never reaches the index, so `failures` is empty and the assertion
    # below fails. That is not hypothetical — it happened in one of the two full runs of this
    # change's prototype. The per-test DDL that used to sit in `test_engine` made the overlap
    # overwhelmingly likely and hid the fragility; removing it exposed it.
    #
    # The barrier puts both callers past their SELECT and short of their flush, which is the only
    # state in which one of them can lose the index (design D5).
    both_have_read = asyncio.Barrier(2)

    class _WaitAfterTheFirstRead:
        """The session the repository sees: it stops once, right after `upsert`'s SELECT.

        Wrapping the session rather than the repository because `upsert` does not go through
        `find_for` — it inlines its own `execute`, so the seam is here.
        """

        def __init__(self, session: AsyncSession) -> None:
            self._session = session
            self._has_read = False

        def __getattr__(self, name: str):
            return getattr(self._session, name)

        async def execute(self, *args, **kwargs):
            result = await self._session.execute(*args, **kwargs)
            if not self._has_read:
                self._has_read = True
                # Bounded on purpose. A barrier of two parties waits for ever if only one
                # arrives, and today both always do — `upsert`'s cross-tenant guard is the
                # one early return before the SELECT, and both callers pass the same tenant.
                # But "today" is the whole problem: with no bound, an edit that ever made
                # that return asymmetric would turn this into a CI hang until the job's
                # 20-minute timeout, and a hang reads as broken infrastructure rather than
                # as the broken test it would be. The timeout makes it a red instead.
                #
                # Note for whoever meets that red: cancelling a `Barrier.wait()` does NOT
                # break the barrier for the other party — CPython only decrements the count
                # — so the survivor is saved by its own timeout, not by a `BrokenBarrierError`.
                # Both callers therefore fail, and the assertion below reports `2 != 1`
                # rather than naming a timeout. The cause is asymmetric arrival, not domain
                # logic.
                await asyncio.wait_for(both_have_read.wait(), timeout=30)
            return result

    async def create(session: AsyncSession) -> None:
        await SqlAlchemyWebhookEndpointRepository(_WaitAfterTheFirstRead(session)).upsert(
            tenant_a.id, _endpoint(tenant_a.id)
        )
        await session.commit()

    async with AsyncSession(test_engine) as first, AsyncSession(test_engine) as second:
        outcomes = await asyncio.gather(
            create(first), create(second), return_exceptions=True
        )

    failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(failures) == 1, "exactly one of the two creations must win the index"
    assert isinstance(failures[0], WebhookEndpointAlreadyExistsError)

    surviving = (
        await db_session.execute(
            text("SELECT count(*) FROM webhook_endpoints WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()
    assert surviving == 1


# --- A stored row that cannot become an entity (D4's indistinguishability) ---


@pytest.mark.asyncio
async def test_a_plaintext_secret_in_the_column_is_refused_on_read(
    db_session, tenant_a
) -> None:
    """The hand-written-SQL row, which is the path an operator takes when nothing else works.

    It must not escape as a bare `ValueError`: on this endpoint that would be a `500` to an
    anonymous caller, which tells them the token exists and its row is broken — the oracle design
    D4 exists to close. `SecretDecryptionError` is the domain vocabulary the caller already
    handles, exactly as `_to_credential` decided for `pms_credentials`.
    """
    token = generate_webhook_token()
    await db_session.execute(
        text(
            "INSERT INTO webhook_endpoints "
            "(id, tenant_id, provider, token_hash, header_name, header_secret_encrypted) "
            "VALUES (:id, :t, 'BEDS24', :h, :n, :s)"
        ),
        {
            "id": str(uuid.uuid4()),
            "t": str(tenant_a.id),
            "h": hash_webhook_token(token),
            "n": HEADER_NAME,
            "s": "not-ciphertext-at-all",
        },
    )
    await db_session.flush()

    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    with pytest.raises(SecretDecryptionError):
        await repository.find_by_token_hash(PMSProvider.BEDS24, hash_webhook_token(token))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "value"),
    [
        # Neither is prevented by a column definition: `token_hash` is a `String(64)`, so a
        # 64-character non-digest fits, and `header_name` has no non-blank constraint. The entity
        # is where both are refused, and this is what proves the repository does not route around
        # it — the entity's guards are only worth having if every path into it applies them.
        ("token_hash", "z" * 64),
        ("header_name", "   "),
    ],
)
async def test_a_row_the_entity_refuses_is_reported_as_a_broken_row(
    db_session, tenant_a, column, value
) -> None:
    """`_to_endpoint` translates `WebhookEndpoint.__post_init__` too, not only `EncryptedSecret`.

    Both causes must arrive as `SecretDecryptionError`, for the reason the sibling test above
    gives: on the anonymous receiving path an unhandled `ValueError` is a `500`, and a `500` tells
    the caller that this route token exists and its row is broken — the oracle design D4 closes.
    """
    # A digest we can still search by, so the lookup reaches the row even in the token_hash case.
    stored_hash = value if column == "token_hash" else hash_webhook_token(generate_webhook_token())
    await db_session.execute(
        text(
            "INSERT INTO webhook_endpoints "
            "(id, tenant_id, provider, token_hash, header_name, header_secret_encrypted) "
            "VALUES (:id, :t, 'BEDS24', :h, :n, :s)"
        ),
        {
            "id": str(uuid.uuid4()),
            "t": str(tenant_a.id),
            "h": stored_hash,
            "n": value if column == "header_name" else HEADER_NAME,
            "s": encrypt("fine").ciphertext,
        },
    )
    await db_session.flush()

    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    with pytest.raises(SecretDecryptionError):
        await repository.find_by_token_hash(PMSProvider.BEDS24, stored_hash)
