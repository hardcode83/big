"""The CSV parser: what it accepts, what it reports per row, what it refuses outright (R4)."""

from datetime import date, time
from decimal import Decimal

import pytest

from app.integrations.infrastructure.csv_parser import (
    CsvFileError,
    CsvTooLargeError,
    parse_reservations_csv,
)

HEADER = (
    "property_internal_code,channel,check_in_date,check_out_date,adults,"
    "guest_name,guest_email,gross_amount,ota_commission,external_pms_id\n"
)
GOOD_ROW = "REDES11,AIRBNB,2026-08-01,2026-08-04,2,John Smith,john@example.com,350.00,52.50,PMS-1\n"


def _parse(body: str, *, max_rows: int = 1000):
    return parse_reservations_csv(body.encode("utf-8"), max_rows=max_rows)


class TestHappyPath:
    def test_it_maps_a_row_onto_the_dto(self) -> None:
        result = _parse(HEADER + GOOD_ROW)

        assert result.failures == []
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.line == 2  # the header is line 1, as a person sees it
        dto = row.reservation
        assert dto.property_external_id == "REDES11"
        assert dto.channel == "AIRBNB"
        assert dto.check_in_date == date(2026, 8, 1)
        assert dto.check_out_date == date(2026, 8, 4)
        assert dto.adults == 2
        assert dto.guest_email == "john@example.com"
        assert dto.gross_amount == Decimal("350.00")
        assert dto.external_id == "PMS-1"
        assert dto.raw_payload["channel"] == "AIRBNB"

    def test_a_bom_from_excel_does_not_break_the_first_column(self) -> None:
        raw = ("﻿" + HEADER + GOOD_ROW).encode("utf-8")

        result = parse_reservations_csv(raw, max_rows=10)

        assert len(result.rows) == 1

    def test_optional_columns_may_be_absent_entirely(self) -> None:
        result = _parse(
            "property_internal_code,channel,check_in_date,check_out_date,adults\n"
            "REDES11,DIRECT,2026-08-01,2026-08-03,1\n"
        )

        assert len(result.rows) == 1
        assert result.rows[0].reservation.guest_email is None
        assert result.rows[0].reservation.currency == "EUR"

    def test_times_and_quoted_comma_decimals_are_accepted(self) -> None:
        """A Spanish spreadsheet writes 120,50 — quoted, as any CSV writer must."""
        result = _parse(
            "property_internal_code,channel,check_in_date,check_out_date,adults,check_in_time,gross_amount\n"
            'REDES11,DIRECT,2026-08-01,2026-08-03,1,16:30,"120,50"\n'
        )

        dto = result.rows[0].reservation
        assert dto.check_in_time == time(16, 30)
        assert dto.gross_amount == Decimal("120.50")

    def test_an_unquoted_comma_decimal_is_reported_not_silently_shifted(self) -> None:
        """Without the column-count check the row would import with every value one column
        to the left — `adults` reading a time, `gross_amount` reading `120`."""
        result = _parse(
            "property_internal_code,channel,check_in_date,check_out_date,adults,check_in_time,gross_amount\n"
            "REDES11,DIRECT,2026-08-01,2026-08-03,1,16:30,120,50\n"
        )

        assert result.rows == []
        assert len(result.failures) == 1
        assert "more columns than the header" in result.failures[0].reason


