import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from app.integrations.domain.enums import PMSProvider
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)


@dataclass
class Property:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    internal_code: str
    created_at: datetime
    updated_at: datetime
    pms_external_id: str | None = None
    pms_provider: PMSProvider | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    max_guests: int = 2
    bedrooms: int = 1
    bathrooms: int = 1
    current_operational_state: PropertyOperationalState = PropertyOperationalState.VACANT_READY
    default_check_in_time: time = time(15, 0)
    default_check_out_time: time = time(11, 0)
    wifi_name: str | None = None
    # Whether a wifi password is stored — NOT the password, and not its ciphertext either
    # (`properties-crud` R5.2). A caller still has to tell "none stored" from "one is stored and
    # you cannot read it", and without this flag no read path could express that difference. A
    # boolean is not the secret, so design D2 below is untouched by it.
    has_wifi_password: bool = False
    # `wifi_password_encrypted` is deliberately NOT a field here (`properties-crud` design D2).
    # The column exists and this change is its first writer, but the entity is what every read
    # path returns and what response schemas are built from, so keeping the secret off it means
    # no serialisation route can carry it — the accident rule 3(a) of `steering/security.md`
    # forbids — instead of every future schema having to remember to omit it. It travels as an
    # explicit `EncryptedSecret` parameter of the two writers that set it, and is never read
    # back: `GET` exposes `has_wifi_password`, not the value.
    access_notes: str | None = None
    cleaning_notes: str | None = None
    emergency_notes: str | None = None
    status: PropertyStatus = PropertyStatus.ACTIVE


@dataclass
class PropertyStateTransition:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    to_state: PropertyOperationalState
    triggered_by: StateTransitionTriggeredBy
    created_at: datetime
    from_state: PropertyOperationalState | None = None
    triggered_by_user_id: uuid.UUID | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
