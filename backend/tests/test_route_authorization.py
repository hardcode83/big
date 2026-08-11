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
from tests.route_walk import flatten_routes

# Anonymous on purpose. `/health` is probed by the container healthcheck (design D2);
# login and refresh are the endpoints that mint credentials, so they cannot require
# one; the rest is FastAPI's own generated documentation.
#
# `GET /api/v1/cleaning-photos/{photo_id}` is the fourth kind and the only one that serves
# tenant data (`cleaning-photos-storage`, design D7). It cannot require a token because a
# browser fetching an `<img src>` sends no `Authorization` header, so a signed URL gated on
# one would work for nothing. **Its authorisation is the HMAC in its query string**, verified
# by `ServeLocalCleaningPhotoUseCase` against the object key read from the database — a key
# that begins with `tenants/{tenant_id}/`, so a valid signature proves the caller was handed a
# URL minted for that photo of that tenant. Refusals answer one constant `403` body for
# "wrong", "expired", "tampered" and "no such photo" alike, so the exemption does not hand an
# unauthenticated caller an existence oracle. Pinned in `tests/cleaning/test_serve_photo_api.py`
# and `tests/cleaning/test_serve_photo_use_case.py`; the entry below is the visible diff this
# allowlist exists to force.
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
    ("GET", "/api/v1/cleaning-photos/{photo_id}"),
    # `reservations-webhooks`: anonymous because the route token IS the credential (rule 12(b) of
    # `steering/security.md`), paired with the provider's static per-tenant header (12(a)). A
    # provider cannot hold a JWT, and ADR 0006 measured that none of the eleven evaluated
    # providers signs its webhooks — so there is nothing else to authenticate with.
    #
    # It is exempt from declaring a permission, NOT from authenticating: the check moved into the
    # use case, where `tests/integrations/test_webhook_receipt.py` asserts that an unknown token,
    # an unknown provider, a missing header and a wrong one are indistinguishable.
    ("POST", "/api/v1/webhooks/{provider}/{webhook_token}"),
    # `guest-portal-api`: the guest portal of PRD §23. Anonymous for the same structural
    # reason as the webhook receiver above — the token in the path IS the credential — with
    # one difference that makes them stricter rather than looser: a webhook endpoint has a
    # second factor in its static header (rule 12(a)), and these have none.
    #
    # Exempt from declaring a permission, NOT from authorising. The check is
    # `GuestPortalAuthenticator` (design D4), and `tests/guests/test_portal_authenticator.py`
    # asserts that a token which does not exist, is malformed, has been revoked, is past its
    # window, or belongs to a cancelled stay are all indistinguishable.
    #
    # Four entries, over three paths: `/checkin/{token}` answers both `GET` (what is still
    # missing) and `POST` (the submission). That is the whole of PRD §23's guest surface, and
    # the count is the point of the census — a fifth route under `/api/v1/guest/` would have to
    # be added here, in a diff a reviewer sees.
    ("GET", "/api/v1/guest/info/{token}"),
    ("GET", "/api/v1/guest/checkin/{token}"),
    ("POST", "/api/v1/guest/checkin/{token}"),
    # The only one of the four that creates a row from a stranger's free text. It authorises
    # through the same `GuestPortalAuthenticator`, and R5.3 is structural: no route here reads
    # an incident back, so there is nothing to restrict.
    ("POST", "/api/v1/guest/incident/{token}"),
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

    The flattening itself lives in `tests/route_walk.py` — it is shared with the contract
    guard of `test_openapi_contract.py`, which was first written by copying the shape of
    this file without the walk and passed while inspecting nothing. Its docstring records
    the `_IncludedRouter` trap that makes the walk necessary.

    What stays here is the second vacuity trap, which is this file's own: keeping only
    `isinstance(route, APIRoute)` and dropping everything else means a
    `@app.websocket(...)`, an `app.mount(...)` or a plain starlette `Route` adds real,
    unauthenticated surface this check never sees. So the rule is: anything that is not an
    `APIRoute` and not on the anonymous allowlist comes back as UNINSPECTABLE, and the
    caller fails on it. FastAPI's own `/docs`, `/redoc` and `/openapi.json` are plain
    starlette `Route`s, which is exactly why the allowlist — not the route class — is what
    grants the exemption.
    """
    found, other = flatten_routes(app)
    uninspectable = [
        f"{type(route).__name__} {path}"
        for path, route in other
        if not _is_anonymous(path, getattr(route, "methods", None))
    ]
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
    per-method permissions are asserted in `tests/reservations/test_authorization.py` — and by
    `user-management` with three user paths (six methods) plus the tenant one (two methods),
    asserted per method and per role in `tests/auth/test_user_admin_authorization.py` and
    `tests/tenants/test_api.py`; by `properties-crud` with two property paths (four
    methods), asserted per method and per role in `tests/properties/test_authorization.py`;
    and by `cleaning` with the checklist template path (two methods), asserted the same way
    in `tests/cleaning/test_templates_api.py`; by `cleaning-photos-storage` with the photo
    upload path, whose `EXECUTE_CLEANING_TASKS` permission and cleaner-owns-the-task rule are
    asserted in `tests/cleaning/test_photos_api.py`; by `access-notifications` with the five
    access-record paths and the in-app inbox, asserted per role in
    `tests/access/test_api.py` and `tests/notifications/test_api.py`; and by
    `reservations-webhooks` with the two webhook-endpoint paths (one method each), asserted per
    role in `tests/integrations/test_webhook_endpoints_api.py`.

    The webhook **receiver** of that last change is deliberately not here and will not be: it is
    anonymous by design (rule 12(b) — the route token is the credential), so it joins
    `ANONYMOUS_ENDPOINTS` above, which is the visible diff this module exists to force.

    And by `guest-portal-api` with the guest-access-token path (`POST` and `DELETE`, both
    `MANAGE_GUEST_ACCESS_TOKENS`), asserted per role in `tests/guests/test_api.py`. Its four
    **anonymous** portal routes are the same case as the webhook receiver and join
    `ANONYMOUS_ENDPOINTS` instead — the token in the path is the credential, so there is no
    permission to declare.
    """
    routes, _ = _api_routes(create_app())
    protected = {path for path, route in routes if _declares_authorisation(route)}

    assert protected == {
        "/api/v1/access-records",
        "/api/v1/access-records/{record_id}",
        "/api/v1/access-records/{record_id}/delivered",
        "/api/v1/access-records/{record_id}/external",
        "/api/v1/access-records/{record_id}/manual-code",
        "/api/v1/notifications",
        "/api/v1/guests/{guest_id}/document",
        "/api/v1/reservations/{reservation_id}/legal-registration/submit",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/cleaning-checklist-templates",
        "/api/v1/cleaning-tasks",
        "/api/v1/cleaning-tasks/{task_id}",
        "/api/v1/cleaning-tasks/{task_id}/accept",
        "/api/v1/cleaning-tasks/{task_id}/checklist",
        "/api/v1/cleaning-tasks/{task_id}/checklist/{item_id}/complete",
        "/api/v1/cleaning-tasks/{task_id}/complete",
        "/api/v1/cleaning-tasks/{task_id}/photos",
        "/api/v1/cleaning-tasks/{task_id}/reject",
        "/api/v1/cleaning-tasks/{task_id}/start",
        "/api/v1/cleaning-tasks/{task_id}/validate",
        "/api/v1/reservations",
        "/api/v1/reservations/{reservation_id}",
        "/api/v1/reservations/{reservation_id}/guest-access-token",
        "/api/v1/integrations/pms/import-csv",
        "/api/v1/integrations/webhook-endpoints",
        "/api/v1/integrations/webhook-endpoints/{endpoint_id}/rotate",
        "/api/v1/users",
        "/api/v1/users/{user_id}",
        "/api/v1/users/{user_id}/reset-password",
        "/api/v1/tenants/{tenant_id}",
        "/api/v1/properties",
        "/api/v1/properties/{property_id}",
    }
