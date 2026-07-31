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
    def from_report(cls, report: IngestReport) -> "ImportReportResponse":
        """Every error already carries its line when the source had one (R4.2).

        The use case merges the rows the parser rejected with the rows the ingest rejected, so
        this is a straight mapping — earlier it stitched the two lists together here, which is
        how the ingest-level errors ended up without a line number.
        """
        return cls(
            created=report.created,
            updated=report.updated,
            skipped=report.skipped,
            errors=[
                RowErrorResponse(line=error.line, reference=error.reference, reason=error.reason)
                for error in report.errors
            ],
        )
