"""The two operator use cases, against in-memory fakes (R1.5, R6.1, R6.2; D14, Risks).

Unit tests with fakes, as `steering/backend-architecture.md` § "Cómo se testea cada capa"
prescribes for `application/`: "unit tests con **fakes** en memoria de los puertos (no la DB
real, no mocks de SQLAlchemy)". (`steering/testing.md` is where the *kinds* of test are
listed; the per-layer rule lives in the architecture doc, and the documentation reviewer of
section 4 caught this docstring citing the wrong one.)

**These exist because the API tests structurally cannot reach what they assert.** The QA
panel of section 4 made the point and it is worth writing down: at HTTP level, a use case
that called `add` *before* `revoke` would still end with one live token — the database's
partial unique index would reject the bad ordering and the caller would see a `409` — so the
net state proves the schema works, not that the use case does. Likewise a double `commit()`,
or a commit before the audit row, leaves the same final rows. What distinguishes those from
the correct implementation is the **sequence of calls**, and only a fake can record it.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

import pytest

from app.audit.domain.entities import AuditLog
from app.core.unit_of_work import CallerOwnedUnitOfWork
from app.guests.application.portal import (
    IssueGuestAccessTokenUseCase,
    RevokeGuestAccessTokenUseCase,
    SubmitGuestCheckinUseCase,
)
from app.guests.application.use_cases import (
    DocumentInput,
    GuestActor,
    SetGuestDocumentUseCase,
)
from app.guests.domain.entities import Guest
from app.guests.domain.enums import GuestDocumentType, LegalRegistrationStatus
from app.guests.domain.exceptions import ReservationNotFoundError
from app.guests.domain.portal_ports import GuestAccessToken, GuestSession, PortalStay
from app.guests.domain.portal_token import hash_guest_token
from app.guests.domain.ports import LegalRegistrationStay
from app.reservations.domain.enums import ReservationStatus
from app.timeline.domain.enums import TimelineActorType, TimelineEventType

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
RESERVATION = uuid.uuid4()
IP = "203.0.113.7"


@dataclass
class FakeStayLocator:
    """`PortalStayLocator`, answering only what these use cases ask of it.

    They borrowed `LegalRegistrationStayStore` until section 5 introduced this port — the
    role mismatch the architect panel of section 4 flagged. The fake changed with them.
    """

    stays: dict[tuple[uuid.UUID, uuid.UUID], PortalStay] = field(default_factory=dict)

    async def find(self, tenant_id, reservation_id):
        return self.stays.get((tenant_id, reservation_id))


@dataclass
class RecordingTokenRepository:
    """`GuestAccessTokenRepository` that remembers **the order it was called in**.

    That ordering is the whole point of this file: `calls` is what proves revoke-before-add
    rather than the final row count, which the database would make look right either way.
    """

    calls: list[str] = field(default_factory=list)
    added: list[GuestAccessToken] = field(default_factory=list)
    live_id: uuid.UUID | None = None

    async def find_live_by_token_hash(self, token_hash):  # pragma: no cover
        raise AssertionError("the operator routes never resolve a presented token")

    async def add(self, tenant_id, token) -> None:
        self.calls.append("add")
        self.added.append(token)

    async def revoke_live_for_reservation(self, tenant_id, reservation_id, *, now):
        self.calls.append("revoke")
        revoked, self.live_id = self.live_id, None
        return revoked


@dataclass
class RecordingAuditRepository:
    calls: list[str] = field(default_factory=list)
    entries: list[AuditLog] = field(default_factory=list)

    async def add(self, tenant_id, entry: AuditLog) -> None:
        self.calls.append("audit")
        self.entries.append(entry)


@dataclass
class CountingUnitOfWork:
    calls: list[str] = field(default_factory=list)

    async def commit(self) -> None:
        self.calls.append("commit")


@dataclass
class Harness:
    tokens: RecordingTokenRepository
    stays: FakeStayLocator
    audit: RecordingAuditRepository
    uow: CountingUnitOfWork
    calls: list[str]


def _harness(*, live_id: uuid.UUID | None = None, stay: bool = True) -> Harness:
    """One shared `calls` list across the fakes, so the *interleaving* is observable."""
    calls: list[str] = []
    tokens = RecordingTokenRepository(calls=calls, live_id=live_id)
    audit = RecordingAuditRepository(calls=calls)
    uow = CountingUnitOfWork(calls=calls)
    stays = FakeStayLocator()
    if stay:
        stays.stays[(TENANT, RESERVATION)] = PortalStay(
            reservation_id=RESERVATION,
            tenant_id=TENANT,
            property_id=uuid.uuid4(),
            guest_id=None,
            check_in_date=date(2026, 9, 1),
            check_out_date=date(2026, 9, 3),
            status=ReservationStatus.CONFIRMED,
        )
    return Harness(tokens=tokens, stays=stays, audit=audit, uow=uow, calls=calls)


def _issue(harness: Harness) -> IssueGuestAccessTokenUseCase:
    return IssueGuestAccessTokenUseCase(
        tokens=harness.tokens, stays=harness.stays, audit=harness.audit, uow=harness.uow
    )


def _revoke(harness: Harness) -> RevokeGuestAccessTokenUseCase:
    return RevokeGuestAccessTokenUseCase(
        tokens=harness.tokens, stays=harness.stays, audit=harness.audit, uow=harness.uow
    )


# --- Issuing (R1.5, R6.2, D14, Risks) -------------------------------------------------


@pytest.mark.asyncio
async def test_it_revokes_before_it_adds() -> None:
    """D14's revoke-and-create, asserted as an **order** rather than as an outcome.

    The reverse order produces the same final rows in production, because the partial unique
    index rejects the second live token and the whole transaction rolls back — so an API
    test sees a `409` and a correct database either way. This is the assertion that tells
    the two apart.
    """
    harness = _harness(live_id=uuid.uuid4())

    await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    assert harness.calls.index("revoke") < harness.calls.index("add")


@pytest.mark.asyncio
async def test_it_audits_before_it_commits() -> None:
    """R6.2, and the reason a failing audit write cannot leave a token in the operator's hand.

    Both writes are in one transaction, so ordering them this way means an audit failure
    rolls the token back. The opposite order would commit the credential and then try to
    record it.
    """
    harness = _harness()

    await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    assert harness.calls == ["revoke", "add", "audit", "commit"]


@pytest.mark.asyncio
async def test_it_commits_exactly_once() -> None:
    """One use case, one transaction (`steering/backend-architecture.md`).

    Unreachable from an API test: two commits leave exactly the same rows behind, and the
    second would silently split the operation into two transactions — so a later failure
    could leave the token committed without its audit row.
    """
    harness = _harness()

    await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    assert harness.calls.count("commit") == 1


@pytest.mark.asyncio
async def test_the_returned_token_is_the_one_whose_hash_was_stored() -> None:
    """R1.1/R1.2: the operator gets a value the stored digest actually verifies."""
    harness = _harness()

    token = await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    stored = harness.tokens.added[-1]
    assert stored.token_hash == hash_guest_token(token)
    assert stored.tenant_id == TENANT
    assert stored.reservation_id == RESERVATION
    assert stored.revoked_at is None


@pytest.mark.asyncio
async def test_two_issues_never_return_the_same_token() -> None:
    """R1.1: the value is drawn fresh, not derived from the stay."""
    tokens = {
        await _issue(_harness()).execute(
            tenant_id=TENANT,
            reservation_id=RESERVATION,
            actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
            now=NOW,
        )
        for _ in range(50)
    }

    assert len(tokens) == 50


@pytest.mark.asyncio
async def test_the_audit_row_carries_the_actor_and_the_instant() -> None:
    """R6.1 names four things — actor, IP, fields, instant — and the API tests assert two.

    Raised by the QA panel of section 4: a refactor that dropped the IP would have passed
    every existing test.
    """
    harness = _harness()
    actor_id = uuid.uuid4()

    await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=actor_id, ip=IP),
        now=NOW,
    )

    entry = harness.audit.entries[-1]
    assert entry.actor_user_id == actor_id
    assert entry.actor_ip == IP
    assert entry.created_at == NOW
    assert entry.tenant_id == TENANT
    assert entry.changes == {"token_hash": {"changed": True}}
    # The row names the credential it is about, matching what the revocation row does, so
    # `ix_audit_logs_tenant_id_entity_type_entity_id` answers "everything that happened to
    # this token". The revoke side was covered and the issue side was not — asymmetry found
    # by the QA panel of section 4, and a regression setting `entity_id=reservation_id` here
    # would have passed every other test.
    assert entry.entity_id == harness.tokens.added[-1].id


@pytest.mark.asyncio
async def test_the_audit_row_never_carries_the_token_or_its_digest() -> None:
    """R6.4. `redacted()` is the only form `token_hash` has, and this is what that means."""
    harness = _harness()

    token = await _issue(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    serialised = str(harness.audit.entries[-1].changes)
    assert token not in serialised
    assert hash_guest_token(token) not in serialised


@pytest.mark.asyncio
async def test_it_writes_nothing_for_a_stay_that_is_not_this_tenants() -> None:
    """R2.5: the existence check runs first, so nothing is minted, audited or committed."""
    harness = _harness(stay=False)

    with pytest.raises(ReservationNotFoundError):
        await _issue(harness).execute(
            tenant_id=TENANT,
            reservation_id=RESERVATION,
            actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
            now=NOW,
        )

    assert harness.calls == []


# --- Revoking (R1.4, D14) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoking_audits_then_commits_once() -> None:
    harness = _harness(live_id=uuid.uuid4())

    revoked = await _revoke(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    assert revoked is True
    assert harness.calls == ["revoke", "audit", "commit"]


@pytest.mark.asyncio
async def test_the_revocation_row_names_the_token_that_was_withdrawn() -> None:
    """The reason the port returns an id rather than a count.

    Both audit rows must name the same `entity_id` for
    `ix_audit_logs_tenant_id_entity_type_entity_id` to answer "everything that happened to
    this credential".
    """
    live_id = uuid.uuid4()
    harness = _harness(live_id=live_id)

    await _revoke(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    entry = harness.audit.entries[-1]
    assert entry.entity_id == live_id
    assert entry.actor_ip == IP
    assert entry.created_at == NOW


@pytest.mark.asyncio
async def test_revoking_nothing_writes_no_audit_row_and_does_not_commit() -> None:
    """Nothing happened, so nothing is recorded — and no empty transaction is committed.

    Auditing a no-op would let an operator fill `audit_logs` by pressing a button twice.
    """
    harness = _harness(live_id=None)

    revoked = await _revoke(harness).execute(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
        now=NOW,
    )

    assert revoked is False
    assert harness.calls == ["revoke"]


@pytest.mark.asyncio
async def test_revoking_a_stay_that_is_not_this_tenants_writes_nothing() -> None:
    harness = _harness(stay=False, live_id=uuid.uuid4())

    with pytest.raises(ReservationNotFoundError):
        await _revoke(harness).execute(
            tenant_id=TENANT,
            reservation_id=RESERVATION,
            actor=GuestActor(user_id=uuid.uuid4(), ip=IP),
            now=NOW,
        )

    assert harness.calls == []
    assert harness.tokens.live_id is not None


# --- The check-in, against fakes (R4.3, R4.5, R6.1, R6.3; D10, D13; task 6.5) ---------
#
# The four things task 6.5 asks for are all invisible at HTTP level, which is why they live
# here and why their absence survived a whole section: the QA panel of section 6 found the
# task ticked while this file covered only the two operator use cases. A double `commit()`
# leaves exactly the rows a single one leaves; a status the check-in must not touch is one
# nobody seeded; a second stay of the same guest is one nobody created. All four are
# sequences or non-effects, and only fakes record those.


@dataclass
class RecordingGuestRepository:
    calls: list[str] = field(default_factory=list)
    guests: dict[uuid.UUID, Guest] = field(default_factory=dict)

    async def get_full(self, tenant_id, guest_id):
        return self.guests.get(guest_id)

    async def add(self, tenant_id, guest: Guest) -> None:
        self.calls.append("guest_add")
        self.guests[guest.id] = guest

    async def save_document(self, tenant_id, guest: Guest) -> None:
        self.calls.append("save_document")
        self.guests[guest.id] = guest

    async def get(self, tenant_id, guest_id):  # pragma: no cover
        raise AssertionError("the portal never reads a summary")

    async def find_by_email(self, tenant_id, email):  # pragma: no cover
        raise AssertionError("the portal never deduplicates by email")


@dataclass
class RecordingLegalStore:
    """`LegalRegistrationStayStore` over a dict of stays, keyed by reservation.

    `set_guest` implements the **claim** the port describes: it writes only where there is no
    guest yet and answers with whoever holds the stay. That is what lets a test stage the
    losing side of the race without two connections — which is exactly what the QA panel of
    section 6 could not do against the real database, leaving the finding as code analysis.
    """

    calls: list[str] = field(default_factory=list)
    stays: dict[uuid.UUID, LegalRegistrationStay] = field(default_factory=dict)

    async def get(self, tenant_id, reservation_id):
        return self.stays.get(reservation_id)

    async def set_status(self, tenant_id, reservation_id, status) -> None:
        self.calls.append(f"set_status:{status.value}")
        self.stays[reservation_id] = replace(self.stays[reservation_id], status=status)

    async def set_guest(self, tenant_id, reservation_id, guest_id):
        self.calls.append("set_guest")
        stay = self.stays.get(reservation_id)
        if stay is None:
            return None
        if stay.guest_id is not None:
            return stay.guest_id
        self.stays[reservation_id] = replace(stay, guest_id=guest_id)
        return guest_id


@dataclass
class RecordingTimeline:
    calls: list[str] = field(default_factory=list)
    events: list[object] = field(default_factory=list)
    explode: bool = False

    async def add(self, tenant_id, event) -> None:
        self.calls.append("timeline")
        if self.explode:
            raise RuntimeError("the timeline write failed")
        self.events.append(event)


SECOND_RESERVATION = uuid.uuid4()
NUMBER = "12345678Z"

DOCUMENT = DocumentInput(
    full_name="Ada Lovelace",
    nationality="GB",
    date_of_birth=date(1815, 12, 10),
    document_type=GuestDocumentType.PASSPORT,
    document_number=NUMBER,
    document_expiry_date=date(2032, 1, 1),
)


@dataclass
class CheckinHarness:
    guests: RecordingGuestRepository
    stays: FakeStayLocator
    legal: RecordingLegalStore
    audit: RecordingAuditRepository
    timeline: RecordingTimeline
    uow: CountingUnitOfWork
    inner_uow: CountingUnitOfWork
    calls: list[str]
    guest_id: uuid.UUID | None
    property_id: uuid.UUID


def _checkin_harness(
    *,
    guest_id: uuid.UUID | None = None,
    status: LegalRegistrationStatus = LegalRegistrationStatus.PENDING_GUEST_DATA,
    second_stay: bool = False,
) -> CheckinHarness:
    calls: list[str] = []
    property_id = uuid.uuid4()
    guests = RecordingGuestRepository(calls=calls)
    if guest_id is not None:
        guests.guests[guest_id] = Guest(
            id=guest_id,
            tenant_id=TENANT,
            full_name="Ada Lovelace",
            created_at=NOW,
            updated_at=NOW,
        )

    legal = RecordingLegalStore(calls=calls)
    legal.stays[RESERVATION] = LegalRegistrationStay(
        reservation_id=RESERVATION,
        property_id=property_id,
        guest_id=guest_id,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 3),
        status=status,
    )
    if second_stay:
        legal.stays[SECOND_RESERVATION] = LegalRegistrationStay(
            reservation_id=SECOND_RESERVATION,
            property_id=uuid.uuid4(),
            guest_id=guest_id,
            check_in_date=date(2026, 10, 1),
            check_out_date=date(2026, 10, 3),
            status=LegalRegistrationStatus.PENDING_GUEST_DATA,
        )

    stays = FakeStayLocator()
    stays.stays[(TENANT, RESERVATION)] = PortalStay(
        reservation_id=RESERVATION,
        tenant_id=TENANT,
        property_id=property_id,
        guest_id=guest_id,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 3),
        status=ReservationStatus.CONFIRMED,
    )
    return CheckinHarness(
        guests=guests,
        stays=stays,
        legal=legal,
        audit=RecordingAuditRepository(calls=calls),
        timeline=RecordingTimeline(calls=calls),
        uow=CountingUnitOfWork(calls=calls),
        # Kept apart from `uow` so that a regression shows up as an extra `commit` in the
        # shared `calls` list rather than as a number nobody reads. Production wires the
        # inner writer with `CallerOwnedUnitOfWork`, and so does `_submit` by default.
        inner_uow=CountingUnitOfWork(calls=calls),
        calls=calls,
        guest_id=guest_id,
        property_id=property_id,
    )


def _submit(harness: CheckinHarness, *, inner_commits: bool = False):
    return SubmitGuestCheckinUseCase(
        guests=harness.guests,
        stays=harness.stays,
        legal=harness.legal,
        documents=SetGuestDocumentUseCase(
            guests=harness.guests,
            stays=harness.legal,
            audit=harness.audit,
            uow=harness.inner_uow if inner_commits else CallerOwnedUnitOfWork(),
        ),
        timeline=harness.timeline,
        uow=harness.uow,
    )


def _session(harness: CheckinHarness) -> GuestSession:
    return GuestSession(
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        property_id=harness.property_id,
        guest_id=harness.guest_id,
        token_hash=hash_guest_token("a-token"),
    )


@pytest.mark.asyncio
async def test_the_whole_check_in_is_one_transaction_with_one_commit() -> None:
    """Task 6.5 and D10, asserted as a sequence — the only form that can fail.

    Both wirings leave identical rows when nothing goes wrong, which is why the second
    `commit()` went unnoticed until four of the five reviewers of section 6 read the wiring
    instead of the result. What tells them apart is where `commit` sits: last, once, after
    the milestone, and after the audit row (R6.2).
    """
    harness = _checkin_harness(guest_id=uuid.uuid4())

    await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert harness.calls == [
        "save_document",
        "audit",
        "set_status:READY_TO_SUBMIT",
        "timeline",
        "commit",
    ]


@pytest.mark.asyncio
async def test_a_failed_milestone_takes_the_document_down_with_it() -> None:
    """R4.4 reaching R6.3: no partial update, "the document without its milestone" included.

    With the inner writer holding a real unit of work — the wiring this change shipped first
    — the encrypted document and its audit row were already committed by the time the
    timeline write failed, and no retry could ever write the milestone either, because
    `status_for` would no longer transition. Now the failure escapes before any commit.
    """
    harness = _checkin_harness(guest_id=uuid.uuid4())
    harness.timeline.explode = True

    with pytest.raises(RuntimeError):
        await _submit(harness).execute(
            session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
        )

    assert "commit" not in harness.calls


@pytest.mark.asyncio
async def test_this_file_can_see_the_wiring_that_broke_it() -> None:
    """The same use case with a committing inner unit of work.

    Without this, the two tests above would be guards that cannot fail for the reason they
    claim: the fakes would record the same list whether or not the composition was correct.
    """
    harness = _checkin_harness(guest_id=uuid.uuid4())

    await _submit(harness, inner_commits=True).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert harness.calls.count("commit") == 2
    assert harness.calls.index("commit") < harness.calls.index("timeline")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        LegalRegistrationStatus.SUBMITTED,
        LegalRegistrationStatus.FAILED,
        LegalRegistrationStatus.MANUAL_REVIEW,
        LegalRegistrationStatus.NOT_REQUIRED,
    ],
)
async def test_it_returns_any_other_legal_status_untouched(
    status: LegalRegistrationStatus,
) -> None:
    """R4.3: only between `PENDING_GUEST_DATA` and `READY_TO_SUBMIT`, and nothing else.

    `SUBMITTED` is the one that matters: recomputing it from field presence would let a guest
    editing their own form silently undo a filing already made with the police.
    """
    harness = _checkin_harness(guest_id=uuid.uuid4(), status=status)

    result = await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert result.legal_registration_status is status
    assert harness.legal.stays[RESERVATION].status is status
    # No transition, no milestone (D13): the timeline is append-only, so a check-in recorded
    # against a stay already submitted could never be taken back.
    assert harness.timeline.events == []
    assert not any(call.startswith("set_status") for call in harness.calls)


@pytest.mark.asyncio
async def test_it_does_not_move_another_stay_of_the_same_guest() -> None:
    """R4.3's second half: one guest, two bookings, one of them named by the token."""
    guest_id = uuid.uuid4()
    harness = _checkin_harness(guest_id=guest_id, second_stay=True)

    await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert harness.legal.stays[RESERVATION].status is LegalRegistrationStatus.READY_TO_SUBMIT
    assert (
        harness.legal.stays[SECOND_RESERVATION].status
        is LegalRegistrationStatus.PENDING_GUEST_DATA
    )
    assert len(harness.timeline.events) == 1


