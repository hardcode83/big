"use client";

import { useState, type FormEvent, type InputHTMLAttributes } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useActiveProperties } from "@/features/properties";
import { useHasPermission } from "@/lib/auth";

import { useCreateReservation } from "../../hooks/use-reservations";
import { reservationMutationErrorKey } from "../../lib/mutation-error-mapping";
import type { CreateReservationInput, ReservationSummaryDto } from "../../data";

interface FormValues {
  propertyId: string;
  checkInDate: string;
  checkOutDate: string;
  checkInTime: string;
  checkOutTime: string;
  adults: string;
  children: string;
  channel: "DIRECT" | "MANUAL";
  grossAmount: string;
  netAmount: string;
  otaCommission: string;
  currency: string;
  internalNotes: string;
  specialRequests: string;
  fullName: string;
  email: string;
  phone: string;
  preferredLanguage: "es" | "en";
}

const INITIAL_VALUES: FormValues = {
  propertyId: "",
  checkInDate: "",
  checkOutDate: "",
  checkInTime: "",
  checkOutTime: "",
  adults: "1",
  children: "0",
  channel: "DIRECT",
  grossAmount: "",
  netAmount: "",
  otaCommission: "",
  currency: "EUR",
  internalNotes: "",
  specialRequests: "",
  fullName: "",
  email: "",
  phone: "",
  preferredLanguage: "es",
};

const fieldClass =
  "min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function optionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  return trimmed === "" ? undefined : Number(trimmed);
}

function buildCreatePayload(values: FormValues): CreateReservationInput {
  const guestName = values.fullName.trim();
  const guest = guestName
    ? {
        full_name: guestName,
        ...(values.email.trim() ? { email: values.email.trim() } : {}),
        ...(values.phone.trim() ? { phone: values.phone.trim() } : {}),
        preferred_language: values.preferredLanguage,
      }
    : undefined;

  return {
    property_id: values.propertyId,
    check_in_date: values.checkInDate,
    check_out_date: values.checkOutDate,
    adults: Number(values.adults),
    children: Number(values.children),
    channel: values.channel,
    ...(values.checkInTime.trim() ? { check_in_time: values.checkInTime } : {}),
    ...(values.checkOutTime.trim() ? { check_out_time: values.checkOutTime } : {}),
    ...(optionalNumber(values.grossAmount) !== undefined
      ? { gross_amount: optionalNumber(values.grossAmount) }
      : {}),
    ...(optionalNumber(values.netAmount) !== undefined
      ? { net_amount: optionalNumber(values.netAmount) }
      : {}),
    ...(optionalNumber(values.otaCommission) !== undefined
      ? { ota_commission: optionalNumber(values.otaCommission) }
      : {}),
    ...(values.currency.trim() ? { currency: values.currency.trim() } : {}),
    ...(values.internalNotes.trim()
      ? { internal_notes: values.internalNotes.trim() }
      : {}),
    ...(values.specialRequests.trim()
      ? { special_requests: values.specialRequests.trim() }
      : {}),
    ...(guest ? { guest } : {}),
  };
}

