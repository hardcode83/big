"""`SendGuestAccessTokenUseCase` and `GetGuestAccessTokenStatusUseCase` against fakes
(`guest-link-delivery` R2, R3; design D4).

Unit tests with in-memory fakes of the ports, as `steering/backend-architecture.md` §"Cómo se
testea cada capa" prescribes for `application/`: "unit tests con **fakes** en memoria de los
puertos (no la DB real, no mocks de SQLAlchemy)". The one double that is not a repository is the
`EMAIL` adapter, which is the actual I/O boundary — the one place `steering/testing.md` allows a
stub, and the only way to make "the provider refused" a controllable input.

**Why a fake and not the HTTP surface.** Every claim this file makes is about the *sequence* of
calls, and an API test structurally cannot see it. Two commits leave exactly the same rows as
one. An adapter called after the commit leaves exactly the same rows as one called before it. A
`NotificationLog` built from the sent (link-bearing) text instead of the stored one leaves a row
that looks perfectly well-formed unless somebody reads its body. What separates the correct
implementation from each of those is observable only from inside, which is what these fakes are
for — the same argument `test_portal_use_cases.py` records for the two use cases it covers.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from app.audit.domain import actions as audit_actions
from app.audit.domain.entities import AuditLog
from app.core.unit_of_work import CallerOwnedUnitOfWork
from app.guests.application.portal import (
    GetGuestAccessTokenStatusUseCase,
    IssueGuestAccessTokenUseCase,
    SendGuestAccessTokenUseCase,
)
from app.guests.application.use_cases import GuestActor
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.domain.exceptions import (
    GuestContactMissingError,
    ReservationNotFoundError,
)
from app.guests.domain.portal_ports import GuestAccessToken, PortalStay
from app.guests.domain.portal_token import hash_guest_token
from app.guests.domain.value_objects import GuestSummary
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.domain.results import NotificationErrorCode, NotificationResult
from app.reservations.domain.enums import ReservationStatus

NOW = datetime(2026, 9, 6, 10, 30, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
RESERVATION = uuid.uuid4()
GUEST = uuid.uuid4()
OPERATOR = uuid.uuid4()
IP = "203.0.113.7"
BASE_URL = "http://localhost:3000"


# --- Fakes ----------------------------------------------------------------------------


@dataclass
class FakeStayLocator:
    """`PortalStayLocator`. Keyed by `(tenant_id, reservation_id)`, so a lookup under the
    wrong tenant misses exactly as the real composite-key read does."""

    stays: dict[tuple[uuid.UUID, uuid.UUID], PortalStay] = field(default_factory=dict)

    async def find(self, tenant_id, reservation_id):
        return self.stays.get((tenant_id, reservation_id))


@dataclass
class RecordingTokenRepository:
    """`GuestAccessTokenRepository`, recording the order it was called in.

    `find_live_for_reservation` answers from what `add` stored, minus whatever `revoke`
    retired — the same `revoked_at IS NULL` predicate the real adapter and the partial unique
    index share, so the read-back in `SendGuestAccessTokenUseCase` is exercised against a fake
    that behaves like the database rather than one that always says yes.
    """

    calls: list[str] = field(default_factory=list)
    rows: list[GuestAccessToken] = field(default_factory=list)

    async def find_live_by_token_hash(self, token_hash):  # pragma: no cover
        raise AssertionError("the operator routes never resolve a presented token")

    async def add(self, tenant_id, token) -> None:
        self.calls.append("add")
        self.rows.append(token)

    async def revoke_live_for_reservation(self, tenant_id, reservation_id, *, now):
        self.calls.append("revoke")
        for index, row in enumerate(self.rows):
            if (
                row.tenant_id == tenant_id
                and row.reservation_id == reservation_id
                and row.revoked_at is None
            ):
                self.rows[index] = GuestAccessToken(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    reservation_id=row.reservation_id,
                    token_hash=row.token_hash,
                    issued_at=row.issued_at,
                    revoked_at=now,
                )
                return row.id
        return None

    async def find_live_for_reservation(self, tenant_id, reservation_id):
        self.calls.append("find_live")
        for row in self.rows:
            if (
                row.tenant_id == tenant_id
                and row.reservation_id == reservation_id
                and row.revoked_at is None
            ):
                return row
        return None


@dataclass
class RecordingGuestRepository:
    """`GuestRepository`, of which only `get` is reachable from this flow.

    The rest are stubs that satisfy the `Protocol`'s shape and nothing else — neither
    `SendGuestAccessTokenUseCase` nor `GetGuestAccessTokenStatusUseCase` calls them, so a
    body that raised unconditionally would be indistinguishable from one that returned a
    trivial value for every test in this file. They raise, so a future caller that *does*
    reach one of them fails loudly instead of silently getting an empty answer.
    """

    calls: list[str] = field(default_factory=list)
    guests: dict[tuple[uuid.UUID, uuid.UUID], GuestSummary] = field(default_factory=dict)

    async def get(self, tenant_id, guest_id):
        self.calls.append("guest")
        return self.guests.get((tenant_id, guest_id))

    async def list_for_ids(self, tenant_id, guest_ids):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def find_by_email(self, tenant_id, email):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def find_by_phone(self, tenant_id, phone):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def add(self, tenant_id, guest) -> None:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def get_full(self, tenant_id, guest_id):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def save_document(self, tenant_id, guest) -> None:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")


@dataclass
class RecordingNotificationRepository:
    """`NotificationLogRepository`, of which only `add` is reachable from this flow.

    The rest are stubs that satisfy the `Protocol`'s shape and nothing else — see
    `RecordingGuestRepository`'s docstring for why they raise instead of returning a
    trivial value.
    """

    calls: list[str] = field(default_factory=list)
    rows: list[NotificationLog] = field(default_factory=list)

    async def add(self, tenant_id, log: NotificationLog) -> None:
        self.calls.append("notification")
        self.rows.append(log)

    async def list_sla_breach_candidates(self, tenant_id, now):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def mark_breached(self, tenant_id, log) -> None:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def list_pending(self, tenant_id, limit):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def list_for_recipient(
        self,
        tenant_id,
        recipient_user_id,
        *,
        page,
        per_page,
        unread=None,
        channel=NotificationChannel.IN_APP,
    ):  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def mark_read(self, tenant_id, user_id, log_id) -> bool:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def count_unread(
        self, tenant_id, user_id, *, channel=NotificationChannel.IN_APP
    ) -> int:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def mark_all_read(self, tenant_id, user_id) -> int:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def record_attempt(
        self, tenant_id, log_id, *, status, attempts, sent_at, last_error
    ) -> None:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def exists_for(
        self, tenant_id, *, related_type, related_id, notification_type
    ) -> bool:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")

    async def cancel_sla_deadline(
        self, tenant_id, *, related_type, related_id, notification_type
    ) -> int:  # pragma: no cover
        raise AssertionError("not exercised by the send/status use cases")


@dataclass
class RecordingAuditRepository:
    calls: list[str] = field(default_factory=list)
    entries: list[AuditLog] = field(default_factory=list)

    async def add(self, tenant_id, entry: AuditLog) -> None:
        self.calls.append("audit")
        self.entries.append(entry)


@dataclass
class CountingUnitOfWork:
    """Records into the shared `calls` (for interleaving) **and** into its own `own` list.

    Two lists, because the two questions differ: "how many commits did the operation make, and
    where in the sequence" is the shared one, and "did *this* unit of work commit at all" is
    what tells the composed mint's boundary from the outer one when both write to the same
    shared list.
    """

    calls: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)

    async def commit(self) -> None:
        self.calls.append("commit")
        self.own.append("commit")

    async def rollback(self) -> None:  # pragma: no cover - nothing here abandons a unit
        self.calls.append("rollback")
        self.own.append("rollback")


@dataclass
class StubEmailAdapter:
    """The I/O boundary, and the one double in this file that is not a repository.

    `result` is what the provider "answers"; `raises` makes it break its own contract
    (`NotificationAdapter.send` promises never to raise for a delivery failure), which is the
    path `_deliver` converts to a value so an exception cannot abandon the transaction.
    """

    calls: list[str] = field(default_factory=list)
    sent: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    result: NotificationResult = field(default_factory=NotificationResult.ok)
    raises: bool = False

    async def send(
        self,
        *,
        recipient_contact,
        subject,
        body,
        channel,
        last_inbound_at=None,
        template_id=None,
        phone_number_id=None,
    ):
        self.calls.append("send")
        self.sent.append((recipient_contact, subject, body))
        if self.raises:
            raise RuntimeError("the relay exploded")
        return self.result


@dataclass
class Harness:
    tokens: RecordingTokenRepository
    stays: FakeStayLocator
    guests: RecordingGuestRepository
    notifications: RecordingNotificationRepository
    audit: RecordingAuditRepository
    uow: CountingUnitOfWork
    inner_uow: CountingUnitOfWork
    adapter: StubEmailAdapter
    adapters: dict
    calls: list[str]


def _guest(email: str | None, language: str = "es") -> GuestSummary:
    return GuestSummary(
        id=GUEST,
        full_name="Ada Lovelace",
        email=email,
        phone=None,
        preferred_language=language,
        document_status=GuestDocumentStatus.NOT_PROVIDED,
        legal_registration_status=LegalRegistrationStatus.PENDING_GUEST_DATA,
    )


def _harness(
    *,
    guest_id: uuid.UUID | None = GUEST,
    email: str | None = "ada@example.com",
    language: str = "es",
    stay: bool = True,
    live_token: bool = False,
    result: NotificationResult | None = None,
    raises: bool = False,
    with_email_adapter: bool = True,
) -> Harness:
    """One shared `calls` list across every fake, so the *interleaving* is observable."""
    calls: list[str] = []
    tokens = RecordingTokenRepository(calls=calls)
    if live_token:
        tokens.rows.append(
            GuestAccessToken(
                id=uuid.uuid4(),
                tenant_id=TENANT,
                reservation_id=RESERVATION,
                token_hash=hash_guest_token("an-older-token"),
                issued_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )

    stays = FakeStayLocator()
    if stay:
        stays.stays[(TENANT, RESERVATION)] = PortalStay(
            reservation_id=RESERVATION,
            tenant_id=TENANT,
            property_id=uuid.uuid4(),
            guest_id=guest_id,
            check_in_date=date(2026, 9, 10),
            check_out_date=date(2026, 9, 12),
            status=ReservationStatus.CONFIRMED,
        )

    guests = RecordingGuestRepository(calls=calls)
    if guest_id is not None:
        guests.guests[(TENANT, guest_id)] = _guest(email, language)

    adapter = StubEmailAdapter(
        calls=calls,
        result=result if result is not None else NotificationResult.ok(),
        raises=raises,
    )
    return Harness(
        tokens=tokens,
        stays=stays,
        guests=guests,
        notifications=RecordingNotificationRepository(calls=calls),
        audit=RecordingAuditRepository(calls=calls),
        uow=CountingUnitOfWork(calls=calls),
        # Kept apart from `uow` so a regression shows up as an extra `commit` in the shared
        # `calls` list. Production wires the composed mint with `CallerOwnedUnitOfWork`, and so
        # does `_send` unless a test asks for the broken wiring on purpose.
        inner_uow=CountingUnitOfWork(calls=calls),
        adapter=adapter,
        adapters=(
            {NotificationChannel.EMAIL: adapter} if with_email_adapter else {}
        ),
        calls=calls,
    )


def _send(harness: Harness, *, inner_commits: bool = False) -> SendGuestAccessTokenUseCase:
    return SendGuestAccessTokenUseCase(
        issue=IssueGuestAccessTokenUseCase(
            tokens=harness.tokens,
            stays=harness.stays,
            audit=harness.audit,
            uow=harness.inner_uow if inner_commits else CallerOwnedUnitOfWork(),
        ),
        tokens=harness.tokens,
        stays=harness.stays,
        guests=harness.guests,
        notifications=harness.notifications,
        adapters=harness.adapters,
        audit=harness.audit,
        uow=harness.uow,
        frontend_base_url=BASE_URL,
    )


def _actor() -> GuestActor:
    return GuestActor(user_id=OPERATOR, ip=IP)


async def _execute(harness: Harness) -> bool:
    return await _send(harness).execute(
        tenant_id=TENANT, reservation_id=RESERVATION, actor=_actor(), now=NOW
    )


# --- The happy path (R3.1, R3.3, R3.6, D4) --------------------------------------------


@pytest.mark.asyncio
async def test_it_mints_sends_records_and_commits_exactly_once() -> None:
    """D4 as a **sequence**, which is the only form that can fail.

    Every wrong arrangement this design rejects leaves the same rows behind: an inner commit
    splits one transaction into two without changing the final state, and an adapter call after
    the commit produces the same `SENT` row. The order is the assertion.
    """
    harness = _harness(live_token=True)

    delivered = await _execute(harness)

    assert delivered is True
    assert harness.calls == [
        "guest",
        "revoke",
        "add",
        "audit",  # GUEST_ACCESS_TOKEN_ISSUED, written by the composed mint
        "find_live",
        "send",
        "notification",
        "audit",  # GUEST_ACCESS_TOKEN_SENT
        "commit",
    ]
    # The `issued_at=now` fix to `IssueGuestAccessTokenUseCase.execute` (section 1's
    # `GuestAccessToken.issued_at` addition made this field required), asserted on a token
    # that went through the real mint — not one seeded directly by a fixture — so a
    # regression that passed some other well-typed datetime instead of `now` would be caught.
    assert harness.tokens.rows[-1].issued_at == NOW


@pytest.mark.asyncio
async def test_the_composed_mint_never_ends_the_transaction() -> None:
    """`CallerOwnedUnitOfWork` on the inner use case, asserted rather than assumed.

    The wiring is the mechanism, so this is the test that fails if somebody "fixes" the inner
    use case back to a real unit of work: two commits, and a crash between them leaves a live
    token with no `notification_logs` row and no send audit row — the precise defect design D4
    exists to prevent (R3.3, R3.6).
    """
    harness = _harness()

    await _execute(harness)

    assert harness.calls.count("commit") == 1
    assert harness.inner_uow.own == []
    assert harness.uow.own == ["commit"]


@pytest.mark.asyncio
async def test_the_wrong_wiring_is_visible_to_this_harness() -> None:
    """The guard above only means something if the harness can see the failure it forbids.

    Wired with a real inner unit of work, the same flow commits twice — and the first commit
    lands *before* the notification row. Asserting that here is what turns the previous test
    from a tautology into a check.
    """
    harness = _harness()

    await _send(harness, inner_commits=True).execute(
        tenant_id=TENANT, reservation_id=RESERVATION, actor=_actor(), now=NOW
    )

    assert harness.calls.count("commit") == 2
    assert harness.calls.index("commit") < harness.calls.index("notification")


@pytest.mark.asyncio
async def test_the_adapter_is_called_before_the_commit() -> None:
    """R3.3: the row's `status` is the adapter's real answer, so the answer must arrive while
    the transaction is still open. Committing first would leave `PENDING` as the only honest
    value — and a `PENDING` row is the dispatcher's queue, which would re-send the guest the
    *stored*, link-free body."""
    harness = _harness()

    await _execute(harness)

    assert harness.calls.index("send") < harness.calls.index("commit")


@pytest.mark.asyncio
async def test_the_guest_receives_the_real_link_for_the_token_that_was_stored() -> None:
    """R3.1 — and the link is checked against the stored digest, not against a shape.

    A body carrying a well-formed URL for some *other* token would satisfy any regex and
    authorise nothing. This asserts the value in the mail is the one whose hash the repository
    holds.
    """
    harness = _harness()

    await _execute(harness)

    recipient, subject, body = harness.adapter.sent[-1]
    assert recipient == "ada@example.com"
    assert subject
    assert body is not None
    token = body.rsplit("/guest/", 1)[1].strip()
    assert body.startswith("Le hemos enviado")
    assert f"{BASE_URL}/guest/{token}" in body
    assert harness.tokens.rows[-1].token_hash == hash_guest_token(token)


@pytest.mark.asyncio
async def test_the_stored_row_carries_no_link_no_token_and_no_identifier() -> None:
    """R3.4 and rule 11 of `steering/security.md`, asserted on the row rather than on the
    builder.

    `domain/notifications.py` exports two functions whose signatures differ by exactly one
    argument, and handing the adapter's text to the row is a one-word mistake that nothing else
    in the suite would catch: the row would look perfectly well-formed. This is the test that
    reads it.
    """
    harness = _harness()

    await _execute(harness)

    log = harness.notifications.rows[-1]
    _, _, sent_body = harness.adapter.sent[-1]
    token = (sent_body or "").rsplit("/guest/", 1)[1].strip()

    assert log.body is not None and log.subject is not None
    assert log.body != sent_body
    for forbidden in (token, "/guest/", BASE_URL, str(RESERVATION), str(GUEST)):
        assert forbidden not in log.body
        assert forbidden not in log.subject


@pytest.mark.asyncio
async def test_the_row_addresses_the_guest_and_points_at_the_reservation() -> None:
    """R3.3 — one row, addressed to the guest, keyed to the stay.

    `recipient_user_id` is `None` because the recipient is a `Guest` and not a `User`; putting
    the operator there would make the row say the platform emailed *them*. What identifies the
    stay travels as `related_type`/`related_id`, which is where R3.4 puts identifiers instead of
    in the rendered text.
    """
    harness = _harness()

    await _execute(harness)

    assert len(harness.notifications.rows) == 1
    log = harness.notifications.rows[-1]
    assert log.tenant_id == TENANT
    assert log.recipient_user_id is None
    assert log.recipient_contact == "ada@example.com"
    assert log.channel is NotificationChannel.EMAIL
    assert log.notification_type == NotificationType.GUEST_PORTAL_LINK_DELIVERED.value
    assert log.related_type == "reservation"
    assert log.related_id == RESERVATION
    assert log.status is NotificationStatus.SENT
    assert log.attempts == 1
    assert log.sent_at == NOW
    assert log.last_error is None
    # R4.2: a link the operator chose to send has no SLA to breach, so the escalation job
    # must never pick this row up.
    assert log.sla_deadline_at is None


@pytest.mark.asyncio
async def test_the_send_is_audited_against_the_new_token_with_a_real_actor() -> None:
    """R3.6 and rule 9 — and `entity_id` is the **new** credential, not the reservation.

    The issue row this same request wrote already names that token, so
    `ix_audit_logs_tenant_id_entity_type_entity_id` keeps answering "everything that happened to
    this credential". Pointing one of the two at the reservation would mix two kinds of id under
    one `entity_type`.

    The actor is the operator who pressed the button: this is an authenticated action, not one
    of rule 9's documented no-actor exceptions (those are scheduler-triggered writes).
    """
    harness = _harness()

    await _execute(harness)

    issued, sent = harness.audit.entries
    assert issued.action == audit_actions.GUEST_ACCESS_TOKEN_ISSUED
    assert sent.action == audit_actions.GUEST_ACCESS_TOKEN_SENT
    assert sent.entity_type == audit_actions.ENTITY_GUEST_ACCESS_TOKEN
    assert sent.entity_id == harness.tokens.rows[-1].id == issued.entity_id
    assert sent.actor_user_id == OPERATOR
    assert sent.actor_ip == IP
    assert sent.actor_guest_token_hash is None
    assert sent.created_at == NOW
    # No diff: a send moves no column of `guest_access_tokens`, and an invented field name is
    # what `AUDITABLE_FIELDS` refuses. `NULL`, not `{}` — the factory collapses the two.
    assert sent.changes is None


@pytest.mark.asyncio
async def test_the_language_of_both_texts_follows_the_guest() -> None:
    """Design D6 — `Guest.preferred_language` as it already exists, no new resolver."""
    spanish = _harness(language="es")
    english = _harness(language="en")

    await _execute(spanish)
    await _execute(english)

    assert spanish.adapter.sent[-1][1] != english.adapter.sent[-1][1]
    assert english.notifications.rows[-1].subject == "Your guest portal access link"
    assert spanish.notifications.rows[-1].subject == (
        "Su enlace de acceso al portal de huéspedes"
    )


# --- The adapter refuses (R3.5) --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_delivery_failure_still_commits_the_mint_and_records_why() -> None:
    """R3.5, and the whole of it: the mint is **not** rolled back by a delivery failure.

    The operator is told "link created, not delivered" (the returned `False`), the token is
    real, and the row says `FAILED` with the adapter's structured code — never provider text,
    which the return type already makes impossible.
    """
    harness = _harness(
        result=NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
    )

    delivered = await _execute(harness)

    assert delivered is False
    assert harness.calls.count("commit") == 1
    assert harness.tokens.rows[-1].revoked_at is None
    log = harness.notifications.rows[-1]
    assert log.status is NotificationStatus.FAILED
    assert log.last_error == NotificationErrorCode.INVALID_RECIPIENT.value
    assert log.sent_at is None
    assert log.attempts == 1


@pytest.mark.asyncio
async def test_a_failed_send_is_audited_exactly_like_a_successful_one() -> None:
    """R3.6 says "success or failure". A row written only on the happy path would make the
    audit trail agree with the operator's screen and disagree with what happened."""
    harness = _harness(result=NotificationResult.failure(NotificationErrorCode.TIMEOUT))

    await _execute(harness)

    actions = [entry.action for entry in harness.audit.entries]
    assert actions == [
        audit_actions.GUEST_ACCESS_TOKEN_ISSUED,
        audit_actions.GUEST_ACCESS_TOKEN_SENT,
    ]


