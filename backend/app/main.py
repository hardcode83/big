import tomllib
from pathlib import Path

from fastapi import FastAPI

# Imported for its side effect: every domain's models must be registered before the
# first request, or the global tenant filter (design D16) silently covers fewer
# tables than it should — see app/core/models_registry.py.
import app.core.models_registry  # noqa: F401
from app.access.api.errors import register_access_error_handlers
from app.access.api.router import router as access_router
from app.auth.api.errors import register_auth_error_handlers
from app.auth.api.router import router as auth_router
from app.auth.api.users_router import router as users_router
from app.cleaning.api.errors import register_cleaning_error_handlers
from app.cleaning.api.photos_router import router as cleaning_photos_router
from app.cleaning.api.tasks_router import router as cleaning_tasks_router
from app.cleaning.api.templates_router import router as cleaning_templates_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.http_limits import JSON_BODY_MAX_BYTES, MaxBodySizeMiddleware
from app.core.log_redaction import install_path_token_redaction
from app.core.openapi import install_openapi
from app.guests.api.errors import register_guest_error_handlers
from app.guests.api.portal_router import router as guest_portal_router
from app.guests.api.router import router as guests_router
from app.integrations.api.errors import register_integration_error_handlers
from app.integrations.api.router import router as integrations_router
from app.integrations.api.webhooks_router import router as webhooks_router
from app.notifications.api.router import router as notifications_router
from app.properties.api.errors import register_property_error_handlers
from app.properties.api.router import router as properties_router
from app.reservations.api.errors import register_reservation_error_handlers
from app.reservations.api.router import router as reservations_router
from app.tenants.api.errors import register_tenant_error_handlers
from app.tenants.api.router import router as tenants_router

API_V1_PREFIX = "/api/v1"

