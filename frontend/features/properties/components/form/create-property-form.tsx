"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { CreatePropertyInput } from "../../data";
import { useCreateProperty } from "../../hooks/use-create-property";
import { mapPropertyFieldErrors } from "../../lib/field-errors";
import { validatePropertyFields } from "../../lib/field-validation";
import { PropertyFieldset, type PropertyFormFields } from "./property-fieldset";

/**
 * Defaults mirror the backend's own (`CreatePropertyRequest`,
 * `backend/app/properties/api/schemas.py:100-116`): `country="ES"`,
 * `timezone="Europe/Madrid"`, `max_guests=2`, `bedrooms=1`, `bathrooms=1`,
 * `default_check_in_time=15:00`, `default_check_out_time=11:00`. Every other
 * field starts blank.
 */
const INITIAL_VALUES: PropertyFormFields = {
  name: "",
  internal_code: "",
  pms_external_id: "",
  address_line1: "",
  address_line2: "",
  city: "",
  province: "",
  postal_code: "",
  country: "ES",
  timezone: "Europe/Madrid",
  max_guests: 2,
  bedrooms: 1,
  bathrooms: 1,
  default_check_in_time: "15:00",
  default_check_out_time: "11:00",
  wifi_name: "",
  wifi_password: "",
  access_notes: "",
  cleaning_notes: "",
  emergency_notes: "",
};

/** A blank optional field is "not set" — omitted from the request entirely. */
function optionalText(value: string): string | undefined {
  return value.trim() === "" ? undefined : value;
}

/** `<input type="time">` yields `"HH:MM"`; the wire format is `"HH:MM:SS"`. */
function withSeconds(value: string): string {
  return value.length === 5 ? `${value}:00` : value;
}

function buildCreateInput(values: PropertyFormFields): CreatePropertyInput {
  return {
    name: values.name,
    internalCode: values.internal_code,
    pmsExternalId: optionalText(values.pms_external_id),
    addressLine1: optionalText(values.address_line1),
    addressLine2: optionalText(values.address_line2),
    city: optionalText(values.city),
    province: optionalText(values.province),
    postalCode: optionalText(values.postal_code),
    country: values.country,
    timezone: values.timezone,
    maxGuests: values.max_guests,
    bedrooms: values.bedrooms,
    bathrooms: values.bathrooms,
    defaultCheckInTime: withSeconds(values.default_check_in_time),
    defaultCheckOutTime: withSeconds(values.default_check_out_time),
    wifiName: optionalText(values.wifi_name),
    wifiPassword: optionalText(values.wifi_password),
    accessNotes: optionalText(values.access_notes),
    cleaningNotes: optionalText(values.cleaning_notes),
    emergencyNotes: optionalText(values.emergency_notes),
  };
}

/**
 * Create-property flow (proposal R1, design D1/D11).
 *
 * Plain `useState` per field plus a local validation function — no form
 * library, matching `CreateTenantForm`/`ConversationReplyForm` (design D1).
 * `validatePropertyFields` runs on submit (R1.3): a client-side failure sets
 * `validationErrors` and returns without ever calling the mutation. Those
 * errors are error **keys** (`lib/field-validation.ts`) and are translated
 * here, through `createForm.errors.*`, before reaching `PropertyFieldset`
 * (which never translates anything itself, design D4).
 *
 * On a `409` (duplicate `internal_code`/`pms_external_id`), `mapPropertyFieldErrors`
 * attributes the raw backend message to the offending field (R1.5) — those
 * messages are backend text, not app copy, and are shown verbatim like
 * `CreateTenantForm`'s own 409/422 handling.
 *
 * The submit control disables, and shows pending copy, whenever the mutation
 * is `isPending` (R1.6). `handleSubmit` also short-circuits on `isPending` as
 * a second, defensive guard against a duplicate submission (e.g. a second
 * Enter keypress landing before the disabled attribute re-renders).
 *
 * On `201`, `router.push`es to the new property's detail page (design D11).
 * This form does not manage the hosting `Sheet`'s open state itself — the
 * navigation takes the whole `/properties` page (and the `Sheet` with it) away.
 */
export function CreatePropertyForm() {
  const { t } = useTranslation("properties");
  const router = useRouter();
  const [values, setValues] = useState<PropertyFormFields>(INITIAL_VALUES);
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({});
  const mutation = useCreateProperty();

  function handleChange(field: keyof PropertyFormFields, value: string | number) {
    setValues((prev) => ({ ...prev, [field]: value }) as PropertyFormFields);
    setValidationErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) {
      return;
    }
    const errors = validatePropertyFields(values);
    if (Object.keys(errors).length > 0) {
      setValidationErrors(errors);
      return;
    }
    setValidationErrors({});
    mutation.mutate(buildCreateInput(values), {
      onSuccess: (created) => {
        router.push(`/properties/${created.id}`);
      },
    });
  }

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
        values={values}
        onChange={handleChange}
        fieldErrors={fieldErrors}
        disabled={mutation.isPending}
      />
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending
          ? t("createForm.submitting")
          : t("createForm.submit")}
      </Button>
      {hasGenericError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {t("createForm.genericError")}
        </p>
      ) : null}
    </form>
  );
}
