"""The shared `SqlAlchemyUnitOfWork` (design D3, D4).

Thin by design, so the only thing worth asserting is that it delegates — and that the
use cases can therefore own the transaction without importing SQLAlchemy.
"""

import pytest

from app.core.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork


class _SpySession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_commit_delegates_to_the_session() -> None:
    session = _SpySession()

    await SqlAlchemyUnitOfWork(session).commit()  # type: ignore[arg-type]

    assert session.commits == 1


def test_the_adapter_exposes_exactly_the_ports_surface() -> None:
    """`UnitOfWork` is what `application/` depends on; the adapter must be substitutable.

    Checked structurally rather than with `isinstance`: the port is a plain `Protocol`
    (not `runtime_checkable`), and making it one just to satisfy a test would change
    production code to fit the test instead of the other way round.
    """
    port_methods = {name for name in vars(UnitOfWork) if not name.startswith("_")}
    assert port_methods == {"commit"}
    for name in port_methods:
        assert callable(getattr(SqlAlchemyUnitOfWork, name))
