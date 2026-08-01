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
