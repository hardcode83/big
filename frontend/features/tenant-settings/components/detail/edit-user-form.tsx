"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { mapFieldErrors } from "@/features/platform";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import type { UserDto, UserRole, UserStatus } from "../../dto";
import { useUpdateUser } from "../../hooks/use-update-user";
import { useUser } from "../../hooks/use-user";

const ROLE_OPTIONS: readonly UserRole[] = [
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
];

const STATUS_OPTIONS: readonly UserStatus[] = ["ACTIVE", "INACTIVE", "SUSPENDED"];

/**
 * Profile/role/status edits via `use-update-user` (R3.1), built on `use-user`
 * the same way `user-detail-view.tsx` (task 3.2) is — a mutation layer "on
 * top of" that read, not a copy of it. Only rendered by the caller
 * (`user-row-actions.tsx`) when `useHasPermission("MANAGE_USERS")` is true
 * (design D5); this component does not re-check the permission itself.
 *
 * Sends only the fields that actually changed (R3.1) — computed against the
 * fetched `UserDto`, never a hardcoded initial-state snapshot.
 *
 * R3.3: when the target row is the acting user's own
 * (`sessionUser.id === user.id`), the role and status controls are disabled
 * in the client (defense in depth; the backend already answers `422` —
 * `SelfRoleChangeError`).
 *
 * R3.2: a `422` from the backend (last-owner / self-action) is surfaced via
 * `mapFieldErrors`. Those two domain errors carry no `details.errors` array
 * (no `loc`), so `mapFieldErrors` resolves to `{}` for them — in that case
 * this form falls back to the ApiError's own `message` (the backend's real
 * reason) instead of inventing a generic "something went wrong" string,
 * which is what "no generic fallback message" means here.
 *
 * i18n (section 5): the `tenant-settings` namespace. `genericMessage` is the
 * backend's own message text (never translated — it is not a static UI
 * string), same as before.
 */
export function EditUserForm({
  userId,
  onSuccess,
}: {
  userId: string;
  onSuccess?: () => void;
}) {
  const { t } = useTranslation("tenant-settings");
  const query = useUser(userId);

  if (query.isPending) {
    return <LoadingState label={t("editUser.loading")} />;
  }

  if (query.isError || !query.data) {
    return (
      <ErrorState
        title={t("editUser.error.title")}
        description={t("editUser.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={t("editUser.error.retry")}
      />
    );
  }

  // A fresh `EditUserFormBody` per fetched `user` (keyed on its id): its own
  // `useState` initializers read straight from `user` on mount, with no
  // `useEffect`-driven sync — the row's `Sheet` unmounts this tree on close
  // anyway (`user-row-actions.tsx`), so there is no case where the same
  // instance must pick up a later refetch of a DIFFERENT user.
  return <EditUserFormBody key={query.data.id} user={query.data} onSuccess={onSuccess} />;
}

function EditUserFormBody({
  user,
  onSuccess,
}: {
  user: UserDto;
  onSuccess?: () => void;
}) {
  const { t } = useTranslation("tenant-settings");
  const { user: sessionUser } = useAuth();
  const mutation = useUpdateUser();

  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [role, setRole] = useState<UserRole>(user.role);
  const [status, setStatus] = useState<UserStatus>(user.status);

  const isSelf = sessionUser?.id === user.id;

  const fieldErrors = mutation.isError ? mapFieldErrors(mutation.error) : {};
  const genericMessage =
    mutation.isError &&
    Object.keys(fieldErrors).length === 0 &&
    mutation.error instanceof ApiError
      ? mutation.error.message
      : null;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const input: {
      name?: string;
      email?: string;
      phone?: string | null;
      role?: UserRole;
      status?: UserStatus;
    } = {};
    if (name !== user.name) input.name = name;
    if (email !== user.email) input.email = email;
    const normalizedPhone = phone || null;
    if (normalizedPhone !== user.phone) input.phone = normalizedPhone;
    if (!isSelf && role !== user.role) input.role = role;
    if (!isSelf && status !== user.status) input.status = status;

    if (Object.keys(input).length === 0) {
      return;
    }

    mutation.mutate(
      { userId: user.id, input },
      { onSuccess: () => onSuccess?.() },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="edit-user-name" className="text-sm font-medium">
          {t("editUser.fields.fullName")}
        </label>
        <input
          id="edit-user-name"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
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
        <label htmlFor="edit-user-email" className="text-sm font-medium">
          {t("editUser.fields.email")}
        </label>
        <input
          id="edit-user-email"
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
        <label htmlFor="edit-user-phone" className="text-sm font-medium">
          {t("editUser.fields.phone")}
        </label>
        <input
          id="edit-user-phone"
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
        <label htmlFor="edit-user-role" className="text-sm font-medium">
          {t("editUser.fields.role")}
        </label>
        <select
          id="edit-user-role"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={role}
          disabled={isSelf}
          onChange={(event) => setRole(event.target.value as UserRole)}
        >
          {ROLE_OPTIONS.map((roleOption) => (
            <option key={roleOption} value={roleOption}>
              {t(`userRole.${roleOption}`)}
            </option>
          ))}
        </select>
        {fieldErrors.role ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.role}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="edit-user-status" className="text-sm font-medium">
          {t("editUser.fields.status")}
        </label>
        <select
          id="edit-user-status"
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={status}
          disabled={isSelf}
          onChange={(event) => setStatus(event.target.value as UserStatus)}
        >
          {STATUS_OPTIONS.map((statusOption) => (
            <option key={statusOption} value={statusOption}>
              {t(`userStatus.${statusOption}`)}
            </option>
          ))}
        </select>
        {fieldErrors.status ? (
          <p role="alert" className="text-sm text-state-error-text">
            {fieldErrors.status}
          </p>
        ) : null}
      </div>
      {isSelf ? (
        <p role="note" className="text-xs text-muted-foreground">
          {t("editUser.selfNote")}
        </p>
      ) : null}
      <Button type="submit" className="tap-target" disabled={mutation.isPending}>
        {mutation.isPending ? t("editUser.submitting") : t("editUser.submit")}
      </Button>
      {genericMessage ? (
        <p role="alert" className="text-sm text-state-error-text">
          {genericMessage}
        </p>
      ) : null}
    </form>
  );
}
