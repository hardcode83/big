"use client";

import { useTranslation } from "react-i18next";

import {
  MAX_ADDRESS,
  MAX_CITY,
  MAX_GUESTS,
  MAX_INTERNAL_CODE,
  MAX_NAME,
  MAX_NOTES,
  MAX_PMS_EXTERNAL_ID,
  MAX_POSTAL_CODE,
  MAX_PROVINCE,
  MAX_ROOMS,
  MAX_WIFI_NAME,
  MAX_WIFI_PASSWORD,
} from "../../lib/field-limits";

/**
 * The full, flat set of fields `CreatePropertyRequest`/`UpdatePropertyRequest`
 * accept, minus `pms_provider` and `status` (R1.2, design D3/D4). Snake_case,
 * matching `PropertyFieldValues` (`lib/field-validation.ts`) field for field —
 * this type is a strict superset of it, so a `values` object typed as this can
 * be passed straight into `validatePropertyFields`.
 *
 * All text fields are plain strings; an empty string is "not yet set" and it
 * is the caller's job (design D4 — this component owns no submit/validation/
 * mutation wiring) to decide whether that becomes an omitted key, `undefined`
 * or an explicit `null` on the wire. The three capacity fields are real
 * `number`s so a `<input type="number">` can bind them directly, and the two
 * time fields are `"HH:MM"` strings straight from `<input type="time">`.
 */
export interface PropertyFormFields {
  name: string;
  internal_code: string;
  pms_external_id: string;
  address_line1: string;
  address_line2: string;
  city: string;
  province: string;
  postal_code: string;
  country: string;
  timezone: string;
  max_guests: number;
  bedrooms: number;
  bathrooms: number;
  default_check_in_time: string;
  default_check_out_time: string;
  wifi_name: string;
  wifi_password: string;
  access_notes: string;
  cleaning_notes: string;
  emergency_notes: string;
}

/** The subset of `PropertyFormFields` whose value is a plain string. */
type TextFieldName = Exclude<
  keyof PropertyFormFields,
  "max_guests" | "bedrooms" | "bathrooms"
>;

export interface PropertyFieldsetProps {
  values: PropertyFormFields;
  onChange: (field: keyof PropertyFormFields, value: string | number) => void;
  /** Field -> already-localized message. This component never translates (design D4). */
  fieldErrors: Record<string, string>;
  /** Disables every control, e.g. while a submit is in flight (R1.6/R2.8). */
  disabled?: boolean;
  /**
   * `id` of an externally-rendered hint paragraph to associate with the
   * `wifi_password` input via `aria-describedby` (D14). `EditPropertyForm`
   * renders its own wifi-password hint alongside the checkbox that has no
   * equivalent here (R2.5) — there is nothing for the create form to pass,
   * so `wifi_password` carries no `aria-describedby` there, same as before.
   */
  wifiPasswordHintId?: string;
}

/** The `id` of a field's control: `property-<field with `_` as `-`>`. */
function fieldId(field: keyof PropertyFormFields): string {
  return `property-${field.replace(/_/g, "-")}`;
}

/**
 * The `id` of a field's error paragraph, so the control can point at it with
 * `aria-describedby` (R4.2, task 6.1). Before section 6 the error was only
 * *visually* adjacent — a sighted user saw it under the input, a screen-reader
 * user moving field by field heard nothing at all, because `role="alert"` only
 * announces the message when it appears, not when focus later lands on the
 * field it belongs to.
 */
function errorId(field: keyof PropertyFormFields): string {
  return `${fieldId(field)}-error`;
}

/** Joins the `aria-describedby` ids that actually exist, or omits the attribute. */
function describedBy(
  ...ids: ReadonlyArray<string | undefined>
): string | undefined {
  const present = ids.filter((id): id is string => Boolean(id));
  return present.length > 0 ? present.join(" ") : undefined;
}

function FieldError({
  field,
  message,
}: {
  field: keyof PropertyFormFields;
  message?: string;
}) {
  if (!message) {
    return null;
  }
  return (
    <p id={errorId(field)} role="alert" className="text-sm text-state-error-text">
      {message}
    </p>
  );
}

/**
 * `tap-target` (`app/globals.css`: `min-height: 44px; min-width: 44px`) is what
 * keeps these controls on the 44×44 floor of `steering/frontend.md`: the
 * padding/font-size trio alone renders ~36px tall. Same class string, same
 * reason, as `features/guest-portal/components/fields/guest-fields.tsx`.
 */
const inputClass =
  "tap-target rounded-md border bg-background px-3 py-2 text-sm disabled:opacity-50";
const textareaClass = `${inputClass} resize-y`;

