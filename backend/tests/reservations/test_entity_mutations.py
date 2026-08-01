"""Invariants of the `Reservation` aggregate (R1.2, R1.3, R1.5, R1.6, R1.7, R2.2).

Pure domain: no database, no mocks. `steering/testing.md` asks for TDD where there is a
real invariant to protect, and these are the invariants — derived fields that must never
be accepted from a caller, and a cancellation that must not repeat itself.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.domain.exceptions import ReservationValidationError

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
CHECK_IN = date(2026, 8, 1)
CHECK_OUT = CHECK_IN + timedelta(days=3)


def _create(**overrides) -> Reservation:
    kwargs = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        channel=ReservationChannel.DIRECT,
        check_in_date=CHECK_IN,
        check_out_date=CHECK_OUT,
        now=NOW,
    )
    kwargs.update(overrides)
    return Reservation.create(**kwargs)


class TestCreate:
    def test_it_derives_nights_and_total_guests(self) -> None:
        reservation = _create(adults=2, children=1)

        assert reservation.nights == 3
        assert reservation.total_guests == 3
        assert reservation.status is ReservationStatus.PENDING

    def test_it_does_not_accept_nights_from_the_caller(self) -> None:
        """A caller-supplied `nights` could contradict the dates it also sent."""
        with pytest.raises(TypeError):
            _create(nights=99)

    def test_it_rejects_a_stay_that_does_not_advance(self) -> None:
        with pytest.raises(ReservationValidationError):
            _create(check_in_date=CHECK_IN, check_out_date=CHECK_IN)

    def test_it_rejects_a_stay_that_goes_backwards(self) -> None:
        with pytest.raises(ReservationValidationError):
            _create(check_in_date=CHECK_OUT, check_out_date=CHECK_IN)

    def test_it_rejects_an_empty_party(self) -> None:
        with pytest.raises(ReservationValidationError):
            _create(adults=0)

    def test_it_rejects_negative_children(self) -> None:
        with pytest.raises(ReservationValidationError):
            _create(children=-1)

    def test_it_stamps_both_timestamps_with_the_given_instant(self) -> None:
        reservation = _create()

        assert reservation.created_at == NOW
        assert reservation.updated_at == NOW


class TestUpdateDetails:
    def test_it_reports_only_what_changed(self) -> None:
        reservation = _create(adults=2)

        changed = reservation.update_details({"adults": 3}, now=NOW + timedelta(hours=1))

        assert changed == {"adults": {"from": 2, "to": 3}}
        assert reservation.adults == 3
        assert reservation.total_guests == 3

    def test_a_field_sent_with_its_current_value_is_not_a_change(self) -> None:
        """This is what makes an effectively-empty PATCH emit no timeline event (R2.2)."""
        reservation = _create(adults=2)

        changed = reservation.update_details({"adults": 2}, now=NOW + timedelta(hours=1))

        assert changed == {}

    def test_an_empty_change_set_does_not_touch_updated_at(self) -> None:
        reservation = _create()
        before = reservation.updated_at

        reservation.update_details({}, now=NOW + timedelta(hours=5))

        assert reservation.updated_at == before

    def test_it_recomputes_nights_when_the_dates_move(self) -> None:
        reservation = _create()

        reservation.update_details(
            {"check_out_date": CHECK_IN + timedelta(days=10)}, now=NOW + timedelta(hours=1)
        )

        assert reservation.nights == 10

    def test_it_validates_the_result_not_the_incoming_field(self) -> None:
        """Moving only the check-in can invalidate a check-out that was fine before."""
        reservation = _create()

        with pytest.raises(ReservationValidationError):
            reservation.update_details(
                {"check_in_date": CHECK_OUT + timedelta(days=1)}, now=NOW
            )

    def test_it_refuses_fields_that_are_not_updatable(self) -> None:
        reservation = _create()

        with pytest.raises(ReservationValidationError):
            reservation.update_details({"tenant_id": uuid.uuid4()}, now=NOW)

        with pytest.raises(ReservationValidationError):
            reservation.update_details({"nights": 40}, now=NOW)

    def test_the_change_map_is_json_serialisable(self) -> None:
        """It becomes the `metadata` of a JSONB column, so no date/Decimal/enum objects."""
        import json

        reservation = _create()

        changed = reservation.update_details(
            {
                "check_out_date": CHECK_IN + timedelta(days=4),
                "gross_amount": Decimal("350.00"),
                "status": ReservationStatus.CONFIRMED,
                "check_in_time": time(16, 30),
            },
            now=NOW,
        )

        assert json.loads(json.dumps(changed)) == {
            "check_out_date": {"from": "2026-08-04", "to": "2026-08-05"},
            "gross_amount": {"from": None, "to": "350.00"},
            "status": {"from": "PENDING", "to": "CONFIRMED"},
            "check_in_time": {"from": None, "to": "16:30:00"},
        }

    def test_free_text_fields_report_the_change_without_their_content(self) -> None:
        """`timeline_events` is append-only, so prose written there can never be redacted.

        A manager pasting a door code into `internal_notes` must not leave it in clear text
        for ever in the one store designed never to be edited. R2.2 asks for the fields
        that changed, not their values.
        """
        reservation = _create(internal_notes="old note")

        changed = reservation.update_details(
            {
                "internal_notes": "door code 4815, wifi hunter2",
                "special_requests": "late check-in",
                "adults": 3,
            },
            now=NOW,
        )

        assert changed["internal_notes"] == {"changed": True}
        assert changed["special_requests"] == {"changed": True}
        # The values still reach the row itself — only the timeline stays opaque.
        assert reservation.internal_notes == "door code 4815, wifi hunter2"
        assert "4815" not in str(changed)
        assert "hunter2" not in str(changed)
        assert "late check-in" not in str(changed)
        # Structured fields keep their before/after, which is what makes the event useful.
        assert changed["adults"] == {"from": 1, "to": 3}

    def test_money_is_never_serialised_as_a_float(self) -> None:
        reservation = _create()

        changed = reservation.update_details({"gross_amount": Decimal("0.10")}, now=NOW)

        assert changed["gross_amount"]["to"] == "0.10"
        assert not isinstance(changed["gross_amount"]["to"], float)


class TestCancel:
    def test_the_first_cancellation_transitions_and_reports_it(self) -> None:
        reservation = _create()
        later = NOW + timedelta(days=1)

        assert reservation.cancel(now=later) is True
        assert reservation.status is ReservationStatus.CANCELLED
        assert reservation.updated_at == later

    def test_a_second_cancellation_changes_nothing_and_reports_it(self) -> None:
        """`DELETE` is idempotent (R1.7), so the use case must be able to skip the event."""
        reservation = _create()
        first = NOW + timedelta(days=1)
        reservation.cancel(now=first)

        assert reservation.cancel(now=NOW + timedelta(days=2)) is False
        assert reservation.updated_at == first
