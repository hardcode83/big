from fastapi import FastAPI
from pydantic import BaseModel

# Imported for its side effect: every domain's models must be registered before the
# first request, or the global tenant filter (design D16) silently covers fewer
# tables than it should — see app/core/models_registry.py.
import app.core.models_registry  # noqa: F401
from app.auth.api.errors import register_auth_error_handlers
from app.auth.api.router import router as auth_router
from app.core.config import settings
from app.core.errors import register_error_handlers

API_V1_PREFIX = "/api/v1"


class VersionResponse(BaseModel):
    """Build identity of the running image (change app-version-visibility, R2.1).

    A field that was not baked serialises as `null`, never as `""`: the caller has to be
    able to tell "this image carries no build identity" from "the value is empty".

    snake_case like the rest of the API (PRD §23, cf. `TokenPairResponse`). No field is
    sensitive — this response is anonymous on purpose (R2.5) — and it deliberately
    carries neither the repository URL nor the Pull Request title, only its number.
    """

    version: str | None
    commit: str | None
    pr: int | None
    built_at: str | None
    run_id: str | None
    ref: str | None


def create_app() -> FastAPI:
    app = FastAPI(title="AutoHostAI backend")
    register_error_handlers(app)
    register_auth_error_handlers(app)
    app.include_router(auth_router, prefix=API_V1_PREFIX)

    # Deliberately NOT under API_V1_PREFIX (design D2): the container healthcheck
    # in docker-compose.yml and docker-compose.deploy.yml probes /health, and the
    # frontend and worker services gate on it via depends_on.
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Alongside /health and outside API_V1_PREFIX for the same class of reason
    # (design D4): this reports the version of the *build*, not of the API — the API is
    # versioned by the /api/v1 prefix itself. It is also the one route that must answer
    # when the rest of the system cannot: it touches neither the database nor Redis, so
    # an operator can still read it while Postgres is down (R2.3).
    #
    # Anonymous by design (R2.5). That exemption is declared in the allowlist of
    # tests/test_route_authorization.py, which is what keeps it a visible decision
    # instead of an oversight.
    @app.get(
        "/version",
        response_model=VersionResponse,
        summary="Build identity of the running image",
        description=(
            "Version string, commit, Pull Request number, build timestamp, CI run id "
            "and ref baked into this image at build time. Unbaked fields are null."
        ),
    )
    async def version() -> VersionResponse:
        return VersionResponse(
            version=settings.app_version or None,
            commit=settings.build_commit or None,
            pr=settings.build_pr,
            built_at=settings.built_at or None,
            run_id=settings.build_run_id or None,
            ref=settings.build_ref or None,
        )

    return app


app = create_app()
