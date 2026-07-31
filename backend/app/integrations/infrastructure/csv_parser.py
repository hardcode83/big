"""CSV → `ReservationDTO`, row by row, reporting failures instead of raising (R4, design D11).

Two shapes of failure, deliberately different:

* The **file** is unusable (not UTF-8, missing required columns, too many rows) → raise. Nothing
  can be imported, so there is nothing to report per row.
* A **row** is unusable (bad date, non-numeric party) → return it as an error alongside the good
  rows. R4.2 is explicit: skip the row, continue, report its line number.

Line numbers are the ones a person sees in a spreadsheet — the header is line 1, so the first
data row is line 2. Reporting the zero-based index of the row within the data would be useless
for the human who has to fix the file.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation

from app.integrations.domain.dtos import ReservationDTO

# One cell can never be longer than this. The `csv` module's own default (131072) raises
# `_csv.Error`, which is neither a `ValueError` nor a `CsvFileError`, so it escaped as a 500 and
# took every valid row of the file with it — measured by the security review. Bounded here, and
# per-column widths below, so a hostile or merely sloppy cell becomes a reported row.
MAX_CELL_CHARS = 10_000

# Mirrors the column widths of PRD §7.6/§7.7 so a too-long value is a row error with a line
# number instead of an `asyncpg.StringDataRightTruncationError` that poisons the transaction.
MAX_LENGTHS = {
    "external_pms_id": 200,
    "external_channel_id": 200,
    "guest_name": 300,
    "guest_email": 255,
    "guest_phone": 30,
    "property_internal_code": 50,
    "channel": 50,
    "status": 50,
    "currency": 3,
    "special_requests": 5_000,
}
MAX_PARTY = 50
MAX_AMOUNT = Decimal("99999999.99")  # Numeric(10,2)

REQUIRED_COLUMNS = ("property_internal_code", "channel", "check_in_date", "check_out_date", "adults")
OPTIONAL_COLUMNS = (
    "external_pms_id",
    "external_channel_id",
    "guest_name",
    "guest_email",
    "guest_phone",
    "children",
    "check_in_time",
    "check_out_time",
    "gross_amount",
    "ota_commission",
    "currency",
    "status",
    "special_requests",
)


class CsvFileError(Exception):
    """The file cannot be parsed at all — nothing to report per row."""


class CsvTooLargeError(CsvFileError):
    """More rows than the configured limit (answered 413, not 422: it is about size)."""


@dataclass
class ParsedRow:
    line: int
    reservation: ReservationDTO


@dataclass
class RowFailure:
    line: int
    reason: str


@dataclass
class ParseResult:
    rows: list[ParsedRow]
    failures: list[RowFailure]


def parse_reservations_csv(raw: bytes, *, max_rows: int) -> ParseResult:
    text = _decode(raw)
    csv.field_size_limit(MAX_CELL_CHARS)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise CsvFileError("The file is empty")

    headers = {name.strip().lower() for name in reader.fieldnames if name}
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise CsvFileError(f"Missing required column(s): {', '.join(missing)}")

    rows: list[ParsedRow] = []
    failures: list[RowFailure] = []
    # `csv.Error` (a cell over `MAX_CELL_CHARS`, a malformed quote) is raised by the reader as it
    # advances, so the iteration itself has to be guarded — it is not a per-field failure.
    try:
        raw_rows = list(enumerate(reader, start=2))  # header is line 1
    except csv.Error as error:
        raise CsvFileError(f"The file could not be read as CSV: {error}") from error
    for index, raw_row in raw_rows:
        if len(rows) + len(failures) >= max_rows:
            raise CsvTooLargeError(f"The file has more than {max_rows} data rows")
        if None in raw_row:
            # `csv.DictReader` collects values past the last header under a `None` key, as a
            # list. That means the row has more columns than the header — a real data problem
            # (a stray comma inside an unquoted field, usually), and reporting it beats
            # importing a row whose values have silently shifted one column to the left.
            failures.append(
                RowFailure(
                    line=index,
                    reason=f"The row has more columns than the header ({len(reader.fieldnames or [])})",
                )
            )
            continue
        normalised = {
            (key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()
        }
        try:
            rows.append(ParsedRow(line=index, reservation=_to_dto(normalised)))
        except ValueError as error:
            failures.append(RowFailure(line=index, reason=str(error)))
    return ParseResult(rows=rows, failures=failures)


def _decode(raw: bytes) -> str:
    """UTF-8, BOM tolerated.

    `utf-8-sig` rather than `utf-8`: Excel writes a BOM, and without this the first header
    would come back as `\\ufeffproperty_internal_code` and the file would be rejected for a
    missing column it actually has.
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvFileError("The file must be UTF-8 encoded") from error


