"""One tenant never reads or writes another's conversations or messages (R1.2, R1.3, R1.5).

Required of every new module by DoD §28.18 and rule 1 of `sdd/steering/security.md`, and
**load-bearing rather than ceremonial for `messages`**: that table has no `tenant_id` column,
so `tenant_scoped_classes()` does not select it and the global `with_loader_criteria` of
`app/core/db.py` does not cover it. A plain `SELECT ... WHERE conversation_id = :id` would
answer, and would answer for every tenant. The `JOIN` with `conversations` is the only
isolation this table has (R1.2, design D3).

**Every test here runs on the unmarked `db_session`, and that is the point.** On a session
marked with a tenant the global listener filters ORM reads by itself — down to the select of a
single column — so an isolation test would pass against a repository that had forgotten its
`WHERE` entirely, and could never fail. Marking the session would make this file decorative.

R1.3 names four access paths and there is a test for each: listing, detail, insertion and
send. "Send" is the read the outbound path performs — resolving the conversation before
replying — which is `get`, exercised here from the other tenant's side.
"""

import uuid

import pytest

from app.messaging.domain.enums import (
    ConversationEscalationStatus,
    ConversationStatus,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import (
    CONVERSATION_NOT_FOUND_MESSAGE,
    ConversationNotFoundError,
)
from app.messaging.domain.repositories import ConversationFilters
from app.messaging.infrastructure.models import MessageModel
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)
from tests.messaging.conftest import (
    NOW,
    seed_conversation,
    seed_guest,
    seed_message,
    seed_property,
    seed_reservation,
    seed_tenant,
)
from tests.messaging.test_repositories import build_message

ALL = ConversationFilters()


async def two_tenants(db_session):
    """Tenant A with a conversation and a message; tenant B with its own."""
    a = await seed_tenant(db_session, "TenantA")
    b = await seed_tenant(db_session, "TenantB")
    a_property = await seed_property(db_session, a, "REDES11")
    b_property = await seed_property(db_session, b, "PAJARITOS8")
    a_conversation = await seed_conversation(db_session, a, a_property)
    b_conversation = await seed_conversation(db_session, b, b_property)
    await seed_message(db_session, a_conversation, content="Mensaje de A")
    await seed_message(db_session, b_conversation, content="Mensaje de B")
    return a, b, a_conversation, b_conversation


