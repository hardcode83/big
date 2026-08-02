import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.domain.exceptions import TenantValidationError
from app.tenants.domain.value_objects import (
    normalise_country,
    normalise_language,
    normalise_timezone,
)

_UNSET: object = object()

# `ASSUMPTION`: same pragmatic shape as `app/auth/api/user_schemas.py`, and the same
# limitation — not RFC 5322. `billing_email` is where the invoice goes, so a typo matters, but
# validating it properly needs a dependency, and this catches the mistakes that happen.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# Column widths and scales of `tenants`/`tenant_configs`
# (`app/tenants/infrastructure/models.py`). Enforced in the domain so an oversized value is a
# `422` in the PRD §23 envelope instead of a driver error that aborts the transaction.
MAX_NAME = 200
MAX_BILLING_EMAIL = 255
THRESHOLD_MAX_DIGITS = 10
THRESHOLD_DECIMALS = 2
CONFIDENCE_DECIMALS = 2

# `Integer` is int32 in Postgres. Every minute/hour column of `tenant_configs` uses it, so
# these are the real bounds of what the schema can hold — see `_require_int`.
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


@dataclass
class Tenant:
    """The customer account. Mutated only through `update`, which holds its invariants.

    `status` is deliberately NOT reachable from `update` (R5.3): `auth-tenancy` revalidates on
    every authenticated request that the tenant is ACTIVE, so suspending yourself locks every
    user out with no endpoint to undo it. Changing it is a platform operation.
    """

    id: uuid.UUID
    name: str
    billing_email: str
    created_at: datetime
    updated_at: datetime
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    default_language: str = "es"
    status: TenantStatus = TenantStatus.ACTIVE

    def update(
        self,
        *,
        name: str | object = _UNSET,
        billing_email: str | object = _UNSET,
        country: str | object = _UNSET,
        timezone: str | object = _UNSET,
        default_language: str | object = _UNSET,
    ) -> dict[str, object]:
        """Apply the fields that were passed; return the ones that really changed.

        Returning the changed values rather than a bare set of names is what lets the caller
        write only those columns AND build the audit diff from the same source (design D21).
        """
        candidates: dict[str, object] = {}
        if name is not _UNSET:
            candidates["name"] = _require_text(str(name), "name", MAX_NAME)
        if billing_email is not _UNSET:
            candidates["billing_email"] = _require_email(str(billing_email))
        if country is not _UNSET:
            candidates["country"] = normalise_country(str(country))
        if timezone is not _UNSET:
            candidates["timezone"] = normalise_timezone(str(timezone))
        if default_language is not _UNSET:
            candidates["default_language"] = normalise_language(str(default_language))

        changed = {
            field: value
            for field, value in candidates.items()
            if getattr(self, field) != value
        }
        for field, value in changed.items():
            setattr(self, field, value)
        return changed


@dataclass
class TenantConfig:
    """The operational thresholds of one tenant, 1:1 with it.

    `storage_type` is NOT reachable from `update` (R5.4): flipping it points photos that are
    already uploaded at a backend that does not have them, and choosing `S3` without
    credentials breaks every upload. It belongs to `cleaning`, with its data migration.
    """

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

    @classmethod
    def with_defaults(cls, *, tenant_id: uuid.UUID, now: datetime) -> "TenantConfig":
        """The row the bootstrap would have created (R5.7).

        Exists so `PATCH /tenants/{id}` works on a tenant whose config is missing, instead of
        depending on the bootstrap having run.
        """
        return cls(id=uuid.uuid4(), tenant_id=tenant_id, created_at=now, updated_at=now)

    def update(
        self,
        *,
        owner_approval_threshold_eur: Decimal | object = _UNSET,
        ai_confidence_threshold: Decimal | object = _UNSET,
        sla_critical_minutes: int | object = _UNSET,
        sla_high_minutes: int | object = _UNSET,
        sla_medium_minutes: int | object = _UNSET,
        sla_low_minutes: int | object = _UNSET,
        checkin_window_hours_before: int | object = _UNSET,
        checkout_ready_hours_after: int | object = _UNSET,
        auto_create_cleaning_task: bool | object = _UNSET,
        cleaning_photo_required: bool | object = _UNSET,
        notification_email_enabled: bool | object = _UNSET,
        notification_whatsapp_enabled: bool | object = _UNSET,
    ) -> dict[str, object]:
        candidates: dict[str, object] = {}

        if owner_approval_threshold_eur is not _UNSET:
            candidates["owner_approval_threshold_eur"] = _require_money(
                owner_approval_threshold_eur, "owner_approval_threshold_eur"
            )
        if ai_confidence_threshold is not _UNSET:
            candidates["ai_confidence_threshold"] = _require_confidence(
                ai_confidence_threshold
            )
        for field, value in (
            ("sla_critical_minutes", sla_critical_minutes),
            ("sla_high_minutes", sla_high_minutes),
            ("sla_medium_minutes", sla_medium_minutes),
            ("sla_low_minutes", sla_low_minutes),
        ):
            if value is not _UNSET:
                candidates[field] = _require_positive_int(value, field)
        for field, value in (
            ("checkin_window_hours_before", checkin_window_hours_before),
            ("checkout_ready_hours_after", checkout_ready_hours_after),
        ):
            if value is not _UNSET:
                candidates[field] = _require_non_negative_int(value, field)
        for field, value in (
            ("auto_create_cleaning_task", auto_create_cleaning_task),
            ("cleaning_photo_required", cleaning_photo_required),
            ("notification_email_enabled", notification_email_enabled),
            ("notification_whatsapp_enabled", notification_whatsapp_enabled),
        ):
            if value is not _UNSET:
                candidates[field] = bool(value)

        changed = {
            field: value
            for field, value in candidates.items()
            if getattr(self, field) != value
        }
        for field, value in changed.items():
            setattr(self, field, value)
        return changed


