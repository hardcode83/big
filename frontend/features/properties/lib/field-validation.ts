import {
  MAX_INTERNAL_CODE,
  MAX_NAME,
  MAX_NOTES,
  MAX_WIFI_PASSWORD,
  MAX_GUESTS,
  MAX_ROOMS,
} from "./field-limits";

/**
 * Client-side shape both `CreatePropertyForm` and `EditPropertyForm` validate before
 * submit (R1.3, design D5). Snake_case, mirroring the backend request fields directly
 * (`CreatePropertyRequest`/`UpdatePropertyRequest`), not the camelCase DTO/input types
 * Section 2 introduces — this module has no dependency on `data/dto.ts`.
 *
 * Nullable fields accept `null`/`undefined`/empty string interchangeably: a field the
 * caller hasn't touched yet (or has cleared) is never itself an error, only exceeding
 * a length bound is.
 */
export interface PropertyFieldValues {
  name: string;
  internal_code: string;
  country: string;
  timezone: string;
  max_guests: number;
  bedrooms: number;
  bathrooms: number;
  wifi_password?: string | null;
  access_notes?: string | null;
  cleaning_notes?: string | null;
  emergency_notes?: string | null;
}

const COUNTRY_PATTERN = /^[A-Z]{2}$/;

function checkMaxLength(
  errors: Record<string, string>,
  field: string,
  value: string | null | undefined,
  max: number,
): void {
  if (value != null && value.length > max) {
    errors[field] = "tooLong";
  }
}

/**
 * Validate a property form's current values against the same bounds
 * `backend/app/properties/api/schemas.py` declares (R1.3). Returns a
 * `field -> errorKey` map (empty when every checked field is within bounds);
 * callers translate `errorKey` via their own locale namespace (Section 3/4).
 *
 * Only the fields R1.3 names are checked here: `name`/`internal_code`/
 * `timezone` (required; `name`/`internal_code` also have a max length),
 * `country` (exact 2 uppercase letters), `max_guests` (1-50),
 * `bedrooms`/`bathrooms` (0-50), and the length caps on `pms_external_id`,
 * the three notes and `wifi_password`. Address/city/province/postal_code/
 * wifi_name/check-in-out are enforced only via `maxLength` on the `<input>`
 * itself (design D5) — HTML already prevents a user from ever producing a
 * too-long value there, so there is nothing this pure function needs to flag
 * for them. `timezone` carries the same `max_length=50` bound on its
 * `<input>`, but backend/app/properties/api/schemas.py:106 also requires it
 * non-empty (`min_length=1`), so unlike those other fields it needs an
 * explicit required check here too.
 */
export function validatePropertyFields(
  values: PropertyFieldValues,
): Record<string, string> {
  const errors: Record<string, string> = {};

  if (!values.name || values.name.trim().length === 0) {
    errors.name = "required";
  } else if (values.name.length > MAX_NAME) {
    errors.name = "tooLong";
  }

  if (!values.internal_code || values.internal_code.trim().length === 0) {
    errors.internal_code = "required";
  } else if (values.internal_code.length > MAX_INTERNAL_CODE) {
    errors.internal_code = "tooLong";
  }

  if (!COUNTRY_PATTERN.test(values.country ?? "")) {
    errors.country = "invalidCountry";
  }

  if (!values.timezone || values.timezone.trim().length === 0) {
    errors.timezone = "required";
  }

  if (
    !Number.isInteger(values.max_guests) ||
    values.max_guests < 1 ||
    values.max_guests > MAX_GUESTS
  ) {
    errors.max_guests = "outOfRange";
  }

  if (
    !Number.isInteger(values.bedrooms) ||
    values.bedrooms < 0 ||
    values.bedrooms > MAX_ROOMS
  ) {
    errors.bedrooms = "outOfRange";
  }

  if (
    !Number.isInteger(values.bathrooms) ||
    values.bathrooms < 0 ||
    values.bathrooms > MAX_ROOMS
  ) {
    errors.bathrooms = "outOfRange";
  }

  checkMaxLength(errors, "wifi_password", values.wifi_password, MAX_WIFI_PASSWORD);
  checkMaxLength(errors, "access_notes", values.access_notes, MAX_NOTES);
  checkMaxLength(errors, "cleaning_notes", values.cleaning_notes, MAX_NOTES);
  checkMaxLength(errors, "emergency_notes", values.emergency_notes, MAX_NOTES);

  return errors;
}
