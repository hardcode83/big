"""Contract of GET /version (change app-version-visibility, R2.1-R2.6).

Same shape as test_health.py: an ASGI transport over the module-level `app`, no
database and no Redis — which is also the property under test, since an operator has
to be able to read the deployed version while the rest of the stack is down.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import VersionResponse, app, create_app

_BAKED = {
    "app_version": "0.1.0+2026-07-30.a2f3c1d",
    "build_commit": "a2f3c1d3f9b2000000000000000000000000000f",
    "build_pr": 42,
    "built_at": "2026-07-30T09:14:02Z",
    "build_run_id": "1234567890",
    "build_ref": "main",
}


async def _get(path: str, target=None) -> tuple[int, dict]:
    transport = ASGITransport(app=target or app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_version_reports_the_baked_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patching the settings instance the route reads, rather than the environment: the
    # module-level `settings` was already built at import time.
    import app.main as main_module

    monkeypatch.setattr(
        main_module, "settings", Settings(_env_file=None, jwt_secret_key="0" * 64, **_BAKED)
    )

    status, body = await _get("/version", create_app())

    assert status == 200
    assert body == {
        "version": "0.1.0+2026-07-30.a2f3c1d",
        "commit": "a2f3c1d3f9b2000000000000000000000000000f",
        "pr": 42,
        "built_at": "2026-07-30T09:14:02Z",
        "run_id": "1234567890",
        "ref": "main",
    }


@pytest.mark.asyncio
async def test_version_answers_with_nulls_when_nothing_was_baked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An image built without build-args (local `docker compose build`) must still answer
    # 200 with an honest "no identity here" instead of failing (R2.6).
    import app.main as main_module

    monkeypatch.setattr(
        main_module, "settings", Settings(_env_file=None, jwt_secret_key="0" * 64)
    )

    status, body = await _get("/version", create_app())

    assert status == 200
    assert body == {
        "version": None,
        "commit": None,
        "pr": None,
        "built_at": None,
        "run_id": None,
        "ref": None,
    }


@pytest.mark.asyncio
async def test_version_needs_no_authentication() -> None:
    # R2.5: no Authorization header, and the response must not be a 401/403. The
    # structural counterpart of this is the allowlist entry in
    # test_route_authorization.py, which is what makes the exemption a visible decision.
    status, _ = await _get("/version")

    assert status == 200


@pytest.mark.asyncio
async def test_version_exposes_no_field_beyond_the_declared_six() -> None:
    # R2.5, schema half: `response_model=VersionResponse` is what stops a new field from
    # reaching an anonymous caller. This does bite on the module-level app, because the
    # KEY SET does not depend on whether anything was baked.
    _, body = await _get("/version")

    assert set(body) == {"version", "commit", "pr", "built_at", "run_id", "ref"}


@pytest.mark.asyncio
async def test_version_leaks_no_repository_url_even_when_one_is_baked_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # R2.5, value half. Asserting this against the module-level `app` would be VACUOUS:
    # its settings are built at import from an environment where nothing is baked, so the
    # body is all-None and no substring assertion on it can ever fail. The repo-shaped
    # values have to be baked in for the assertion to mean anything — this is what would
    # catch a later change that smuggled a repository URL inside a `ref` or a version
    # string, which is a value-level leak the response_model cannot stop.
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            _env_file=None,
            jwt_secret_key="0" * 64,
            app_version="0.1.0+2026-07-30.a2f3c1d",
            build_commit="a2f3c1d3f9b2000000000000000000000000000f",
            build_pr=42,
            built_at="2026-07-30T09:14:02Z",
            build_run_id="1234567890",
            build_ref="refs/heads/main",
        ),
    )

    _, body = await _get("/version", create_app())

    assert "github.com" not in str(body)
    assert "autohostai-labs" not in str(body)
    # And the PR is the number, never a title.
    assert body["pr"] == 42


def test_version_response_serialises_absent_fields_as_null() -> None:
    # Guards the choice of `str | None` over `str`: a caller has to be able to tell "not
    # baked" from "empty string". A default-of-"" refactor would silently break that.
    assert VersionResponse(
        version=None, commit=None, pr=None, built_at=None, run_id=None, ref=None
    ).model_dump() == {
        "version": None,
        "commit": None,
        "pr": None,
        "built_at": None,
        "run_id": None,
        "ref": None,
    }


@pytest.mark.asyncio
async def test_health_contract_is_untouched() -> None:
    # R2.4: /health is probed by the container healthcheck of both composes and gated on
    # by `depends_on` for frontend and worker. Adding /version must not have changed it.
    status, body = await _get("/health")

    assert status == 200
    assert body == {"status": "ok"}
