"""`POST /api/v1/integrations/pms/import-csv` end to end (R4, R5).

The report is the contract here: which rows went in, which did not, and why — with line
numbers a person can act on.
"""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.integrations.conftest import auth_header

HEADER = (
    "property_internal_code,channel,check_in_date,check_out_date,adults,"
    "guest_name,guest_email,external_pms_id\n"
)
ROW = "REDES11,AIRBNB,2026-08-01,2026-08-04,2,John Smith,john@example.com,CSV-1\n"
BAD_ROW = "REDES11,AIRBNB,nope,2026-08-04,2,Bad Row,,CSV-2\n"
UNKNOWN_PROPERTY_ROW = "NOPE11,AIRBNB,2026-08-01,2026-08-04,2,Ghost,,CSV-3\n"

ENDPOINT = "/api/v1/integrations/pms/import-csv"


def _upload(body: str) -> dict:
    return {"file": ("reservations.csv", body.encode("utf-8"), "text/csv")}


@pytest.fixture
def manager(users_by_role_a):
    return users_by_role_a[UserRole.PROPERTY_MANAGER]


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_it_imports_a_valid_file_and_reports_it(
        self, api, manager, property_a, db_session
    ) -> None:
        response = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW), headers=auth_header(api, manager)
        )

        assert response.status_code == 200
        assert response.json() == {"created": 1, "updated": 0, "skipped": 0, "errors": []}
        row = (await db_session.execute(select(ReservationModel))).scalar_one()
        assert row.external_pms_id == "CSV-1"
        assert row.check_in_date == date(2026, 8, 1)
        assert row.nights == 3
        assert row.guest_id is not None

    @pytest.mark.asyncio
    async def test_the_event_is_attributed_to_the_uploader(
        self, api, manager, property_a, db_session
    ) -> None:
        """R2.5 and design D15: a person imported this, and the timeline must say who."""
        await api.post(ENDPOINT, files=_upload(HEADER + ROW), headers=auth_header(api, manager))

        event = (await db_session.execute(select(TimelineEventModel))).scalar_one()
        assert event.event_type is TimelineEventType.RESERVATION_IMPORTED
        assert event.actor_type is TimelineActorType.USER
        assert event.actor_user_id == manager.id
        assert event.metadata_["source"] == "csv"

    @pytest.mark.asyncio
    async def test_importing_the_same_file_twice_creates_nothing_the_second_time(
        self, api, manager, property_a, db_session
    ) -> None:
        """R4.5: the same idempotency rule as the sync (R3.2)."""
        first = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW), headers=auth_header(api, manager)
        )
        second = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW), headers=auth_header(api, manager)
        )

        assert first.json()["created"] == 1
        assert second.json()["created"] == 0
        assert await db_session.scalar(select(func.count()).select_from(ReservationModel)) == 1


class TestPartialFailures:
    @pytest.mark.asyncio
    async def test_a_bad_row_is_skipped_with_its_line_number(
        self, api, manager, property_a, db_session
    ) -> None:
        response = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW + BAD_ROW), headers=auth_header(api, manager)
        )

        body = response.json()
        assert body["created"] == 1
        assert body["skipped"] == 1
        assert body["errors"][0]["line"] == 3
        assert "check_in_date" in body["errors"][0]["reason"]
        assert await db_session.scalar(select(func.count()).select_from(ReservationModel)) == 1

    @pytest.mark.asyncio
    async def test_a_row_naming_an_unknown_property_is_reported(
        self, api, manager, property_a
    ) -> None:
        response = await api.post(
            ENDPOINT,
            files=_upload(HEADER + ROW + UNKNOWN_PROPERTY_ROW),
            headers=auth_header(api, manager),
        )

        body = response.json()
        assert body["created"] == 1
        assert body["skipped"] == 1
        assert "Unknown property" in body["errors"][0]["reason"]


class TestFileRejections:
    @pytest.mark.asyncio
    async def test_a_file_missing_a_required_column_is_422(self, api, manager, property_a) -> None:
        response = await api.post(
            ENDPOINT,
            files=_upload("property_internal_code,channel\nREDES11,AIRBNB\n"),
            headers=auth_header(api, manager),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "check_in_date" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_an_empty_file_is_422(self, api, manager, property_a) -> None:
        response = await api.post(ENDPOINT, files=_upload(""), headers=auth_header(api, manager))

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_a_file_over_the_byte_limit_is_413(
        self, api, manager, property_a, monkeypatch
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "csv_import_max_bytes", 50)

        response = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW * 5), headers=auth_header(api, manager)
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_a_file_over_the_row_limit_is_413(
        self, api, manager, property_a, monkeypatch
    ) -> None:
        """A small file can still hold a million rows, so bytes alone is not a limit."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "csv_import_max_rows", 2)

        response = await api.post(
            ENDPOINT, files=_upload(HEADER + ROW * 5), headers=auth_header(api, manager)
        )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_a_non_csv_content_type_is_refused(self, api, manager, property_a) -> None:
        response = await api.post(
            ENDPOINT,
            files={"file": ("payload.bin", b"\x00\x01", "application/octet-stream")},
            headers=auth_header(api, manager),
        )

        assert response.status_code == 422


class TestAuthorizationAndIsolation:
    @pytest.mark.parametrize("role", list(UserRole))
    @pytest.mark.asyncio
    async def test_only_a_manager_may_import(
        self, api, users_by_role_a, property_a, role: UserRole
    ) -> None:
        response = await api.post(
            ENDPOINT,
            files=_upload(HEADER + ROW),
            headers=auth_header(api, users_by_role_a[role]),
        )

        expected = 200 if role is UserRole.PROPERTY_MANAGER else 403
        assert response.status_code == expected

    @pytest.mark.asyncio
    async def test_it_requires_a_token(self, api, property_a) -> None:
        response = await api.post(ENDPOINT, files=_upload(HEADER + ROW))

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_a_csv_naming_another_tenants_property_imports_nothing(
        self, api, manager, property_a, property_b, db_session
    ) -> None:
        """The lookup is by `internal_code` **within the tenant**, so PAJARITOS8 (tenant B's)
        is simply unknown here — no row, and a reported error (R5.1)."""
        response = await api.post(
            ENDPOINT,
            files=_upload(
                HEADER + "PAJARITOS8,AIRBNB,2026-08-01,2026-08-04,2,Ghost,,CSV-9\n"
            ),
            headers=auth_header(api, manager),
        )

        body = response.json()
        assert body["created"] == 0
        assert body["skipped"] == 1
        assert "Unknown property" in body["errors"][0]["reason"]
        assert await db_session.scalar(select(func.count()).select_from(ReservationModel)) == 0
