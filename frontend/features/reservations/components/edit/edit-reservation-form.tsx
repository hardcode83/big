"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useHasPermission } from "@/lib/auth";

import type { ReservationDetailDto, UpdateReservationInput } from "../../data";
import { useUpdateReservation } from "../../hooks/use-reservations";
import { reservationMutationErrorKey } from "../../lib/mutation-error-mapping";

export const INGEST_OWNED_FIELDS = [
  "checkInDate", "checkOutDate", "checkInTime", "checkOutTime", "adults", "children",
  "grossAmount", "otaCommission", "netAmount", "currency", "specialRequests",
] as const;
const EDITABLE_FIELDS = [
  "checkInDate", "checkOutDate", "checkInTime", "checkOutTime", "adults", "children",
  "grossAmount", "otaCommission", "netAmount", "currency", "specialRequests", "internalNotes",
] as const;
type EditableField = (typeof EDITABLE_FIELDS)[number];
export type EditFormValues = Record<EditableField, string>;

const DETAIL_TO_FORM: Record<EditableField, keyof ReservationDetailDto> = {
  checkInDate: "checkInDate", checkOutDate: "checkOutDate", checkInTime: "checkInTime",
  checkOutTime: "checkOutTime", adults: "adults", children: "children", grossAmount: "grossAmount",
  otaCommission: "otaCommission", netAmount: "netAmount", currency: "currency",
  specialRequests: "specialRequests", internalNotes: "internalNotes",
};
const API_FIELDS: Record<EditableField, string> = {
  checkInDate: "check_in_date", checkOutDate: "check_out_date", checkInTime: "check_in_time",
  checkOutTime: "check_out_time", adults: "adults", children: "children", grossAmount: "gross_amount",
  otaCommission: "ota_commission", netAmount: "net_amount", currency: "currency",
  specialRequests: "special_requests", internalNotes: "internal_notes",
};

function formValue(detail: ReservationDetailDto, field: EditableField): string {
  const value = detail[DETAIL_TO_FORM[field]];
  return value === null || value === undefined ? "" : String(value);
}
export function initialEditValues(detail: ReservationDetailDto): EditFormValues {
  return Object.fromEntries(EDITABLE_FIELDS.map((field) => [field, formValue(detail, field)])) as EditFormValues;
}
function normalizeValue(field: EditableField, value: string): unknown {
  if (value.trim() === "") return null;
  if (["adults", "children", "grossAmount", "otaCommission", "netAmount"].includes(field)) return Number(value);
  return value.trim();
}
export function buildReservationPatch(detail: ReservationDetailDto, values: EditFormValues): UpdateReservationInput {
  const patch: Record<string, unknown> = {};
  for (const field of EDITABLE_FIELDS) {
    const next = normalizeValue(field, values[field]);
    if (typeof next === "number" && (!Number.isFinite(next) || next < 0 || (["adults", "children"].includes(field) && !Number.isInteger(next)))) continue;
    const previous = detail[DETAIL_TO_FORM[field]];
    const comparablePrevious = previous === null || previous === undefined ? null : normalizeValue(field, String(previous));
    if (next !== comparablePrevious) patch[API_FIELDS[field]] = next;
  }
  return patch as UpdateReservationInput;
}

export type EditValidationKey = "required" | "invalidDate" | "dateOrder" | "invalidAdults" | "invalidGuests" | "invalidAmount";
export function validateEditValues(values: EditFormValues): Partial<Record<EditableField, EditValidationKey>> {
  const errors: Partial<Record<EditableField, EditValidationKey>> = {};
  const validDate = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  };
  if (!values.checkInDate) errors.checkInDate = "required";
  else if (!validDate(values.checkInDate)) errors.checkInDate = "invalidDate";
  if (!values.checkOutDate) errors.checkOutDate = "required";
  else if (!validDate(values.checkOutDate)) errors.checkOutDate = "invalidDate";
  if (validDate(values.checkInDate) && validDate(values.checkOutDate) && values.checkOutDate < values.checkInDate) errors.checkOutDate = "dateOrder";
  for (const field of ["adults", "children"] as const) {
    const number = Number(values[field].trim());
    const minimum = field === "adults" ? 1 : 0;
    if (!values[field].trim() || !Number.isFinite(number) || !Number.isInteger(number) || number < minimum) errors[field] = field === "adults" ? "invalidAdults" : "invalidGuests";
  }
  for (const field of ["grossAmount", "otaCommission", "netAmount"] as const) {
    if (values[field].trim()) {
      const number = Number(values[field].trim());
      if (!Number.isFinite(number) || number < 0) errors[field] = "invalidAmount";
    }
  }
  if (!values.currency.trim()) errors.currency = "required";
  return errors;
}

