import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AuditLog:
    """No enums: §7.25 types `action` and `entity_type` as free-form VARCHAR."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None = None
    actor_ip: str | None = None
    changes: dict[str, Any] | None = None