class TestPerRowFailures:
    @pytest.mark.parametrize(
        "row,expected_in_reason",
        [
            ("REDES11,AIRBNB,not-a-date,2026-08-04,2,,,,,\n", "check_in_date"),
            ("REDES11,AIRBNB,2026-08-04,2026-08-01,2,,,,,\n", "check_out_date"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-01,2,,,,,\n", "check_out_date"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,many,,,,,\n", "adults"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,-1,,,,,\n", "adults"),
            (",AIRBNB,2026-08-01,2026-08-04,2,,,,,\n", "property_internal_code"),
            ("REDES11,,2026-08-01,2026-08-04,2,,,,,\n", "channel"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,2,,,not-money,,\n", "gross_amount"),
        ],
    )
    def test_a_bad_row_is_reported_with_its_line(self, row: str, expected_in_reason: str) -> None:
        result = _parse(HEADER + row)

        assert result.rows == []
        assert len(result.failures) == 1
        assert result.failures[0].line == 2
        assert expected_in_reason in result.failures[0].reason

    def test_good_rows_survive_a_bad_one(self) -> None:
        """R4.2: one broken row must not cost the rest of the file."""
        result = _parse(
            HEADER
            + GOOD_ROW
            + "REDES11,AIRBNB,broken,2026-08-04,2,,,,,\n"
            + "REDES11,DIRECT,2026-09-01,2026-09-05,1,,,,,\n"
        )

        assert [row.line for row in result.rows] == [2, 4]
        assert [failure.line for failure in result.failures] == [3]


class TestFileLevelFailures:
    def test_a_missing_required_column_is_a_file_error(self) -> None:
        with pytest.raises(CsvFileError) as raised:
            _parse("property_internal_code,channel\nREDES11,AIRBNB\n")

        assert "check_in_date" in str(raised.value)

    def test_an_empty_file_is_a_file_error(self) -> None:
        with pytest.raises(CsvFileError):
            _parse("")

    def test_a_non_utf8_file_is_a_file_error(self) -> None:
        with pytest.raises(CsvFileError):
            parse_reservations_csv("REDES11;ñ".encode("latin-1"), max_rows=10)

    def test_too_many_rows_is_its_own_error(self) -> None:
        """Distinct from a malformed file: the answer is `413`, not `422`."""
        with pytest.raises(CsvTooLargeError):
            _parse(HEADER + GOOD_ROW * 5, max_rows=3)


class TestRecordBudget:
    """A record over budget costs that record, never the file (R4.2, D11).

    Three shapes, because three successive fixes each closed one and left another open — the
    history is in `_bounded_lines`' docstring. All three were measured by the review panel or while
    verifying its findings.
    """

    HEADER_WITH_NOTES = (
        "property_internal_code,channel,check_in_date,check_out_date,adults,special_requests\n"
    )

    def _row(self, note: str, day: int = 1) -> str:
        return f"REDES11,AIRBNB,2026-08-0{day},2026-08-1{day},2,{note}\n"

    def test_one_very_long_physical_line_only_costs_its_own_row(self) -> None:
        body = (
            self.HEADER_WITH_NOTES
            + self._row("Ana", 1)
            + f'REDES11,AIRBNB,2026-08-05,2026-08-08,2,{"X" * 20_001}\n'
            + self._row("Bob", 2)
            + self._row("Cara", 3)
        )

        result = _parse(body)

        assert [row.reservation.special_requests for row in result.rows] == ["Ana", "Bob", "Cara"]
        assert [failure.line for failure in result.failures] == [3]

    def test_a_quoted_field_spread_over_short_lines_only_costs_its_own_row(self) -> None:
        """The shape a physical-line bound missed: no single line is long, the record is.

        And the shape that a record bound *without buffering* made worse — the reader had already
        been handed the opening lines, so its unterminated quote swallowed the rows after it.
        """
        oversized = (
            'REDES11,AIRBNB,2026-08-05,2026-08-08,2,"'
            + ("A" * 9_000 + "\n") * 2
            + "A" * 9_000
            + '"\n'
        )
        body = (
            self.HEADER_WITH_NOTES
            + self._row("fine", 1)
            + oversized
            + self._row("also fine", 2)
            + self._row("still fine", 3)
        )

        result = _parse(body)

        assert [row.reservation.special_requests for row in result.rows] == [
            "fine",
            "also fine",
            "still fine",
        ]
        assert [failure.line for failure in result.failures] == [3]

    def test_a_legitimate_multi_line_quoted_field_still_works(self) -> None:
        """The bound must not turn a normal two-line note into an error."""
        body = (
            self.HEADER_WITH_NOTES
            + self._row("fine", 1)
            + 'REDES11,AIRBNB,2026-09-01,2026-09-03,2,"two\nlines"\n'
            + self._row("last", 3)
        )

        result = _parse(body)

        assert result.failures == []
        assert [row.reservation.special_requests for row in result.rows] == [
            "fine",
            "two\nlines",
            "last",
        ]
        # The line number is the record's first line, which is what a person looks for.
        assert [row.line for row in result.rows] == [2, 4, 5]

    def test_a_file_ending_inside_a_quoted_value_reports_that_row_and_keeps_the_rest(self) -> None:
        body = (
            self.HEADER_WITH_NOTES
            + self._row("fine", 1)
            + 'REDES11,AIRBNB,2026-09-01,2026-09-03,2,"never closed\n'
        )

        result = _parse(body)

        assert [row.reservation.special_requests for row in result.rows] == ["fine"]
        assert [failure.line for failure in result.failures] == [3]
        assert "unclosed" in result.failures[0].reason
