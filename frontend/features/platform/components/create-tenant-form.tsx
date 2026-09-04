"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { TenantSummaryDto } from "../dto";
import { useCreateTenant } from "../hooks/use-create-tenant";
import { mapFieldErrors } from "../lib/field-errors";

/**
 * The five `CreateTenantRequest` fields as plain controlled inputs (R3.1, design D8 — no
 * form library, matching `ConversationReplyForm`'s hand-rolled convention). On `201` this
 * component switches ITSELF, in place, to a success view with an "add staff" button
 * (R3.2) — the Sheet hosting it never changes which child it renders; only the button
 * click tells the parent to swap the Sheet to `CreateUserForm` (design D6).
 *
 * `409` (duplicate name) is attributed to `name` — the only field a `409` here can
 * concern (design D5). No `status` field: a tenant is born `ACTIVE` always (R3.4).
 */
export function CreateTenantForm({
  onAddStaff,
}: {
  onAddStaff: (tenant: TenantSummaryDto) => void;
}) {
  const { t } = useTranslation("platform");
  const [name, setName] = useState("");
  const [billingEmail, setBillingEmail] = useState("");
  const [country, setCountry] = useState("ES");
  const [timezone, setTimezone] = useState("Europe/Madrid");
  const [defaultLanguage, setDefaultLanguage] = useState<"es" | "en">("es");
  const mutation = useCreateTenant();

  const fieldErrors = mutation.isError ? mapFieldErrors(mutation.error, "name") : {};
  const hasGenericError = mutation.isError && Object.keys(fieldErrors).length === 0;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ name, billingEmail, country, timezone, defaultLanguage });
  }

  if (mutation.isSuccess) {
    const tenant = mutation.data;
    return (
      <div className="flex flex-col gap-4">
        <p role="status">{t("createTenant.success", { name: tenant.name })}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("list.columns.name")}</dt>
          <dd>{tenant.name}</dd>
          <dt className="text-muted-foreground">{t("list.columns.status")}</dt>
          <dd>{t(`status.${tenant.status}`)}</dd>
        </dl>
        <Button type="button" onClick={() => onAddStaff(tenant)}>
          {t("createTenant.addStaff")}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-name" className="text-sm font-medium">
          {t("createTenant.fields.name")}
        </label>
        <input
          id="tenant-name"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        {fieldErrors.name ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.name}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-billing-email" className="text-sm font-medium">
          {t("createTenant.fields.billingEmail")}
        </label>
        <input
          id="tenant-billing-email"
          type="email"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={billingEmail}
          onChange={(event) => setBillingEmail(event.target.value)}
          required
        />
        {fieldErrors.billing_email ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.billing_email}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-country" className="text-sm font-medium">
          {t("createTenant.fields.country")}
        </label>
        <input
          id="tenant-country"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={country}
          maxLength={2}
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
          required
        />
        {fieldErrors.country ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.country}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-timezone" className="text-sm font-medium">
          {t("createTenant.fields.timezone")}
        </label>
        <input
          id="tenant-timezone"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          required
        />
        {fieldErrors.timezone ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.timezone}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="tenant-default-language" className="text-sm font-medium">
          {t("createTenant.fields.defaultLanguage")}
        </label>
        <select
          id="tenant-default-language"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={defaultLanguage}
          onChange={(event) => setDefaultLanguage(event.target.value as "es" | "en")}
        >
          <option value="es">{t("createTenant.fields.languageOptions.es")}</option>
          <option value="en">{t("createTenant.fields.languageOptions.en")}</option>
        </select>
      </div>
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? t("createTenant.submitting") : t("createTenant.submit")}
      </Button>
      {hasGenericError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {t("createTenant.genericError")}
        </p>
      ) : null}
    </form>
  );
}
