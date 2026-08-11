"""The transactional boundary of the whole application (reservations design D3).

`auth` used to carry an identical eight-line copy at
`app/auth/infrastructure/unit_of_work.py`, recorded as debt for "the next change that
touches `auth`". `user-management` was that change and deleted it (its design D16), so
this is now the only `SqlAlchemyUnitOfWork` in the codebase.

The `UnitOfWork` **Protocol** still exists twice on purpose, and that is not the same
duplication: `app/auth/domain/ports.py` declares its own so `auth/application/` imports
its ports from its own `domain/`, which is the purest arrangement of the dependency rule.
Unifying them would make that layer import this module, and this module imports
`sqlalchemy`.

The Protocol here lives outside any `domain/` package because it has no owner domain:
reservations, integrations and everything after them commit through the same boundary.
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork(Protocol):
    async def commit(self) -> None:
        """Commit the business operation.

        Declared as a port so `application/` never imports SQLAlchemy: one use case is
        one transaction, and the use case is what decides it is complete.
        """
        ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


class CallerOwnedUnitOfWork:
    """A boundary for a use case that another use case composes: `commit()` does nothing.

    One use case is one transaction — until one of them is reused *inside* another, and then
    exactly one of the two may end it. Handing the inner one this instead of
    `SqlAlchemyUnitOfWork` is how the outer one says "the boundary is mine", in the wiring,
    where both are visible side by side.

    It exists because `guest-portal-api` needed it and got it wrong first. `POST
    /guest/checkin` composes `SetGuestDocumentUseCase` (the codebase's single writer of
    `guests.document_number_encrypted`) inside `SubmitGuestCheckinUseCase`, and the first
    wiring gave both a real unit of work on the same session. The inner `commit()` therefore
    landed the encrypted document, its `AuditLog`, the `Guest` that OQ3 had just created and
    the new `legal_registration_status` **before** the outer one wrote the
    `GUEST_CHECKIN_COMPLETED` milestone — so a failure in between left the check-in done, the
    milestone lost for ever (the retry sees no status transition and writes nothing), and a
    `500` for the guest. Four of the five reviewers of that section found it independently,
    each pointing at a docstring that claimed "one transaction with one commit".

    Nothing about it is guest-specific: any composition of two use cases over one session has
    the same question to answer, which is why it lives here beside the real one.
    """

    async def commit(self) -> None:
        """Deliberately empty. The composing use case commits, once, at the end."""