/**
 * The shared ~15-field presentational list both `CreatePropertyForm` and
 * `EditPropertyForm` render (design D3/D4): name, internal_code,
 * pms_external_id, the address block, country, timezone, the capacity trio,
 * check-in/out times, wifi name/password, and the three free-text notes.
 *
 * Receives `values`/`onChange`/`fieldErrors` as props and owns none of the
 * submit/validation/mutation wiring. Never renders `pms_provider` or
 * `status` — `PropertyFormFields` has no such keys, so there is nothing to
 * accidentally wire up (R1.2).
 *
 * Every field has one programmatically associated `<label htmlFor>` (R4.2);
 * `name`/`internal_code`/`timezone` are the only three marked `required` —
 * every other field carries a backend default (R1.2) so leaving it blank is
 * a valid submission, not an error `validatePropertyFields` would ever
 * raise. `timezone` also has a backend default (`"Europe/Madrid"`), but
 * unlike the others it cannot be sent as an empty string —
 * `backend/app/properties/api/schemas.py:106` declares it `min_length=1` —
 * so it is required in the sense of "must be non-empty", not "has no
 * default".
 *
 * `access_notes` carries an inline hint (design D14, R3.1) associated via
 * `aria-describedby`, stating it is guest-facing free text for arrival
 * instructions and not a door/lock code. `wifi_password` is `type="password"`
 * with `autoComplete="new-password"` (R3.2): write-only, never pre-filled in
 * this create form (there is no stored value yet) and never echoed back.
 * `wifi_password` and the three notes are otherwise plain, unstructured text
 * inputs — no parsing or structuring of their content (R3.3).
 */
