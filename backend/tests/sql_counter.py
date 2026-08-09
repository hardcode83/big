"""Counting the statements a piece of code emits (`dashboard-api` R1.7).

R1.7 says the dashboard collection "SHALL resolver la colección completa **sin una consulta
por propiedad** (sin N+1), y un test SHALL demostrarlo contando las consultas emitidas". The
design says why an assertion and not a metric: *"Un `for` en el caso de uso que llame a un
`get` por propiedad es sintácticamente idéntico al código correcto"* — nothing about the
shape of the wrong code looks wrong, so the count is the only thing that can tell them apart.

Shared rather than local to one test file because two tests need it — the timeline batch
reader (task 4.4) and the dashboard collection (task 6.4) — and two copies of a counting
harness drift into disagreeing about what counts as a statement.
"""

from contextlib import contextmanager

from sqlalchemy import event


class StatementLog:
    """The SQL emitted inside the block, in order.

    Deliberately NOT a `list` subclass: `list.count` already means "how many times does this
    value appear", so a `count` property would have shadowed it and made
    `log.count("SELECT")` a `TypeError` for anyone who reached for the obvious thing.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __len__(self) -> int:
        return len(self.statements)

    def __iter__(self):
        return iter(self.statements)

    def matching(self, fragment: str) -> list[str]:
        """The statements containing `fragment`, case-insensitively.

        Useful to separate the query under test from the fixture writes that a test's own
        setup may still be flushing.
        """
        needle = fragment.lower()
        return [statement for statement in self.statements if needle in statement.lower()]


@contextmanager
def count_statements(engine):
    """Record every statement the (async) `engine` executes inside the block.

    Listens on `before_cursor_execute` of the underlying **sync** engine, which is the layer
    the async engine drives — an `executemany` still arrives here once per cursor execution,
    so a batched insert does not read as N statements.

    Takes the engine rather than the session on purpose: a session can be rebound, and what
    R1.7 is really asserting is what reached the database.
    """
    log = StatementLog()
    sync_engine = getattr(engine, "sync_engine", engine)

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany):
        log.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        yield log
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)
