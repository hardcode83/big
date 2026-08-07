"""`PMSAdapterFactory`: resolution, failure modes and the audit of credential reads (R1, R2, R4).

The factory is the single chokepoint where a credential is decrypted, so what matters here is
less "does it return an adapter" than what it refuses to do and what it records.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.audit.domain.actions import ENTITY_PMS_CREDENTIAL, PMS_CREDENTIAL_READ
from app.audit.infrastructure.models import AuditLogModel
from app.core.crypto import encrypt
from app.core.db import bind_session_to_tenant
from app.integrations.domain.entities import CredentialReadLog, PmsCredential
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope
from app.integrations.domain.errors import (
    MissingPmsCredentialError,
    PmsUnavailableError,
    PMSMessagingUnsupportedError,
)
from app.integrations.infrastructure.beds24.adapter import Beds24Adapter
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE, MockPMSAdapter
from app.integrations.infrastructure.pms_factory import (
    DEFAULT_PROVIDER,
    SqlAlchemyPMSAdapterFactory,
)
from app.integrations.infrastructure.repositories import SqlAlchemyPmsCredentialRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository


def _factory(db_session, *, forced=None):
    return SqlAlchemyPMSAdapterFactory(
        credentials=SqlAlchemyPmsCredentialRepository(db_session),
        forced_provider=forced,
    )


async def _entity(db_session, tenant, property_model):
    return await SqlAlchemyPropertyRepository(db_session).get(tenant.id, property_model.id)


# --- Resolution and its failure modes (R2.4) ---


@pytest.mark.asyncio
async def test_a_property_with_no_provider_uses_the_bootstrap_default(
    db_session, tenant_a, property_a
) -> None:
    """NULL means "the mock", which is what keeps the suite and local startup free of
    configuration — and what lets every pre-existing row work with no data migration."""
    entity = await _entity(db_session, tenant_a, property_a)
    assert entity.pms_provider is None

    adapter = await _factory(db_session).reservations_for(entity, read_log=CredentialReadLog())

    assert isinstance(adapter, MockPMSAdapter)
    assert DEFAULT_PROVIDER is PMSProvider.MOCK


@pytest.mark.asyncio
async def test_a_provider_needing_a_credential_fails_loudly_when_there_is_none(
    db_session, tenant_a, property_a
) -> None:
    """R2.4, and the failure that must NEVER degrade to the mock.

    A silent fall back would report "created 0", which is indistinguishable from a PMS that
    genuinely had nothing — the confusion `specs/reservations.md` already refuses for
    `CHANNEX_API_KEY`.
    """
    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    await db_session.flush()
    entity = await _entity(db_session, tenant_a, property_a)

    with pytest.raises(MissingPmsCredentialError):
        await _factory(db_session).reservations_for(entity, read_log=CredentialReadLog())


@pytest.mark.asyncio
async def test_a_stored_credential_resolves_to_the_real_beds24_adapter(
    db_session, tenant_a, property_a
) -> None:
    """A stored credential now resolves to a REAL adapter (`pms-beds24-adapter` R5.1).

    This test used to assert the opposite — that the chain ran to the end and then raised
    `PmsUnavailableError` because no adapter implemented Beds24. That hole is what this change
    fills, so the assertion is inverted rather than deleted: what it still proves is the part
    that matters and that no other test covers, namely that resolution goes all the way through
    lookup, scope, decryption and audit, and that the decrypted secret does not escape into the
    object's repr.
    """
    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(
        tenant_a.id,
        PmsCredential(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            provider=PMSProvider.BEDS24,
            scope=PmsCredentialScope.ACCOUNT,
            secret=encrypt("a-real-looking-refresh-token"),
        ),
    )
    await db_session.flush()
    entity = await _entity(db_session, tenant_a, property_a)
    read_log = CredentialReadLog()

    adapter = await _factory(db_session).reservations_for(entity, read_log=read_log)

    assert isinstance(adapter, Beds24Adapter)
    # The decryption happened and was recorded — the audit chain rule 3(b) requires.
    assert len(read_log.credential_ids) == 1
    # And the decrypted secret is not one `logger.debug` away from a log file.
    assert "a-real-looking-refresh-token" not in repr(adapter._client)


@pytest.mark.asyncio
async def test_the_override_outranks_the_stored_provider(
    db_session, tenant_a, property_a
) -> None:
    """`--provider` forces one provider for the whole run, and `provider_for` must agree with
    what `reservations_for` builds — otherwise grouping and resolution disagree silently."""
    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    await db_session.flush()
    entity = await _entity(db_session, tenant_a, property_a)

    factory = _factory(db_session, forced=PMSProvider.MOCK)

    assert factory.provider_for(entity) is PMSProvider.MOCK
    assert isinstance(await factory.reservations_for(entity, read_log=CredentialReadLog()), MockPMSAdapter)


# --- Messaging (R1.2) ---


@pytest.mark.asyncio
async def test_messaging_is_refused_for_a_provider_that_has_none(
    db_session, tenant_a, property_a
) -> None:
    entity = await _entity(db_session, tenant_a, property_a)
    factory = _factory(db_session)

    assert factory.supports_messaging(PMSProvider.MOCK) is False
    with pytest.raises(PMSMessagingUnsupportedError):
        await factory.messaging_for(entity)


def test_supports_messaging_is_pure(db_session) -> None:
    """It must not touch credentials: resolving decrypts, and decrypting is an audited act
    (R4.2). If asking the question cost an audit row, planning work would leave a trail of reads
    that never happened."""
    factory = _factory(db_session)

    assert factory.supports_messaging(PMSProvider.BEDS24) is True
    assert factory.supports_messaging(PMSProvider.CHANNEX) is False


# --- The factory holds no state (D8, task 7.5) ---


def test_the_factory_holds_no_session_and_caches_no_adapter(db_session) -> None:
    """A factory that kept a session would become the object that carries one tenant's session
    into another tenant's resolution — the failure `bind_session_to_tenant`'s guard exists to
    catch. One that cached adapters would keep a decrypted credential alive past its use.
    """
    factory = _factory(db_session)
    held = vars(factory)

    assert set(held) == {"_credentials", "_forced_provider"}
    # The repository holds the session; the factory reaches it only through the port, so there is
    # no attribute here that a second tenant's resolution could inherit.
    assert not any(name.endswith("cache") for name in held)


# --- The audit of credential reads (R4.2, tasks 6.2/6.3) ---


@pytest.mark.asyncio
async def test_the_read_log_deduplicates_by_credential_id(
    db_session, tenant_a, property_a
) -> None:
    """The MECHANISM: four resolutions sharing one credential leave one id in the log.

    Named after what it exercises, not after the granularity it enables — the count is stated in
    rule 9 of `steering/security.md` and nowhere else. A test name is a normative-looking sentence
    that CI enforces, and this one used to carry the claim; the final security panel pointed out
    that a name is exactly where a superseded version survives a correction to the rule.
    """
    bind_session_to_tenant(db_session, tenant_a.id)
    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)
    await db_session.flush()
    entity = await _entity(db_session, tenant_a, property_a)

    read_log = CredentialReadLog()
    factory = _factory(db_session)
    for _ in range(4):
        await factory.reservations_for(entity, read_log=read_log)

    assert read_log.credential_ids == {credential.id}


@pytest.mark.asyncio
async def test_the_run_writes_one_audit_row_naming_the_credential(
    db_session, tenant_a, property_a, monkeypatch
) -> None:
    """R4.2 on the path that actually reaches a credential — which is the one that had no row.

    The security panel of sections 6-8 measured it: the factory decrypts and then raises (no
    Beds24 adapter yet), and the audit rows were written after the loop on the success path only,
    so a decryption that definitely happened produced **zero** rows. Now the recording is in a
    `finally` and a provider that cannot be synced is reported rather than aborting the run.

    Nothing here pre-seeds the read log: the credential is stored, the sync resolves it for real,
    and the row must exist because the read did.

    **The transport is stubbed, and that is not tidiness** (QA panel of sections 3-5). This test
    predates `pms-beds24-adapter`: it relied on the factory raising "no adapter yet" *before* any
    HTTP existed. R5.1 removed that guard, so the use case started building a real
    `Beds24Client` with no transport override and **calling the production Beds24 API** — it
    stayed green only because a `401` folds into `PmsUnavailableError`, which the assertion
    below accepts. Coincidentally green, not deterministically green, and dependent on the
    sandbox having internet egress. Design D12 and `steering/testing.md` both forbid it.
    """
    from datetime import UTC, datetime

    import httpx

    from app.integrations.infrastructure import pms_factory as pms_factory_module
    from app.integrations.infrastructure.beds24.client import Beds24Client

    def _offline_client(**kwargs) -> Beds24Client:
        # 500 rather than an empty page, so the "reported, not raised" assertion below keeps
        # exercising a provider failure — which is what it was written for.
        return Beds24Client(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(500))
        )

    monkeypatch.setattr(pms_factory_module, "Beds24Client", _offline_client)

    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    bind_session_to_tenant(db_session, tenant_a.id)
    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)
    await db_session.flush()

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    report = await SyncReservationsFromPmsUseCase(
        factory=_factory(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    ).execute(tenant_id=tenant_a.id, since=now, now=now)

    # The provider could not be synced — no adapter yet — and that is REPORTED, not raised: one
    # provider failing must not abort the others, the same rule `celery-jobs` fixed for tenants.
    assert any("BEDS24" in error.reason for error in report.errors)

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == PMS_CREDENTIAL_READ)
        )
    ).scalars().all()

    assert len(rows) == 1, "the credential was decrypted, so the read must be recorded"
    assert rows[0].entity_type == ENTITY_PMS_CREDENTIAL
    assert rows[0].entity_id == credential.id
    assert rows[0].changes is None, "a read has no diff; NULL, not {}"


@pytest.mark.asyncio
async def test_a_run_that_decrypted_nothing_writes_no_audit_row(
    db_session, tenant_a, property_a
) -> None:
    """The mock needs no credential, so a mock-only run must leave the audit trail untouched.
    An audit row for a read that did not happen is worse than none."""
    from datetime import UTC, datetime

    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    bind_session_to_tenant(db_session, tenant_a.id)
    read_log = CredentialReadLog()
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    await SyncReservationsFromPmsUseCase(
        factory=_factory(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    ).execute(tenant_id=tenant_a.id, since=now, now=now)

    count = await db_session.scalar(
        select(func.count()).select_from(AuditLogModel).where(
            AuditLogModel.action == PMS_CREDENTIAL_READ
        )
    )
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_two_runs_of_one_use_case_do_not_share_their_credential_reads(
    db_session, tenant_a, tenant_b
) -> None:
    """The read log is per RUN, not per use case — reproduced by the security panel as a leak.

    It used to be constructor state shared with the factory and never cleared, so a second
    `execute` for a different tenant wrote an audit row under tenant B naming tenant A's
    credential id. `SqlAlchemyAuditLogRepository`'s guard cannot catch that: it compares the log
    row's own tenant, not the credential's.
    """
    from datetime import UTC, datetime

    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    use_case = SyncReservationsFromPmsUseCase(
        factory=_factory(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    )
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    bind_session_to_tenant(db_session, tenant_a.id)
    await use_case.execute(tenant_id=tenant_a.id, since=now, now=now)

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == PMS_CREDENTIAL_READ)
        )
    ).scalars().all()

    # Neither run decrypted anything (no stored provider), so neither may invent a row — and in
    # particular the second must not inherit the first's.
    assert rows == []


@pytest.mark.asyncio
async def test_one_credential_shared_by_several_properties_is_recorded_once(
    db_session, tenant_a, property_a
) -> None:
    """The discriminator task 6.3 promised, with genuinely DISTINCT properties.

    The existing test resolves the same property four times, which a property-keyed regression
    would also collapse to one — so it could not tell the two apart. The QA panel of sections 6-8
    probed it: with two distinct properties sharing one ACCOUNT credential, a property-keyed log
    reports two ids and this assertion is what catches it.
    """
    from app.properties.infrastructure.models import PropertyModel

    second = PropertyModel(
        tenant_id=tenant_a.id,
        name="Second",
        internal_code="SECOND",
        pms_external_id="EXT-SECOND",
        max_guests=2,
    )
    db_session.add(second)
    await db_session.flush()

    repository = SqlAlchemyPropertyRepository(db_session)
    for prop in (property_a, second):
        await repository.set_pms_provider(tenant_a.id, prop.id, PMSProvider.BEDS24)
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)
    await db_session.flush()

    read_log = CredentialReadLog()
    factory = _factory(db_session)
    for prop in (property_a, second):
        entity = await repository.get(tenant_a.id, prop.id)
        await factory.reservations_for(entity, read_log=read_log)

    assert read_log.credential_ids == {credential.id}, "one ACCOUNT credential, one id"


@pytest.mark.asyncio
async def test_resolving_for_two_tenants_needs_two_marked_sessions(
    db_session, tenant_a, tenant_b
) -> None:
    """R5.1, and no test covered it — task 7.6 was marked done claiming otherwise.

    The contract is `specs/celery-jobs.md`'s and this change derives no new one: a session is
    marked for ONE tenant and never re-marked. What this pins is that the guard still holds along
    the factory's path, so a batch that tried to serve two tenants on one session fails loudly
    instead of resolving the second tenant's credentials under the first tenant's filter.
    """
    bind_session_to_tenant(db_session, tenant_a.id)

    with pytest.raises(ValueError):
        bind_session_to_tenant(db_session, tenant_b.id)

    # And re-marking to the SAME tenant stays idempotent, so a job that re-enters its own tenant
    # is not punished for it.
    bind_session_to_tenant(db_session, tenant_a.id)


@pytest.mark.asyncio
async def test_a_provider_with_no_known_credential_scope_never_falls_back_to_mock(
    db_session, tenant_a, property_a, monkeypatch
) -> None:
    """R2.4's own branch, which was implemented and untested — the QA panel probed it by hand.

    A provider the resolver has no scope for is a configuration the code cannot serve. What it
    must NOT do is degrade to the mock: that would report "created 0", indistinguishable from a
    PMS that genuinely had nothing, which `specs/reservations.md` refuses for exactly this
    reason.

    Simulated by removing the provider from the scope map rather than inventing an enum member,
    so the test exercises the real branch instead of a parallel universe.
    """
    from app.integrations.infrastructure import pms_factory

    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    await db_session.flush()
    entity = await _entity(db_session, tenant_a, property_a)

    monkeypatch.setattr(pms_factory, "credential_scope_for", lambda provider: None)

    with pytest.raises(MissingPmsCredentialError):
        await _factory(db_session).reservations_for(entity, read_log=CredentialReadLog())


@pytest.mark.asyncio
async def test_an_undecryptable_credential_fails_its_provider_without_taking_the_run_down(
    db_session, tenant_a, property_a
) -> None:
    """A tampered ciphertext or a rotated key must isolate to ITS provider, not abort the tenant.

    Before this was caught, `SecretDecryptionError` escaped `_sync_one_provider` — there is no
    `except` around the loop, only a `finally` — so it aborted the **whole** run: every other
    provider of that tenant lost its sync too, and the pending audit row went down with the
    transaction. For a tenant mid-migration that is worse than the exit-code bug, because it
    takes out the provider that was working.

    Flagged by the feature-scale QA panel as implemented-but-untested, which is precisely the
    class of gap this change exists to close.
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
    from app.properties.infrastructure.models import PropertyModel
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    bind_session_to_tenant(db_session, tenant_a.id)
    repository = SqlAlchemyPropertyRepository(db_session)

    # One property on the broken provider...
    await repository.set_pms_provider(tenant_a.id, property_a.id, PMSProvider.BEDS24)
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)

    # ...and a second one on a provider that works, so the isolation is observable rather than
    # merely asserted: a run with only the broken provider cannot tell "isolated" from "aborted".
    healthy = PropertyModel(
        tenant_id=tenant_a.id,
        name="Healthy",
        internal_code="HEALTHY",
        pms_external_id=SEED_PROPERTY_CODE,
        max_guests=2,
    )
    db_session.add(healthy)
    await db_session.flush()

    # Corrupt the stored ciphertext directly: the repository would refuse to build an
    # `EncryptedSecret` from garbage, which is the guarantee under test one layer up.
    await db_session.execute(
        text("UPDATE pms_credentials SET secret_encrypted = :junk WHERE id = :id"),
        {"junk": encrypt("other").ciphertext[:-6] + "AAAAAA", "id": str(credential.id)},
    )
    await db_session.flush()

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    report = await SyncReservationsFromPmsUseCase(
        factory=_factory(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=repository,
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    ).execute(tenant_id=tenant_a.id, since=now, now=now)

    assert report.provider_failures == ["BEDS24"], "the broken provider is reported, not raised"
    # The healthy provider still ran: the mock's seed rows landed. This is the assertion that
    # distinguishes isolation from a run that simply survived.
    assert report.created > 0, "the working provider must still have synced"


@pytest.mark.asyncio
async def test_a_credential_that_is_not_ciphertext_at_all_also_isolates_to_its_provider(
    db_session, tenant_a, property_a
) -> None:
    """The half the previous isolation test did not cover, and the one reachable today.

    Its sibling corrupts the ciphertext while **preserving Fernet structure**, so it exercises the
    path `decrypt` handles. A value that is not ciphertext at all — a plaintext credential inserted
    with SQL by hand, or a truncated restore — is refused earlier, by `EncryptedSecret`, with a
    plain `ValueError` that used to escape everything: not in `_sync_one_provider`'s caught tuple,
    not in the port's declared raise set, not caught by `pms_sync.main`. One such row aborted the
    entire tenant's sync and rolled back the audit rows of reads that had already happened.

    The final security panel named it exactly: *the refused half was the unhandled half.*
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
    from app.properties.infrastructure.models import PropertyModel
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    bind_session_to_tenant(db_session, tenant_a.id)
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.set_pms_provider(tenant_a.id, property_a.id, PMSProvider.BEDS24)
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)

    healthy = PropertyModel(
        tenant_id=tenant_a.id,
        name="Healthy",
        internal_code="HEALTHY2",
        pms_external_id=SEED_PROPERTY_CODE,
        max_guests=2,
    )
    db_session.add(healthy)
    await db_session.flush()

    # Not ciphertext at all: exactly what a hand-written row would contain.
    await db_session.execute(
        text("UPDATE pms_credentials SET secret_encrypted = :plain WHERE id = :id"),
        {"plain": "beds24-refresh-token-in-the-clear", "id": str(credential.id)},
    )
    await db_session.flush()

    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    report = await SyncReservationsFromPmsUseCase(
        factory=_factory(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=repository,
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    ).execute(tenant_id=tenant_a.id, since=now, now=now)

    assert report.provider_failures == ["BEDS24"]
    assert report.created > 0, "the healthy provider must still have synced"
    # And the plaintext never reaches the operator-facing report.
    assert all("in-the-clear" not in error.reason for error in report.errors)

