/**
 * Client-side range checks for `PATCH /api/v1/tenants/{id}` (R5.3), mirroring
 * the backend's own guards so a doomed request never leaves the client:
 * `backend/app/tenants/domain/entities.py`'s `_require_money` (threshold
 * cannot be negative), `_require_confidence` (`[0, 1]`), `_require_positive_int`
 * (SLAs `> 0`), and `backend/app/tenants/domain/value_objects.py`'s
 * `normalise_timezone` (a real IANA zone, constructed rather than matched
 * against a fixed list — see `isValidIanaTimeZone` below for why).
 *
 * Scope is deliberately the four checks R5.3's own acceptance criterion names
 * ("umbral no negativo, SLAs positivos, confianza en [0,1], huso horario
 * IANA") — not every range the backend enforces (e.g. decimal-precision
 * limits, `checkin_window_hours_before`/`checkout_ready_hours_after`
 * non-negativity, `review_recurring_issues_top_n`'s `1..50`). Anything out of
 * this function's scope still round-trips to the backend and surfaces via
 * `mapFieldErrors` on a genuine `422` — this function only prevents the
 * request that is unconditionally doomed for one of these four reasons.
 *
 * Only fields present on `input` (`!== undefined`) are validated — mirrors
 * the "only sent fields are checked" contract every `TenantConfigPatch`
 * field already has server-side (design's "sends only the fields that
 * changed"), so a field the caller is not changing is never blocked by a
 * pre-existing out-of-range value it did not touch.
 *
 * Returns a validation-failure CODE per field, not a rendered message: this
 * module has no `useTranslation` access (it is plain client-side logic, not
 * a component), and `sdd/steering/frontend.md` requires every end-user-facing
 * string to go through `locales/es/`+`locales/en/tenant-settings.json`'s
 * `validation` namespace. `tenant-config-form.tsx` (the only caller) maps
 * each code to `t("validation.<code>")` at the error-display site —
 * `notPositive` additionally interpolates `{{label}}` with that field's own
 * already-translated `tenantConfig.fields.*` label.
 */
export interface TenantConfigValidationInput {
  timezone?: string;
  ownerApprovalThresholdEur?: string | number;
  aiConfidenceThreshold?: string | number;
  slaCriticalMinutes?: number;
  slaHighMinutes?: number;
  slaMediumMinutes?: number;
  slaLowMinutes?: number;
}

/** Validation-failure codes; `tenant-config-form.tsx` resolves each to `t("validation.<code>")`. */
export type TenantConfigValidationErrorCode =
  | "notANumber"
  | "negative"
  | "outOfConfidenceRange"
  | "notPositive"
  | "timezoneEmpty"
  | "timezoneInvalid";

const SLA_FIELDS = [
  "slaCriticalMinutes",
  "slaHighMinutes",
  "slaMediumMinutes",
  "slaLowMinutes",
] as const;

/** Returns field → error-code pairs for every present-and-invalid field; `{}` means "safe to send". */
export function validateTenantConfig(
  input: TenantConfigValidationInput,
): Record<string, TenantConfigValidationErrorCode> {
  const errors: Record<string, TenantConfigValidationErrorCode> = {};

  if (input.ownerApprovalThresholdEur !== undefined) {
    const amount = toNumber(input.ownerApprovalThresholdEur);
    if (amount === null) {
      errors.ownerApprovalThresholdEur = "notANumber";
    } else if (amount < 0) {
      errors.ownerApprovalThresholdEur = "negative";
    }
  }

  if (input.aiConfidenceThreshold !== undefined) {
    const amount = toNumber(input.aiConfidenceThreshold);
    if (amount === null) {
      errors.aiConfidenceThreshold = "notANumber";
    } else if (amount < 0 || amount > 1) {
      errors.aiConfidenceThreshold = "outOfConfidenceRange";
    }
  }

  for (const field of SLA_FIELDS) {
    const value = input[field];
    if (value !== undefined) {
      if (!Number.isFinite(value) || value <= 0) {
        errors[field] = "notPositive";
      }
    }
  }

  if (input.timezone !== undefined) {
    const candidate = input.timezone.trim();
    if (!candidate) {
      errors.timezone = "timezoneEmpty";
    } else if (!isValidIanaTimeZone(candidate)) {
      errors.timezone = "timezoneInvalid";
    }
  }

  return errors;
}

function toNumber(value: string | number): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Constructs the zone rather than checking it against
 * `Intl.supportedValuesOf("timeZone")`'s enumeration: that list is the ICU
 * data bundled with the JS engine, which is not guaranteed to be the same
 * set of names Python's `zoneinfo`/the IANA tzdata on the backend host
 * recognizes (legacy aliases in particular) — the backend's own
 * `normalise_timezone` validates the same way, by constructing `ZoneInfo`
 * and catching the failure, not by matching a fixed list. `Intl.DateTimeFormat`
 * throws a `RangeError` for an unrecognized `timeZone` in every engine this
 * app runs in (including the test environment), so this is also the more
 * portable check of the two the task describes.
 */
function isValidIanaTimeZone(candidate: string): boolean {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: candidate });
    return true;
  } catch {
    return false;
  }
}
