import tomllib
from pathlib import Path

from fastapi import FastAPI

# Imported for its side effect: every domain's models must be registered before the
# first request, or the global tenant filter (design D16) silently covers fewer
# tables than it should — see app/core/models_registry.py.
import app.core.models_registry  # noqa: F401
from app.auth.api.errors import register_auth_error_handlers
from app.auth.api.router import router as auth_router
from app.auth.api.users_router import router as users_router
from app.cleaning.api.errors import register_cleaning_error_handlers
from app.cleaning.api.tasks_router import router as cleaning_tasks_router
from app.cleaning.api.templates_router import router as cleaning_templates_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.http_limits import JSON_BODY_MAX_BYTES, MaxBodySizeMiddleware
from app.core.openapi import install_openapi
from app.integrations.api.errors import register_integration_error_handlers
from app.integrations.api.router import router as integrations_router
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
    register_error_handlers(app)
    register_auth_error_handlers(app)
    register_reservation_error_handlers(app)
    register_integration_error_handlers(app)
    register_tenant_error_handlers(app)
    register_cleaning_error_handlers(app)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    # `user-management`: a second router of the same module. `auth` owns the `User`
    # aggregate, so its writers live there too (its design D1), but the endpoints of PRD §23
    # are under `/users`, not under `/auth`.
    app.include_router(users_router, prefix=API_V1_PREFIX)
    app.include_router(reservations_router, prefix=API_V1_PREFIX)
    app.include_router(integrations_router, prefix=API_V1_PREFIX)
    app.include_router(tenants_router, prefix=API_V1_PREFIX)
    # `cleaning`: templates are their own router because they are their own aggregate, and
    # because PRD §23 does not declare them — the deviation is easier to see in a file of
    # its own than buried among the task routes (proposal R1, `ASSUMPTION`).
    app.include_router(cleaning_templates_router, prefix=API_V1_PREFIX)
    app.include_router(cleaning_tasks_router, prefix=API_V1_PREFIX)

    # Before anything reads the body — see `app/core/http_limits.py` for why an in-endpoint
    # check is too late for an upload.
    app.add_middleware(
        MaxBodySizeMiddleware,
        path_prefixes=(f"{API_V1_PREFIX}/integrations/",),
        max_bytes_provider=lambda: settings.csv_import_max_bytes,
    )
    # `cleaning`: the checklist template endpoint takes a client-sized array, so it is the
    # first JSON route whose body is not a small fixed object. Its Pydantic caps run after the
    # whole body is in memory and after `require(...)`, so without this an anonymous request
    # can make the backend read arbitrary volumes before the 401 (measured by the security
    # panel of sections 2-3). One prefix covers `/cleaning-checklist-templates` and
    # `/cleaning-tasks`.
    #
    # **Obligation for `cleaning-photos-storage`**: `POST /cleaning-tasks/{id}/photos` starts
    # with this prefix too, so as mounted this ceiling would refuse any photo above 1 MiB.
    # The repair is NOT to raise `JSON_BODY_MAX_BYTES` — that would remove the JSON ceiling
    # from every cleaning route and re-open the hole this closes. That change has to teach
    # `MaxBodySizeMiddleware` to exclude a path, or split the prefixes so the upload path is
    # served only by its own instance with the 10 MB of rule 6. Recorded here and in the
    # roadmap entry.
    app.add_middleware(
        MaxBodySizeMiddleware,
        path_prefixes=(f"{API_V1_PREFIX}/cleaning-",),
        max_bytes_provider=lambda: JSON_BODY_MAX_BYTES,
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
