"""Every handled failure must speak the PRD §23 envelope (R6.2, design D11).

`frontend/lib/api/errors.ts:isApiErrorEnvelope` recognises only this shape; a
response that deviates arrives at the client as UNKNOWN_ERROR with the real
message lost, silently.
"""

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.errors import (
    ForbiddenError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from app.main import create_app


class _Body(BaseModel):
    quantity: int


def _app_raising(exc: Exception):
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    @app.post("/echo")
    async def echo(body: _Body) -> dict[str, int]:
        return {"quantity": body.quantity}

    return app


async def _get(app, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        if kwargs.get("json") is not None:
            return await client.post(path, json=kwargs["json"])
        return await client.get(path)


def _assert_envelope(payload: object, code: str) -> None:
    assert isinstance(payload, dict)
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) >= {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (InvalidCredentialsError("Invalid email or password"), 401, "INVALID_CREDENTIALS"),
        (InvalidTokenError("Token is not valid"), 401, "INVALID_TOKEN"),
        (ForbiddenError("Role is not allowed to perform this action"), 403, "FORBIDDEN"),
        (NotFoundError("Resource does not exist"), 404, "NOT_FOUND"),
        (ValidationFailedError("Password is too long"), 422, "VALIDATION_ERROR"),
        (RateLimitedError("Too many login attempts"), 429, "RATE_LIMITED"),
    ],
)
async def test_app_errors_render_the_envelope(exc: Exception, status: int, code: str) -> None:
    response = await _get(_app_raising(exc), "/boom")

    assert response.status_code == status
    _assert_envelope(response.json(), code)


@pytest.mark.asyncio
async def test_fastapi_validation_errors_are_reshaped_into_the_envelope() -> None:
    # Without the RequestValidationError handler this body would be
    # `{"detail": [...]}` — not the envelope.
    response = await _get(_app_raising(NotFoundError("unused")), "/echo", json={"quantity": "abc"})

    assert response.status_code == 422
    payload = response.json()
    _assert_envelope(payload, "VALIDATION_ERROR")
    assert payload["error"]["details"]["errors"], "validation details must survive"


@pytest.mark.asyncio
async def test_raised_http_exceptions_are_reshaped_into_the_envelope() -> None:
    response = await _get(_app_raising(HTTPException(status_code=403, detail="nope")), "/boom")

    assert response.status_code == 403
    _assert_envelope(response.json(), "FORBIDDEN")


@pytest.mark.asyncio
async def test_unmatched_route_renders_the_envelope() -> None:
    response = await _get(create_app(), "/does-not-exist")

    assert response.status_code == 404
    _assert_envelope(response.json(), "NOT_FOUND")


@pytest.mark.asyncio
async def test_error_messages_stay_in_english() -> None:
    response = await _get(_app_raising(InvalidCredentialsError("Invalid email or password")), "/boom")

    assert response.json()["error"]["message"] == "Invalid email or password"
