"""SQLAlchemy adapter for `PmsCredentialRepository`.

Moved here from `properties/infrastructure/` after the architecture panel of sections 4-5: the
design's own "Changes by area" table always said `integrations`, and writing it next to the
property repository made this domain's aggregate someone else's responsibility.

No method commits: the transactional boundary is the use case, as everywhere else.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import SecretDecryptionError
from app.core.encrypted_secret import EncryptedSecret
from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.entities import (
    MAX_WEBHOOK_ATTEMPTS,
    PmsCredential,
    QueuedWebhookEvent,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventFailure,
)
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope
from app.integrations.domain.errors import WebhookEndpointAlreadyExistsError
from app.integrations.infrastructure.models import (
    PmsCredentialModel,
    WebhookEndpointModel,
    WebhookEventModel,
)
from app.properties.infrastructure.models import PropertyModel

WEBHOOK_ENDPOINT_CONSTRAINT = "uq_webhook_endpoints_tenant_provider"


class SqlAlchemyWebhookEventRepository:
    """Adapter for `WebhookEventRepository`. The receiver writes the queue; the job drains it.

    Runs on an **unmarked** session by construction. That matters for the read side more than the
    write side — a marked session hides `tenant_id IS NULL` rows without erroring — and the
    boundary is pinned by `tests/test_tenant_filter.py` and by this module's own queue tests.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: WebhookEvent) -> None:
        self._session.add(
            WebhookEventModel(
                id=event.id,
                tenant_id=event.tenant_id,
                provider=event.provider,
                event_type=event.event_type,
                payload=event.payload,
                processed=event.processed,
                processed_at=event.processed_at,
                # `.render()` is the ONLY way a value reaches this column, which is what makes
                # rule 11's structured form a property of the type rather than of each caller
                # remembering. The column is `Text`; the entity is not.
                error=None if event.error is None else event.error.render(),
                received_at=event.received_at,
            )
        )

    async def select_pending(
        self, *, now: datetime, limit: int
    ) -> list[QueuedWebhookEvent]:
        rows = await self._session.execute(
            select(
                WebhookEventModel.id,
                WebhookEventModel.tenant_id,
                WebhookEventModel.provider,
                WebhookEventModel.received_at,
                WebhookEventModel.attempts,
            )
            .where(
                WebhookEventModel.processed.is_(False),
                WebhookEventModel.attempts < MAX_WEBHOOK_ATTEMPTS,
                or_(
                    WebhookEventModel.next_attempt_at.is_(None),
                    WebhookEventModel.next_attempt_at <= now,
                ),
            )
            # Oldest first, so a backlog drains in the order it arrived. It does NOT make the
            # processing order-dependent — D13 and R5.7 rest on the re-read and on the
            # ingestor's idempotency, not on this — it only keeps a starved notice from staying
            # starved behind newer ones.
            .order_by(WebhookEventModel.received_at)
            .limit(limit)
        )
        # Columns, not entities: the payload is not selected at all, so it never reaches this
        # process. `QueuedWebhookEvent` explains why that is the point rather than an
        # optimisation.
        return [QueuedWebhookEvent(*row) for row in rows]

    async def mark_processed(
        self, event_ids: Sequence[uuid.UUID], *, now: datetime
    ) -> None:
        if not event_ids:
            return
        await self._session.execute(
            update(WebhookEventModel)
            .where(WebhookEventModel.id.in_(event_ids))
            .values(processed=True, processed_at=now, error=None)
        )

    async def record_failure(
        self,
        event_ids: Sequence[uuid.UUID],
        *,
        failure: WebhookEventFailure,
        next_attempt_at: datetime,
    ) -> None:
        if not event_ids:
            return
        await self._session.execute(
            update(WebhookEventModel)
            .where(WebhookEventModel.id.in_(event_ids))
            .values(
                attempts=WebhookEventModel.attempts + 1,
                next_attempt_at=next_attempt_at,
                error=failure.render(),
            )
        )

    async def exhaust(
        self, event_ids: Sequence[uuid.UUID], *, failure: WebhookEventFailure
    ) -> None:
        if not event_ids:
            return
        await self._session.execute(
            update(WebhookEventModel)
            .where(WebhookEventModel.id.in_(event_ids))
            .values(attempts=MAX_WEBHOOK_ATTEMPTS, error=failure.render())
        )