@pytest.mark.asyncio
async def test_an_adapter_that_raises_becomes_a_failed_row_not_a_500() -> None:
    """`NotificationAdapter.send` promises never to raise for a delivery failure; when one
    breaks that promise the exception must not escape.

    It matters more here than on the anonymous recovery route: an exception past this point
    abandons the transaction, so a mint the operator has already been charged for vanishes
    along with every record that it happened — the state R3.5 exists to forbid.
    """
    harness = _harness(raises=True)

    delivered = await _execute(harness)

    assert delivered is False
    assert harness.notifications.rows[-1].last_error == (
        NotificationErrorCode.ADAPTER_ERROR.value
    )
    assert harness.calls.count("commit") == 1


@pytest.mark.asyncio
async def test_no_email_adapter_is_a_named_failure_rather_than_a_silent_one() -> None:
    """A registry with no `EMAIL` entry is a configuration error, and R3.5 wants a `FAILED`
    row that says *why*. `last_error=None` on a `FAILED` row says nothing at all."""
    harness = _harness(with_email_adapter=False)

    delivered = await _execute(harness)

    assert delivered is False
    assert harness.notifications.rows[-1].last_error == (
        NotificationErrorCode.NO_ADAPTER_FOR_CHANNEL.value
    )
    assert harness.adapter.sent == []
    assert "send" not in harness.calls


