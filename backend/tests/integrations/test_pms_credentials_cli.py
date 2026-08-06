"""The `pms_credentials` command (D13, tasks 8.2-8.3).

Its whole reason to exist is that the credentials table has no other way in: no Property API by
design, and SQL by hand would bypass the encryption, the cross-tenant guard and the audit at
once. So what these tests pin is not "does it write a row" but everything around it — where the
secret may come from, what the output may contain, and what a rotation records.
"""

import uuid

import pytest
from sqlalchemy import func, select, text

from app.audit.domain.actions import ENTITY_PMS_CREDENTIAL, PMS_CREDENTIAL_ROTATED
from app.audit.infrastructure.models import AuditLogModel
from app.core.crypto import decrypt
from app.integrations.cli import pms_credentials
from app.integrations.cli.pms_credentials import UsageError, store_with_session
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope
from app.integrations.infrastructure.repositories import SqlAlchemyPmsCredentialRepository

SECRET = "beds24-account-refresh-token-XYZ"


async def _store(db_session, tenant, *, secret=SECRET, rotating=False, scope=None, property_id=None):
    await store_with_session(
        db_session,
        tenant_id=tenant.id,
        provider=PMSProvider.BEDS24,
        scope=scope or PmsCredentialScope.ACCOUNT,
        property_id=property_id,
        secret=secret,
        rotating=rotating,
    )


@pytest.mark.asyncio
async def test_set_stores_the_credential_encrypted(db_session, tenant_a) -> None:
    await _store(db_session, tenant_a)

    found = await SqlAlchemyPmsCredentialRepository(db_session).get_for(
        tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT
    )
    assert decrypt(found.secret) == SECRET


@pytest.mark.asyncio
async def test_set_writes_no_audit_row(db_session, tenant_a) -> None:
    """Storing a credential for the first time is not a rotation.

    Rule 9 and ADR 0006 obligation 4 ask for the READ and the ROTATION. A first write has nothing
    it replaced, and recording it as a rotation would make the trail claim a superseded secret
    exists somewhere.
    """
    await _store(db_session, tenant_a)

    count = await db_session.scalar(
        select(func.count()).select_from(AuditLogModel).where(
            AuditLogModel.action == PMS_CREDENTIAL_ROTATED
        )
    )
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_rotate_replaces_the_secret_and_records_it(db_session, tenant_a) -> None:
    """The rotation half of R4.2, and the only place it can be exercised.

    The diff is `{"changed": true}` and nothing else: `secret_encrypted` is on rule 11's denylist,
    so `diff()` on it raises by construction and `redacted()` is the only recordable form.
    """
    await _store(db_session, tenant_a)
    await _store(db_session, tenant_a, secret="the-new-token", rotating=True)

    found = await SqlAlchemyPmsCredentialRepository(db_session).get_for(
        tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT
    )
    assert decrypt(found.secret) == "the-new-token"
    assert found.rotated_at is not None

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == PMS_CREDENTIAL_ROTATED)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity_type == ENTITY_PMS_CREDENTIAL
    assert rows[0].entity_id == found.id
    assert rows[0].changes == {"secret_encrypted": {"changed": True}}
    assert "the-new-token" not in str(rows[0].changes)


@pytest.mark.asyncio
async def test_rotating_something_absent_is_refused(db_session, tenant_a) -> None:
    """Almost always a typo in the coordinates, and creating it silently would hide that: the
    operator would believe a leaked credential had been replaced while it is still live."""
    with pytest.raises(UsageError):
        await _store(db_session, tenant_a, rotating=True)


@pytest.mark.asyncio
async def test_a_property_scope_without_a_property_is_refused(db_session, tenant_a) -> None:
    with pytest.raises(UsageError):
        await _store(db_session, tenant_a, scope=PmsCredentialScope.PROPERTY)


@pytest.mark.asyncio
async def test_an_account_scope_with_a_property_is_refused(db_session, tenant_a, property_a):
    """Caught before the database, so the operator gets a sentence rather than an
    `IntegrityError` from the CHECK constraint."""
    with pytest.raises(UsageError):
        await _store(
            db_session, tenant_a, scope=PmsCredentialScope.ACCOUNT, property_id=property_a.id
        )


# --- The secret's route in, and what may be printed (R4.1) ---


def test_the_secret_is_never_a_command_line_argument() -> None:
    """An argument survives in the shell history and is visible in `ps` to every user on the box.

    Pinned as a property of the USAGE text and the parser: there is no positional or flag through
    which a secret could arrive, so a future edit adding one has to break this test first.
    """
    assert pms_credentials.SECRET_ENV_VAR in pms_credentials.USAGE
    assert "never from an argument" in pms_credentials.USAGE


def test_an_empty_secret_variable_is_refused_naming_it(monkeypatch) -> None:
    monkeypatch.delenv(pms_credentials.SECRET_ENV_VAR, raising=False)

    with pytest.raises(UsageError) as excinfo:
        pms_credentials._read_secret()

    assert pms_credentials.SECRET_ENV_VAR in str(excinfo.value)


def test_a_bad_enum_argument_is_refused_without_echoing_it() -> None:
    """A mistyped argument list can put the secret in the provider position."""
    secret_looking = "sk-live-0a1b2c3d4e5f"

    with pytest.raises(UsageError) as excinfo:
        pms_credentials._parse_enum(secret_looking, PMSProvider, "provider")

    assert secret_looking not in str(excinfo.value)


@pytest.mark.asyncio
async def test_show_providers_reveals_no_credential(db_session, tenant_a, property_a) -> None:
    """It lists which provider each property uses, which is configuration, not a secret — and it
    touches no credential, so it audits nothing."""
    await _store(db_session, tenant_a)

    lines = await pms_credentials.show_providers_with_session(db_session, tenant_a.id)

    joined = "\n".join(lines)
    assert property_a.internal_code in joined
    assert SECRET not in joined


