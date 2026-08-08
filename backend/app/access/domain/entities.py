"""The access record and its state machine (PRD §15, `access-notifications` R2, design D14).

`domain-foundation-ops` created the dataclass; this change gives it methods, because it turned
out to have a real invariant to protect and `steering/backend-architecture.md` is explicit
about when the tactical ceremony is earned: "**Dominio con invariante real**: entidad completa
con métodos que protegen la regla".

The invariant is not bookkeeping. `DELIVERED` is an operator asserting that the guest can get
into the flat; reaching it from `PENDING` would be asserting it about a code nobody ever
registered, and the timeline event that goes with it is append-only.

**`PropertyStateMachine` is untouched by any of this.** `steering/architecture.md` makes it
"el único lugar donde ocurren transiciones de estado" — of the *property*. An access record has
a lifecycle of its own and moves no property between operational states; PRD §15's own event
list (`ACCESS_CODE_PENDING` → … → `ACCESS_CODE_DELIVERED`) is a timeline of the reservation's
access, not of the home.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus
from app.access.domain.exceptions import (
    AccessCodeRequiredError,
    InvalidAccessTransitionError,
)
from app.access.domain.masking import mask_access_code

#: Which states each operation may be invoked from (design D14). The single source: the
#: methods below read it rather than repeating their own `if`, so a new `AccessRecordStatus`
#: shows up as five failing cases in `tests/access/test_entities.py` instead of silently
#: inheriting whatever the last `elif` did.
_ALLOWED_FROM: dict[AccessRecordStatus, frozenset[AccessRecordStatus]] = {
    AccessRecordStatus.MANUAL_ADDED: frozenset({AccessRecordStatus.PENDING}),
    AccessRecordStatus.CREATED_EXTERNAL: frozenset({AccessRecordStatus.PENDING}),
    AccessRecordStatus.DELIVERED: frozenset(
        {AccessRecordStatus.MANUAL_ADDED, AccessRecordStatus.CREATED_EXTERNAL}
    ),
    AccessRecordStatus.REVOKED: frozenset(
        {
            AccessRecordStatus.PENDING,
            AccessRecordStatus.MANUAL_ADDED,
            AccessRecordStatus.CREATED_EXTERNAL,
            AccessRecordStatus.DELIVERED,
        }
    ),
    # Expiry needs a code to have existed: a `PENDING` record has nothing to expire, and
    # `valid_to` — the only thing that could trigger it — is written by a real access
    # provider, which the MVP does not have (design D14, and OQ4 of this change).
    AccessRecordStatus.EXPIRED: frozenset(
        {
            AccessRecordStatus.MANUAL_ADDED,
            AccessRecordStatus.CREATED_EXTERNAL,
            AccessRecordStatus.DELIVERED,
        }
    ),
}

MAX_NOTES = 2000


@dataclass
class AccessRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    provider: AccessProvider = AccessProvider.MANUAL
    external_id: str | None = None
    status: AccessRecordStatus = AccessRecordStatus.PENDING
    #: `****XX` only. **There is deliberately no plaintext field** — see `masking.py` and
    #: design D9. A change that adds one is adding a secret at rest that PRD §15 says the
    #: provider owns, not us.
    code_masked: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_mode: AccessCreatedMode = AccessCreatedMode.MANUAL
    notes: str | None = field(default=None)

    def register_manual_code(
        self, code: str, *, notes: str | None, now: datetime
    ) -> None:
        """R2.2 — the operator types the code; we keep its mask and forget the rest.

        The plaintext parameter dies with this call: it is masked, and nothing on the entity
        or in the repository can hold it. That is what makes design D9 structural.
        """
        self._require(AccessRecordStatus.MANUAL_ADDED)
        if not code.strip():
            # Not a generic validation error: `mask_access_code("")` returns a perfectly
            # ordinary-looking `"****"`, so an empty code would be stored as a mask and the
            # record would claim a code exists.
            raise AccessCodeRequiredError()
        self.code_masked = mask_access_code(code)
        self.provider = AccessProvider.MANUAL
        self.created_mode = AccessCreatedMode.MANUAL
        self._apply(AccessRecordStatus.MANUAL_ADDED, notes=notes, now=now)

    def mark_external_managed(self, *, notes: str | None, now: datetime) -> None:
        """R2.3 — GrinPass (through the PMS) created and owns the code.

        No `code_masked`: PRD §15 has the provider generate *and* deliver it, so there is
        nothing of ours to mask. What we record is who is responsible.
        """
        self._require(AccessRecordStatus.CREATED_EXTERNAL)
        self.provider = AccessProvider.EXTERNAL_MANAGED
        self.created_mode = AccessCreatedMode.EXTERNAL_PMS_AUTOMATIC
        self._apply(AccessRecordStatus.CREATED_EXTERNAL, notes=notes, now=now)

    def mark_delivered(self, *, notes: str | None = None, now: datetime) -> None:
        """R2.4 — the operator confirms the guest has the instructions."""
        self._require(AccessRecordStatus.DELIVERED)
        self._apply(AccessRecordStatus.DELIVERED, notes=notes, now=now)

    def revoke(self, *, reason: str, now: datetime) -> None:
        """R1.4 — the stay is off, so the access is.

        `code_masked` survives on purpose: it is the record of what existed, and this table
        is the only account of an access that was once live.
        """
        self._require(AccessRecordStatus.REVOKED)
        self._apply(AccessRecordStatus.REVOKED, notes=f"Revoked: {reason}", now=now)

    def expire(self, *, now: datetime) -> None:
        """`valid_to` has passed (design D14).

        Implemented and, today, unexercised in production: nothing writes `valid_from`/
        `valid_to` because that is a real access provider's job. Recorded as OQ4 — the
        alternative was leaving an enum value with no path into it.
        """
        self._require(AccessRecordStatus.EXPIRED)
        self._apply(AccessRecordStatus.EXPIRED, notes=None, now=now)

    def _require(self, target: AccessRecordStatus) -> None:
        if self.status not in _ALLOWED_FROM[target]:
            raise InvalidAccessTransitionError(
                current=self.status.value, requested=target.value
            )

    def _apply(
        self, target: AccessRecordStatus, *, notes: str | None, now: datetime
    ) -> None:
        self.status = target
        if notes is not None:
            self.notes = notes[:MAX_NOTES]
        self.updated_at = now
