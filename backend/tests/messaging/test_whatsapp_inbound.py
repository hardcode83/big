"""`PostWhatsAppInboundMessageUseCase` — identity resolution and the entry into the pipeline.

`whatsapp-cloud-adapter` R4.1-R4.5, R5.1, R5.2; design D4, D5, D6.

Unit tests with the in-memory fakes of `fakes.py`, per `steering/backend-architecture.md`
("`application/`: unit tests con **fakes** en memoria de los puertos"). The two halves that
cannot be answered by a fake live elsewhere on purpose: `ensure_whatsapp`'s concurrency and
index behaviour is proved against Postgres in `test_repositories.py`, and its tenant scoping
in `test_tenant_isolation.py`. What is proved here is the *resolution* — which anchors each of
the five branches produces, which of them calls a person, and that no branch ever drops the
guest's message.

The `InboundMessageActor` "exactly one identity" invariant itself (D6, task 5.1) is pinned in
`test_value_objects.py`, including all three two-identity combinations and the triple; what
this file adds is the other half — that this use case builds the actor with `resolved_phone`
and with the number the lookup actually used.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.domain.value_objects import GuestSummary
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase
from app.messaging.application.whatsapp_inbound import (
    DEFAULT_WHATSAPP_LANGUAGE,
    PostWhatsAppInboundMessageUseCase,
)
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)
from app.messaging.domain.value_objects import InboundWhatsAppMessage
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from tests.messaging.fakes import (
    FakeConversationRepository,
    FakeGuestRepository,
    FakeIncidentReportingPort,
    FakeMessageRepository,
    FakeNotificationRepository,
    FakeOutboundAdapter,
    FakePropertyRepository,
    FakeReservationRepository,
    FakeTenantConfigRepository,
    FakeTimelineRepository,
    FakeUnitOfWork,
    FakeUserRepository,
    StubAIAdapter,
)
from tests.messaging.test_use_cases import make_user

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()

#: The tenant's default property — where a message that cannot be attached to a stay lands
#: (D4 supersession, 2026-09-02). Section 6 stores it on `WhatsAppPhoneNumberModel`; here it
#: is simply an input, exactly as `tenant_id` is.
DEFAULT_PROPERTY = uuid.uuid4()
STAY_PROPERTY = uuid.uuid4()

#: Meta's `phone_number_id` for the tenant's own number, and the sender as Meta sends it:
#: **bare digits, no `+`** — the shape section 4's `InboundWhatsAppMessage` preserves verbatim.
BUSINESS_NUMBER = "109876543210987"
SENDER_DIGITS = "34612345678"
SENDER_E164 = "+34612345678"


def make_guest(
    *, phone: str | None = SENDER_E164, guest_id: uuid.UUID | None = None
) -> GuestSummary:
    return GuestSummary(
        id=guest_id or uuid.uuid4(),
        full_name="Ana",
        email="ana@example.com",
        phone=phone,
        preferred_language="es",
        document_status=GuestDocumentStatus.NOT_PROVIDED,
        legal_registration_status=LegalRegistrationStatus.NOT_REQUIRED,
    )


def make_reservation(
    *,
    guest_id: uuid.UUID,
    property_id: uuid.UUID = STAY_PROPERTY,
    check_in: date | None = None,
    nights: int = 2,
    tenant_id: uuid.UUID = TENANT,
) -> Reservation:
    start = check_in or NOW.date()
    return Reservation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        channel=ReservationChannel.DIRECT,
        check_in_date=start,
        check_out_date=start + timedelta(days=nights),
        nights=nights,
        created_at=NOW,
        updated_at=NOW,
        guest_id=guest_id,
        status=ReservationStatus.CONFIRMED,
    )


def make_inbound(
    *,
    sender_phone: str = SENDER_DIGITS,
    text: str = "¿A qué hora es el check-in?",
    received_at: datetime | None = None,
) -> InboundWhatsAppMessage:
    return InboundWhatsAppMessage(
        sender_phone=sender_phone,
        provider_message_id=f"wamid.{uuid.uuid4().hex}",
        text=text,
        received_at=received_at or NOW,
        business_phone_number=BUSINESS_NUMBER,
    )


class _MessagesForNewThreads(FakeMessageRepository):
    """`FakeMessageRepository` refuses a conversation it was not told about.

    On this path the conversation is created *during* the run by `ensure_whatsapp`, so the set
    of known threads is read from the conversation repository at write time rather than
    pre-seeded. Keeping the refusal (instead of dropping it) is what still proves the message
    is written into the conversation this use case resolved and not into a fresh id.
    """

    def __init__(self, conversations: FakeConversationRepository) -> None:
        super().__init__()
        self._conversations = conversations

    async def add(self, tenant_id: uuid.UUID, message) -> None:
        self.known_conversations |= set(self._conversations.rows)
        await super().add(tenant_id, message)


class Harness:
    """The use case with every port faked, plus the handles a test asserts on."""

    def __init__(
        self,
        *,
        guests: FakeGuestRepository | None = None,
        reservations: FakeReservationRepository | None = None,
        conversations: FakeConversationRepository | None = None,
        ai: StubAIAdapter | None = None,
        threshold: Decimal = Decimal("0.75"),
    ) -> None:
        self.conversations = conversations or FakeConversationRepository()
        self.messages = _MessagesForNewThreads(self.conversations)
        self.guests = guests or FakeGuestRepository()
        self.reservations = reservations or FakeReservationRepository()
        self.ai = ai or StubAIAdapter()
        self.adapter = FakeOutboundAdapter()
        self.timeline = FakeTimelineRepository()
        self.notifications = FakeNotificationRepository()
        self.incidents = FakeIncidentReportingPort()
        self.uow = FakeUnitOfWork()
        self.pipeline = ProcessInboundGuestMessageUseCase(
            conversations=self.conversations,
            messages=self.messages,
            ai=self.ai,
            channels={ConversationChannel.WHATSAPP: self.adapter},
            incidents=self.incidents,
            timeline=self.timeline,
            notifications=self.notifications,
            users=FakeUserRepository(make_user(TENANT)),
            guests=self.guests,
            configs=FakeTenantConfigRepository(threshold=threshold),
            properties=FakePropertyRepository(),
            reservations=self.reservations,
            uow=self.uow,
        )
        self.use_case = PostWhatsAppInboundMessageUseCase(
            conversations=self.conversations,
            guests=self.guests,
            reservations=self.reservations,
            pipeline=self.pipeline,
        )

    async def run(
        self,
        inbound: InboundWhatsAppMessage | None = None,
        *,
        tenant_id: uuid.UUID = TENANT,
        default_property_id: uuid.UUID = DEFAULT_PROPERTY,
        now: datetime = NOW,
    ):
        return await self.use_case.execute(
            tenant_id=tenant_id,
            default_property_id=default_property_id,
            inbound_message=inbound or make_inbound(),
            now=now,
        )

    def thread(self):
        """The one conversation the run resolved. Asserts there is exactly one."""
        assert len(self.conversations.rows) == 1, self.conversations.rows
        return next(iter(self.conversations.rows.values()))


# --- R4.3: nobody has that number ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_number_still_gets_a_conversation_on_the_default_property() -> None:
    """R4.3: "registrar el mensaje de forma que quede visible a un operador… en vez de
    descartarlo en silencio, y no SHALL inventar una asociación".

    All three halves asserted: the message exists, the thread is on the tenant's default
    property (D4 supersession — `Conversation.property_id` cannot be `None`), and **no
    association was invented**: no guest and no stay.
    """
    harness = Harness()

    message = await harness.run()

    thread = harness.thread()
    assert thread.channel is ConversationChannel.WHATSAPP
    assert thread.property_id == DEFAULT_PROPERTY
    assert thread.guest_id is None
    assert thread.reservation_id is None
    assert message.conversation_id == thread.id
    assert message.sender_type is MessageSenderType.GUEST
    assert message.content == "¿A qué hora es el check-in?"


@pytest.mark.asyncio
async def test_an_unknown_number_is_not_escalated() -> None:
    """R4.4 names *ambiguity* as the escalation trigger, and R4.3 names visibility for the
    no-match case — two different answers, so the no-match branch must not quietly borrow the
    other's. The manager sees it through the inbox, not through a handover."""
    harness = Harness()

    await harness.run()

    thread = harness.thread()
    assert thread.escalation_status is ConversationEscalationStatus.NONE
    assert thread.status is ConversationStatus.OPEN


