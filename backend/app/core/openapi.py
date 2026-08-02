"""Makes the published OpenAPI describe the errors this API actually returns.

FastAPI derives the contract from the route signatures, so it never learns about the
handlers in `app/core/errors.py`: it documents every `422` with its own
`HTTPValidationError` (`{"detail": [...]}`), a shape this backend does not return
anywhere. `frontend/lib/api/errors.ts` only recognises the PRD §23 envelope and
degrades anything else to `UNKNOWN_ERROR`, so the generated contract was actively
misleading about the error path of all 18 endpoints.

The correction is applied here, post-generation, rather than as `responses=` on each
route decorator (design D7): FastAPI injects that `422` automatically as soon as an
endpoint has a validated body or parameter, so a per-decorator fix would be forgotten
by endpoint 19. One control point covers the routes of today and those to come.

What is deliberately NOT done here (design D8): inventing per-endpoint catalogues of
`404`/`409`/`429`. Declaring a plausible-but-unverified set would replace today's lie
with a different one. An endpoint that wants to declare its own says so in its
`responses=`, and this module keeps it pointing at the envelope.
"""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

from app.core.error_codes import ErrorCode

ENVELOPE_SCHEMA_NAME = "ErrorEnvelope"

# Emitted by FastAPI for its own validation error shape. Both become unreferenced once
# every `422` points at the envelope, and an unreferenced schema in a published contract
# is an invitation to generate a client type nothing will ever return.
_FASTAPI_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")

_ENVELOPE_REF = {"$ref": f"#/components/schemas/{ENVELOPE_SCHEMA_NAME}"}


class ErrorBody(BaseModel):
    """The `error` object of the PRD §23 envelope."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """Mirror of `app.core.errors.error_envelope()` — the only error shape this API emits.

    `code` is typed as `ErrorCode` on purpose (design D11): it publishes the catalogue of
    codes as an enum, so a consumer can switch over it exhaustively with its compiler's
    help. `app/core/error_codes.py` is the single source of truth that keeps that
    catalogue from going stale.
    """

    error: ErrorBody


# Declared by every router whose routes hang off `require(...)`, and by the individual
# authenticated routes of the `auth` router — `login` and `refresh` are anonymous by
# design (they are the endpoints that mint credentials) and must not claim a 401.
#
# These two and no more (design D8): a per-endpoint catalogue of the 404/409/429 an
# operation *might* return would be plausible rather than verified, which is the defect
# this module exists to remove, not to relocate.
AUTHENTICATED_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorEnvelope,
        "description": "Missing, malformed or expired credentials.",
    },
    403: {
        "model": ErrorEnvelope,
        "description": "Authenticated, but the role lacks the required permission.",
    },
}


def _envelope_schemas() -> dict[str, Any]:
    """The envelope and everything it references, flattened for `components.schemas`."""
    schema = ErrorEnvelope.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    nested = schema.pop("$defs", {})
    return {ENVELOPE_SCHEMA_NAME: schema, **nested}


def _point_errors_at_envelope(schema: dict[str, Any]) -> None:
    """Rewrite every documented 4xx/5xx JSON response to reference the envelope."""
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for status_code, response in operation.get("responses", {}).items():
                if not str(status_code)[:1] in {"4", "5"}:
                    continue
                content = response.get("content")
                if not content:
                    # A declared error response with no body (rare, but valid): leave it
                    # alone rather than inventing one.
                    continue
                for media_type in content.values():
                    media_type["schema"] = dict(_ENVELOPE_REF)


def _drop_orphaned_validation_schemas(schema: dict[str, Any]) -> None:
    """Remove FastAPI's validation schemas, but only once nothing references them.

    Unconditionally popping them by name is what this did first, and it is a trap: a
    future domain model legitimately named `ValidationError` would be deleted while its
    `$ref` survived, publishing a dangling reference in the committed artifact — a
    contract that generates a client type for a schema that is not there.

    Order matters: `HTTPValidationError` references `ValidationError`, so the outer one
    must go first for the inner one to look orphaned.
    """
    components = schema.get("components", {}).get("schemas", {})
    for name in _FASTAPI_VALIDATION_SCHEMAS:
        if name not in components:
            continue
        without_its_own_definition = {
            key: value for key, value in components.items() if key != name
        }
        elsewhere = {**schema, "components": {"schemas": without_its_own_definition}}
        if f"#/components/schemas/{name}" in json.dumps(elsewhere):
            continue
        components.pop(name)


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """The application's OpenAPI document, with the error contract corrected."""
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description or None,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("schemas", {}).update(
        _envelope_schemas()
    )
    _point_errors_at_envelope(schema)
    _drop_orphaned_validation_schemas(schema)
    return schema


def install_openapi(app: FastAPI) -> None:
    """Replace `app.openapi` so `/openapi.json`, `/docs` and the exported file agree.

    Without this the served document and `backend/openapi.json` would be two different
    contracts, which is the failure mode the export exists to prevent.
    """

    def _openapi() -> dict[str, Any]:
        if not app.openapi_schema:
            app.openapi_schema = build_openapi(app)
        return app.openapi_schema

    app.openapi = _openapi  # type: ignore[method-assign]
