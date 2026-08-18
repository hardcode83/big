"""The demo seed of PRD §27 (`seed-data-demo` R1-R5).

In `tests/cli/` rather than beside a domain, and that is a deliberate departure from
`steering/testing.md`'s "tests junto al dominio que cubren" (design, "Ubicación de los tests"):
the seed belongs to no single domain, it crosses five. `test_bootstrap.py` lives in
`tests/auth/` because bootstrap really is an auth concern.
"""

import ast
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.repositories import UserFilters
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningPhotoRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineFilters
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader

from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.value_objects import parse_template_content
from app.integrations.infrastructure.storage import ConfiguredFileStorageFactory
from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningChecklistTemplateModel,
    CleaningPhotoModel,
    CleaningTaskModel,
)
from app.guests.infrastructure.models import GuestModel
from app.integrations.application.ingest import IngestReport
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.properties.infrastructure.models import (
    PropertyModel,
    PropertyStateTransitionModel,
)
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel

from app.cli import seed_demo
from app.integrations.domain.storage import MAGIC_BYTES_LENGTH, detect_image_type
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
)
from app.maintenance.domain.value_objects import IncidentClassification
from app.maintenance.infrastructure.classifier import RuleBasedIncidentClassifier
from app.maintenance.domain.repositories import IncidentFilters
from app.maintenance.infrastructure.models import IncidentModel
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentReader
from app.notifications.infrastructure.models import NotificationLogModel
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel
from app.audit.domain import actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.cli.seed_demo import (
    SeedConfigurationError,
    SeedConflictError,
    SeedPreconditionError,
    build_plan,
)
from app.cli.seed_demo import apply_plan as _apply_plan
from app.core.config import settings
from app.core.db import TENANT_ID_SESSION_KEY
from tests.auth.conftest import insert_tenant, insert_user
from tests.cli.conftest import BOOTSTRAPPED_TENANT_NAME

async def apply_plan(session, plan, hasher, **kwargs):
    """One call models one `make seed-demo` PROCESS, which always gets a fresh session.

    `apply_plan` resolves the tenant by name through `find_by_email_globally` BEFORE it binds,
    and `require_unmarked_session` refuses that lookup on a session something already bound.
    Production cannot reach the refusal — every run is a new process with a new session — but
    the suite reuses one `db_session` for a whole test, so the idempotency tests, which run the
    seed twice on purpose, would meet the marker the first run left behind.

    Clearing it here is what makes the second call a second *run* rather than a second call on
    a session halfway through the first. Everything else is left alone, so the rows the first
    run wrote are exactly the state the second one has to find and leave untouched, which is
    what those tests are about.
    """
    session.info.pop(TENANT_ID_SESSION_KEY, None)
    return await _apply_plan(session, plan, hasher, **kwargs)


COMPLETE_ENV = {
    "BOOTSTRAP_TENANT_NAME": BOOTSTRAPPED_TENANT_NAME,
    "SEED_CLEANER_NAME": "Cleaner Person",
    "SEED_CLEANER_EMAIL": "cleaner@example.com",
    "SEED_CLEANER_PASSWORD": "cleaner-password-for-tests",
    "SEED_TECHNICIAN_NAME": "Technician Person",
    "SEED_TECHNICIAN_EMAIL": "tech@example.com",
    "SEED_TECHNICIAN_PASSWORD": "technician-password-for-tests",
}


@pytest.fixture
def complete_env(monkeypatch: pytest.MonkeyPatch):
    for name, value in COMPLETE_ENV.items():
        monkeypatch.setattr(settings, name.lower(), value)
    return COMPLETE_ENV


# --- Configuration, checked before any transaction (R1.5, R3.3, D11) -------------------