@pytest.mark.asyncio
async def test_the_thread_is_visible_in_the_operators_inbox() -> None:
    """What "visible a un operador" resolves to concretely: the row the manager's inbox query
    returns (R7.3's listing, scoped to the tenant), on the default property."""
    harness = Harness()

    await harness.run()

    from app.messaging.domain.repositories import ConversationFilters

    page = await harness.conversations.list(
        TENANT, ConversationFilters(), page=1, per_page=50
    )
    assert [row.property_id for row in page.items] == [DEFAULT_PROPERTY]


# --- R4.2: exactly one guest ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_known_number_with_one_active_stay_uses_that_stays_property() -> None:
    """R4.2 end to end, and the one branch that resolves a real stay: the thread hangs off the
    reservation's own property — **not** the default one, which is the whole point of keeping
    the default as a fallback rather than as the answer."""
    guest = make_guest()
    stay = make_reservation(guest_id=guest.id)
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(stay),
    )

    await harness.run()

    thread = harness.thread()
    assert thread.guest_id == guest.id
    assert thread.property_id == STAY_PROPERTY
    assert thread.reservation_id == stay.id
    assert thread.escalation_status is ConversationEscalationStatus.NONE


@pytest.mark.asyncio
async def test_the_bare_digits_meta_sends_are_matched_against_a_stored_e164_number() -> None:
    """**The gotcha section 3's notes warned about.** Meta's `from` is `"34612345678"` — a
    full E.164 number with no `+` — and `normalize_phone_e164`'s bare-number branch only
    recognises a 9-digit *national* number, so without the `+` prepended by the use case this
    lookup returns `None`, every guest looks unknown, and R4.2 never fires for a real message.

    The guest below is stored exactly as `guests.phone` stores it, and the message carries
    exactly what Meta sends.
    """
    guest = make_guest(phone=SENDER_E164)
    harness = Harness(guests=FakeGuestRepository(guest))

    await harness.run(make_inbound(sender_phone=SENDER_DIGITS))

    assert harness.thread().guest_id == guest.id


