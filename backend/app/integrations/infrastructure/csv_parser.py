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
from collections.abc import Iterator
from datetime import date, time
from decimal import Decimal, InvalidOperation

from app.integrations.domain.dtos import ParsedRow, ParseResult, ReservationDTO, RowFailure

# One cell can never be longer than this. The `csv` module's own default (131072) raises
# `_csv.Error`, which is neither a `ValueError` nor a `CsvFileError`, so it escaped as a 500 and
# took every valid row of the file with it — measured by the security review. Bounded here, and
# per-column widths below, so a hostile or merely sloppy cell becomes a reported row.
MAX_CELL_CHARS = 10_000
# A whole physical line. Bounded separately from a cell because it is what can be checked BEFORE
# the tokeniser runs, which is what lets an oversized row be skipped instead of killing the file.
MAX_LINE_CHARS = 20_000

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


def parse_reservations_csv(raw: bytes, *, max_rows: int) -> ParseResult:
    # `field_size_limit` is process-global interpreter state, so it is restored afterwards rather
    # than left lowered for every other CSV reader in the process (raised by the security review
    # as an informational point).
    previous_field_limit = csv.field_size_limit(MAX_LINE_CHARS)
    try:
        return _parse(_text_stream(raw), max_rows=max_rows)
    finally:
        csv.field_size_limit(previous_field_limit)


def _text_stream(raw: bytes) -> io.TextIOBase:
    """Decode lazily, over the bytes we already hold.

    Not `io.StringIO(raw.decode(...))`: that materialises the whole file a second time as a `str`
    and then copies it again into the buffer. Reading through a `TextIOWrapper` decodes in chunks as
    the reader advances, which is what keeps the transient cost of a file at the byte ceiling
    proportional instead of a multiple — the security review measured the difference.
    """
    try:
        # `utf-8-sig` strips Excel's BOM; see the note that used to live in `_decode`.
        return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
    except UnicodeDecodeError as error:  # pragma: no cover - raised on read, not on construction
        raise CsvFileError("The file must be UTF-8 encoded") from error


def _bounded_lines(
    stream: io.TextIOBase, dropped: list[RowFailure], fed_lines: list[int]
) -> "Iterator[str]":
    """Yield the file's lines, dropping any that is too long — as a ROW failure.

    This is the difference between "the file is unusable" and "one row is unusable", and R4.2 only
    accepts the second reading: *"omitir esa fila, continuar con el resto"*. D11 rejects the other
    one by name ("Rejected: abortar todo el fichero al primer error").

    A previous version let the oversized cell reach `csv.reader`, which raises `csv.Error` and
    cannot resume — so a single 20 000-character cell anywhere in the file made the whole upload
    return `422` with **zero** rows imported, losing every good row around it. The QA review
    measured exactly that. Bounding the physical line before the tokeniser ever sees it keeps the
    reader alive for the rest of the file.

    `fed_lines` records the physical line number of each line actually handed to the reader, so a
    record's line number stays truthful even after lines have been dropped (`reader.line_num`
    counts what it saw, not what the file contains).
    """
    for physical_line, line in enumerate(stream, start=1):
        if len(line) > MAX_LINE_CHARS:
            dropped.append(
                RowFailure(
                    line=physical_line,
                    reason=f"The row is longer than {MAX_LINE_CHARS} characters",
                )
            )
            continue
        fed_lines.append(physical_line)
        yield line


def _parse(stream: io.TextIOBase, *, max_rows: int) -> ParseResult:
    dropped: list[RowFailure] = []
    fed_lines: list[int] = []
    reader = csv.DictReader(_bounded_lines(stream, dropped, fed_lines))
    try:
        fieldnames = reader.fieldnames
    except UnicodeDecodeError as error:
        raise CsvFileError("The file must be UTF-8 encoded") from error
    if fieldnames is None:
        raise CsvFileError("The file is empty")

    headers = {name.strip().lower() for name in fieldnames if name}
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise CsvFileError(f"Missing required column(s): {', '.join(missing)}")

    rows: list[ParsedRow] = []
    failures: list[RowFailure] = []
    # Streamed, one row at a time. An earlier version hoisted this into `list(enumerate(reader))`
    # to guard `csv.Error` in one place, and the security review measured what that cost: a 10 MiB
    # file — inside the configured byte limit — built 283 000 rows and 200 MiB of heap before the
    # `max_rows` ceiling was ever consulted. Guarding each step of the iteration instead keeps the
    # ceiling meaningful: nothing past row `max_rows` is ever constructed.
    rows_iterator = iter(reader)
    while True:
        try:
            raw_row = next(rows_iterator)
        except StopIteration:
            break
        except UnicodeDecodeError as error:
            # The decode happens as the reader advances now, so a non-UTF-8 file surfaces here.
            raise CsvFileError("The file must be UTF-8 encoded") from error
        except csv.Error as error:
            # Lines are bounded before the tokeniser sees them, so this is no longer the
            # oversized-cell path: what remains is a structurally unparseable file (an unbalanced
            # quote swallowing the rest of it), where there is genuinely no next row to move on to.
            raise CsvFileError(f"The file could not be read as CSV: {error}") from error
        # The physical line this record ended on, which is what a person looks for in the file.
        index = fed_lines[min(reader.line_num, len(fed_lines)) - 1] if fed_lines else 1
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
    # `dropped` is filled BY the generator as the loop consumes it, so it can only be merged once
    # the loop is over — reading it before iterating gave an empty list and silently swallowed
    # every over-long row. Sorted so the report reads in file order.
    failures.extend(dropped)
    failures.sort(key=lambda failure: failure.line)
    return ParseResult(rows=rows, failures=failures)


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
        currency=_currency(row),
        status=row.get("status") or None,
        special_requests=row.get("special_requests") or None,
        raw_payload=dict(row),
    )


def _currency(row: dict[str, str]) -> str:
    """Exactly three ASCII letters, checked AFTER normalising.

    `_reject_overlong_values` bounds the raw cell, but `.upper()` can make a string LONGER —
    `"ß".upper()` is `"SS"`, `"ﬄ".upper()` is `"FFL"` — so a 2-character cell could still produce
    6 characters for a `varchar(3)` column and abort the whole transaction with a
    `StringDataRightTruncationError`. Measured by the security review in its verification round:
    the outgoing value is what has to satisfy the column, not the incoming one.

    An explicit ISO-4217 shape (three ASCII letters) rather than a bare length check, because
    that is what the column and the API schema (`^[A-Z]{3}$`) both mean by a currency.
    """
    raw = row.get("currency", "")
    if not raw:
        return "EUR"
    normalised = raw.strip().upper()
    if len(normalised) != 3 or not normalised.isascii() or not normalised.isalpha():
        raise ValueError(f"currency must be a 3-letter code, got {raw!r}")
    return normalised


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
