import json
import re
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
    # `WebhookEventFailure`, never `str`, and the type IS the guarantee (R4.3, rule 11). Typed
    # `str | None` this field made `WebhookEventFailure` advice rather than a contract: the next
    # writer — the processing job of D11 — could have written `error=f"could not map {payload}"`
    # and reintroduced through the text column exactly what `payload` had just dropped. The
    # security panel of section 2 pointed out that a class nothing forces you to use guarantees
    # nothing. The adapter renders it on the way to the column.
    # Quoted because `WebhookEventFailure` is declared below: the alternative is reordering this
    # module so a value object precedes the entity that uses it, which reads worse than one pair
    # of quotes. Dataclasses store annotations without evaluating them.
    error: "WebhookEventFailure | None" = None


@dataclass(frozen=True)
class WebhookEventFailure:
    """What may be written to `webhook_events.error` — a code and a field name, never prose.

    `error` is one of the six cleartext sinks of rule 11, and the model's own docstring states the
    trap: *"`error` must never echo the raw body back: that would reintroduce through the text
    column what `payload` just dropped"*. A message built by interpolating whatever failed is
    exactly that echo, and it is the natural thing to write — `f"could not map {row}"` reads like
    good diagnostics right up until `row` holds a PAN.

    So the type carries no free-text field at all. `code` comes from a closed set and `field` is a
    key **name**, never its value. That makes the guarantee structural rather than a rule each
    writer has to remember, the same way `ChangeSet` makes rule 11 hold for `audit_logs.changes`.

    Rendered as compact JSON because the column is text: a reader gets a shape it can parse, and a
    writer gets no room to append.
    """

    code: str
    field: str | None = None

    def __post_init__(self) -> None:
        if self.code not in WEBHOOK_FAILURE_CODES:
            raise ValueError(
                f"unknown webhook failure code {self.code!r}; add it to WEBHOOK_FAILURE_CODES "
                "rather than passing a message — rule 11 forbids free text in this column"
            )
        # `field` was a plain unvalidated string until the security panel of section 2 pointed out
        # that the guarantee above then stopped one level short: a writer could pass
        # `field=f"guest.document_number={value}"` and carry a rule-3 value into the column
        # through the very type that exists to make that impossible. A dotted path of identifiers
        # is what a key name looks like, and nothing else fits — no spaces, no `=`, no punctuation
        # to hide a value behind. Latent when it was found (nothing writes `error` yet), and
        # closed here rather than when the processing job makes it live.
        if self.field is not None and not _IS_FIELD_PATH.fullmatch(self.field):
            raise ValueError(
                f"webhook failure field {self.field!r} is not a field NAME. Record the key that "
                "failed, never its value (rule 11): a dotted path of identifiers, like "
                "'guarantee.card_number'."
            )

    def render(self) -> str:
        payload = {"code": self.code}
        if self.field is not None:
            payload["field"] = self.field
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


UNATTRIBUTED = "UNATTRIBUTED"
"""The notice carries no tenant, so it can never become a reservation (D11, R1.8).

Should not occur while the authentication of R1 stands — the token is what resolves the tenant —
but §7.26 allows the row, so the branch stays honest rather than pretending it cannot happen.
"""

UNMAPPABLE = "UNMAPPABLE"
"""The re-read produced something the ingest could not turn into a reservation."""

PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
"""The provider could not be re-read within the retry budget."""

_IS_FIELD_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
"""What a key NAME looks like, and nothing a value could hide behind."""

WEBHOOK_FAILURE_CODES = frozenset({UNATTRIBUTED, UNMAPPABLE, PROVIDER_UNAVAILABLE})
"""Closed on purpose, like `app/audit/domain/actions.py`'s vocabulary and for the same reason:
an open set of codes is a free-text field with extra steps."""


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
