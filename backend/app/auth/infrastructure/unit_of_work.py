"""SQLAlchemy adapter for the UnitOfWork port (design D10).

Thin on purpose: its only reason to exist is keeping `application/` free of
SQLAlchemy, so the use cases can own the transactional boundary without importing
infrastructure.
"""

from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()