@pytest.mark.asyncio
async def test_a_known_guest_with_no_active_stay_lands_on_the_default_property() -> None:
    """R4.3's other shape: the guest is known, the stay is not. The thread names the guest —
    that association is not invented, the phone matched — and falls back for the property."""
    guest = make_guest()
    old_stay = make_reservation(guest_id=guest.id, check_in=NOW.date() - timedelta(days=60))
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(old_stay),
    )

    await harness.run()

    thread = harness.thread()
    assert thread.guest_id == guest.id
    assert thread.property_id == DEFAULT_PROPERTY
    assert thread.reservation_id is None
    assert thread.escalation_status is ConversationEscalationStatus.NONE


@pytest.mark.asyncio
async def test_the_stay_window_is_asked_about_the_moment_the_guest_wrote() -> None:
    """D5's `on_date` is the **message's** date and not the processing clock.

    A webhook redelivered — or a Celery task retried — days later must still ask "was there a
    stay when the guest wrote", which is the difference this test pins: the stay below ended
    long before `now`, and is still the one the message is about.
    """
    guest = make_guest()
    stay = make_reservation(guest_id=guest.id, check_in=date(2026, 8, 15), nights=1)
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(stay),
    )

    await harness.run(
        make_inbound(received_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC)),
        now=datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
    )

    assert harness.thread().reservation_id == stay.id


# --- R4.4: ambiguity goes to a person ------------------------------------------------------


@pytest.mark.asyncio
async def test_two_guests_sharing_a_number_escalate_and_name_neither() -> None:
    """R4.4: "escalar a revisión humana en vez de adivinar cuál es la conversación correcta".

    Both halves: the thread is handed to a person, and `guest_id` stays `None` — naming either
    guest would be exactly the guess the requirement forbids.
    """
    first, second = make_guest(), make_guest()
    harness = Harness(guests=FakeGuestRepository(first, second))

    await harness.run()

    thread = harness.thread()
    assert thread.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert thread.status is ConversationStatus.ESCALATED
    assert thread.guest_id is None
    assert thread.property_id == DEFAULT_PROPERTY


@pytest.mark.asyncio
async def test_two_active_stays_of_one_guest_escalate_and_attach_no_stay() -> None:
    """R4.4's second trigger. The guest is unambiguous, the stay is not — so the guest is
    named and `reservation_id` is left `None` rather than picking the nearer stay."""
    guest = make_guest()
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(
            make_reservation(guest_id=guest.id),
            make_reservation(guest_id=guest.id, property_id=uuid.uuid4()),
        ),
    )

    await harness.run()

    thread = harness.thread()
    assert thread.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert thread.guest_id == guest.id
    assert thread.reservation_id is None
    assert thread.property_id == DEFAULT_PROPERTY


