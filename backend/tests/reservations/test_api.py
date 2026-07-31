"""The five reservation endpoints end to end over ASGI (R1, R2).

The happy paths matter less than the answers on the edges: `422` shapes, the `404` that must
not become a `403`, the idempotent `204`, and the `409` the unique constraint produces.
"""

import pytest

from app.auth.domain.enums import UserRole
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from sqlalchemy import select

from tests.reservations.conftest import auth_header


def _envelope(payload, code: str) -> None:
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str) and payload["error"]["message"]


async def _create(api, manager, create_payload, **overrides):
    return await api.post(
        "/api/v1/reservations",
        json=create_payload(**overrides),
        headers=auth_header(api, manager),
    )


@pytest.fixture
def manager(users_by_role_a):
    return users_by_role_a[UserRole.PROPERTY_MANAGER]


@pytest.fixture
def owner(users_by_role_a):
    return users_by_role_a[UserRole.TENANT_OWNER]


class TestCreate:
    @pytest.mark.asyncio
    async def test_it_creates_and_derives_the_computed_fields(
        self, api, manager, create_payload, property_a
    ) -> None:
        response = await _create(api, manager, create_payload, adults=2, children=1)

        assert response.status_code == 201
        body = response.json()
        assert body["nights"] == 3
        assert body["total_guests"] == 3
        assert body["status"] == "PENDING"
        assert body["property_id"] == str(property_a.id)
        assert body["currency"] == "EUR"

    @pytest.mark.asyncio
    async def test_it_records_a_timeline_event_for_the_acting_user(
        self, api, manager, create_payload, db_session
    ) -> None:
        response = await _create(api, manager, create_payload)

        event = (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.reservation_id == response.json()["id"]
                )
            )
        ).scalar_one()
        assert event.event_type is TimelineEventType.RESERVATION_CREATED_MANUAL
        assert event.actor_user_id == manager.id

    @pytest.mark.asyncio
    async def test_a_body_field_that_does_not_exist_is_refused(
        self, api, manager, create_payload
    ) -> None:
        """`extra="forbid"` is what stops a `tenant_id` in the body from being ignored
        silently rather than rejected (R5.2)."""
        response = await _create(api, manager, create_payload, tenant_id="whatever")

        assert response.status_code == 422
        _envelope(response.json(), "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_an_inverted_stay_is_refused(self, api, manager, create_payload) -> None:
        response = await _create(
            api, manager, create_payload, check_in_date="2026-08-04", check_out_date="2026-08-01"
        )

        assert response.status_code == 422
        _envelope(response.json(), "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_an_empty_party_is_refused(self, api, manager, create_payload) -> None:
        response = await _create(api, manager, create_payload, adults=0)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_an_ota_channel_cannot_be_created_by_hand(
        self, api, manager, create_payload
    ) -> None:
        """An `AIRBNB` booking typed by hand carries no `external_pms_id`, so the next PMS
        sync would import it again as a second row."""
        response = await _create(api, manager, create_payload, channel="AIRBNB")

        assert response.status_code == 422
        _envelope(response.json(), "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_a_property_of_another_tenant_answers_404(
        self, api, manager, create_payload, property_b
    ) -> None:
        response = await _create(api, manager, create_payload, property_id=str(property_b.id))

        assert response.status_code == 404
        _envelope(response.json(), "NOT_FOUND")

    @pytest.mark.asyncio
    async def test_the_endpoint_cannot_set_an_external_pms_id(
        self, api, manager, create_payload
    ) -> None:
        """Which is why `POST` has no `409` path (design D9, corrected here).

        `external_pms_id` is the idempotency key of the ingest routes; a value typed into a
        manual booking would let the next PMS sync believe it already imported that
        reservation. The `409` of the unique constraint is therefore reachable only from the
        sync and the CSV import — it is covered at repository level in
        `test_repositories.py::test_a_duplicate_external_id_raises_a_domain_error`.
        """
        response = await _create(api, manager, create_payload, external_pms_id="PMS-1")

        assert response.status_code == 422
        _envelope(response.json(), "VALIDATION_ERROR")


class TestRead:
    @pytest.mark.asyncio
    async def test_the_detail_of_an_unknown_reservation_is_404(self, api, manager) -> None:
        import uuid

        response = await api.get(
            f"/api/v1/reservations/{uuid.uuid4()}", headers=auth_header(api, manager)
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_the_owner_can_read_but_not_create(
        self, api, owner, manager, create_payload
    ) -> None:
        created = await _create(api, manager, create_payload)

        readable = await api.get(
            f"/api/v1/reservations/{created.json()['id']}", headers=auth_header(api, owner)
        )
        forbidden = await api.post(
            "/api/v1/reservations", json=create_payload(), headers=auth_header(api, owner)
        )

        assert readable.status_code == 200
        assert forbidden.status_code == 403

    @pytest.mark.asyncio
    async def test_the_listing_paginates_with_the_prd_envelope(
        self, api, manager, create_payload
    ) -> None:
        for day in ("01", "05", "09"):
            await _create(
                api,
                manager,
                create_payload,
                check_in_date=f"2026-08-{day}",
                check_out_date=f"2026-08-{int(day) + 1:02d}",
            )

        response = await api.get(
            "/api/v1/reservations?page=1&per_page=2", headers=auth_header(api, manager)
        )

        body = response.json()
        assert set(body) == {"data", "total", "page", "per_page", "total_pages"}
        assert body["total"] == 3
        assert body["per_page"] == 2
        assert body["total_pages"] == 2
        assert len(body["data"]) == 2

    @pytest.mark.asyncio
    async def test_per_page_is_capped(self, api, manager) -> None:
        response = await api.get(
            "/api/v1/reservations?per_page=5000", headers=auth_header(api, manager)
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_page_zero_is_refused(self, api, manager) -> None:
        """An unbounded `page` would reach the adapter as a negative OFFSET."""
        response = await api.get(
            "/api/v1/reservations?page=0", headers=auth_header(api, manager)
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_an_inverted_date_range_is_refused(self, api, manager) -> None:
        response = await api.get(
            "/api/v1/reservations?date_from=2026-09-01&date_to=2026-08-01",
            headers=auth_header(api, manager),
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_the_range_filter_matches_overlapping_stays(
        self, api, manager, create_payload
    ) -> None:
        spanning = await _create(
            api, manager, create_payload, check_in_date="2026-08-01", check_out_date="2026-08-11"
        )
        await _create(
            api, manager, create_payload, check_in_date="2026-07-01", check_out_date="2026-07-03"
        )

        response = await api.get(
            "/api/v1/reservations?date_from=2026-08-05&date_to=2026-08-06",
            headers=auth_header(api, manager),
        )

        assert [row["id"] for row in response.json()["data"]] == [spanning.json()["id"]]


class TestUpdateAndCancel:
    @pytest.mark.asyncio
    async def test_a_patch_applies_only_the_fields_sent(
        self, api, manager, create_payload
    ) -> None:
        created = await _create(api, manager, create_payload)

        response = await api.patch(
            f"/api/v1/reservations/{created.json()['id']}",
            json={"adults": 4},
            headers=auth_header(api, manager),
        )

        body = response.json()
        assert response.status_code == 200
        assert body["adults"] == 4
        assert body["total_guests"] == 4
        assert body["check_in_date"] == created.json()["check_in_date"]

    @pytest.mark.asyncio
    async def test_a_patch_that_invalidates_the_stay_is_refused(
        self, api, manager, create_payload
    ) -> None:
        created = await _create(api, manager, create_payload)

        response = await api.patch(
            f"/api/v1/reservations/{created.json()['id']}",
            json={"check_in_date": "2026-08-30"},
            headers=auth_header(api, manager),
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_cancels_without_removing_the_row(
        self, api, manager, create_payload
    ) -> None:
        created = await _create(api, manager, create_payload)
        reservation_id = created.json()["id"]

        deleted = await api.delete(
            f"/api/v1/reservations/{reservation_id}", headers=auth_header(api, manager)
        )
        reread = await api.get(
            f"/api/v1/reservations/{reservation_id}", headers=auth_header(api, manager)
        )

        assert deleted.status_code == 204
        assert reread.status_code == 200
        assert reread.json()["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_delete_is_idempotent_and_records_one_event(
        self, api, manager, create_payload, db_session
    ) -> None:
        created = await _create(api, manager, create_payload)
        reservation_id = created.json()["id"]

        first = await api.delete(
            f"/api/v1/reservations/{reservation_id}", headers=auth_header(api, manager)
        )
        second = await api.delete(
            f"/api/v1/reservations/{reservation_id}", headers=auth_header(api, manager)
        )

        assert (first.status_code, second.status_code) == (204, 204)
        cancellations = (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.reservation_id == reservation_id,
                    TimelineEventModel.event_type == TimelineEventType.RESERVATION_CANCELLED,
                )
            )
        ).scalars()
        assert len(list(cancellations)) == 1

    @pytest.mark.asyncio
    async def test_free_text_content_never_reaches_the_timeline(
        self, api, manager, create_payload, db_session
    ) -> None:
        """The event says the note changed, not what it now says (R2.2)."""
        created = await _create(api, manager, create_payload)

        await api.patch(
            f"/api/v1/reservations/{created.json()['id']}",
            json={"internal_notes": "door code 4815"},
            headers=auth_header(api, manager),
        )

        event = (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.reservation_id == created.json()["id"],
                    TimelineEventModel.event_type == TimelineEventType.RESERVATION_UPDATED,
                )
            )
        ).scalar_one()
        assert event.metadata_ == {"changed": {"internal_notes": {"changed": True}}}
        assert "4815" not in str(event.metadata_)
