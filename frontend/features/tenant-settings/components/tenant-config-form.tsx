"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { mapFieldErrors } from "@/features/platform";
import { ApiError } from "@/lib/api";
import { useHasPermission } from "@/lib/auth";

import type { TenantDto, UpdateTenantInput } from "../dto";
import { useTenant } from "../hooks/use-tenant";
import { useUpdateTenant } from "../hooks/use-update-tenant";
import {
  validateTenantConfig,
  type TenantConfigValidationInput,
} from "../lib/validate-tenant-config";

/** Mirrors the backend's `SUPPORTED_LANGUAGES` (`tenants/domain/value_objects.py`). */
const LANGUAGE_OPTIONS = ["es", "en"] as const;

const TENANT_FIELDS = [
  "name",
  "billingEmail",
  "country",
  "timezone",
  "defaultLanguage",
] as const;

const CONFIG_FIELDS = [
  "ownerApprovalThresholdEur",
  "aiConfidenceThreshold",
  "slaCriticalMinutes",
  "slaHighMinutes",
  "slaMediumMinutes",
  "slaLowMinutes",
  "checkinWindowHoursBefore",
  "checkoutReadyHoursAfter",
  "autoCreateCleaningTask",
  "cleaningPhotoRequired",
  "notificationEmailEnabled",
  "notificationWhatsappEnabled",
  "reviewRecurringIssuesTopN",
] as const;

interface EditableValues {
  name: string;
  billingEmail: string;
  country: string;
  timezone: string;
  defaultLanguage: string;
  ownerApprovalThresholdEur: string;
  aiConfidenceThreshold: string;
  slaCriticalMinutes: number;
  slaHighMinutes: number;
  slaMediumMinutes: number;
  slaLowMinutes: number;
  checkinWindowHoursBefore: number;
  checkoutReadyHoursAfter: number;
  autoCreateCleaningTask: boolean;
  cleaningPhotoRequired: boolean;
  notificationEmailEnabled: boolean;
  notificationWhatsappEnabled: boolean;
  reviewRecurringIssuesTopN: number;
}

function toEditableValues(tenant: TenantDto): EditableValues {
  return {
    name: tenant.name,
    billingEmail: tenant.billingEmail,
    country: tenant.country,
    timezone: tenant.timezone,
    defaultLanguage: tenant.defaultLanguage,
    ownerApprovalThresholdEur: tenant.config.ownerApprovalThresholdEur,
    aiConfidenceThreshold: tenant.config.aiConfidenceThreshold,
    slaCriticalMinutes: tenant.config.slaCriticalMinutes,
    slaHighMinutes: tenant.config.slaHighMinutes,
    slaMediumMinutes: tenant.config.slaMediumMinutes,
    slaLowMinutes: tenant.config.slaLowMinutes,
    checkinWindowHoursBefore: tenant.config.checkinWindowHoursBefore,
    checkoutReadyHoursAfter: tenant.config.checkoutReadyHoursAfter,
    autoCreateCleaningTask: tenant.config.autoCreateCleaningTask,
    cleaningPhotoRequired: tenant.config.cleaningPhotoRequired,
    notificationEmailEnabled: tenant.config.notificationEmailEnabled,
    notificationWhatsappEnabled: tenant.config.notificationWhatsappEnabled,
    reviewRecurringIssuesTopN: tenant.config.reviewRecurringIssuesTopN,
  };
}

function diff<T extends object>(
  current: T,
  base: T,
  fields: readonly (keyof T)[],
): Partial<T> {
  const result: Partial<T> = {};
  for (const field of fields) {
    if (current[field] !== base[field]) {
      result[field] = current[field];
    }
  }
  return result;
}

