"""The PMS port (PRD §16, R3.1, design D1).

EXTERNAL_DEPENDENCY: the real providers (Octorate/Smoobu/Beds24) need credentials this
project does not have, so the MVP implementation is `MockPMSAdapter`. The interface is the
definitive one — `steering/architecture.md`: "MVP = implementaciones mock/manual con la
interfaz definitiva".

**Two methods of the eight in PRD §16**, deliberately. `update_price`, `block_dates`,
`get_availability`, `list_properties`, `get_messages` and `send_message` arrive with the
changes that consume them (`revenue`, `messaging-ai`); a port sized for everything it could
eventually do is the "StorageAdapter gigante con 15 métodos" that
`steering/backend-architecture.md` names as the Interface Segregation failure. The two here
keep PRD §16's signatures verbatim so the rest can be added without rewriting these.

**Two ports, not one** (ADR 0006 decision 3, change `pms-provider-resolution`): `PMSAdapter`
for reservations and ARI, `PMSMessagingPort` for conversations. The second is empty today —
fixing where each of PRD §16's remaining operations will land, before any of them exists, is
what makes the separation cost a class declaration instead of a refactor. PRD §16 puts them
all in one `Protocol` with a `# si soportado`, which is the shape this deviates from, and the
deviation is registered in that ADR.

Substitutability is a requirement, not a nicety (SOLID's L, spelled out in the steering):
the mock must raise what a real adapter raises and return the same shapes, so a use case
tested against it behaves the same in production.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from app.integrations.domain.dtos import ParseResult, PmsFetchResult, ReservationDTO
from app.integrations.domain.entities import CredentialReadLog
from app.integrations.domain.enums import PMSProvider

if TYPE_CHECKING:  # pragma: no cover - import only for the annotation
    # `Property` lives in another domain's `domain/` layer, and this port names it because
    # resolution is per property.
    #
    # **Not to break a cycle** — an earlier version of this comment claimed that and the
    # architecture panel checked: an eager import here succeeds today. It is guarded to keep the
    # dependency one-directional at runtime, so `integrations` describes a `Property` in a
    # signature without importing `properties` to run. If that ever stops being worth the
    # indirection, the honest fix is an eager import, not a comment inventing a cycle.
    from app.properties.domain.entities import Property


class PMSAdapter(Protocol):
    """Reservations and, later, ARI. **Messaging is NOT here** — see `PMSMessagingPort`.

    The split is ADR 0006 decision 3 and it is a Liskov obligation, not a preference: most of the
    eleven providers evaluated have no messaging API at all (Avantio and ICNEA none, Smoobu's
    Booking.com half broken), so a single Protocol would force them to implement it by raising
    `NotImplementedError`, which is exactly the substitution failure
    `steering/backend-architecture.md:108` forbids.
    """

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> PmsFetchResult:
        """Reservations created or changed since `since`, optionally for one property.

        `since` is explicit rather than read from a clock inside the adapter: the caller
        owns time, which is what lets the sync be replayed over a known window.

        Returns a `PmsFetchResult` rather than a bare list so an element the adapter could not
        map travels back with the ones it could (design D10). The previous shape reported those
        through an `unmappable_rows` attribute on the adapter itself — a mutable slot reset per
        call, which made the report a property of the object instead of the call, and let a
        caller that never read it drop rows in silence. Mapping each element separately and
        reporting the failures is required by `specs/reservations.md`; only the channel changed.
        """
        ...

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """One reservation by the provider's id; `None` when the provider has no such id."""
        ...


class PMSMessagingPort(Protocol):
    """Guest conversations through the PMS. Empty on purpose, and that is the deliverable.

    ADR 0006 decision 3 separates this from `PMSAdapter`; what this change delivers is the
    **boundary**, fixed before the methods land, because the six remaining operations of PRD §16
    do not exist yet. Fixing it now costs a class declaration; fixing it after `get_messages` had
    landed on `PMSAdapter` would be a refactor across every adapter and every consumer.

    What arrives here, and with which change:

    - `get_messages`, `send_message` → `pms-beds24-adapter`, the first provider with a real
      messaging API, followed by `messaging-ai` as its first consumer.

    What stays on `PMSAdapter` instead: `update_price`, `block_dates` and `get_availability`
    (ARI, arriving with `revenue`) and `list_properties`.

    A provider without messaging implements `PMSAdapter` and simply does not implement this. It is
    `PMSAdapterFactory.messaging_for` — defined below in this same file — that refuses, by raising
    `PMSMessagingUnsupportedError`, rather than an adapter method that exists in order to fail;
    and `supports_messaging` is the question to ask when the answer should not be an exception,
    pure by contract so that asking decrypts nothing (R4.2 makes a credential read an audited
    act).

    This paragraph was written in the future tense while the factory did not exist yet, and stayed
    that way after it did — claiming four lines above its own definition that it was still to
    come. Present tense now that it is present: a docstring describing a state the file has left
    is as misleading as one describing a state it never reached.

    Deliberately not `runtime_checkable`: the repo checks conformance structurally in tests
    (`tests/test_unit_of_work.py`), because making a port runtime-checkable to satisfy a test
    changes production code to fit the test.
    """


