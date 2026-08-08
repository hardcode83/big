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


@dataclass(frozen=True)
class WebhookEndpoint:
    """The material that authenticates one tenant's incoming webhooks (rule 12(a)/(b), D2, D3).

    **Not a `PmsCredential`, and the difference is the direction of trust.** A `PmsCredential`
    holds a secret the *provider* gave us; this holds one *we minted for the provider to
    authenticate itself to us*. That is what the narrow exception of rule 3(a) is about — the
    secret "que un operador debe copiar al panel del proveedor" may be returned once, at creation
    and on each rotation, which is a licence the provider's own credentials never get. Two
    contracts of exposure in one table would have been one column with two rules.

    It holds `header_secret` as an `EncryptedSecret` and, like `PmsCredential`, offers **no way
    back to cleartext**: `app.core.crypto.decrypt` is the single chokepoint, which is what lets
    rule 3(a) and the audit obligation attach anywhere at all.

    `token_hash` and not the token (D3): a dump of this table must not hand over the route, or
    rule 12(b) stops being a defence independent of 12(a).

    Frozen, unlike `PmsCredential`: nothing mutates an endpoint in place. A rotation writes a new
    token hash and a new secret over the row in one transaction (D3), so the aggregate is
    replaced rather than edited, and there is no partially-rotated state for anything to observe.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: PMSProvider
    token_hash: str
    header_name: str
    header_secret: EncryptedSecret
    rotated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse the two accidents a column definition cannot catch.

        `token_hash` is a `String(64)`, so the database would happily accept a **token** stored
        where its hash belongs — the one mistake that would defeat D3 completely, and the
        plausible one, since both are opaque strings of similar length that come from the same
        function call two lines apart. Checking the shape of a SHA-256 digest makes it impossible
        rather than merely discouraged, the same argument `EncryptedSecret.__post_init__` makes
        for Fernet ciphertext.

        A blank `header_name` is the other: rule 12(a) authenticates *by* that header, so an
        endpoint without one is an endpoint that cannot authenticate anything, and it would fail
        far away from here — as a `None` header value that `secrets_match` reads as a wrong
        secret, i.e. as a mysterious `404` on every legitimate webhook.
        """
        if len(self.token_hash) != _SHA256_HEX_LENGTH or not all(
            character in _HEX_DIGITS for character in self.token_hash
        ):
            raise ValueError(
                "token_hash must be a SHA-256 hex digest — build it with "
                "app.integrations.domain.webhook_auth.hash_webhook_token(), and never store "
                "the token itself"
            )
        if not self.header_name.strip():
            raise ValueError(
                "header_name must name the provider's static header (rule 12(a)); "
                "without it there is nothing to authenticate against"
            )


_SHA256_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


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