/**
 * Tenant + `TenantConfig` section of `/settings` (R5). Outer component owns
 * `use-tenant`'s loading/error states (mirrors `edit-user-form.tsx`'s outer/
 * inner split); a fresh body keyed on the fetched `tenant.id` reads its own
 * `useState` initializers straight off the fetched `TenantDto` with no
 * `useEffect` sync — same `react-hooks/set-state-in-effect` gotcha
 * `edit-user-form.tsx` documents.
 *
 * `useHasPermission("MANAGE_TENANT_SETTINGS")` picks the branch (design D5):
 * `false` renders every field read-only with NO submit control at all (not
 * rendered-and-disabled, an absent branch); `true` renders the editable form.
 *
 * `storageType` has no input anywhere (read-only display even in the
 * editable branch): `TenantConfigPatch` does not accept it (R5 "Out of
 * scope" — switching storage backends is `cleaning`'s data-migration
 * problem, not this form's).
 *
 * Plain English literals (section 4 scope note, mirrors section 3's): i18n
 * lands in tasks.md section 5, not here.
 */
export function TenantConfigForm() {
  const query = useTenant();
  const canManage = useHasPermission("MANAGE_TENANT_SETTINGS");

  if (query.isPending) {
    return <LoadingState label="Loading tenant settings…" />;
  }

  if (query.isError || !query.data) {
    return (
      <ErrorState
        title="Couldn't load tenant settings"
        description="Something went wrong while loading the tenant configuration."
        onRetry={() => void query.refetch()}
        retryLabel="Retry"
      />
    );
  }

  return canManage ? (
    <TenantConfigFormBody key={query.data.id} tenant={query.data} />
  ) : (
    <TenantConfigReadOnly key={query.data.id} tenant={query.data} />
  );
}

/**
 * R5.2: `PROPERTY_MANAGER` (and anyone else `MANAGE_TENANT_SETTINGS` is
 * `false` for) sees every field, no inputs, no submit control.
 */
function TenantConfigReadOnly({ tenant }: { tenant: TenantDto }) {
  return (
    <dl className="flex flex-col gap-3" aria-label="Tenant settings (read-only)">
      <DetailRow label="Name" value={tenant.name} />
      <DetailRow label="Billing email" value={tenant.billingEmail} />
      <DetailRow label="Country" value={tenant.country} />
      <DetailRow label="Time zone" value={tenant.timezone} />
      <DetailRow label="Default language" value={tenant.defaultLanguage} />
      <DetailRow
        label="Owner approval threshold (EUR)"
        value={tenant.config.ownerApprovalThresholdEur}
      />
      <DetailRow label="AI confidence threshold" value={tenant.config.aiConfidenceThreshold} />
      <DetailRow label="SLA — critical (minutes)" value={String(tenant.config.slaCriticalMinutes)} />
      <DetailRow label="SLA — high (minutes)" value={String(tenant.config.slaHighMinutes)} />
      <DetailRow label="SLA — medium (minutes)" value={String(tenant.config.slaMediumMinutes)} />
      <DetailRow label="SLA — low (minutes)" value={String(tenant.config.slaLowMinutes)} />
      <DetailRow
        label="Check-in window (hours before)"
        value={String(tenant.config.checkinWindowHoursBefore)}
      />
      <DetailRow
        label="Checkout-ready window (hours after)"
        value={String(tenant.config.checkoutReadyHoursAfter)}
      />
      <DetailRow
        label="Auto-create cleaning task"
        value={tenant.config.autoCreateCleaningTask ? "Enabled" : "Disabled"}
      />
      <DetailRow
        label="Cleaning photo required"
        value={tenant.config.cleaningPhotoRequired ? "Enabled" : "Disabled"}
      />
      <DetailRow label="Storage type" value={tenant.config.storageType} />
      <DetailRow
        label="Email notifications"
        value={tenant.config.notificationEmailEnabled ? "Enabled" : "Disabled"}
      />
      <DetailRow
        label="WhatsApp notifications"
        value={tenant.config.notificationWhatsappEnabled ? "Enabled" : "Disabled"}
      />
      <DetailRow
        label="Recurring issues shown"
        value={String(tenant.config.reviewRecurringIssuesTopN)}
      />
    </dl>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{value}</dd>
    </div>
  );
}

