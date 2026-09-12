"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";

import type { PropertyDetailDto, UpdatePropertyInput } from "../../data";
import { useProperty } from "../../hooks/use-property";
import { useUpdateProperty } from "../../hooks/use-update-property";
import { mapPropertyFieldErrors } from "../../lib/field-errors";
import { validatePropertyFields } from "../../lib/field-validation";
import { PropertyFieldset, type PropertyFormFields } from "./property-fieldset";

/**
 * The live values, the snapshot they were seeded from, and the write-only
 * password's explicit-clear flag (design D8). The snapshot is what makes
 * "changed" answerable at all: without it, a `PATCH` body can only be "send
 * everything", which is the overwrite semantics D8 rejects.
 *
 * `propertyId` rides along so the seed happens once per property and a
 * background refetch (window focus, an invalidation from another mutation)
 * cannot silently replace what the user is typing.
 */
interface EditFormState {
  propertyId: string;
  initial: PropertyFormFields;
  values: PropertyFormFields;
  clearWifiPassword: boolean;
}

/** `PropertyResponse` carries `"HH:MM:SS"`; `<input type="time">` binds `"HH:MM"`. */
function toTimeInput(value: string): string {
  return value.slice(0, 5);
}

/** `<input type="time">` yields `"HH:MM"`; the wire format is `"HH:MM:SS"`. */
function withSeconds(value: string): string {
  return value.length === 5 ? `${value}:00` : value;
}

/**
 * Seed the form from the fetched property (R2.2).
 *
 * Every nullable column becomes `""` — the fieldset binds plain strings — and
 * `wifi_password` is seeded blank **always** (R2.5): the API never returns it
 * (`PropertyDetailDto` has no such field to read from in the first place), and
 * blank means "unchanged", never "clear it".
 */
function toFormFields(detail: PropertyDetailDto): PropertyFormFields {
  return {
    name: detail.name,
    internal_code: detail.internalCode,
    pms_external_id: detail.pmsExternalId ?? "",
    address_line1: detail.addressLine1 ?? "",
    address_line2: detail.addressLine2 ?? "",
    city: detail.city ?? "",
    province: detail.province ?? "",
    postal_code: detail.postalCode ?? "",
    country: detail.country,
    timezone: detail.timezone,
    max_guests: detail.maxGuests,
    bedrooms: detail.bedrooms,
    bathrooms: detail.bathrooms,
    default_check_in_time: toTimeInput(detail.defaultCheckInTime),
    default_check_out_time: toTimeInput(detail.defaultCheckOutTime),
    wifi_name: detail.wifiName ?? "",
    wifi_password: "",
    access_notes: detail.accessNotes ?? "",
    cleaning_notes: detail.cleaningNotes ?? "",
    emergency_notes: detail.emergencyNotes ?? "",
  };
}

function seedState(propertyId: string, detail: PropertyDetailDto): EditFormState {
  const fields = toFormFields(detail);
  return {
    propertyId,
    initial: fields,
    // Two distinct objects on purpose: `values` is mutated by every keystroke
    // and `initial` must stay the snapshot it was seeded from.
    values: { ...fields },
    clearWifiPassword: false,
  };
}

/**
 * The nullable columns of `properties`, as `[UpdatePropertyInput key, form key]`
 * pairs — `NULLABLE_FIELDS` in `backend/app/properties/api/schemas.py` minus
 * `wifi_password`, which has its own rule below. These are the only fields that
 * may ever appear in the body as an explicit `null` (R2.4).
 */
const NULLABLE_TEXT_FIELDS: ReadonlyArray<
  [
    (
      | "pmsExternalId"
      | "addressLine1"
      | "addressLine2"
      | "city"
      | "province"
      | "postalCode"
      | "wifiName"
      | "accessNotes"
      | "cleaningNotes"
      | "emergencyNotes"
    ),
    keyof PropertyFormFields,
  ]
> = [
  ["pmsExternalId", "pms_external_id"],
  ["addressLine1", "address_line1"],
  ["addressLine2", "address_line2"],
  ["city", "city"],
  ["province", "province"],
  ["postalCode", "postal_code"],
  ["wifiName", "wifi_name"],
  ["accessNotes", "access_notes"],
  ["cleaningNotes", "cleaning_notes"],
  ["emergencyNotes", "emergency_notes"],
];

/**
 * The NOT NULL columns, same pairing. A `null` here is rejected by
 * `UpdatePropertyRequest._reject_explicit_nulls` before it can reach the
 * database, so this form never produces one: a changed value is sent as the
 * string it is, and an emptied `name`/`internal_code`/`country` never gets this
 * far because `validatePropertyFields` blocks the submit first (design D8).
 */
const REQUIRED_TEXT_FIELDS: ReadonlyArray<
  [
    "name" | "internalCode" | "country" | "timezone",
    keyof PropertyFormFields,
  ]
> = [
  ["name", "name"],
  ["internalCode", "internal_code"],
  ["country", "country"],
  ["timezone", "timezone"],
];

