"""The published contract must describe the API this backend actually is (R3, design D9).

Structural, like `tests/test_route_authorization.py`: everything is derived from
`create_app()` and its routes, so a new endpoint or a new error code is covered without
anyone remembering to extend a list here.

The private `_MAPPING` tables are imported on purpose. They are one of the seven places
that used to spell error codes as bare literals, and this module is what keeps them
pointing at the single registry — reaching into them is the whole point, not a shortcut.
"""

import json
import socket

import httpx
import pytest
from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from app.auth.api.errors import _MAPPING as AUTH_MAPPING
from app.cleaning.api.errors import _MAPPING as CLEANING_MAPPING
from app.cli.openapi import _document, check, serialise
from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.errors import _HTTP_STATUS_CODES, AppError
from app.core.http_limits import TOO_LARGE_CODE
from app.core.openapi import ENVELOPE_SCHEMA_NAME, ErrorEnvelope, build_openapi
from app.main import create_app
from app.pricing.api.errors import _MAPPING as PRICING_MAPPING
from app.properties.api.errors import _MAPPING as PROPERTY_MAPPING
from app.reservations.api.errors import _MAPPING as RESERVATION_MAPPING
from app.tenants.api.errors import _MAPPING as TENANT_MAPPING
from tests.route_walk import flatten_routes

API_PREFIX = "/api/v1"
ENVELOPE_REF = {"$ref": f"#/components/schemas/{ENVELOPE_SCHEMA_NAME}"}


def _every_subclass(cls: type) -> list[type]:
    """Depth-first, not just `cls.__subclasses__()`.

    Every `AppError` subclass is direct today, so one level happens to be enough — but a
    grandchild with a literal `code` would sail past a one-level check, which is the exact
    silent gap the registry guard exists to close.
    """
    subclasses: list[type] = []
    for subclass in cls.__subclasses__():
        subclasses.append(subclass)
        subclasses += _every_subclass(subclass)
    return subclasses


def _api_routes(app) -> list[tuple[str, APIRoute]]:
    """The `/api/v1` routes, flattened through the shared walk.

    NOT `[r for r in app.routes if isinstance(r, APIRoute)]`: this FastAPI version keeps
    an included router as one `_IncludedRouter`, so that filter matches nothing and the
    guard below passes without inspecting a single endpoint. That is how this file was
    first written, and review caught it. See `tests/route_walk.py`.
    """
    found, _ = flatten_routes(app)
    return [(path, route) for path, route in found if path.startswith(API_PREFIX)]