# --- Nobody to send to (R3.2) ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stay_with_no_guest_is_refused_before_anything_is_minted() -> None:
    """R3.2 — and "before" is the load-bearing word.

    A booking with no guest is legal (`POST /reservations` allows it, `guest-portal-api` OQ3),
    so this is a real path and not a defensive one. Refusing *after* the mint would replace the
    stay's live token — cutting off a guest who was mid-session — in order to tell the operator
    to go and fill in an address.
    """
    harness = _harness(guest_id=None)

    with pytest.raises(GuestContactMissingError) as refusal:
        await _execute(harness)

    assert str(refusal.value) == GuestContactMissingError.NO_GUEST
    assert harness.calls == []
    assert harness.tokens.rows == []


@pytest.mark.parametrize("email", [None, "", "   "])
@pytest.mark.asyncio
async def test_a_guest_with_no_usable_address_is_refused_before_anything_is_minted(
    email: str | None,
) -> None:
    """R3.2's other half. Whitespace counts as blank: an address of three spaces is not one,
    and the adapter should not be the layer that finds out."""
    harness = _harness(email=email)

    with pytest.raises(GuestContactMissingError) as refusal:
        await _execute(harness)

    assert str(refusal.value) == GuestContactMissingError.NO_EMAIL
    assert harness.calls == ["guest"]
    assert harness.tokens.rows == []
    assert harness.notifications.rows == []


