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
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.integrations.domain.entities import (
    PmsCredential,
    QueuedWebhookEvent,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventFailure,
)
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope


class WebhookEventRepository(Protocol):
    """The queue of received notices (PRD §7.26).

    `add` takes `tenant_id` **on the entity and not as a separate argument**, unlike every other
    port in this module, and the asymmetry is forced by the table: `webhook_events.tenant_id` is
    the one nullable tenant column in the schema, because §7.26 requires a notice that cannot be
    attributed to be recorded rather than dropped (R1.8). A `tenant_id` parameter would have to
    accept `None`, which is exactly the signature that invites a caller to pass it by accident.

    The reading half arrived with the processing job (§4). Every method here runs on a session
    that was **never marked**, and for this table that is not a convention but a correctness
    requirement: `tenant_id` is nullable, so a marked session's `tenant_id = X` predicate hides
    the `NULL` rows silently rather than erroring, and those are precisely the rows D11 has to
    reach in order to exhaust them.
    """

    async def add(self, event: WebhookEvent) -> None:
        """Persist one notice with `processed=False`.

        No tenant scoping and no `bind_session_to_tenant`: the caller is an anonymous request that
        has just resolved a tenant from a route token, and marking the session mid-request is the
        half-marked state `app/core/db.py` guards against (design D1). The `tenant_id` written is
        the one the token resolved, never anything the caller supplied.
        """
        ...

    async def select_pending(
        self, *, now: datetime, limit: int
    ) -> list[QueuedWebhookEvent]:
        """The batch this run may process, oldest first (R5.1, R5.3, D9).

        `processed = FALSE AND attempts < MAX_WEBHOOK_ATTEMPTS AND (next_attempt_at IS NULL OR
        next_attempt_at <= now)` — the three predicates of D9 in one place. The middle one is what
        keeps a poisoned notice from being retried forever, and the last is the backoff: a notice
        that just failed is invisible until its wait has passed, so it does not consume the batch
        on every tick.

        Returns `QueuedWebhookEvent`, which carries no payload. See that type for why.
        """
        ...

    async def mark_processed(
        self, event_ids: Sequence[uuid.UUID], *, now: datetime
    ) -> None:
        """`processed = TRUE`, `processed_at = now`, for a whole group at once (R5.1).

        Grouped rather than one call per notice because the outcome is grouped: a re-read serves
        every notice that named the same destination (D10), so they succeed or fail together.
        """
        ...

    async def record_failure(
        self,
        event_ids: Sequence[uuid.UUID],
        *,
        failure: WebhookEventFailure,
        next_attempt_at: datetime,
    ) -> None:
        """Charge one failed attempt and schedule the retry (R5.3).

        `attempts` is incremented **in SQL** rather than written from a value this process read,
        so two runs that somehow overlap cannot both write `attempts = 1`. Leaves `processed`
        alone: an exhausted notice stays `FALSE` with its cause in `error`, which is what R5.3
        asks for and what makes the queue readable as "these never landed".
        """
        ...

    async def exhaust(
        self, event_ids: Sequence[uuid.UUID], *, failure: WebhookEventFailure
    ) -> None:
        """Spend the whole retry budget at once, for a failure that retrying cannot fix (D11).

        The one caller is the `tenant_id IS NULL` branch: there is no tenant to attribute a
        reservation to, so the next attempt would fail identically. Setting `attempts` to the
        maximum is what takes it out of `select_pending` for good — visible for diagnosis,
        never selected again.
        """
        ...


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

        Raises `CrossTenantWriteError` when the endpoint belongs to another tenant, and
        `WebhookEndpointAlreadyExistsError` when an insert collides with the
        `(tenant_id, provider)` uniqueness. The second one is raised by the **constraint**, not by
        a prior read: `find_for` narrows the common case to a clean refusal, but two concurrent
        creations both pass it and only one can pass the index, so the adapter is where the
        refusal becomes race-free.
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