@pytest.mark.asyncio
async def test_the_ai_never_answers_a_message_that_went_to_a_person() -> None:
    """Why the escalation happens **before** the pipeline runs (D5).

    `Conversation.is_handed_over()` is what the pipeline asks before letting the AI reply, and
    `PENDING_HUMAN` answers `True` — so escalating first is what keeps the AI from answering a
    sender we just declared unidentified. Escalating afterwards would pass every assertion
    above and still send that reply, which is why this one asserts on the adapter and on the
    absence of an `AI` row.
    """
    harness = Harness(guests=FakeGuestRepository(make_guest(), make_guest()))

    await harness.run()

    assert harness.adapter.sends == []
    assert harness.messages.by_sender(MessageSenderType.AI) == []
    assert harness.ai.generate_calls == []


@pytest.mark.asyncio
async def test_an_ambiguous_message_is_still_recorded_and_classified() -> None:
    """Escalating is not dropping: R4.3's "nunca en silencio" holds on the R4.4 branches too,
    and R5.2's "sin duplicarlas" means the pipeline still ran — one commit, one message, one
    classification."""
    harness = Harness(guests=FakeGuestRepository(make_guest(), make_guest()))

    message = await harness.run()

    assert harness.messages.by_sender(MessageSenderType.GUEST) == [message]
    assert harness.ai.classify_calls == 1
    assert harness.uow.commits == 1


@pytest.mark.asyncio
async def test_a_thread_a_person_already_holds_is_not_escalated_twice() -> None:
    """R5.4's "NEVER SHALL emitir una segunda notificación… mientras siga `PENDING_HUMAN`",
    from this side: the second ambiguous message finds the thread already handed over and
    leaves both axes exactly where they were, without raising."""
    guest = make_guest()
    reservations = FakeReservationRepository(
        make_reservation(guest_id=guest.id),
        make_reservation(guest_id=guest.id, property_id=uuid.uuid4()),
    )
    harness = Harness(guests=FakeGuestRepository(guest), reservations=reservations)

    await harness.run()
    first = harness.thread()
    escalated_at = first.updated_at

    await harness.run(make_inbound(text="¿Hola?"), now=NOW + timedelta(minutes=5))

    thread = harness.thread()
    assert thread.id == first.id
    assert thread.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert thread.status is ConversationStatus.ESCALATED
    assert thread.updated_at >= escalated_at


@pytest.mark.asyncio
async def test_a_resolved_thread_does_not_lose_the_message_when_it_cannot_escalate() -> None:
    """The one transition the table refuses outright: `escalate` accepts `OPEN` alone, so an
    ambiguous message into a thread a manager had marked `RESOLVED` cannot escalate.

    R4.3 decides what happens then — the message is never lost — and the pipeline's own
    `_resolve` reopens the thread. Raising here would instead abort the transaction, and since
    Meta redelivers on any non-2xx, that would retry the same message forever.
    """
    guest = make_guest()
    reservations = FakeReservationRepository(
        make_reservation(guest_id=guest.id),
        make_reservation(guest_id=guest.id, property_id=uuid.uuid4()),
    )
    harness = Harness(guests=FakeGuestRepository(guest), reservations=reservations)
    await harness.run()
    thread = harness.thread()
    thread.escalation_status = ConversationEscalationStatus.RESOLVED
    thread.status = ConversationStatus.RESOLVED

    message = await harness.run(make_inbound(text="¿Sigue ahí?"), now=NOW + timedelta(hours=1))

    assert message.conversation_id == thread.id
    assert harness.thread().status is ConversationStatus.OPEN


# --- R4.5: one thread per guest and property -----------------------------------------------


@pytest.mark.asyncio
async def test_a_second_message_from_the_same_guest_reuses_the_thread() -> None:
    """R4.5: "SHALL reutilizarla en vez de crear una nueva por cada mensaje"."""
    guest = make_guest()
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(make_reservation(guest_id=guest.id)),
    )

    first = await harness.run()
    second = await harness.run(make_inbound(text="Gracias"), now=NOW + timedelta(minutes=1))

    assert len(harness.conversations.rows) == 1
    assert first.conversation_id == second.conversation_id