def _require_text(value: str, field: str, max_length: int) -> str:
    candidate = value.strip()
    if not candidate:
        raise TenantValidationError(f"{field} cannot be empty")
    if len(candidate) > max_length:
        raise TenantValidationError(f"{field} cannot exceed {max_length} characters")
    return candidate


def _require_email(value: str) -> str:
    candidate = value.strip().lower()
    if not _EMAIL.match(candidate) or len(candidate) > MAX_BILLING_EMAIL:
        raise TenantValidationError("billing_email is not a valid address")
    return candidate


def _require_money(value: object, field: str) -> Decimal:
    amount = _as_decimal(value, field)
    if amount < 0:
        raise TenantValidationError(f"{field} cannot be negative")
    if amount.as_tuple().exponent < -THRESHOLD_DECIMALS:  # type: ignore[operator]
        raise TenantValidationError(f"{field} cannot have more than 2 decimals")
    digits = len(amount.as_tuple().digits)
    if digits - max(0, -int(amount.as_tuple().exponent)) > (  # type: ignore[arg-type]
        THRESHOLD_MAX_DIGITS - THRESHOLD_DECIMALS
    ):
        raise TenantValidationError(
            f"{field} is too large for its column (Numeric(10, 2))"
        )
    return amount


def _require_confidence(value: object) -> Decimal:
    amount = _as_decimal(value, "ai_confidence_threshold")
    if not (Decimal("0") <= amount <= Decimal("1")):
        raise TenantValidationError("ai_confidence_threshold must be between 0 and 1")
    if amount.as_tuple().exponent < -CONFIDENCE_DECIMALS:  # type: ignore[operator]
        raise TenantValidationError(
            "ai_confidence_threshold cannot have more than 2 decimals; its column is "
            "Numeric(3, 2) and Postgres would round it silently"
        )
    return amount


def _as_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as error:  # noqa: BLE001 - any parse failure is the same answer
        raise TenantValidationError(f"{field} is not a number") from error


def _require_positive_int(value: object, field: str) -> int:
    number = _require_int(value, field)
    if number <= 0:
        raise TenantValidationError(f"{field} must be greater than zero")
    return number


def _require_non_negative_int(value: object, field: str) -> int:
    number = _require_int(value, field)
    if number < 0:
        raise TenantValidationError(f"{field} cannot be negative")
    return number


def _require_int(value: object, field: str) -> int:
    """An integer that fits the column, not just an integer of the right sign.

    The upper bound was missing in the first version, and the security panel of sections 7-8
    reproduced what that costs: `{"sla_high_minutes": 99999999999}` reached asyncpg as
    `DataError: value out of int32 range`, which is not a `TenantDomainError` and therefore
    surfaced as an unmapped `500` instead of the `422` R5.5 requires — breaking the promise
    this module's own header makes ("Enforced in the domain so an oversized value is a `422`
    ... instead of a driver error that aborts the transaction"). The `Decimal` fields had
    their bound from the start; the plain integers did not.

    Bounded by the COLUMN (`Integer` is int32 in Postgres) and not by a business ceiling: a
    tighter limit —"an SLA cannot exceed a week"— would be inventing a rule the PRD does not
    state. If the business wants one, it belongs to whoever states it.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TenantValidationError(f"{field} must be an integer")
    if not (INT32_MIN <= value <= INT32_MAX):
        raise TenantValidationError(
            f"{field} does not fit its column (a 32-bit integer, "
            f"{INT32_MIN}..{INT32_MAX})"
        )
    return value
