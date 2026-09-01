"use client";

import { useTranslation } from "react-i18next";

/**
 * The optional ETA of «Accept» and «On my way» (R3.3, design D9).
 *
 * `datetime-local` yields a naïve instant, converted at submit time with
 * `new Date(value).toISOString()` — that is, **read in the device's zone** and
 * sent with `Z`, which satisfies the backend's "must carry a timezone". Empty
 * means the body is omitted entirely.
 *
 * No "cannot be in the past" check is replicated here (R3.4): the boundary is
 * the server's `now`. A `422` is shown next to the field without losing what was
 * typed, and the property's `timezone` is displayed with the address but never
 * used to reinterpret what the technician typed — doing so would silently shift
 * the hour they just wrote. `ASSUMPTION`: the technician types the time on the
 * clock in front of them.
 */
export function TechEtaField({
  value,
  onChange,
  error,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  error?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation("tech");

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="tech-eta" className="text-sm text-muted-foreground">
        {t("eta.label")}
      </label>
      <input
        id="tech-eta"
        type="datetime-local"
        className="min-h-11 rounded-md border bg-background px-3 py-2 text-sm"
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? "tech-eta-error" : "tech-eta-help"}
        onChange={(event) => onChange(event.target.value)}
      />
      {error ? (
        <p id="tech-eta-error" role="alert" className="text-sm text-state-error-text">
          {error}
        </p>
      ) : (
        <p id="tech-eta-help" className="text-xs text-muted-foreground">
          {t("eta.help")}
        </p>
      )}
    </div>
  );
}

/**
 * The value a `datetime-local` input carries, as the instant the contract wants
 * — or `undefined` when the field is empty, which is what tells the caller to
 * omit the body entirely.
 */
export function etaToInstant(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    // Let the server refuse it rather than inventing a client-side rule: an
    // unparseable value is not one of the two validations R3.4 assigns to the
    // backend, but it is still not this component's call to reject.
    return value;
  }
  return date.toISOString();
}
