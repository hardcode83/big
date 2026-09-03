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
# `GET /api/v1/cleaning-photos/{photo_id}` is the fourth kind, and since `incident-photos` one
# of **two** that serve tenant data — `GET /api/v1/incident-photos/{photo_id}` is the other, and
# the same factory builds both (that change's D5). It cannot require a token because a
# browser fetching an `<img src>` sends no `Authorization` header, so a signed URL gated on
# one would work for nothing. **Its authorisation is the HMAC in its query string**, verified
# by `ServeSignedObjectUseCase` against the object key read from the database — a key
# that begins with `tenants/{tenant_id}/`, so a valid signature proves the caller was handed a
# URL minted for that photo of that tenant. Refusals answer one constant `403` body for
# "wrong", "expired", "tampered" and "no such photo" alike, so the exemption does not hand an
# unauthenticated caller an existence oracle. Pinned in `tests/cleaning/test_serve_photo_api.py`
# and `tests/integrations/test_signed_serving_use_case.py`; the entry below is the visible diff
# this allowlist exists to force.
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
    # `auth-account-recovery` R2.1: anonymous by necessity — somebody who has lost their
    # password cannot authenticate to ask for a link. Its protections are the shared per-IP
    # budget (R2.4) and a response that is identical whatever the address resolves to (R2.2),
    # not a permission.
    ("POST", "/api/v1/auth/forgot-password"),
    # `auth-account-recovery` R3.1: anonymous for the same reason — the token IS the
    # credential, and somebody who lost their password cannot authenticate to spend it. Its
    # protections are the shared per-IP budget (R3.7), single use enforced by one conditional
    # UPDATE (R3.2), and one indistinguishable error for every failure (R3.3).
    ("POST", "/api/v1/auth/reset-password"),
    ("GET", "/api/v1/cleaning-photos/{photo_id}"),
    # `incident-photos` R4.1/R4.6, design D12. Anonymous for exactly the reason the cleaning
    # one above is, and it is the **second route in the application that serves object bytes
    # against an HMAC signature** — the two are built by one factory
    # (`app/integrations/api/signed_media.py`, design D5), so the reasoning that governs the
    # cleaning entry governs this one and is not restated.
    #
    # It is the twelfth entry in this census, not the second: the proposal said "second" while
    # counting only the signed-media routes, and design D12 corrected that in writing.
    ("GET", "/api/v1/incident-photos/{photo_id}"),
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


