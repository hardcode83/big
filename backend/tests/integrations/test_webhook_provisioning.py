"""Minting and rotating a tenant's webhook material (`reservations-webhooks` R2, D3).

These drive the use cases directly, without FastAPI: what R2 promises — that both secrets are
generated per tenant, that they come back exactly once, that rotation kills the previous pair and
that neither value survives in `audit_logs` — is a property of the application layer, and testing
it through HTTP would only add a way for the test to pass because a router happened to filter a
field. The endpoint's own concerns (RBAC, status codes, the response shape) are task 1.6.
"""

import uuid

import pytest
from sqlalchemy import select, text

from app.audit.domain.actions import (
    ENTITY_WEBHOOK_ENDPOINT,
    WEBHOOK_ENDPOINT_CREATED,
    WEBHOOK_ENDPOINT_ROTATED,
)
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.domain.enums import UserRole
from app.core.crypto import decrypt
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.application.use_cases import (
    CreateWebhookEndpointUseCase,
    RotateWebhookEndpointUseCase,
)
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import (
    WebhookEndpointAlreadyExistsError,
    WebhookEndpointNotFoundError,
)
from app.integrations.domain.webhook_auth import hash_webhook_token
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
)
from tests.auth.conftest import utc_now

HEADER_NAME = "X-Beds24-Secret"
ACTOR_IP = "203.0.113.7"


def _create(db_session) -> CreateWebhookEndpointUseCase:
    return CreateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


def _rotate(db_session) -> RotateWebhookEndpointUseCase:
    return RotateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


async def _provision(db_session, tenant, actor, provider=PMSProvider.BEDS24):
    return await _create(db_session).execute(
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        actor_ip=ACTOR_IP,
        provider=provider,
        header_name=HEADER_NAME,
        now=utc_now(),
    )


async def _audit_rows(db_session, tenant_id: uuid.UUID) -> list[AuditLogModel]:
    result = await db_session.execute(
        select(AuditLogModel)
        .where(AuditLogModel.tenant_id == tenant_id)
        .where(AuditLogModel.entity_type == ENTITY_WEBHOOK_ENDPOINT)
        .order_by(AuditLogModel.created_at)
    )
    return list(result.scalars())


@pytest.fixture
def actor_a(users_by_role_a):
    return users_by_role_a[UserRole.PROPERTY_MANAGER]


# --- Creation (R2.1, R2.2, R2.3) ---


@pytest.mark.asyncio
async def test_creation_returns_both_secrets_and_stores_neither_in_cleartext(
    db_session, tenant_a, actor_a
) -> None:
    """R2.2 and R2.3 together: what comes back is usable, what is stored is not readable.

    The two assertions have to be made against the SAME pair, which is why they are one test:
    "the response has a token" and "the column holds a digest" are both satisfiable by a bug that
    stores the digest of a *different* token.
    """
    material = await _provision(db_session, tenant_a, actor_a)

    stored = (
        await db_session.execute(
            text(
                "SELECT token_hash, header_secret_encrypted FROM webhook_endpoints "
                "WHERE tenant_id = :t"
            ),
            {"t": str(tenant_a.id)},
        )
    ).one()

    assert stored.token_hash == hash_webhook_token(material.webhook_token)
    assert material.webhook_token not in stored.token_hash
    assert material.header_secret not in stored.header_secret_encrypted

    endpoint = await SqlAlchemyWebhookEndpointRepository(db_session).get(
        tenant_a.id, material.endpoint_id
    )
    assert endpoint is not None
    assert decrypt(endpoint.header_secret) == material.header_secret


