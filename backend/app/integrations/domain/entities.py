import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.encrypted_secret import EncryptedSecret
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope


@dataclass
class WebhookEvent:
    """`tenant_id` is optional (§7.26: "nullable si no está autenticado aún").

    A payload that cannot be attributed to a tenant is still recorded, so it can be
    reprocessed rather than lost. `provider` and `event_type` are free-form strings,
    not enums — the PRD types them as VARCHAR because the set of providers is open.
    """

    id: uuid.UUID
    provider: str
    event_type: str
    payload: dict[str, Any]
    received_at: datetime
    tenant_id: uuid.UUID | None = None
    processed: bool = False
    processed_at: datetime | None = None
    error: str | None = None


@dataclass
class PmsCredential:
    """One provider credential, at one granularity, for one tenant (ADR 0006 decision 7).

    Holds an `EncryptedSecret`, never cleartext. That is the whole point of the type: there is
    no attribute on this entity from which a plaintext credential can be read, so serialising
    the entity — the accident rule 3(a) forbids — cannot expose one. Turning it back into a
    string requires calling `app.core.crypto.decrypt`, which is the single place R4.2's audit
    obligation can attach to.

    `property_id` is set only when `scope` is `PROPERTY`; an account or organization credential
    has none, which is why it could not live in a column on `Property` without being duplicated
    across every row of that account — N copies to rotate, and a partial rotation leaving some
    properties authenticating with a dead token.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: PMSProvider
    scope: PmsCredentialScope
    secret: EncryptedSecret
    property_id: uuid.UUID | None = None
    rotated_at: datetime | None = None


@dataclass
class CredentialReadLog:
    """The credential ids a run decrypted, deduplicated. Owned by the CALLER, not the factory.

    Lives in `domain/` and not beside the factory that fills it: `application/` names it in a
    constructor signature, and `tests/test_layering.py` forbids `application/` importing
    `infrastructure/`. It is a plain collector of ids with no infrastructure in it, so the
    layer it was first written in was simply the wrong one.

    What this class is, and all it is: the deduplication **mechanism**. The granularity it serves
    — how many rows a run may write — is stated once in the named exception of rule 9 of
    `sdd/steering/security.md`, and neither this docstring nor any other paraphrases it. An
    earlier version did, and carried both an inverted granularity and a boundary condition the
    rule had already retired; it was one of five copies that made three reviews each find a
    different error in the same claim.

    Deduplicating by credential id is what makes the rule's allowance implementable: a sync over
    N properties served by one credential decrypts it N times, and the set collapses those to one
    entry per credential. What that entitles the caller to write is the rule's business, not this
    class's.
    """

    credential_ids: set[uuid.UUID] = field(default_factory=set)

    def record(self, credential: PmsCredential) -> None:
        self.credential_ids.add(credential.id)
