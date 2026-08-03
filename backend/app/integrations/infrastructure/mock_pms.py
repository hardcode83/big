"""`MockPMSAdapter` — the MVP implementation of the PMS port (R3.1, PRD §16, §27).

EXTERNAL_DEPENDENCY: stands in for Octorate/Smoobu/Beds24 until there are credentials.

It returns the seed reservations of PRD §27 **and, deliberately, rows that fail**: one
pointing at a property this tenant does not have, and one whose dates do not advance. A mock
that only ever produces valid data would let R3.4 ("omitir esa reserva e informarla… sin
abortar las restantes") pass without ever being exercised — and `steering/backend-architecture.md`
is explicit that if the mock hides a case the real adapter has, the port contract is wrong,
not the mock. `include_broken_rows=False` is available for tests that need a clean feed.

Dates are relative to the `since` the caller passes rather than to a clock read here: the
port owns time (see `PMSAdapter.list_reservations`), and a mock that called `now()` would
make every test that depends on "a reservation active today" flaky at midnight.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from app.integrations.domain.dtos import ReservationDTO

SEED_PROPERTY_CODE = "PMS-REDES11"
_LOOKUP_REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)
UNKNOWN_PROPERTY_CODE = "PMS-DOES-NOT-EXIST"


class MockPMSAdapter:
    def __init__(self, *, include_broken_rows: bool = True) -> None:
        self._include_broken_rows = include_broken_rows
        # Part of the port's contract, not a courtesy (see `PMSAdapter.unmappable_rows`). The
        # mock builds its own rows, so it can never fail to map one — but leaving the attribute
        # off would be exactly the silent-zero hazard the port's docstring warns about, and it
        # would break substitutability with the real adapter (Liskov, `backend-architecture.md`).
        self.unmappable_rows: list[str] = []

    async def list_reservations(
        self, since: datetime, property_external_id: str | None = None
    ) -> list[ReservationDTO]:
        rows = self._seed(since)
        if self._include_broken_rows:
            rows = rows + self._broken(since)
        if property_external_id is not None:
            rows = [row for row in rows if row.property_external_id == property_external_id]
        return rows

    async def get_reservation(self, external_id: str) -> ReservationDTO | None:
        """Looked up over the same feed `list_reservations` produces.

        The reference instant is a fixed date, not `datetime.min`: the seed rows are built by
        subtracting days from it, and `datetime.min` overflows. A real adapter would query the
        provider by id and ignore time altogether.
        """
        for row in await self.list_reservations(_LOOKUP_REFERENCE):
            if row.external_id == external_id:
                return row
        return None

    def _seed(self, since: datetime) -> list[ReservationDTO]:
        """The two REDES11 reservations of PRD §27: one active, one upcoming."""
        today = since.date()
        return [
            ReservationDTO(
                external_id="MOCK-PMS-0001",
                channel="AIRBNB",
                property_external_id=SEED_PROPERTY_CODE,
                guest_name="John Smith",
                guest_email="john.smith@example.com",
                guest_phone="+34600000001",
                check_in_date=today - timedelta(days=2),
                check_out_date=today + timedelta(days=1),
                check_in_time=time(15, 0),
                check_out_time=time(11, 0),
                adults=2,
                gross_amount=Decimal("350.00"),
                ota_commission=Decimal("52.50"),
                currency="EUR",
                status="CHECKED_IN_ESTIMATED",
                raw_payload={"provider": "mock", "id": "MOCK-PMS-0001"},
            ),
            ReservationDTO(
                external_id="MOCK-PMS-0002",
                channel="BOOKING",
                property_external_id=SEED_PROPERTY_CODE,
                guest_name="María García",
                guest_email="maria.garcia@example.com",
                check_in_date=today + timedelta(days=3),
                check_out_date=today + timedelta(days=7),
                adults=2,
                gross_amount=Decimal("480.00"),
                ota_commission=Decimal("72.00"),
                currency="EUR",
                status="CONFIRMED",
                raw_payload={"provider": "mock", "id": "MOCK-PMS-0002"},
            ),
        ]

    def _broken(self, since: datetime) -> list[ReservationDTO]:
        """Rows a real provider will eventually send and the ingest must survive."""
        today = since.date()
        return [
            ReservationDTO(
                external_id="MOCK-PMS-9001",
                channel="AIRBNB",
                property_external_id=UNKNOWN_PROPERTY_CODE,
                guest_name="Ghost Booking",
                check_in_date=today + timedelta(days=10),
                check_out_date=today + timedelta(days=12),
                raw_payload={"provider": "mock", "note": "property not in this tenant"},
            ),
            ReservationDTO(
                external_id="MOCK-PMS-9002",
                channel="BOOKING",
                property_external_id=SEED_PROPERTY_CODE,
                guest_name="Impossible Stay",
                check_in_date=today + timedelta(days=5),
                check_out_date=today + timedelta(days=5),
                raw_payload={"provider": "mock", "note": "check-out does not advance"},
            ),
        ]
