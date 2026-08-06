"""SQLAlchemy adapter for `PmsCredentialRepository`.

Moved here from `properties/infrastructure/` after the architecture panel of sections 4-5: the
design's own "Changes by area" table always said `integrations`, and writing it next to the
property repository made this domain's aggregate someone else's responsibility.

No method commits: the transactional boundary is the use case, as everywhere else.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encrypted_secret import EncryptedSecret
from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.entities import PmsCredential
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope
from app.integrations.infrastructure.models import PmsCredentialModel
from app.properties.infrastructure.models import PropertyModel


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
                PmsCredentialModel.tenant_id == tenant_id,
                PmsCredentialModel.provider == provider,
                PmsCredentialModel.scope == scope,
                # `is_(None)` and not `== None`: for the account and organization scopes the
                # column IS NULL, and `= NULL` is never true in SQL.
                PmsCredentialModel.property_id.is_(None)
                if property_id is None
                else PmsCredentialModel.property_id == property_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_credential(model)

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
                PmsCredentialModel.tenant_id == tenant_id,
                PmsCredentialModel.provider == credential.provider,
                PmsCredentialModel.scope == credential.scope,
                PmsCredentialModel.property_id.is_(None)
                if credential.property_id is None
                else PmsCredentialModel.property_id == credential.property_id,
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


def _to_credential(model: PmsCredentialModel) -> PmsCredential:
    return PmsCredential(
        id=model.id,
        tenant_id=model.tenant_id,
        provider=model.provider,
        scope=model.scope,
        secret=EncryptedSecret(ciphertext=model.secret_encrypted),
        property_id=model.property_id,
        rotated_at=model.rotated_at,
    )
