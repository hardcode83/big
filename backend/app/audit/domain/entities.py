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
    #: The bearer of a guest-portal token, named by the SHA-256 of what they presented
    #: (`guest-portal-api` D11). Never the cleartext token — R1.2 and R6.4 forbid it, and
    #: `AuditLogFactory` refuses anything that is not a digest.
    actor_guest_token_hash: str | None = None
    actor_ip: str | None = None
    changes: dict[str, Any] | None = None
