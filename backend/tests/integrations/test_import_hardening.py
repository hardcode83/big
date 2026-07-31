"""What the feature-scale panel found, pinned so it cannot come back.

Three classes of defect, all reproduced by the reviewers against the running app:

1. **R4.2 was only half met**: rows rejected *after* parsing (unknown channel, unknown property,
   `adults < 1`) reached the report with no line number, so a person could not find them in a
   file of hundreds of rows.
2. **Hostile or merely sloppy cells escaped as 500s**, taking every valid row of the file with
   them: a 200 kB cell (`_csv.Error`), `nan` in an amount (`decimal.InvalidOperation`), a
   31-character phone (`StringDataRightTruncationError`), a NUL byte
   (`CharacterNotInRepertoireError`).
3. **The byte ceiling was applied too late**: FastAPI parses the multipart form before it solves
   dependencies, so an anonymous request already had its file spooled to disk before the 401.
"""

import pytest
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole
from app.core.config import settings
from app.reservations.infrastructure.models import ReservationModel
from tests.integrations.conftest import auth_header

ENDPOINT = "/api/v1/integrations/pms/import-csv"
HEADER = (
    "property_internal_code,channel,check_in_date,check_out_date,adults,"
    "guest_name,guest_email,guest_phone,gross_amount,external_pms_id\n"
)
GOOD = "REDES11,AIRBNB,2026-08-01,2026-08-04,2,John,john@example.com,+34600000001,350.00,OK-1\n"


def _upload(body: str) -> dict:
    return {"file": ("reservations.csv", body.encode("utf-8"), "text/csv")}


@pytest.fixture
def manager(users_by_role_a):
    return users_by_role_a[UserRole.PROPERTY_MANAGER]


class TestEveryRejectedRowCarriesItsLine:
    """R4.2: "incluir en el informe **su número de línea** y el motivo" — for any invalid row."""

    @pytest.mark.parametrize(
        "row,expected_in_reason",
        [
            ("REDES11,SPACESHIP,2026-08-01,2026-08-04,2,,,,,\n", "channel"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,0,,,,,\n", "adults"),
            ("NOPE11,AIRBNB,2026-08-01,2026-08-04,2,,,,,\n", "Unknown property"),
            ("REDES11,AIRBNB,not-a-date,2026-08-04,2,,,,,\n", "check_in_date"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_report_names_the_line(
        self, api, manager, property_a, row: str, expected_in_reason: str
    ) -> None:
        response = await api.post(
            ENDPOINT, files=_upload(HEADER + GOOD + row), headers=auth_header(api, manager)
        )

        body = response.json()
        assert body["created"] == 1
        assert body["skipped"] == 1
        assert len(body["errors"]) == 1
        # The bad row is the third line of the file (header, good row, bad row).
        assert body["errors"][0]["line"] == 3
        assert expected_in_reason in body["errors"][0]["reason"]

    @pytest.mark.asyncio
    async def test_errors_are_ordered_by_line(self, api, manager, property_a) -> None:
        """A report a person reads top-to-bottom must not jump around the file."""
        response = await api.post(
            ENDPOINT,
            files=_upload(
                HEADER
                + "NOPE11,AIRBNB,2026-08-01,2026-08-04,2,,,,,\n"  # line 2: ingest-level
                + GOOD  # line 3
                + "REDES11,AIRBNB,bad,2026-08-04,2,,,,,\n"  # line 4: parse-level
            ),
            headers=auth_header(api, manager),
        )

        lines = [error["line"] for error in response.json()["errors"]]
        assert lines == [2, 4]


class TestHostileCellsBecomeRowErrorsNot500s:
    @pytest.mark.parametrize(
        "row,expected_in_reason",
        [
            # 200 kB in one cell: `_csv.Error`, which is neither ValueError nor CsvFileError.
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,2," + "A" * 200_000 + ",,,,\n", "guest_name"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,2,,,,nan,\n", "finite"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,2,,,,1E+999,\n", "greater than"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,2,,," + "9" * 31 + ",,\n", "guest_phone"),
            ("REDES11,AIRBNB,2026-08-01,2026-08-04,4000000000,,,,,\n", "adults"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_good_rows_of_the_file_still_import(
        self, api, manager, property_a, db_session, row: str, expected_in_reason: str
    ) -> None:
        response = await api.post(
            ENDPOINT, files=_upload(HEADER + GOOD + row), headers=auth_header(api, manager)
        )

        assert response.status_code in (200, 422)
        if response.status_code == 200:
            body = response.json()
            assert body["created"] == 1
            assert any(expected_in_reason in error["reason"] for error in body["errors"])
            assert await db_session.scalar(select(func.count()).select_from(ReservationModel)) == 1
        else:
            # A file-level refusal is acceptable for the oversized-cell case, as long as it is a
            # 422 in the envelope and not a 500.
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_a_nul_byte_is_a_row_error(self, api, manager, property_a) -> None:
        row = "REDES11,AIRBNB,2026-08-01,2026-08-04,2,Jo\x00hn,,,,\n"

        response = await api.post(
            ENDPOINT, files=_upload(HEADER + GOOD + row), headers=auth_header(api, manager)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["created"] == 1
        assert "NUL" in body["errors"][0]["reason"]


class TestTheBodyCeilingAppliesBeforeAnythingReadsTheBody:
    @pytest.mark.asyncio
    async def test_an_oversized_upload_is_refused_without_a_token(
        self, api, monkeypatch
    ) -> None:
        """The measured hole: 60 MiB were received before the 401 was returned.

        Refusing with `413` rather than `401` is deliberate — the request never gets far enough
        for authentication to be the answer, and the client needs to know the body is the problem.
        """
        monkeypatch.setattr(settings, "csv_import_max_bytes", 1_000)

        response = await api.post(ENDPOINT, files=_upload(HEADER + GOOD * 100))

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_an_oversized_upload_is_refused_with_a_token_too(
        self, api, manager, property_a, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "csv_import_max_bytes", 1_000)

        response = await api.post(
            ENDPOINT, files=_upload(HEADER + GOOD * 100), headers=auth_header(api, manager)
        )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_a_normal_upload_is_untouched_by_the_middleware(
        self, api, manager, property_a
    ) -> None:
        response = await api.post(
            ENDPOINT, files=_upload(HEADER + GOOD), headers=auth_header(api, manager)
        )

        assert response.status_code == 200
        assert response.json()["created"] == 1

    @pytest.mark.asyncio
    async def test_other_endpoints_are_not_affected(self, api, manager, property_a) -> None:
        """The ceiling is scoped to the upload paths; a JSON body must not be measured by it."""
        response = await api.get(
            "/api/v1/reservations", headers=auth_header(api, manager)
        )

        assert response.status_code == 200


class TestConfigurationDefaults:
    def test_the_documented_defaults_are_the_real_ones(self) -> None:
        """Task 6.3 asked for this: without it, shrinking the default to 10 kB passes the suite."""
        assert settings.csv_import_max_bytes == 10 * 1024 * 1024
        assert settings.csv_import_max_rows == 1000
