"""The portal's two use cases (`guest-portal-messaging` R1.4, R2.1-R2.5, R3.3, D3, D5, D9).

Driven over the same in-memory fakes as `test_use_cases.py`, because what is under test here
is composition rather than persistence: that the submitter runs the **existing** pipeline
instead of a second copy of it, and that the reader publishes a projection with nothing extra
in it. The persistence-level guarantees these lean on — the `ON CONFLICT` race, tenant scoping
— are proved against a real Postgres in `test_repositories.py` and `test_tenant_isolation.py`,
which are the only places they can be.
"""

import uuid
from datetime import timedelta

import pytest

from app.guests.domain.portal_ports import (
    GuestPortalMessageSubmitter,
    GuestPortalThreadReader,
    GuestSession,
    PortalMessage,
    PortalMessageSender,
    PortalThreadState,
)
from app.messaging.application.portal import (
    PostPortalGuestMessageUseCase,
    ReadPortalThreadUseCase,
    _SENDER,
)
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    MessageIntent,
    MessageSenderType,
)
from app.timeline.domain.enums import TimelineEventType
from tests.messaging.conftest import NOW
from tests.messaging.test_use_cases import (
    GUEST_MESSAGE,
    Harness,
    StubAIAdapter,
    TENANT,
    make_conversation,
)

#: An emergency keyword of `escalation.EMERGENCY_KEYWORDS`, so the policy escalates rather
#: than replying. Spelled out here rather than imported, because what this file needs is a
#: message that *does* escalate and not the particular one another test happens to use.
ESCALATES = "Hay sangre en el bano"


RESERVATION = uuid.uuid4()
PROPERTY = uuid.uuid4()
GUEST = uuid.uuid4()
DIGEST = "d" * 64
CLIENT_IP = "203.0.113.42"

SESSION = GuestSession(
    tenant_id=TENANT,
    reservation_id=RESERVATION,
    property_id=PROPERTY,
    guest_id=GUEST,
    token_hash=DIGEST,
)


def submitter(harness: Harness) -> PostPortalGuestMessageUseCase:
    return PostPortalGuestMessageUseCase(
        conversations=harness.conversations, pipeline=harness.use_case
    )


def portal_harness(*, ai=None, **conversation_kwargs) -> Harness:
    """A harness whose conversation is the stay's `PORTAL` thread, already open.

    The stay's anchors are set after construction because `make_conversation` does not take
    them — every other test in this suite works with conversations that have no reservation,
    and the portal is the first caller for which the stay is the key.
    """
    conversation = make_conversation(
        channel=ConversationChannel.PORTAL, **conversation_kwargs
    )
    conversation.reservation_id = RESERVATION
    conversation.property_id = PROPERTY
    harness = Harness(conversation, ai=ai)
    harness.channels[ConversationChannel.PORTAL] = harness.adapter
    return harness


# --- The submitter runs the pipeline whole (R1.4, D5) -------------------------------------


@pytest.mark.asyncio
async def test_the_whole_pipeline_runs_for_a_portal_message() -> None:
    """R1.4: "el pipeline de `messaging-ai` **entero y sin duplicarlo**".

    Asserted through its artefacts rather than by inspecting the call: the message carries the
    intent and the confidence the classifier produced, the timeline gained the guest's event,
    and a reply was delivered — none of which a second, simpler write path would produce.
    """
    harness = portal_harness()

    result = await submitter(harness).submit(SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW)

    assert isinstance(result, PortalMessage)
    stored = harness.messages.rows[0]
    assert stored.intent is not None
    assert stored.confidence_score is not None
    assert any(
        event.event_type is TimelineEventType.GUEST_MESSAGE_RECEIVED
        for event in harness.timeline.events
    )
    assert harness.adapter.sends


@pytest.mark.asyncio
async def test_the_portal_message_lands_in_a_single_commit() -> None:
    """R1.4's "en **una sola transacción**". The submitter adds a step before the pipeline —
    resolving the conversation — and must not add a commit of its own."""
    harness = portal_harness()

    await submitter(harness).submit(SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW)

    assert harness.uow.commits == 1