def test_manage_platform_only_lives_under_platform_prefix() -> None:
    """Design risk R-6: `MANAGE_PLATFORM` is the platform's permission; only platform routes
    carry it.

    `platform-admin-api` introduces the permission as `SUPER_ADMIN`'s alone and ships it under
    `/api/v1/platform/`. A route hung off a sibling prefix (a stray `require(MANAGE_PLATFORM)`
    added to a tenants-scoped endpoint, for example) would still pass the snapshot test above
    — it would just add a new entry to `protected` — so this guard pins the property the
    snapshot cannot: the permission is bound to its prefix, not to a role check the body can
    work around. A future cross-tenant surface would either live under the same prefix (and
    keep the property) or fail this test, which is the visible diff a reviewer sees.
    """
    routes, _ = _api_routes(create_app())
    offending = sorted(
        path
        for path, route in routes
        if Permission.MANAGE_PLATFORM in _declared_permissions(route)
        and not path.startswith("/api/v1/platform/")
    )

    assert not offending, (
        f"routes declaring `MANAGE_PLATFORM` outside `/api/v1/platform/`: {offending}. "
        "The platform permission lives under the platform prefix; a route elsewhere that "
        "needs cross-tenant reach either moves under `/api/v1/platform/` or declares a "
        "permission of its own."
    )


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
    `dashboard-api` with four read paths: the timeline, the property state, the dashboard
    collection and the property aggregate, asserted per role in `tests/timeline/test_api.py`,
    `tests/properties/test_state_api.py` and `tests/dashboard/test_api.py`.

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

    And by `cleaner-task-context` with the task context path (`GET`, `READ_CLEANING_TASKS`),
    asserted per role in `tests/cleaning/test_task_context_api.py`. It declares no new permission
    on purpose (its design D7): the gate is the one the sibling read routes already use, and the
    row-level half — a `CLEANER` reaches only her own tasks — is derived inside the use case from
    the persisted role, which is precisely the kind of restriction this snapshot cannot see.
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
        # `notifications-inbox-web` R1.2/R2.2/R5.2: the three routes that close the in-app
        # cycle. All three declare `READ_OWN_NOTIFICATIONS` and **no new permission** —
        # acknowledging one's own notice is not a capability distinct from reading it (that
        # change's design D2) — and all three derive the recipient from the token, which is
        # the restriction this snapshot cannot see. Asserted per role in
        # `tests/notifications/test_api.py`, and across tenants in
        # `tests/notifications/test_read_isolation.py`.
        "/api/v1/notifications/unread-count",
        "/api/v1/notifications/read-all",
        "/api/v1/notifications/{notification_id}/read",
        "/api/v1/guests/{guest_id}/document",
        "/api/v1/reservations/{reservation_id}/legal-registration/submit",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        # `auth-account-recovery` R1.4: self-service, so `MANAGE_OWN_SESSION` — the permission
        # PRD §6 grants to every role that can authenticate. Asserted per role in
        # `tests/auth/test_recovery_api.py`. The change's other two endpoints are anonymous
        # and live in `ANONYMOUS_ENDPOINTS` instead.
        "/api/v1/auth/change-password",
        "/api/v1/cleaning-checklist-templates",
        "/api/v1/cleaning-tasks",
        "/api/v1/cleaning-tasks/{task_id}",
        "/api/v1/cleaning-tasks/{task_id}/accept",
        # `cleaning-stall-blocks-next-stay` R3.1: the exit the cycle lacked, restricted to
        # `MANAGE_CLEANING_TASKS`. Asserted per role in `tests/cleaning/test_tasks_api.py`.
        "/api/v1/cleaning-tasks/{task_id}/cancel",
        "/api/v1/cleaning-tasks/{task_id}/checklist",
        "/api/v1/cleaning-tasks/{task_id}/checklist/{item_id}/complete",
        "/api/v1/cleaning-tasks/{task_id}/complete",
        "/api/v1/cleaning-tasks/{task_id}/context",
        # `cleaner-incident-report`: the cleaner opens an incident from her own task. Gated on
        # `EXECUTE_CLEANING_TASKS`, which no other role holds, so it needed no new permission —
        # and it lives here rather than under `/api/v1/incidents` precisely so that module's
        # "no creation route" invariant survives (R1.2).
        "/api/v1/cleaning-tasks/{task_id}/incidents",
        # `cleaner-photo-requirements` R4.1: `READ_CLEANING_TASKS`, **no new permission**, on the
        # same reasoning as the context path above. It is the read half of the photo path right
        # below it — the cleaner is told which categories exist instead of discovering them by
        # trying identifiers against that route's 404 — and reading three fields of the task's
        # own template server-side is deliberately not `READ_CLEANING_TEMPLATES` (R4.2), which
        # would open the tenant's whole template catalogue to resolve one row. The row-level
        # half is again derived from the persisted role and invisible to this snapshot.
        # Asserted per role in `tests/cleaning/test_photo_requirements_api.py`.
        "/api/v1/cleaning-tasks/{task_id}/photo-requirements",
        "/api/v1/cleaning-tasks/{task_id}/photos",
        "/api/v1/cleaning-tasks/{task_id}/reject",
        "/api/v1/cleaning-tasks/{task_id}/start",
        "/api/v1/cleaning-tasks/{task_id}/validate",
        # `maintenance`: sixteen authenticated routes now, fifteen here plus the owner approval
        # below — fourteen until `incident-photos` added `POST` and `GET` on `.../photos`, and
        # thirteen before `tech-cycle-completion` added `reject`. Every one of *these* is
        # authenticated. The module does have an anonymous door, exactly one, and it is not on
        # this router: `GET /api/v1/incident-photos/{photo_id}` is in `ANONYMOUS_ENDPOINTS`
        # above (R4.6). The only surface that creates an incident without a session is still
        # the guest portal's, also in `ANONYMOUS_ENDPOINTS`.
        # Asserted per role in `tests/maintenance/test_api_incidents.py`.
        "/api/v1/incidents",
        "/api/v1/incidents/{incident_id}",
        "/api/v1/incidents/{incident_id}/accept",
        "/api/v1/incidents/{incident_id}/assign",
        "/api/v1/incidents/{incident_id}/cancel",
        "/api/v1/incidents/{incident_id}/classify",
        # `tech-incident-context` R4.1: `READ_INCIDENTS`, **no new permission**, and a
        # `TECHNICIAN` narrowed to their own rows by the persisted role rather than by anything
        # this table can see. Its own authorisation cases — `CLEANER` refused, guest token
        # refused — are in `tests/maintenance/test_incident_context_api.py`.
        "/api/v1/incidents/{incident_id}/context",
        # `tech-cycle-completion` R2.3: renamed from `/start`, same `EXECUTE_INCIDENTS`. The
        # old path is gone rather than aliased — there was no consumer to protect.
        "/api/v1/incidents/{incident_id}/en-route",
        # `tech-cycle-completion` R1.6: `EXECUTE_INCIDENTS`, the same gate the rest of the
        # technician's cycle uses, and **no new permission**. The row-level half — only the
        # assignee, or a `PROPERTY_MANAGER` unblocking — is derived inside the use case from
        # the persisted role, which is the kind of restriction this snapshot cannot see. Its
        # per-role cases are in `tests/maintenance/test_api_authorization.py`.
        "/api/v1/incidents/{incident_id}/reject",
        # `incident-photos` R2.2/R3.2: the upload takes `EXECUTE_INCIDENTS` and the listing
        # `READ_INCIDENTS`, both **already existing** — `ROLE_PERMISSIONS` is untouched, so
        # uploading stays with the `TECHNICIAN` and `PROPERTY_MANAGER` while listing adds the
        # `TENANT_OWNER`. One path, two methods; asserted per role in
        # `tests/maintenance/test_api_authorization.py`.
        #
        # The change's third route, `GET /api/v1/incident-photos/{photo_id}`, is anonymous and
        # lives in `ANONYMOUS_ENDPOINTS` instead — deliberately not hung off this router, whose
        # every path carries a `require(...)`.
        "/api/v1/incidents/{incident_id}/photos",
        "/api/v1/incidents/{incident_id}/resolve",
        "/api/v1/incidents/{incident_id}/resume",
        "/api/v1/incidents/{incident_id}/wait-parts",
        "/api/v1/owner-approvals/{approval_id}/respond",
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
        "/api/v1/properties/{property_id}/state",
        # `cleaning-stall-blocks-next-stay` D5: a path of its own rather than a literal segment
        # under `/properties`, which would collide with `/properties/{property_id}`. Read with
        # `READ_PROPERTIES` (D6), so the owner sees her own stalled flat; asserted per role in
        # `tests/properties/test_blocked_transitions_api.py`.
        "/api/v1/blocked-transitions",
        "/api/v1/timeline/{property_id}",
        "/api/v1/dashboard/properties",
        "/api/v1/properties/{property_id}/dashboard",
        # `revenue-reviews` R5: the seven routes of PRD §18 over five paths. Every one is
        # authenticated; the narrowest gate (`APPROVE_REVIEW`) is what `require(...)`
        # declares for the response PATCH route — `IGNORE_REVIEW` and `MARK_REVIEW_POSTED`
        # are also required at the router (asserted per role in
        # `tests/reviews/test_review_endpoints.py`), and the cross-tenant `404`
        # indistinguishability is asserted in `tests/reviews/test_tenant_isolation.py`.
        "/api/v1/reviews",
        "/api/v1/reviews/{review_id}",
        "/api/v1/reviews/{review_id}/response",
        "/api/v1/properties/{property_id}/reviews/summary",
        # `dashboard-operational-kpis` R4.2: same door as the two routes above
        # (`require(Permission.READ_PROPERTIES)`), but each of its three fields is
        # redacted to `null` inside the use case when the caller's role lacks the finer
        # permission that guards its source domain — never a second gate at the router.
        # Asserted per role in `tests/dashboard/test_api.py`.
        "/api/v1/dashboard/operational-kpis",
        # `revenue-pricing`: the seven routes of PRD §23 over five paths, on two routers
        # because they are two aggregates (design D1). Every one is authenticated — the
        # module has no anonymous door, and the nightly generator reaches the same use case
        # through the scheduler rather than through a route. Asserted per method and per role
        # in `tests/pricing/test_api_authorization.py`.
        "/api/v1/pricing-rules",
        "/api/v1/pricing-rules/{rule_id}",
        "/api/v1/price-recommendations",
        "/api/v1/price-recommendations/generate",
        "/api/v1/price-recommendations/{recommendation_id}",
        "/api/v1/provenance",
        # `messaging-ai` D17: the seven routes of PRD §16, five distinct paths. All
        # authenticated, and deliberately so — messages enter through the panel or the API,
        # never from an OTA, because `PMSMessagingPort` is still the port with no methods.
        # There is no anonymous door into this module, which is what keeps the human actor of
        # D12 true and therefore keeps rule 9 free of a new exception. Asserted per role in
        # `tests/messaging/test_api_authorization.py`.
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/escalate",
        "/api/v1/conversations/{conversation_id}/resolve",
        # `platform-admin-api` R6.1: the cross-tenant surface, two routes under one router,
        # both gated on `MANAGE_PLATFORM` (held by `SUPER_ADMIN` and nobody else,
        # `app.auth.domain.policy`). Asserted per role in
        # `tests/platform/test_api.py::test_post_tenants_with_a_non_super_admin_token_and_an_invalid_body_answers_403`
        # — the gate cuts BEFORE body validation, so an invalid body plus a non-SUPER_ADMIN
        # token still answers `403` (R1.4 / 4.14).
        "/api/v1/platform/tenants",
        "/api/v1/platform/tenants/{tenant_id}/users",
    }


