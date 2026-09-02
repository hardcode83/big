"""Request/response DTOs of the tenant endpoints (PRD §23, R5, design D13).

The configuration travels **nested** in one resource, because PRD §23 defines no endpoint of
its own for it and the relation is 1:1 (the unique index on `tenant_configs.tenant_id`).

`model_fields_set` is consulted on the nested object as well as on the outer one: without that,
"absent" and "sent as null" would be the same thing one level down, and a caller could not tell
the API to leave the configuration alone.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.tenants.application.use_cases import TenantSettings
from app.tenants.domain.enums import StorageType, TenantStatus

MAX_NAME = 200
MAX_EMAIL = 255


# Column widths of `tenants` (`app/tenants/infrastructure/models.py`), so an oversized value is
# a `422` naming the field rather than something the domain has to interpret.
MAX_COUNTRY = 2
MAX_TIMEZONE = 50
MAX_LANGUAGE = 5


def _reject_bool(value: object) -> object:
    """`True` is not a number, however much Python disagrees.

    Pydantic coerces `true` to `1` for an `int` field in lax mode, so
    `{"sla_high_minutes": true}` would be accepted **as one minute** — an SLA breached the
    instant it is set. The domain guard in `TenantConfig.update` cannot catch it either: by the
    time it runs, the bool is already an `int`, so `isinstance(value, bool)` is False.

    Same class as the explicit-`null` bug of design D22: a silent coercion of nonsense into a
    value nobody meant. Rejecting it here, before the coercion, is the only place that works.
    """
    if isinstance(value, bool):
        raise ValueError("expected a number, got a boolean")
    return value


def _reject_nulls(model: BaseModel, nullable: frozenset[str]) -> None:
    """Raise if the caller SENT `null` for a field that cannot hold it.

    `model_fields_set` is what distinguishes "sent" from "absent"; without this check the two
    collapse into Python's `None` by the time `changes()` runs, and a `null` reaches a NOT NULL
    column — a `500` at best, a corrupted value at worst.
    """
    sent_nulls = {
        field
        for field in model.model_fields_set
        if field not in nullable and getattr(model, field) is None
    }
    if sent_nulls:
        raise ValueError(f"{', '.join(sorted(sent_nulls))} cannot be null")


class TenantConfigPatch(BaseModel):
    """The patchable part of the configuration.

    `storage_type` is absent, and that is R5.4: switching it points already-uploaded photos at
    a backend that does not have them, so it belongs to `cleaning` with its data migration. A
    body that sends it is rejected by `extra="forbid"` rather than ignored — silently dropping
    a field the caller asked for is worse than refusing it.
    """

    model_config = ConfigDict(extra="forbid")

    owner_approval_threshold_eur: Decimal | None = None
    ai_confidence_threshold: Decimal | None = None
    sla_critical_minutes: int | None = None
    sla_high_minutes: int | None = None
    sla_medium_minutes: int | None = None
    sla_low_minutes: int | None = None
    checkin_window_hours_before: int | None = None
    checkout_ready_hours_after: int | None = None
    auto_create_cleaning_task: bool | None = None
    cleaning_photo_required: bool | None = None
    notification_email_enabled: bool | None = None
    notification_whatsapp_enabled: bool | None = None
    # `revenue-reviews` R5.5: top-N bound for the recurring-issues summary. `1..50`,
    # matching the migration's CHECK constraint and the domain guard.
    review_recurring_issues_top_n: int | None = Field(default=None, ge=1, le=50)

    _no_bools = field_validator(
        "owner_approval_threshold_eur",
        "ai_confidence_threshold",
        "sla_critical_minutes",
        "sla_high_minutes",
        "sla_medium_minutes",
        "sla_low_minutes",
        "checkin_window_hours_before",
        "checkout_ready_hours_after",
        mode="before",
    )(_reject_bool)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "TenantConfigPatch":
        """No column of `tenant_configs` is nullable, so `null` is never a value here.

        Every field is `X | None` only because that is how "not sent" is spelled. The security
        panel of sections 2-6 found the same conflation in the user PATCH writing the string
        `"none"` into a NOT NULL column; this closes it here before it can happen.
        """
        _reject_nulls(self, frozenset())
        return self

    def changes(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.model_fields_set}


class UpdateTenantRequest(BaseModel):
    """`status` is absent, and that is R5.3.

    `auth-tenancy` revalidates on every authenticated request that the tenant is ACTIVE, so
    suspending your own tenant locks every user out with no endpoint to undo it. Rejected by
    `extra="forbid"`.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(default=None, min_length=1, max_length=MAX_NAME)] = None
    billing_email: Annotated[str | None, Field(default=None, max_length=MAX_EMAIL)] = None
    country: Annotated[str | None, Field(default=None, max_length=MAX_COUNTRY)] = None
    timezone: Annotated[str | None, Field(default=None, max_length=MAX_TIMEZONE)] = None
    default_language: Annotated[
        str | None, Field(default=None, max_length=MAX_LANGUAGE)
    ] = None
    config: TenantConfigPatch | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "UpdateTenantRequest":
        """No column of `tenants` reachable here is nullable (`config` is not a column)."""
        _reject_nulls(self, frozenset({"config"}))
        return self

    def tenant_changes(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.model_fields_set
            if field != "config"
        }

    def config_changes(self) -> dict[str, Any]:
        return self.config.changes() if self.config is not None else {}


class TenantConfigResponse(BaseModel):
    owner_approval_threshold_eur: Decimal
    ai_confidence_threshold: Decimal
    sla_critical_minutes: int
    sla_high_minutes: int
    sla_medium_minutes: int
    sla_low_minutes: int
    checkin_window_hours_before: int
    checkout_ready_hours_after: int
    auto_create_cleaning_task: bool
    cleaning_photo_required: bool
    # Readable but not writable: an operator needs to know where photos go.
    storage_type: StorageType
    notification_email_enabled: bool
    notification_whatsapp_enabled: bool
    review_recurring_issues_top_n: int


class TenantResponse(BaseModel):
    """The tenant with its configuration nested. Fields enumerated, never dumped."""

    id: uuid.UUID
    name: str
    billing_email: str
    country: str
    timezone: str
    default_language: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime
    config: TenantConfigResponse

    @classmethod
    def from_settings(cls, settings: TenantSettings) -> "TenantResponse":
        tenant, config = settings.tenant, settings.config
        return cls(
            id=tenant.id,
            name=tenant.name,
            billing_email=tenant.billing_email,
            country=tenant.country,
            timezone=tenant.timezone,
            default_language=tenant.default_language,
            status=tenant.status,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            config=TenantConfigResponse(
                owner_approval_threshold_eur=config.owner_approval_threshold_eur,
                ai_confidence_threshold=config.ai_confidence_threshold,
                sla_critical_minutes=config.sla_critical_minutes,
                sla_high_minutes=config.sla_high_minutes,
                sla_medium_minutes=config.sla_medium_minutes,
                sla_low_minutes=config.sla_low_minutes,
                checkin_window_hours_before=config.checkin_window_hours_before,
                checkout_ready_hours_after=config.checkout_ready_hours_after,
                auto_create_cleaning_task=config.auto_create_cleaning_task,
                cleaning_photo_required=config.cleaning_photo_required,
                storage_type=config.storage_type,
                notification_email_enabled=config.notification_email_enabled,
                notification_whatsapp_enabled=config.notification_whatsapp_enabled,
                review_recurring_issues_top_n=config.review_recurring_issues_top_n,
            ),
        )