def test_the_submitter_never_constructs_a_message() -> None:
    """D5, structurally: "**No construye ningún `Message`.**"

    The census of rule 11 counts *use cases that write `messages.content`*, and D5's claim is
    that this change does not move that number — it is still the two use cases of
    `messaging/application/use_cases.py`. This is what makes that claim checkable.

    **Three earlier versions of this guard were wrong, each in a way worth keeping written
    down**, because they are the standard failure modes of a structural check:

    1. `"Message(" in source` — also matched `PortalMessage(`, the projection this module
       exists to build. A substring cannot tell a type from a type whose name ends in it.
    2. a word-boundary regex on `Message(` — matched the sentence in this module's own
       docstring promising there is no such call. A guard that reads prose is not reading code.
    3. Walking the AST but only for `ast.Call` with an `ast.Name` func — blind to
       `entities.Message(...)` (an `ast.Attribute`) and to
       `from ... import Message as M; M(...)`. The QA panel of sections 5-6 demonstrated both
       bypasses, so both are covered below and both are exercised by the counter-examples.

    The rule this settles on is about the **binding**, not the spelling: whatever name
    `messaging.domain.entities.Message` is reachable under in this module must never be called.
    """
    import ast
    import inspect

    from app.messaging.application import portal

    def constructions(source: str) -> set[str]:
        """Every name called in `source`, plus the local aliases of an imported `Message`."""
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
                # `entities.Message(...)` — the qualified form the third version missed.
                called.add(node.func.attr)
        return called | {name for name in aliases if name in called}

    called = constructions(inspect.getsource(portal))

    assert "Message" not in called
    # The counter-examples. Without them a refactor that broke the walker would leave every
    # assertion above vacuously true — the failure `mutation-that-doesnt-apply` describes.
    assert "Message" in constructions("from x import Message\nMessage(id=1)")
    assert "Message" in constructions("from x import entities\nentities.Message(id=1)")
    assert "M" in constructions("from x import Message as M\nM(id=1)")
    # And the projection this module *does* build is still visible, so the walker sees calls.
    assert "PortalMessage" in called


@pytest.mark.asyncio
async def test_the_audit_actor_carries_the_address_the_request_came_from() -> None:
    """Rule 9 of `steering/security.md` names `actor_ip` as one of the two things `audit_logs`
    records that nothing else does, and none of its five exceptions covers this path — they are
    all grounded in there being no request to take an address from, and the portal has one.

    Until the security panel of sections 5-6, this path passed no address at all, so every
    portal-originated `INCIDENT_CREATED` row went with `actor_ip` NULL while the sibling
    anonymous route (`POST /guest/incident/{token}`) recorded one for the same kind of actor.
    """
    harness = portal_harness(ai=StubAIAdapter(intent=MessageIntent.MAINTENANCE_ISSUE))

    await submitter(harness).submit(
        SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW
    )

    actor = harness.incidents.reports[0]["actor"]
    assert actor.ip == CLIENT_IP
    assert actor.token_hash == DIGEST
    assert actor.user_id is None


@pytest.mark.asyncio
async def test_a_request_with_no_resolvable_address_still_records_the_message() -> None:
    """`client_ip` is `None` when the address cannot be resolved. That must not refuse the
    guest's message — losing what they typed to protect an audit column would be the wrong
    trade, and `AuditLogFactory` accepts a null `actor_ip` for exactly this reason."""
    harness = portal_harness(ai=StubAIAdapter(intent=MessageIntent.MAINTENANCE_ISSUE))

    await submitter(harness).submit(
        SESSION, content=GUEST_MESSAGE, client_ip=None, now=NOW
    )

    assert harness.incidents.reports[0]["actor"].ip is None
    assert harness.messages.rows


@pytest.mark.asyncio
async def test_an_incident_intent_still_opens_its_incident_with_the_token_actor() -> None:
    """R1.4 names the incident among the steps, and R4.1 says who reports it. Both at once,
    because the portal is the first caller for which the reporter is not a `User`."""
    harness = portal_harness(
        ai=StubAIAdapter(intent=MessageIntent.MAINTENANCE_ISSUE)
    )

    await submitter(harness).submit(SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW)

    assert len(harness.incidents.reports) == 1
    assert harness.incidents.reports[0]["actor"].token_hash == DIGEST
    assert harness.incidents.reports[0]["actor"].user_id is None


@pytest.mark.asyncio
async def test_an_escalating_message_escalates_rather_than_replying() -> None:
    harness = portal_harness()

    await submitter(harness).submit(SESSION, content=ESCALATES, client_ip=CLIENT_IP, now=NOW
    )

    assert harness.conversation.escalation_status is (
        ConversationEscalationStatus.PENDING_HUMAN
    )


# --- Resolving the conversation (R1.3, R3.3) ----------------------------------------------


@pytest.mark.asyncio
async def test_every_anchor_comes_from_the_session_and_from_nowhere_else() -> None:
    """R1.3, and the obligation task 6.2 carries from the section 3-4 security panel.

    `ensure_portal` **states** that its three anchors were resolved within the tenant and does
    not check them — `conversations`' foreign keys are global rather than composite with
    `tenant_id` — so this use case is the whole of what makes the precondition true. The gap it
    leaves for any other caller is pinned in
    `test_tenant_isolation.py::test_ensure_portal_does_not_verify_the_stay_belongs_to_the_tenant`.
    """
    harness = portal_harness()

    await submitter(harness).submit(SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW)

    call = harness.conversations.ensure_portal_calls[0]
    assert call["tenant_id"] == SESSION.tenant_id
    assert call["reservation_id"] == SESSION.reservation_id
    assert call["property_id"] == SESSION.property_id
    assert call["guest_id"] == SESSION.guest_id


