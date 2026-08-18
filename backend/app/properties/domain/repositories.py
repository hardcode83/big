"""Ports owned by the properties domain (`reservations` design D16).

Shaped by its consumers, not by everything a property repository could eventually do
(Interface Segregation, `steering/backend-architecture.md`). It was read-only until
`celery-jobs`, whose scheduled jobs are the first writers of operational state: `save`
persists that column and nothing else.

`properties-crud` added the row writers (`add`, `update_details`, `set_wifi_password`) and the
paginated `list` behind `/api/v1/properties`. `current_operational_state` still belongs to
`PropertyStateMachine` alone and `save` is still its only route — but **how that is enforced
differs per method, and the difference matters**:

- `update_details` and `set_wifi_password` name exactly what they write, so their *signatures*
  make a state change unrepresentable. That is a structural guarantee.
- `add` takes a whole `Property`, so it cannot have that guarantee: an entity carries a state
  whether the caller meant it or not. It is enforced by a **runtime guard** in the adapter
  instead, which refuses any entity not in `VACANT_READY` and omits the column from the INSERT
  so the DDL default is the authority.

An earlier version of this paragraph claimed no signature here could express such a change. It
was false for `add`, and the review that caught it noted the real risk: the next consumer of
this port could otherwise seed rows into arbitrary states with no transition history.

**And the obligation that goes with writing that column — persisting a `property_state_transitions`
row in the same transaction — is NOT restated here on purpose. Rule 9 of `steering/security.md`
is its only normative home; cite it, do not paraphrase it.** `properties-crud` got that
attribution wrong four separate times while re-narrating it in four artifacts, which is the same
failure `security.md:41` already records for another of its rules.

Every method takes `tenant_id` explicitly and returns `None` outside it. That is what
makes R1.4 answer `404` (design D6) instead of leaking the existence of a neighbour's
property, and what lets the ingest paths of R3.4/R4.2 report a row as an error rather
than aborting the batch.
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.encrypted_secret import EncryptedSecret
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus


# The fields `PATCH /api/v1/properties/{id}` may write (`properties-crud` design D3).
#
# This is the single home of that rule: the request schema validates against it and the use
# case filters against it, so the two cannot drift (`user-management` recorded that "two copies
# of one rule is how they drift"). `current_operational_state` is absent **by design and not by
# omission** — `steering/backend.md` forbids bypassing `PropertyStateMachine`, `celery-jobs`
# requires that column be written by no other route, and keeping it out of here means the
# signature of `update_details` cannot express a state change at all.
#
# `wifi_password` is absent too: it is not a plain column write, it goes through
# `set_wifi_password` so the value is encrypted before it reaches SQL.
PATCHABLE_PROPERTY_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "internal_code",
        "pms_external_id",
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "country",
        "timezone",
        "max_guests",
        "bedrooms",
        "bathrooms",
        "default_check_in_time",
        "default_check_out_time",
        "wifi_name",
        "access_notes",
        "cleaning_notes",
        "emergency_notes",
        "status",
    }
)


@dataclass(frozen=True)
class PropertyFilters:
    """The AND-combined filters `GET /api/v1/properties` accepts (R1.4)."""

    status: PropertyStatus | None = None
    current_operational_state: PropertyOperationalState | None = None


@dataclass(frozen=True)
class Page:
    """One page of properties plus the total the client needs for `total_pages` (PRD §23).

    Declared here rather than imported: there is no shared pagination helper in this codebase
    and `reservations`/`auth` each own theirs, so following that keeps the domains uncoupled.
    """

    items: tuple[Property, ...]
    total: int


class PropertyRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property | None:
        """The property, only within `tenant_id` (R1.4)."""
        ...

    async def find_by_internal_code(
        self, tenant_id: uuid.UUID, internal_code: str
    ) -> Property | None:
        """Resolution for the CSV import, which names properties the way people do (D11).

        `internal_code` is unique per tenant (`uq_properties_tenant_id_internal_code`),
        so at most one row can match.
        """
        ...

    async def find_by_pms_external_id(
        self, tenant_id: uuid.UUID, pms_external_id: str
    ) -> Property | None:
        """Resolution for the PMS sync (R3.4).

        Unlike `internal_code` this column carries no uniqueness guarantee in the schema
        (`ix_properties_tenant_id_pms_external_id` is an index), so two properties of one
        tenant can share an external id. In that case this raises
        `AmbiguousPropertyExternalIdError` — a **domain** error, so the caller can report
        the row and carry on with the batch (R3.4) without importing SQLAlchemy to catch
        `MultipleResultsFound`, which the dependency rule forbids in `application/`.
        """
        ...

    async def list_by_state(
        self, tenant_id: uuid.UUID, states: Collection[PropertyOperationalState]
    ) -> list[Property]:
        """The tenant's properties currently in any of `states` (`celery-jobs` R3).

        The coarse half of design D3: it narrows the candidates a scheduled job has to
        consider, and nothing more. Whether a candidate may actually transition is
        `PropertyStateMachine`'s decision, never this query's.

        An empty `states` returns an empty list without querying — a job whose trigger
        has no source states has no candidates, and an `IN ()` is not the way to say so.
        """
        ...

    async def list_by_status(
        self, tenant_id: uuid.UUID, status: PropertyStatus
    ) -> list[Property]:
        """The tenant's properties in one administrative `status` (`revenue-pricing` R4.1).

        The narrow method `list_all`'s docstring asks for, rather than filtering it in
        memory: the nightly pricing job wants "every ACTIVE property" and nothing else, and
        `list_all` says in as many words that "un caller que solo necesita un subconjunto
        debería añadir un método más estrecho en vez de filtrar éste en memoria".

        **Not `list_by_state`**, which is the *operational* state (`VACANT_READY`,
        `OCCUPIED`…). A property being cleaned still has a calendar and still needs a price,
        so the pricing job asks the administrative question — is this property live at all —
        and that is `status`.

        Unpaginated, like `list_by_state` beside it: it feeds a sweep, not a screen.

        **Ordered by `internal_code`, ascending, and that is part of the contract.** A sweep
        must walk a tenant's portfolio the same way twice so a failing run is reproducible
        from its log rather than order-dependent — and `revenue-pricing`'s generator relies
        on the order being *some* fixed one to make "a property that fails does not discard
        the horizons already written" a testable claim at all. Promised here because the port
        is what `application/` programs against: while the order lived only in the adapter,
        deleting the `.order_by` left the suite green.
        """
        ...

    async def list_all(self, tenant_id: uuid.UUID) -> list[Property]:
        """Every property of the tenant (`pms-provider-resolution` R2.2).

        Added for the PMS sync, which since ADR 0006 decision 7 has to know **which providers a
        tenant actually uses** before it can talk to any of them — grouping the portfolio by
        provider and making one call per provider instead of one per property. That is not a
        micro-optimisation: a call per property scales without bound, and the measured Beds24
        budget is 100 credits per 300 s per account, which 12 properties would exhaust in a
        single cycle (`specs/pms-beds24-spike.md`).

        **Unbounded on purpose, and worth knowing**: unlike `list_by_state` this narrows nothing.
        A tenant's portfolio is small by construction (units someone physically manages), so the
        risk is understood rather than overlooked — but a caller that only needs a subset should
        add a narrower method rather than filter this one in memory.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, property: Property) -> None:
        """Persist `current_operational_state`, and only that (`celery-jobs` R3.6).

        Narrow on purpose. The only writer today is the state-transition use case, which
        has already had its destination approved by `PropertyStateMachine`; widening this
        to a full update would offer every future caller a way to change a property
        without passing through the machine, which `steering/backend.md` forbids
        outright ("no saltarse `PropertyStateMachine`").

        Raises `CrossTenantWriteError` when the entity belongs to another tenant.
        """
        ...

    async def set_pms_provider(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, provider: PMSProvider | None
    ) -> None:
        """Persist `pms_provider`, and only that (`pms-provider-resolution` R2.1).

        A second narrow writer rather than a widening of `save`, and for the reason `save`'s
        own docstring gives: making it a general update would hand every future caller a way
        around `PropertyStateMachine`. Two named methods that each write one column keep that
        rule intact; one method that writes "whatever the entity holds" does not.

        `None` is a legitimate value, meaning "use the bootstrap default", so this cannot be
        expressed as "set it if given" — clearing the provider is an operation.

        Raises `CrossTenantWriteError` when the property belongs to another tenant.
        """
        ...

    async def add(
        self,
        tenant_id: uuid.UUID,
        property: Property,
        *,
        wifi_secret: EncryptedSecret | None = None,
    ) -> None:
        """Insert one property (`properties-crud` R2.1).

        **Why the secret is a parameter and not a field of `property`** (design D2): `Property`
        is what every read path returns and what response schemas are built from, so a secret
        living on it would be one forgetful schema away from being serialised — the accident
        rule 3(a) of `steering/security.md` forbids outright. As a parameter typed
        `EncryptedSecret` the guarantee is structural in both directions: it cannot reach SQL
        as plaintext, because `EncryptedSecret.__post_init__` rejects anything that is not
        Fernet ciphertext, and it cannot leave, because nothing reads it back.

        **`current_operational_state` is not written from the entity, and cannot be chosen.**
        The INSERT omits the column so its DDL default (`VACANT_READY`) applies, and an entity
        carrying anything else is REFUSED with `PropertyValidationError` rather than quietly
        normalised. Creation is not a transition — an insert has no source state to move *from*,
        and PRD §3.1 attaches the `TimelineEvent` obligation to a transition — but "not a
        transition" is precisely why no other state may be reached this way: there would be no
        `property_state_transitions` row to record it (R4.2, and rule 9 of
        `steering/security.md`).

        This is a runtime guard and not a signature-level one, because this method takes a whole
        entity. The sibling writers get the stronger form; this one cannot, so it is checked.

        Raises `DuplicateInternalCodeError` / `DuplicatePmsExternalIdError`, translated from
        the named constraint violations rather than from a prior SELECT, and
        `CrossTenantWriteError` when the entity belongs to another tenant.
        """
        ...

    async def update_details(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, changes: Mapping[str, Any]
    ) -> bool:
        """Persist the descriptive columns named in `changes` (R3.1).

        **The admissible key set is `PATCHABLE_PROPERTY_FIELDS`, and the caller is not trusted
        to respect it** — the adapter rejects anything outside it. `current_operational_state`
        is not in that set, so this method is structurally incapable of the bypass that `save`'s
        docstring warns about; it is the third narrow writer, not a general update.

        An empty `changes` is a caller bug, not a no-op to absorb: the use case decides "nothing
        changed" before getting here, because that decision also governs whether an `AuditLog`
        row is written.

        Returns whether a row matched, so the caller can answer `404` without a prior read.
        Raises `DuplicateInternalCodeError` / `DuplicatePmsExternalIdError` on the same two
        constraints as `add`, since a `PATCH` can collide just as an insert can.
        """
        ...

    async def set_wifi_password(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, secret: EncryptedSecret | None
    ) -> bool:
        """Persist `wifi_password_encrypted`, and only that (R5.2).

        A writer of its own rather than a key of `update_details`, because the value that
        arrives is not the value that is stored: it is encrypted on the way in, and typing the
        parameter as `EncryptedSecret` is what makes "stored in plaintext" unrepresentable.

        `None` clears the stored password and is a legitimate operation, so this cannot be
        expressed as "set it if given" — the same reasoning `set_pms_provider` records.

        There is deliberately **no reader**. Rule 3 of `steering/security.md` lists
        `wifi_password` first among the values that are never in plaintext, and rule 11 is
        explicit that needing to show it to a guest does not authorise a masked form either.
        Whoever eventually has to deliver it to a guest decrypts through the one explicit call
        in `app/core/crypto.py`, and that will be their change to justify.

        Returns whether a row matched.
        """
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        filters: PropertyFilters,
        page: int,
        per_page: int,
    ) -> Page:
        """One page of the tenant's properties, filters AND-combined (R1.1, R1.3, R1.4).

        Ordered by `name` with `id` as the tiebreaker so paging cannot show a row twice or skip
        one — two properties may share a name, and an unstable sort makes pagination lie.
        `total` counts the same filtered set, not the whole table.
        """
        ...


class PropertyStateTransitionRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, transition: PropertyStateTransition) -> None:
        """Append one transition to the history (`celery-jobs` R3.6).

        **The only writer, and still the only one.** It used to be the only method here
        full stop, for the same reason `TimelineEventRepository` has only `add`: a
        transition is a record of something that happened, and history is not edited.
        `dashboard-api` added `last_for_property` below — a *read* — which leaves that
        property exactly where it was: what the signature of this port refuses is `save`,
        `update` and `delete`, and none of the three appeared.

        **Precondition the caller owns**, identical to the one `TimelineEventRepository`
        already documents: `property_id` and `triggered_by_user_id` must have been
        resolved inside `tenant_id` before getting here. The adapter can check the row's
        own tenant and no more — `property_state_transitions`' foreign keys are not
        composite with `tenant_id`, so the database would happily accept a transition
        anchored to a neighbour's flat. This table is the audit record of property state
        (rule 9 of `sdd/steering/security.md`), so a misanchored row is a corrupted audit
        trail, not just a bad read.
        """
        ...

    async def last_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> PropertyStateTransition | None:
        """The most recent transition of one property, or `None` (`dashboard-api` R3.1).

        The reader this port lacked. `add` has existed since `celery-jobs` and nothing ever
        read the history back, so `GET /api/v1/properties/{id}/state` had no way to say
        *when* the current state began — the `properties` row carries the state, not its
        instant.

        **A read, and emphatically not a resolution.** It returns the row
        `PropertyStateMachine` wrote; it computes, infers and reconciles nothing.
        `steering/backend.md` forbids "saltarse `PropertyStateMachine`" and R3.2 says the
        read layer "SHALL NOT reimplementar la resolución de estado" — a method answering
        "what state *should* this be in" would be precisely that reimplementation.

        `None` for a property with no transitions and for a property of another tenant
        alike. The caller cannot tell those apart from here, which is deliberate: it is
        `PropertyRepository.get` that decides whether the property exists for this tenant,
        and this method never becomes a second, weaker answer to that question.
        """
        ...
