"""Access provider adapters for the MVP (PRD §15, `access-notifications` design D12).

Both live here rather than in `app/integrations/` because neither talks to an external
system: `ManualAccessAdapter` is an operator, and `MockAccessAdapter` is a fixture. The day
GrinPass, TTLock or Beds24's Arrivals API lands, that adapter goes to `app/integrations/`
where the PMS ones already are.

**Substitutable by contract** (`steering/backend-architecture.md`, Liskov): same return
type, same precondition, same failure mode. Where they differ is only what
`get_access_status` can answer — the manual one has no provider to ask, and says so with
`None`, which the port documents as an ordinary answer rather than an error.
"""

from datetime import datetime

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus
from app.access.domain.ports import AccessStatusResult

#: What `MockAccessAdapter` reports, in the shape PRD §15 asks for ("genera código demo
#: `****23`"). Already masked — there is no plaintext anywhere in this module, and a mock
#: that invented one would be the first place a real code learned it could live here.
DEMO_CODE_MASKED = "****23"


class ManualAccessAdapter:
    """PRD §15: "el operador introduce el código manualmente".

    Has no provider to query, so `get_access_status` answers `None` — not an empty result
    pretending to be a reading. The two write paths just drive the entity's own state
    machine, which is where the invariant lives (design D14).
    """

    async def get_access_status(
        self, reservation_external_id: str
    ) -> AccessStatusResult | None:
        return None

    async def create_manual_access(
        self, *, record: AccessRecord, code: str, notes: str | None, now: datetime
    ) -> AccessRecord:
        record.register_manual_code(code, notes=notes, now=now)
        return record

    async def mark_external_managed(
        self, *, record: AccessRecord, notes: str | None, now: datetime
    ) -> AccessRecord:
        record.mark_external_managed(notes=notes, now=now)
        return record


class MockAccessAdapter:
    """PRD §15: "genera código demo `****23`". For seed data and demos.

    EXTERNAL_DEPENDENCY: stands in for a real provider (GrinPass / TTLock / Beds24 Arrivals),
    undecided per [ADR 0006](../../../../docs/adr/0006-pms-channel-manager-provider.md)
    decision 5.

    It reports every access as already created by the provider, which is what a real one
    would do for a booking it has imported.
    """

    async def get_access_status(
        self, reservation_external_id: str
    ) -> AccessStatusResult | None:
        return AccessStatusResult(
            status=AccessRecordStatus.CREATED_EXTERNAL,
            external_id=f"mock-{reservation_external_id}",
            code_masked=DEMO_CODE_MASKED,
        )

    async def create_manual_access(
        self, *, record: AccessRecord, code: str, notes: str | None, now: datetime
    ) -> AccessRecord:
        record.register_manual_code(code, notes=notes, now=now)
        return record

    async def mark_external_managed(
        self, *, record: AccessRecord, notes: str | None, now: datetime
    ) -> AccessRecord:
        record.mark_external_managed(notes=notes, now=now)
        return record