const NUMBER_FIELDS: ReadonlyArray<
  ["maxGuests" | "bedrooms" | "bathrooms", keyof PropertyFormFields]
> = [
  ["maxGuests", "max_guests"],
  ["bedrooms", "bedrooms"],
  ["bathrooms", "bathrooms"],
];

const TIME_FIELDS: ReadonlyArray<
  [
    "defaultCheckInTime" | "defaultCheckOutTime",
    keyof PropertyFormFields,
  ]
> = [
  ["defaultCheckInTime", "default_check_in_time"],
  ["defaultCheckOutTime", "default_check_out_time"],
];

/**
 * Build the `PATCH` body out of the difference between the seeded snapshot and
 * the live values (design D8, R2.2). Three rules, and only three:
 *
 *  - a field whose value is unchanged is **omitted** — an absent key is what
 *    `model_fields_set` reads as "leave it alone";
 *  - a nullable field emptied from a previously non-empty value is sent as
 *    `null` — the explicit clear of R2.4. A field that was already empty and
 *    stays empty (whitespace included) is still omitted, never sent as `null`;
 *  - `wifi_password` is write-only: `clearWifiPassword` sends `null`, a typed
 *    value sends that value, and blank-with-the-box-unchecked omits the key
 *    entirely (R2.5).
 *
 * `status` is never written here, under any input: retiring a property is its
 * own confirmed action (design D9, R2.3) and `EditPropertyForm` renders no
 * control for it — nor for `pms_provider`/`current_operational_state`, which
 * `PropertyFormFields` has no keys for.
 */
function buildUpdateInput(
  initial: PropertyFormFields,
  values: PropertyFormFields,
  clearWifiPassword: boolean,
): UpdatePropertyInput {
  const body: UpdatePropertyInput = {};

  for (const [inputKey, formKey] of NULLABLE_TEXT_FIELDS) {
    const current = String(values[formKey]);
    const before = String(initial[formKey]);
    const isCleared = current.trim() === "";
    if (isCleared && before.trim() === "") {
      // Already empty, still empty: untouched, so it must not travel as `null`.
      continue;
    }
    if (isCleared) {
      body[inputKey] = null;
      continue;
    }
    if (current !== before) {
      body[inputKey] = current;
    }
  }

  for (const [inputKey, formKey] of REQUIRED_TEXT_FIELDS) {
    const current = String(values[formKey]);
    if (current !== String(initial[formKey])) {
      body[inputKey] = current;
    }
  }

  for (const [inputKey, formKey] of TIME_FIELDS) {
    const current = String(values[formKey]);
    if (current !== String(initial[formKey])) {
      body[inputKey] = withSeconds(current);
    }
  }

  for (const [inputKey, formKey] of NUMBER_FIELDS) {
    const current = Number(values[formKey]);
    if (current !== Number(initial[formKey])) {
      body[inputKey] = current;
    }
  }

  if (clearWifiPassword) {
    body.wifiPassword = null;
  } else if (values.wifi_password !== "") {
    body.wifiPassword = values.wifi_password;
  }

  return body;
}

export interface EditPropertyFormProps {
  propertyId: string;
  /** Host-supplied dismissal (closes the `Sheet`). Omit and no cancel control renders. */
  onCancel?: () => void;
  /** Called after a successful save, with the server's own updated property. */
  onSaved?: (property: PropertyDetailDto) => void;
}

/**
 * Edit-property flow (proposal R2, design D3/D7/D8/D13).
 *
 * Fetches the full property itself through `useProperty` (design D7) — the
 * dashboard aggregate that hosts this form does not carry the writable fields —
 * seeds `PropertyFieldset` from it (R2.2), and on submit sends only what
 * changed (`buildUpdateInput`, D8).
 *
 * Two namespaces, the split D13 fixes: field labels and the WiFi-password copy
 * come from `properties` (shared with `PropertyFieldset`, which translates the
 * labels itself), while the save/cancel/result copy comes from `dashboard`,
 * where the hosting detail view's own strings live.
 *
 * `noValidate` for the same reason `CreatePropertyForm` carries it: `name` and
 * `internal_code` keep their HTML `required` attribute for a11y (R4.2), but
 * native constraint validation would block the `submit` event before
 * `validatePropertyFields` — the single validation path — ever ran.
 */