@pytest.mark.asyncio
async def test_resending_writes_a_second_audit_row_and_no_second_milestone() -> None:
    """R4.5 and D13, at the layer where the difference is a decision and not a row count."""
    harness = _checkin_harness(guest_id=uuid.uuid4())
    use_case = _submit(harness)

    first = await use_case.execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )
    second = await use_case.execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert first == second
    assert len(harness.audit.entries) == 2
    assert len(harness.timeline.events) == 1


@pytest.mark.asyncio
async def test_losing_the_claim_writes_the_document_to_the_guest_that_won() -> None:
    """OQ3 under concurrency (R4.5), staged rather than raced.

    Two submissions of the same form on a booking with no guest both create a `Guest` and
    both try to link it. `set_guest` writes only where the column is still empty and returns
    the holder, so the loser continues with the winner's id and the encrypted document lands
    on the row the reservation actually points at. Before, the loser wrote it to its own
    orphan: an identity document no route could reach and no flow could delete.
    """
    winner = uuid.uuid4()
    harness = _checkin_harness(guest_id=None)
    harness.legal.stays[RESERVATION] = replace(
        harness.legal.stays[RESERVATION], guest_id=winner
    )
    harness.guests.guests[winner] = Guest(
        id=winner,
        tenant_id=TENANT,
        full_name="Ada Lovelace",
        created_at=NOW,
        updated_at=NOW,
    )

    await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    assert harness.guests.guests[winner].document_number_encrypted is not None
    assert [
        guest_id
        for guest_id, guest in harness.guests.guests.items()
        if guest_id != winner and guest.document_number_encrypted is not None
    ] == []


