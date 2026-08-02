"""Maps CSV file-level errors onto the PRD §23 envelope (R4.3, R4.4).

`413` for a file that is too big and `422` for one that is malformed: the distinction is not
cosmetic — the first says "send less", the second "fix the contents", and a person uploading a
spreadsheet needs to know which.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.integrations.infrastructure.csv_parser import CsvFileError, CsvTooLargeError


def register_integration_error_handlers(app: FastAPI) -> None:
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