@pytest.mark.asyncio
async def test_the_two_refusals_say_different_things() -> None:
    """R3.2 asks for an **actionable** `422`, and the two chores differ: link a guest, or give
    the linked guest an address. Safe to distinguish because the stay has already resolved
    inside the acting tenant — neither message describes a row the caller may not read."""
    assert GuestContactMissingError.NO_GUEST != GuestContactMissingError.NO_EMAIL


@pytest.mark.asyncio
async def test_a_surrounding_space_does_not_reach_the_adapter() -> None:
    """The mirror of the blank case: a stored address with whitespace around it is the same
    address, and it is stripped once, here, rather than by every consumer of the row."""
    harness = _harness(email="  ada@example.com  ")

    await _execute(harness)

    assert harness.adapter.sent[-1][0] == "ada@example.com"
    assert harness.notifications.rows[-1].recipient_contact == "ada@example.com"


# --- Tenant isolation (security rule 1) ------------------------------------------------


@pytest.mark.asyncio
async def test_a_reservation_of_another_tenant_is_a_404_and_mints_nothing() -> None:
    """Security rule 1, and the same refusal the mint and revoke siblings give.

    The stay is looked up through `PortalStayLocator`, whose key is `(tenant_id,
    reservation_id)`, so a foreign reservation is indistinguishable from one that does not
    exist — the oracle argument this module makes everywhere else.
    """
    harness = _harness()

    with pytest.raises(ReservationNotFoundError):
        await _send(harness).execute(
            tenant_id=OTHER_TENANT,
            reservation_id=RESERVATION,
            actor=_actor(),
            now=NOW,
        )

    assert harness.calls == []
    assert harness.notifications.rows == []


