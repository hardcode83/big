from fastapi import FastAPI

# Imported for its side effect: every domain's models must be registered before the
# first request, or the global tenant filter (design D16) silently covers fewer
# tables than it should — see app/core/models_registry.py.
import app.core.models_registry  # noqa: F401
from app.auth.api.errors import register_auth_error_handlers
from app.auth.api.router import router as auth_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.http_limits import MaxBodySizeMiddleware
from app.integrations.api.errors import register_integration_error_handlers
from app.integrations.api.router import router as integrations_router
from app.reservations.api.errors import register_reservation_error_handlers
from app.reservations.api.router import router as reservations_router

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="AutoHostAI backend")
    register_error_handlers(app)
    register_auth_error_handlers(app)
    register_reservation_error_handlers(app)
    register_integration_error_handlers(app)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(reservations_router, prefix=API_V1_PREFIX)
    app.include_router(integrations_router, prefix=API_V1_PREFIX)

    # Before anything reads the body — see `app/core/http_limits.py` for why an in-endpoint
    # check is too late for an upload.
    app.add_middleware(
        MaxBodySizeMiddleware,
        path_prefixes=(f"{API_V1_PREFIX}/integrations/",),
        max_bytes_provider=lambda: settings.csv_import_max_bytes,
    )

    # Deliberately NOT under API_V1_PREFIX (design D2): the container healthcheck
    # in docker-compose.yml and docker-compose.deploy.yml probes /health, and the
    # frontend and worker services gate on it via depends_on.
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