export function PropertyFieldset({
  values,
  onChange,
  fieldErrors,
  disabled = false,
  wifiPasswordHintId,
}: PropertyFieldsetProps) {
  const { t } = useTranslation("properties");

  /**
   * The `aria-invalid` / `aria-describedby` pair every control shares (R4.2).
   * `hintId` is the field's own static hint, when it has one — it comes first so
   * assistive technology reads the guidance before the error, in visual order.
   */
  function a11yProps(field: keyof PropertyFormFields, hintId?: string) {
    const invalid = Boolean(fieldErrors[field]);
    return {
      "aria-invalid": invalid || undefined,
      "aria-describedby": describedBy(
        hintId,
        invalid ? errorId(field) : undefined,
      ),
    };
  }

  function textFieldProps(field: TextFieldName, hintId?: string) {
    return {
      id: fieldId(field),
      value: values[field],
      disabled,
      ...a11yProps(field, hintId),
      onChange: (
        event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => onChange(field, event.target.value),
    };
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="property-name" className="text-sm font-medium">
          {t("createForm.fields.name")}
          <span aria-hidden="true"> *</span>
        </label>
        <input
          className={inputClass}
          maxLength={MAX_NAME}
          required
          {...textFieldProps("name")}
        />
        <FieldError field="name" message={fieldErrors.name} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="property-internal-code" className="text-sm font-medium">
          {t("createForm.fields.internalCode")}
          <span aria-hidden="true"> *</span>
        </label>
        <input
          className={inputClass}
          maxLength={MAX_INTERNAL_CODE}
          required
          {...textFieldProps("internal_code")}
        />
        <FieldError field="internal_code" message={fieldErrors.internal_code} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="property-pms-external-id" className="text-sm font-medium">
          {t("createForm.fields.pmsExternalId")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_PMS_EXTERNAL_ID}
          {...textFieldProps("pms_external_id")}
        />
        <FieldError field="pms_external_id" message={fieldErrors.pms_external_id} />
      </div>

      {/* Address block */}
      <div className="flex flex-col gap-1">
        <label htmlFor="property-address-line1" className="text-sm font-medium">
          {t("createForm.fields.addressLine1")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_ADDRESS}
          {...textFieldProps("address_line1")}
        />
        <FieldError field="address_line1" message={fieldErrors.address_line1} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-address-line2" className="text-sm font-medium">
          {t("createForm.fields.addressLine2")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_ADDRESS}
          {...textFieldProps("address_line2")}
        />
        <FieldError field="address_line2" message={fieldErrors.address_line2} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-city" className="text-sm font-medium">
          {t("createForm.fields.city")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_CITY}
          {...textFieldProps("city")}
        />
        <FieldError field="city" message={fieldErrors.city} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-province" className="text-sm font-medium">
          {t("createForm.fields.province")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_PROVINCE}
          {...textFieldProps("province")}
        />
        <FieldError field="province" message={fieldErrors.province} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-postal-code" className="text-sm font-medium">
          {t("createForm.fields.postalCode")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_POSTAL_CODE}
          {...textFieldProps("postal_code")}
        />
        <FieldError field="postal_code" message={fieldErrors.postal_code} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="property-country" className="text-sm font-medium">
          {t("createForm.fields.country")}
        </label>
        <input
          className={inputClass}
          maxLength={2}
          placeholder={t("createForm.placeholders.country")}
          {...textFieldProps("country")}
          onChange={(event) =>
            onChange("country", event.target.value.toUpperCase())
          }
        />
        <FieldError field="country" message={fieldErrors.country} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="property-timezone" className="text-sm font-medium">
          {t("createForm.fields.timezone")}
          <span aria-hidden="true"> *</span>
        </label>
        <input
          className={inputClass}
          // `timezone` has no named constant in `field-limits.ts` (Section 1
          // exported only the fields task 1.2 named); mirrors
          // `backend/app/properties/api/schemas.py:106` (`max_length=50`,
          // `min_length=1`) directly — `required` below enforces the latter.
          maxLength={50}
          required
          placeholder={t("createForm.placeholders.timezone")}
          {...textFieldProps("timezone")}
        />
        <FieldError field="timezone" message={fieldErrors.timezone} />
      </div>

      {/* Capacity trio */}
      <div className="flex flex-col gap-1">
        <label htmlFor="property-max-guests" className="text-sm font-medium">
          {t("createForm.fields.maxGuests")}
        </label>
        <input
          id="property-max-guests"
          type="number"
          className={inputClass}
          min={1}
          max={MAX_GUESTS}
          value={values.max_guests}
          disabled={disabled}
          {...a11yProps("max_guests")}
          onChange={(event) => onChange("max_guests", Number(event.target.value))}
        />
        <FieldError field="max_guests" message={fieldErrors.max_guests} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-bedrooms" className="text-sm font-medium">
          {t("createForm.fields.bedrooms")}
        </label>
        <input
          id="property-bedrooms"
          type="number"
          className={inputClass}
          min={0}
          max={MAX_ROOMS}
          value={values.bedrooms}
          disabled={disabled}
          {...a11yProps("bedrooms")}
          onChange={(event) => onChange("bedrooms", Number(event.target.value))}
        />
        <FieldError field="bedrooms" message={fieldErrors.bedrooms} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-bathrooms" className="text-sm font-medium">
          {t("createForm.fields.bathrooms")}
        </label>
        <input
          id="property-bathrooms"
          type="number"
          className={inputClass}
          min={0}
          max={MAX_ROOMS}
          value={values.bathrooms}
          disabled={disabled}
          {...a11yProps("bathrooms")}
          onChange={(event) => onChange("bathrooms", Number(event.target.value))}
        />
        <FieldError field="bathrooms" message={fieldErrors.bathrooms} />
      </div>

      {/* Check-in / check-out */}
      <div className="flex flex-col gap-1">
        <label htmlFor="property-default-check-in-time" className="text-sm font-medium">
          {t("createForm.fields.defaultCheckInTime")}
        </label>
        <input
          type="time"
          className={inputClass}
          {...textFieldProps("default_check_in_time")}
        />
        <FieldError field="default_check_in_time" message={fieldErrors.default_check_in_time} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-default-check-out-time" className="text-sm font-medium">
          {t("createForm.fields.defaultCheckOutTime")}
        </label>
        <input
          type="time"
          className={inputClass}
          {...textFieldProps("default_check_out_time")}
        />
        <FieldError field="default_check_out_time" message={fieldErrors.default_check_out_time} />
      </div>

      {/* WiFi */}
      <div className="flex flex-col gap-1">
        <label htmlFor="property-wifi-name" className="text-sm font-medium">
          {t("createForm.fields.wifiName")}
        </label>
        <input
          className={inputClass}
          maxLength={MAX_WIFI_NAME}
          {...textFieldProps("wifi_name")}
        />
        <FieldError field="wifi_name" message={fieldErrors.wifi_name} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-wifi-password" className="text-sm font-medium">
          {t("createForm.fields.wifiPassword")}
        </label>
        <input
          type="password"
          autoComplete="new-password"
          className={inputClass}
          maxLength={MAX_WIFI_PASSWORD}
          {...textFieldProps("wifi_password", wifiPasswordHintId)}
        />
        <FieldError field="wifi_password" message={fieldErrors.wifi_password} />
      </div>

      {/* The three free-text sinks (R3.3: plain, unstructured text, never parsed). */}
      <div className="flex flex-col gap-1">
        <label htmlFor="property-access-notes" className="text-sm font-medium">
          {t("createForm.fields.accessNotes")}
        </label>
        <p id="property-access-notes-hint" className="text-sm text-muted-foreground">
          {t("createForm.accessNotesHint")}
        </p>
        <textarea
          rows={3}
          className={textareaClass}
          maxLength={MAX_NOTES}
          {...textFieldProps("access_notes", "property-access-notes-hint")}
        />
        <FieldError field="access_notes" message={fieldErrors.access_notes} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-cleaning-notes" className="text-sm font-medium">
          {t("createForm.fields.cleaningNotes")}
        </label>
        <textarea
          rows={3}
          className={textareaClass}
          maxLength={MAX_NOTES}
          {...textFieldProps("cleaning_notes")}
        />
        <FieldError field="cleaning_notes" message={fieldErrors.cleaning_notes} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="property-emergency-notes" className="text-sm font-medium">
          {t("createForm.fields.emergencyNotes")}
        </label>
        <textarea
          rows={3}
          className={textareaClass}
          maxLength={MAX_NOTES}
          {...textFieldProps("emergency_notes")}
        />
        <FieldError field="emergency_notes" message={fieldErrors.emergency_notes} />
      </div>
    </div>
  );
}