@pytest.mark.asyncio
async def test_an_absent_reservation_is_the_same_404() -> None:
    harness = _harness(stay=False)

    with pytest.raises(ReservationNotFoundError):
        await _execute(harness)

    assert harness.calls == []


@pytest.mark.asyncio
async def test_it_refuses_to_audit_a_credential_this_request_did_not_create() -> None:
    """The read-back is compared against the minted token's digest, not trusted.

    `find_live_for_reservation`'s predicate is "the live one for this stay", which under a
    concurrent issue is not necessarily ours. An audit row naming somebody else's credential is
    worse than none, so a mismatch raises **before** the commit and the whole operation rolls
    back rather than landing half-recorded.
    """
    harness = _harness()

    async def _somebody_elses_token(tenant_id, reservation_id):
        harness.tokens.calls.append("find_live")
        return GuestAccessToken(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            reservation_id=reservation_id,
            token_hash=hash_guest_token("a-token-from-another-request"),
            issued_at=NOW,
        )

    use_case = _send(harness)
    use_case._tokens = type(  # type: ignore[assignment]
        "Swapped", (), {"find_live_for_reservation": staticmethod(_somebody_elses_token)}
    )()

    with pytest.raises(RuntimeError):
        await use_case.execute(
            tenant_id=TENANT, reservation_id=RESERVATION, actor=_actor(), now=NOW
        )

    assert harness.calls.count("commit") == 0
    assert harness.notifications.rows == []


