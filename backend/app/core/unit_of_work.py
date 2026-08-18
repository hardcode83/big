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

    async def rollback(self) -> None:
        """Abandon the work done since the last commit.

        The sibling of `commit()`, and it arrives with `revenue-pricing` D9, whose
        generator puts a transaction around **each property** and keeps going when one
        fails: without this the failing property's partial rows would ride along into the
        next property's commit, and a database-level failure would leave the session
        unusable for the rest of the sweep.

        It is on the port rather than reached for through the session because a use case
        that may end a transaction is the one that may also abandon it — and
        `application/` never imports SQLAlchemy.
        """
        ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


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

    async def rollback(self) -> None:
        """Deliberately empty, for the same reason `commit()` is.

        An inner use case that abandoned the transaction would discard the outer one's
        work too — the mirror image of the failure that produced this class.

        **What that costs, said plainly rather than discovered later**: a use case whose
        correctness depends on abandoning its own failed unit cannot be composed under this
        boundary. `revenue-pricing`'s generator is exactly that — its `rollback()` on a
        failed property is what keeps the partial horizon out of the next property's commit
        — so composed here its "abandon and carry on" would silently become "keep and carry
        on", reporting `failed` while committing the rows that failed.

        That sentence used to be the *only* barrier, while the one machine-checked surface
        (`tests/test_unit_of_work.py`) asserted the two adapters substitutable — so a future
        composer would type-check, pass the suite and corrupt a horizon. The QA panel of
        `/sdd:review` reproduced it (`created=0, failed=2`, then
        `InFailedSQLTransactionError`), so `GeneratePriceRecommendationsUseCase.__init__`
        now refuses this class outright. The prose stays because it is the *reason*; the
        constructor check is what makes it hold.
        """
