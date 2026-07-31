"""The transactional boundary, shared by the modules that came after `auth` (design D3).

`auth` has its own copy of this pair (`app/auth/infrastructure/unit_of_work.py`) and
keeps it: refactoring an archived module is not this change's job. The duplication is
eight lines and is recorded as debt in `sdd/changes/reservations/design.md` D3 — the
next change that touches `auth` consolidates them.

The Protocol lives here rather than in a `domain/` package because it has no owner
domain: reservations, integrations and everything after them commit through the same
boundary.
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
