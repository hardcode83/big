"""`AuditLogFactory` — the only way to build an `AuditLog` (R6.3, R6.5, design D2).

Mirrors `app/timeline/domain/services.py::TimelineEventFactory`, and for the same reason:
`audit_logs` is written by the use cases of other modules, so the contract of the column has
to live at the point of construction rather than in each writer.

What it guarantees: the action and entity type come from `actions.py`, the change set has
already passed rule 11 (it can only arrive as a `ChangeSet`), the timestamp is
timezone-aware, and `actor_ip` fits its column.
"""

import uuid
from datetime import datetime

from app.audit.domain.actions import ACTIONS, ENTITY_TYPES
from app.audit.domain.entities import AuditLog
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import ChangeSet

# `audit_logs.actor_ip` is VARCHAR(45) — an IPv6 address with an IPv4 suffix and a zone
# index is the longest thing that legitimately fits.
MAX_ACTOR_IP_LENGTH = 45


class AuditLogFactory:
    @staticmethod
    def build(
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> AuditLog:
        if action not in ACTIONS:
            raise AuditContractError(
                f"Unknown audit action {action!r}. The vocabulary is closed in "
                "app/audit/domain/actions.py so the column stays queryable (design D4)."
            )
        if entity_type not in ENTITY_TYPES:
            raise AuditContractError(
                f"Unknown audit entity type {entity_type!r}. One spelling per table, or "
                "ix_audit_logs_tenant_id_entity_type_entity_id stops helping."
            )
        if changes and changes.entity_type != entity_type:
            # A change set built for USER attached to a TENANT row would audit the right
            # fields against the wrong object, and the allowlist of the other entity would
            # have vetted them.
            raise AuditContractError(
                f"Change set describes {changes.entity_type!r} but the entry is for "
                f"{entity_type!r}"
            )
        if now.tzinfo is None or now.utcoffset() is None:
            raise AuditContractError("Audit timestamps must be timezone-aware")
        if actor_ip is not None and len(actor_ip) > MAX_ACTOR_IP_LENGTH:
            raise AuditContractError(
                f"actor_ip is longer than the {MAX_ACTOR_IP_LENGTH} characters the column "
                "holds; it would fail at the driver and abort the whole transaction."
            )

        return AuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=now,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            # NULL rather than `{}` when there is nothing to record: two representations of
            # "no diff" would make every future query on this column check for both.
            changes=changes.as_dict() or None,
        )
