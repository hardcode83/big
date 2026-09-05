"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { UserRole } from "../dto";
import { useCreatePlatformUser } from "../hooks/use-create-platform-user";
import { mapFieldErrors } from "../lib/field-errors";
import { TemporaryPasswordReveal } from "./temporary-password-reveal";

/**
 * The four grantable roles (R4.2). `GRANTABLE_ROLES` on the backend excludes
 * `SUPER_ADMIN` for the same reason this list never offers it — this change does not
 * reopen that decision.
 */
const GRANTABLE_ROLES: readonly UserRole[] = [
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
];

/**
 * `full_name`/`email`/`phone` plus the role selector, pre-scoped to a given `tenantId`
 * (R4.1, design D6). On `201` this component switches ITSELF to `TemporaryPasswordReveal`
 * (R4.3) — matching `CreateTenantForm`'s self-contained success handling. `409` (email
 * already in use) is attributed to `email` — the only field a `409` here can concern
 * (design D5).
 */
export function CreateUserForm({ tenantId }: { tenantId: string }) {
  const { t } = useTranslation("platform");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<UserRole>("PROPERTY_MANAGER");
  const mutation = useCreatePlatformUser(tenantId);

  const fieldErrors = mutation.isError ? mapFieldErrors(mutation.error, "email") : {};
  const hasGenericError = mutation.isError && Object.keys(fieldErrors).length === 0;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ fullName, email, phone: phone || null, role });
  }

  if (mutation.isSuccess) {
    return (
      <TemporaryPasswordReveal
        temporaryPassword={mutation.data.temporaryPassword}
        userName={mutation.data.user.name}
      />
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="user-full-name" className="text-sm font-medium">
          {t("createUser.fields.fullName")}
        </label>
        <input
          id="user-full-name"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          required
        />
        {fieldErrors.full_name ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.full_name}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="user-email" className="text-sm font-medium">
          {t("createUser.fields.email")}
        </label>
        <input
          id="user-email"
          type="email"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        {fieldErrors.email ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.email}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="user-phone" className="text-sm font-medium">
          {t("createUser.fields.phone")}
        </label>
        <input
          id="user-phone"
          type="tel"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />
        {fieldErrors.phone ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.phone}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="user-role" className="text-sm font-medium">
          {t("createUser.fields.role")}
        </label>
        <select
          id="user-role"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={role}
          onChange={(event) => setRole(event.target.value as UserRole)}
        >
          {GRANTABLE_ROLES.map((grantableRole) => (
            <option key={grantableRole} value={grantableRole}>
              {t(`createUser.roles.${grantableRole}`)}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? t("createUser.submitting") : t("createUser.submit")}
      </Button>
      {hasGenericError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {t("createUser.genericError")}
        </p>
      ) : null}
    </form>
  );
}