@pytest.mark.asyncio
async def test_the_second_message_does_not_rewrite_the_business_number() -> None:
    """D4's addendum, from the use case's side: the second call passes the number again and the
    thread keeps the one it was opened on (`ensure_whatsapp` does `DO NOTHING`, not
    `DO UPDATE`), so a reply always leaves from where the conversation started."""
    guest = make_guest()
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(make_reservation(guest_id=guest.id)),
    )

    await harness.run()
    await harness.run(make_inbound(text="Gracias"), now=NOW + timedelta(minutes=1))

    assert harness.thread().business_phone_number == BUSINESS_NUMBER
    assert [call["business_phone_number"] for call in harness.conversations.ensure_whatsapp_calls] == [
        BUSINESS_NUMBER,
        BUSINESS_NUMBER,
    ]


# --- R5.1: the same pipeline the portal uses ----------------------------------------------


@pytest.mark.asyncio
async def test_the_message_goes_through_the_existing_pipeline_marked_whatsapp() -> None:
    """R5.1 and R5.2: the same use case the portal invokes, with the channel marked `WHATSAPP`
    — structurally, since the channel is the conversation's and nothing here can override it.
    The pipeline's own products are the evidence: a classified guest message, a timeline
    event, and exactly one commit."""
    guest = make_guest()
    harness = Harness(
        guests=FakeGuestRepository(guest),
        reservations=FakeReservationRepository(make_reservation(guest_id=guest.id)),
    )

    message = await harness.run()

    from app.timeline.domain.enums import TimelineEventType

    assert harness.thread().channel is ConversationChannel.WHATSAPP
    assert message.sender_type is MessageSenderType.GUEST
    assert message.intent == harness.ai.intent.value
    assert len(harness.timeline.of_type(TimelineEventType.GUEST_MESSAGE_RECEIVED)) == 1
    assert harness.uow.commits == 1
    assert harness.thread().last_message_at == NOW


def test_this_module_never_constructs_a_message() -> None:
    """R5.2's "sin duplicarlas", as a property of the source rather than of a run: the rule-11
    census counts *use cases that write `messages.content`*, and this one must not become a
    third. The pipeline builds the row; this module resolves where it goes.

    **The technique is the one `test_portal_use_cases.py::
    test_the_submitter_never_constructs_a_message` settled on after three wrong versions**, and
    it is reproduced rather than imported because that guard's walker is a local of its own
    test. Its three lessons are what this needs too: a substring also matches
    `InboundWhatsAppMessage(`; a word-boundary regex matches this module's own docstring
    promising there is no such call (the first version of *this* test failed exactly there);
    and an `ast.Name`-only walk is blind to `entities.Message(...)` and to `import ... as M`.
    The rule is about the binding, not the spelling.
    """
    import ast
    import inspect

    from app.messaging.application import whatsapp_inbound

    def constructions(source: str) -> set[str]:
        tree = ast.parse(source)
        aliases = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name == "Message"
        }
        called: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        return called | {name for name in aliases if name in called}

    called = constructions(inspect.getsource(whatsapp_inbound))

    assert "Message" not in called
    # The counter-examples, so a broken walker cannot make the assertion above vacuous.
    assert "Message" in constructions("from x import Message\nMessage(id=1)")
    assert "Message" in constructions("from x import entities\nentities.Message(id=1)")
    assert "M" in constructions("from x import Message as M\nM(id=1)")
    # And the value object this module *does* build is visible, so the walker sees calls.
    assert "_Anchors" in called


def test_this_module_holds_no_message_repository() -> None:
    """The other half of the same claim, from the dependency list: a use case that cannot
    reach `MessageRepository` cannot write a message row however it is edited later. Four
    dependencies, and `messages` is not one of them."""
    import inspect

    parameters = set(
        inspect.signature(PostWhatsAppInboundMessageUseCase.__init__).parameters
    ) - {"self"}

    assert parameters == {"conversations", "guests", "reservations", "pipeline"}


@pytest.mark.asyncio
async def test_the_actor_is_named_by_the_resolved_phone_number() -> None:
    """D6: the third identity, carrying the E.164 number the webhook authenticated by — and
    the normalised form, which is the one the guest lookup used."""
    recorded: list = []
    guest = make_guest()
    harness = Harness(guests=FakeGuestRepository(guest))
    original = harness.pipeline.execute

    async def spy(**kwargs):
        recorded.append(kwargs["actor"])
        return await original(**kwargs)

    harness.pipeline.execute = spy  # type: ignore[method-assign]

    await harness.run()

    (actor,) = recorded
    assert actor.resolved_phone == SENDER_E164
    assert actor.user_id is None
    assert actor.token_hash is None