def test_the_route_guard_actually_sees_the_api() -> None:
    """The guard on the guard below — a vacuous check is worse than a missing one.

    `test_every_api_route_declares_a_response_model` reports success on an empty list, so
    without this the whole check silently evaporates the day the walk stops matching.
    """
    routes = _api_routes(create_app())

    assert len(routes) >= 22
    assert {path.split("/")[3] for path, _ in routes} == {
        "auth",
        "users",
        "reservations",
        "integrations",
        "tenants",
        # `properties-crud`: four routes over two paths. The floor above moved from 18 to 22 with
        # them — it is a floor and not an equality so an added route does not fail here, but the
        # prefix set IS exact, so a new module has to be named.
        "properties",
        # `cleaning-stall-blocks-next-stay` D5: its own prefix rather than a literal segment
        # under `/properties`, which would collide with `/properties/{property_id}` and be
        # resolved by registration order.
        "blocked-transitions",
        # `cleaning`: templates plus the ten task routes of PRD §23 that did not need file
        # storage. `cleaning-photos-storage` adds the last two (`POST` and `GET .../photos`),
        # completing the twelve.
        "cleaning-checklist-templates",
        "cleaning-tasks",
        # The same change's third route, and the first of the two anonymous ones that serve
        # tenant data — `incident-photos` below is the second:
        # `GET /cleaning-photos/{photo_id}` (design D7). A prefix of its own because the path
        # is not under `/cleaning-tasks/` — the URL carries the photo id alone, never the
        # storage key (R3.2) and never the task.
        "cleaning-photos",
        # `incident-photos`: the same shape one module over, and for the same reason — the
        # anonymous route that serves an incident photo's bytes against an HMAC signature
        # (R4.1/R4.6). A prefix of its own because the path is not under `/incidents/`: the URL
        # carries the photo id alone, never the storage key (R3.3) and never the incident.
        #
        # The two are built by one factory (`app/integrations/api/signed_media.py`, design D5),
        # so they are the same surface twice rather than two surfaces — which is why the prose
        # above governs both and is not repeated.
        "incident-photos",
        # `maintenance`: the ten incident routes of design D14 plus the owner's answer. Two
        # prefixes because they are two aggregates — one incident can raise two approvals,
        # so the approval has an identity the incident cannot stand in for. There is
        # deliberately no `POST /incidents`: every source that creates one has a declared
        # owner elsewhere.
        "incidents",
        "owner-approvals",
        # `access-notifications`: the five access-record routes of PRD §15 and the in-app
        # inbox that makes `IN_APP` delivery a fact rather than a claim (design D5/D6).
        "access-records",
        "notifications",
        # PRD §17: guest documents and the SES.Hospedajes submission. The submit route lives
        # under `reservations` by path but on the guests router, so the prefix set already
        # names it.
        "guests",
        # `dashboard-api`: the read side of PRD §10, and the first `api/` layer the
        # `timeline` module has had.
        "timeline",
        # `dashboard-api`: the aggregate's own prefix. Its second route lives under
        # `properties`, which the set already names.
        "dashboard",
        # `reservations-webhooks`: the anonymous receiver. A module prefix of its own rather than
        # a route under `integrations`, because rule 12(b) of `steering/security.md` makes the
        # route token the credential and mixing it into the authenticated router would hide that.
        "webhooks",
        # `guest-portal-api`: the four anonymous routes of PRD §23, singular because the prefix
        # is the guest being served rather than the collection. A prefix of its own for the same
        # reason `webhooks` has one — the token in the path is the credential, and hanging these
        # off `guests` would put them on a router that declares `AUTHENTICATED_RESPONSES`.
        #
        # Note it is `guest`, not `guests`: the two are different surfaces, and PRD §23 spells
        # the anonymous one in the singular. That the two prefixes differ by a letter is worth
        # seeing here rather than discovering from a route that ended up on the wrong router.
        "guest",
        # `messaging-ai`: the seven inbox routes of PRD §16, all under one prefix because
        # `Conversation` is the aggregate and a message has no identity outside its thread —
        # unlike `incidents`/`owner-approvals`, which are two aggregates and therefore two.
        "conversations",
        # `revenue-pricing`: the seven routes of PRD §23. Two prefixes because they are two
        # aggregates (design D1) — the rules a person edits and the horizon the nightly job
        # rewrites, with their own permissions each.
        "pricing-rules",
        "price-recommendations",
        "provenance",
    }


# Routes whose success answer carries no body at all, so there is no shape to declare. Listed by
# path rather than exempting their status code wholesale: a `202` that later grew a body would be
# a contract that says nothing, and blanket-exempting `202` is what would let it through.
#
# `reservations-webhooks` R1.1 requires this one to answer "sin cuerpo de negocio" — anything
# echoed to an anonymous caller is a signal, and the only caller entitled to detail here is one
# that already holds both secrets.
BODILESS_SUCCESS_PATHS = frozenset({"/api/v1/webhooks/{provider}/{webhook_token}"})


def _declares_its_success_media_types(route: APIRoute) -> bool:
    """True when the route spells out the content of its success response by hand.

    The escape hatch for a body that is not JSON and therefore has no Pydantic model to name.
    It is **not** a weakening of the rule below: the obligation is "declare the shape of what
    you return", and a `content` block naming the media types discharges it just as a
    `response_model` does. What stays forbidden is declaring nothing — an empty or absent
    `content` is falsy here and still fails.
    """
    declared = (route.responses or {}).get(route.status_code or 200, {})
    return bool(declared.get("content"))


def test_every_api_route_declares_a_response_model() -> None:
    """R3.2 — a success response with no declared shape is a contract that says nothing.

    Three legitimate exemptions, all narrow:

    * `204 No Content` — there is no body to describe. Today exactly `POST /auth/logout`,
      `DELETE /users/{user_id}` and `DELETE /reservations/{reservation_id}`.
    * a body that is not JSON, which declares its media types in `responses` instead. Today
      exactly `GET /cleaning-photos/{photo_id}` (`cleaning-photos-storage`, design D7), which
      returns image bytes: `response_model` describes a JSON schema, and there is no JSON
      schema for a JPEG. It names `image/jpeg`, `image/png` and `image/webp` — the allowlist
      `content_type_for_extension` answers from — so the contract still says what comes back.
    * `BODILESS_SUCCESS_PATHS` — a success that is deliberately empty under a status other
      than 204. Today exactly the webhook receiver's `202` (`reservations-webhooks` R1.1).
    """
    app = create_app()
    undeclared = [
        f"{sorted(route.methods or [])} {path}"
        for path, route in _api_routes(app)
        if route.status_code != 204
        and route.response_model is None
        and not _declares_its_success_media_types(route)
        and path not in BODILESS_SUCCESS_PATHS
    ]

    assert undeclared == []