# `pyproject.toml` declares no `[build-system]`, so `backend` is never installed as a
# distribution and `importlib.metadata.version()` raises everywhere — including inside the
# container. Reading the file is the only source that exists in every environment; it ships
# in the image (`COPY pyproject.toml` in `devops/Dockerfile`), and `app/core/config.py`
# already locates the repo `.env` the same way.
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _package_version() -> str:
    with _PYPROJECT.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def create_app() -> FastAPI:
    # The version of the installed package, NOT the build string of
    # `app-version-visibility` (`0.1.0+2026-07-31.5872022`) and NOT the root `VERSION`
    # file. The build string would change on every commit, leaving the committed
    # `openapi.json` — and therefore its CI check — permanently out of date; the root
    # file is unreachable because containers mount only their own directory.
    app = FastAPI(title="AutoHostAI backend", version=_package_version())
    # Before any route exists, because the leak it closes is in the access log rather than in a
    # handler: both the webhook route token and the guest portal token travel as path segments
    # (`reservations-webhooks` D1, `guest-portal-api` D8), and uvicorn logs paths by default.
    # See `app/core/log_redaction.py`.
    install_path_token_redaction()
    register_error_handlers(app)
    register_auth_error_handlers(app)
    register_reservation_error_handlers(app)
    register_integration_error_handlers(app)
    register_tenant_error_handlers(app)
    register_property_error_handlers(app)
    register_cleaning_error_handlers(app)
    register_access_error_handlers(app)
    register_guest_error_handlers(app)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    # `user-management`: a second router of the same module. `auth` owns the `User`
    # aggregate, so its writers live there too (its design D1), but the endpoints of PRD §23
    # are under `/users`, not under `/auth`.
    app.include_router(users_router, prefix=API_V1_PREFIX)
    app.include_router(reservations_router, prefix=API_V1_PREFIX)
    app.include_router(integrations_router, prefix=API_V1_PREFIX)
    # `reservations-webhooks`: a SECOND router of the `integrations` module, and separate on
    # purpose. It is the only anonymous route outside `auth`, because rule 12(b) of
    # `steering/security.md` makes the route token itself the credential. Putting it on the
    # router above — which carries `AUTHENTICATED_RESPONSES` and whose every route declares a
    # permission — would hide an unauthenticated endpoint inside a shape that says otherwise.
    # `tests/test_route_authorization.py` names it in its anonymous allowlist, which is the
    # visible diff that decision has to pass through.
    app.include_router(webhooks_router, prefix=API_V1_PREFIX)
    app.include_router(tenants_router, prefix=API_V1_PREFIX)
    # `properties-crud`: the first `api/` layer of the `properties` domain, which until now was
    # the only domain module without one. Its arrival is what makes `POST /reservations`
    # reachable — it answered 404 on every request because no property could exist.
    app.include_router(properties_router, prefix=API_V1_PREFIX)
    # `cleaning`: templates are their own router because they are their own aggregate, and
    # because PRD §23 does not declare them — the deviation is easier to see in a file of
    # its own than buried among the task routes (proposal R1, `ASSUMPTION`).
    app.include_router(cleaning_templates_router, prefix=API_V1_PREFIX)
    app.include_router(cleaning_tasks_router, prefix=API_V1_PREFIX)
    # `cleaning-photos-storage`: the **only anonymous route this application mounts** besides
    # login, refresh and `/health` (design D7). Its own router because it is the only one, and
    # because sharing `cleaning_tasks_router` — which declares `AUTHENTICATED_RESPONSES` and
    # hangs every route off a `require(...)` — would put an unauthenticated endpoint one copied
    # decorator away from twelve authorised ones. The signature in its query string is its
    # authorisation, and `tests/test_route_authorization.py` names it in `ANONYMOUS_ENDPOINTS`,
    # which is a visible diff by construction.
    app.include_router(cleaning_photos_router, prefix=API_V1_PREFIX)
    # `access-notifications`: the read side of the in-app channel. Without it the dispatcher
    # would mark `IN_APP` rows `SENT` with nothing able to show them to their recipient
    # (design D5/D6).
    app.include_router(notifications_router, prefix=API_V1_PREFIX)
    # `access-notifications`: PRD §15's operator surface. The `access` domain had entities and
    # a table since `domain-foundation-ops` and no way to reach them until now.
    app.include_router(access_router, prefix=API_V1_PREFIX)
    # `access-notifications`: guest documents and the SES.Hospedajes submission (PRD §17).
    # One router for everything that touches an identity document, which is the file a
    # reviewer opens when a real provider arrives.
    app.include_router(guests_router, prefix=API_V1_PREFIX)
    # The anonymous half of `guests`, mounted separately on purpose (`guest-portal-api` D1):
    # its routes carry no `Authorization` header and declare no permission, because the token
    # in the path is the credential. Keeping them off `guests_router` — which declares
    # `AUTHENTICATED_RESPONSES` — is what stops an unauthenticated route from hiding inside a
    # shape that says otherwise, and forces an entry per route in `ANONYMOUS_ENDPOINTS`:
    # four, one per route of PRD §23.
    app.include_router(guest_portal_router, prefix=API_V1_PREFIX)

    # Before anything reads the body — see `app/core/http_limits.py` for why an in-endpoint
    # check is too late.
    #
    # ONE mounting covering all of `/api/v1/`, with the ceiling resolved PER PATH. It used to
    # be two, and merging them is not tidying: `api-ingress-routing` and `cleaning` found the
    # same hole independently — an unbounded body read in full before the `401` — and each
    # mounted its own instance. Stacked instances nest, so the outermost decides first and a
    # narrower inner ceiling never gets to see the request; the generic 1 MiB would have
    # refused a 10 MB CSV before the upload instance could allow it.
    #
    # The four cases, and each number has its own reason:
    #
    # * `/cleaning-tasks/…/photos` → `PHOTO_UPLOAD_MAX_BYTES` (10 MiB). From
    #   `cleaning-photos-storage` (R5, design D10). **It is first, and the position is the
    #   mechanism, not tidiness**: the path also starts with `/cleaning-`, so an `elif` after
    #   that branch would never be reached and every photo above 1 MiB would be refused.
    # * `/integrations/` → `CSV_IMPORT_MAX_BYTES` (10 MiB). Rule 6 of steering/security.md.
    # * `/cleaning-` → `JSON_BODY_MAX_BYTES` (1 MiB). From `cleaning`: the checklist template
    #   endpoint takes a **client-sized array**, so its body is not a small fixed object, and
    #   its Pydantic caps only run once the whole body is in memory. Measured there: an
    #   anonymous ~50 MB `POST` was received in full and then answered `401`. The constant is
    #   measured against that schema's maximum (338 KB with accented labels), NOT guessed.
    # * everything else → `REQUEST_MAX_BYTES` (1 MiB). From `api-ingress-routing` (R7/D11):
    #   once `/api/v1` is reachable from the internet, an unbounded body on a public anonymous
    #   endpoint is a memory amplifier — measured, one 400 MB `POST /auth/login` took the
    #   container from 195 MiB to 1.016 GiB of RSS, and FastAPI reads that body before
    #   dependencies run, i.e. before the 10/min login throttle is ever consulted.
    #
    # `JSON_BODY_MAX_BYTES` and `REQUEST_MAX_BYTES` happen to be equal today. They stay
    # separate on purpose: one is pinned to a schema maximum and one is an operational knob,
    # so collapsing them would make a future tuning of the knob silently move a measured
    # boundary.
    #
    # **The obligation `cleaning` recorded for `cleaning-photos-storage` is now paid.**
    # `POST /cleaning-tasks/{id}/photos` starts with `/cleaning-`, so the JSON ceiling would
    # refuse any photo above 1 MiB. `cleaning` noted the repair would have to "teach
    # `MaxBodySizeMiddleware` to exclude a path, or split the prefixes" — the per-path
    # provider IS that capability, so the repair is the one branch below, before the
    # `/cleaning-` one. Still NOT by raising `JSON_BODY_MAX_BYTES`, which would remove the
    # JSON ceiling from every cleaning route and re-open the hole it closes.
    #
    # The photo branch matches on BOTH ends — the `/cleaning-tasks/` prefix and a trailing
    # `/photos` — so the wider ceiling reaches that one collection and no neighbour that
    # happens to end the same way. `tests/cleaning/test_photo_body_limit.py` pins all three
    # halves: the photo body passes, the template body is still refused, and a lookalike path
    # keeps the JSON ceiling.
    #
    # **ACCEPTED RISK, photo branch: 10 MiB of anonymous body before any authentication.**
    # This provider is consulted by the middleware, which by construction runs before the
    # route is resolved and before `require(...)` — that is the whole reason it exists. So the
    # match is on the path string alone: anyone who can guess the URL shape can make the
    # backend receive up to `PHOTO_UPLOAD_MAX_BYTES` per request without a token, and the
    # answer (a 401) comes only after the body is in. The pattern is also **wider than the
    # route**: `/api/v1/cleaning-tasks/photos` and `/api/v1/cleaning-tasks/a/b/c/photos` match
    # it too, so those consume up to 10 MiB and then answer 404/405. Tightening the pattern to
    # a UUID segment would narrow the second half but not the first, which is the one that
    # matters — a real task id is just as guessable in shape.
    #
    # Accepted because it is the irreducible cost of having an upload endpoint at all, and it
    # is the same bargain `/integrations/` already struck with `CSV_IMPORT_MAX_BYTES` (also
    # 10 MiB, also pre-auth). What bounds it is that 10 MiB is ~40× below the 400 MB body that
    # made `api-ingress-routing` mount this middleware in the first place, and that it is a
    # per-request ceiling, not a per-connection one. Written down here because it was not
    # written down anywhere: the other three branches each carry the measurement that justifies
    # their number, and this one carried none.
    app.add_middleware(
        MaxBodySizeMiddleware,
        path_prefixes=(API_V1_PREFIX,),
        max_bytes_provider=lambda path: (
            settings.photo_upload_max_bytes
            if path.startswith(f"{API_V1_PREFIX}/cleaning-tasks/")
            and path.endswith("/photos")
            else settings.csv_import_max_bytes
            if path.startswith(f"{API_V1_PREFIX}/integrations/")
            else JSON_BODY_MAX_BYTES
            if path.startswith(f"{API_V1_PREFIX}/cleaning-")
            else settings.request_max_bytes
        ),
    )

    # Deliberately NOT under API_V1_PREFIX (design D2): the container healthcheck
    # in docker-compose.yml and docker-compose.deploy.yml probes /health, and the
    # frontend and worker services gate on it via depends_on.
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Last: it reads `app.routes`, so every router must already be mounted.
    install_openapi(app)

    return app


app = create_app()