export function CreateReservationForm({
  onCreated,
}: {
  onCreated?: (reservation: ReservationSummaryDto) => void;
}) {
  const { t } = useTranslation("reservations");
  const { t: tStates } = useTranslation("states");
  const properties = useActiveProperties();
  const create = useCreateReservation();
  const canManage = useHasPermission("MANAGE_RESERVATIONS");
  const [values, setValues] = useState<FormValues>(INITIAL_VALUES);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof FormValues, string>>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createdReservation, setCreatedReservation] = useState<{
    id: string;
    propertyName: string | null;
    checkInDate: string;
    checkOutDate: string;
    status: string;
  } | null>(null);

  if (!canManage) return null;

  if (properties.isPending) {
    return <LoadingState label={tStates("loading.label")} />;
  }
  if (properties.isError) {
    return (
      <ErrorState
        title={t("create.propertiesError")}
        description={t("create.propertiesErrorDescription")}
        onRetry={() => void properties.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }
  if (!properties.data || properties.data.data.length === 0) {
    return (
      <EmptyState
        title={t("create.propertiesEmpty")}
        description={t("create.propertiesEmptyDescription")}
      />
    );
  }

  const selectedProperty = properties.data.data.find(
    (property) => property.id === values.propertyId,
  );
  const setField = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setFieldErrors((current) => ({ ...current, [key]: undefined }));
    setFormError(null);
    setCreatedReservation(null);
    setValues((current) => ({ ...current, [key]: value }));
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (create.isPending || isSubmitting) return;
    setFormError(null);
    setFieldErrors({});
    const errors: Partial<Record<keyof FormValues, string>> = {};
    if (!values.propertyId) errors.propertyId = t("create.errors.requiredProperty");
    if (!values.checkInDate) errors.checkInDate = t("create.errors.requiredDate");
    if (!values.checkOutDate) errors.checkOutDate = t("create.errors.requiredDate");
    if (!values.adults.trim()) errors.adults = t("create.errors.requiredAdults");
    if (!values.children.trim()) errors.children = t("create.errors.requiredChildren");
    const adults = Number(values.adults.trim());
    const children = Number(values.children.trim());
    if (values.adults.trim() && (!Number.isInteger(adults) || !Number.isFinite(adults) || adults < 1)) {
      errors.adults = t("create.errors.invalidAdults");
    }
    if (values.children.trim() && (!Number.isInteger(children) || !Number.isFinite(children) || children < 0)) {
      errors.children = t("create.errors.invalidGuests");
    }
    for (const key of ["grossAmount", "netAmount", "otaCommission"] as const) {
      const amount = optionalNumber(values[key]);
      if (amount !== undefined && (!Number.isFinite(amount) || amount < 0)) {
        errors[key] = t("create.errors.invalidAmount");
      }
    }
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormError(t("create.errors.correctFields"));
      return;
    }
    if (values.checkOutDate <= values.checkInDate) {
      setFieldErrors({ checkOutDate: t("create.errors.dateOrder") });
      setFormError(t("create.errors.dateOrder"));
      return;
    }
    if (
      (values.email.trim() || values.phone.trim()) &&
      !values.fullName.trim()
    ) {
      setFieldErrors({ fullName: t("create.errors.guestName") });
      setFormError(t("create.errors.guestName"));
      return;
    }
    setIsSubmitting(true);
    create.mutate(buildCreatePayload(values), {
      onSuccess: (reservation) => {
        setIsSubmitting(false);
        setValues(INITIAL_VALUES);
        setFieldErrors({});
        setCreatedReservation({
          id: reservation.id,
          propertyName: reservation.propertyName ?? t("create.unknownProperty"),
          checkInDate: reservation.checkInDate,
          checkOutDate: reservation.checkOutDate,
          status: t(`status.${reservation.status}`),
        });
        onCreated?.(reservation);
      },
      onError: (error) => {
        setIsSubmitting(false);
        setFormError(t(reservationMutationErrorKey(error, "create")));
      },
    });
  }

  const label = (key: string) => t(`create.fields.${key}`);
  const input = (
    key: keyof FormValues,
    type: string = "text",
    extra: InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <input
      id={`reservation-create-${String(key)}`}
      name={String(key)}
      type={type}
      className={fieldClass}
      value={values[key]}
      aria-invalid={fieldErrors[key] ? true : undefined}
      aria-describedby={fieldErrors[key] ? `reservation-create-${String(key)}-error` : undefined}
      onChange={(event) => setField(key, event.target.value as FormValues[typeof key])}
      {...extra}
    />
  );

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-4" noValidate>
      <div>
        <h2 className="text-lg font-semibold">{t("create.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("create.description")}</p>
      </div>
      {formError ? <p role="alert" className="text-sm text-destructive">{formError}</p> : null}
      {createdReservation ? <p role="status" aria-live="polite">{t("create.successDetail", createdReservation)}</p> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor="reservation-create-propertyId" className="mb-1 block text-sm font-medium">{label("property")}</label>
          <select id="reservation-create-propertyId" name="propertyId" className={fieldClass} required value={values.propertyId} aria-invalid={fieldErrors.propertyId ? true : undefined} aria-describedby={fieldErrors.propertyId ? "reservation-create-propertyId-error" : undefined} onChange={(e) => setField("propertyId", e.target.value)}>
            <option value="">{t("create.selectProperty")}</option>
            {properties.data.data.map((property) => <option key={property.id} value={property.id}>{property.name} ({property.internalCode})</option>)}
          </select>
          {fieldErrors.propertyId ? <p id="reservation-create-propertyId-error" className="text-sm text-destructive">{fieldErrors.propertyId}</p> : null}
          {selectedProperty ? <p className="mt-1 text-xs text-muted-foreground">{t("create.propertyContext", { timezone: selectedProperty.timezone, checkIn: selectedProperty.defaultCheckInTime, checkOut: selectedProperty.defaultCheckOutTime })}</p> : null}
        </div>
        {(["checkInDate", "checkOutDate"] as const).map((key) => <div key={key}><label htmlFor={`reservation-create-${key}`} className="mb-1 block text-sm font-medium">{label(key)} *</label>{input(key, "date", { required: true })}{fieldErrors[key] ? <p id={`reservation-create-${key}-error`} className="text-sm text-destructive">{fieldErrors[key]}</p> : null}</div>)}
        {(["checkInTime", "checkOutTime"] as const).map((key) => <div key={key}><label htmlFor={`reservation-create-${key}`} className="mb-1 block text-sm font-medium">{label(key)}</label>{input(key, "time")}</div>)}
        {(["adults", "children"] as const).map((key) => <div key={key}><label htmlFor={`reservation-create-${key}`} className="mb-1 block text-sm font-medium">{label(key)} *</label>{input(key, "text", { inputMode: "numeric", required: true })}{fieldErrors[key] ? <p id={`reservation-create-${key}-error`} className="text-sm text-destructive">{fieldErrors[key]}</p> : null}</div>)}
        <div><label htmlFor="reservation-create-channel" className="mb-1 block text-sm font-medium">{label("channel")}</label><select id="reservation-create-channel" name="channel" className={fieldClass} value={values.channel} onChange={(e) => setField("channel", e.target.value as FormValues["channel"])}><option value="DIRECT">{t("create.channels.DIRECT")}</option><option value="MANUAL">{t("create.channels.MANUAL")}</option></select></div>
        {(["grossAmount", "netAmount", "otaCommission"] as const).map((key) => <div key={key}><label htmlFor={`reservation-create-${key}`} className="mb-1 block text-sm font-medium">{label(key)}</label>{input(key, "text", { inputMode: "decimal" })}{fieldErrors[key] ? <p id={`reservation-create-${key}-error`} className="text-sm text-destructive">{fieldErrors[key]}</p> : null}</div>)}
        <div><label htmlFor="reservation-create-currency" className="mb-1 block text-sm font-medium">{label("currency")}</label>{input("currency")}</div>
      </div>
      <fieldset className="grid gap-4 rounded-md border border-border p-3 sm:grid-cols-2"><legend className="px-1 text-sm font-medium">{t("create.guestTitle")}</legend>{(["fullName", "email", "phone"] as const).map((key) => <div key={key}><label htmlFor={`reservation-create-${key}`} className="mb-1 block text-sm font-medium">{label(key)}</label>{input(key, key === "email" ? "email" : "text")}{fieldErrors[key] ? <p id={`reservation-create-${key}-error`} className="text-sm text-destructive">{fieldErrors[key]}</p> : null}</div>)}<div><label htmlFor="reservation-create-preferredLanguage" className="mb-1 block text-sm font-medium">{label("preferredLanguage")}</label><select id="reservation-create-preferredLanguage" name="preferredLanguage" className={fieldClass} value={values.preferredLanguage} onChange={(e) => setField("preferredLanguage", e.target.value as FormValues["preferredLanguage"])}><option value="es">{t("create.languages.es")}</option><option value="en">{t("create.languages.en")}</option></select></div></fieldset>
      <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="reservation-create-internalNotes" className="mb-1 block text-sm font-medium">{label("internalNotes")}</label><textarea id="reservation-create-internalNotes" name="internalNotes" className={fieldClass} rows={3} value={values.internalNotes} onChange={(e) => setField("internalNotes", e.target.value)} /></div><div><label htmlFor="reservation-create-specialRequests" className="mb-1 block text-sm font-medium">{label("specialRequests")}</label><textarea id="reservation-create-specialRequests" name="specialRequests" className={fieldClass} rows={3} value={values.specialRequests} onChange={(e) => setField("specialRequests", e.target.value)} /></div></div>
      <Button type="submit" className="tap-target" disabled={create.isPending || isSubmitting} aria-busy={create.isPending || isSubmitting}>{create.isPending || isSubmitting ? t("create.submitting") : t("create.submit")}</Button>
    </form>
  );
}

export { buildCreatePayload };