@pytest.mark.asyncio
async def test_the_audit_row_names_the_bearer_the_address_and_the_instant() -> None:
    """R6.1 names four things.

    The panel of section 4 already made this point for the operator side: asserting the actor
    and forgetting the address leaves half a criterion untested. `changes` carries names,
    never values (R6.4).
    """
    harness = _checkin_harness(guest_id=uuid.uuid4())

    await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    entry = harness.audit.entries[0]
    assert entry.actor_guest_token_hash == hash_guest_token("a-token")
    assert entry.actor_user_id is None
    assert entry.actor_ip == IP
    assert entry.created_at == NOW
    assert NUMBER not in str(entry.changes)
    assert "Lovelace" not in str(entry.changes)


@pytest.mark.asyncio
async def test_the_milestone_is_a_guest_event_carrying_only_identifiers() -> None:
    """R6.3 and R6.4.

    The timeline is immutable, so whatever lands here can never be redacted afterwards — and
    this is the one flow in the system whose subject is an identity document.
    """
    harness = _checkin_harness(guest_id=uuid.uuid4())

    await _submit(harness).execute(
        session=_session(harness), document=DOCUMENT, ip=IP, now=NOW
    )

    event = harness.timeline.events[0]
    assert event.actor_type is TimelineActorType.GUEST
    assert event.actor_user_id is None
    assert event.event_type is TimelineEventType.GUEST_CHECKIN_COMPLETED
    assert event.reservation_id == RESERVATION
    serialised = f"{event.metadata}{event.title}"
    assert NUMBER not in serialised
    assert hash_guest_token("a-token") not in serialised
    assert "Lovelace" not in serialised
