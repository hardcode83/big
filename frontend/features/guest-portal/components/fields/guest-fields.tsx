"use client";
import type { ChangeEventHandler, ReactNode } from "react";

type Props = { id: string; label: string; value: string; error?: string; onChange: ChangeEventHandler<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>; children?: ReactNode; as?: "input" | "textarea" | "select"; type?: string };
export function GuestField({ id, label, value, error, onChange, children, as = "input", type = "text" }: Props) {
  const describedBy = error ? `${id}-error` : undefined;
  const common = { id, name: id, value, onChange, required: true, "aria-invalid": Boolean(error), "aria-describedby": describedBy, className: "mt-1 block min-h-10 w-full rounded-md border border-input bg-background px-3 py-2" };
  return <div className="space-y-1"><label htmlFor={id} className="text-sm font-medium">{label}</label>{as === "textarea" ? <textarea {...common} rows={4} /> : as === "select" ? <select {...common}>{children}</select> : <input {...common} type={type} />}{error ? <p id={`${id}-error`} className="text-sm text-state-error-text">{error}</p> : null}</div>;
}
