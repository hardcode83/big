"""The `extra_forbidden` `loc` bound and the total entry-count cap (R1, R2, R3.1).

Every case drives a real `RequestValidationError` through a throwaway `extra="forbid"`
model and the actual `register_error_handlers` wiring — a hand-built dict would not
prove the fix survives Pydantic's real error shape.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import (
    _EXTRA_FORBIDDEN_LOC_MAX_LENGTH,
    _EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER,
    _MAX_SERIALISED_ERRORS,
    register_error_handlers,
)


class _LeafModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=5)


class _NestedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaf: _LeafModel


class _CollectionModel(BaseModel):
    """Same shape as the real pricing request schemas: an unbounded `list[dict[str, Any]]`
    with no `max_length`, so the caller — not the schema — decides how many errors a single
    request produces, and they are not `extra_forbidden`."""

    model_config = ConfigDict(extra="forbid")

    rules: list[dict[str, Any]]


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/leaf")
    async def _leaf(payload: _LeafModel) -> dict:
        return {}

    @app.post("/nested")
    async def _nested(payload: _NestedModel) -> dict:
        return {}

    @app.post("/collection")
    async def _collection(payload: _CollectionModel) -> dict:
        return {}

    return app


async def _post(app: FastAPI, path: str, json: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=json)


def _extra_forbidden_errors(response: httpx.Response) -> list[dict]:
    errors = response.json()["error"]["details"]["errors"]
    return [error for error in errors if error["type"] == "extra_forbidden"]


@pytest.mark.asyncio
async def test_a_5000_character_unknown_key_is_capped_with_the_marker() -> None:
    """The original probe: a 5,000-char unknown key must no longer size the body."""
    app = _build_app()
    long_key = "x" * 5000

    response = await _post(app, "/leaf", {"name": "ok", long_key: "value"})

    assert response.status_code == 422
    extra_forbidden = _extra_forbidden_errors(response)
    assert len(extra_forbidden) == 1
    last_segment = extra_forbidden[0]["loc"][-1]
    assert len(last_segment) == _EXTRA_FORBIDDEN_LOC_MAX_LENGTH
    assert last_segment.endswith(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)
    # The original unbounded probe produced a 5,182-byte body for a 5,000-char key; a
    # bounded body must stay small regardless of how large the caller-sent key is.
    assert len(response.content) < 1000


@pytest.mark.asyncio
async def test_an_unknown_key_at_the_cap_is_returned_unchanged() -> None:
    app = _build_app()
    key_at_cap = "y" * _EXTRA_FORBIDDEN_LOC_MAX_LENGTH

    response = await _post(app, "/leaf", {"name": "ok", key_at_cap: "value"})

    extra_forbidden = _extra_forbidden_errors(response)
    assert len(extra_forbidden) == 1
    assert extra_forbidden[0]["loc"][-1] == key_at_cap
    assert not extra_forbidden[0]["loc"][-1].endswith(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)


@pytest.mark.asyncio
async def test_string_too_long_loc_is_left_completely_unmodified() -> None:
    app = _build_app()
    long_value = "z" * 5000

    response = await _post(app, "/leaf", {"name": long_value})

    errors = response.json()["error"]["details"]["errors"]
    string_too_long = [error for error in errors if error["type"] == "string_too_long"]
    assert len(string_too_long) == 1
    assert string_too_long[0]["loc"] == ["body", "name"]


@pytest.mark.asyncio
async def test_missing_field_loc_is_left_completely_unmodified() -> None:
    app = _build_app()

    response = await _post(app, "/leaf", {})

    errors = response.json()["error"]["details"]["errors"]
    missing = [error for error in errors if error["type"] == "missing"]
    assert len(missing) == 1
    assert missing[0]["loc"] == ["body", "name"]


@pytest.mark.asyncio
async def test_nested_extra_forbidden_caps_only_the_final_segment() -> None:
    app = _build_app()
    long_key = "n" * 5000

    response = await _post(app, "/nested", {"leaf": {"name": "ok", long_key: "value"}})

    extra_forbidden = _extra_forbidden_errors(response)
    assert len(extra_forbidden) == 1
    loc = extra_forbidden[0]["loc"]
    assert loc[:-1] == ["body", "leaf"]
    assert len(loc[-1]) == _EXTRA_FORBIDDEN_LOC_MAX_LENGTH
    assert loc[-1].endswith(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)


@pytest.mark.asyncio
async def test_loc_stays_a_list_of_str_of_the_same_length() -> None:
    app = _build_app()
    long_key = "m" * 5000

    response = await _post(app, "/leaf", {"name": "ok", long_key: "value"})

    extra_forbidden = _extra_forbidden_errors(response)
    loc = extra_forbidden[0]["loc"]
    assert isinstance(loc, list)
    assert len(loc) == 2  # ["body", "<key>"]
    assert all(isinstance(part, str) for part in loc)


@pytest.mark.asyncio
async def test_many_distinct_unknown_keys_do_not_scale_the_response() -> None:
    """Scaled-down reproduction of the panel's probe: 300 distinct unknown keys must
    still produce a small, bounded body, not one proportional to the key count."""
    app = _build_app()
    payload = {"name": "ok", **{f"unknown_{i}": "value" for i in range(300)}}

    response = await _post(app, "/leaf", payload)

    assert response.status_code == 422
    extra_forbidden = _extra_forbidden_errors(response)
    assert len(extra_forbidden) == _MAX_SERIALISED_ERRORS
    errors = response.json()["error"]["details"]["errors"]
    omitted = [error for error in errors if error["type"] == "errors_omitted"]
    assert len(omitted) == 1
    assert "280" in omitted[0]["msg"]  # 300 sent - 20 kept = 280 omitted
    # The original unbounded probe scaled linearly with key count; a bounded body must
    # stay small regardless of how many distinct unknown keys the caller sends.
    assert len(response.content) < 3000


@pytest.mark.asyncio
async def test_a_genuine_error_survives_alongside_capped_unknown_keys() -> None:
    """The cap must not swallow the errors the caller actually needs to see: a real schema
    violation is still reported when unknown keys exhaust the entry cap."""
    app = _build_app()
    payload = {f"unknown_{i}": "value" for i in range(30)}  # no `name` → one `missing`

    response = await _post(app, "/leaf", payload)

    errors = response.json()["error"]["details"]["errors"]
    missing = [error for error in errors if error["type"] == "missing"]
    assert len(missing) == 1
    assert missing[0]["loc"] == ["body", "name"]
    # 31 errors, 20 kept (1 `missing` + 19 `extra_forbidden`) plus the summary entry.
    assert len(_extra_forbidden_errors(response)) == _MAX_SERIALISED_ERRORS - 1
    omitted = [error for error in errors if error["type"] == "errors_omitted"]
    assert len(omitted) == 1
    assert "11" in omitted[0]["msg"]  # 31 errors - 20 kept = 11 omitted
    assert len(errors) == _MAX_SERIALISED_ERRORS + 1


@pytest.mark.asyncio
async def test_many_errors_of_a_non_extra_forbidden_type_do_not_scale_the_response() -> None:
    """The count cap is on the total, not on `extra_forbidden`: an unbounded collection
    field lets a caller drive the error count with a type the schema's field count does not
    bound at all (the measured `dict_type` vector on the pricing request schemas)."""
    app = _build_app()

    response = await _post(app, "/collection", {"rules": ["not-a-dict"] * 80})

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    dict_type = [error for error in errors if error["type"] == "dict_type"]
    assert len(dict_type) == _MAX_SERIALISED_ERRORS
    assert dict_type[0]["loc"] == ["body", "rules", "0"]  # schema-derived, untouched
    omitted = [error for error in errors if error["type"] == "errors_omitted"]
    assert len(omitted) == 1
    assert "60" in omitted[0]["msg"]  # 80 sent - 20 kept = 60 omitted
    # Bounded regardless of how many invalid items the caller sent.
    assert len(response.content) < 3000


@pytest.mark.asyncio
async def test_a_genuinely_truncated_key_is_distinguishable_from_a_forged_one() -> None:
    """A key ending in the marker string but at/under the cap must not be mistaken for a
    genuinely truncated one — the ambiguity a caller could otherwise exploit."""
    app = _build_app()
    forged_key = "z" * 80 + _EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER  # 94 chars, <= cap
    assert len(forged_key) <= _EXTRA_FORBIDDEN_LOC_MAX_LENGTH
    genuinely_long_key = "w" * 5000

    forged_response = await _post(app, "/leaf", {"name": "ok", forged_key: "value"})
    truncated_response = await _post(app, "/leaf", {"name": "ok", genuinely_long_key: "value"})

    forged_error = _extra_forbidden_errors(forged_response)[0]
    truncated_error = _extra_forbidden_errors(truncated_response)[0]

    assert forged_error["loc"][-1] == forged_key
    assert forged_error["loc"][-1].endswith(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)
    assert "loc_truncated" not in forged_error

    assert truncated_error["loc"][-1].endswith(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)
    assert truncated_error.get("loc_truncated") is True
