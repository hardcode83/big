"""Application code must never remove a session's tenant marker.

`session.info` is per-session, not per-statement, so clearing the marker mid-request
switches the global filter off for EVERY scoped table for the rest of that session —
`guests.document_number` included. `bind_session_to_tenant` has no symmetric unbind
precisely because there is no legitimate reason to call one.

The prose lives in limit 2 of `_scope_statement_to_tenant` (app/core/db.py). This file
is its executable half, added by `domain-foundation-financial`: that change makes
`webhook_events` the first table whose legitimate read path needs the filter OFF (its
`tenant_id IS NULL` rows), and the only worked example of unmarking in the repo is a
green test — which makes it the discoverable idiom for the next implementer. The
correct shape is a session that was NEVER marked, from `async_session_factory`, the
way `app/cli/bootstrap.py` does it.

Static analysis in its own module rather than inside `test_tenant_filter.py`, whose
tests are all async integration tests against real Postgres. This is the shape and the
neighbourhood of `test_layering.py`, which enforces the dependency rule the same way,
meta-test included.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# `app/core/db.py` owns the marker: it defines the key, sets it and reads it.
# Anchored to the relative path, not the file name — several modules could be db.py.
MARKER_OWNER = Path("core/db.py")

SESSION_STATE_ATTR = "info"


def _app_modules() -> list[Path]:
    return sorted(path for path in APP_ROOT.glob("**/*.py") if path.relative_to(APP_ROOT) != MARKER_OWNER)


def _session_state_accesses(tree: ast.Module) -> list[ast.Attribute]:
    """Every `<expr>.info` that is NOT a call to a method named `info`.

    Matching the ACCESS rather than enumerating mutations is what closes the hole the
    first version had: `pop` and `del` were listed, so `clear()`, `update(...)`,
    `setdefault(...)`, `info[key] = None` and `d = session.info; d.pop(...)` all sailed
    through — and `= None` disables the net exactly like removal does, because
    `_scope_statement_to_tenant` returns early when the value `is None`.

    Excluding the call case keeps `logger.info("...")` legal, which is the only other
    thing named `info` in this codebase.
    """
    called_attributes = {
        node.func for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == SESSION_STATE_ATTR
        and node not in called_attributes
    ]


@pytest.mark.parametrize("module_path", _app_modules(), ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_application_code_never_touches_session_state(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    offenders = _session_state_accesses(tree)

    assert not offenders, (
        f"{module_path.relative_to(APP_ROOT)} reaches into `session.info` "
        f"(line {offenders[0].lineno}). Only app/core/db.py may: the marker is "
        "per-session, so touching it disables tenant scoping for every table for the "
        "rest of that session. Read unmarked data from a session that was never "
        "marked instead — see limit 2 in app/core/db.py."
    )


def test_there_are_app_modules_to_check() -> None:
    # Guards against the whole file passing because the glob matched nothing.
    assert len(_app_modules()) > 50


def test_the_checks_actually_catch_the_escapes_they_claim_to() -> None:
    """The enforcement mechanism gets its own test, like test_layering.py's.

    Every line here is an escape the FIRST version of this scan let through; they are
    pinned so a future simplification cannot silently reopen them.
    """
    escapes = (
        'session.info.pop("tenant_id")',
        "session.info.clear()",
        'session.info["tenant_id"] = None',
        'session.info.update({"tenant_id": None})',
        'session.info.setdefault("tenant_id", None)',
        'del session.info["tenant_id"]',
        'd = session.info\nd.pop("tenant_id")',
        "from app.core.db import TENANT_ID_SESSION_KEY as K\nsession.info[K] = None",
    )
    for source in escapes:
        assert _session_state_accesses(ast.parse(source)), source

    # The one thing named `info` that must stay legal.
    assert not _session_state_accesses(ast.parse('logger.info("started")'))
    assert not _session_state_accesses(ast.parse('self._log.info("x", extra={"a": 1})'))

    # No separate rule is needed for the key itself, by name or by literal: reaching
    # the marker at all means going through `.info`, and that is what is matched.
    # A rule on the literal `"tenant_id"` would be unusable anyway — it is the column
    # name in every index and foreign key in the schema.
    assert _session_state_accesses(ast.parse('session.info["tenant_id"] = None'))
    assert not _session_state_accesses(ast.parse('Index("ix_x_tenant_id", "tenant_id")'))