# --- Path 1: listing (R1.3) --------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_conversations_never_shows_another_tenants(db_session) -> None:
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    page = await SqlAlchemyConversationRepository(db_session).list(
        a.id, ALL, page=1, per_page=50
    )

    assert [item.id for item in page.items] == [a_conversation.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_listing_messages_never_shows_another_tenants(db_session) -> None:
    """The `JOIN` is the whole mechanism here: `messages` names no tenant of its own, so a
    query that forgot it would return tenant B's rows for a caller from tenant A."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    page = await SqlAlchemyMessageRepository(db_session).list_for_conversation(
        a.id, b_conversation.id, page=1, per_page=50
    )

    assert page.items == ()
    assert page.total == 0


@pytest.mark.asyncio
async def test_the_guest_message_count_never_crosses_a_tenant(db_session) -> None:
    """The fourth read of the port, and the newest — added in section 6 for
    `ConversationContext.guest_message_count`, which travels to an `AIAdapter`.

    It gets its own case because the count below exercises a *different* method: with only
    that one, dropping the tenant condition from `_scoped` would leave this path untested.
    Raised by the security panel of sections 5-6.
    """
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    count = await SqlAlchemyMessageRepository(db_session).count_guest_messages(
        a.id, b_conversation.id
    )

    assert count == 0


@pytest.mark.asyncio
async def test_the_message_count_never_crosses_a_tenant(db_session) -> None:
    """The third read of the port, and the one that feeds an escalation decision (R5.1): a
    count leaking across tenants would escalate a conversation because of somebody else's
    guest."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)
    await seed_message(
        db_session, b_conversation, intent=MessageIntent.WIFI.value
    )

    count = await SqlAlchemyMessageRepository(
        db_session
    ).count_unresolved_guest_messages_with_intent(
        a.id, b_conversation.id, MessageIntent.WIFI
    )

    assert count == 0


@pytest.mark.asyncio
async def test_the_guests_last_message_time_never_crosses_a_tenant(db_session) -> None:
    """The fifth read of the port (`whatsapp-cloud-adapter` R2.4, D2): tenant A must not learn
    when tenant B's guest last wrote, which would leak into A's own session-window decision.
    A repository that dropped the tenant condition from `_scoped` would answer tenant B's
    guest message instead of `None`."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    result = await SqlAlchemyMessageRepository(db_session).last_guest_message_at(
        a.id, b_conversation.id
    )

    assert result is None


# --- Path 2: detail (R1.3, R1.5) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_reading_another_tenants_conversation_answers_none(db_session) -> None:
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    assert (
        await SqlAlchemyConversationRepository(db_session).get(a.id, b_conversation.id)
        is None
    )


@pytest.mark.asyncio
async def test_an_unknown_id_and_another_tenants_id_are_indistinguishable(
    db_session,
) -> None:
    """R1.5, at the port. Both are the same query returning zero rows (D3), so there is no
    branch that could tell them apart even deliberately — which is a stronger statement than
    "both answer `None`", and is why the test compares the two answers rather than asserting
    each separately."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)
    repository = SqlAlchemyConversationRepository(db_session)

    unknown = await repository.get(a.id, uuid.uuid4())
    foreign = await repository.get(a.id, b_conversation.id)

    assert unknown == foreign is None


# --- Path 3: insertion (R1.3, R1.5) ------------------------------------------------------


@pytest.mark.asyncio
async def test_writing_a_message_into_another_tenants_conversation_is_refused(
    db_session,
) -> None:
    """The write resolves the parent inside the tenant first, so this fails before any row is
    inserted rather than being caught afterwards."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    with pytest.raises(ConversationNotFoundError):
        await SqlAlchemyMessageRepository(db_session).add(
            a.id, build_message(b_conversation.id)
        )


@pytest.mark.asyncio
async def test_the_refused_write_and_an_unknown_parent_raise_the_same_error(
    db_session,
) -> None:
    """R1.5 applies to the write path too: a distinguishable message here would let a caller
    use `POST /messages` to probe whether a conversation id exists in another tenant."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)
    repository = SqlAlchemyMessageRepository(db_session)

    with pytest.raises(ConversationNotFoundError) as unknown:
        await repository.add(a.id, build_message(uuid.uuid4()))
    with pytest.raises(ConversationNotFoundError) as foreign:
        await repository.add(a.id, build_message(b_conversation.id))

    assert str(unknown.value) == str(foreign.value) == CONVERSATION_NOT_FOUND_MESSAGE
    assert type(unknown.value) is type(foreign.value)


@pytest.mark.asyncio
async def test_no_row_is_left_behind_by_a_refused_write(db_session) -> None:
    """The refusal happens before the insert, so tenant B's thread is untouched — a check
    worth making because "raises" and "wrote nothing" are different claims."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    with pytest.raises(ConversationNotFoundError):
        await SqlAlchemyMessageRepository(db_session).add(
            a.id, build_message(b_conversation.id)
        )

    page = await SqlAlchemyMessageRepository(db_session).list_for_conversation(
        b.id, b_conversation.id, page=1, per_page=50
    )
    assert page.total == 1


# --- Path 4: send (R1.3) -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_send_path_cannot_resolve_another_tenants_conversation(
    db_session,
) -> None:
    """"Send" reaches the database exactly once — to resolve the conversation it is about to
    reply on — so this is the read that gates it. A caller from tenant A gets `None` and
    therefore a 404, and never a channel to send on."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    resolved = await SqlAlchemyConversationRepository(db_session).get(
        a.id, b_conversation.id
    )

    assert resolved is None


