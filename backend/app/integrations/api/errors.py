"""Maps this module's errors onto the PRD §23 envelope (R4.3, R4.4; `reservations-webhooks` R2).

`413` for a file that is too big and `422` for one that is malformed: the distinction is not
cosmetic — the first says "send less", the second "fix the contents", and a person uploading a
spreadsheet needs to know which.

The two webhook-endpoint errors follow the same principle. `409` says "there is already one, and
I did not touch it", which is the answer that keeps a live integration from being silently
replaced; `404` says nothing at all about whether the id exists in another tenant.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.integrations.domain.errors import (
    WebhookEndpointAlreadyExistsError,
    WebhookEndpointNotFoundError,
)
from app.integrations.infrastructure.csv_parser import CsvFileError, CsvTooLargeError


def register_integration_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WebhookEndpointAlreadyExistsError)
    async def _already_exists(
        _: Request, exc: WebhookEndpointAlreadyExistsError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409, content=error_envelope(ErrorCode.CONFLICT, str(exc))
        )

    @app.exception_handler(WebhookEndpointNotFoundError)
    async def _endpoint_absent(
        _: Request, exc: WebhookEndpointNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404, content=error_envelope(ErrorCode.NOT_FOUND, str(exc))
        )

    @app.exception_handler(CsvTooLargeError)
    async def _too_large(_: Request, exc: CsvTooLargeError) -> JSONResponse:
        return JSONResponse(
            status_code=413, content=error_envelope(ErrorCode.PAYLOAD_TOO_LARGE, str(exc))
        )

    @app.exception_handler(CsvFileError)
    async def _malformed(_: Request, exc: CsvFileError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=error_envelope(ErrorCode.VALIDATION_ERROR, str(exc))
        )
