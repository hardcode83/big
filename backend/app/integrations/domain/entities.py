import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class WebhookEvent:
    """`tenant_id` is optional (§7.26: "nullable si no está autenticado aún").

    A payload that cannot be attributed to a tenant is still recorded, so it can be
    reprocessed rather than lost. `provider` and `event_type` are free-form strings,
    not enums — the PRD types them as VARCHAR because the set of providers is open.
    """

    id: uuid.UUID
    provider: str
    event_type: str
    payload: dict[str, Any]
    received_at: datetime
    tenant_id: uuid.UUID | None = None
    processed: bool = False
    processed_at: datetime | None = None
    error: str | None = None
