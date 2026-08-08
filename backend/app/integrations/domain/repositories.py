"""Ports owned by the integrations domain.

`PmsCredentialRepository` lives HERE and not in `properties/domain/`, which is where it was
first written. The architecture panel of sections 4-5 caught that: its entire vocabulary —
`PmsCredential`, `PMSProvider`, `PmsCredentialScope` — belongs to this domain, and `properties`
contributes only an optional foreign key, exactly the scalar relationship
`PropertyStateTransitionRepository` already handles without importing a foreign entity.

The misplacement was not merely untidy: it made `properties` the owner of another domain's
aggregate, and `infrastructure/pms_factory.py` then imported the port back out of `properties`,
a properties→integrations→properties round trip that did not exist before this change.
`tests/test_layering.py` does not catch it, because it checks layer direction within a domain
and not port ownership across domains.
"""

import uuid
from typing import Protocol

from app.integrations.domain.entities import PmsCredential, WebhookEndpoint
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope


class WebhookEndpointRepository(Protocol):
    """The per-tenant webhook authentication material (rule 12(a)/(b), design D2).

    **`find_by_token_hash` is the only read that runs without a tenant**, and that is not an
    oversight in the tenancy model — it is the inversion the rule requires. An incoming webhook
    carries no JWT, so there is nothing to scope the session by *until this lookup answers*: the
    token is what resolves the tenant. Its implementation therefore runs on a session that was
    never marked and filters by nothing but the hash, which is only safe because the hash is a
    256-bit random value and the method returns exactly one row (`UNIQUE`).

    Every other method takes `tenant_id` explicitly, like the rest of this module's ports.
    """

    async def find_by_token_hash(
        self, provider: PMSProvider, token_hash: str
    ) -> WebhookEndpoint | None:
        """The endpoint that owns this route token, or `None`.

        `provider` is part of the query and not merely of the route: a token minted for one
        provider must not authenticate a webhook claiming to be from another, or the `provider`
        column of `webhook_events` becomes attacker-controlled.

        `None` rather than raising, for the same reason `PmsCredentialRepository.get_for` returns
        it: absence is an answer. The caller — the receiving use case — turns every negative into
        the one indistinguishable failure of design D4, which is where that decision belongs.
        """
        ...

    async def get(
        self, tenant_id: uuid.UUID, endpoint_id: uuid.UUID
    ) -> WebhookEndpoint | None:
        """The endpoint by id, within the tenant. Used by rotation."""
        ...

    async def find_for(
        self, tenant_id: uuid.UUID, provider: PMSProvider
    ) -> WebhookEndpoint | None:
        """The endpoint at the `UNIQUE(tenant_id, provider)` coordinates, or `None`.

        Exists so creation can **refuse** rather than overwrite: `upsert` expresses "this is the
        material now", which is the right shape for rotation and the wrong one for a `POST` that
        would otherwise invalidate a live integration without saying so
        (`WebhookEndpointAlreadyExistsError`).
        """
        ...

    async def upsert(self, tenant_id: uuid.UUID, endpoint: WebhookEndpoint) -> None:
        """Store or replace the endpoint at its `(tenant, provider)` coordinates.

        Upsert for the same reason `PmsCredentialRepository.upsert` is one: the caller's intent is
        always "this is the material now", and a separate add would invite a read-then-write race
        on rotation. Rotation overwrites `token_hash` and `header_secret` together, in one
        transaction, so no half-rotated row is ever visible (design D3).

        Raises `CrossTenantWriteError` when the endpoint belongs to another tenant.
        """
        ...


class PmsCredentialRepository(Protocol):
    """Provider credentials, stored encrypted (ADR 0006 decision 7, R3/R4).

    Read `get_for` as "the credential this property's provider needs at this granularity". Where
    this port lives, and why it moved, is the module docstring above — not repeated here, because
    a sentence stating its own location in two places is how this one went stale in the first
    place: it still claimed to live in `properties/` fifteen lines below the paragraph explaining
    it no longer does.

    **No `list` and no `get_all`, deliberately.** Every read of a credential is an audited act
    (R4.2) and a decryption point, so a method that returns many of them would multiply both by
    the size of the portfolio. Callers resolve exactly the one they are about to use.
    """

    async def get_for(
        self,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        scope: PmsCredentialScope,
        property_id: uuid.UUID | None = None,
    ) -> PmsCredential | None:
        """The stored credential, or `None` when there is none.

        `None` rather than raising: absence is an answer the caller must handle, and the caller
        is the one that knows whether it is fatal. The command turns it into
        `MissingPmsCredentialError` and exits non-zero — never a silent fall back to the mock,
        which would report "created 0" and be indistinguishable from an empty PMS.

        Returns the ciphertext inside an `EncryptedSecret`. Decrypting is a separate, explicit
        act; this port never hands back cleartext.
        """
        ...

    async def id_at(
        self,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        scope: PmsCredentialScope,
        property_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """The id of the credential at these coordinates, or `None`. **Reads no secret.**

        Exists because "is something stored here, and which row is it" is a different question
        from "give me the credential", and only the second one needs the stored value to be
        readable. The provisioning command asks the first: it needs the id for the audit row and
        the presence for the rotate guard, and it is about to OVERWRITE the value, so whether the
        old one parses is irrelevant to it.

        Answering it through `get_for` made a malformed stored value unfixable by the only
        audited route that exists — the operator could neither `set` over it nor `rotate` it, and
        was pushed to the hand-written SQL this command exists to prevent, on the one occasion it
        matters most: replacing a credential that has leaked. Not decrypting is also why this
        method carries no R4.2 obligation — there is no read to audit.
        """
        ...

    async def upsert(self, tenant_id: uuid.UUID, credential: PmsCredential) -> None:
        """Store or replace the credential at its (provider, scope, property) coordinates.

        Upsert rather than add/update because the caller's intent is always "this is the
        credential now" — the provisioning command has no use for the distinction, and a
        separate `add` would invite a read-then-write race on rotation.

        Raises `CrossTenantWriteError` when the credential belongs to another tenant.
        """
        ...