# --- Numbers that do not normalise ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unnormalisable_number_is_treated_as_no_match_and_never_discarded() -> None:
    """The normaliser fails closed (`None`, never a guess), and R4.3 decides what that means:
    the message is recorded on the default property with no guest, rather than looked up raw
    — a raw lookup against E.164-stored numbers could only ever match by accident.
    """
    guest = make_guest(phone="123")
    harness = Harness(guests=FakeGuestRepository(guest))

    message = await harness.run(make_inbound(sender_phone="123"))

    thread = harness.thread()
    assert thread.guest_id is None
    assert thread.property_id == DEFAULT_PROPERTY
    assert message.conversation_id == thread.id


@pytest.mark.asyncio
async def test_an_unnormalisable_number_still_names_an_actor() -> None:
    """`InboundMessageActor` refuses to name nobody, so the actor falls back to the number as
    it arrived: it is still what the webhook authenticated by, and the audit trail of an
    unidentified sender is the only trace there is."""
    recorded: list = []
    harness = Harness()
    original = harness.pipeline.execute

    async def spy(**kwargs):
        recorded.append(kwargs["actor"])
        return await original(**kwargs)

    harness.pipeline.execute = spy  # type: ignore[method-assign]

    await harness.run(make_inbound(sender_phone="123"))

    (actor,) = recorded
    assert actor.resolved_phone == "+123"


# --- Language ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_thread_is_born_in_the_language_of_its_first_message() -> None:
    harness = Harness()

    await harness.run(make_inbound(text="What time is the check in please?"))

    assert harness.thread().language == "en"


@pytest.mark.asyncio
async def test_a_message_that_does_not_say_falls_back_to_the_default_language() -> None:
    harness = Harness()

    await harness.run(make_inbound(text="?!"))

    assert harness.thread().language == DEFAULT_WHATSAPP_LANGUAGE


# --- R4.1/rule 1: the tenant is never crossed ----------------------------------------------


@pytest.mark.asyncio
async def test_a_guest_of_another_tenant_with_the_same_number_is_not_matched() -> None:
    """Rule 1 of `steering/security.md` over the whole resolution, not just over one query.

    The same phone number exists in two tenants' guest tables — the exact scenario D5 rejects
    a cross-tenant lookup for. Resolving for tenant A must reach A's guest only, and the
    thread must belong to A: `find_by_phone` takes the tenant as a required parameter, and
    this test is what proves the use case passes the one it was given rather than a tenant
    read off the message.
    """
    ours, theirs = make_guest(), make_guest()
    guests = FakeGuestRepository(
        ours, theirs, tenants={ours.id: TENANT, theirs.id: OTHER_TENANT}
    )
    harness = Harness(
        guests=guests,
        reservations=FakeReservationRepository(make_reservation(guest_id=ours.id)),
    )

    await harness.run(tenant_id=TENANT)

    thread = harness.thread()
    assert thread.tenant_id == TENANT
    assert thread.guest_id == ours.id


@pytest.mark.asyncio
async def test_a_stay_of_another_tenant_is_not_the_stay_of_this_message() -> None:
    """The second query of the resolution, scoped the same way: the guest is ours, the stay
    with the matching dates is another tenant's, and it must not be attached — the fallback to
    the default property is the right answer, not the other tenant's reservation."""
    guest = make_guest()
    harness = Harness(
        guests=FakeGuestRepository(guest, tenants={guest.id: TENANT}),
        reservations=FakeReservationRepository(
            make_reservation(guest_id=guest.id, tenant_id=OTHER_TENANT)
        ),
    )

    await harness.run(tenant_id=TENANT)

    thread = harness.thread()
    assert thread.reservation_id is None
    assert thread.property_id == DEFAULT_PROPERTY


@pytest.mark.asyncio
async def test_the_tenant_and_the_default_property_come_only_from_the_parameters() -> None:
    """R4.1: "no SHALL resolver el tenant… desde ningún campo del cuerpo que el remitente del
    mensaje controle". Enforced by the shape rather than by a check — there is no repository
    in this class through which a body could name a tenant — and pinned here: the anchors
    `ensure_whatsapp` receives carry the parameters, and the message's own
    `business_phone_number` reaches the row as data only.
    """
    harness = Harness()

    await harness.run(tenant_id=TENANT, default_property_id=DEFAULT_PROPERTY)

    (call,) = harness.conversations.ensure_whatsapp_calls
    assert call["tenant_id"] == TENANT
    assert call["property_id"] == DEFAULT_PROPERTY
    assert call["business_phone_number"] == BUSINESS_NUMBER