def test_the_bodiless_exemptions_really_return_nothing() -> None:
    """The exemption above is only honest while the route it names sends no body.

    Without this, adding a response body to an exempted path would be invisible: the guard skips
    it by name, so the contract would stop describing a body the endpoint actually returns.
    `tests/integrations/test_webhook_receiver_api.py` asserts the empty `202` over HTTP; this
    asserts that the exemption list has not outlived its reason.
    """
    exempted = [
        route for path, route in _api_routes(create_app()) if path in BODILESS_SUCCESS_PATHS
    ]

    assert len(exempted) == len(BODILESS_SUCCESS_PATHS)
    for route in exempted:
        assert route.response_model is None
        assert route.status_code == 202


def test_the_binary_exemption_does_not_wave_through_a_route_that_declares_nothing() -> None:
    """The guard on the exemption above — otherwise it could quietly become "anything goes".

    A route with neither a model nor a declared `content` must still fail, and one whose
    `content` block is empty must fail too: an empty dict is a declaration of nothing.

    `BODILESS_SUCCESS_PATHS` is subtracted here for the same reason the real check subtracts
    it, and leaving it out is what broke when `reservations-webhooks` and
    `cleaning-photos-storage` met: the webhook receiver declares no model and no media types
    — deliberately, its `202` has no body — so it showed up in this list as if it were one of
    the two synthetic routes. This test is about the **media-type** exemption not becoming
    "anything goes"; a path exempted by name is the other exemption's business, and
    `test_the_bodiless_exemptions_really_return_nothing` above is what guards that one.
    """
    app = create_app()

    @app.get(f"{API_PREFIX}/no-shape-at-all")
    async def shapeless():  # pragma: no cover - never called, only described
        return Response(b"")

    @app.get(f"{API_PREFIX}/empty-content-block", responses={200: {"content": {}}})
    async def empty_block():  # pragma: no cover - never called, only described
        return Response(b"")

    undeclared = sorted(
        path
        for path, route in _api_routes(app)
        if route.status_code != 204
        and route.response_model is None
        and not _declares_its_success_media_types(route)
        and path not in BODILESS_SUCCESS_PATHS
    )

    assert undeclared == [
        f"{API_PREFIX}/empty-content-block",
        f"{API_PREFIX}/no-shape-at-all",
    ]


def test_no_operation_documents_the_fastapi_validation_shape() -> None:
    """R3.1 — `{"detail": [...]}` is a shape `app/core/errors.py` never returns."""
    document = json.dumps(build_openapi(create_app()))

    assert "HTTPValidationError" not in document


def test_every_documented_error_response_references_the_envelope() -> None:
    """R3.1 — including the 422 FastAPI generates on its own."""
    schema = build_openapi(create_app())

    mismatched = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            for status_code, response in operation.get("responses", {}).items():
                if str(status_code)[:1] not in {"4", "5"}:
                    continue
                for media_type, media in (response.get("content") or {}).items():
                    if media.get("schema") != ENVELOPE_REF:
                        mismatched.append(
                            f"{method.upper()} {path} {status_code} {media_type}"
                        )

    assert mismatched == []


def test_the_published_catalogue_is_the_registry() -> None:
    """D11 — the enum consumers switch over must be the codes the backend can emit."""
    schema = build_openapi(create_app())

    published = set(schema["components"]["schemas"]["ErrorCode"]["enum"])

    assert published == {code.value for code in ErrorCode}


def test_no_error_code_lives_outside_the_registry() -> None:
    """D11 — the guard that keeps the published catalogue from going stale.

    A code written as a bare literal anywhere below would sail past the enum and reach a
    client the contract swears cannot produce it. That is not hypothetical: the first
    draft of D11 derived the catalogue from `AppError` alone and would have shipped
    without `CONFLICT` (409) and `PAYLOAD_TOO_LARGE` (413), both returned today.
    """
    declared: list[object] = [TOO_LARGE_CODE, *_HTTP_STATUS_CODES.values()]
    # Every module with a `_MAPPING` belongs here. `properties` was missing for the whole of
    # `properties-crud` and the review panel demonstrated the gap by injecting a bare string into
    # its mapping and watching this test still pass — the guard was blind to a module it was
    # supposed to cover, which is worse than not having it.
    # `cleaning` was the second module in that blind spot — its mapping has existed since
    # `cleaning` and was never inspected here — and `cleaning-photos-storage` is what makes the
    # omission matter: it adds four rows, one of them carrying a code (`BAD_GATEWAY`) that no
    # other mapping emits.
    # `revenue-pricing` adds itself in the same task that creates its mapping (its design D15),
    # rather than a task later: the docstring of `app/core/error_codes.py` documents that
    # exactly this gap already shipped once, so entering the guard is part of having a mapping
    # at all.
    for mapping in (
        AUTH_MAPPING,
        CLEANING_MAPPING,
        PRICING_MAPPING,
        PROPERTY_MAPPING,
        RESERVATION_MAPPING,
        TENANT_MAPPING,
    ):
        declared += [code for _, _, code in mapping]
    declared += [subclass.code for subclass in _every_subclass(AppError)]

    outside = [code for code in declared if not isinstance(code, ErrorCode)]

    assert outside == []


