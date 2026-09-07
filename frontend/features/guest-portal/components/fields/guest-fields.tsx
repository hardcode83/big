"use client";
import type { ChangeEventHandler, ReactNode } from "react";

/**
 * The guest portal's one form-control pattern (design D9): the same
 * input/label styling `reservations-filters.tsx`'s controls established for
 * this change, reused here rather than invented a second time. Every
 * `<form>` in `guest-portal-view.tsx` (check-in, incident, conversation)
 * shares this single component, so restyling it here restyles all three.
 */
type Props = { id: string; label: string; value: string; error?: string; onChange: ChangeEventHandler<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>; children?: ReactNode; as?: "input" | "textarea" | "select"; type?: string };
export function GuestField({ id, label, value, error, onChange, children, as = "input", type = "text" }: Props) {
  const describedBy = error ? `${id}-error` : undefined;
  const common = { id, name: id, value, onChange, required: true, "aria-invalid": Boolean(error), "aria-describedby": describedBy, className: "tap-target block w-full rounded-md border bg-background px-3 py-2 text-sm" };
  return <div className="space-y-1"><label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">{label}</label>{as === "textarea" ? <textarea {...common} rows={4} /> : as === "select" ? <select {...common}>{children}</select> : <input {...common} type={type} />}{error ? <p id={`${id}-error`} className="text-body-base text-state-error-text">{error}</p> : null}</div>;
}