@pytest.mark.asyncio
async def test_a_second_message_writes_into_the_same_thread() -> None:
    """R3.4 at this layer: `ensure_portal` is asked every time and answers with the same row,
    so the second message does not open a second conversation."""
    harness = portal_harness()
    use_case = submitter(harness)

    await use_case.submit(SESSION, content=GUEST_MESSAGE, client_ip=CLIENT_IP, now=NOW)
    await use_case.submit(SESSION, content="Otra cosa mas", client_ip=CLIENT_IP, now=NOW + timedelta(minutes=1))

    portal_rows = [
        row for row in harness.conversations.rows.values()
        if row.channel is ConversationChannel.PORTAL
    ]
    assert len(portal_rows) == 1
    assert len(harness.messages.rows) >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected"),
    [("Good morning, the wifi is not working", "en"), ("Hola, no va el wifi", "es")],
)
async def test_the_new_thread_takes_the_language_of_the_first_message(
    content: str, expected: str
) -> None:
    """R3.3."""
    harness = portal_harness()

    await submitter(harness).submit(SESSION, content=content, client_ip=CLIENT_IP, now=NOW)

    assert harness.conversations.ensure_portal_calls[0]["language"] == expected


@pytest.mark.asyncio
async def test_a_message_in_no_particular_language_opens_the_thread_in_spanish() -> None:
    """R3.3's "IF el idioma no puede decidirse, THEN SHALL usar `es`". `detect_language`
    answers `None` on no evidence, and that `None` is a real answer rather than a failure."""
    harness = portal_harness()

    await submitter(harness).submit(SESSION, content="...", client_ip=CLIENT_IP, now=NOW)

    assert harness.conversations.ensure_portal_calls[0]["language"] == "es"


# --- The reader (R2.1, R2.3, R2.5, D9) ----------------------------------------------------


def reader(harness: Harness) -> ReadPortalThreadUseCase:
    return ReadPortalThreadUseCase(
        conversations=harness.conversations, messages=harness.messages
    )


@pytest.mark.asyncio
async def test_a_stay_with_no_thread_reads_empty_and_creates_nothing() -> None:
    """R2.5: "leer no abre conversación". Both halves — the answer and the absence of a row."""
    harness = Harness(make_conversation())
    before = len(harness.conversations.rows)

    thread = await reader(harness).read(SESSION, page=None, per_page=20)

    assert thread.items == ()
    assert thread.total == 0
    assert thread.state is PortalThreadState.AUTOMATIC
    assert len(harness.conversations.rows) == before


@pytest.mark.asyncio
async def test_the_thread_is_ascending_and_publishes_its_window() -> None:
    """R2.1: chronological ascending, and `total`/`page`/`per_page` travel so the client knows
    which window it holds — which D9's last-page default makes necessary rather than polite."""
    harness = portal_harness()
    use_case = submitter(harness)
    for offset in range(3):
        await use_case.submit(SESSION, content=f"mensaje {offset}", client_ip=CLIENT_IP, now=NOW + timedelta(minutes=offset)
        )

    thread = await reader(harness).read(SESSION, page=None, per_page=20)

    timestamps = [item.created_at for item in thread.items]
    assert timestamps == sorted(timestamps)
    assert thread.per_page == 20
    assert thread.total == len(thread.items)
    assert thread.page == 1


@pytest.mark.asyncio
async def test_without_a_page_the_reader_returns_the_last_window() -> None:
    """D9, the decision that departs from this API's `page=1` convention.

    The count is read from the harness rather than written here: four `submit` calls do **not**
    produce four rows — the pipeline answers most of them, so the thread holds the guest's
    messages *and* the automatic replies. An earlier version of this docstring said "with four
    messages … page 2", which was wrong by three rows; the assertion was already computing the
    real total, so the test was right and only its prose was not. Caught by the QA panel of
    sections 5-6.
    """
    harness = portal_harness()
    use_case = submitter(harness)
    for offset in range(4):
        await use_case.submit(SESSION, content=f"mensaje {offset}", client_ip=CLIENT_IP, now=NOW + timedelta(minutes=offset)
        )
    total = len(harness.messages.rows)

    thread = await reader(harness).read(SESSION, page=None, per_page=2)

    assert thread.page == (total + 1) // 2
    assert thread.total == total
    newest = max(message.created_at for message in harness.messages.rows)
    assert any(item.created_at == newest for item in thread.items)