function TenantConfigFormBody({ tenant }: { tenant: TenantDto }) {
  const mutation = useUpdateTenant();
  const [values, setValues] = useState<EditableValues>(() => toEditableValues(tenant));
  const [baseline, setBaseline] = useState<EditableValues>(() => toEditableValues(tenant));
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const backendErrors = mutation.isError ? mapFieldErrors(mutation.error) : {};
  const genericMessage =
    mutation.isError &&
    Object.keys(backendErrors).length === 0 &&
    mutation.error instanceof ApiError
      ? mutation.error.message
      : null;

  // Client-validation errors (keyed camelCase, this form's own naming) take
  // priority over a backend error surfaced under the SAME submission for the
  // same field; the two sources use different key conventions on purpose —
  // `validateTenantConfig` returns the DTO's camelCase names, while
  // `mapFieldErrors` returns whatever `loc`'s last segment names on the wire
  // (the backend's snake_case request-body field, e.g.
  // `owner_approval_threshold_eur`), so each inline error reads from both by
  // its own two names rather than one shared key.
  function errorFor(clientKey: string, backendKey: string): string | null {
    return clientErrors[clientKey] ?? backendErrors[backendKey] ?? null;
  }

  function set<K extends keyof EditableValues>(key: K, value: EditableValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Both `Partial<EditableValues>` — narrower (non-nullable) than
    // `UpdateTenantInput`/`UpdateTenantConfigInput`'s own field types, so
    // they widen implicitly (no cast needed) at the two points below that
    // actually build the API payload; kept in this narrower shape here so
    // `validationInput` and `setBaseline` never have to think about `null`.
    const tenantChanges = diff(values, baseline, TENANT_FIELDS);
    const configChanges = diff(values, baseline, CONFIG_FIELDS);

    const validationInput: TenantConfigValidationInput = {};
    if (tenantChanges.timezone !== undefined) {
      validationInput.timezone = tenantChanges.timezone;
    }
    if (configChanges.ownerApprovalThresholdEur !== undefined) {
      validationInput.ownerApprovalThresholdEur = configChanges.ownerApprovalThresholdEur;
    }
    if (configChanges.aiConfidenceThreshold !== undefined) {
      validationInput.aiConfidenceThreshold = configChanges.aiConfidenceThreshold;
    }
    if (configChanges.slaCriticalMinutes !== undefined) {
      validationInput.slaCriticalMinutes = configChanges.slaCriticalMinutes;
    }
    if (configChanges.slaHighMinutes !== undefined) {
      validationInput.slaHighMinutes = configChanges.slaHighMinutes;
    }
    if (configChanges.slaMediumMinutes !== undefined) {
      validationInput.slaMediumMinutes = configChanges.slaMediumMinutes;
    }
    if (configChanges.slaLowMinutes !== undefined) {
      validationInput.slaLowMinutes = configChanges.slaLowMinutes;
    }

    const validationErrors = validateTenantConfig(validationInput);
    setClientErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      // R5.3: rejected in the client — no request is sent for a value that
      // would be a doomed 422 on the same range the backend enforces.
      return;
    }

    if (Object.keys(tenantChanges).length === 0 && Object.keys(configChanges).length === 0) {
      return;
    }

    const input: UpdateTenantInput = { ...tenantChanges };
    if (Object.keys(configChanges).length > 0) {
      input.config = configChanges;
    }

    mutation.mutate(input, {
      onSuccess: () => {
        setBaseline((prev) => ({ ...prev, ...tenantChanges, ...configChanges }));
      },
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-name" className="text-sm font-medium">
          Name
        </label>
        <input
          id="tenant-name"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.name}
          onChange={(event) => set("name", event.target.value)}
          required
        />
        {errorFor("name", "name") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("name", "name")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-billing-email" className="text-sm font-medium">
          Billing email
        </label>
        <input
          id="tenant-billing-email"
          type="email"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.billingEmail}
          onChange={(event) => set("billingEmail", event.target.value)}
          required
        />
        {errorFor("billingEmail", "billing_email") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("billingEmail", "billing_email")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-country" className="text-sm font-medium">
          Country
        </label>
        <input
          id="tenant-country"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.country}
          onChange={(event) => set("country", event.target.value)}
          required
        />
        {errorFor("country", "country") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("country", "country")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-timezone" className="text-sm font-medium">
          Time zone
        </label>
        <input
          id="tenant-timezone"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.timezone}
          onChange={(event) => set("timezone", event.target.value)}
          required
        />
        {errorFor("timezone", "timezone") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("timezone", "timezone")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-default-language" className="text-sm font-medium">
          Default language
        </label>
        <select
          id="tenant-default-language"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.defaultLanguage}
          onChange={(event) => set("defaultLanguage", event.target.value)}
        >
          {LANGUAGE_OPTIONS.map((language) => (
            <option key={language} value={language}>
              {language}
            </option>
          ))}
        </select>
        {/* R5.4 */}
        <p role="note" className="text-xs text-muted-foreground">
          Changing this does not affect the preferred language already set on existing users.
        </p>
        {errorFor("defaultLanguage", "default_language") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("defaultLanguage", "default_language")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-owner-approval-threshold" className="text-sm font-medium">
          Owner approval threshold (EUR)
        </label>
        <input
          id="tenant-owner-approval-threshold"
          type="text"
          inputMode="decimal"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.ownerApprovalThresholdEur}
          onChange={(event) => set("ownerApprovalThresholdEur", event.target.value)}
          required
        />
        {/* R5.5 */}
        <p role="note" className="text-xs text-muted-foreground">
          Changing this does not re-evaluate owner approvals already generated.
        </p>
        {errorFor("ownerApprovalThresholdEur", "owner_approval_threshold_eur") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("ownerApprovalThresholdEur", "owner_approval_threshold_eur")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-ai-confidence-threshold" className="text-sm font-medium">
          AI confidence threshold
        </label>
        <input
          id="tenant-ai-confidence-threshold"
          type="text"
          inputMode="decimal"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.aiConfidenceThreshold}
          onChange={(event) => set("aiConfidenceThreshold", event.target.value)}
          required
        />
        {errorFor("aiConfidenceThreshold", "ai_confidence_threshold") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("aiConfidenceThreshold", "ai_confidence_threshold")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-sla-critical" className="text-sm font-medium">
          SLA — critical (minutes)
        </label>
        <input
          id="tenant-sla-critical"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.slaCriticalMinutes}
          onChange={(event) => set("slaCriticalMinutes", Number(event.target.value))}
          required
        />
        {errorFor("slaCriticalMinutes", "sla_critical_minutes") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("slaCriticalMinutes", "sla_critical_minutes")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-sla-high" className="text-sm font-medium">
          SLA — high (minutes)
        </label>
        <input
          id="tenant-sla-high"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.slaHighMinutes}
          onChange={(event) => set("slaHighMinutes", Number(event.target.value))}
          required
        />
        {errorFor("slaHighMinutes", "sla_high_minutes") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("slaHighMinutes", "sla_high_minutes")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-sla-medium" className="text-sm font-medium">
          SLA — medium (minutes)
        </label>
        <input
          id="tenant-sla-medium"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.slaMediumMinutes}
          onChange={(event) => set("slaMediumMinutes", Number(event.target.value))}
          required
        />
        {errorFor("slaMediumMinutes", "sla_medium_minutes") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("slaMediumMinutes", "sla_medium_minutes")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-sla-low" className="text-sm font-medium">
          SLA — low (minutes)
        </label>
        <input
          id="tenant-sla-low"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.slaLowMinutes}
          onChange={(event) => set("slaLowMinutes", Number(event.target.value))}
          required
        />
        {errorFor("slaLowMinutes", "sla_low_minutes") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("slaLowMinutes", "sla_low_minutes")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-checkin-window" className="text-sm font-medium">
          Check-in window (hours before)
        </label>
        <input
          id="tenant-checkin-window"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.checkinWindowHoursBefore}
          onChange={(event) => set("checkinWindowHoursBefore", Number(event.target.value))}
          required
        />
        {errorFor("checkinWindowHoursBefore", "checkin_window_hours_before") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("checkinWindowHoursBefore", "checkin_window_hours_before")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-checkout-window" className="text-sm font-medium">
          Checkout-ready window (hours after)
        </label>
        <input
          id="tenant-checkout-window"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.checkoutReadyHoursAfter}
          onChange={(event) => set("checkoutReadyHoursAfter", Number(event.target.value))}
          required
        />
        {errorFor("checkoutReadyHoursAfter", "checkout_ready_hours_after") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("checkoutReadyHoursAfter", "checkout_ready_hours_after")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-review-top-n" className="text-sm font-medium">
          Recurring issues shown
        </label>
        <input
          id="tenant-review-top-n"
          type="number"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={values.reviewRecurringIssuesTopN}
          onChange={(event) => set("reviewRecurringIssuesTopN", Number(event.target.value))}
          required
        />
        {errorFor("reviewRecurringIssuesTopN", "review_recurring_issues_top_n") ? (
          <p role="alert" className="text-sm text-state-error-text">
            {errorFor("reviewRecurringIssuesTopN", "review_recurring_issues_top_n")}
          </p>
        ) : null}
      </div>

      <label htmlFor="tenant-auto-create-cleaning-task" className="tap-target flex items-center gap-2 text-sm">
        <input
          id="tenant-auto-create-cleaning-task"
          type="checkbox"
          className="h-5 w-5 rounded border"
          checked={values.autoCreateCleaningTask}
          onChange={(event) => set("autoCreateCleaningTask", event.target.checked)}
        />
        Auto-create cleaning task after checkout
      </label>

      <label htmlFor="tenant-cleaning-photo-required" className="tap-target flex items-center gap-2 text-sm">
        <input
          id="tenant-cleaning-photo-required"
          type="checkbox"
          className="h-5 w-5 rounded border"
          checked={values.cleaningPhotoRequired}
          onChange={(event) => set("cleaningPhotoRequired", event.target.checked)}
        />
        Require a cleaning photo
      </label>

      <label htmlFor="tenant-notification-email" className="tap-target flex items-center gap-2 text-sm">
        <input
          id="tenant-notification-email"
          type="checkbox"
          className="h-5 w-5 rounded border"
          checked={values.notificationEmailEnabled}
          onChange={(event) => set("notificationEmailEnabled", event.target.checked)}
        />
        Email notifications
      </label>

      <label htmlFor="tenant-notification-whatsapp" className="tap-target flex items-center gap-2 text-sm">
        <input
          id="tenant-notification-whatsapp"
          type="checkbox"
          className="h-5 w-5 rounded border"
          checked={values.notificationWhatsappEnabled}
          onChange={(event) => set("notificationWhatsappEnabled", event.target.checked)}
        />
        WhatsApp notifications
      </label>

      {/* `storage_type` has no control anywhere in this form — read-only display only. */}
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium text-muted-foreground">Storage type</span>
        <span className="text-sm text-foreground">{tenant.config.storageType}</span>
      </div>

      <Button type="submit" className="tap-target" disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save changes"}
      </Button>

      {mutation.isSuccess ? (
        <p role="status" className="text-sm text-muted-foreground">
          Tenant settings updated.
        </p>
      ) : null}

      {genericMessage ? (
        <p role="alert" className="text-sm text-state-error-text">
          {genericMessage}
        </p>
      ) : null}
    </form>
  );
}
