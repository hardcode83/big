import uuid
from datetime import datetime, timezone

from app.audit.domain.entities import AuditLog


def test_audit_log_instantiates_with_defaults() -> None:
    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        action="reservation.update",
        entity_type="Reservation",
        entity_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    assert entry.actor_user_id is None
    assert entry.actor_ip is None
    assert entry.changes is None


def test_audit_log_carries_the_change_set_as_plain_data() -> None:
    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        action="user.role_change",
        entity_type="User",
        entity_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        actor_ip="203.0.113.7",
        changes={"role": {"old": "CLEANER", "new": "PROPERTY_MANAGER"}},
    )

    assert entry.changes["role"]["new"] == "PROPERTY_MANAGER"