export function EditPropertyForm({
  propertyId,
  onCancel,
  onSaved,
}: EditPropertyFormProps) {
  const { t } = useTranslation("properties");
  const { t: tDashboard } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const query = useProperty(propertyId);
  const mutation = useUpdateProperty();
  const [state, setState] = useState<EditFormState | null>(null);
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({});

  const detail = query.data;
  // Seed once per property, without an effect: React's documented "adjust state
  // during render" pattern. `seedState` is pure, so recomputing it on the
  // seeding render costs nothing and the guard below stops after one pass — a
  // later background refetch of the same property leaves the user's edits alone.
  const active =
    state !== null && state.propertyId === propertyId
      ? state
      : detail
        ? seedState(propertyId, detail)
        : null;
  if (active !== null && active !== state) {
    setState(active);
  }

  if (query.isError) {
    return (
      <ErrorState
        title={tStates("error.title")}
        description={tStates("error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  if (active === null) {
    return <LoadingState label={tStates("loading.label")} />;
  }

  function handleChange(
    field: keyof PropertyFormFields,
    value: string | number,
  ) {
    setState((prev) =>
      prev === null
        ? prev
        : {
            ...prev,
            values: { ...prev.values, [field]: value } as PropertyFormFields,
            // Typing a password and asking to clear the stored one are mutually
            // exclusive answers to the same question, so the later one wins
            // instead of the body carrying an ambiguous pair.
            clearWifiPassword:
              field === "wifi_password" && value !== ""
                ? false
                : prev.clearWifiPassword,
          },
    );
    setValidationErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }

  function handleClearWifiPassword(checked: boolean) {
    setState((prev) =>
      prev === null
        ? prev
        : {
            ...prev,
            clearWifiPassword: checked,
            values: checked
              ? { ...prev.values, wifi_password: "" }
              : prev.values,
          },
    );
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending || state === null) {
      return;
    }
    const errors = validatePropertyFields(state.values);
    if (Object.keys(errors).length > 0) {
      setValidationErrors(errors);
      return;
    }
    setValidationErrors({});
    mutation.mutate(
      {
        id: propertyId,
        input: buildUpdateInput(
          state.initial,
          state.values,
          state.clearWifiPassword,
        ),
      },
      {
        onSuccess: (updated) => {
          // Re-seed from the server's own answer: the saved values become the
          // new snapshot, the password field goes blank again and the clear
          // checkbox resets, so a second save diffs against reality.
          setState(seedState(propertyId, updated));
          onSaved?.(updated);
        },
      },
    );
  }

  const pendingChanges = buildUpdateInput(
    active.initial,
    active.values,
    active.clearWifiPassword,
  );
  const isDirty = Object.keys(pendingChanges).length > 0;
  const serverFieldErrors = mutation.isError
    ? mapPropertyFieldErrors(mutation.error)
    : {};
  const hasValidationErrors = Object.keys(validationErrors).length > 0;
  const fieldErrors: Record<string, string> = hasValidationErrors
    ? Object.fromEntries(
        Object.entries(validationErrors).map(([field, key]) => [
          field,
          t(`createForm.errors.${key}`),
        ]),
      )
    : serverFieldErrors;
  const hasGenericError =
    mutation.isError &&
    !hasValidationErrors &&
    Object.keys(serverFieldErrors).length === 0;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      <PropertyFieldset
        values={active.values}
        onChange={handleChange}
        fieldErrors={fieldErrors}
        disabled={mutation.isPending}
        wifiPasswordHintId="property-wifi-password-hint"
      />

      {/*
        The write-only password's two extra affordances (R2.5, design D8). They
        live here and not in `PropertyFieldset` because the create form has no
        stored password to keep or clear — there is nothing for it to say.
      */}
      <div className="flex flex-col gap-1">
        <p
          id="property-wifi-password-hint"
          className="text-sm text-muted-foreground"
        >
          {t("editForm.wifiPasswordHint")}
        </p>
        {/*
          `tap-target` sits on the `<label>`, not on the `<input>`: a `<label
          htmlFor>` IS the checkbox's pointer target (clicking anywhere in it
          toggles the box), so raising the row to a 44px minimum height gives
          the control a real 44×44 hit area without inflating the native
          checkbox glyph to the size of a button — the documented shape of this
          exception, per `steering/frontend.md`'s «salvo que una excepción
          objetiva quede documentada junto al componente».
        */}
        <label
          htmlFor="property-clear-wifi-password"
          className="tap-target flex items-center gap-2 text-sm font-medium"
        >
          <input
            id="property-clear-wifi-password"
            type="checkbox"
            checked={active.clearWifiPassword}
            disabled={mutation.isPending}
            onChange={(event) => handleClearWifiPassword(event.target.checked)}
          />
          {t("editForm.clearWifiPassword")}
        </label>
      </div>

      {/*
        `tap-target` on both: `Button`'s default size is `h-10` (40px), under the
        44×44 floor of `steering/frontend.md` (task 6.1/6.2).
      */}
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          className="tap-target"
          disabled={mutation.isPending}
        >
          {mutation.isPending
            ? tDashboard("detail.edit.submitting")
            : tDashboard("detail.edit.submit")}
        </Button>
        {onCancel ? (
          <Button
            type="button"
            variant="outline"
            className="tap-target"
            disabled={mutation.isPending}
            onClick={onCancel}
          >
            {tDashboard("detail.edit.cancel")}
          </Button>
        ) : null}
      </div>

      {mutation.isSuccess && !isDirty ? (
        <p role="status" className="text-sm text-muted-foreground">
          {tDashboard("detail.edit.success")}
        </p>
      ) : null}
      {hasGenericError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {tDashboard("detail.edit.genericError")}
        </p>
      ) : null}
    </form>
  );
}
