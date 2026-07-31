"""Integration endpoints (PRD §16, §23, R4).

Only the CSV import for now. The PMS sync has no endpoint on purpose (design D10) and the
webhook receiver of PRD §16 is out of scope for this change — it needs the `WebhookEvent`
entity of `domain-foundation-financial` and the Celery job of `celery-jobs`, both unstarted.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth.api.dependencies import AuthenticatedRequest, now_utc, require
from app.auth.domain.policy import Permission
from app.core.config import settings
from app.integrations.api.dependencies import get_import_csv_use_case
from app.integrations.api.schemas import ImportReportResponse, RowErrorResponse
from app.integrations.application.use_cases import ImportReservationsFromCsvUseCase
from app.integrations.infrastructure.csv_parser import (
    CsvFileError,
    CsvTooLargeError,
    parse_reservations_csv,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

ACCEPTED_CONTENT_TYPES = frozenset(
    {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", ""}
)


@router.post(
    "/pms/import-csv",
    response_model=ImportReportResponse,
    summary="Import reservations from a CSV file",
    description=(
        "Manual alternative to the PMS integration. Valid rows are imported and invalid ones "
        "are reported with their line number — one bad row never costs the good ones. Rows "
        "carrying an `external_pms_id` already known to the tenant are updated, not "
        "duplicated. The property is named by its `internal_code` (e.g. REDES11)."
    ),
)
async def import_reservations_csv(
    authenticated: Annotated[
        AuthenticatedRequest, Depends(require(Permission.MANAGE_RESERVATIONS))
    ],
    use_case: Annotated[ImportReservationsFromCsvUseCase, Depends(get_import_csv_use_case)],
    file: Annotated[UploadFile, File(description="UTF-8 CSV with the documented columns")],
) -> ImportReportResponse:
    if file.content_type is not None and file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise CsvFileError(f"Unsupported content type {file.content_type!r}; expected CSV")

    # Read with a ceiling: `await file.read()` unbounded is how a 2 GB upload becomes an
    # out-of-memory kill instead of a 413 (rule 6 of `steering/security.md`). One byte over the
    # limit is enough to know the file is too big without holding all of it.
    limit = settings.csv_import_max_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise CsvTooLargeError(f"The file exceeds the {limit} byte limit")
    if not raw:
        raise CsvFileError("The file is empty")

    parsed = parse_reservations_csv(raw, max_rows=settings.csv_import_max_rows)
    report = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        rows=[row.reservation for row in parsed.rows],
        now=now_utc(),
    )
    return ImportReportResponse.from_report(
        report,
        parse_failures=[
            RowErrorResponse(line=failure.line, reason=failure.reason)
            for failure in parsed.failures
        ],
    )
