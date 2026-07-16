import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.tenants.domain.enums import StorageType, TenantStatus


@dataclass
class Tenant:
    id: uuid.UUID
    name: str
    billing_email: str
    created_at: datetime
    updated_at: datetime
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    default_language: str = "es"
    status: TenantStatus = TenantStatus.ACTIVE


@dataclass
class TenantConfig:
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    owner_approval_threshold_eur: Decimal = Decimal("100.00")
    ai_confidence_threshold: Decimal = Decimal("0.75")
    sla_critical_minutes: int = 5
    sla_high_minutes: int = 15
    sla_medium_minutes: int = 240
    sla_low_minutes: int = 480
    checkin_window_hours_before: int = 2
    checkout_ready_hours_after: int = 1
    auto_create_cleaning_task: bool = True
    cleaning_photo_required: bool = True
    storage_type: StorageType = StorageType.LOCAL
    notification_email_enabled: bool = True
    notification_whatsapp_enabled: bool = False