@pytest.mark.asyncio
async def test_an_explicit_page_still_reaches_the_earlier_ones() -> None:
    """The other half of D9: the default is a default, not a ceiling."""
    harness = portal_harness()
    use_case = submitter(harness)
    for offset in range(4):
        await use_case.submit(SESSION, content=f"mensaje {offset}", client_ip=CLIENT_IP, now=NOW + timedelta(minutes=offset)
        )

    first = await reader(harness).read(SESSION, page=1, per_page=2)

    assert first.page == 1
    oldest = min(message.created_at for message in harness.messages.rows)
    assert first.items[0].created_at == oldest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "escalation_status",
    [
        ConversationEscalationStatus.PENDING_HUMAN,
        ConversationEscalationStatus.HUMAN_HANDLING,
    ],
)
async def test_a_handed_over_conversation_reads_as_awaiting_human(
    escalation_status: ConversationEscalationStatus,
) -> None:
    """R2.3. Both members collapse to one state: that a manager has already taken it over is
    our business, not the guest's."""
    harness = portal_harness(escalation_status=escalation_status)

    thread = await reader(harness).read(SESSION, page=None, per_page=20)

    assert thread.state is PortalThreadState.AWAITING_HUMAN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "escalation_status",
    [ConversationEscalationStatus.NONE, ConversationEscalationStatus.RESOLVED],
)
async def test_a_conversation_nobody_holds_reads_as_automatic(
    escalation_status: ConversationEscalationStatus,
) -> None:
    """`RESOLVED` is not "handed over" — the escalation is finished and the AI answers again."""
    harness = portal_harness(escalation_status=escalation_status)

    thread = await reader(harness).read(SESSION, page=None, per_page=20)

    assert thread.state is PortalThreadState.AUTOMATIC


# --- The sender map (R2.2, R5.5, D4) ------------------------------------------------------


def test_the_sender_map_is_total_over_the_sender_vocabulary() -> None:
    """D4: "un miembro nuevo de `MessageSenderType` rompe el test en vez de caer por defecto en
    `PROPERTY`". This is that test, and it is the reason the map is not a `.get(..., PROPERTY)`."""
    assert set(_SENDER) == set(MessageSenderType)


def test_the_ai_and_a_manager_are_published_identically() -> None:
    """R2.2: the projection may not carry the AI/person distinction in **any** field.

    **Compared over `dataclasses.fields` rather than a hand-written list.** The first version
    named `("sender", "content")`, which had two problems the QA panel of sections 5-6 spelled
    out: a field added later would not enter the comparison on its own, and neither of those
    two is a field that could plausibly diverge — so the test re-asserted what the two lines
    above it already proved. Deriving the set means a fifth field is compared the day it exists.

    `id` is the one exclusion, and it is not a carve-out of convenience: two distinct rows have
    distinct ids by definition, so comparing them would assert something false. `created_at` is
    **not** excluded any more — an earlier docstring here said the comparison held "but for id,
    content and instant", and the instant is precisely the channel by which the distinction
    leaks (see `design.md` §Residuo de R2.2). Both messages are built at the same `NOW` so the
    field genuinely matches; what the residual describes is the *pipeline* writing a reply at
    the guest's instant, which is out of this projection's reach and is recorded rather than
    asserted away.
    """
    import dataclasses

    from app.messaging.application.portal import _project
    from app.messaging.domain.entities import Message

    def message(sender_type: MessageSenderType) -> Message:
        return Message(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            sender_type=sender_type,
            content="Le respondemos enseguida",
            created_at=NOW,
        )

    by_ai = _project(message(MessageSenderType.AI))
    by_manager = _project(message(MessageSenderType.MANAGER))

    compared = {f.name for f in dataclasses.fields(PortalMessage)} - {"id"}
    assert compared, "nothing left to compare: the projection lost its fields"
    differing = {
        name for name in compared if getattr(by_ai, name) != getattr(by_manager, name)
    }

    assert differing == set()
    assert by_ai.sender is PortalMessageSender.PROPERTY


# --- The two use cases satisfy the two ports (R1.4, R2.1, D3) -----------------------------


def test_the_use_cases_satisfy_the_ports_they_implement() -> None:
    """6.5: structural conformance, checked the way `test_portal_wiring.py` checks wiring — by
    the shape rather than by a runtime `isinstance`, since these `Protocol`s are not
    `runtime_checkable` and making them so would be a change to the port for a test's benefit.
    """
    import inspect

    assert inspect.signature(PostPortalGuestMessageUseCase.submit) == inspect.signature(
        GuestPortalMessageSubmitter.submit
    )
    assert inspect.signature(ReadPortalThreadUseCase.read) == inspect.signature(
        GuestPortalThreadReader.read
    )