class PMSAdapterFactory(Protocol):
    """Resolves a property's adapters (ADR 0006 decision 7, design D2).

    Two methods and a predicate rather than one `resolve` returning both ports: a reservations
    sync must not have to resolve messaging, because resolving decrypts a credential and
    decrypting is an audited act (R4.2). Interface Segregation with a cost attached.

    `messaging_for` RAISES `PMSMessagingUnsupportedError` instead of returning
    `PMSMessagingPort | None`, and that is the answer to the question ADR 0006 decision 7 leaves
    open by name. The deciding fact is measured: **CI runs no type checker** (`app/core/db.py`),
    so a `| None` would be verified by nothing and would surface as an `AttributeError` on
    `NoneType` at the worst possible moment. A named domain error explains itself.

    The use cases depend on THIS, never on a concrete adapter — which is what ADR 0006 means by
    "los casos de uso nunca reciben un adapter inyectado como singleton", and what
    `tests/test_layering.py` enforces by refusing an `infrastructure/` import from
    `application/`.
    """

    def supports_messaging(self, provider: PMSProvider) -> bool:
        """Whether the provider has a messaging API at all.

        **Pure**: a property of the provider, resolved without touching credentials, so asking
        costs no decryption and leaves no audit row. That is what lets a consumer plan over a
        portfolio — filter the properties it can message — without fabricating a trail of reads
        that never happened.
        """
        ...

    def provider_for(self, property: "Property") -> PMSProvider:
        """Which provider will actually be used for this property, override included.

        Pure, like `supports_messaging`, and separate from resolving so a caller can GROUP a
        portfolio by provider without decrypting anything.

        It exists because the operator override of `pms_sync --provider` lives in the factory:
        grouping on `property.pms_provider` directly would ignore the override while resolving
        would honour it, and the two would disagree silently — the sync would group a property
        under Beds24 and then talk to the mock.
        """
        ...

    async def reservations_for(
        self, property: "Property", *, read_log: "CredentialReadLog | None" = None
    ) -> PMSAdapter:
        """The reservations adapter for this property.

        `read_log` collects the credentials this call decrypted, and it is a parameter of the
        CALL rather than configuration of the factory. It was the latter, and the security panel
        of sections 6-8 reproduced why that is wrong: a factory reused across two `execute` calls
        carried the first run's reads into the second, which wrote an audit row under one tenant
        naming another tenant's credential. A run's reads belong to the run.

        Raises, and the full set matters because a caller's error handling is only as complete as
        this list — the boundedness argument in `SyncReservationsFromPmsUseCase` rests on it:

        - `MissingPmsCredentialError` — the provider needs a stored credential and none is there.
          Never a silent fall back to the mock, which would report "created 0" and be
          indistinguishable from an empty PMS.
        - `SecretDecryptionError` — the credential is there but will not decrypt: a rotated
          `ENCRYPTION_KEY`, a corrupted row, or a tampered ciphertext.
        - `PmsUnavailableError` — no adapter implements the provider yet, or it could not answer.

        This list was incomplete while the last two were already reachable; the feature-scale
        security panel caught it.
        """
        ...

    async def messaging_for(self, property: "Property") -> PMSMessagingPort:
        """The messaging port, or `PMSMessagingUnsupportedError` if the provider has none."""
        ...


class ReservationCsvParser(Protocol):
    """Turns an uploaded CSV into rows, reporting per-row failures instead of raising (R4.2).

    A port because the use case must not import `infrastructure/` (the feature-scale
    architecture review caught the router doing exactly that): parsing a file format is an
    adapter concern, and going through a port is what keeps `application/` free of it.

    Raises only for failures of the FILE as a whole — not UTF-8, missing required columns, more
    rows than allowed — because in those cases there is nothing to report per row.
    """

    def parse(self, raw: bytes, *, max_rows: int) -> ParseResult:
        ...
