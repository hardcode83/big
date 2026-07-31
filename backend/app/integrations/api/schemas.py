"""Response DTOs for the integration endpoints (R4.1, PRD §23)."""

from pydantic import BaseModel

from app.integrations.application.ingest import IngestReport


class RowErrorResponse(BaseModel):
    """One row the import could not take, with what a person needs to fix it."""

    line: int | None = None
    reference: str | None = None
    reason: str


class ImportReportResponse(BaseModel):
    """What the import did, per outcome (R4.1, R4.2).

    `created` and `updated` are separate because that difference is the observable proof of
    idempotency: importing the same file twice must show `created: 0` the second time.
    """

    created: int
    updated: int
    skipped: int
    errors: list[RowErrorResponse]

    @classmethod
    def from_report(
        cls, report: IngestReport, *, parse_failures: list[RowErrorResponse] | None = None
    ) -> "ImportReportResponse":
        failures = list(parse_failures or [])
        return cls(
            created=report.created,
            updated=report.updated,
            skipped=report.skipped + len(failures),
            errors=failures
            + [
                RowErrorResponse(reference=error.reference or None, reason=error.reason)
                for error in report.errors
            ],
        )
