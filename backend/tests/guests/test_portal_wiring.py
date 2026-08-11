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
    get_stay_info_use_case,
    get_submit_guest_checkin_use_case,
)


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
