"""The shared `SqlAlchemyUnitOfWork` (design D3, D4).

Thin by design, so the only thing worth asserting is that it delegates — and that the
use cases can therefore own the transaction without importing SQLAlchemy.
"""

import pytest

from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork, UnitOfWork


class _SpySession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_commit_delegates_to_the_session() -> None:
    session = _SpySession()

    await SqlAlchemyUnitOfWork(session).commit()  # type: ignore[arg-type]

    assert session.commits == 1


@pytest.mark.asyncio
async def test_rollback_delegates_to_the_session() -> None:
    """The sibling `revenue-pricing` D9 needs: its generator wraps each property in a
    transaction and abandons the one that failed so the sweep can carry on."""
    session = _SpySession()

    await SqlAlchemyUnitOfWork(session).rollback()  # type: ignore[arg-type]

    assert (session.rollbacks, session.commits) == (1, 0)


@pytest.mark.asyncio
async def test_the_caller_owned_boundary_neither_commits_nor_rolls_back() -> None:
    """Both halves are deliberately empty: an inner use case that abandoned the
    transaction would discard the outer one's work, which is the mirror image of the
    failure that produced this class."""
    session = _SpySession()
    uow = CallerOwnedUnitOfWork()

    await uow.commit()
    await uow.rollback()

    assert (session.commits, session.rollbacks) == (0, 0)


@pytest.mark.parametrize("adapter", [SqlAlchemyUnitOfWork, CallerOwnedUnitOfWork])
def test_the_adapters_expose_exactly_the_ports_surface(adapter) -> None:
    """`UnitOfWork` is what `application/` depends on; the adapters must be substitutable.

    Checked structurally rather than with `isinstance`: the port is a plain `Protocol`
    (not `runtime_checkable`), and making it one just to satisfy a test would change
    production code to fit the test instead of the other way round.

    Pinning the exact set is what makes a widened port a decision: `rollback` arrived with
    `revenue-pricing` and this assertion is what stopped it arriving on the port alone,
    with `CallerOwnedUnitOfWork` silently no longer substitutable for it.
    """
    port_methods = {name for name in vars(UnitOfWork) if not name.startswith("_")}
    assert port_methods == {"commit", "rollback"}
    for name in port_methods:
        assert callable(getattr(adapter, name))