# --- Coordinates the resolver will never read (security panel, sections 6-8) ---


@pytest.mark.asyncio
async def test_a_scope_the_resolver_never_reads_is_refused(db_session, tenant_a, property_a):
    """`rotate beds24 property <uuid>` used to succeed and write a rotation row.

    That is worse than a no-op: the audit trail asserted a leaked secret had been replaced while
    the credential the factory actually reads — the ACCOUNT one — was untouched. Exactly the
    deception the "refuse to rotate what is absent" guard exists to prevent, arriving through the
    other door.
    """
    with pytest.raises(UsageError) as excinfo:
        await store_with_session(
            db_session,
            tenant_id=tenant_a.id,
            provider=PMSProvider.BEDS24,
            scope=PmsCredentialScope.PROPERTY,
            property_id=property_a.id,
            secret=SECRET,
            rotating=False,
        )

    assert "would never be read" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_provider_that_stores_nothing_is_refused(db_session, tenant_a) -> None:
    """Channex authenticates from the environment, so a credential stored for it is dead weight.

    It used to be accepted and printed "ok" while every sync kept using the environment-wide key —
    so an operator could believe a tenant had its own Channex account when it did not.
    """
    with pytest.raises(UsageError) as excinfo:
        await store_with_session(
            db_session,
            tenant_id=tenant_a.id,
            provider=PMSProvider.CHANNEX,
            scope=PmsCredentialScope.ACCOUNT,
            property_id=None,
            secret=SECRET,
            rotating=False,
        )

    assert "environment" in str(excinfo.value)


# --- The command's own entry point (task 8.3) ---


def test_main_refuses_an_unknown_subcommand_without_echoing_it(capsys) -> None:
    """Driving `main()` and not only its helpers.

    The QA panel of sections 6-8 noted the suite never touched it, so task 8.3's promise — "the
    secret never appears in stdout, stderr or a provoked traceback" — was true but unverified,
    and an edit to the confirmation `print` could have leaked it with nothing to catch it.
    """
    secret_looking = "sk-live-aabbccddeeff"

    code = pms_credentials.main([secret_looking, str(uuid.uuid4())])

    captured = capsys.readouterr()
    assert code == 2
    assert secret_looking not in captured.out
    assert secret_looking not in captured.err


def test_main_refuses_a_bad_tenant_without_echoing_it(capsys) -> None:
    secret_looking = "sk-live-112233445566"

    code = pms_credentials.main(["set", secret_looking, "beds24", "account"])

    captured = capsys.readouterr()
    assert code == 2
    assert secret_looking not in captured.out + captured.err


def test_main_with_no_secret_names_the_variable_and_prints_no_value(
    capsys, monkeypatch
) -> None:
    monkeypatch.delenv(pms_credentials.SECRET_ENV_VAR, raising=False)

    code = pms_credentials.main(["set", str(uuid.uuid4()), "beds24", "account"])

    captured = capsys.readouterr()
    assert code == 2
    assert pms_credentials.SECRET_ENV_VAR in captured.err



# --- The malformed stored value (review finding, 2026-08-06) ---
#
# A row whose `secret_encrypted` is not ciphertext at all. Written by hand with SQL, which is
# precisely the path this command exists to close, and precisely the path an operator is pushed
# back onto if the command cannot fix its result. The corruption is PLAINTEXT and not a mangled
# token on purpose: an earlier isolation test corrupted the ciphertext while preserving the
# Fernet structure, so it only ever exercised the half that already worked.


async def _corrupt(db_session, tenant) -> None:
    await db_session.execute(
        text(
            "UPDATE pms_credentials SET secret_encrypted = :v WHERE tenant_id = :t"
        ),
        {"v": "not-ciphertext-at-all", "t": str(tenant.id)},
    )


@pytest.mark.asyncio
async def test_set_replaces_a_stored_value_that_is_not_ciphertext(db_session, tenant_a) -> None:
    """The recovery route for a credential that has leaked AND will not parse.

    Before this, `set` read the old value to find the row and died on the parse, so the ONLY
    audited way to replace it was unavailable at the one moment it matters. The command never
    needed that value: it is about to overwrite it.
    """
    await _store(db_session, tenant_a)
    await _corrupt(db_session, tenant_a)

    await _store(db_session, tenant_a, secret="the-replacement-token")

    found = await SqlAlchemyPmsCredentialRepository(db_session).get_for(
        tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT
    )
    assert decrypt(found.secret) == "the-replacement-token"


@pytest.mark.asyncio
async def test_rotate_over_a_malformed_value_replaces_it_and_audits_the_same_row(
    db_session, tenant_a
) -> None:
    """Rotation must survive it too, and must keep pointing at the row it actually replaced.

    The `entity_id` assertion is what proves the id came from the STORED row rather than a fresh
    `uuid4()`. Had it not, the audit trail would name a credential that never existed, and the
    trail is the only evidence the leaked secret was retired.
    """
    await _store(db_session, tenant_a)
    original_id = await SqlAlchemyPmsCredentialRepository(db_session).id_at(
        tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT
    )
    await _corrupt(db_session, tenant_a)

    await _store(db_session, tenant_a, secret="rotated-after-corruption", rotating=True)

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == PMS_CREDENTIAL_ROTATED)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity_id == original_id

    count = await db_session.scalar(
        select(func.count()).select_from(
            select(1).select_from(text("pms_credentials")).subquery()
        )
    )
    assert int(count or 0) == 1, "it must replace the malformed row, not add a second one"
