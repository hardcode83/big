"""What `portal_dependencies.py` builds — the layer where section 6's worst defect lived.

**This file exists because the defect was found by reading and not by running.** The wiring
gave the composed `SetGuestDocumentUseCase` a real `SqlAlchemyUnitOfWork`, so the check-in
committed twice: the encrypted document, its audit row and the `Guest` that OQ3 creates
landed before the milestone was written, and a failure in between lost the milestone for ever
because the retry no longer transitions. Four of the five reviewers of that section found it
independently. The tenancy panel then measured what the tests would have said: putting the
old wiring back leaves `tests/guests` at 269 passed, because every use-case test composes the
object by hand and none of them looks at this module.

So the assertions here are about **construction**, not behaviour, and they reach into private
attributes on purpose. There is no public way to ask a use case which unit of work it holds,
and the alternative — asserting behaviour through an HTTP call — is what already failed to
notice: both wirings leave identical rows when nothing goes wrong.

The second half is the standing warning the tenancy panel has repeated since section 3: every
repository on a portal request must share **one** `AsyncSession`, because the authoriser marks
that instance and the global tenant filter only covers what runs on it. A dependency that
built its own would be unmarked in production and invisible in tests, where the override hands
the same object to everybody. Asserting identity catches that; counting sessions does not.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.api.portal_dependencies import (
    get_checkin_status_use_case,
    get_guest_portal_authenticator,
    get_post_portal_guest_message_use_case,
    get_read_portal_thread_use_case,
    get_stay_info_use_case,
    get_submit_guest_checkin_use_case,
)
from app.messaging.api.dependencies import get_process_inbound_message_use_case
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase


@pytest_asyncio.fixture
async def session(test_engine):
    async with AsyncSession(test_engine) as session:
        yield session


def test_the_composed_document_writer_does_not_own_the_transaction(session) -> None:
    """D10 and task 6.5: "un solo `UnitOfWork`, un solo `commit()` al final".

    `SetGuestDocumentUseCase.execute` ends with an unconditional `commit()`, so the only
    thing standing between this change and two transactions is which unit of work it is
    handed here. That makes this line the invariant, and this test the guard the tenancy
    panel of section 6 asked for after showing the suite green with the broken wiring.
    """
    use_case = get_submit_guest_checkin_use_case(session)

    assert isinstance(use_case._documents._uow, CallerOwnedUnitOfWork)
    assert isinstance(use_case._uow, SqlAlchemyUnitOfWork)


def test_the_operator_route_still_owns_its_own_transaction(session) -> None:
    """The other side of the same coin: `CallerOwnedUnitOfWork` belongs to the composition,
    not to the writer. `PATCH /guests/{id}/document` is not composed inside anything, so it
    keeps the real one — and this is what would fail if somebody "simplified" by giving the
    class a no-op default."""
    from app.guests.api.dependencies import get_set_guest_document_use_case

    assert isinstance(get_set_guest_document_use_case(session)._uow, SqlAlchemyUnitOfWork)


def test_every_repository_of_a_portal_request_shares_one_session(session) -> None:
    """The tenancy panel's standing warning for section 6, as an assertion at last.

    The authoriser calls `bind_session_to_tenant` on the session FastAPI cached for the
    request; a repository built on a different one would run with the global filter off for
    the whole request, and no test would see it — the override in the API tests returns the
    same object to every caller, so a second dependency collapses to one there and is two in
    production.
    """
    submit = get_submit_guest_checkin_use_case(session)
    sessions = {
        id(get_guest_portal_authenticator(session)._tokens._session),
        id(get_guest_portal_authenticator(session)._stays._session),
        id(get_guest_portal_authenticator(session)._binder._session),
        id(get_stay_info_use_case(session)._stays._session),
        id(get_checkin_status_use_case(session)._guests._session),
        id(get_checkin_status_use_case(session)._stays._session),
        id(submit._guests._session),
        id(submit._stays._session),
        id(submit._legal._session),
        id(submit._timeline._session),
        # Reaching two levels down on purpose: the composed writer has its own repositories,
        # and they are the ones furthest from the `bind` and easiest to rebuild by accident.
        id(submit._documents._guests._session),
        id(submit._documents._stays._session),
        # One more hop: `SetGuestDocumentUseCase` wraps the audit repository in a
        # `GuestAuditWriter`, so the session lives under the writer rather than on it.
        id(submit._documents._audit._audit._session),
    }

    assert sessions == {id(session)}


def test_the_submitter_is_handed_the_pipeline_and_does_not_rebuild_it(session) -> None:
    """R1.4 and D5 at the wiring layer: "entero y sin duplicarlo".

    `get_process_inbound_message_use_case` composes eleven collaborators. A copy of that graph
    assembled here would be a second place to forget one, and the forgetting would show up as a
    step of the pipeline silently not running for portal messages only — with no test noticing,
    because the use-case tests build the object by hand. So what is pinned is that the
    submitter holds that class and that the factory is what produced it.
    """
    pipeline = get_process_inbound_message_use_case(session)
    use_case = get_post_portal_guest_message_use_case(session, pipeline)

    assert isinstance(use_case._pipeline, ProcessInboundGuestMessageUseCase)
    assert use_case._pipeline is pipeline


def test_every_repository_of_the_two_message_routes_shares_one_session(session) -> None:
    """The tenancy panel's standing warning, extended to the two routes of section 7.

    Same reasoning as its sibling above, and the same reason it cannot be caught by an HTTP
    test: the override hands every caller the same object, so a dependency that builds its own
    session collapses to one in the suite and is two in production — where the second is
    unmarked and the global tenant filter does not cover it.

    **Every session-bound collaborator of the pipeline, not the two the portal touches
    directly.** The first version of this test asserted identity for `_conversations` and
    `_messages` only, and the tenancy panel of sections 5-7 measured what that leaves open: a
    later edit giving `incident_reporting_port` or the timeline repository a session of its own
    would pass this test, pass the whole HTTP suite, and be tenant-unscoped in production. So the
    set below is built from **all eleven** constructor arguments of
    `ProcessInboundGuestMessageUseCase`, minus the two that hold no session — `ai`
    (`MockAIAdapter`) and `channels` (the outbound registry) — and reaching into the incident
    port's own three repositories, which are the ones furthest from the `bind` and the easiest to
    rebuild by accident. That is the multi-hop shape its sibling above already uses.
    """
    pipeline = get_process_inbound_message_use_case(session)
    submit = get_post_portal_guest_message_use_case(session, pipeline)
    read = get_read_portal_thread_use_case(session)

    assert {
        # What the portal itself builds.
        id(submit._conversations._session),
        id(read._conversations._session),
        id(read._messages._session),
        # The pipeline's own nine session-bound collaborators, plus its unit of work.
        id(submit._pipeline._conversations._session),
        id(submit._pipeline._messages._session),
        id(submit._pipeline._timeline._session),
        id(submit._pipeline._notifications._session),
        id(submit._pipeline._users._session),
        id(submit._pipeline._guests._session),
        id(submit._pipeline._configs._session),
        id(submit._pipeline._properties._session),
        id(submit._pipeline._reservations._session),
        id(submit._pipeline._uow._session),
        # One hop further: `incident_reporting_port` composes a use case of `maintenance` with
        # three repositories of its own. Its unit of work is `CallerOwnedUnitOfWork`, which holds
        # no session by design, so it is absent here rather than forgotten.
        id(submit._pipeline._incidents._incidents._session),
        id(submit._pipeline._incidents._audit._session),
        id(submit._pipeline._incidents._timeline._session),
    } == {id(session)}


def test_the_pipeline_has_no_session_bound_collaborator_this_guard_forgets(session) -> None:
    """The guard above is a hand-written list, so this is what stops it going stale.

    A collaborator added to `ProcessInboundGuestMessageUseCase` later would not appear in that
    set, and its absence would look exactly like a pass. So instead of trusting the list, this
    walks the use case's own attributes and asserts that **every** one holding a `_session` is a
    session the request owns — which needs no maintenance when the constructor grows.

    Kept beside the explicit list rather than replacing it: the list is what names the
    collaborators a reader can check against the wiring, and this is what fails when somebody
    adds a twelfth.
    """
    pipeline = get_process_inbound_message_use_case(session)

    found = {
        name: value
        for name, value in vars(pipeline).items()
        if getattr(value, "_session", None) is not None
    }

    assert len(found) >= 10, f"the walk must reach the collaborators, found only {sorted(found)}"
    for name, collaborator in found.items():
        assert collaborator._session is session, (
            f"{name} was built on a different AsyncSession; in production the tenant marker "
            "the authoriser set would not cover it"
        )
