"""Ports and projections of the guest portal (R1.1, R2.1, R3.2; design D2, D4, D9).

Separate from `domain/ports.py` and `domain/repositories.py` because the consumer is
different: those serve the manager's authenticated flows, these serve an anonymous surface
where the token is the only identity. Keeping them apart is what stops a later change from
handing the portal a method that was written for someone holding a JWT.

**Both dataclasses are frozen, and both are projections rather than entities**, for the
reason `GuestSummary` exists (`domain/value_objects.py`): a use case holding the
`Reservation` aggregate is one edit away from reaching `internal_notes` or `gross_amount`
from a context that has no business with them. Here the stakes are higher than there — the
context is unauthenticated — so R3.2 is satisfied *structurally*: the fields simply do not
exist on the type, and no future serialiser can leak what it cannot name.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol

from app.reservations.domain.enums import ReservationStatus


@dataclass(frozen=True)
class GuestAccessToken:
    """One row of `guest_access_tokens`, as the domain sees it.

    Carries the hash and never the token: past the authoriser, the cleartext value does not
    exist anywhere in the system (R1.2). `tenant_id` is here because this row is what
    *resolves* it — the lookup runs before any tenant is known (D4).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    reservation_id: uuid.UUID
    token_hash: str
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PortalStay:
    """The seven fields the authoriser needs about a reservation (design D4, step 2).

    A projection, not the `Reservation` aggregate, for the reason `LegalRegistrationStay` and
    `GuestSummary` exist: an aggregate held on an anonymous path is one edit away from
    `internal_notes` or `gross_amount`.

    **Not `LegalRegistrationStay`, which looks similar and is not.** That one's `status` is
    the `LegalRegistrationStatus` of the stay's police filing; this one's is the booking's own
    `ReservationStatus`, which is what D3's second check needs in order to stop authorising a
    `CANCELLED` stay. Two different questions that happen to share a field name — reusing one
    type for both is precisely how a check ends up reading the wrong column.
    """

    reservation_id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    guest_id: uuid.UUID | None
    check_in_date: date
    check_out_date: date
    #: The booking's own status. Typed as the enum rather than a string so D3's check is an
    #: identity test against a member, not a comparison against a spelling — `reservations`
    #: already imports `guests`' enums the other way round, so the dependency is symmetric
    #: and stays inside `domain/`.
    status: ReservationStatus


@dataclass(frozen=True)
class GuestSession:
    """Who the bearer of a token turns out to be (D4).

    The return of `GuestPortalAuthenticator.authorize`, and the only thing the four portal
    use cases are given. R2.1 is satisfied by construction: every identifier here came out
    of the token's own row and its reservation, so a use case *cannot* read a tenant, a
    reservation or a property from the path, the body, the query or a header — there is
    nowhere else for them to come from.

    `guest_id` is nullable because `reservations.guest_id` is: a booking may exist with no
    guest attached, and OQ3 decided the check-in creates one rather than refusing.

    `token_hash` travels so the throttle can charge the per-token limit with the digest
    already in hand (D6) and so the audit rows can name the actor (D11) — in both cases
    without re-hashing the path segment, which is what would put the cleartext back into
    circulation.
    """

    tenant_id: uuid.UUID
    reservation_id: uuid.UUID
    property_id: uuid.UUID
    guest_id: uuid.UUID | None
    token_hash: str


@dataclass(frozen=True)
class StayInfo:
    """Everything `GET /api/v1/guest/info/{token}` may show, and nothing else (D9, R3.1).

    **The field list is the security control**, not the serialiser. R3.2 forbids
    `reservations.internal_notes`, the three money columns, the external PMS/channel ids,
    other guests' data, credentials and the token itself; none of them is declared here, so
    there is no path by which a response model could include one. R3.3 likewise: there is no
    `document_number`, and the only endpoint that returns one stays
    `GET /api/v1/guests/{id}/document` with its own role and audit row.

    Two fields deserve their own note:

    - `wifi_name` is the network's **name**. `properties.wifi_password_encrypted` is not here
      and must never be: rule 4 of `steering/security.md` gives no masked form for a WiFi
      password, so there is no shape in which it could legitimately appear.
    - `access_code_masked` comes out of `access_records.code_masked` already masked, because
      the system stores no cleartext access code anywhere (`access-notifications` design D9).
      So this endpoint cannot violate rule 4 even if it tried.

    `arrival_notes` is `properties.access_notes`, exposed deliberately (OQ2): it is the field
    whose purpose is arrival instructions and whose audience is the guest. It is also free
    text an operator could paste a door code into, which is why `docs/guest-portal.md` warns
    them that the guest sees it verbatim (task 8.2).
    """

    check_in_date: date
    check_out_date: date
    # Nullable on the reservation, so the reader falls back to the property's defaults (D9).
    check_in_time: time
    check_out_time: time
    property_name: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    wifi_name: str | None
    arrival_notes: str | None
    access_code_masked: str | None
    support_channel: str | None


