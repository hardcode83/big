"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { UserDto, UserRole, UserStatus } from "../../dto";
import { useUsers } from "../../hooks/use-users";
import { UserRowActions } from "./user-row-actions";

const ROLE_OPTIONS: readonly UserRole[] = [
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
  "SUPER_ADMIN",
];

const STATUS_OPTIONS: readonly UserStatus[] = ["ACTIVE", "INACTIVE", "SUSPENDED"];

/**
 * The paginated user directory of `/settings`'s "Usuarios" section (R1.1,
 * R1.2, design D4). Owns the filters state and `useUsers(filters)`'s
 * loading/empty/error states (`steering/frontend.md`'s UI-states rule); a
 * populated page renders a table whose rows each mount `UserRowActions`
 * (design D4's row-opens-a-Sheet pattern, task 3.7) so row selection opens the
 * read-only detail (R1.3) for any role, plus the mutation controls when
 * `useHasPermission("MANAGE_USERS")` is true (task 3.7, design D5).
 *
 * i18n (section 5): every visible string goes through the `tenant-settings`
 * namespace. Role/status option values stay the raw enum (untranslated) — only
 * their rendered label is `t(...)` — so filter wiring/tests that assert on
 * `value` are unaffected by locale.
 */
export function UserList() {
  const [filters, setFilters] = useState<{ role?: UserRole; status?: UserStatus }>({});
  const query = useUsers(filters);

  return (
    <div className="flex flex-col gap-4">
      <UserListFilters value={filters} onChange={setFilters} />
      <UserListBody query={query} />
    </div>
  );
}

function UserListFilters({
  value,
  onChange,
}: {
  value: { role?: UserRole; status?: UserStatus };
  onChange: (next: { role?: UserRole; status?: UserStatus }) => void;
}) {
  const { t } = useTranslation("tenant-settings");

  return (
    <div
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface/60 p-3"
      aria-label={t("userList.filters.ariaLabel")}
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="user-filter-role" className="text-xs font-medium text-muted-foreground">
          {t("userList.filters.role")}
        </label>
        <select
          id="user-filter-role"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.role ?? ""}
          onChange={(event) => {
            const role = (event.target.value || undefined) as UserRole | undefined;
            onChange({ ...value, role });
          }}
        >
          <option value="">{t("userList.filters.allRoles")}</option>
          {ROLE_OPTIONS.map((role) => (
            <option key={role} value={role}>
              {t(`userRole.${role}`)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="user-filter-status" className="text-xs font-medium text-muted-foreground">
          {t("userList.filters.status")}
        </label>
        <select
          id="user-filter-status"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(event) => {
            const status = (event.target.value || undefined) as UserStatus | undefined;
            onChange({ ...value, status });
          }}
        >
          <option value="">{t("userList.filters.allStatuses")}</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {t(`userStatus.${status}`)}
            </option>
          ))}
        </select>
      </div>
      <button
        type="button"
        className="tap-target rounded-md border bg-background px-3 py-1 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
        onClick={() => onChange({})}
      >
        {t("userList.filters.clear")}
      </button>
    </div>
  );
}

function UserListBody({
  query,
}: {
  query: ReturnType<typeof useUsers>;
}) {
  const { t } = useTranslation("tenant-settings");

  if (query.isPending) {
    return <LoadingState label={t("userList.loading")} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title={t("userList.error.title")}
        description={t("userList.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={t("userList.error.retry")}
      />
    );
  }

  const page = query.data;

  if (page.data.length === 0) {
    return (
      <EmptyState
        title={t("userList.empty.title")}
        description={t("userList.empty.description")}
      />
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">{t("userList.table.caption")}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {t("userList.table.name")}
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {t("userList.table.email")}
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {t("userList.table.role")}
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {t("userList.table.status")}
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                <span className="sr-only">{t("userList.table.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {page.data.map((user) => (
              <UserRow key={user.id} user={user} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UserRow({ user }: { user: UserDto }) {
  const { t } = useTranslation("tenant-settings");

  return (
    <tr className="border-b border-border last:border-b-0 hover:bg-accent/50">
      <td className="px-4 py-3">{user.name}</td>
      <td className="px-4 py-3">{user.email}</td>
      <td className="px-4 py-3">
        <Badge variant="outline">{t(`userRole.${user.role}`)}</Badge>
      </td>
      <td className="px-4 py-3">
        <Badge variant="outline">{t(`userStatus.${user.status}`)}</Badge>
      </td>
      <td className="px-4 py-3 text-right">
        <UserRowActions user={user} />
      </td>
    </tr>
  );
}
