"""The guest portal's use cases (R1.1, R1.4, R1.5, R6.1; design D14).

This module starts with the **operator** side — minting and revoking the credential — and
grows the anonymous side (the authoriser, and the use cases behind the stay and check-in
routes) in later sections. Named rather than counted: this sentence said "the four portal use
cases" until `guest-portal-messaging` put two more of them in
`messaging/application/portal.py`, where the behaviour they need lives (D2), leaving the
number describing neither this module nor the portal.
The order is deliberate: D14 resolves R1.6's open question by giving the token a way to be
issued at all, so the capability is reachable before any of it is exposed anonymously.

**Returning the cleartext token once is explicitly permitted, and only here.** Rule 3(a) of
`steering/security.md` states its single named exception: "un secreto que *nosotros*
generamos para que un tercero nos autentique … se puede devolver **una sola vez en el momento
de generarlo y en cada rotación**, nunca en una lectura posterior". The guest token is exactly
that class, like `webhook_endpoints.header_secret`. What makes the exception safe rather than
a loophole is that there is no second path: the repository stores only a digest, and
`GuestAccessTokenRepository` deliberately offers no read (D2), so a later call *cannot*
return it even by mistake.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.value_objects import ChangeSet
from app.core.unit_of_work import UnitOfWork
from app.guests.application.use_cases import (
    DocumentInput,
    GuestActor,
    GuestAuditWriter,
    SetGuestDocumentUseCase,
)
from app.guests.domain.entities import Guest
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.domain.exceptions import (
    GuestContactMissingError,
    GuestNotFoundError,
    GuestPortalUnauthorised,
    ReservationNotFoundError,
)
from app.guests.domain.legal_registration import LegalRegistrationSubject, missing_fields
from app.guests.domain.notifications import (
    render_guest_link_delivery_email,
    render_stored_guest_link_notice,
)
from app.guests.domain.portal_authorisation import token_still_authorises
from app.guests.domain.portal_ports import (
    GuestAccessToken,
    GuestAccessTokenRepository,
    GuestPortalStayReader,
    GuestSession,
    PortalStay,
    PortalStayLocator,
    StayInfo,
    TenantBinder,
)
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.guests.domain.ports import LegalRegistrationStayStore
from app.guests.domain.repositories import GuestRepository
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.repositories import NotificationLogRepository
from app.notifications.domain.results import NotificationErrorCode, NotificationResult
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)


class GuestPortalAuthenticator:
    """Turns a presented token into a `GuestSession`, or refuses (R1.3, R1.4, R2.1, R2.2; D3, D4).

    **The order is fixed and every step of it is load-bearing** (D4):

    1. hash the presented value and look the row up by digest, on a session that is **not yet
       marked** — there is no tenant to filter by, because this row is what resolves it;
    2. project the reservation, still unmarked;
    3. D3's three checks, delegated to `domain/portal_authorisation.py` — not revoked, not
       `CANCELLED`, inside the window;
    4. `bind_session_to_tenant`, after which the global filter covers the rest of the request;
    5. return a frozen `GuestSession`.

    **Every rejection is the same rejection.** D5 requires that "inexistente, mal formado,
    revocado, fuera de ventana o de una reserva cancelada" be indistinguishable, and the
    single `GuestPortalUnauthorised` exception is how that is kept true — one exception type,
    no cause attached, mapped to one constant `404` body by the router.

    That extends past the body, and the security panel of section 3 spelled out why: an
    implementation that looked the stay up only for tokens that resolve answers "unknown" in
    one query and "known but dead" in two, so *work* is observable even when the response is
    not. Hence **both lookups always run**, in this order, rather than short-circuiting on
    the cheapest failure — including the miss, which is issued against ids that cannot
    resolve. The section 5 panel found the first draft of this class short-circuiting while
    this paragraph already claimed it did not.

    What remains, stated rather than papered over: the throttle is charged by the router, so
    D6's "identically either way" is an obligation on §6 and not something this class can
    guarantee. `tasks.md` 5.1 carries it.

    **No ORM instance is created on this path.** Both reads select columns and return frozen
    dataclasses, so nothing can linger in the identity map to be reachable after step 4 —
    limit 4 of `app/core/db.py`, which sections 3 and 4 both flagged as holding only by
    CPython refcounting for the sibling read. It now holds structurally, because there is no
    instance to drop.
    """

    def __init__(
        self,
        *,
        tokens: GuestAccessTokenRepository,
        stays: PortalStayLocator,
        binder: TenantBinder,
        grace_days: int,
    ) -> None:
        self._tokens = tokens
        self._stays = stays
        self._binder = binder
        self._grace_days = grace_days

    async def authorize(self, token: str, now: datetime) -> GuestSession:
        if now.tzinfo is None or now.utcoffset() is None:
            # Refused up front, before either lookup, so the failure is uniform. A naive
            # clock would otherwise blow up inside `token_still_authorises` — which is only
            # reached by tokens that *resolve*, turning a wiring mistake into a clean
            # existence oracle: 500 for every real token, the constant 404 for every other.
            raise ValueError("`now` must be timezone-aware")

        # Step 1. A malformed value is not a special case: it simply hashes to a digest no
        # row carries, so "mal formado" and "inexistente" are the same code path rather than
        # two branches that could drift apart.
        row = await self._tokens.find_live_by_token_hash(hash_guest_token(token))

        # Step 2, and **genuinely** unconditional — see the class docstring. A first draft
        # raised here when `row` was `None`, which left "unknown" costing one query and
        # "known but dead" costing two: exactly the asymmetry the section 3 security panel
        # told this task to close, and which the docstring already claimed was closed. The
        # panel of this section caught the claim outrunning the code.
        #
        # The miss is issued against ids that cannot resolve, so both paths do the same
        # work: one indexed lookup that finds nothing.
        stay = await self._stays.find(
            row.tenant_id if row else uuid.uuid4(),
            row.reservation_id if row else uuid.uuid4(),
        )

        # Step 3, as one call into `domain/`. The rule spans the token and the stay, so it is
        # a domain service rather than a method on either — and it does not belong here at
        # all: the architecture panel of section 5 raised the first draft, which inlined it,
        # against `steering/backend-architecture.md`'s "si hay una regla … pertenece a
        # `domain/`". What is left in this class is orchestration.
        if (
            row is None
            or stay is None
            or not token_still_authorises(
                revoked_at=row.revoked_at,
                reservation_status=stay.status,
                check_out_date=stay.check_out_date,
                now=now,
                grace_days=self._grace_days,
            )
        ):
            raise GuestPortalUnauthorised()

        # Step 4. One way, and correct precisely because an anonymous request's session is
        # born unmarked.
        self._binder.bind(stay.tenant_id)

        return GuestSession(
            tenant_id=stay.tenant_id,
            reservation_id=stay.reservation_id,
            property_id=stay.property_id,
            guest_id=stay.guest_id,
            token_hash=row.token_hash,
        )


class GetStayInfoUseCase:
    """`GET /guest/info/{token}` (R3.1, R3.2, R3.3; design D9).

    Thin to the point of looking pointless, and that is the shape: the projection *is* the
    security control. `StayInfo` names sixteen fields and none of them is a money column, an
    internal note, an external id or a document, so there is nothing here to filter — a use
    case that had filtering to do would mean the type had been widened wrongly.

    It exists rather than the router calling the reader directly because D4 rejects putting
    the decision in `api/`, and because §7's routes will want the same shape.
    """

    def __init__(self, *, stays: GuestPortalStayReader) -> None:
        self._stays = stays

    async def execute(self, session: GuestSession) -> StayInfo:
        info = await self._stays.stay_info(session.tenant_id, session.reservation_id)
        if info is None:
            # Unreachable while the authoriser has just resolved this stay, and fail-closed
            # rather than `assert`: on this surface the alternative to a refusal is an
            # unhandled 500, which is a louder signal to an anonymous caller than the
            # constant 404 D5 works to keep uniform.
            raise GuestPortalUnauthorised()
        return info


class GetCheckinStatusUseCase:
    """`GET /guest/checkin/{token}` — what is still missing (R4.1, R3.3).

    Answers with **names of absent fields**, never with values already supplied. The guest
    knows what they typed; echoing it back would put PII in one more response body, one more
    proxy log and one more browser cache for nothing. R3.3 makes that binding for the
    document number specifically — "ni siquiera al huésped que lo aportó" — and the same
    reasoning covers the rest of the eight.

    The readiness rule is **not** reimplemented: `missing_fields` is the same pure service
    `SubmitLegalRegistrationUseCase` uses, so the portal and the operator cannot disagree
    about what "complete" means.
    """

    def __init__(self, *, guests: GuestRepository, stays: PortalStayLocator) -> None:
        self._guests = guests
        self._stays = stays

    async def execute(self, session: GuestSession) -> "CheckinStatus":
        stay = await self._stays.find(session.tenant_id, session.reservation_id)
        if stay is None:
            raise GuestPortalUnauthorised()

        if session.guest_id is None:
            # A booking with no guest yet (OQ3). Everything about the person is missing; the
            # two reservation dates are not, and saying so is the difference between a form
            # that asks for six things and one that asks for eight.
            #
            # Through the same pure service as the branch below, over an empty subject,
            # rather than by filtering `REQUIRED_FIELDS` here. The list would agree today and
            # diverge the moment a ninth field arrives that is not the guest's — and it would
            # diverge in the branch this class's docstring declares cannot disagree with the
            # operator's view (documentation panel, section 6).
            return CheckinStatus(
                missing_fields=missing_fields(
                    LegalRegistrationSubject(
                        full_name=None,
                        nationality=None,
                        date_of_birth=None,
                        document_type=None,
                        has_document_number=False,
                        document_expiry_date=None,
                        check_in_date=stay.check_in_date,
                        check_out_date=stay.check_out_date,
                    )
                ),
                document_status=GuestDocumentStatus.NOT_PROVIDED,
                legal_registration_status=LegalRegistrationStatus.PENDING_GUEST_DATA,
            )

        guest = await self._guests.get_full(session.tenant_id, session.guest_id)
        if guest is None:
            raise GuestPortalUnauthorised()

        return CheckinStatus(
            missing_fields=missing_fields(
                LegalRegistrationSubject.of(
                    guest,
                    check_in_date=stay.check_in_date,
                    check_out_date=stay.check_out_date,
                )
            ),
            document_status=guest.document_status,
            legal_registration_status=guest.legal_registration_status,
        )


@dataclass(frozen=True)
class CheckinStatus:
    """What the guest is told about their own check-in (R4.1).

    Three fields, and what is absent is the point: no `full_name`, no `document_number`, no
    `date_of_birth`. `missing_fields` carries **names**, which is information the guest
    already has — they know which boxes they left empty — while the values would be PII the
    response has no reason to carry.
    """

    missing_fields: tuple[str, ...]
    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus


class SubmitGuestCheckinUseCase:
    """`POST /guest/checkin/{token}` (R4.2, R4.3, R4.5, R6.1, R6.3; design D10, D13).

    **It never writes the document itself.** That goes through `SetGuestDocumentUseCase`,
    which is the codebase's one writer of `guests.document_number_encrypted` — its module
    docstring enumerates exhaustively where the cleartext number exists, and that enumeration
    is verifiable precisely because there is one writer. A second one here would turn it into
    a list somebody has to remember to update. (It does write two other things, below.)

    What this class does is the three things that writer cannot:

    1. **resolve the guest**, creating one from the submitted name if the booking has none
       (OQ3) and claiming the stay with `set_guest` — the narrow method D10 asked for rather
       than widening `LegalRegistrationStayStore` to the whole reservation;
    2. **record the milestone**, but only when the legal status actually transitions (D13);
    3. hold the whole thing in **one transaction with one commit** — which is the wiring's
       job as much as this class's: the composed writer gets a `CallerOwnedUnitOfWork`, so
       the only `commit()` in the operation is the one at the end of `execute`.

    **R4.3 is not reimplemented.** `SetGuestDocumentUseCase` already re-evaluates the stay
    through `status_for`, which moves only between `PENDING_GUEST_DATA` and
    `READY_TO_SUBMIT` and never touches another stay of the same guest. What changes here is
    who triggers it, not what it does.

    **R4.5 (idempotence) needs no key and no extra state** (D13): the operation is a complete
    overwrite of the same field set, so resending converges on the same row and `status_for`
    on the same status. The two side effects are treated differently and deliberately — the
    `TimelineEvent` only on a real transition, because the timeline is append-only; the
    `AuditLog` on every call, because suppressing the second would hide a second submission
    of a document, possibly from another IP, which is exactly what an incident review looks
    for.
    """

    def __init__(
        self,
        *,
        guests: GuestRepository,
        stays: PortalStayLocator,
        legal: LegalRegistrationStayStore,
        documents: SetGuestDocumentUseCase,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._guests = guests
        self._stays = stays
        self._legal = legal
        self._documents = documents
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self, *, session: GuestSession, document: DocumentInput, ip: str | None, now: datetime
    ) -> "CheckinResult":
        stay = await self._stays.find(session.tenant_id, session.reservation_id)
        if stay is None:
            raise GuestPortalUnauthorised()

        before = await self._legal.get(session.tenant_id, session.reservation_id)
        if before is None:
            raise GuestPortalUnauthorised()

        guest_id = session.guest_id or await self._create_guest(session, document, now)

        # The actor is the bearer of the link, named by the digest the authoriser resolved
        # (R6.1). `GuestActor` refuses to carry both this and a `user_id`, so the audit row
        # cannot claim the write was made by a logged-in manager.
        try:
            guest = await self._documents.execute(
                tenant_id=session.tenant_id,
                guest_id=guest_id,
                document=document,
                actor=GuestActor(token_hash=session.token_hash, ip=ip),
                now=now,
                reservation_id=session.reservation_id,
            )
        except (GuestNotFoundError, ReservationNotFoundError):
            # The composed writer speaks the operator's error vocabulary, and those two carry
            # a message of their own ("Guest does not exist" / "Reservation does not exist").
            # Letting them out of this method would hand the anonymous surface a second and a
            # third `404` body beside D5's constant one — the drift D5 exists to prevent,
            # arriving through the exception handler rather than through a route. They mean
            # here what every other refusal means: this token authorises nothing right now.
            #
            # Re-raised without `from`, so `__cause__` stays empty: `GuestPortalUnauthorised`
            # promises in its own docstring to carry no cause, because on this surface a
            # chained one is a detail waiting for somebody to serialise it.
            raise GuestPortalUnauthorised()

        after = await self._legal.get(session.tenant_id, session.reservation_id)
        if after is not None and after.status is not before.status:
            await self._record_completed(session, stay, now)

        await self._uow.commit()
        return CheckinResult(
            document_status=guest.document_status,
            legal_registration_status=after.status if after else before.status,
        )

    async def _create_guest(
        self, session: GuestSession, document: DocumentInput, now: datetime
    ) -> uuid.UUID:
        """OQ3: a booking with no guest gets one, from the name the guest just typed.

        `POST /reservations` allows a stay without a guest, so the case is real rather than
        defensive. Refusing would leave stays that can never complete their legal
        registration and no signal to the operator that anything is wrong.

        Bounded on purpose: one row per stay, and only for a token an operator already chose
        to mint. The link goes through `set_guest`, which writes `reservations.guest_id` and
        nothing else.

        **The claim can be lost, and losing it is handled rather than prevented.** Two
        submissions of the same form arriving together — the network retry R4.5 names — both
        see `guest_id IS NULL`. `set_guest` writes only where the column is still empty and
        returns whoever holds the stay, so the loser continues with the winner's guest and
        the document lands on the linked row. What the loser leaves behind is a `Guest` with
        a name and nothing else; what it no longer leaves behind is an orphaned row holding
        an encrypted identity document, which is the outcome the QA panel of section 6
        found.
        """
        if not document.full_name or not document.full_name.strip():
            # Belt to the schema's braces: `SubmitCheckinRequest` strips and then demands one
            # character, so a blank name is a `422` before this method exists. It stays
            # because the alternative is creating a `Guest` whose name is whitespace — a row
            # that can never satisfy PRD §17 and that nothing downstream would flag. The
            # first version of the schema did not strip, and this branch turned that into a
            # `404` for a perfectly live token (QA panel, section 6).
            raise GuestPortalUnauthorised()

        guest = Guest(
            id=uuid.uuid4(),
            tenant_id=session.tenant_id,
            full_name=document.full_name.strip(),
            created_at=now,
            updated_at=now,
        )
        await self._guests.add(session.tenant_id, guest)
        holder = await self._legal.set_guest(
            session.tenant_id, session.reservation_id, guest.id
        )
        if holder is None:
            # The stay stopped being reachable between the locator's read and this write.
            # Same answer as every other refusal on this surface.
            raise GuestPortalUnauthorised()
        return holder

    async def _record_completed(
        self, session: GuestSession, stay: PortalStay, now: datetime
    ) -> None:
        """R6.3 — the milestone, written **only** on a real transition (D13).

        `actor_type = GUEST` with `actor_user_id = None`, which is the only combination
        `TimelineEventFactory` allows for an actor that is not a `USER`.

        `metadata` carries identifiers and nothing else. The timeline is immutable, so
        anything that lands here can never be redacted afterwards — and this is the one flow
        in the system where the thing being handled is an identity document.
        """
        await self._timeline.add(
            session.tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=session.tenant_id,
                    property_id=stay.property_id,
                    reservation_id=stay.reservation_id,
                    actor_type=TimelineActorType.GUEST,
                    actor_user_id=None,
                    event_type=TimelineEventType.GUEST_CHECKIN_COMPLETED,
                    title="Guest completed check-in",
                    created_at=now,
                    metadata={"reservation_id": str(stay.reservation_id)},
                )
            ),
        )


@dataclass(frozen=True)
class CheckinResult:
    """What a successful check-in returns: two statuses, and **no echo of the document**.

    The guest just sent the number; returning it would put it in one more response body for
    no benefit (R3.3, and the same reasoning `DocumentStoredResponse` already applies to the
    manager's route).
    """

    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus


class IssueGuestAccessTokenUseCase:
    """Mint the credential for one stay, replacing whatever it had (R1.1, R1.5, D14).

    **Revoke-and-create inside one transaction**, which is the half of R1.5 the partial
    unique index cannot give. The index makes two live tokens impossible; it does not make
    replacement *possible*, and without an explicit revoke first, re-issuing would simply
    hit the constraint. Doing both in one transaction is also what the Risks section asks
    for: of two concurrent issues one wins and the loser rolls back whole, leaving no
    half-revoked stay behind, so its retry mints cleanly.

    R1.5 offers "idempotente **o** sustituirlo de manera explícita" and this takes the second
    branch, because the first is unreachable: the previous token cannot be returned again —
    only its digest was ever stored — so "idempotent" would mean handing back a value the
    system does not have.
    """

    def __init__(
        self,
        *,
        tokens: GuestAccessTokenRepository,
        stays: PortalStayLocator,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._tokens = tokens
        self._stays = stays
        self._audit = GuestAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        actor: GuestActor,
        now: datetime,
    ) -> str:
        """Return the cleartext token. The **only** time it exists outside this call."""
        # Checked explicitly rather than left to the composite foreign key: a stay of another
        # tenant must answer `404` like one that does not exist (the oracle argument this
        # module's siblings already make about identity documents), and an `IntegrityError`
        # surfacing as a `409` would tell the caller the id exists somewhere.
        stay = await self._stays.find(tenant_id, reservation_id)
        if stay is None:
            raise ReservationNotFoundError()

        # The previous token, if any, dies in the same transaction as its replacement is
        # born. Its id is not needed here — the audit row below names the *new* credential,
        # and the replacement is legible from the revoked row's own timestamp.
        await self._tokens.revoke_live_for_reservation(tenant_id, reservation_id, now=now)

        token = generate_guest_token()
        minted = GuestAccessToken(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            reservation_id=reservation_id,
            token_hash=hash_guest_token(token),
            # The same `now` the revoke above stamped and the audit row below carries, so a
            # status read's "since when" (R2.1) cannot disagree with the audit trail by the
            # width of a clock read. `GuestAccessTokenModel.created_at` is what actually
            # persists it — `TimestampMixin` stamps the row — so this value is what the
            # *entity* claims rather than what the database will store; they differ only by
            # the microseconds between here and `flush`, and nothing compares them.
            issued_at=now,
        )
        await self._tokens.add(tenant_id, minted)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.GUEST_ACCESS_TOKEN_ISSUED,
            entity_type=audit_actions.ENTITY_GUEST_ACCESS_TOKEN,
            entity_id=minted.id,
            actor=actor,
            # `redacted()` is the only form `token_hash` has — it is on rule 11's denylist,
            # so `diff()` on it raises. Recording *that* a credential was minted is the whole
            # point; recording which digest would hand an insider an offline oracle.
            changes=ChangeSet(audit_actions.ENTITY_GUEST_ACCESS_TOKEN).redacted("token_hash"),
            now=now,
        )
        await self._uow.commit()

        # Returned after the commit, so a caller never holds a token for a row that rolled
        # back. The audit row is written before the value is produced, exactly as
        # `ReadGuestDocumentUseCase` documents for the document it returns (R6.2).
        return token


class RevokeGuestAccessTokenUseCase:
    """Withdraw the stay's live token, if it has one (R1.4, D14).

    Idempotent by construction: revoking twice leaves the first `revoked_at` untouched,
    because the repository's predicate is `WHERE revoked_at IS NULL`. That matters beyond
    tidiness — the timestamp answers "when was access withdrawn", and a second call
    overwriting it would quietly rewrite the answer.

    Note what this does **not** do: it does not need the reservation to be in any particular
    state, and it does not care whether the stay is over. Revocation is always allowed, which
    is the right direction for a withdrawal.
    """

    def __init__(
        self,
        *,
        tokens: GuestAccessTokenRepository,
        stays: PortalStayLocator,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._tokens = tokens
        self._stays = stays
        self._audit = GuestAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        actor: GuestActor,
        now: datetime,
    ) -> bool:
        """Whether a live token was actually withdrawn."""
        stay = await self._stays.find(tenant_id, reservation_id)
        if stay is None:
            raise ReservationNotFoundError()

        revoked_id = await self._tokens.revoke_live_for_reservation(
            tenant_id, reservation_id, now=now
        )
        if revoked_id is None:
            # Nothing changed, so nothing is audited. Rule 9 audits acts on the credential,
            # and "an operator asked to revoke a stay that had no token" is not one — writing
            # a row for it would let a caller fill `audit_logs` by pressing a button twice.
            return False

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.GUEST_ACCESS_TOKEN_REVOKED,
            entity_type=audit_actions.ENTITY_GUEST_ACCESS_TOKEN,
            # The token that was withdrawn, matching what the issue row names, so
            # `ix_audit_logs_tenant_id_entity_type_entity_id` answers "everything that
            # happened to this credential". Pointing one of the two at the reservation would
            # mix two kinds of id under one `entity_type` and make that index useless.
            entity_id=revoked_id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_GUEST_ACCESS_TOKEN).diff(
                "revoked_at", None, now.isoformat()
            ),
            now=now,
        )
        await self._uow.commit()
        return True


@dataclass(frozen=True)
class GuestAccessTokenStatus:
    """Whether the stay has a live portal link, and since when (`guest-link-delivery` R2).

    **Two fields, and the absence of a third is the requirement.** R2.2 forbids this surface
    from carrying the token or its hash, and the way that is kept true is the same way
    `StayInfo` and `GuestSummary` keep their own promises: there is no field to leak. A caller
    holding this object cannot reach `token_hash` even by mistake, so R2.2 does not depend on
    every future serialiser of a `GuestAccessToken` remembering to exclude it.

    `issued_at` is `None` exactly when `is_live` is `False` — one nullable field rather than
    two independent ones, because "not live but issued at 10:04" describes nothing.
    """

    is_live: bool
    issued_at: datetime | None


class GetGuestAccessTokenStatusUseCase:
    """Does this stay have a live portal link, and since when (R2.1, R2.2, R2.3)?

    The read that `GuestAccessTokenRepository`'s own docstring spent a paragraph refusing to
    allow, and it is allowed now for the reason that docstring anticipated: what comes back is
    presence and an instant, never the credential. Minting is how an operator gets a link;
    this is how they find out they already have one — which is what stops "is there a link?"
    from being answered by pressing the button that replaces it.

    **The 404 comes from the stay, not from the token.** `find_live_for_reservation` collapses
    "no token", "only a revoked token" and "another tenant's token" into the same `None`, so it
    cannot distinguish a foreign reservation from an unminted one — which is correct for a
    repository and useless for tenant isolation, because `False` would then be the answer for a
    neighbour's stay as well as for your own. `PortalStayLocator.find` runs first and refuses
    with `ReservationNotFoundError` (security rule 1), exactly as
    `Issue`/`RevokeGuestAccessTokenUseCase` already do, so a foreign reservation is a `404` here
    and not a truthful-looking `is_live: false`.
    """

    def __init__(
        self,
        *,
        tokens: GuestAccessTokenRepository,
        stays: PortalStayLocator,
    ) -> None:
        self._tokens = tokens
        self._stays = stays

    async def execute(
        self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> GuestAccessTokenStatus:
        """Presence and issuance instant. No `actor`, no `now`, and nothing is written."""
        stay = await self._stays.find(tenant_id, reservation_id)
        if stay is None:
            raise ReservationNotFoundError()

        live = await self._tokens.find_live_for_reservation(tenant_id, reservation_id)
        if live is None:
            return GuestAccessTokenStatus(is_live=False, issued_at=None)
        return GuestAccessTokenStatus(is_live=True, issued_at=live.issued_at)


class SendGuestAccessTokenUseCase:
    """Mint a portal link and email it to the guest, in one transaction (R3, design D4).

    **One transaction, one commit, and the composition is what makes that hard.** This use case
    reuses `IssueGuestAccessTokenUseCase` rather than reimplementing revoke-and-replace, so
    there are two use cases over one session and exactly one of them may end it. The wiring says
    which: the composed mint is constructed with `CallerOwnedUnitOfWork`
    (`app/core/unit_of_work.py`), whose `commit()` does nothing, and the only real
    `SqlAlchemyUnitOfWork` is this class's — committed once, at the end, after the token, its
    issue audit row, the `NotificationLog` and the send audit row have all been written.

    An earlier draft of this design let the mint commit on its own and opened a second
    transaction for the notification row. That is the exact shape `CallerOwnedUnitOfWork` was
    built to prevent — a crash between the two commits leaves a live token with no
    `notification_logs` row and no `GUEST_ACCESS_TOKEN_SENT` audit row, so R3.3 and R3.6 would
    hold only for requests that happened not to be interrupted. It is written here as well as in
    the design because the wiring is what enforces it, and a reader of this class alone would
    otherwise not know that `self._issue`'s unit of work is a no-op by construction and not by
    luck.

    **The adapter is called mid-transaction, before the commit**, mirroring
    `RequestPasswordResetUseCase` (`auth/application/recovery.py`) field for field. That is not
    an oversight: the row's `status` has to be the adapter's real answer (R3.3 forbids
    `PENDING`, because a `PENDING` row is the dispatcher's queue and it would re-send using the
    *stored*, link-free body), so the answer must arrive while the transaction is still open.

    **What that costs, stated rather than discovered**: if the commit fails after a successful
    send, the guest holds a link to a token that was rolled back. The link then simply does not
    authorise, and the operator sees an error and can retry — the failure is visible and
    recoverable. The opposite arrangement (commit, then send) trades that for an invisible one:
    a committed live token with no record of whether anybody was ever told about it. R3.5 picks
    this side explicitly — a delivery failure must not roll the mint back — and it is the same
    choice `auth-account-recovery` made for the same reason.

    **Two texts, from two functions, and mixing them up is the failure mode.**
    `render_guest_link_delivery_email` builds what the guest receives, with the real portal URL
    in it. `render_stored_guest_link_notice` builds what the row keeps: fixed prose, no link, no
    token, no identifiers — rule 11 of `steering/security.md` gives
    `notification_logs.subject`/`body` one exception in the whole codebase and a live portal URL
    is not it. What identifies the stay travels on the row itself, as
    `related_type`/`related_id`.
    """

    def __init__(
        self,
        *,
        issue: IssueGuestAccessTokenUseCase,
        tokens: GuestAccessTokenRepository,
        stays: PortalStayLocator,
        guests: GuestRepository,
        notifications: NotificationLogRepository,
        adapters: dict[NotificationChannel, NotificationAdapter],
        audit: AuditLogRepository,
        uow: UnitOfWork,
        frontend_base_url: str,
    ) -> None:
        self._issue = issue
        self._tokens = tokens
        self._stays = stays
        self._guests = guests
        self._notifications = notifications
        self._adapters = adapters
        self._audit = GuestAuditWriter(audit)
        self._uow = uow
        self._frontend_base_url = frontend_base_url

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        actor: GuestActor,
        now: datetime,
    ) -> bool:
        """Whether the adapter accepted the mail. The token is minted either way (R3.5).

        The cleartext token is **not** returned. R1 keeps the two operator actions distinct —
        "copy it yourself" is the existing `POST`, "email it to the guest" is this one — and an
        operator who chose to send has no reason to also hold the value in their own browser.
        """
        stay = await self._stays.find(tenant_id, reservation_id)
        if stay is None:
            # Same refusal as the mint and revoke siblings: a stay of another tenant is
            # indistinguishable from one that does not exist (security rule 1).
            raise ReservationNotFoundError()

        # R3.2, and it is checked **here** rather than inside the mint. Two reasons: the mint
        # has no business knowing what a guest or an email is (that is why this is a
        # composition and not a `deliver: bool` flag on it), and the refusal must land before
        # anything is written — a `422` that had already replaced the stay's live token would
        # cut off a guest mid-session to tell the operator to go and fill in an address.
        recipient = await self._recipient(tenant_id, stay)

        # Nothing is durable yet: `self._issue`'s unit of work is a `CallerOwnedUnitOfWork`.
        token = await self._issue.execute(
            tenant_id=tenant_id,
            reservation_id=reservation_id,
            actor=actor,
            now=now,
        )
        # The audit row below needs the new token's **id**, and `execute` returns the cleartext
        # value and nothing else. Reading it back through this class's own port is the cheap
        # answer; the alternative — widening the mint's return to a `(token, id)` pair — would
        # put the credential and its identifier in one tuple for every caller of that use case,
        # the existing `POST` route included, to serialise.
        #
        # The read runs on the same still-open session, so it sees the row the mint just added:
        # the `SELECT` autoflushes the pending `INSERT` first. And the digest is compared rather
        # than trusted, because `find_live_for_reservation`'s predicate is "the live one for
        # this stay" — under a concurrent issue that is not necessarily *ours*, and an audit row
        # naming somebody else's credential would be worse than no audit row at all. A mismatch
        # (or a miss) is a broken invariant, so it raises before the commit and the whole
        # operation — token included — rolls back rather than landing half-recorded.
        minted = await self._tokens.find_live_for_reservation(tenant_id, reservation_id)
        if minted is None or minted.token_hash != hash_guest_token(token):
            raise RuntimeError(
                "the token just minted for this reservation is not the live one; "
                "refusing to audit a credential this request did not create"
            )

        portal_url = f"{self._frontend_base_url.rstrip('/')}/guest/{token}"
        subject, body = render_guest_link_delivery_email(
            recipient.preferred_language, portal_url
        )
        result = await self._deliver(recipient.email, subject, body)

        stored_subject, stored_body = render_stored_guest_link_notice(
            recipient.preferred_language
        )
        await self._notifications.add(
            tenant_id,
            NotificationLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                # `None`, and the column allows it: the recipient is a guest, not a `User`.
                # Pointing this at the operator who pressed the button would say the platform
                # emailed them.
                recipient_user_id=None,
                recipient_contact=recipient.email,
                channel=NotificationChannel.EMAIL,
                notification_type=NotificationType.GUEST_PORTAL_LINK_DELIVERED.value,
                created_at=now,
                updated_at=now,
                # The STORED texts (R3.4): constants, no link, no token, no identifiers.
                subject=stored_subject,
                body=stored_body,
                # Never `PENDING` (R3.3). The adapter has already answered, and a `PENDING`
                # row would be picked up by the dispatcher on the next tick and delivered
                # using the *stored* body — mailing the guest a notice with no link in it.
                status=(
                    NotificationStatus.SENT if result.delivered else NotificationStatus.FAILED
                ),
                attempts=1,
                sent_at=now if result.delivered else None,
                # R3.5's "structured error code": a `NotificationErrorCode`, never provider
                # text, which is what the return type already guarantees.
                last_error=(
                    None if result.delivered else result.error_code.value  # type: ignore[union-attr]
                ),
                # R4.2 — no SLA. A link the operator chose to send has no promise to breach,
                # so `escalation_for` returns `None` and the SLA job leaves the row alone.
                sla_deadline_at=None,
                # R3.4: what identifies the stay lives here, not in the rendered text.
                related_type="reservation",
                related_id=reservation_id,
            ),
        )

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.GUEST_ACCESS_TOKEN_SENT,
            entity_type=audit_actions.ENTITY_GUEST_ACCESS_TOKEN,
            # The **new** token, matching what the issue row this same request wrote already
            # names, so `ix_audit_logs_tenant_id_entity_type_entity_id` still answers
            # "everything that happened to this credential" — now including the fact that it
            # was mailed to somebody. Pointing it at the reservation would mix two kinds of id
            # under one `entity_type` and make that index useless.
            entity_id=minted.id,
            actor=actor,
            # **Empty, and that is the whole diff.** `AuditLogFactory.build` turns an empty
            # change set into `changes = NULL`, which is the honest record here: a send moves
            # no column of `guest_access_tokens`, so there is nothing to diff. The two fields
            # `AUDITABLE_FIELDS["GUEST_ACCESS_TOKEN"]` allows — `token_hash` and `revoked_at` —
            # would both be lies (`redacted("token_hash")` claims the digest changed), and an
            # invented `"delivered"` key is exactly what the allowlist refuses: an audited
            # field must be a real column of the entity, or the column becomes a free-form
            # payload slot.
            #
            # R3.6 is still satisfied, because it asks for the **attempt** to be audited, not
            # for a diff: `action` says what happened, `entity_id` says to which credential,
            # `actor`/`actor_ip` say by whom (rule 9 — an authenticated operator, not one of
            # the documented no-actor exceptions), and `now` says when. Whether the mail
            # actually left is on the `NotificationLog` this same transaction wrote, keyed to
            # the same reservation — one fact, one row, and no second copy to drift.
            changes=ChangeSet(audit_actions.ENTITY_GUEST_ACCESS_TOKEN),
            now=now,
        )

        # The one commit of the operation. Everything above — the revoked predecessor, the new
        # token, its issue audit row, the notification row and the row just above — lands
        # together or not at all.
        await self._uow.commit()

        logger.info(
            "guests.portal_link_sent",
            extra={
                "delivered": result.delivered,
                # No address, no token, no URL: an application log is one more place rule 3's
                # values must not appear, and the reservation id is what an operator needs to
                # find the row anyway.
                "reservation_id": str(reservation_id),
            },
        )
        return result.delivered

    async def _recipient(self, tenant_id: uuid.UUID, stay: PortalStay) -> "_Recipient":
        """The guest to mail, or `GuestContactMissingError` — **before** anything is minted.

        Both refusals are `422` and they carry different messages, because the operator's next
        action differs: link a guest, or give the linked guest an address. That is safe to
        distinguish here in a way it would not be one layer out — the stay has already resolved
        inside the acting tenant, so neither message describes a row the caller may not read.
        """
        if stay.guest_id is None:
            raise GuestContactMissingError(GuestContactMissingError.NO_GUEST)

        guest = await self._guests.get(tenant_id, stay.guest_id)
        if guest is None:
            # `reservations.guest_id` is a composite foreign key into this tenant's guests, so
            # this is unreachable short of a broken invariant. It answers `422` rather than
            # `GuestNotFoundError`'s `404` on purpose: on this route a `404` means "this
            # reservation is not yours", and it is — saying so would send the operator looking
            # for a permissions problem that does not exist.
            raise GuestContactMissingError(GuestContactMissingError.NO_EMAIL)

        email = (guest.email or "").strip()
        if not email:
            raise GuestContactMissingError(GuestContactMissingError.NO_EMAIL)

        # Stripped, because a stored address with surrounding whitespace is the same address
        # and the adapter should not be the one to find out.
        return _Recipient(email=email, preferred_language=guest.preferred_language)

    async def _deliver(
        self, recipient: str, subject: str, body: str
    ) -> NotificationResult:
        """Hand the mail to the `EMAIL` adapter, and ALWAYS come back with a result.

        The same two collapses `RequestPasswordResetUseCase._deliver` makes, for the same
        reasons — a missing adapter is `NO_ADAPTER_FOR_CHANNEL` rather than a `FAILED` row with
        no reason, and an adapter that raises (breaking its own "never raise for a delivery
        failure" contract) becomes a value here rather than a `500`.

        The `500` matters more on this route than on the anonymous one: an exception escaping
        past this point would abandon the transaction, so a mint the operator has already been
        charged for would silently vanish along with every record that it happened — which is
        precisely the state R3.5 exists to forbid.

        **No `exc_info`.** The exception's text on this path carries the recipient by
        construction (`smtplib.SMTPRecipientsRefused` is keyed by address), and a guest's email
        is rule 4 PII; the class name and the error code are what an operator needs.
        """
        adapter = self._adapters.get(NotificationChannel.EMAIL)
        if adapter is None:
            logger.warning(
                "guests.portal_link_no_email_adapter",
                extra={"channel": NotificationChannel.EMAIL.value},
            )
            return NotificationResult.failure(NotificationErrorCode.NO_ADAPTER_FOR_CHANNEL)
        try:
            return await adapter.send(
                recipient_contact=recipient,
                subject=subject,
                body=body,
                channel=NotificationChannel.EMAIL,
            )
        except Exception as exc:
            logger.warning(
                "guests.portal_link_adapter_raised",
                extra={"adapter_error": type(exc).__name__},
            )
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)


@dataclass(frozen=True)
class _Recipient:
    """The two things a send needs about the guest: where to write, and in which language.

    Private and narrow rather than passing `GuestSummary` around, so the branch that resolved
    the address is the only place a `None`/blank `email` can exist — past `_recipient`, the
    type says there is one.
    """

    email: str
    preferred_language: str