class TenantBinder(Protocol):
    """Step 4 of D4: mark the request's session with the tenant the token resolved.

    A port, so `application/` never imports `app.core.db` — which imports SQLAlchemy — and
    the authoriser stays unit-testable with nothing booted. It is one method because binding
    is one-way by design: `bind_session_to_tenant` refuses a null and refuses a rebind, and
    exposing an "unbind" here would hand back exactly the footgun that function's docstring
    exists to close.
    """

    def bind(self, tenant_id: uuid.UUID) -> None:
        ...


class GuestAccessTokenRepository(Protocol):
    """Mint, revoke and resolve the portal credential (D2, D14).

    Deliberately three methods and no `list`, no `get_by_reservation`: an operator has no
    read to perform — the row holds only a digest, and rule 3(a)'s named exception returns
    the cleartext exactly once at issue time. A port that offered a listing would be the open
    door for the change that comes next.
    """

    async def find_live_by_token_hash(self, token_hash: str) -> GuestAccessToken | None:
        """Resolve a presented token **without a tenant in hand** (D4, step 1).

        The one query in this module that runs on an unmarked session, and it has to: this
        row is what resolves the tenant, so there is nothing to filter by yet. The situation
        is the same as `find_by_email_globally` on the login path, documented in
        `app/core/db.py`'s second limit — and safe for the same reason, plus one this change
        added: the composite foreign key on `(tenant_id, reservation_id)` makes it impossible
        for the row to name a reservation of another tenant.

        Returns the row whatever its state; deciding whether it still authorises is the
        authoriser's job (D3), because "revoked" and "outside the window" must be
        indistinguishable to the caller and that decision belongs in one place.
        """
        ...

    async def add(self, tenant_id: uuid.UUID, token: GuestAccessToken) -> None:
        """Persist a freshly minted token; refuses a row belonging to another tenant.

        The cross-tenant check is the caller's and this port's, not the session filter's:
        `app/core/db.py`'s third limit is that INSERTs are not covered.
        """
        ...

    async def revoke_live_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID, *, now: datetime
    ) -> uuid.UUID | None:
        """Stamp `revoked_at` on the stay's live token, and return **its id** (R1.4).

        Expressed as a predicate over `revoked_at IS NULL` rather than a read-then-write, so
        the partial unique index and this method agree about what "live" means and two
        concurrent issues cannot both believe they revoked the previous one.

        Returning the id rather than a count, because the index guarantees there is at most
        one: a count would be a weaker answer to a question the schema already makes exact.
        And the callers need the id, not the number — `RevokeGuestAccessTokenUseCase` writes
        an `AuditLog` whose `entity_id` must point at the token that was withdrawn, so that
        `ix_audit_logs_tenant_id_entity_type_entity_id` keeps answering "everything that
        happened to this credential". Pointing it at the reservation instead would mix two
        kinds of id under one `entity_type` and make that index useless.

        `None` when the stay had no live token — which is not an error: revoking twice is
        allowed and leaves the first `revoked_at` intact.
        """
        ...


class PortalStayLocator(Protocol):
    """Step 2 of D4: the reservation behind a token, projected.

    Its own port rather than a method on `GuestAccessTokenRepository`, on interface
    segregation: that one is about the credential, this one about the stay it points at.
    And deliberately **not** `LegalRegistrationStayStore`, which the two operator use cases
    of section 4 borrowed for their existence check until this landed — that port is
    documented as reaching "one column of `reservations`, and no more", with a role about
    the police filing rather than about the booking. The architect panel of section 4 was
    right that borrowing it was a role mismatch; this is where it is repaid.
    """

    async def find(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> PortalStay | None:
        """The stay, or `None` if it is not this tenant's.

        Takes `tenant_id` explicitly even though the authoriser calls it before binding the
        session, and that is the point: on that path the global filter of `app/core/db.py` is
        off by design (its limit 2), so the parameter is the *only* thing scoping the read.
        The composite foreign key on `guest_access_tokens` already guarantees the pair agrees,
        which makes this belt and braces rather than the sole defence — the arrangement
        section 3's panel asked for after finding a join that relied on the net alone.
        """
        ...


class GuestPortalStayReader(Protocol):
    """The read behind `GET /guest/info` (D9).

    A port of its own rather than a method on `GuestAccessTokenRepository`, on interface
    segregation: this one joins `properties` and `access_records` and answers a question
    about the *stay*, while that one is about the credential. One port doing both would be
    the "repositorio Dios" `steering/backend-architecture.md` bans.
    """

    async def stay_info(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> StayInfo | None:
        """Project one stay, or `None` if it is not this tenant's.

        `None` rather than an exception for a missing row, because the router turns every
        failure into the same constant `404` (D5) and an exception type per cause would be
        an invitation to distinguish them.
        """
        ...