# --- `GetGuestAccessTokenStatusUseCase` (R2.1, R2.2, R2.3) -----------------------------


def _status(harness: Harness) -> GetGuestAccessTokenStatusUseCase:
    return GetGuestAccessTokenStatusUseCase(tokens=harness.tokens, stays=harness.stays)


@pytest.mark.asyncio
async def test_a_live_token_is_reported_with_the_instant_it_was_issued() -> None:
    """R2.1 — presence and "since when", which is what lets an operator see there is already a
    link before pressing the button that replaces it."""
    harness = _harness(live_token=True)

    status = await _status(harness).execute(tenant_id=TENANT, reservation_id=RESERVATION)

    assert status.is_live is True
    assert status.issued_at == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_stay_with_no_token_reports_absence_without_minting_one() -> None:
    """R2.1's other side, and the point of the whole surface: asking is not minting."""
    harness = _harness()

    status = await _status(harness).execute(tenant_id=TENANT, reservation_id=RESERVATION)

    assert status.is_live is False
    assert status.issued_at is None
    assert harness.calls == ["find_live"]
    assert harness.tokens.rows == []


@pytest.mark.asyncio
async def test_a_revoked_token_is_not_a_live_one() -> None:
    """The same `revoked_at IS NULL` predicate the partial unique index enforces, so "live"
    cannot mean two different things across the repository and this use case."""
    harness = _harness(live_token=True)
    await harness.tokens.revoke_live_for_reservation(TENANT, RESERVATION, now=NOW)

    status = await _status(harness).execute(tenant_id=TENANT, reservation_id=RESERVATION)

    assert status.is_live is False
    assert status.issued_at is None


@pytest.mark.asyncio
async def test_the_status_of_a_foreign_reservation_is_a_404_not_a_false() -> None:
    """R2.3, and it is the reason `PortalStayLocator` runs first.

    `find_live_for_reservation` collapses "no token", "only revoked" and "another tenant's" into
    the same `None`, so without the stay lookup a neighbour's reservation would answer a
    truthful-looking `is_live: false` — which confirms the id resolves to *something*.
    """
    harness = _harness(live_token=True)

    with pytest.raises(ReservationNotFoundError):
        await _status(harness).execute(
            tenant_id=OTHER_TENANT, reservation_id=RESERVATION
        )

    assert harness.calls == []


@pytest.mark.asyncio
async def test_the_status_never_carries_the_hash(  # noqa: D401
) -> None:
    """R2.2, asserted structurally: there is no field to leak.

    A test that checked "the hash is not in the response" would pass on a type that carries it
    and happens not to have been serialised yet. This checks the type instead.
    """
    harness = _harness(live_token=True)

    status = await _status(harness).execute(tenant_id=TENANT, reservation_id=RESERVATION)

    assert set(vars(status)) == {"is_live", "issued_at"}
    assert "token_hash" not in vars(status)