def _to_dto(row: dict[str, str]) -> ReservationDTO:
    _reject_control_characters(row)
    _reject_overlong_values(row)
    check_in = _date(row, "check_in_date")
    check_out = _date(row, "check_out_date")
    if check_out <= check_in:
        # Caught here as well as in the aggregate so the message names the columns the person
        # has to fix, instead of the domain's field names.
        raise ValueError("check_out_date must be after check_in_date")
    property_code = row.get("property_internal_code", "")
    if not property_code:
        raise ValueError("property_internal_code is required")
    channel = row.get("channel", "")
    if not channel:
        raise ValueError("channel is required")
    return ReservationDTO(
        external_id=row.get("external_pms_id", ""),
        channel=channel,
        property_external_id=property_code,
        external_channel_id=row.get("external_channel_id") or None,
        guest_name=row.get("guest_name") or None,
        guest_email=row.get("guest_email") or None,
        guest_phone=row.get("guest_phone") or None,
        check_in_date=check_in,
        check_out_date=check_out,
        check_in_time=_time(row, "check_in_time"),
        check_out_time=_time(row, "check_out_time"),
        adults=_int(row, "adults", default=1),
        children=_int(row, "children", default=0),
        gross_amount=_decimal(row, "gross_amount"),
        ota_commission=_decimal(row, "ota_commission"),
        currency=(row.get("currency") or "EUR").upper(),
        status=row.get("status") or None,
        special_requests=row.get("special_requests") or None,
        raw_payload=dict(row),
    )


def _reject_control_characters(row: dict[str, str]) -> None:
    """A NUL byte never reaches the database.

    Postgres refuses `\x00` in a text column with `CharacterNotInRepertoireError`, which aborted
    the whole transaction instead of just the offending row (measured by the security review of
    this change). Other control characters are harmless in these columns, so only NUL is refused.
    """
    for column, value in row.items():
        if "\x00" in value:
            raise ValueError(f"{column} contains a NUL byte")


def _reject_overlong_values(row: dict[str, str]) -> None:
    for column, limit in MAX_LENGTHS.items():
        value = row.get(column, "")
        if len(value) > limit:
            raise ValueError(f"{column} is longer than {limit} characters")


def _date(row: dict[str, str], column: str) -> date:
    value = row.get(column, "")
    if not value:
        raise ValueError(f"{column} is required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{column} must be an ISO date (YYYY-MM-DD), got {value!r}") from error


def _time(row: dict[str, str], column: str) -> time | None:
    value = row.get(column, "")
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{column} must be an ISO time (HH:MM), got {value!r}") from error


def _int(row: dict[str, str], column: str, *, default: int) -> int:
    value = row.get(column, "")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{column} must be a whole number, got {value!r}") from error
    if parsed < 0:
        raise ValueError(f"{column} cannot be negative")
    if parsed > MAX_PARTY:
        raise ValueError(f"{column} cannot be greater than {MAX_PARTY}")
    return parsed


def _decimal(row: dict[str, str], column: str) -> Decimal | None:
    value = row.get(column, "")
    if not value:
        return None
    try:
        parsed = Decimal(value.replace(",", "."))
        # `Decimal("nan")` and `Decimal("1E+999")` CONSTRUCT fine; it is the comparison and the
        # INSERT that blow up. Both checks therefore live inside the `try`, and `is_finite`
        # rejects NaN/Infinity before any comparison is attempted with them (both found by the
        # security review as escaping 500s).
        if not parsed.is_finite():
            raise ValueError(f"{column} must be a finite amount, got {value!r}")
        if parsed < 0:
            raise ValueError(f"{column} cannot be negative")
        if parsed > MAX_AMOUNT:
            raise ValueError(f"{column} cannot be greater than {MAX_AMOUNT}")
    except InvalidOperation as error:
        raise ValueError(f"{column} must be a decimal amount, got {value!r}") from error
    return parsed


class CsvReservationParser:
    """Adapter for the `ReservationCsvParser` port (design D1).

    A thin class around the function so the use case depends on a port instead of importing this
    module — the dependency rule the architecture review flagged. The function stays public
    because the parser tests exercise it directly.
    """

    def parse(self, raw: bytes, *, max_rows: int) -> ParseResult:
        return parse_reservations_csv(raw, max_rows=max_rows)