@pytest.mark.parametrize("missing", sorted(COMPLETE_ENV))
def test_a_missing_variable_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch, complete_env, missing: str
) -> None:
    # No database in this test on purpose: R1.5 is about the check happening BEFORE a
    # transaction exists, and `build_plan` is where that property lives.
    monkeypatch.setattr(settings, missing.lower(), "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert missing in str(excinfo.value)


def test_a_whitespace_only_variable_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_password", "   ")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert "SEED_CLEANER_PASSWORD" in str(excinfo.value)


def test_every_missing_variable_is_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in COMPLETE_ENV:
        monkeypatch.setattr(settings, name.lower(), "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    for name in COMPLETE_ENV:
        assert name in str(excinfo.value)


def test_the_error_never_echoes_a_password(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_email", "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert COMPLETE_ENV["SEED_CLEANER_PASSWORD"] not in str(excinfo.value)
    assert COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"] not in str(excinfo.value)


def test_two_accounts_may_not_share_one_address(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    """R1.4, found by the section 2-3 security panel.

    Not a nicety about tidy configuration: keyed by address, the two conflict lookups of
    `apply_plan` collapse into one entry that answers `None` for both accounts, the loop
    inserts twice, and the second insert dies inside `uq_users_lower_email`. A SQLAlchemy
    `IntegrityError` stringifies its statement *with* its parameters — one of which is a
    bcrypt hash. Refusing in `build_plan` means the flush never happens.
    """
    monkeypatch.setattr(settings, "seed_technician_email", COMPLETE_ENV["SEED_CLEANER_EMAIL"])

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    message = str(excinfo.value)
    assert "SEED_CLEANER_EMAIL" in message and "SEED_TECHNICIAN_EMAIL" in message
    # The address belongs to a person; naming the two variables is what fixes it.
    assert COMPLETE_ENV["SEED_CLEANER_EMAIL"] not in message


def test_two_addresses_differing_only_in_case_are_the_same_address(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    # `uq_users_lower_email` is built on `lower(email)`, so the comparison has to be too.
    monkeypatch.setattr(settings, "seed_technician_email", "  CLEANER@Example.COM ")

    with pytest.raises(SeedConfigurationError):
        build_plan()


def test_the_plan_carries_the_two_operational_roles(complete_env) -> None:
    # Two and not four: the owner and the manager are whoever `make bootstrap` created,
    # resolved by role rather than re-declared here (design D4).
    plan = build_plan()

    assert tuple(account.role for account in plan.accounts) == (
        UserRole.CLEANER,
        UserRole.TECHNICIAN,
    )


def test_the_plan_normalises_both_addresses(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_email", "  Cleaner@EXAMPLE.com ")

    plan = build_plan()

    assert plan.accounts[0].email == "cleaner@example.com"


def test_an_unexpected_failure_prints_its_class_and_never_its_parameters(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """R1.4, and the second half of the same security finding as above.

    `StatementError.__str__` appends `[SQL: ...] [parameters: (...)]`, and this command's
    parameters are a bcrypt hash and two people's addresses. Stood up with a real
    `IntegrityError` rather than a stand-in, because what is under test is precisely how
    SQLAlchemy renders itself.
    """
    leak = "$2b$04$averyrealisticlookingbcrypthashvalue"
    error = IntegrityError(
        f"INSERT INTO users (password_hash) VALUES ('{leak}')", {"password_hash": leak}, Exception()
    )

    async def _explode() -> dict[str, int]:
        raise error

    monkeypatch.setattr(seed_demo, "run", _explode)

    assert seed_demo.main() == 2

    captured = capsys.readouterr()
    assert leak in str(error), "the guard is pointless if SQLAlchemy stopped embedding parameters"
    assert leak not in captured.err
    assert leak not in captured.out
    assert "IntegrityError" in captured.err


def test_a_configuration_refusal_exits_one_and_carries_its_own_remedy(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The exit-1 half of R6.1, and of every other `SeedConfigurationError` before it.

    Driven through `main()` rather than through `apply_plan`, because the exit code is
    `main()`'s and nothing else asserted it: the whole table of codes (1 for configuration,
    precondition and conflict; 2 for ingest and unexpected) was pinned only on its 2s. The
    message a person reads is asserted against the real database in
    `test_a_tenant_whose_timezone_cannot_be_resolved_is_refused_before_any_write`; what is
    driven here is the mapping.

    Two conditions and not one, because since R6.1 they differ in remedy: one is a variable
    in `.env`, the other a column of the database, and the handler no longer appends a
    blanket "fill them in your .env" to both.
    """
    for message, misdirection in (
        ("tenants.timezone is not a resolvable time zone: 'Not/AZone'.", ".env"),
        ("Missing required environment variables: SEED_CLEANER_NAME. Fill them in your .env", None),
        (
            "This tenant stores files in S3 and the demo cleaning uploads six photos, but "
            "this is not configured (values not echoed): S3_BUCKET.",
            None,
        ),
    ):

        async def _refuse(message: str = message) -> dict[str, int]:
            raise SeedConfigurationError(message)

        monkeypatch.setattr(seed_demo, "run", _refuse)

        assert seed_demo.main() == 1

        err = capsys.readouterr().err
        assert message in err
        if misdirection is not None:
            assert misdirection not in err, "a database column is not fixed in the .env file"


def test_an_ingest_failure_reaches_the_console_with_its_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The `SeedIngestError` branch has to stay AHEAD of the catch-all (D11).

    Both branches exit 2, so a reorder would be invisible to a test that only checked the
    code — and `SeedIngestError` subclasses `Exception`, so moving it below `except
    Exception` silently disables it and the operator loses the one detail they can act on.
    What pins the order is asserting the REASON survives.

    Safe to print, unlike the catch-all's exception: every reason `ReservationIngestor`
    produces is a fixed sentence, a field name, or the repr of one of this module's own
    literal DTO constants — no `SEED_*` value ever reaches the ingestor.
    """

    async def _explode() -> dict[str, int]:
        raise seed_demo.SeedIngestError(
            "The demo reservations could not be ingested: Unknown property 'REDES11'"
        )

    monkeypatch.setattr(seed_demo, "run", _explode)

    assert seed_demo.main() == 2

    err = capsys.readouterr().err
    assert "Unknown property 'REDES11'" in err
    assert "details withheld" not in err, "this must not fall through to the catch-all"


@pytest.mark.asyncio
async def test_an_ingest_that_skipped_rows_without_rejecting_any_still_fails_loudly(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6.3: the branch that reports the counts when there is no `RowError` to quote.

    `skipped` can be non-zero with nothing in `errors` — the ingestor's "known and unchanged"
    case — and joining an empty `errors` used to produce a refusal that ended in a colon and
    said nothing. The pre-filter of `_seed_ota_reservations` keeps that unreachable in
    practice, which is why it takes a stubbed `ingest` to reach it, and why it went untested.

    The exception class already reaches the console with its detail ahead of the catch-all
    (the test above); what this one adds is that the detail exists at all when `errors` is
    empty, and that it names the counts instead of trailing off after a colon.
    """

    async def _skipped_without_errors(self, **kwargs):
        return IngestReport(created=0, updated=0, skipped=1)

    monkeypatch.setattr(seed_demo.ReservationIngestor, "ingest", _skipped_without_errors)

    with pytest.raises(seed_demo.SeedIngestError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    message = str(excinfo.value)
    assert "1 were skipped" in message
    assert not message.rstrip().endswith(":"), "a loud failure that names no reason states counts"


# --- The dataset constants of PRD §27 (R1.1, R3.2, D6, D10) ---------------------------


def test_the_six_photos_are_bytes_the_upload_path_accepts_as_images() -> None:
    """R3.2: the format is read from the CONTENT, so a placeholder string would be a 422.

    Six distinct payloads and not one repeated: six objects in the store have to be six
    objects, or a second run writing over the same key would look like idempotency.
    """
    assert set(seed_demo.SEED_PHOTO_BYTES) == {
        photo_type for photo_type, _ in seed_demo._CHECKLIST_PHOTOS
    }
    for photo_type, content in seed_demo.SEED_PHOTO_BYTES.items():
        image = detect_image_type(content[:MAGIC_BYTES_LENGTH])
        assert image is not None, f"{photo_type} is not an accepted image"
        assert image.extension == "jpg"
    assert len(set(seed_demo.SEED_PHOTO_BYTES.values())) == 6


@pytest.mark.asyncio
async def test_the_upload_delivers_the_whole_photo_in_chunks() -> None:
    """`UploadCleaningPhotoUseCase` reads its `ChunkedUpload` in 64 KiB bites and stops on the
    first empty answer, so a `read` that ignored `size` or never emptied would hang or truncate."""
    content = seed_demo.SEED_PHOTO_BYTES["kitchen"]
    upload = seed_demo.BytesUpload(content)

    chunks = []
    while chunk := await upload.read(8):
        assert len(chunk) <= 8
        chunks.append(chunk)

    assert b"".join(chunks) == content
    assert await upload.read(8) == b""


def test_the_three_incidents_are_the_ones_prd_27_declares() -> None:
    """Constants of the module and not composed text (D6): `incidents.title`/`description` are
    rule-11 sinks whose excepción 2 «no autoriza a un escritor nuestro», and the seed is one."""
    assert [
        (incident.internal_code, incident.source.value, incident.title)
        for incident in seed_demo.SEED_INCIDENTS
    ] == [
        ("REDES11", "GUEST", "WiFi va lento"),
        ("REDES11", "GUEST", "Problema con código de acceso"),
        ("PAJARITOS8", "CLEANER", "Lavadora hace ruido extraño"),
    ]
    assert [
        (incident.category.value, incident.severity.value)
        for incident in seed_demo.SEED_INCIDENTS
    ] == [("WIFI", "LOW"), ("ACCESS", "HIGH"), ("APPLIANCE", "MEDIUM")]


# --- Preconditions: the tenant and the two accounts bootstrap left (R1.3, D4) ----------


async def _row_counts(session) -> dict[str, int]:
    """Every table the seed can write, so "nothing was written" is checked and not assumed.

    All seven and not just the two the accounts step touches: an abort that happens after a
    later step had already written would leave rows this helper never looked at, and the three
    tests below would still pass. The list has to match what the isolation test enumerates.

    **Counted with raw SQL on purpose**, which limit 1 of `app/core/db.py` documents as
    bypassing the tenant listener. An ORM `select(func.count())` would not measure the same
    thing before and after: `apply_plan` marks the session, so a "before" taken while unmarked
    is a global count and an "after" is silently scoped to the seeded tenant. The two can even
    coincide — a neighbour's row dropping out as a seeded row appears — which hides exactly the
    write these tests exist to catch. The rows are flushed but uncommitted, so a second session
    cannot see them at all; it has to be this session, counted past the listener.

    **Flushed first, and that is not a formality.** `session.execute(text(...))` does not
    autoflush, where the ORM `select(func.count())` this replaced did, and not every writer
    flushes on its own — `SqlAlchemyAuditLogRepository.add` only calls `session.add`. Without
    this line the helper would be blind to a pending-but-unflushed row and would report
    "nothing written" for an implementation that had written one. Raw SQL answers the scoping
    problem above and the flush answers the pending-row one; it takes both to measure
    everything the seed can leave behind.
    """
    await session.flush()
    return {
        model.__tablename__: int(
            await session.scalar(text(f"SELECT count(*) FROM {model.__tablename__}")) or 0
        )
        for model in (
            UserModel,
            PropertyModel,
            GuestModel,
            ReservationModel,
            CleaningChecklistTemplateModel,
            AuditLogModel,
            TimelineEventModel,
            # Everything the advance phase can write, including the two child tables with no
            # `tenant_id` of their own: "nothing was written" has to be measured over every
            # table a refusal could have written to, or the guarantee is only as wide as the
            # list somebody remembered to keep.
            IncidentModel,
            CleaningTaskModel,
            CleaningChecklistCompletionModel,
            CleaningPhotoModel,
            PropertyStateTransitionModel,
            NotificationLogModel,
        )
    }


@pytest.mark.asyncio
async def test_without_the_tenant_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "make bootstrap" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_without_the_owner_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    tenant = await insert_tenant(db_session, name=BOOTSTRAPPED_TENANT_NAME)
    await insert_user(db_session, tenant=tenant, role=UserRole.PROPERTY_MANAGER)
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "TENANT_OWNER" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_without_the_manager_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    tenant = await insert_tenant(db_session, name=BOOTSTRAPPED_TENANT_NAME)
    await insert_user(db_session, tenant=tenant, role=UserRole.TENANT_OWNER)
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "PROPERTY_MANAGER" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_a_tenant_whose_timezone_cannot_be_resolved_is_refused_before_any_write(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R6.1. Written straight onto the column, which is the only way it can happen.

    `normalise_timezone` refuses this value on every domain path, so the row that carries it
    got there past the entity — and until this check it surfaced as `main()`'s catch-all:
    "unexpected ZoneInfoNotFoundError; details withheld", naming neither the column nor the
    value. Unlike the `SEED_*` refusals the message echoes the value: a zone name is not a
    person's address and it is what the operator has to correct.
    """
    bootstrapped_tenant.timezone = "Not/AZone"
    await db_session.flush()
    before = await _row_counts(db_session)

    with pytest.raises(SeedConfigurationError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    message = str(excinfo.value)
    assert "tenants.timezone" in message
    assert "Not/AZone" in message
    assert await _row_counts(db_session) == before


def _configured_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """A complete object-store configuration, with the credential chain answered rather than
    resolved: left alone, `credentials_are_resolvable` reads the operator's `~/.aws` files
    and the instance metadata endpoint, which would make the outcome depend on the machine."""
    monkeypatch.setattr(settings, "s3_bucket", "autohost-media")
    monkeypatch.setattr(settings, "s3_region", "eu-madrid-1")
    monkeypatch.setattr(seed_demo, "credentials_are_resolvable", lambda: True)


@pytest.mark.parametrize(
    ("blanked", "expected"),
    [
        ("s3_bucket", "S3_BUCKET"),
        ("s3_region", "S3_REGION"),
        (None, "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY"),
    ],
)
@pytest.mark.asyncio
async def test_a_tenant_in_s3_missing_any_piece_is_refused_before_any_write(
    db_session,
    bootstrapped_tenant,
    complete_env,
    hasher,
    monkeypatch: pytest.MonkeyPatch,
    blanked: str | None,
    expected: str,
) -> None:
    """R3.3 and D10, over every piece its IF-clause names, not just the bucket.

    The store is judged before the transaction and not in the middle of it: `storage_for(S3)`
    raises and **never** falls back to `LOCAL`, and six photos are `required: True` in the
    seed's own template, so a half-configured `dev` would otherwise break after the
    reservations were seeded and report "details withheld" with exit 2.

    **`S3_ENDPOINT_URL` is not one of the pieces**, and its absence from this list is the
    decision of the section-4 panel rather than an oversight: an empty endpoint is how the
    rest of the system spells "this is AWS".
    """
    db_session.add(
        TenantConfigModel(tenant_id=bootstrapped_tenant.id, storage_type=StorageType.S3)
    )
    await db_session.flush()
    _configured_s3(monkeypatch)
    if blanked is None:
        monkeypatch.setattr(seed_demo, "credentials_are_resolvable", lambda: False)
    else:
        monkeypatch.setattr(settings, blanked, "   ")
    before = await _row_counts(db_session)

    with pytest.raises(SeedConfigurationError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    message = str(excinfo.value)
    assert expected in message
    # The names of what is missing, never a value: two of the four real secrets of rule 8
    # can be in that list.
    assert "values not echoed" in message
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_an_s3_tenant_with_no_endpoint_passes_the_precondition(
    db_session, bootstrapped_tenant, complete_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conflict the section-4 panel resolved: an empty `S3_ENDPOINT_URL` is the correct
    configuration for AWS, so refusing it would refuse a deployment every other path serves.

    Driven against the precondition rather than the whole run, and the reason is the point:
    a full run over an `S3` tenant really uploads six photos, so the only way to assert "the
    command goes on" end to end would be to reach a store — which the suite refuses to do by
    design (`app/integrations/infrastructure/storage/s3.py`: "nothing in the automated suite
    talks to a real store").
    """
    db_session.add(
        TenantConfigModel(tenant_id=bootstrapped_tenant.id, storage_type=StorageType.S3)
    )
    await db_session.flush()
    _configured_s3(monkeypatch)
    monkeypatch.setattr(settings, "s3_endpoint_url", "")

    await seed_demo._refuse_an_object_store_this_run_cannot_reach(
        db_session, bootstrapped_tenant.id
    )


@pytest.mark.asyncio
async def test_a_local_tenant_is_not_asked_for_any_object_store_setting(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of R3.3: `LOCAL` — the default, and every new tenant — changes nothing.

    Left without a `tenant_configs` row on purpose, which is the state `make bootstrap`
    leaves and the one the check has to read as `LOCAL` without creating anything. Nothing
    about the store is even asked, which is why the credential chain is not stubbed here.
    """
    monkeypatch.setattr(settings, "s3_bucket", "")

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["properties"] == 2


@pytest.mark.asyncio
async def test_each_write_carries_the_actor_its_use_case_demands(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """What replaces `test_the_actor_of_everything_it_writes_is_the_owner` (R5.1-R5.4, D8).

    The old rule — one actor for the whole run, the `TENANT_OWNER` — described a command
    that only wrote things an owner can write. It is not relaxed here: it became impossible.
    `accept`, `start`, `complete` and every photo upload call `_require_assignee` on the
    entity, so the cleaning cycle can only be signed by the cleaner it was assigned to; and
    the automatic classification is written with no actor at all, which is what rule 9's
    fourth exception of `steering/security.md` concedes and `TimelineEventFactory` mirrors
    by putting `AI` in the timeline instead of a person who was not there.

    So the assertion is a **split by action** rather than a single set: what the seed already
    wrote before this change, plus the incident work, stays with the owner; the cleaning is
    the cleaner's; `INCIDENT_CLASSIFIED` has none. Anything else without an actor would be a
    rule-9 violation and fails here.

    **The set of actions is pinned first, and by equality**, because a split by action can
    only speak about the rows it finds: an action that stopped being audited would simply not
    appear, and the loop below would pass over a trail with a hole in it. Rule 9 names
    `Incident` and `roles de User` in its enumeration, so their absence is exactly what has
    to fail.

    **What this test does NOT cover, and it is not an oversight**: the property-state
    transitions the cleaning cycle fires carry actor `USER`, and rule 9's first exception
    excuses only `SYSTEM` ones from `AuditLog` — but no writer in `properties`, `cleaning` or
    `maintenance` writes that row, and `audit/domain/actions.py` has no action for it. That
    gap is the design's OQ3, decided and recorded: this change "no lo cierra ni lo ensancha:
    usa los mismos casos de uso que la API ya usa". Asserting it here would be asserting a
    behaviour nobody implements, so the boundary is written down instead. Raised by the
    section-8 security panel.

    The set below encodes a second recorded debt, and it is worth naming so that its day
    comes as a red test rather than a surprise: rule 9 lists `Reservation`, `reservations`
    writes no `AuditLog` for its mutations (its own spec records it), and the seed moves
    three stays — so no `RESERVATION_*` action appears here. When that trail arrives, this
    equality fails and somebody adds it deliberately.
    """
    await apply_plan(db_session, build_plan(), hasher)

    owner = (
        await db_session.execute(
            select(UserModel).where(
                UserModel.tenant_id == bootstrapped_tenant.id,
                UserModel.role == UserRole.TENANT_OWNER,
            )
        )
    ).scalar_one()
    cleaner = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"])
        )
    ).scalar_one()
    rows = (
        (
            await db_session.execute(
                select(AuditLogModel.action, AuditLogModel.actor_user_id)
            )
        )
        .tuples()
        .all()
    )
    by_action: dict[str, set] = {}
    for action, actor_user_id in rows:
        by_action.setdefault(action, set()).add(actor_user_id)

    assert by_action.keys() == {
        actions.USER_CREATED,
        actions.PROPERTY_CREATED,
        actions.CLEANING_TASK_ACCEPTED,
        actions.CLEANING_TASK_STARTED,
        actions.CLEANING_PHOTO_UPLOADED,
        actions.CLEANING_TASK_COMPLETED,
        actions.INCIDENT_CREATED,
        actions.INCIDENT_CLASSIFIED,
        actions.INCIDENT_ASSIGNED,
    }

    # `CLEANING_` and not `CLEANING_TASK_`: the photo upload writes its own action
    # (`CLEANING_PHOTO_UPLOADED`) and is as much the cleaner's hands as the rest of the cycle.
    cleaning_actions = {action for action in by_action if action.startswith("CLEANING_")}
    assert cleaning_actions, "the cleaning cycle has to leave its own audit trail"
    for action in cleaning_actions:
        assert by_action[action] == {cleaner.id}, action

    for action, actors in by_action.items():
        if action in cleaning_actions:
            continue
        if action == actions.INCIDENT_CLASSIFIED:
            # Rule 9's fourth exception, and only for this action: the classification is
            # written by a command with no person behind it.
            assert actors == {None}
            continue
        assert actors == {owner.id}, action


# --- The two operational accounts (R3.1-R3.6, D3, D6) ---------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_cleaner_and_the_technician_ready_to_work(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["users"] == 2
    seeded = (
        (
            await db_session.execute(
                select(UserModel).where(
                    UserModel.email.in_(
                        [COMPLETE_ENV["SEED_CLEANER_EMAIL"], COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"]]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert {user.role for user in seeded} == {UserRole.CLEANER, UserRole.TECHNICIAN}
    # R3.4: a demo that demands four password rotations before the first click is not a demo.
    assert all(user.must_change_password is False for user in seeded)
    assert all(user.password_hash.startswith("$2") for user in seeded)


@pytest.mark.asyncio
async def test_a_second_run_creates_nothing_and_keeps_the_existing_password(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)
    before = (
        await db_session.execute(
            select(UserModel.password_hash).where(
                UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"]
            )
        )
    ).scalar_one()

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["users"] == 0
    assert await db_session.scalar(select(func.count()).select_from(UserModel)) == 4
    after = (
        await db_session.execute(
            select(UserModel.password_hash).where(
                UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"]
            )
        )
    ).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_an_address_taken_by_another_tenant_is_refused(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.CLEANER,
        email=COMPLETE_ENV["SEED_CLEANER_EMAIL"],
    )

    with pytest.raises(SeedConflictError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "another tenant" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_conflict_on_the_second_account_still_writes_nothing_at_all(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """D11: the exit-1 conditions hold BEFORE the first write, not thanks to the rollback.

    The contested address here is the TECHNICIAN's, so the CLEANER — first in `plan.accounts`
    — is clean and gets inserted by any implementation that judges one account per iteration
    of the write loop, refusing only on the second. That is what this pins: the refusal has to
    be settled with both answers in hand, while nothing has been written yet.
    """
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.TECHNICIAN,
        email=COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"],
    )
    before = await _row_counts(db_session)

    with pytest.raises(SeedConflictError):
        await apply_plan(db_session, build_plan(), hasher)

    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_each_new_account_gets_its_audit_row_with_the_password_redacted(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # Rule 9 of steering/security.md names "roles de User", and this is the only role
    # assignment of the run (design D6).
    await apply_plan(db_session, build_plan(), hasher)

    entries = (
        (
            await db_session.execute(
                select(AuditLogModel).where(AuditLogModel.action == actions.USER_CREATED)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 2
    for entry in entries:
        assert entry.entity_type == actions.ENTITY_USER
        serialised = str(entry.changes)
        assert COMPLETE_ENV["SEED_CLEANER_PASSWORD"] not in serialised
        assert COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"] not in serialised
        assert "password" in serialised


# --- The console contract and tenant isolation (R1.1, R1.2, R1.4, security rule 1) -----


# The shape `main()` is driven with below. Pinned to what `apply_plan` really returns by
# `test_the_counts_apply_plan_returns_have_the_shape_the_console_prints`, which is what keeps
# the canned dict from drifting into a fiction the console never sees.
_CONSOLE_COUNTS = {
    "users": 2,
    "properties": 2,
    "guests": 3,
    "reservations": 3,
    "checklist_templates": 1,
    # The three the advance phase adds (D12). Entities created and nothing else: no
    # operational state and no transition, because a state is not an entity somebody created.
    "cleaning_tasks": 1,
    "cleaning_photos": 6,
    "incidents": 3,
}


def _drive_main(monkeypatch: pytest.MonkeyPatch, counts: dict[str, int]) -> int:
    """Run `main()` over a canned result, because it cannot be run over the test session.

    `main()` calls `asyncio.run(run())`, which builds its OWN event loop, while `db_session`
    is bound to the test's — the "attached to a different loop" problem `tests/conftest.py`
    documents at length. Driving it with the counts `apply_plan` returns is not a weakening:
    `main()` receives a `dict[str, int]` and nothing else, so what the console can possibly
    print is decided entirely by this dict. The counts themselves are asserted against the
    database by the tests above.
    """

    async def _canned() -> dict[str, int]:
        return counts

    monkeypatch.setattr(seed_demo, "run", _canned)
    return seed_demo.main()


def test_the_output_carries_a_count_per_entity_and_nothing_else(
    complete_env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1.1 (a count per entity type) and R1.4 (never a password, a hash or a token) over the
    # success path. The three refusal paths and the catch-all are covered separately.
    exit_code = _drive_main(monkeypatch, dict(_CONSOLE_COUNTS))

    assert exit_code == 0
    captured = capsys.readouterr()
    for entity in _CONSOLE_COUNTS:
        assert entity in captured.out
    for secret in (
        COMPLETE_ENV["SEED_CLEANER_PASSWORD"],
        COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"],
    ):
        assert secret not in captured.out
        assert secret not in captured.err
    assert "$2b$" not in captured.out, "no bcrypt hash may reach the console"


@pytest.mark.asyncio
async def test_the_counts_apply_plan_returns_have_the_shape_the_console_prints(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """Ties the canned dict above to reality, which is the one thing `_drive_main` cannot.

    `main()` receives a `dict[str, int]` and nothing else, so that dict decides entirely what
    the console can print — but only as long as it is the dict `apply_plan` really returns. If
    a future entity type were added to one and not the other, every console test above would
    keep passing while the real command printed something different.
    """
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created.keys() == _CONSOLE_COUNTS.keys()
    assert all(isinstance(count, int) for count in created.values())


def test_a_run_with_nothing_to_do_prints_every_count_at_zero_and_exits_zero(
    complete_env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1.2's console half: an operator has to be able to SEE that nothing happened, which is
    # why every entity type is printed even at zero. A line that dropped the zeros would be
    # indistinguishable from a run that did only part of the work.
    exit_code = _drive_main(monkeypatch, dict.fromkeys(_CONSOLE_COUNTS, 0))

    assert exit_code == 0
    out = capsys.readouterr().out
    for entity in _CONSOLE_COUNTS:
        assert f"0 {entity}" in out


@pytest.mark.asyncio
async def test_a_second_run_returns_every_count_at_zero(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # The other half of R1.2: what `main()` prints comes from here, so this is where "nothing
    # was created" has to be true rather than merely reported.
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created == dict.fromkeys(_CONSOLE_COUNTS, 0)


@pytest.mark.asyncio
async def test_nothing_the_seed_writes_is_reachable_from_another_tenant(
    db_session, test_engine, bootstrapped_tenant, complete_env, hasher
) -> None:
    """DoD §28.18 and rule 1 of `steering/security.md`, over everything the seed writes.

    Two halves, because they fail differently. First: every row carries the seeded tenant's
    id — a row with a NULL or foreign `tenant_id` would be invisible to its owner rather than
    visible to a stranger. Second: the neighbour cannot reach any of it through the ports.

    **Both halves run on a SEPARATE, never-marked session, and the first one has to.**
    `apply_plan` marks `db_session`, and the `do_orm_execute` listener rewrites column-only
    selects too — so `select(Model.tenant_id).distinct()` on that session compiles to
    `... WHERE tenant_id = :seeded` and can only ever answer `[seeded]` or `[]`. Asserting
    ownership there proves the tables are non-empty and nothing else: a row written with a
    foreign or NULL `tenant_id` is filtered out by the very net the assertion is meant to
    work without. The section 7 security panel caught that; it was tautological as first
    written. Unmarked, the net is off and the rows answer for themselves.

    The second half is unmarked for a related but distinct reason: a marked session would
    prove only that the listener works, when the authoritative mechanism is the explicit
    `tenant_id` every repository method takes (design D6 of `auth-tenancy`). And it could not
    be `db_session` in any case — `bind_session_to_tenant` refuses to rebind a session
    already bound to another tenant, so the test would die in that guard instead of in an
    assertion.

    `audit_logs` is covered by the first half only, and deliberately: `SqlAlchemyAuditLog
    Repository` exposes no read method at all — only `add` — so there is no port through
    which a neighbour could ask. What `tests/audit` carries for it is therefore the
    cross-tenant WRITE guard (`test_it_refuses_an_entry_of_another_tenant`), not reads;
    there are none anywhere.
    """
    await apply_plan(db_session, build_plan(), hasher)
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await db_session.commit()
    seeded = bootstrapped_tenant.id
    redes = (
        await db_session.execute(
            select(PropertyModel.id).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()

    async with AsyncSession(test_engine, expire_on_commit=False) as stranger:
        for model in (
            UserModel,
            PropertyModel,
            GuestModel,
            ReservationModel,
            CleaningChecklistTemplateModel,
            AuditLogModel,
            TimelineEventModel,
            # The five the advance phase brought. `notification_logs` is one of them because
            # the checkout auto-assigns the cleaning — the tenant has exactly one active
            # cleaner — and that writes its assignment notice.
            IncidentModel,
            CleaningTaskModel,
            PropertyStateTransitionModel,
            NotificationLogModel,
        ):
            owners = (
                (await stranger.execute(select(model.tenant_id).distinct())).scalars().all()
            )
            assert owners == [seeded], (
                f"{model.__tablename__} must belong to the seeded tenant and to no other"
            )

        assert (
            await SqlAlchemyPropertyRepository(stranger).find_by_internal_code(
                neighbour.id, "REDES11"
            )
            is None
        )
        assert (
            await SqlAlchemyReservationRepository(stranger).find_by_external_pms_id(
                neighbour.id, "SEED-AIRBNB-1"
            )
            is None
        )
        assert (
            await SqlAlchemyGuestRepository(stranger).find_by_email(
                neighbour.id, "john.smith@example.com"
            )
            is None
        )
        assert (
            await SqlAlchemyCleaningChecklistTemplateRepository(stranger).list(
                neighbour.id, page=1, per_page=10
            )
        ).total == 0
        roster = await SqlAlchemyUserRepository(stranger).list(
            neighbour.id, UserFilters(), page=1, per_page=50
        )
        assert roster.total == 0
        # The neighbour naming the seeded property by its real id still gets nothing: the
        # timeline is scoped by tenant first, so knowing an id buys no access. Through the
        # READER and not the writer — the port is split on purpose, because the writer's
        # signature is what states the timeline is append-only.
        events = await SqlAlchemyTimelineEventReader(stranger).list_for_property(
            neighbour.id, redes, filters=TimelineFilters(), page=1, per_page=50
        )
        assert events.total == 0
        assert (
            await SqlAlchemyIncidentReader(stranger).list(
                neighbour.id, IncidentFilters(), page=1, per_page=50
            )
        ).total == 0
        assert not await SqlAlchemyCleaningTaskRepository(stranger).list_for_property(
            neighbour.id, redes
        )

        # `cleaning_checklist_completions` and `cleaning_photos` have **no `tenant_id` of
        # their own** — `app/core/db.py` names them among the child tables the listener
        # cannot reach, so "any repository touching them must join the scoped parent
        # explicitly and bring its own isolation test". That join is the only thing between a
        # neighbour and these rows, so it is asked directly: the task id is the real one, and
        # the answer still has to be empty.
        task_id = (
            await stranger.execute(select(CleaningTaskModel.id))
        ).scalar_one()
        assert not await SqlAlchemyCleaningChecklistCompletionRepository(
            stranger
        ).list_for_task(neighbour.id, task_id)
        assert not await SqlAlchemyCleaningPhotoRepository(stranger).list_for_task(
            neighbour.id, task_id
        )
        assert not await SqlAlchemyCleaningPhotoRepository(stranger).uploaded_photo_types(
            neighbour.id, task_id
        )


# --- The two properties (R2.1-R2.4) ---------------------------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_two_properties_of_the_prd_with_their_values(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["properties"] == 2
    homes = {
        model.internal_code: model
        for model in (await db_session.execute(select(PropertyModel))).scalars().all()
    }
    assert set(homes) == {"REDES11", "PAJARITOS8"}
    redes = homes["REDES11"]
    assert redes.name == "Redes 11"
    assert redes.address_line1 == "Calle de las Redes, 11"
    assert (redes.city, redes.province) == ("Madrid", "Madrid")
    assert (redes.max_guests, redes.bedrooms, redes.bathrooms) == (4, 2, 1)
    assert redes.default_check_in_time == time(15, 0)
    assert redes.default_check_out_time == time(11, 0)
    # §27 gives no postal code, and inventing one would be dataset drift.
    assert redes.postal_code is None
    # OQ1 closed with a NO: no `pms_external_id`, so `make pms-sync` does not import the
    # mock's own copy of these reservations on top of the seed's.
    assert redes.pms_external_id is None
    pajaritos = homes["PAJARITOS8"]
    assert (pajaritos.max_guests, pajaritos.bedrooms, pajaritos.bathrooms) == (2, 1, 1)


@pytest.mark.asyncio
async def test_the_operational_state_is_always_a_consequence_and_never_a_column_written(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """What survives of `test_both_properties_are_born_vacant_ready`, and what does not.

    Still true, and the property this change is careful to keep: the seed never passes nor
    writes `current_operational_state` — every value it ends up with is the verdict of
    `PropertyStateMachine`, reached by a trigger, with its `property_state_transitions` row
    behind it. No longer true: that both homes end in `VACANT_READY`. REDES11 now has a
    journey, and the sequence test is what pins it; PAJARITOS8 receives no trigger at all —
    it has no stays, and its incident is `MEDIUM`, which maps to no trigger — so it is the
    one that still shows the untouched default.
    """
    await apply_plan(db_session, build_plan(), hasher)

    pajaritos = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "PAJARITOS8")
        )
    ).scalar_one()
    assert pajaritos.current_operational_state is PropertyOperationalState.VACANT_READY
    assert not (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.property_id == pajaritos.id
            )
        )
    ).scalars().all()

    redes = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()
    transitions = (
        (
            await db_session.execute(
                select(PropertyStateTransitionModel).where(
                    PropertyStateTransitionModel.property_id == redes.id
                )
            )
        )
        .scalars()
        .all()
    )
    # Not a state count: the point is that wherever REDES11 ended up, a transition put it
    # there, and the chain starts at the DDL default nobody wrote.
    #
    # Deliberately not "the newest row's destination": two transitions of this run share an
    # instant — the checkout and the auto-assignment its provisioner performs — so `created_at`
    # does not order them. The full ordered sequence is the sequence test's business.
    assert transitions
    assert PropertyOperationalState.VACANT_READY in {row.from_state for row in transitions}
    assert redes.current_operational_state in {row.to_state for row in transitions}


@pytest.mark.asyncio
async def test_a_second_run_creates_no_third_property(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["properties"] == 0
    assert await db_session.scalar(select(func.count()).select_from(PropertyModel)) == 2


@pytest.mark.asyncio
async def test_a_second_run_leaves_an_existing_property_exactly_as_it_was(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # R2.3 asks for the existing home to be left INTACT, and a row count cannot show that: a
    # re-run that rewrote §27's values over an operator's edits would keep the count at two.
    # The users test asserts the password hash survives; a property deserves the same.
    await apply_plan(db_session, build_plan(), hasher)
    redes = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()
    redes.name = "Renamed by whoever runs this environment"
    redes.max_guests = 9
    await db_session.flush()

    await apply_plan(db_session, build_plan(), hasher)

    refreshed = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()
    assert refreshed.name == "Renamed by whoever runs this environment"
    assert refreshed.max_guests == 9


# --- The three reservations and their guests (R4.1-R4.6, D7, D8, D9) -------------------


async def _reservations_by_channel(session) -> dict[ReservationChannel, ReservationModel]:
    rows = (await session.execute(select(ReservationModel))).scalars().all()
    return {row.channel: row for row in rows}


@pytest.mark.asyncio
async def test_the_dates_are_anchored_to_the_tenants_day_and_not_to_utc(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R4.3's composition is about the calendar the demo is watched on.

    23:30 UTC on 15 June is already 01:30 on the **16th** in Madrid (CEST). Anchored on
    `now.date()` this run used the 15th, so every stay landed a day early — the "live" one as
    the 13th → 16th. The reasoning lives beside the `today` computation in `seed_demo.py` and
    in D9's amendment; this test only pins it, so the two do not drift. Every other date test
    uses 09:00 UTC, where the two calendars agree and this cannot show up.
    """
    await apply_plan(
        db_session, build_plan(), hasher, now=datetime(2026, 6, 15, 23, 30, tzinfo=UTC)
    )

    airbnb = (await _reservations_by_channel(db_session))[ReservationChannel.AIRBNB]
    # today = 2026-06-16 in Madrid ⇒ today−2 → today+1.
    assert airbnb.check_in_date == date(2026, 6, 14)
    assert airbnb.check_out_date == date(2026, 6, 17)


@pytest.mark.asyncio
async def test_it_creates_the_three_stays_of_the_prd_dated_from_today(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    now = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)

    created = await apply_plan(db_session, build_plan(), hasher, now=now)

    assert created["reservations"] == 3
    stays = await _reservations_by_channel(db_session)
    assert set(stays) == {
        ReservationChannel.DIRECT,
        ReservationChannel.AIRBNB,
        ReservationChannel.BOOKING,
    }
    today = now.date()
    # R4.3: past, live and upcoming, whatever day the seed runs.
    assert stays[ReservationChannel.DIRECT].check_in_date == today - timedelta(days=10)
    assert stays[ReservationChannel.DIRECT].check_out_date == today - timedelta(days=7)
    assert stays[ReservationChannel.AIRBNB].check_in_date == today - timedelta(days=2)
    assert stays[ReservationChannel.AIRBNB].check_out_date == today + timedelta(days=1)
    assert stays[ReservationChannel.BOOKING].check_in_date == today + timedelta(days=3)
    assert stays[ReservationChannel.BOOKING].check_out_date == today + timedelta(days=7)


@pytest.mark.asyncio
async def test_none_of_the_three_is_given_a_status_at_the_moment_it_is_created(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """What survives of `test_none_of_the_three_is_given_a_status_by_hand` (R2.1-R2.3).

    Still true, and still the most tempting thing to get wrong: **no stay is born with a
    status somebody chose**. The DIRECT path cannot express one at all
    (`CreateReservationCommand` has no `status` field); the OTA path can, through
    `ReservationDTO.status`, and leaving it `None` is what makes this hold. The two defaults
    are DIFFERENT on purpose: `Reservation.create` starts a hand-made booking at `PENDING`,
    while `ReservationStatus.parse_ingested(None)` reads a feed row with no status as
    `CONFIRMED` — "a booking somebody already accepted".

    What is no longer true is that the statuses §27 draws never appear. They do, and they
    arrive **afterwards and through a writer**: `UpdateReservationUseCase`, which is a
    declared substitute rather than the definitive way — `reservations` offers no check-in
    operation and no closing one, and opening them is its own work, not a seed's. What this
    test pins is the difference between reaching a status and being born with it, which is
    the whole of R4.4's original point.
    """
    await apply_plan(db_session, build_plan(), hasher)

    stays = await _reservations_by_channel(db_session)
    # Reached: each by one `UpdateReservationUseCase` call, at the instant of the fact.
    assert stays[ReservationChannel.DIRECT].status is ReservationStatus.COMPLETED
    assert stays[ReservationChannel.AIRBNB].status is ReservationStatus.CHECKED_IN_ESTIMATED
    # Untouched: the upcoming stay keeps the status its ingest gave it.
    assert stays[ReservationChannel.BOOKING].status is ReservationStatus.CONFIRMED

    # And each move left its `RESERVATION_UPDATED` in the timeline — which is what makes it a
    # transition of the system and not a column somebody wrote.
    updates = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.event_type == TimelineEventType.RESERVATION_UPDATED
                )
            )
        )
        .scalars()
        .all()
    )
    moved = {event.reservation_id for event in updates}
    assert stays[ReservationChannel.DIRECT].id in moved
    assert stays[ReservationChannel.AIRBNB].id in moved
    assert stays[ReservationChannel.BOOKING].id not in moved


@pytest.mark.asyncio
async def test_the_two_ota_stays_carry_their_external_pms_id_and_the_direct_one_does_not(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # R4.2: the ingest path is what assigns `external_pms_id`, and that id is the key the
    # next sync uses to avoid re-importing the same stay. Giving the DIRECT one an id would
    # be a lie — it came from no PMS (design D8).
    await apply_plan(db_session, build_plan(), hasher)

    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.AIRBNB].external_pms_id == "SEED-AIRBNB-1"
    assert stays[ReservationChannel.BOOKING].external_pms_id == "SEED-BOOKING-1"
    assert stays[ReservationChannel.DIRECT].external_pms_id is None
    assert stays[ReservationChannel.DIRECT].external_channel_id == "SEED-DIRECT-1"


@pytest.mark.asyncio
async def test_the_airbnb_stay_carries_the_money_of_the_prd_with_net_derived(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # §27's €297.50 is NOT a field of the DTO: it is gross − commission, derived by
    # `net_amount_from` inside the ingestor.
    await apply_plan(db_session, build_plan(), hasher)

    airbnb = (await _reservations_by_channel(db_session))[ReservationChannel.AIRBNB]
    assert airbnb.gross_amount == Decimal("350.00")
    assert airbnb.ota_commission == Decimal("52.50")
    assert airbnb.net_amount == Decimal("297.50")
    assert airbnb.adults == 2


@pytest.mark.asyncio
async def test_the_three_guests_are_registered_and_linked(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["guests"] == 3
    guests = {
        row.full_name: row
        for row in (await db_session.execute(select(GuestModel))).scalars().all()
    }
    assert set(guests) == {"Pedro López", "John Smith", "María García"}
    assert guests["John Smith"].email == "john.smith@example.com"
    assert guests["María García"].email == "maria.garcia@example.com"
    # §27 gives Pedro no address, and inventing one would be dataset drift.
    assert guests["Pedro López"].email is None
    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.DIRECT].guest_id == guests["Pedro López"].id
    assert stays[ReservationChannel.AIRBNB].guest_id == guests["John Smith"].id


@pytest.mark.asyncio
async def test_a_second_run_a_week_later_moves_nothing(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R1.2 over R4.3, which is the trade design D9 makes explicit.

    The ingestor's own idempotency is to UPDATE what it recognises, so handing it rows it
    already has would re-anchor the dates on every run. R4.3 describes a FRESH seed; a
    re-seed keeps the dates it was given. An environment seeded a fortnight ago shows a
    "live" stay that has already ended, and the way to refresh it is to drop the database.
    """
    first = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    await apply_plan(db_session, build_plan(), hasher, now=first)
    before = {
        row.id: (row.check_in_date, row.check_out_date)
        for row in (await db_session.execute(select(ReservationModel))).scalars().all()
    }

    created = await apply_plan(
        db_session, build_plan(), hasher, now=first + timedelta(days=7)
    )

    assert created["reservations"] == 0
    assert created["guests"] == 0
    after = {
        row.id: (row.check_in_date, row.check_out_date)
        for row in (await db_session.execute(select(ReservationModel))).scalars().all()
    }
    assert after == before
    assert await db_session.scalar(select(func.count()).select_from(GuestModel)) == 3


@pytest.mark.asyncio
async def test_deleting_the_direct_stay_by_hand_and_reseeding_duplicates_its_guest(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """The one entity with no identity key, pinned so it cannot change in silence (D9).

    Every other entity keys on something stable; Pedro López cannot, because §27 gives him no
    email and R4.5 says "nombre y correo *donde §27 lo da*". Inventing one to buy a key would
    be drift in the dataset the PRD fixes, and the guests port offers no lookup by name.

    So his creation rides on the reservation's: an ordinary second run does not duplicate him,
    because the whole step is skipped. Hand-deleting the DIRECT stay and re-seeding does — a
    new stay and a second Pedro, the first left orphaned. This test asserts that outcome
    rather than wishing it away, and `docs/seed-demo.md` tells the reader to drop the database
    instead.
    """
    await apply_plan(db_session, build_plan(), hasher)
    direct = (await _reservations_by_channel(db_session))[ReservationChannel.DIRECT]
    await db_session.execute(
        delete(TimelineEventModel).where(TimelineEventModel.reservation_id == direct.id)
    )
    # The past stay now drags a whole cleaning behind it: the checkout provisioned a
    # `CleaningTask` pointing at it, and the cleaner walked it — 18 completions and 6 photos
    # — so three foreign keys refuse the delete. Part of what "hand-deleting the stay" costs,
    # and the reason `docs/seed-demo.md` says to drop the database instead.
    task_ids = (
        (
            await db_session.execute(
                select(CleaningTaskModel.id).where(
                    CleaningTaskModel.reservation_id == direct.id
                )
            )
        )
        .scalars()
        .all()
    )
    await db_session.execute(
        delete(CleaningPhotoModel).where(CleaningPhotoModel.cleaning_task_id.in_(task_ids))
    )
    await db_session.execute(
        delete(CleaningChecklistCompletionModel).where(
            CleaningChecklistCompletionModel.cleaning_task_id.in_(task_ids)
        )
    )
    await db_session.execute(
        delete(CleaningTaskModel).where(CleaningTaskModel.reservation_id == direct.id)
    )
    await db_session.execute(delete(ReservationModel).where(ReservationModel.id == direct.id))
    await db_session.flush()

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["reservations"] == 1
    assert created["guests"] == 1
    pedros = (
        (
            await db_session.execute(
                select(GuestModel).where(GuestModel.full_name == "Pedro López")
            )
        )
        .scalars()
        .all()
    )
    assert len(pedros) == 2, "documented consequence of the missing key, not a surprise"


@pytest.mark.asyncio
async def test_a_failure_after_the_reservations_rolls_the_whole_run_back(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-transaction guarantee, asserted instead of assumed.

    `apply_plan` hands every composed use case a `CallerOwnedUnitOfWork`, so the only real
    commit is its own at the very end. That is what makes a mid-run failure leave nothing
    behind — and it is exactly the kind of promise that holds until somebody swaps one wiring
    back to a real unit of work, which is why it needs a test rather than a docstring.

    The failure is injected at the last step, so accounts, properties, guests and all three
    reservations have already been flushed when it fires. What proves the point is that they
    are gone AFTER the rollback: had any composed use case been wired to a real unit of work,
    its rows would have been committed and would survive.

    The tenant and its two administrative accounts go too, and that is the fixture's doing
    rather than the seed's — `bootstrapped_tenant` flushes instead of committing, so it shares
    this transaction.
    """

    async def _explode(*args, **kwargs):
        raise RuntimeError("boom-after-the-reservations")

    monkeypatch.setattr(seed_demo, "_seed_checklist_template", _explode)

    with pytest.raises(RuntimeError):
        await apply_plan(db_session, build_plan(), hasher)
    await db_session.rollback()

    for model in (PropertyModel, ReservationModel, GuestModel, AuditLogModel, UserModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_an_ingest_that_skips_a_row_fails_the_command_loudly(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ingest` reports a bad row instead of raising, which is right for an uploaded CSV and
    wrong for a dataset this module wrote itself. Without this the command would print counts
    claiming a seed that did not happen.

    Provoked by pointing one DTO at a property that does not exist — the resolver returns
    `None` and the ingestor records a skipped row.
    """
    original = seed_demo._ota_reservation_dtos

    def _one_row_points_nowhere(today):
        first, second = original(today)
        return (replace(first, property_external_id="NOSUCHCODE"), second)

    monkeypatch.setattr(seed_demo, "_ota_reservation_dtos", _one_row_points_nowhere)

    with pytest.raises(seed_demo.SeedIngestError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "NOSUCHCODE" in str(excinfo.value)


# --- The tenant's checklist template (R5.1, R5.2, D10) --------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_default_template_for_the_whole_tenant(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["checklist_templates"] == 1
    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    # No `property_id` is how the schema spells "both homes" (§7.10 declares it nullable).
    assert template.property_id is None
    assert template.active is True
    assert [item["item_id"] for item in template.items] == [
        "ventilate",
        "remove_rubbish",
        "check_fridge",
        "clean_kitchen_surfaces",
        "clean_sink",
        "clean_bathroom",
        "replace_toilet_paper",
        "replace_towels",
        "make_beds",
        "check_linen",
        "mop_floor",
        "check_sofa",
        "replenish_amenities",
        "check_wifi_router",
        "check_ac_remote",
        "check_keys",
        "report_damages",
        "upload_photos",
    ]
    assert [photo["photo_type"] for photo in template.required_photos] == [
        "living_room",
        "bedroom",
        "bathroom",
        "kitchen",
        "entrance",
        "damage_if_found",
    ]


@pytest.mark.asyncio
async def test_every_item_and_photo_is_required_and_labelled_in_spanish(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # `required` spelled out on every entry, because `parse_template_content` reads a missing
    # one as False — and demands a real bool, so `1` would be refused (design D10).
    await apply_plan(db_session, build_plan(), hasher)

    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    assert all(item["required"] is True for item in template.items)
    assert all(photo["required"] is True for photo in template.required_photos)
    assert template.items[0]["label"] == "Ventilar la vivienda"
    assert template.required_photos[0]["label"] == "Salón"


@pytest.mark.asyncio
async def test_the_seeded_template_passes_the_value_objects_validation(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """What the column holds must survive being read back through the parser.

    The use case parses on the way in, so this asserts the round trip rather than the input:
    a template the seed wrote but `cleaning` could not re-read would be a checklist nobody
    could complete.
    """
    await apply_plan(db_session, build_plan(), hasher)

    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    spec = parse_template_content(template.items, template.required_photos)

    assert len(spec.items) == 18
    assert len(spec.required_photos) == 6


@pytest.mark.asyncio
async def test_a_tenant_that_already_has_a_template_gets_no_second_one(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["checklist_templates"] == 0
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CleaningChecklistTemplateModel)
        )
        == 1
    )


# --- The three incidents, each by its own way in (R1.1-R1.6, R5.3, D2 step 12) ---------


async def _incidents_by_title(db_session) -> dict:
    rows = (await db_session.execute(select(IncidentModel))).scalars().all()
    return {row.title: row for row in rows}


@pytest.mark.asyncio
async def test_the_three_incidents_are_born_unclassified_and_end_where_prd_27_says(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R1.1-R1.5: created with no verdict, then given one by the classifier.

    The pair `(category, severity)` is asserted against §27 because that is what R1.3 makes
    the command itself check: they are the classifier's answer, and a seed that wrote them
    would be a seed that cannot tell a working classifier from a broken one.

    Incidents 1 and 3 end `CLASSIFIED` and not §27's literal `OPEN`, which is the declared
    divergence of R1.5: `classify` is the only door out of `OPEN`, and the beat job would
    move an `OPEN` one within five minutes anyway.
    """
    await apply_plan(db_session, build_plan(), hasher)

    incidents = await _incidents_by_title(db_session)
    assert len(incidents) == 3
    for seeded in seed_demo.SEED_INCIDENTS:
        row = incidents[seeded.title]
        assert row.description == seeded.description
        assert row.source is seeded.source
        assert row.category is seeded.category
        assert row.severity is seeded.severity
        assert row.ai_classification is not None, "the verdict has to come from the adapter"

    assert incidents["Problema con código de acceso"].status is IncidentStatus.ASSIGNED
    assert incidents["WiFi va lento"].status is IncidentStatus.CLASSIFIED
    assert incidents["Lavadora hace ruido extraño"].status is IncidentStatus.CLASSIFIED


@pytest.mark.asyncio
async def test_the_classification_names_no_person_and_the_assignment_does(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R1.2, R1.4, R5.3, R5.4 and D7.

    The classification goes with `actor=None`, so its `AuditLog` row has no actor —
    the fourth exception of rule 9, which this change extended to name the seed command —
    and its timeline entry says `AI`. Putting the owner there instead would have the demo
    claim she classified three incidents she never looked at.
    """
    await apply_plan(db_session, build_plan(), hasher)

    classified = (
        (
            await db_session.execute(
                select(AuditLogModel).where(
                    AuditLogModel.action == actions.INCIDENT_CLASSIFIED
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(classified) == 3
    for row in classified:
        assert row.actor_user_id is None
        assert row.actor_ip is None

    events = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.event_type == TimelineEventType.INCIDENT_CLASSIFIED
                )
            )
        )
        .scalars()
        .all()
    )
    assert {event.actor_type for event in events} == {TimelineActorType.AI}
    assert {event.actor_user_id for event in events} == {None}

    technician = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"])
        )
    ).scalar_one()
    access = (await _incidents_by_title(db_session))["Problema con código de acceso"]
    assert access.assigned_technician_id == technician.id
    # And its SLA is open: an assignment nobody answers has to escalate like any other.
    assert await db_session.scalar(
        select(func.count())
        .select_from(NotificationLogModel)
        .where(NotificationLogModel.related_id == access.id)
    )


@pytest.mark.asyncio
async def test_a_classifier_that_drifts_stops_the_seed_instead_of_changing_the_dataset(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1.3: the command refuses a dataset that is not the one PRD §27 declares.

    Not a nicety: the `(category, severity)` of §27 is what the demo is shown against, and a
    keyword edit that quietly turned the WiFi incident into `OTHER/MEDIUM` would leave a
    dataset that still looks seeded. The message names both values because "this is not what
    §27 says" without saying what it is sends the reader to the wrong file.
    """

    async def _drift(self, *, title: str, description: str):
        return IncidentClassification(
            category=IncidentCategory.NOISE,
            severity=IncidentSeverity.LOW,
            summary="Noise problem reported at the property",
            confidence=Decimal("0.95"),
            vocabulary=frozenset({"Noise problem reported at the property"}),
        )

    monkeypatch.setattr(RuleBasedIncidentClassifier, "classify", _drift)

    with pytest.raises(SeedConflictError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    message = str(excinfo.value)
    assert "WiFi va lento" in message, "the refusal has to name the incident"
    assert "NOISE" in message and "WIFI" in message, "and both verdicts, obtained and expected"

    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(IncidentModel)) == 0


def test_a_conflict_refusal_exits_one_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The exit-1 half of R1.3, driven through `main()` — which no async test can do.

    The mapping is the thing under test, not the message: `SeedConflictError` subclasses
    `Exception` like `SeedIngestError` does, so moving its branch below the catch-all would
    silently turn this refusal into an exit 2 with "details withheld", losing the one detail
    an operator can act on. The message itself is asserted against the database by
    `test_a_classifier_that_drifts_stops_the_seed_instead_of_changing_the_dataset`.
    """
    reason = (
        "The classifier put 'WiFi va lento' in NOISE/LOW, and PRD §27 declares WIFI/LOW."
    )

    async def _refuse() -> dict[str, int]:
        raise SeedConflictError(reason)

    monkeypatch.setattr(seed_demo, "run", _refuse)

    assert seed_demo.main() == 1

    err = capsys.readouterr().err
    assert reason in err
    assert "details withheld" not in err, "this must not fall through to the catch-all"


@pytest.mark.asyncio
async def test_a_technician_account_that_cannot_take_the_incident_is_named(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R5.3's loud half, over the only way it can really happen.

    The seed leaves an account that already exists exactly as it is (R3.5), so an address
    that was already in use with another role — or deactivated — reaches the assignment as
    an assignee the use case refuses. Without a name for it, that arrives as `main()`'s
    catch-all: "unexpected InvalidTechnicianError; details withheld", exit 2, which says
    nothing about which account to fix.
    """
    await insert_user(
        db_session,
        tenant=bootstrapped_tenant,
        role=UserRole.PROPERTY_MANAGER,
        email=COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"],
    )

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    message = str(excinfo.value)
    assert "SEED_TECHNICIAN_EMAIL" in message
    assert "TECHNICIAN" in message


@pytest.mark.asyncio
async def test_a_second_run_creates_no_fourth_incident(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R4.1 and R4.2: the key is `(property_id, title)`, which does not move with the day."""
    created = await apply_plan(db_session, build_plan(), hasher)
    assert created["incidents"] == 3

    again = await apply_plan(db_session, build_plan(), hasher)

    assert again["incidents"] == 0
    assert await db_session.scalar(select(func.count()).select_from(IncidentModel)) == 3


def test_the_seed_reaches_incidents_only_through_maintenance_use_cases() -> None:
    """R1.6, and it needs to be structural rather than behavioural to mean anything.

    Every other test here asserts what the rows *look like* after a run, and a second write
    route added tomorrow would produce rows that look exactly the same — the criterion would
    stay green while the thing it forbids happened. `/sdd:review`'s panel flagged R1.6 as met
    by code audit alone for that reason.

    So this reads the module instead: `app/cli/seed_demo.py` may not name the ORM class, the
    table, or the incident adapter. What it may name are the three `maintenance` use cases,
    which is the route the requirement mandates — they encapsulate the `AuditLog` and the
    `TimelineEvent` that a hand-rolled `IncidentModel(...)` would silently skip, which is why
    D5 rejected composing entity plus port from the CLI in the first place.

    **Three** things are forbidden and one is explicitly allowed, and the distinction is the
    whole test. Forbidden: naming `IncidentModel` at all (a row built by hand), calling a
    mutating method **on** an incident port, and carrying raw SQL that writes the table.
    Allowed: *constructing* an incident repository, because the use cases take it as a
    collaborator — `ReportIncidentUseCase` cannot be wired without one, so banning the name
    would ban the compliant route along with the forbidden one. The first draft of this test did
    exactly that and failed, which is why the allowance is written down instead of assumed.

    **The second and third clauses exist because the panel broke the first version of this
    test.** Its mutating-call check keyed on the receiver's *name* containing `"incident"`, and
    its author had no raw-SQL check at all; QA demonstrated both bypasses with an AST probe —
    `repo = SqlAlchemyIncidentRepository(session); await repo.add(...)` and
    `session.execute(text("UPDATE incidents SET title = …"))` — each of which satisfied every
    assertion while doing precisely what R1.6 forbids. So the receiver is now resolved by **what
    it was assigned from** rather than by what it is called, and the raw-SQL literal check is
    borrowed from `tests/maintenance/test_free_text_sink_contract.py`, which had already learned
    that a `values()`/`text()` write is the form an AST matcher misses first.

    The census guard in `tests/maintenance/test_free_text_sink_contract.py` covers the
    complementary direction: that no new module composes the *text* of those columns.
    """
    tree = ast.parse(Path(seed_demo.__file__).read_text(encoding="utf-8"))

    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "IncidentModel" not in named, (
        "the seed names IncidentModel: R1.6 says it writes `incidents` only through a use case "
        "of `maintenance`, because those are what carry the AuditLog and the TimelineEvent "
        "with it, and a hand-built row skips both"
    )

    # Which locals hold an incident port, by what they were *assigned from* rather than by what
    # they are called — `repo = SqlAlchemyIncidentRepository(session)` binds a writer under a name
    # that says nothing, and a substring check on the receiver would wave it through. Reported as
    # a LOW by the security panel's re-review of the first version of this test, which matched
    # `"incident" in name.lower()`.
    port_holders: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        constructed = node.value.func
        name = (
            constructed.id
            if isinstance(constructed, ast.Name)
            else constructed.attr
            if isinstance(constructed, ast.Attribute)
            else ""
        )
        if "IncidentRepository" in name:
            port_holders.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )

    mutators = {"add", "update", "save", "delete", "create", "persist", "upsert", "merge"}
    direct_writes = [
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in mutators
        and isinstance(node.func.value, ast.Name)
        and (node.func.value.id in port_holders or "incident" in node.func.value.id.lower())
    ]
    assert not direct_writes, (
        f"the seed calls {sorted(set(direct_writes))} straight on an incident repository: "
        "injecting the port into a use case is the compliant wiring, writing through it here "
        "is the second route R1.6 forbids"
    )

    # A raw `insert`/`update`/`delete` against the table sidesteps the port entirely, so it has
    # to be checked as text and not as a method call.
    raw_sql = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "incidents" in node.value.lower()
        and any(
            verb in node.value.lower()
            for verb in ("insert into", "update ", "delete from")
        )
    ]
    assert not raw_sql, (
        f"the seed carries raw SQL that writes `incidents`: {raw_sql}. R1.6 admits exactly one "
        "route, and it is a use case of `maintenance`"
    )

    # And the route it *is* meant to use is the route it uses, so the test cannot pass by the
    # seed having quietly stopped writing incidents at all.
    assert {
        "ReportIncidentUseCase",
        "ClassifyIncidentUseCase",
        "AssignIncidentUseCase",
    } <= named


# --- The cleaning cycle and its six photos (R3.1-R3.5, R4.5, R4.6, R5.2, D9, D11) ------


@pytest.fixture(autouse=True)
def seed_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """The `LOCAL` backend, rooted where the test can count what really got written.

    Left alone, the seed writes its six objects under `MEDIA_ROOT` (`/app/media`) — the
    container's real media directory, shared by every test of the run. Pointing the factory
    at `tmp_path` is what makes "six objects, not twelve" a question this suite can answer.

    **`autouse`, and that is not convenience**: every test in this file that runs the command
    uploads six photos, so without it a single run of this module would leave hundreds of
    files in the container's media directory and each test's count would depend on which
    tests ran before it.
    """
    root = tmp_path / "media"
    factory = ConfiguredFileStorageFactory(signing_key=b"k" * 32, local_root=root)
    monkeypatch.setattr(seed_demo, "_file_storage_factory", lambda: factory)
    return root


def _stored_objects(root) -> list:
    return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.mark.asyncio
async def test_the_cleaning_is_walked_by_the_cleaner_and_closes_with_its_evidence(
    db_session, bootstrapped_tenant, complete_env, hasher, seed_storage
) -> None:
    """R3.1, R3.2, R3.4 and R5.2: the whole cycle, through the use cases of `cleaning`.

    `validation_status = PASSED` is not written by the seed — `CleaningTask.complete` sets it
    once PRD §11's three clauses hold — so asserting it is asserting that the evidence was
    really there: 18 required items ticked and the 6 required photos uploaded.
    """
    await apply_plan(db_session, build_plan(), hasher)

    task = (await db_session.execute(select(CleaningTaskModel))).scalars().one()
    cleaner = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"])
        )
    ).scalar_one()
    assert task.status is CleaningTaskStatus.COMPLETED
    assert task.validation_status is CleaningValidationStatus.PASSED
    assert task.assigned_cleaner_id == cleaner.id

    completions = (
        (
            await db_session.execute(
                select(CleaningChecklistCompletionModel).where(
                    CleaningChecklistCompletionModel.cleaning_task_id == task.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(completions) == 18
    assert {row.completed_by for row in completions} == {cleaner.id}

    photos = (
        (
            await db_session.execute(
                select(CleaningPhotoModel).where(
                    CleaningPhotoModel.cleaning_task_id == task.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {photo.photo_type for photo in photos} == {
        photo_type for photo_type, _ in seed_demo._CHECKLIST_PHOTOS
    }
    assert {photo.uploaded_by for photo in photos} == {cleaner.id}
    # And the six objects are really in the store the tenant resolves — a row pointing at
    # nothing would be a broken photo for ever (R3.4).
    assert len(_stored_objects(seed_storage)) == 6


@pytest.mark.asyncio
async def test_a_second_run_uploads_no_seventh_photo(
    db_session, bootstrapped_tenant, complete_env, hasher, seed_storage
) -> None:
    """R3.5 and D9: one question — "is the task already `COMPLETED`?" — covers the task, its
    items and its photos.

    Counting the **objects** and not only the rows is the whole point: a re-upload would roll
    its rows back on any later failure and still leave six more files nobody references.
    """
    created = await apply_plan(db_session, build_plan(), hasher)
    assert created["cleaning_photos"] == 6

    again = await apply_plan(db_session, build_plan(), hasher)

    assert again["cleaning_photos"] == 0
    assert again["cleaning_tasks"] == 0
    assert await db_session.scalar(select(func.count()).select_from(CleaningPhotoModel)) == 6
    assert len(_stored_objects(seed_storage)) == 6


@pytest.mark.asyncio
async def test_a_tenant_that_creates_no_cleaning_tasks_is_seeded_without_one(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """The quiet half of the amended D9: no task provisioned, no cleaning to walk.

    A tenant that turned `auto_create_cleaning_task` off is a configuration choice, not a
    broken environment — `ProvisionCleaningTaskUseCase` "returns `None` for every ordinary
    reason not to create one and lets the caller count it", and refusing the whole seed over
    it would be this command deciding something that is not its to decide. What tells the
    operator is the console: zero tasks, zero photos.
    """
    db_session.add(
        TenantConfigModel(
            tenant_id=bootstrapped_tenant.id, auto_create_cleaning_task=False
        )
    )
    await db_session.flush()

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["cleaning_tasks"] == 0
    assert created["cleaning_photos"] == 0
    assert created["properties"] == 2, "the rest of the dataset is seeded as usual"
    assert await db_session.scalar(select(func.count()).select_from(CleaningTaskModel)) == 0


@pytest.mark.asyncio
async def test_a_provisioned_cleaning_that_cannot_be_found_stops_the_run(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loud half of the amended D9, and the distinction the section-7 panel asked for.

    "No task at all" is ordinary; "the checkout just provisioned one and it is not there" is
    a dataset nobody can explain, and the two must not share an answer. Reproduced by making
    the lookup blind rather than by corrupting the data, which is the only way to reach a
    disagreement between the report and the table.
    """

    async def _sees_nothing(self, tenant_id, property_id):
        return []

    monkeypatch.setattr(
        seed_demo.SqlAlchemyCleaningTaskRepository, "list_for_property", _sees_nothing
    )

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "cannot be found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_failure_after_the_photos_names_the_objects_it_could_not_take_back(
    db_session, bootstrapped_tenant, complete_env, hasher, seed_storage, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4.6 and D11: the one write of this command a rollback cannot undo.

    `UploadCleaningPhotoUseCase` deletes the object compensatorily only when **its own**
    `commit()` fails, and under `CallerOwnedUnitOfWork` that commit never happens — so a
    failure after the uploads takes the six rows and leaves the six objects. Enumerating them
    is not cleaning them, and that distinction is what makes the output honest.
    """

    async def _explode(self) -> None:
        raise RuntimeError("the transaction could not be closed")

    monkeypatch.setattr(seed_demo.SqlAlchemyUnitOfWork, "commit", _explode)

    with pytest.raises(RuntimeError):
        await apply_plan(db_session, build_plan(), hasher)

    err = capsys.readouterr().err
    stored = _stored_objects(seed_storage)
    assert len(stored) == 6
    for path in stored:
        assert path.stem in err, "every orphaned object has to be named"
    assert "rolled back" in err

    # R4.5, measured and not taken from the message: the rows really go, which is what makes
    # the objects orphans in the first place. Without this the test would pass over an
    # implementation that committed the cleaning halfway and merely said otherwise.
    await db_session.rollback()
    for model in (CleaningPhotoModel, CleaningChecklistCompletionModel, CleaningTaskModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    # R4.5 in full — "incluidos los estados ya avanzados". The advanced states are the part
    # most easily left behind: they are written by a different use case, on a different
    # table, and a `SqlAlchemyUnitOfWork` slipped into any of the wiring would commit them
    # while the cleaning rolled back.
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PropertyStateTransitionModel)
        )
        == 0
    )
    assert await db_session.scalar(select(func.count()).select_from(IncidentModel)) == 0


# --- The advance phase: the clock of the two stays (R2.1-R2.4, D2, D3, D4) -------------


async def _transitions_of(db_session, internal_code: str):
    property = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == internal_code)
        )
    ).scalar_one()
    rows = (
        (
            await db_session.execute(
                select(PropertyStateTransitionModel).where(
                    PropertyStateTransitionModel.property_id == property.id
                )
            )
        )
        .scalars()
        .all()
    )
    return property, rows


@pytest.mark.asyncio
async def test_the_past_stay_is_confirmed_before_the_clock_can_touch_it(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """D4, and a finding about the system rather than about this change.

    The DIRECT stay is born `PENDING`, and all four clock preconditions demand `CONFIRMED` or
    `CHECKED_IN_ESTIMATED` — so the stay the seed has been writing since 2026-08-12 was in a
    state no trigger could ever advance. Two `RESERVATION_UPDATED` events is what says the
    confirmation happened and was not skipped by a step that wrote `COMPLETED` straight over
    `PENDING`: one for the confirmation, one for the close.
    """
    await apply_plan(db_session, build_plan(), hasher)

    direct = (await _reservations_by_channel(db_session))[ReservationChannel.DIRECT]
    updates = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.reservation_id == direct.id,
                    TimelineEventModel.event_type == TimelineEventType.RESERVATION_UPDATED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 2
    assert direct.status is ReservationStatus.COMPLETED


@pytest.mark.asyncio
async def test_a_second_run_does_not_walk_a_reached_status_backwards(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R4.1's «no mover ningún estado ya alcanzado», over the one move that is not free.

    `update_details` compares values and has no state machine, so an unguarded confirmation
    step would take the already-`COMPLETED` stay back to `CONFIRMED` and forward again on
    every re-run: two real writes and two more timeline events each time. Counting the
    events is what sees it — the final status looks identical either way.
    """
    await apply_plan(db_session, build_plan(), hasher)
    direct = (await _reservations_by_channel(db_session))[ReservationChannel.DIRECT]
    airbnb = (await _reservations_by_channel(db_session))[ReservationChannel.AIRBNB]

    await apply_plan(db_session, build_plan(), hasher)

    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.DIRECT].status is ReservationStatus.COMPLETED
    assert stays[ReservationChannel.AIRBNB].status is ReservationStatus.CHECKED_IN_ESTIMATED
    updates = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.event_type == TimelineEventType.RESERVATION_UPDATED,
                    TimelineEventModel.reservation_id.in_([direct.id, airbnb.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 3, "two moves for the past stay, one for the live one, once"


@pytest.mark.asyncio
async def test_redes11_walks_the_journey_and_pajaritos8_receives_no_trigger(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R2.4 and D2: the states of the demo are reached, one trigger at a time.

    The four this asserts are the ones the past stay produces — arrival, occupancy, checkout
    — and they are asserted as *visited*, not as a final state: the run keeps going. What
    pins the order and the whole set is the sequence test.

    PAJARITOS8 is the control: no stays, and an incident that maps to no trigger, so nothing
    at all should have moved it.
    """
    await apply_plan(db_session, build_plan(), hasher)

    _, redes_rows = await _transitions_of(db_session, "REDES11")
    visited = {row.from_state for row in redes_rows} | {row.to_state for row in redes_rows}
    assert {
        PropertyOperationalState.VACANT_READY,
        PropertyOperationalState.AWAITING_CHECKIN,
        PropertyOperationalState.OCCUPIED_ESTIMATED,
        PropertyOperationalState.AWAITING_CLEANING,
    } <= visited

    # The clock's transitions fired as `SYSTEM`, and that is not decoration: rule 9 of
    # `steering/security.md` exempts a property transition from `AuditLog` **only** for that
    # actor — "una transición con cualquier otro actor … NO está exenta". A re-wiring that
    # produced a `USER` actor here would silently leave them unaudited, so the exemption this
    # phase relies on is asserted rather than assumed.
    #
    # The cleaning cycle's transitions are `USER` — the cleaner really is the actor — and
    # they inherit the known, documented gap of `cleaning`'s own mixin (design OQ3): this
    # change "no lo cierra ni lo ensancha: usa los mismos casos de uso que la API ya usa".
    clock_states = {
        PropertyOperationalState.AWAITING_CHECKIN,
        PropertyOperationalState.OCCUPIED_ESTIMATED,
        PropertyOperationalState.AWAITING_CLEANING,
    }
    assert {
        row.triggered_by for row in redes_rows if row.to_state in clock_states
    } == {StateTransitionTriggeredBy.SYSTEM}

    pajaritos, pajaritos_rows = await _transitions_of(db_session, "PAJARITOS8")
    assert pajaritos_rows == []
    assert pajaritos.current_operational_state is PropertyOperationalState.VACANT_READY


@pytest.mark.asyncio
async def test_redes11_walks_the_whole_sequence_of_d2_in_order(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """The mitigation D2 names for its own risk, and the reason it is a *sequence* test.

    The permutation that seeds the incidents before the stays leaves REDES11 in
    `MAINTENANCE_REQUIRED` from the first step; `(MAINTENANCE_REQUIRED,
    CHECKIN_WINDOW_OPENED)` does not exist in `_POLICY`, and the properties use case filters
    its candidates by source state, so the refusal is not even raised — the property is
    simply never a candidate. The dataset would reach the same **final** state with five
    transitions missing and a timeline with nothing in it. Only the whole ordered sequence
    fails in red for that.

    Step 8 (`CLEANING_COMPLETED`) is the one position asserted as a **set**: its destination
    is resolved contextually out of `{READY_FOR_NEXT_GUEST, AWAITING_CHECKIN, VACANT_READY}`
    and all three chain on to the next arrival, so pinning one value would pin an
    implementation detail of the resolver rather than this command's contract.

    Ordered by `created_at` and then by the chain itself, because two of the nine share an
    instant: the checkout and the auto-assignment its provisioner performs.
    """
    await apply_plan(db_session, build_plan(), hasher)

    redes, rows = await _transitions_of(db_session, "REDES11")
    by_instant = sorted(rows, key=lambda row: row.created_at)
    chain = [(row.from_state, row.to_state) for row in _chained(by_instant)]

    contextual = {
        PropertyOperationalState.READY_FOR_NEXT_GUEST,
        PropertyOperationalState.AWAITING_CHECKIN,
        PropertyOperationalState.VACANT_READY,
    }
    assert len(chain) == 9, "nine facts of D2 carry a trigger"
    assert chain[:5] == [
        (PropertyOperationalState.VACANT_READY, PropertyOperationalState.AWAITING_CHECKIN),
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyOperationalState.OCCUPIED_ESTIMATED),
        (PropertyOperationalState.OCCUPIED_ESTIMATED, PropertyOperationalState.AWAITING_CLEANING),
        (PropertyOperationalState.AWAITING_CLEANING, PropertyOperationalState.CLEANING_SCHEDULED),
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyOperationalState.CLEANING_IN_PROGRESS),
    ]
    assert chain[5][0] is PropertyOperationalState.CLEANING_IN_PROGRESS
    assert chain[5][1] in contextual
    assert chain[6] == (chain[5][1], PropertyOperationalState.AWAITING_CHECKIN)
    assert chain[7] == (
        PropertyOperationalState.AWAITING_CHECKIN,
        PropertyOperationalState.OCCUPIED_ESTIMATED,
    )
    assert chain[8] == (
        PropertyOperationalState.OCCUPIED_ESTIMATED,
        PropertyOperationalState.MAINTENANCE_REQUIRED,
    )
    assert redes.current_operational_state is PropertyOperationalState.MAINTENANCE_REQUIRED


def _chained(rows: list) -> list:
    """Order transitions that share an instant by following `from_state` → `to_state`.

    Two of the nine are written at the same `created_at` — the checkout and the assignment
    its provisioner performs — so `created_at` alone does not order them, and asserting a
    sequence over an ambiguous order would be asserting whatever the database returned.
    """
    remaining = list(rows)
    ordered = [remaining.pop(0)]
    while remaining:
        following = next(
            (row for row in remaining if row.from_state is ordered[-1].to_state), None
        )
        assert following is not None, (
            "the transitions do not form a chain: "
            f"{[(row.from_state, row.to_state) for row in rows]}"
        )
        remaining.remove(following)
        ordered.append(following)
    return ordered


@pytest.mark.asyncio
async def test_two_runs_on_the_same_day_end_in_the_same_state(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R2.5: whatever the machine resolves, it resolves the same twice.

    The trigger of the `HIGH` incident and the ones of the stays compete for REDES11, and the
    proposal accepts as the answer whatever the state machine decides — on the condition that
    it decides it consistently.
    """
    await apply_plan(db_session, build_plan(), hasher)
    redes, first = await _transitions_of(db_session, "REDES11")
    state = redes.current_operational_state

    await apply_plan(db_session, build_plan(), hasher)

    redes, second = await _transitions_of(db_session, "REDES11")
    assert redes.current_operational_state is state
    assert len(second) == len(first), "a second run adds no transition"


@pytest.mark.asyncio
async def test_the_checkout_provisions_the_cleaning_instead_of_the_seed_inserting_it(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R3.1: the task of the past stay comes from the way that creates one today.

    `AdvancePropertyStatesUseCase` is handed a `ProvisionCleaningTaskUseCase` for the
    checkout and for no other trigger, exactly as the scheduler wires it — so the task is
    the checkout's consequence and carries the stay that produced it.
    """
    await apply_plan(db_session, build_plan(), hasher)

    direct = (await _reservations_by_channel(db_session))[ReservationChannel.DIRECT]
    tasks = (
        (await db_session.execute(select(CleaningTaskModel))).scalars().all()
    )
    assert len(tasks) == 1
    assert tasks[0].reservation_id == direct.id
    assert tasks[0].property_id == direct.property_id


@pytest.mark.asyncio
async def test_a_second_run_adds_no_audit_rows(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)
    before = await db_session.scalar(select(func.count()).select_from(AuditLogModel))

    await apply_plan(db_session, build_plan(), hasher)

    assert await db_session.scalar(select(func.count()).select_from(AuditLogModel)) == before