# --- the password-change gate's exempt list (`auth-account-recovery` R5.4, design D6) ---


def test_every_password_change_exemption_names_a_real_route() -> None:
    """An exemption pointing at nothing is a route that is NOT exempt, and the failure is
    silent: the account is simply trapped on a path nobody tested.

    Derived from the registered routes rather than hand-compared, so renaming
    `/auth/change-password` breaks the suite here instead of turning the flag into a
    permanent lockout with no endpoint back.
    """
    from app.auth.api.dependencies import PASSWORD_CHANGE_EXEMPT

    routes, _ = _api_routes(create_app())
    registered = {
        (verb, path)
        for path, route in routes
        for verb in (route.methods or set())
        if verb != "HEAD"
    }

    unknown = PASSWORD_CHANGE_EXEMPT - registered
    assert not unknown, (
        f"exempt entries that match no registered route: {sorted(unknown)}. An exemption "
        "that points nowhere leaves the account fenced on that path."
    )


def test_the_way_out_of_the_password_change_state_is_exempt() -> None:
    """The one entry whose absence is unrecoverable (R5.4).

    Without it a temporary password becomes a permanent lockout: the holder can authenticate
    and can reach nothing, including the endpoint that would fix it.
    """
    from app.auth.api.dependencies import PASSWORD_CHANGE_EXEMPT

    assert ("POST", "/api/v1/auth/change-password") in PASSWORD_CHANGE_EXEMPT


