"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { mapFieldErrors, TemporaryPasswordReveal } from "@/features/platform";

import type { UserRole } from "../../dto";
import { useCreateUser } from "../../hooks/use-create-user";

/**
 * The four grantable roles (`GRANTABLE_ROLES` minus `SUPER_ADMIN`), mirroring
 * `features/platform/components/create-user-form.tsx`'s own list — this
 * change does not reopen why `SUPER_ADMIN` is excluded there.
 */
const GRANTABLE_ROLES: readonly UserRole[] = [
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
];

/**
 * `full_name`/email/phone/role fields for `POST /api/v1/users` (R2.1). Only
 * rendered by its caller (`user-list.tsx`/`tenant-settings-view.tsx`, section
 * 5) when `useHasPermission("MANAGE_USERS")` is true (design D5) — this
 * component itself does not re-check the permission, same as
 * `platform`'s `CreateUserForm`.
 *
 * On `201` this component switches itself to `TemporaryPasswordReveal` (R2.1)
 * — the reused component from `@/features/platform`. `409` (email already in
 * use) is attributed to `email` via `mapFieldErrors(error, "email")` (R2.2) —
 * the only field a `409` here can concern.
 *
 * i18n (section 5): the `tenant-settings` namespace. Role option values stay
 * the raw enum; only the rendered label is translated.
 */
export function CreateUserForm() {
  const { t } = useTranslation("tenant-settings");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<UserRole>("PROPERTY_MANAGER");
  const mutation = useCreateUser();

  const fieldErrors = mutation.isError ? mapFieldErrors(mutation.error, "email") : {};
  const hasGenericError = mutation.isError && Object.keys(fieldErrors).length === 0;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ name: fullName, email, phone: phone || null, role });
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
        <label htmlFor="new-user-full-name" className="text-sm font-medium">
          {t("createUser.fields.fullName")}
        </label>
        <input
          id="new-user-full-name"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          required
        />
        {fieldErrors.name ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.name}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new-user-email" className="text-sm font-medium">
          {t("createUser.fields.email")}
        </label>
        <input
          id="new-user-email"
          type="email"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
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
        <label htmlFor="new-user-phone" className="text-sm font-medium">
          {t("createUser.fields.phone")}
        </label>
        <input
          id="new-user-phone"
          type="tel"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
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
        <label htmlFor="new-user-role" className="text-sm font-medium">
          {t("createUser.fields.role")}
        </label>
        <select
          id="new-user-role"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={role}
          onChange={(event) => setRole(event.target.value as UserRole)}
        >
          {GRANTABLE_ROLES.map((grantableRole) => (
            <option key={grantableRole} value={grantableRole}>
              {t(`userRole.${grantableRole}`)}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" className="tap-target" disabled={mutation.isPending}>
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
