"""Deny by default, enforced structurally (R3.2, R3.3, R3.6, design D9).

Every route that is not on the explicit anonymous allowlist must declare an
authorisation dependency. A new endpoint that forgets makes this fail; getting past
it requires adding the path to the list below, which is a visible diff.
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.auth.api.dependencies import REQUIRED_PERMISSION_ATTR
from app.auth.domain.policy import Permission
from app.main import create_app

# Anonymous on purpose. `/health` is probed by the container healthcheck (design D2);
# login and refresh are the endpoints that mint credentials, so they cannot require
# one; the rest is FastAPI's own generated documentation.
#
# Keyed on (METHOD, path), not on path alone. R3.3 names the exemptions with their verb
# — "POST /api/v1/auth/login" — and a bare-path allowlist exempts every method on that
# path: a `GET /login`, a `DELETE /auth/refresh` "revoke my chain" convenience endpoint
# or a `POST /health` would ship with no authorisation declaration and this module would
# stay green. Same vacuity class as the route-type hole, one axis over.
ANONYMOUS_ENDPOINTS = {
    ("GET", "/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}


def _is_anonymous(path: str, methods: set[str] | None) -> bool:
    """True only when EVERY method on this path is allowlisted.

    HEAD is ignored: FastAPI and starlette add it implicitly alongside GET, so it is
    never a verb somebody chose.
    """
    verbs = {method for method in (methods or {"GET"}) if method != "HEAD"}
    return bool(verbs) and all((verb, path) in ANONYMOUS_ENDPOINTS for verb in verbs)


def _api_routes(app: FastAPI) -> tuple[list[tuple[str, APIRoute]], list[str]]:
    """Flattens the route tree, and reports every bit of surface it cannot inspect.

    Two vacuity traps here, both found by review rather than by design:

    1. This FastAPI version keeps an included router as a single `_IncludedRouter`
       object instead of copying its endpoints into `app.routes`, so walking
       `app.routes` alone inspects ZERO of the auth endpoints and passes.
    2. Keeping only `isinstance(route, APIRoute)` and dropping everything else means a
       `@app.websocket(...)`, an `app.mount(...)` or a plain starlette `Route` adds
       real, unauthenticated surface this check never sees.

    So the rule is: anything that is not an `APIRoute` and not on the anonymous
    allowlist comes back as UNINSPECTABLE, and the caller fails on it. FastAPI's own
    `/docs`, `/redoc` and `/openapi.json` are plain starlette `Route`s, which is exactly
    why the allowlist — not the route class — is what grants the exemption.
    """
    found: list[tuple[str, APIRoute]] = []
    uninspectable: list[str] = []

    def walk(routes, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            path = prefix + str(getattr(route, "path", "?"))
            if inner is not None:
                context = getattr(route, "include_context", None)
                walk(inner.routes, prefix + getattr(context, "prefix", ""))
            elif isinstance(route, APIRoute):
                found.append((path, route))
            elif not _is_anonymous(path, getattr(route, "methods", None)):
                uninspectable.append(f"{type(route).__name__} {path}")

    walk(app.routes, "")
    return found, uninspectable


def _declared_permissions(route: APIRoute) -> set[Permission]:
    """The permissions this route declares through `require(...)`.

    Looks for the tag `require()` puts on the callable it returns, NOT for the
    authentication dependency. Asserting the latter would be a weaker check that
    passes for a route written with the public `AuthenticatedDep` and no permission at
    all — authenticated but unauthorised, which is not what
    `steering/security.md` rule 2 asks for.

    The walk starts at the route's DEPENDENCIES, not at `route.dependant` itself, whose
    `.call` is the endpoint function: otherwise tagging the endpoint would satisfy the
    check with no `require()` anywhere in the graph.
    """
    found: set[Permission] = set()

    def walk(dependant) -> None:
        permission = getattr(dependant.call, REQUIRED_PERMISSION_ATTR, None)
        if permission is not None:
            found.add(permission)
        for sub in dependant.dependencies:
            walk(sub)

    for sub in route.dependant.dependencies:
        walk(sub)
    return found


def _declares_authorisation(route: APIRoute) -> bool:
    return bool(_declared_permissions(route))


def test_the_flattener_finds_the_auth_endpoints() -> None:
    # Without this the whole module could pass by inspecting nothing.
    routes, _ = _api_routes(create_app())
    paths = {path for path, _ in routes}

    assert {"/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout"} <= paths


def test_every_route_outside_the_allowlist_declares_authorisation() -> None:
    routes, unknown = _api_routes(create_app())
    undeclared = [
        path
        for path, route in routes
        if not _is_anonymous(path, route.methods) and not _declares_authorisation(route)
    ]
    assert not unknown, f"route types this check cannot inspect: {unknown}"

    assert not undeclared, (
        f"these routes declare no authorisation: {sorted(undeclared)}. "
        "Add the dependency, or add (METHOD, path) to ANONYMOUS_ENDPOINTS if it is "
        "meant to be public."
    )


def test_the_check_catches_a_new_verb_on_an_anonymous_path() -> None:
    """A bare-path allowlist would exempt this; R3.3 names the verb, so the check must too."""
    app = create_app()

    @app.get("/api/v1/auth/login")
    async def login_by_get() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/health")
    async def health_by_post() -> dict[str, bool]:
        return {"ok": True}

    routes, _ = _api_routes(app)
    undeclared = sorted(
        path
        for path, route in routes
        if not _is_anonymous(path, route.methods) and not _declares_authorisation(route)
    )

    assert undeclared == ["/api/v1/auth/login", "/health"]


def test_the_check_catches_an_endpoint_that_forgets() -> None:
    """The mechanism gets its own test, so it cannot pass vacuously (design D9)."""
    app = create_app()

    @app.get("/forgot-its-authorisation")
    async def forgotten() -> dict[str, bool]:
        return {"ok": True}

    routes, _ = _api_routes(app)
    undeclared = [
        path
        for path, route in routes
        if not _is_anonymous(path, route.methods) and not _declares_authorisation(route)
    ]

    assert undeclared == ["/forgot-its-authorisation"]


def test_the_check_catches_an_endpoint_that_authenticates_but_declares_no_permission() -> None:
    """The subtler escape, and the reason the check looks for the permission tag.

    `AuthenticatedDep` is a public export. An endpoint that uses it is authenticated
    but consults no permission — `steering/security.md` rule 2 requires the second
    thing too, so this must be caught, not waved through.
    """
    from app.auth.api.dependencies import AuthenticatedDep

    app = create_app()

    @app.get("/authenticated-but-unauthorised")
    async def sneaky(authenticated: AuthenticatedDep) -> dict[str, bool]:
        return {"ok": True}

    routes, _ = _api_routes(app)
    undeclared = [
        path
        for path, route in routes
        if not _is_anonymous(path, route.methods) and not _declares_authorisation(route)
    ]

    assert undeclared == ["/authenticated-but-unauthorised"]


def test_the_check_catches_surface_it_cannot_inspect() -> None:
    """A websocket and a mount bypass the dependency machinery entirely.

    They can never satisfy a permission check, so silently skipping them — which an
    `isinstance(route, APIRoute)` filter does — would let real unauthenticated surface
    ship green. That is the same vacuous-pass class as trap 1, one layer down.
    """
    from starlette.applications import Starlette

    app = create_app()

    @app.websocket("/ws")
    async def socket(websocket) -> None:  # pragma: no cover - never connected to
        await websocket.accept()

    app.mount("/static", Starlette())

    _, uninspectable = _api_routes(app)

    assert sorted(uninspectable) == ["APIWebSocketRoute /ws", "Mount /static"]


def test_the_real_app_has_no_uninspectable_surface() -> None:
    _, uninspectable = _api_routes(create_app())

    assert uninspectable == []


def test_the_docs_routes_are_exempt_by_allowlist_not_by_class() -> None:
    # They are plain starlette `Route`s, so a class-based exemption would also wave
    # through a hand-added Route. The allowlist is what grants it.
    routes, uninspectable = _api_routes(create_app())

    assert uninspectable == []
    assert "/openapi.json" not in {path for path, _ in routes}


def test_every_declared_permission_is_in_the_catalogue() -> None:
    # A tag carrying something that is not a Permission would make the walk pass while
    # `is_allowed` could never grant it.
    routes, _ = _api_routes(create_app())
    for path, route in routes:
        for permission in _declared_permissions(route):
            assert isinstance(permission, Permission), f"{path} declares {permission!r}"


def test_the_allowlist_only_names_endpoints_that_exist() -> None:
    # Stops a stale entry from quietly exempting a path that got renamed.
    routes, _ = _api_routes(create_app())
    real = {
        (method, path)
        for path, route in routes
        for method in route.methods
        if method != "HEAD"
    } | {
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
    }

    assert ANONYMOUS_ENDPOINTS <= real


def test_the_protected_endpoints_are_the_ones_expected() -> None:
    """A snapshot, on purpose: every new protected path has to show up in this diff.

    Grown by `reservations` with its five endpoints (two paths, five methods) — the
    per-method permissions are asserted in `tests/reservations/test_authorization.py`.
    """
    routes, _ = _api_routes(create_app())
    protected = {path for path, route in routes if _declares_authorisation(route)}

    assert protected == {
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/reservations",
        "/api/v1/reservations/{reservation_id}",
        "/api/v1/integrations/pms/import-csv",
    }