@pytest.mark.asyncio
async def test_a_reply_cannot_be_written_into_another_tenants_thread(db_session) -> None:
    """The other half of send: persisting the AI's reply goes through the same guarded write."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    with pytest.raises(ConversationNotFoundError):
        await SqlAlchemyMessageRepository(db_session).add(
            a.id,
            build_message(
                b_conversation.id,
                sender_type=MessageSenderType.AI,
                ai_generated=True,
                content="We have received your message and we are reviewing it. "
                "We will reply here as soon as possible.",
            ),
        )


# --- The mechanism itself ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_session_these_tests_run_on_is_not_tenant_marked(db_session) -> None:
    """**The test that makes every test above meaningful.**

    `messages` has no `tenant_id`, so the global listener never covered it — but
    `conversations` does, and on a marked session the listener would filter the reads above by
    itself. Every assertion here would then pass against a repository with no `WHERE` at all,
    and this file would be decorative. The guard is cheap and the failure it prevents is
    silent, which is exactly the combination worth a test.

    Checked by writing a row for tenant B and reading it back **without** naming a tenant: on
    a marked session this returns nothing.
    """
    a, b, a_conversation, b_conversation = await two_tenants(db_session)

    from sqlalchemy import select

    from app.messaging.infrastructure.models import ConversationModel

    rows = await db_session.execute(select(ConversationModel.id))
    visible = set(rows.scalars())

    assert {a_conversation.id, b_conversation.id} <= visible


@pytest.mark.asyncio
async def test_messages_still_has_no_tenant_column(db_session) -> None:
    """The premise of this whole file, pinned so a future migration that adds the column has
    to come past these tests and decide what they now mean."""
    assert "tenant_id" not in MessageModel.__table__.c


@pytest.mark.asyncio
async def test_escalating_never_touches_another_tenants_conversation(db_session) -> None:
    """The write path of `save`, which the four access paths above reach through the API."""
    a, b, a_conversation, b_conversation = await two_tenants(db_session)
    repository = SqlAlchemyConversationRepository(db_session)

    stolen = await repository.get(b.id, b_conversation.id)
    stolen.escalate(now=NOW)

    from app.core.tenancy import CrossTenantWriteError

    with pytest.raises(CrossTenantWriteError):
        await repository.save(a.id, stolen)

    untouched = await repository.get(b.id, b_conversation.id)
    assert untouched.status is ConversationStatus.OPEN
    assert untouched.escalation_status is ConversationEscalationStatus.NONE


# --- The portal thread, both ways (`guest-portal-messaging` R3.4, R3.5, R4.5) -------------
# R4.5 asks for isolation "en **cada** vía nueva: lectura del hilo y envío". Section 3 added
# two, and the section 3-4 security panel found only the read half covered — the write half
# was named by a test that did not exercise it. Both are here now, on the unmarked
# `db_session` for the reason this module's header gives.


async def portal_two_tenants(db_session):
    """Two tenants, each with its own stay, and a portal thread for A only."""
    a = await seed_tenant(db_session, "TenantA")
    b = await seed_tenant(db_session, "TenantB")
    a_property = await seed_property(db_session, a, "REDES11")
    b_property = await seed_property(db_session, b, "PAJARITOS8")
    a_stay = await seed_reservation(db_session, a, a_property)
    b_stay = await seed_reservation(db_session, b, b_property)
    a_thread = await SqlAlchemyConversationRepository(db_session).ensure_portal(
        a.id, reservation_id=a_stay.id, property_id=a_property.id,
        guest_id=None, language="es", now=NOW,
    )
    return a, b, a_stay, b_stay, a_property, b_property, a_thread


@pytest.mark.asyncio
async def test_find_portal_never_returns_another_tenants_thread(db_session) -> None:
    """The read half. B asks for A's stay by id — the only way it could reach A's thread —
    and gets nothing."""
    a, b, a_stay, _, _, _, a_thread = await portal_two_tenants(db_session)

    assert await SqlAlchemyConversationRepository(db_session).find_portal(
        b.id, a_stay.id
    ) is None
    # And A still sees its own, so the filter is on the tenant rather than on everything.
    assert (
        await SqlAlchemyConversationRepository(db_session).find_portal(a.id, a_stay.id)
    ).id == a_thread.id


@pytest.mark.asyncio
async def test_ensure_portal_never_writes_into_another_tenants_thread(db_session) -> None:
    """The write half, which is the one R4.5 names first and the one that was missing.

    B calls `ensure_portal` naming A's stay. Whatever else happens, the one thing that must
    not is B writing into — or taking over — the row that belongs to A: A's thread keeps its
    id, its tenant and its language.
    """
    a, b, a_stay, _, b_property, _, a_thread = await portal_two_tenants(db_session)

    result = await SqlAlchemyConversationRepository(db_session).ensure_portal(
        b.id, reservation_id=a_stay.id, property_id=b_property.id,
        guest_id=None, language="en", now=NOW,
    )

    assert result.id != a_thread.id
    assert result.tenant_id == b.id

    unchanged = await SqlAlchemyConversationRepository(db_session).find_portal(a.id, a_stay.id)
    assert unchanged is not None
    assert unchanged.id == a_thread.id
    assert unchanged.tenant_id == a.id
    assert unchanged.language == "es"


@pytest.mark.asyncio
async def test_ensure_portal_does_not_verify_the_stay_belongs_to_the_tenant(
    db_session,
) -> None:
    """**A characterisation test: this pins a known gap, not a guarantee.**

    `conversations`' foreign keys are global rather than composite with `tenant_id`, so the
    row B just wrote names A's reservation. `ensure_portal` does not check the anchors — its
    docstring states that as a precondition on the caller, and on the portal path it holds
    because every id comes from the `GuestSession` the authoriser resolved. Nothing enforces
    it for any *other* caller, and `CreateConversationUseCase` spends three lookups on exactly
    this hazard.

    It is written down here rather than left in a docstring so the gap is visible in the
    suite. **If someone adds enforcement, this test goes red and should be deleted** — that
    is the intended outcome, not a regression. The structural fix is a composite foreign key
    `(tenant_id, reservation_id) -> reservations(tenant_id, id)`, whose target index
    `uq_reservations_tenant_id_id` already exists for `guest_access_tokens`; it is out of this
    change's declared scope ("ninguna columna nueva… ningún backfill") and is recorded as a
    roadmap candidate. Raised by the security panel of sections 3-4.
    """
    a, b, a_stay, _, b_property, _, _ = await portal_two_tenants(db_session)

    written = await SqlAlchemyConversationRepository(db_session).ensure_portal(
        b.id, reservation_id=a_stay.id, property_id=b_property.id,
        guest_id=None, language="en", now=NOW,
    )

    assert written.tenant_id == b.id
    assert written.reservation_id == a_stay.id  # A's stay: the anchor nobody checked


# --- The WhatsApp thread, both ways (`whatsapp-cloud-adapter` R4.5, D4, rule 1) -----------
# The new write path of this change, on the unmarked `db_session` for the reason this
# module's header gives. Its key is `(tenant_id, guest_id, property_id)`, so the question the
# index itself raises is whether the tenant is really part of it — a partial unique index over
# `(guest_id, property_id)` alone would have collapsed two tenants' threads into one row, and
# the two tests below are what tell those apart.

A_NUMBER = "109876543210987"
B_NUMBER = "555000111222333"


async def whatsapp_two_tenants(db_session):
    """Two tenants, a property and a guest each, and a `WHATSAPP` thread for A only."""
    a = await seed_tenant(db_session, "TenantA")
    b = await seed_tenant(db_session, "TenantB")
    a_property = await seed_property(db_session, a, "REDES11")
    b_property = await seed_property(db_session, b, "PAJARITOS8")
    a_guest = await seed_guest(db_session, a, full_name="Ana A")
    b_guest = await seed_guest(db_session, b, full_name="Bruno B", phone="+34698765432")
    a_thread = await SqlAlchemyConversationRepository(db_session).ensure_whatsapp(
        a.id,
        guest_id=a_guest.id,
        property_id=a_property.id,
        reservation_id=None,
        language="es",
        business_phone_number=A_NUMBER,
        now=NOW,
    )
    return a, b, a_guest, b_guest, a_property, b_property, a_thread


@pytest.mark.asyncio
async def test_ensure_whatsapp_never_writes_into_another_tenants_thread(db_session) -> None:
    """The write half. B calls `ensure_whatsapp` naming **A's** guest and **A's** property —
    the only way it could reach A's thread — and must get a row of its own instead: A's
    thread keeps its id, its tenant, its language and the number it was opened on.

    Were `tenant_id` missing from the unique index, B's INSERT would conflict with A's row and
    B would be handed A's conversation — the leak this test exists to make impossible.
    """
    a, b, a_guest, _, a_property, _, a_thread = await whatsapp_two_tenants(db_session)
    repository = SqlAlchemyConversationRepository(db_session)

    result = await repository.ensure_whatsapp(
        b.id,
        guest_id=a_guest.id,
        property_id=a_property.id,
        reservation_id=None,
        language="en",
        business_phone_number=B_NUMBER,
        now=NOW,
    )

    assert result.id != a_thread.id
    assert result.tenant_id == b.id

    unchanged = await repository.get(a.id, a_thread.id)
    assert unchanged is not None
    assert unchanged.tenant_id == a.id
    assert unchanged.language == "es"
    assert unchanged.business_phone_number == A_NUMBER


@pytest.mark.asyncio
async def test_another_tenant_cannot_read_a_whatsapp_thread(db_session) -> None:
    """The read half, through the one method the inbound path resolves a thread with. Both
    directions asserted, so the filter is on the tenant rather than on everything."""
    a, b, _, _, _, _, a_thread = await whatsapp_two_tenants(db_session)
    repository = SqlAlchemyConversationRepository(db_session)

    assert await repository.get(b.id, a_thread.id) is None
    assert (await repository.get(a.id, a_thread.id)).id == a_thread.id


@pytest.mark.asyncio
async def test_the_second_tenants_thread_is_a_row_of_its_own(db_session) -> None:
    """The same guest id under two tenants yields two rows, not one — the arithmetic behind
    the test above, stated where a future index change would break it."""
    a, b, a_guest, _, a_property, _, _ = await whatsapp_two_tenants(db_session)
    repository = SqlAlchemyConversationRepository(db_session)

    await repository.ensure_whatsapp(
        b.id, guest_id=a_guest.id, property_id=a_property.id, reservation_id=None,
        language="en", business_phone_number=B_NUMBER, now=NOW,
    )

    for tenant in (a, b):
        page = await repository.list(tenant.id, ALL, page=1, per_page=50)
        assert [row.tenant_id for row in page.items] == [tenant.id]