@pytest.mark.asyncio
async def test_two_tenants_get_different_material(
    db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    """R2.1: distinct per tenant, and no global constant for either secret.

    A constant would pass every other test in this file — it stores, it decrypts, it rotates —
    while making one tenant's token authenticate every other tenant's webhooks.
    """
    mine = await _provision(db_session, tenant_a, users_by_role_a[UserRole.PROPERTY_MANAGER])
    theirs = await _provision(db_session, tenant_b, users_by_role_b[UserRole.PROPERTY_MANAGER])

    assert mine.webhook_token != theirs.webhook_token
    assert mine.header_secret != theirs.header_secret


@pytest.mark.asyncio
async def test_the_token_and_the_header_secret_are_not_the_same_value(
    db_session, tenant_a, actor_a
) -> None:
    """The two halves of rule 12 are meant to fail independently.

    "(a) y (b) se sostienen mutuamente: si el secreto se filtra queda la ruta, y si la ruta se
    adivina queda el secreto" — which is false the moment one is derived from the other.
    """
    material = await _provision(db_session, tenant_a, actor_a)

    assert material.webhook_token != material.header_secret


@pytest.mark.asyncio
async def test_creating_a_second_endpoint_for_a_provider_is_refused(
    db_session, tenant_a, actor_a
) -> None:
    """And, crucially, the live material still works afterwards.

    `upsert` would have overwritten it: the first integration would start receiving 404s with
    nothing anywhere saying why, while the operator read "created".
    """
    first = await _provision(db_session, tenant_a, actor_a)

    with pytest.raises(WebhookEndpointAlreadyExistsError):
        await _provision(db_session, tenant_a, actor_a)

    found = await SqlAlchemyWebhookEndpointRepository(db_session).find_by_token_hash(
        PMSProvider.BEDS24, hash_webhook_token(first.webhook_token)
    )
    assert found is not None


@pytest.mark.asyncio
async def test_one_tenant_can_hold_an_endpoint_per_provider(
    db_session, tenant_a, actor_a
) -> None:
    """The refusal above is keyed on (tenant, provider), not on tenant."""
    beds24 = await _provision(db_session, tenant_a, actor_a, provider=PMSProvider.BEDS24)
    channex = await _provision(db_session, tenant_a, actor_a, provider=PMSProvider.CHANNEX)

    assert beds24.endpoint_id != channex.endpoint_id


# --- Rotation (R2.4, design D3) ---


@pytest.mark.asyncio
async def test_rotation_invalidates_the_previous_material(
    db_session, tenant_a, actor_a
) -> None:
    """R2.4 in its own words, and D3's "sin ventana de gracia" in the same breath.

    Both halves are checked: the old token must stop resolving AND the old header secret must be
    gone, because a rotation that replaced only the token would leave the leaked secret live.
    """
    old = await _provision(db_session, tenant_a, actor_a)

    new = await _rotate(db_session).execute(
        tenant_id=tenant_a.id,
        actor_user_id=actor_a.id,
        actor_ip=ACTOR_IP,
        endpoint_id=old.endpoint_id,
        now=utc_now(),
    )

    repository = SqlAlchemyWebhookEndpointRepository(db_session)
    assert (
        await repository.find_by_token_hash(
            PMSProvider.BEDS24, hash_webhook_token(old.webhook_token)
        )
    ) is None

    rotated = await repository.find_by_token_hash(
        PMSProvider.BEDS24, hash_webhook_token(new.webhook_token)
    )
    assert rotated is not None
    assert rotated.id == old.endpoint_id
    assert decrypt(rotated.header_secret) == new.header_secret
    assert new.header_secret != old.header_secret
    assert rotated.rotated_at is not None


@pytest.mark.asyncio
async def test_rotation_keeps_the_provider_header_name(
    db_session, tenant_a, actor_a
) -> None:
    """`header_name` is the provider's, not ours: rotating material must not silently move it."""
    created = await _provision(db_session, tenant_a, actor_a)

    rotated = await _rotate(db_session).execute(
        tenant_id=tenant_a.id,
        actor_user_id=actor_a.id,
        actor_ip=ACTOR_IP,
        endpoint_id=created.endpoint_id,
        now=utc_now(),
    )

    assert rotated.header_name == HEADER_NAME


@pytest.mark.asyncio
async def test_rotating_an_unknown_endpoint_is_refused(db_session, tenant_a, actor_a) -> None:
    with pytest.raises(WebhookEndpointNotFoundError):
        await _rotate(db_session).execute(
            tenant_id=tenant_a.id,
            actor_user_id=actor_a.id,
            actor_ip=ACTOR_IP,
            endpoint_id=uuid.uuid4(),
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_a_tenant_cannot_rotate_another_tenants_endpoint(
    db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    """Rule 1, and here a scoping failure would concede control rather than disclose data.

    Rotating a neighbour's endpoint would hand their live integration a 404 on every webhook and
    hand the attacker a working token for the tenant they do not own.
    """
    theirs = await _provision(
        db_session, tenant_b, users_by_role_b[UserRole.PROPERTY_MANAGER]
    )

    with pytest.raises(WebhookEndpointNotFoundError):
        await _rotate(db_session).execute(
            tenant_id=tenant_a.id,
            actor_user_id=users_by_role_a[UserRole.PROPERTY_MANAGER].id,
            actor_ip=ACTOR_IP,
            endpoint_id=theirs.endpoint_id,
            now=utc_now(),
        )

    still_live = await SqlAlchemyWebhookEndpointRepository(db_session).find_by_token_hash(
        PMSProvider.BEDS24, hash_webhook_token(theirs.webhook_token)
    )
    assert still_live is not None


# --- The audit trail (R2.4, rule 9, rule 11) ---


@pytest.mark.asyncio
async def test_both_operations_are_audited_with_the_acting_person(
    db_session, tenant_a, actor_a
) -> None:
    """Rule 9 wants the "quién", so the row carries the user and the IP, not just the fact."""
    created = await _provision(db_session, tenant_a, actor_a)
    await _rotate(db_session).execute(
        tenant_id=tenant_a.id,
        actor_user_id=actor_a.id,
        actor_ip=ACTOR_IP,
        endpoint_id=created.endpoint_id,
        now=utc_now(),
    )

    rows = await _audit_rows(db_session, tenant_a.id)

    assert [row.action for row in rows] == [
        WEBHOOK_ENDPOINT_CREATED,
        WEBHOOK_ENDPOINT_ROTATED,
    ]
    for row in rows:
        assert row.entity_id == created.endpoint_id
        assert row.actor_user_id == actor_a.id
        assert row.actor_ip == ACTOR_IP


@pytest.mark.asyncio
async def test_no_secret_survives_in_the_audit_diff(db_session, tenant_a, actor_a) -> None:
    """Rule 11: "el valor no sobrevive en absoluto", not even the ciphertext or the digest.

    `token_hash` is on the denylist for a reason worth re-stating here, because it is the one an
    author would relax: it is already a digest, so it looks harmless — but it is the lookup key
    of a route whose non-guessability IS rule 12(b), and an `old`/`new` pair of them in
    `audit_logs` is a permanent record of every route this tenant has ever had.
    """
    created = await _provision(db_session, tenant_a, actor_a)
    rotated = await _rotate(db_session).execute(
        tenant_id=tenant_a.id,
        actor_user_id=actor_a.id,
        actor_ip=ACTOR_IP,
        endpoint_id=created.endpoint_id,
        now=utc_now(),
    )

    rows = await _audit_rows(db_session, tenant_a.id)
    rendered = str([row.changes for row in rows])

    for secret in (
        created.webhook_token,
        created.header_secret,
        rotated.webhook_token,
        rotated.header_secret,
        hash_webhook_token(created.webhook_token),
        hash_webhook_token(rotated.webhook_token),
    ):
        assert secret not in rendered

    for row in rows:
        assert row.changes["token_hash"] == {"changed": True}
        assert row.changes["header_secret_encrypted"] == {"changed": True}


@pytest.mark.asyncio
async def test_the_header_name_is_diffed_because_it_is_not_a_secret(
    db_session, tenant_a, actor_a
) -> None:
    """The deliberate asymmetry: an operational fact stays readable in the trail."""
    await _provision(db_session, tenant_a, actor_a)

    row = (await _audit_rows(db_session, tenant_a.id))[0]

    assert row.changes["header_name"] == {"old": None, "new": HEADER_NAME}
