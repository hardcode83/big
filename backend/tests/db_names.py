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

A run killed with SIGKILL leaves its database behind. Harmless — a later run reusing
that pid creates-if-missing and drops every table per test anyway — but
`make db-clean-test` exists for the tidy-minded.
"""

import os


def run_suffix() -> str:
    return os.environ.get("PYTEST_DB_SUFFIX") or str(os.getpid())


def scoped_name(base: str, purpose: str) -> str:
    return f"{base}_{purpose}_{run_suffix()}"