def test_the_exempt_list_is_no_wider_than_the_requirement() -> None:
    """R5.4 names exactly three routes. A fourth would be an endpoint reachable with a
    temporary password, which is what the gate exists to prevent — so the list is pinned as
    a snapshot and any addition has to show up in this diff."""
    from app.auth.api.dependencies import PASSWORD_CHANGE_EXEMPT

    assert PASSWORD_CHANGE_EXEMPT == {
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/change-password"),
    }


def test_no_password_change_exemption_uses_a_path_parameter() -> None:
    """The constraint `password_change_exempt_key` imposes, enforced rather than trusted.

    The gate matches the path the client requested, so a pattern like `/users/{id}` would
    never equal it and the exemption would silently never fire. Failing loudly here is the
    difference between "this route is not exempt" and "somebody thinks it is".
    """
    from app.auth.api.dependencies import PASSWORD_CHANGE_EXEMPT

    parameterised = [path for _verb, path in PASSWORD_CHANGE_EXEMPT if "{" in path]
    assert not parameterised, (
        f"exempt entries with a path parameter: {sorted(parameterised)}. The gate compares "
        "against the requested path, so these could never match."
    )


def test_the_exempt_key_uses_the_routed_path() -> None:
    """The one structural test that CAN catch this bug, pinned against BOTH wrong formulas.

    Two guards before this were vacuous (see `test_where_the_exempt_list_is_actually_enforced`),
    and then a third formula was found wrong by review. The scope below reproduces both traps
    at once: `route.path` is mount-relative AND a `root_path` prefix is present, as it would
    be behind an ingress.

      - `get_route_path(scope)`         -> "/api/v1/auth/me"      matches the list
      - `scope["route"].path`           -> "/auth/me"             does NOT  (shipped broken)
      - `request.url.path`              -> "/gw/api/v1/auth/me"   does NOT  (root_path trap)

    The last two assertions are what make the first load-bearing instead of a restatement of
    the constant.
    """
    from fastapi import Request

    from app.auth.api.dependencies import (
        PASSWORD_CHANGE_EXEMPT,
        password_change_exempt_key,
    )

    class _MountRelativeRoute:
        path = "/auth/me"

    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/gw/api/v1/auth/me",
            "root_path": "/gw",
            "query_string": b"",
            "headers": [],
            "route": _MountRelativeRoute(),
        }
    )

    key = password_change_exempt_key(request)

    assert key == ("GET", "/api/v1/auth/me")
    assert key in PASSWORD_CHANGE_EXEMPT
    # Both rejected formulas would have fenced this request.
    assert ("GET", _MountRelativeRoute.path) not in PASSWORD_CHANGE_EXEMPT
    assert ("GET", request.url.path) not in PASSWORD_CHANGE_EXEMPT