class SqlAlchemyWebhookEndpointRepository:
    """Adapter for `WebhookEndpointRepository`. Stores ciphertext; never decrypts.

    Same contract as its sibling below: `app.core.crypto.decrypt` is the chokepoint, so a
    repository that decrypted on read would spread rule 3(a)'s obligation over every call site.

    **`find_by_token_hash` runs with no tenant, and that is the design and not a hole** (D1). It is
    the query that *resolves* the tenant, so there is nothing to scope it by yet: an incoming
    webhook carries no JWT. What makes it safe is not a filter, it is the shape of the key — 256
    bits of CSPRNG output behind a `UNIQUE` index, so the query addresses at most one row and
    guessing it is the thing rule 12(b) is betting against. Every other method takes `tenant_id`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_token_hash(
        self, provider: PMSProvider, token_hash: str
    ) -> WebhookEndpoint | None:
        result = await self._session.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.token_hash == token_hash,
                # `provider` is part of the WHERE and not merely of the route: a token minted for
                # one provider must not authenticate a webhook claiming to be another, or
                # `webhook_events.provider` becomes a column the caller chooses.
                WebhookEndpointModel.provider == provider,
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_endpoint(model)

    async def get(
        self, tenant_id: uuid.UUID, endpoint_id: uuid.UUID
    ) -> WebhookEndpoint | None:
        result = await self._session.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.tenant_id == tenant_id,
                WebhookEndpointModel.id == endpoint_id,
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_endpoint(model)

    async def find_for(
        self, tenant_id: uuid.UUID, provider: PMSProvider
    ) -> WebhookEndpoint | None:
        result = await self._session.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.tenant_id == tenant_id,
                WebhookEndpointModel.provider == provider,
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_endpoint(model)

    async def upsert(self, tenant_id: uuid.UUID, endpoint: WebhookEndpoint) -> None:
        if endpoint.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="webhook endpoint",
                entity_tenant_id=endpoint.tenant_id,
                acting_tenant_id=tenant_id,
            )

        existing = await self._session.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.tenant_id == tenant_id,
                WebhookEndpointModel.provider == endpoint.provider,
            )
        )
        model = existing.scalar_one_or_none()
        if model is None:
            self._session.add(
                WebhookEndpointModel(
                    id=endpoint.id,
                    tenant_id=endpoint.tenant_id,
                    provider=endpoint.provider,
                    token_hash=endpoint.token_hash,
                    header_name=endpoint.header_name,
                    header_secret_encrypted=endpoint.header_secret.ciphertext,
                    rotated_at=endpoint.rotated_at,
                )
            )
            # FLUSHES, and the flush is the point (the same shape `SqlAlchemyPropertyRepository.add`
            # uses for `uq_properties_tenant_id_internal_code`). **The constraint is the authority
            # on the duplicate, never the caller's prior read**: two concurrent creations for one
            # (tenant, provider) both pass `find_for`, and only one can pass the index. Without
            # this, the loser surfaced as an `IntegrityError` nobody handled — an unhandled `500`
            # instead of the `409` the operation promises, found by the QA panel of section 1,
            # which reproduced it with two concurrent sessions.
            #
            # Flushing here also puts the failure BEFORE the audit row is built, so a refused
            # creation leaves no `WEBHOOK_ENDPOINT_CREATED` trace of something that did not happen.
            try:
                await self._session.flush()
            except IntegrityError as error:
                if WEBHOOK_ENDPOINT_CONSTRAINT in str(error.orig):
                    raise WebhookEndpointAlreadyExistsError(
                        "tenant already has a webhook endpoint for that provider; "
                        "rotate it instead of creating a second one"
                    ) from error
                # Anything else is re-raised untranslated: a 409 blamed on a constraint the
                # client cannot see would be a lie it has no way to act on.
                raise
            return

        # Rotation: both secrets move together, in this one transaction, so nothing ever observes
        # a row whose token is new and whose header secret is old (design D3). No grace window —
        # the old material stops authenticating the moment this commits.
        model.token_hash = endpoint.token_hash
        model.header_name = endpoint.header_name
        model.header_secret_encrypted = endpoint.header_secret.ciphertext
        model.rotated_at = endpoint.rotated_at


class SqlAlchemyPmsCredentialRepository:
    """Adapter for `PmsCredentialRepository`. Stores ciphertext; never decrypts.

    Decryption belongs to the factory, which is the single chokepoint R4.2's audit obligation
    attaches to. A repository that decrypted on read would spread that obligation over every
    call site — the same argument that rejected a SQLAlchemy `TypeDecorator` in design D3.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for(
        self,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        scope: PmsCredentialScope,
        property_id: uuid.UUID | None = None,
    ) -> PmsCredential | None:
        result = await self._session.execute(
            select(PmsCredentialModel).where(
                *_at(tenant_id, provider, scope, property_id)
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_credential(model)

    async def id_at(
        self,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        scope: PmsCredentialScope,
        property_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Selects the id COLUMN, so a malformed stored value cannot reach `EncryptedSecret`.

        Not `get_for(...).id`: that is the same query plus a parse that can fail, and failing is
        the whole problem this method exists to avoid. Selecting the column makes the guarantee
        structural rather than a promise — there is no code path from here to a secret.
        """
        return await self._session.scalar(
            select(PmsCredentialModel.id).where(
                *_at(tenant_id, provider, scope, property_id)
            )
        )

    async def upsert(self, tenant_id: uuid.UUID, credential: PmsCredential) -> None:
        if credential.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="pms credential",
                entity_tenant_id=credential.tenant_id,
                acting_tenant_id=tenant_id,
            )

        # The SECOND tenant axis, and checking only the first was a real hole the security panel
        # reproduced: `property_id`'s foreign key names `properties.id` alone — it carries no
        # tenant — so a credential of tenant A could be anchored to a property of tenant B. The
        # damage was not hypothetical: B deprovisioning its own flat then destroyed A's stored
        # credential through `ON DELETE CASCADE`, and A's next sync failed as "no credential".
        #
        # The composite foreign key that would enforce this in the schema does not exist because
        # `properties` has no unique `(id, tenant_id)`; the same reason
        # `PropertyStateTransitionRepository` documents the precondition as the caller's.
        if credential.property_id is not None:
            owner = await self._session.execute(
                select(PropertyModel.id).where(
                    PropertyModel.id == credential.property_id,
                    PropertyModel.tenant_id == tenant_id,
                )
            )
            if owner.scalar_one_or_none() is None:
                raise CrossTenantWriteError(
                    entity="pms credential property",
                    entity_tenant_id="unknown",
                    acting_tenant_id=tenant_id,
                )

        existing = await self._session.execute(
            select(PmsCredentialModel).where(
                *_at(
                    tenant_id, credential.provider, credential.scope, credential.property_id
                )
            )
        )
        model = existing.scalar_one_or_none()
        if model is None:
            self._session.add(
                PmsCredentialModel(
                    id=credential.id,
                    tenant_id=credential.tenant_id,
                    provider=credential.provider,
                    scope=credential.scope,
                    property_id=credential.property_id,
                    secret_encrypted=credential.secret.ciphertext,
                    rotated_at=credential.rotated_at,
                )
            )
            return
        model.secret_encrypted = credential.secret.ciphertext
        model.rotated_at = credential.rotated_at


def _at(
    tenant_id: uuid.UUID,
    provider: PMSProvider,
    scope: PmsCredentialScope,
    property_id: uuid.UUID | None,
) -> tuple:
    """The coordinates of one credential, as WHERE clauses.

    Shared by the three queries that address a credential, so `id_at` cannot drift from `get_for`
    and start answering about a different row than the one `upsert` is about to overwrite.
    """
    return (
        PmsCredentialModel.tenant_id == tenant_id,
        PmsCredentialModel.provider == provider,
        PmsCredentialModel.scope == scope,
        # `is_(None)` and not `== None`: for the account and organization scopes the column IS
        # NULL, and `= NULL` is never true in SQL.
        PmsCredentialModel.property_id.is_(None)
        if property_id is None
        else PmsCredentialModel.property_id == property_id,
    )


def _to_credential(model: PmsCredentialModel) -> PmsCredential:
    """Row → entity, translating a malformed stored value into the port's vocabulary.

    `EncryptedSecret` refuses anything that is not a Fernet token, and it does so with a plain
    `ValueError` because it may not import `cryptography`. That `ValueError` was escaping every
    caller: it is not in the tuple `_sync_one_provider` catches, not in the raise set
    `PMSAdapterFactory.reservations_for` declares, and not caught by `pms_sync.main` — so one
    hand-written row (a plaintext credential inserted with SQL, which is exactly the path the
    credentials command exists to prevent) aborted the whole tenant's sync, killed the healthy
    providers' sync with it, and rolled back the `PMS_CREDENTIAL_READ` rows of reads that had
    already happened.

    The final security panel put it exactly right: **the refused half was the unhandled half.**
    The isolation test written for this only corrupted the ciphertext while preserving Fernet
    structure, so it exercised the half that was already handled.

    `SecretDecryptionError` is the right home: from the caller's side "the stored value will not
    decrypt" and "the stored value is not ciphertext at all" demand the same response — this
    provider cannot be used, report it and move on — and the port already declares that error.
    """
    try:
        secret = EncryptedSecret(ciphertext=model.secret_encrypted)
    except ValueError as error:
        # The message names neither the stored value nor any fragment of it.
        raise SecretDecryptionError(
            f"stored credential {model.id} is not valid ciphertext"
        ) from error

    return PmsCredential(
        id=model.id,
        tenant_id=model.tenant_id,
        provider=model.provider,
        scope=model.scope,
        secret=secret,
        property_id=model.property_id,
        rotated_at=model.rotated_at,
    )


def _to_endpoint(model: WebhookEndpointModel) -> WebhookEndpoint:
    """Row → entity, with the same translation of a malformed stored value as `_to_credential`.

    The `ValueError` that `EncryptedSecret` raises for a non-Fernet value must not escape as
    itself: the receiving path catches the domain's vocabulary, and an unhandled `ValueError`
    there would surface as a `500` on a public, unauthenticated endpoint — telling an anonymous
    caller that this particular route token exists and that its row is broken, which is exactly
    the oracle design D4 closes.

    `WebhookEndpoint.__post_init__` can also raise `ValueError`, for a `token_hash` that is not a
    digest or a blank `header_name`. Same treatment and the same reason: a row that cannot become
    an entity is a row that cannot authenticate anybody, which from the caller's side is
    indistinguishable from a token that does not exist — and that is precisely how it must look.
    """
    try:
        secret = EncryptedSecret(ciphertext=model.header_secret_encrypted)
        return WebhookEndpoint(
            id=model.id,
            tenant_id=model.tenant_id,
            provider=model.provider,
            token_hash=model.token_hash,
            header_name=model.header_name,
            header_secret=secret,
            rotated_at=model.rotated_at,
        )
    except ValueError as error:
        # Names the row, never the stored value or any fragment of it.
        raise SecretDecryptionError(
            f"stored webhook endpoint {model.id} is not usable"
        ) from error