const fieldClass = "min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring";
export function EditReservationForm({ detail }: { detail: ReservationDetailDto }) {
  const { t } = useTranslation("reservations");
  const canManage = useHasPermission("MANAGE_RESERVATIONS");
  const mutation = useUpdateReservation();
  const [values, setValues] = useState<EditFormValues>(() => initialEditValues(detail));
  const baseline = useRef(detail);
  const [submitted, setSubmitted] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<EditableField, EditValidationKey>>>({});
  useEffect(() => {
    setValues((current) => {
      const previous = initialEditValues(baseline.current);
      const next = initialEditValues(detail);
      return Object.fromEntries(EDITABLE_FIELDS.map((field) => [field, current[field] === previous[field] ? next[field] : current[field]])) as EditFormValues;
    });
    baseline.current = detail;
  }, [detail]);
  if (!canManage) return null;
  const nonManual = !["DIRECT", "MANUAL"].includes(detail.channel);
  const disabled = (field: EditableField) => nonManual && INGEST_OWNED_FIELDS.includes(field as never);
  const setField = (field: EditableField, value: string) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    setValues((current) => ({ ...current, [field]: value }));
  };
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    setSubmitted(true);
    const errors = validateEditValues(values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    const input = buildReservationPatch(detail, values);
    if (Object.keys(input).length === 0) return;
    mutation.mutate({ reservationId: detail.id, input });
  }
  return <form onSubmit={submit} noValidate className="flex flex-col gap-3" aria-label={t("edit.title")}>
    <h2 className="text-lg font-semibold">{t("edit.title")}</h2>
    {nonManual ? <p className="text-sm text-muted-foreground">{t("edit.ingestOwnedHelp")}</p> : null}
    <div className="grid gap-3 sm:grid-cols-2">
      {EDITABLE_FIELDS.map((field) => {
        const id = `reservation-edit-${field}`;
        const errorId = `${id}-error`;
        const error = fieldErrors[field];
        const common = { id, name: field, className: fieldClass, value: values[field], disabled: disabled(field), "aria-invalid": Boolean(error), "aria-describedby": error ? errorId : undefined };
        const control = field === "specialRequests" || field === "internalNotes"
          ? <textarea {...common} onChange={(event) => setField(field, event.target.value)} />
          : <input {...common} type={field.includes("Date") ? "date" : field.includes("Time") ? "time" : ["adults", "children", "grossAmount", "otaCommission", "netAmount"].includes(field) ? "number" : "text"} onChange={(event) => setField(field, event.target.value)} />;
        return <label key={field} htmlFor={id} className="flex flex-col gap-1 text-sm">{t(`edit.fields.${field}`)}{control}{error ? <span id={errorId} role="alert">{t(`edit.errors.${error}`)}</span> : null}</label>;
      })}
    </div>
    {submitted && Object.keys(fieldErrors).length > 0 ? <p role="alert">{t("edit.errors.correctFields")}</p> : null}
    {mutation.isError ? <p role="alert">{t(reservationMutationErrorKey(mutation.error, "edit"))}</p> : null}
    {submitted && mutation.isSuccess ? <p role="status">{t("edit.success")}</p> : null}
    <Button type="submit" className="tap-target" disabled={mutation.isPending} aria-busy={mutation.isPending}>{mutation.isPending ? t("edit.submitting") : t("edit.submit")}</Button>
  </form>;
}
