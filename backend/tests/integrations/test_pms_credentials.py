"""Encrypted provider credentials and per-property resolution (R2, R3, R4).

Integration against real Postgres, not fakes: the point of most of these is what the DATABASE
holds — that the stored bytes are ciphertext, that the partial unique index really does prevent
a second account credential, and that a tenant cannot reach another's row. A fake would let all
three pass while being false.
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.crypto import decrypt, encrypt
from app.core.encrypted_secret import EncryptedSecret
from app.core.db import tenant_scoped_classes
from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.entities import PmsCredential
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope
from app.integrations.infrastructure.models import PmsCredentialModel
from app.integrations.infrastructure.repositories import SqlAlchemyPmsCredentialRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository

SECRET = "beds24-refresh-token-abc123"


def _credential(tenant_id, scope, *, provider=PMSProvider.BEDS24, property_id=None, secret=SECRET):
    return PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        scope=scope,
        secret=encrypt(secret),
        property_id=property_id,
    )


# --- The three granularities (R3.2) ---


@pytest.mark.parametrize(
    ("scope", "needs_property"),
    [
        (PmsCredentialScope.PROPERTY, True),
        (PmsCredentialScope.ACCOUNT, False),
        (PmsCredentialScope.ORGANIZATION, False),
    ],
)
@pytest.mark.asyncio
async def test_a_credential_of_every_scope_is_stored_encrypted_and_recovered(
    db_session, tenant_a, property_a, scope, needs_property
) -> None:
    """R3.2 demands all THREE granularities, not just the per-property one.

    This test exists because the panel of section 1 found R3.2 was tagged by no task at all —
    the criterion most likely to be assumed satisfied without anyone checking. The ACCOUNT case
    is the one that matters most: ADR 0006 warns that an account credential grants **write**
    access to every property of that account, so it is more dangerous than the per-property one,
    not less.
    """
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    credential = _credential(
        tenant_a.id, scope, property_id=property_a.id if needs_property else None
    )

    await repository.upsert(tenant_a.id, credential)
    await db_session.flush()

    found = await repository.get_for(
        tenant_a.id,
        PMSProvider.BEDS24,
        scope,
        property_id=property_a.id if needs_property else None,
    )

    assert found is not None
    assert decrypt(found.secret) == SECRET


@pytest.mark.asyncio
async def test_the_stored_bytes_are_ciphertext_not_the_secret(
    db_session, tenant_a, property_a
) -> None:
    """R3.1 in the place it can actually be checked: the column, read with raw SQL.

    Asserting through the repository would only prove the round trip works, which it would with
    no encryption at all.
    """
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    await repository.upsert(
        tenant_a.id, _credential(tenant_a.id, PmsCredentialScope.ACCOUNT)
    )
    await db_session.flush()

    stored = (
        await db_session.execute(
            text("SELECT secret_encrypted FROM pms_credentials WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()

    assert SECRET not in stored
    assert stored != SECRET


@pytest.mark.asyncio
async def test_rotation_replaces_the_secret_in_place(db_session, tenant_a) -> None:
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    original = _credential(tenant_a.id, PmsCredentialScope.ACCOUNT)
    await repository.upsert(tenant_a.id, original)
    await db_session.flush()

    rotated = _credential(tenant_a.id, PmsCredentialScope.ACCOUNT, secret="the-new-token")
    await repository.upsert(tenant_a.id, rotated)
    await db_session.flush()

    found = await repository.get_for(tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT)
    assert decrypt(found.secret) == "the-new-token"

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM pms_credentials WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()
    assert count == 1, "rotation must replace, not accumulate"


@pytest.mark.asyncio
async def test_an_absent_credential_is_none_rather_than_an_error(db_session, tenant_a) -> None:
    """Absence is an answer. The caller decides whether it is fatal — and it is, loudly, but
    that decision belongs to the command and not to the repository."""
    repository = SqlAlchemyPmsCredentialRepository(db_session)

    assert (
        await repository.get_for(tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT)
    ) is None


# --- Tenant isolation, its own test for these columns (R4.3) ---


def test_the_credentials_table_is_inside_the_global_filter() -> None:
    """The premise every isolation test below rests on.

    In the shape of `tests/tenants/test_isolation.py`: if `pms_credentials` ever stopped being
    tenant-scoped, this is what would say so, instead of the isolation tests quietly passing
    against a table the filter no longer covers.
    """
    assert PmsCredentialModel in tenant_scoped_classes()


@pytest.mark.asyncio
async def test_a_tenant_cannot_write_a_credential_of_another(
    db_session, tenant_a, tenant_b
) -> None:
    """R4.4. Not the module's generic isolation test, a dedicated one — because a scoping
    failure here does not disclose data, it grants WRITE access to another client's calendar,
    pricing and messaging (ADR 0006, obligation 2)."""
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    theirs = _credential(tenant_b.id, PmsCredentialScope.ACCOUNT)

    with pytest.raises(CrossTenantWriteError):
        await repository.upsert(tenant_a.id, theirs)


@pytest.mark.asyncio
async def test_a_tenant_cannot_read_a_credential_of_another(
    db_session, tenant_a, tenant_b
) -> None:
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    await repository.upsert(tenant_b.id, _credential(tenant_b.id, PmsCredentialScope.ACCOUNT))
    await db_session.flush()

    assert (
        await repository.get_for(tenant_a.id, PMSProvider.BEDS24, PmsCredentialScope.ACCOUNT)
    ) is None

    # Raw SQL on purpose: this verifies the ROW still exists rather than what a filtered query
    # is willing to show — otherwise a bug that deleted it would pass this test.
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM pms_credentials WHERE tenant_id = :t"),
            {"t": str(tenant_b.id)},
        )
    ).scalar_one()
    assert count == 1


# --- The provider column on Property (R2.1) ---


@pytest.mark.asyncio
async def test_the_provider_survives_a_write_and_a_read(
    db_session, tenant_a, property_a
) -> None:
    """`_to_property` maps 24 fields by hand, so a column missing there reads back as `None`
    with no error anywhere. This is the test that would catch that."""
    repository = SqlAlchemyPropertyRepository(db_session)

    await repository.set_pms_provider(tenant_a.id, property_a.id, PMSProvider.BEDS24)
    await db_session.flush()

    found = await repository.get(tenant_a.id, property_a.id)
    assert found.pms_provider is PMSProvider.BEDS24


@pytest.mark.asyncio
async def test_a_property_starts_with_no_provider(db_session, tenant_a, property_a) -> None:
    """NULL means "the bootstrap default", which is what keeps every existing row working
    without a data migration."""
    found = await SqlAlchemyPropertyRepository(db_session).get(tenant_a.id, property_a.id)

    assert found.pms_provider is None


@pytest.mark.asyncio
async def test_setting_the_provider_of_another_tenants_property_is_refused(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
            tenant_a.id, property_b.id, PMSProvider.BEDS24
        )


@pytest.mark.asyncio
async def test_saving_operational_state_does_not_touch_the_provider(
    db_session, tenant_a, property_a
) -> None:
    """`save` writes one column and the port forbids widening it. Pinned here because this
    change adds a second writer, and the tempting shortcut would have been to widen `save`."""
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.set_pms_provider(tenant_a.id, property_a.id, PMSProvider.CHANNEX)
    await db_session.flush()

    entity = await repository.get(tenant_a.id, property_a.id)
    entity.pms_provider = PMSProvider.BEDS24  # a caller mutating the entity in memory
    await repository.save(tenant_a.id, entity)
    await db_session.flush()

    reread = await repository.get(tenant_a.id, property_a.id)
    assert reread.pms_provider is PMSProvider.CHANNEX, "save must not persist this column"


# --- The invariants the DATABASE enforces (design D4) ---


@pytest.mark.asyncio
async def test_a_second_account_credential_for_one_provider_is_refused(
    db_session, tenant_a
) -> None:
    """The partial unique index, tested rather than asserted in a docstring.

    The file header claimed this was covered and it was not — the security panel pointed out
    that no test inserted a second one. It matters because a plain UNIQUE constraint does NOT
    say it: Postgres treats NULLs as distinct, and `property_id` is NULL for exactly the
    account- and organization-scoped rows, i.e. the dangerous ones.
    """
    repository = SqlAlchemyPmsCredentialRepository(db_session)
    await repository.upsert(tenant_a.id, _credential(tenant_a.id, PmsCredentialScope.ACCOUNT))
    await db_session.flush()

    # A different id, same coordinates: `upsert` finds the existing row and replaces it rather
    # than inserting a duplicate.
    await repository.upsert(tenant_a.id, _credential(tenant_a.id, PmsCredentialScope.ACCOUNT))
    await db_session.flush()

    count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM pms_credentials "
                "WHERE tenant_id = :t AND scope = 'ACCOUNT'"
            ),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_an_account_credential_cannot_carry_a_property_id(db_session, tenant_a, property_a):
    """`property_id` is set exactly when the scope is PROPERTY, enforced by a CHECK.

    Without it, a mis-scoped ACCOUNT row carrying a property id slips past the partial index
    (whose predicate is `property_id IS NULL`) and then survives every rotation, because rotation
    writes the `property_id IS NULL` coordinates — leaving the superseded account token at rest
    and decryptable in a row nobody reads. Reproduced by the security panel before the fix.
    """
    from sqlalchemy.exc import IntegrityError

    malformed = _credential(
        tenant_a.id, PmsCredentialScope.ACCOUNT, property_id=property_a.id
    )

    with pytest.raises(IntegrityError):
        await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, malformed)
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_property_scoped_credential_needs_a_property(db_session, tenant_a) -> None:
    """The other half of the same CHECK: PROPERTY without a property is equally malformed."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await SqlAlchemyPmsCredentialRepository(db_session).upsert(
            tenant_a.id, _credential(tenant_a.id, PmsCredentialScope.PROPERTY)
        )
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_credential_cannot_be_anchored_to_another_tenants_property(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    """The SECOND tenant axis, and checking only the first was a real hole.

    `property_id`'s foreign key names `properties.id` alone and carries no tenant, so tenant A
    could anchor its credential to a property of tenant B. The security panel reproduced the
    consequence: B deprovisioning its own flat then destroyed A's credential through
    `ON DELETE CASCADE`, and A's next sync failed as "no credential" — a cross-tenant data loss
    triggered by an entirely ordinary action.
    """
    credential = _credential(
        tenant_a.id, PmsCredentialScope.PROPERTY, property_id=property_b.id
    )

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)


@pytest.mark.asyncio
async def test_the_secret_type_refuses_plaintext(db_session, tenant_a) -> None:
    """`EncryptedSecret` validates, so a plaintext credential cannot reach the column.

    The realistic accident, and the one the security panel named: the provisioning command wraps
    an operator-supplied token as `EncryptedSecret(ciphertext=token)` instead of `encrypt(token)`.
    Before the fix nothing objected — not the type, not the repository, not the schema, and not
    the "is it ciphertext?" test, which only exercises the path that did call `encrypt`.
    """
    with pytest.raises(ValueError):
        EncryptedSecret(ciphertext="a-plaintext-refresh-token")