def _probe_app() -> FastAPI:
    """A throwaway app whose published schema DOES derive from configuration.

    No model in `app/` does this today, which is exactly why the stability test below
    needs it: without a document that genuinely varies, that test asserts a property
    nothing can violate and would keep passing if the comparison itself broke.
    """
    limit = settings.csv_import_max_rows

    class Probe(BaseModel):
        rows: int = Field(default=limit)

    probe = FastAPI(title="probe", version="0")

    @probe.get("/probe", response_model=Probe)
    def _read() -> Probe:  # pragma: no cover - never called, only described
        return Probe()

    return probe


def test_the_stability_check_can_detect_configuration_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard on the guard below (R1.2).

    Proves the serialisation pipeline reacts when the document really does depend on
    `Settings`. Without this, `test_the_serialised_contract_is_byte_stable` is vacuous:
    it would pass whether or not the check works, because nothing in `app/` currently
    derives a schema value from configuration.
    """
    before = serialise(build_openapi(_probe_app()))

    monkeypatch.setattr(settings, "csv_import_max_rows", 4321, raising=True)

    assert serialise(build_openapi(_probe_app())) != before


def test_the_serialised_contract_is_byte_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1.2 — the check of R2 is only meaningful if the output cannot wobble.

    Deliberately NOT two runs in the same environment, which would prove nothing: the
    failure this guards against is a schema deriving a default, an example or a limit
    from `Settings`, and that only shows up when the settings differ. If it ever does,
    the CI check would fail on the runner and pass on the developer's machine, and the
    report would read as a flaky test rather than as the real defect.
    """
    first = _document()

    monkeypatch.setattr(settings, "csv_import_max_bytes", 1234, raising=True)
    monkeypatch.setattr(settings, "csv_import_max_rows", 7, raising=True)
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 99, raising=True)
    monkeypatch.setattr(settings, "jwt_access_token_minutes", 1, raising=True)

    assert _document() == first


def test_generating_the_contract_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1.3 — the property the CI job of R2 depends on, asserted instead of assumed.

    The workflow runs with no PostgreSQL and no Redis service, so the day a schema starts
    sourcing something from the database — a dynamic enum read from a table is the
    plausible one — the contract job breaks on the runner while every local run stays
    green, because local and `backend-tests` always have both services up. Blocking the
    socket constructors turns that into a failure here first.

    Reaching the database or Redis needs an event loop, and `asyncio` opens a
    `socketpair` while bootstrapping one, so this trips before the driver is even
    involved. Known limit: `uvloop` (transitive through `uvicorn[standard]`) creates its
    sockets in C without going through this module, so a uvloop-backed loop would slip
    past. Inert today — nothing installs uvloop and generation is fully synchronous — but
    if this command or `build_openapi` ever grows an async path, this guard needs more
    than the stdlib constructors.
    """
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("generating the contract opened a socket (R1.3)")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert _document().startswith("{")


def test_the_committed_contract_matches_the_code() -> None:
    """R2.1 — the same comparison CI runs, so a stale file fails locally first."""
    assert check() == 0


@pytest.mark.asyncio
async def test_a_real_validation_failure_matches_the_published_shape() -> None:
    """R3.1 — the fidelity check.

    Without this the module would only prove that the document is self-consistent. The
    defect it exists to fix was precisely a document that disagreed with the handlers, so
    a declared shape nobody compares against a real response is the same bug rewritten.
    """
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"{API_PREFIX}/auth/login", json={})

    assert response.status_code == 422
    envelope = ErrorEnvelope.model_validate(response.json())
    assert envelope.error.code is ErrorCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_a_real_http_error_matches_the_published_shape() -> None:
    """R3.1 — the other handler, reached without touching any endpoint."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"{API_PREFIX}/there-is-no-such-endpoint")

    assert response.status_code == 404
    envelope = ErrorEnvelope.model_validate(response.json())
    assert envelope.error.code is ErrorCode.NOT_FOUND
