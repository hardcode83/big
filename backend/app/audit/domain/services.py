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

# `audit_logs.actor_guest_token_hash` is VARCHAR(64): a SHA-256 hex digest and nothing else.
GUEST_TOKEN_HASH_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def is_guest_token_digest(value: str) -> bool:
    """Whether `value` is the only thing `actor_guest_token_hash` may hold.

    Public because the guarantee has three layers and they must agree on one predicate:
    this factory, `SqlAlchemyAuditLogRepository.add`, and the column's own CHECK constraint
    (`ck_audit_logs_actor_guest_token_hash_is_a_digest`). Lower-case only — `hexdigest()`
    never produces anything else, so accepting upper case would only widen what a mistake
    can look like.
    """
    return len(value) == GUEST_TOKEN_HASH_LENGTH and set(value) <= _HEX_DIGITS


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
        actor_guest_token_hash: str | None = None,
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
        if actor_user_id is not None and actor_guest_token_hash is not None:
            # One act, one actor. A row claiming both a logged-in user and the bearer of an
            # anonymous portal link describes something that cannot have happened, and this
            # table is append-only, so nobody can later decide which half was true.
            #
            # `GuestActor.__post_init__` refuses the same pair, and that is not redundant:
            # that dataclass belongs to `guests`, while this factory is the chokepoint every
            # module writes through — the architecture panel of section 1 pointed out that a
            # caller assembling these fields by hand would bypass the dataclass entirely.
            raise AuditContractError(
                "An audit row has one actor: either a user or a guest-portal token bearer, "
                "never both."
            )
        if actor_guest_token_hash is not None and not is_guest_token_digest(
            actor_guest_token_hash
        ):
            # The realistic accident is passing the **token** instead of its hash, which
            # `String(64)` would not notice for a value of the right length. R1.2 and R6.4 of
            # `guest-portal-api` forbid the cleartext token in `AuditLog`, and this is the
            # chokepoint where that stops being a convention every writer must remember.
            raise AuditContractError(
                "actor_guest_token_hash must be a SHA-256 hex digest, not the token itself: "
                "R6.4 keeps the cleartext guest token out of audit_logs entirely."
            )

        return AuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=now,
            actor_user_id=actor_user_id,
            actor_guest_token_hash=actor_guest_token_hash,
            actor_ip=actor_ip,
            # NULL rather than `{}` when there is nothing to record: two representations of
            # "no diff" would make every future query on this column check for both.
            changes=changes.as_dict() or None,
        )
