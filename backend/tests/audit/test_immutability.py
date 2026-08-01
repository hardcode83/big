"""`audit_logs` is append-only, and nothing exposes a way to change that (R6.6).

Two independent checks, because either alone would pass in a system that broke the rule:
the port offers no mutation beyond `add`, and no HTTP route addresses the audit trail at
all. A future change that adds a read endpoint must keep both true.
"""

import inspect

from app.audit.domain.repositories import AuditLogRepository
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.main import create_app

MUTATING_METHODS = {"save", "update", "delete", "remove", "purge", "edit", "set"}


def _public_methods(cls) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=callable)
        if not name.startswith("_")
    }


def test_the_port_offers_no_way_to_change_an_entry() -> None:
    assert _public_methods(AuditLogRepository) == {"add"}


def test_the_adapter_offers_no_way_to_change_an_entry() -> None:
    """Checked separately: a port can stay clean while its adapter grows a `delete`."""
    assert _public_methods(SqlAlchemyAuditLogRepository) == {"add"}
    assert not MUTATING_METHODS & _public_methods(SqlAlchemyAuditLogRepository)


def _served_paths(app=None) -> set[str]:
    """Every path the app actually SERVES, documented or not.

    Two sources unioned, because each one alone is a false green — both discovered by the
    security panel of section 1:

    * `[route.path for route in app.routes]` misses the endpoints entirely: with FastAPI
      >= 0.139 `include_router` stores an `_IncludedRouter` that has **no `.path`**, so a
      `getattr(route, "path", "")` walk only ever sees the four framework routes
      (`/health`, `/docs`, `/openapi.json`, `/docs/oauth2-redirect`). Hence the recursion
      into `original_router`.
    * `openapi()["paths"]` misses anything registered with `include_in_schema=False`,
      which is served all the same — the usual pattern for internal or debug endpoints,
      and exactly how an audit endpoint would plausibly arrive.
    """
    app = app or create_app()
    return _walk(app.routes) | set(app.openapi()["paths"])


def _walk(routes) -> set[str]:
    found: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            found.add(path)
        nested = getattr(route, "original_router", None)
        if nested is not None:
            found |= _walk(nested.routes)
    return found


def test_the_path_walk_sees_the_real_endpoints() -> None:
    """Guard for the guard: prove the walk is not inspecting an empty list."""
    paths = _served_paths()

    assert "/api/v1/auth/login" in paths
    assert "/api/v1/reservations" in paths
    assert len(paths) > 4


def test_the_path_walk_sees_an_undocumented_route() -> None:
    """The second half of the guard: a route hidden from the schema is still found.

    Nothing in the repo uses `include_in_schema=False` today, so without this test the
    blind spot would be invisible until somebody did.
    """
    app = create_app()

    @app.get("/api/v1/audit-logs", include_in_schema=False)
    async def _hidden() -> dict[str, str]:  # pragma: no cover — never called
        return {}

    assert "/api/v1/audit-logs" not in set(app.openapi()["paths"])
    assert "/api/v1/audit-logs" in _served_paths(app)


def test_no_route_addresses_the_audit_trail() -> None:
    """Nothing reaches `audit_logs` over HTTP — not even to read it, today."""
    assert [path for path in sorted(_served_paths()) if "audit" in path.lower()] == []