def test_the_exempt_key_is_unaffected_by_the_absence_of_a_root_path() -> None:
    """The ordinary deployment, so the fix is not only correct behind an ingress."""
    from fastapi import Request

    from app.auth.api.dependencies import (
        PASSWORD_CHANGE_EXEMPT,
        password_change_exempt_key,
    )

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/change-password",
            "root_path": "",
            "query_string": b"",
            "headers": [],
        }
    )

    assert password_change_exempt_key(request) in PASSWORD_CHANGE_EXEMPT


def test_where_the_exempt_list_is_actually_enforced() -> None:
    """A signpost, not a guarantee — and the docstring is the point.

    Two structural guards were written for the exempt list and BOTH were vacuous, so this
    records the outcome rather than pretending a third one works:

    1. The first compared the list against paths reconstructed by `_api_routes`. The gate
       read `request.scope["route"].path`, which is mount-relative (`/auth/me`), so nothing
       matched at runtime while the guard compared two full paths and passed.
    2. The second drove real requests and captured the key from an `@app.middleware("http")`.
       Middleware runs BEFORE routing, so `scope["route"]` is unset there and the buggy
       formula falls back to `request.url.path` — the same value as the fixed one. Measured:
       both formulas "MATCH" from middleware, so the guard could not tell them apart.

    A third guard, `test_the_exempt_key_uses_the_routed_path`, IS non-vacuous — but only
    because it constructs a scope carrying both traps at once (a mount-relative `route.path`
    AND a non-empty `root_path`), so neither rejected formula can satisfy it. A guard that
    merely reads the list still proves nothing.

    What caught the bug, and what holds the property, is BEHAVIOURAL — four tests in
    `tests/auth/test_recovery_api.py` that put an account in the must-change state and check
    it can still reach each escape route:
      - `test_the_whole_escape_route_works_end_to_end`
      - `test_me_is_reachable_while_fenced_and_reports_the_flag`
      - `test_logout_is_reachable_while_fenced`
      - `test_refresh_works_while_fenced`
    Those failed loudly with `403 PASSWORD_CHANGE_REQUIRED` on all three exempt routes.

    The lesson for whoever edits the list: a test that inspects the list proves nothing about
    the gate. Add a behavioural test for the new entry.
    """
    from app.auth.api.dependencies import PASSWORD_CHANGE_EXEMPT

    assert len(PASSWORD_CHANGE_EXEMPT) == 3


def test_refresh_is_not_exempt_and_does_not_need_to_be() -> None:
    """R5.5: `POST /auth/refresh` must keep working for an account owing a change, and it
    does so by not passing through the gate at all rather than by being listed.

    Pinned because "add it to the exempt list" is the obvious wrong fix if somebody later
    believes refresh is blocked: listing it would be harmless but misleading, and the real
    property is that the dependency is not in its path.
    """
    from app.auth.api.dependencies import (
        PASSWORD_CHANGE_EXEMPT,
        get_authenticated_request,
    )

    assert ("POST", "/api/v1/auth/refresh") not in PASSWORD_CHANGE_EXEMPT

    routes, _ = _api_routes(create_app())
    refresh = [
        route
        for path, route in routes
        if path == "/api/v1/auth/refresh" and "POST" in (route.methods or set())
    ]
    assert len(refresh) == 1
    dependencies = {
        getattr(dependant.call, "__name__", None)
        for dependant in refresh[0].dependant.dependencies
    }
    assert get_authenticated_request.__name__ not in dependencies
