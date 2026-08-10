"""Per-run names for the throwaway databases the suite creates.

Both `tests/conftest.py` and `tests/test_migrations.py` used a fixed name
(`<db>_test`, `<db>_migrations`), which made two concurrent pytest runs against the
same Postgres destroy each other: the migrations fixture opens with
`DROP DATABASE IF EXISTS`, so the run that started second would drop the database
the first one was mid-test in, and the failure would look like a flaky test rather
than a collision. That is also what stopped a reviewer from verifying a commit while
the suite was running, so it is a real constraint on the CI gate, not just tidiness.

The suffix is the process id: unique among *live* processes, which is exactly the
collision that matters, and it keeps the names short and greppable in `\\l` output.
`PYTEST_DB_SUFFIX` overrides it so a CI job can pin a name it can clean up.

**Under `pytest-xdist` the pid is not enough, and the override makes it worse.** Each
worker is its own process, so the pid would separate them — but CI pins
`PYTEST_DB_SUFFIX: ci`, and then all four workers compute the *same* name and
`test_migrations.py`'s `DROP DATABASE IF EXISTS` deletes the database another worker is
mid-test in. That is precisely the collision this module exists to prevent, reintroduced
by the pin. So the worker id joins the suffix whenever xdist provides one
(`<db>_test_ci_gw0`); with no xdist there is no `PYTEST_XDIST_WORKER` and nothing changes.

A run killed with SIGKILL leaves its database behind. Harmless, but not for the reason it
used to be: the suite no longer rebuilds the schema in every test, so it can no longer
paper over an inherited one. What makes it harmless now is that the run drops the database
and creates it again before the first test (`tests/conftest.py::_the_run_database`), so a
name it reuses carries nothing from the run that died on it. `make db-clean-test` still
exists for the tidy-minded.
"""

import os
import re

# The suffix reaches `DROP DATABASE`/`CREATE DATABASE` as a quoted identifier, and those two
# run over asyncpg's simple query protocol (no bind parameters), which accepts several commands
# separated by `;`. A `"` in the value would therefore close the identifier and let the rest of
# it execute. Whoever sets the variable can already run code, so this is not a privilege boundary
# — it is blast radius: the run now drops its database *before* the first test, so a pasted or
# mistyped value gets to be destructive at startup rather than at teardown.
#
# The class is deliberately the same one `make db-clean-test` sweeps with
# (`datname ~ '_(test|migrations)_[0-9a-z_]+$'`, `Makefile`): a suffix this accepted but
# that pattern did not would create databases the orphan sweeper can never find. The two
# widen together or not at all — `_` is in both because the xdist worker id joins the
# suffix with one.
_SAFE_SUFFIX = re.compile(r"\A[0-9a-z_]+\Z")

# Postgres truncates identifiers at 63 bytes, quotes included. With a long enough `POSTGRES_DB`,
# `<base>_test_<suffix>` truncates back onto `<base>` — the dev database that `make up` manages,
# which the suite must never touch.
_MAX_IDENTIFIER_BYTES = 63


def run_suffix() -> str:
    suffix = os.environ.get("PYTEST_DB_SUFFIX") or str(os.getpid())
    # Set by pytest-xdist in each worker process, and by nobody else: with the suite run
    # serially the variable is absent and the name is what it always was.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        suffix = f"{suffix}_{worker}"
    if not _SAFE_SUFFIX.match(suffix):
        raise ValueError(
            f"the run suffix must match {_SAFE_SUFFIX.pattern}, got {suffix!r} "
            "(from PYTEST_DB_SUFFIX/pid and PYTEST_XDIST_WORKER)"
        )
    return suffix


def scoped_name(base: str, purpose: str) -> str:
    name = f"{base}_{purpose}_{run_suffix()}"
    if len(name.encode()) > _MAX_IDENTIFIER_BYTES:
        raise ValueError(
            f"the throwaway database name {name!r} exceeds Postgres' {_MAX_IDENTIFIER_BYTES}-byte "
            "identifier limit and would be truncated onto another database"
        )
    return name
